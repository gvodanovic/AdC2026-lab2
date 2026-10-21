# Componentes del sistema que simula se.py.
#
# La primera parte es el modelo de CVA6 (cv64a6_imafdc_sv39_hpdcache_wb) sobre
# el MinorCPU de gem5, copiado sin cambios de gem5_config_CVA6_patch.py, la
# configuracion calibrada contra el RTL de CVA6. Necesita el gem5 con
# MinorCPU_CVA6.patch (build/RISCV_PATCH). Sus constantes CLK_FREQ, L1I_SIZE
# y L1D_SIZE son los valores del CVA6 real y no se usan: la frecuencia sale de
# cpu_config.toml y las caches de cada archivo de procesador.
#
# La segunda parte, al final, arma los procesadores del laboratorio con ese
# modelo y con un O3CPU generico.
#
# No modificar este archivo: lo que se puede cambiar esta en cpu_config.toml y
# en los archivos de procesador (in_order.py, out_of_order.py, ...).

import os

from m5.params import NULL  # type: ignore
from gem5.components.boards.simple_board import SimpleBoard  # type: ignore
from gem5.components.processors.base_cpu_core import (  # type: ignore
    BaseCPUCore,
)
from gem5.components.processors.base_cpu_processor import (  # type: ignore
    BaseCPUProcessor,
)
from gem5.components.memory.simple import (  # type: ignore
    SingleChannelSimpleMemory,
)
from gem5.components.memory.single_channel import (  # type: ignore
    SingleChannelDDR3_1600,
)
from gem5.components.memory.memory import ChanneledMemory  # type: ignore
from gem5.components.cachehierarchies.classic.private_l1_cache_hierarchy import (  # type: ignore
    PrivateL1CacheHierarchy,
)
from gem5.isas import ISA  # type: ignore
from gem5.simulate.simulator import Simulator  # type: ignore
from gem5.resources.resource import BinaryResource  # type: ignore

from m5.objects import (  # type: ignore
    Axi2MemPort,
    DDR3_1600_8x8,
    CVA6IcacheRandomRP,
    HPDcacheRandomRP,
    LocalBP,
    LRURP,
    TreePLRURP,
    RandomRP,
    MinorFUPool,
    MinorDefaultFloatSimdFU,
    MinorDefaultPredFU,
    MinorDefaultMiscFU,
    MinorFU,
    MinorFUTiming,
    MinorOpClassSet,
    MinorOpClass,
    ReturnAddrStack,
    RiscvMinorCPU,
    SimpleBTB,
    TimingExprLiteral,
    TimingExprSrcReg,
    TimingExprUn,
    TimingExprBin,
    TimingExprIf,
    TimingExprLet,
    TimingExprRef,
)

# gem5 MinorCPU configuration matched to CVA6 (cv64a6_imafdc_sv39_hpdcache_wb).
# Every value is either derived from a CVA6 RTL localparam or is a gem5-side
# estimate where CVA6 has no clean counterpart.
#
# The production configuration. Every transcribed mechanism is on by default
# and each has a --no- switch that turns it off, so this doubles as its own
# ablation harness. The README lists what each switch does.
#
# It needs the patched build even with --no-patch, for its imports and the
# patch parameters it sets. gem5_config_CVA6.py is the stock-gem5 version.

CLK_FREQ = "50MHz"
L1I_SIZE = "16KiB"
L1D_SIZE = "32KiB"

# Cycles a load waits after a store collision clears, the CVA6 LSU re-request.
# Every colliding load of the suite measures one cycle longer than 2 allows.
STORE_COLLISION_REPLAY_DELAY = 3

# Class extras on the dirty-victim readout window, the additive law's
# x and z terms (hpdcache_rtab.sv POP_TRY, hpdcache_flush.sv).
VICTIM_READOUT_STORE_EXTRA = 4
VICTIM_READOUT_FIRST_LOAD_EXTRA = 1

# Miss-latency split, L1D only. L1D_FILL_DELAY is the flat split used when the
# window mechanism is off. Under the window the fill delay is 0, because it
# charges the trigger's own fill and a flat delay would double-charge.
MEM_LATENCY = "0ns"
L1D_FILL_DELAY = 2
L1D_RESPONSE_LATENCY = 2
FROZEN_L1D_FILL_DELAY = 0
FROZEN_L1D_RESPONSE_LATENCY = 4


def _lit(value):
    # The literal is a UInt64, so a negative bound goes in as its two's
    # complement, which the signed comparisons read back.
    e = TimingExprLiteral()
    e.value = value & 0xFFFFFFFFFFFFFFFF
    return e


def _src(index):
    e = TimingExprSrcReg()
    e.index = index
    return e


def _un(op, arg):
    e = TimingExprUn()
    e.op = op
    e.arg = arg
    return e


def _bin(op, left, right):
    e = TimingExprBin()
    e.op = op
    e.left = left
    e.right = right
    return e


def _if(cond, then_expr, else_expr):
    e = TimingExprIf()
    e.cond = cond
    e.trueExpr = then_expr
    e.falseExpr = else_expr
    return e


def serdivExtraLatency(base=1):
    """Data-dependent latency of the CVA6 integer divider,
    max(bits(a) - bits(b), 0) + base, and none when bits(a) < bits(b). The
    calibration harnesses pass 0 for TEST 21, so base stays a parameter."""
    # timingExprSizeInBits is ceilLog2, a bit short on a power of two, and
    # serdiv counts leading zeros, so the length is taken of the value plus 1.
    bits_a = _un('timingExprSizeInBits',
                 _bin('timingExprAdd', _src(0), _lit(1)))
    bits_b = _un('timingExprSizeInBits',
                 _bin('timingExprAdd', _src(1), _lit(1)))
    diff = _bin('timingExprSub', bits_a, bits_b)
    # max(bits(a) - bits(b), 0), since the subtraction is unsigned and wraps
    clamped = _if(_bin('timingExprSGreaterThan',
                  bits_a, bits_b), diff, _lit(0))
    # A quotient known to be zero answers in the first DIVIDE cycle,
    # without the FINISH cycle base stands for.
    early = _bin('timingExprSGreaterThan', bits_b, bits_a)
    return _if(early, _lit(0), _bin('timingExprAdd', clamped, _lit(base)))


# The C910 radix-16 SRT divider CVA6 runs (fpnew DivSqrtSel THMULTI) stops a
# round after its partial remainder reaches zero, so an exact short result
# runs short. Each timing's consumers wait for its commit, the latency unseen.
def _add(a, b): return _bin('timingExprAdd', a, b)
def _sub(a, b): return _bin('timingExprSub', a, b)
def _mul(a, b): return _bin('timingExprUMul', a, b)
def _div(a, b): return _bin('timingExprUDiv', a, b)
def _eq(a, b): return _bin('timingExprEqual', a, b)
def _ne(a, b): return _bin('timingExprNotEqual', a, b)
def _ult(a, b): return _bin('timingExprULessThan', a, b)
def _sgt(a, b): return _bin('timingExprSGreaterThan', a, b)
def _slt(a, b): return _bin('timingExprSLessThan', a, b)
def _and(a, b): return _bin('timingExprAnd', a, b)   # logical
def _or(a, b): return _bin('timingExprOr', a, b)     # logical


class _Let:
    """One TimingExprLet. bind() stores a subterm once and returns a factory
    of fresh TimingExprRef nodes, so no SimObject has two parents and no
    subterm is evaluated twice (timing_expr.cc memoises Refs per Let)."""

    def __init__(self):
        self.defns = []

    def bind(self, expr):
        self.defns.append(expr)
        index = len(self.defns) - 1

        def ref():
            e = TimingExprRef()
            e.index = index
            return e
        return ref

    def build(self, body):
        e = TimingExprLet()
        e.defns = self.defns
        e.expr = body
        return e


def _mod_pow2(x_ref, k):
    """x mod 2**k, with x already bound."""
    p = 1 << k
    return _sub(x_ref(), _mul(_div(x_ref(), _lit(p)), _lit(p)))


# ------------------------------------------------------ operand decoding


def _decode(let, fmt, index):
    """Bind sign, biased exponent, fraction and the normalised 53-bit
    significand of source`index`."""
    if fmt == 'd':
        v = let.bind(_src(index))
        sign = let.bind(_div(v(), _lit(1 << 63)))
        e = let.bind(_div(_mod_pow2(v, 63), _lit(1 << 52)))
        f = let.bind(_mod_pow2(v, 52))
        emax = 0x7FF
    else:
        v64 = let.bind(_src(index))
        v = let.bind(_mod_pow2(v64, 32))
        sign = let.bind(_div(v(), _lit(1 << 31)))
        e = let.bind(_div(_mod_pow2(v, 31), _lit(1 << 23)))
        f = let.bind(_mul(_mod_pow2(v, 23), _lit(1 << 29)))
        emax = 0xFF

    # Subnormal normalisation, a six-step binary shift network. c_j is 1 when
    # the step shifts by 2**j, and the total shift sh = 53 - bitlen(f).
    x = f
    shift_terms = []
    for j, limit in ((5, 21), (4, 37), (3, 45), (2, 49), (1, 51), (0, 52)):
        c = let.bind(_ult(x(), _lit(1 << limit)))
        x_prev = x
        x = let.bind(_if(c(), _mul(x_prev(), _lit(1 << (1 << j))), x_prev()))
        shift_terms.append((c, 1 << j))
    sh = None
    for c, w in shift_terms:
        term = _mul(c(), _lit(w))
        sh = term if sh is None else _add(sh, term)
    sh = let.bind(sh)

    is_sub = let.bind(_eq(e(), _lit(0)))
    sig = let.bind(_if(is_sub(), x(), _add(f(), _lit(1 << 52))))
    exp = let.bind(_if(is_sub(), _sub(_lit(1), sh()), e()))
    zero = _and(_eq(e(), _lit(0)), _eq(f(), _lit(0)))
    special = let.bind(_or(_eq(e(), _lit(emax)), zero))
    return dict(sign=sign, e=e, f=f, sig=sig, exp=exp, special=special)


# ------------------------------------------------------------ the law


def _div_rounds(fmt):
    """m for fdiv.{s,d}."""
    N = 13 if fmt == 'd' else 6
    let = _Let()
    a = _decode(let, fmt, 0)
    b = _decode(let, fmt, 1)
    A, B = a['sig'], b['sig']

    # rem_zero after round k  <=>  B divides A * 2**(4k-2)
    # (Q = A / 4B, the first quotient digit weighs 1/16). r_k is that
    # residue, r_1 = 4A mod B and r_{k+1} = 16 r_k mod B. Zero is absorbing.
    def mod_b(x_factory):
        return _sub(x_factory(), _mul(_div(x_factory(), B()), B()))

    r = let.bind(mod_b(lambda: _mul(_lit(4), A())))
    rounds = _lit(1)
    for k in range(1, N):
        rounds = _add(rounds, _ne(r(), _lit(0)))
        if k < N - 1:
            r_prev = r
            r = let.bind(mod_b(lambda rp=r_prev: _mul(_lit(16), rp())))

    diff = let.bind(_sub(a['exp'](), b['exp']()))
    of_lim, uf_lim = (1024, -1075) if fmt == 'd' else (128, -150)
    skip = _or(_or(a['special'](), b['special']()),
               _or(_sgt(diff(), _lit(of_lim)), _slt(diff(), _lit(uf_lim))))
    return let.build(_if(skip, _lit(0), rounds))


def _sqrt_rounds(fmt):
    """m for fsqrt.{s,d}."""
    N = 13 if fmt == 'd' else 6
    let = _Let()
    a = _decode(let, fmt, 0)

    # radicand at the double scale, doubled when the unbiased exponent is odd
    exp = a['exp']
    odd = _eq(_sub(exp(), _mul(_div(exp(), _lit(2)), _lit(2))), _lit(0))
    c = let.bind(_if(odd, _mul(a['sig'](), _lit(2)), a['sig']()))

    # y = isqrt(c) by integer Newton from above, c in [2**52, 2**54)
    y = let.bind(_lit(1 << 27))
    for _ in range(6):
        y_prev = y
        y = let.bind(_div(_add(y_prev(), _div(c(), y_prev())), _lit(2)))

    # root significand y / 2**26, and rem_zero after round k
    # <=>  2**(28-4k) divides y
    exact = _eq(_mul(y(), y()), c())
    rounds = _lit(1)
    for k in range(1, N):
        if 28 - 4 * k <= 0:
            break
        rounds = _add(rounds, _ne(_mod_pow2(y, 28 - 4 * k), _lit(0)))

    skip = _or(a['special'](), _ne(a['sign'](), _lit(0)))
    return let.build(_if(skip, _lit(0),
                         _if(exact, rounds, _lit(N))))


# ------------------------------------------------------- MinorFUTiming

# funct7 [31:25] and opcode [6:0] of OP-FP
_MASK = 0xFE00007F
_MATCH = {
    ('div', 's'): (0x0C << 25) | 0x53,
    ('div', 'd'): (0x0D << 25) | 0x53,
    ('sqrt', 's'): (0x2C << 25) | 0x53,
    ('sqrt', 'd'): (0x2D << 25) | 0x53,
}

# Issue to writeback is 8 + R with R = m + 1 SRT rounds: five hand-offs lead
# into the first round and four follow the last, so opLat is 9 and the
# expression adds m.
FP_DIVSQRT_BASE_LAT = 9

# A divide or root arriving while the unit is busy waits in fpnew's input
# register and starts in the WB cycle of the one ahead, so it writes back
# 6 + m after that one, 3 cycles sooner than a start at the writeback.
FP_DIVSQRT_QUEUE_OVERLAP = 3

# CVA6's scoreboard entries (CVA6ConfigNrScoreboardEntries). One freed at a
# commit is taken at the next edge, since the full flag is registered, and its
# instruction executes a cycle later, so a release delay of 2.
SCOREBOARD_ENTRIES = 8
SCOREBOARD_RELEASE_DELAY = 2

# Without the decode targets, a BTB that holds every taken branch stands in
# for them, as in gem5_config_CVA6.py.
STOCK_BTB_ENTRIES = 4096


def fpDivSqrtTimings(extra=0):
    timings = []
    for (op, fmt), match in _MATCH.items():
        expr = _div_rounds(fmt) if op == 'div' else _sqrt_rounds(fmt)
        if extra:
            expr = _add(expr, _lit(extra))
        timings.append(MinorFUTiming(
            description=f'FpDivSqrt_{op}_{fmt}',
            srcRegsRelativeLats=[0],
            mask=_MASK,
            match=match,
            extraCommitLatExpr=expr,
            consumersWaitForCommit=True))
    return timings


def flatDivSqrtTimings(extra=0):
    # The flat law, 15 cycles and 7 more for a double.
    timings = [MinorFUTiming(
        description='FpDivSqrtDouble',
        srcRegsRelativeLats=[0],
        mask=0x06000000,
        match=0x02000000,
        extraCommitLat=7 + extra)]
    if extra:
        timings.append(MinorFUTiming(
            description='FpDivSqrtSingle',
            srcRegsRelativeLats=[0],
            mask=0x06000000,
            match=0x00000000,
            extraCommitLat=extra))
    return timings


def minorMakeOpClassSet(op_classes):
    def boxOpClass(op_class):
        return MinorOpClass(opClass=op_class)
    return MinorOpClassSet(opClasses=[boxOpClass(o) for o in op_classes])


class CVA6FUPool(MinorFUPool):
    def __init__(self, c910_divider=True, divider_queue=True,
                 int_divider_wait=True):
        super().__init__()

        # The pipelined units are made by a function each, since the pool
        # takes several of every one.
        def int_alu():
            unit = MinorFU()
            unit.opClasses = minorMakeOpClassSet(['IntAlu'])
            unit.opLat = 1
            unit.issueLat = 1
            return unit

        def int_mul():
            unit = MinorFU()
            unit.opClasses = minorMakeOpClassSet(['IntMult'])
            unit.opLat = 2
            unit.issueLat = 1
            return unit

        int_div = MinorFU()
        int_div.opClasses = minorMakeOpClassSet(['IntDiv'])
        int_div.opLat = 2
        int_div.issueLat = 3
        # A divide's latency is set at its commit, unseen at issue, so its
        # consumers wait for the commit, and one cycle more, since the integer
        # unit stays busy through serdiv's writeback.
        int_div.timings = [MinorFUTiming(
            description='IntDivSerdiv',
            srcRegsRelativeLats=[0],
            extraCommitLatExpr=serdivExtraLatency(base=1),
            consumersWaitForCommit=int_divider_wait,
            consumerReleaseDelay=1 if int_divider_wait else 0)]

        def fp_addmul():
            unit = MinorFU()
            unit.opClasses = minorMakeOpClassSet(
                ['FloatAdd', 'FloatMult', 'FloatMultAcc'])
            unit.opLat = 3
            unit.issueLat = 1
            unit.timings = [MinorFUTiming(
                description='FpAddMulDouble',
                srcRegsRelativeLats=[0],
                mask=0x06000000,
                match=0x02000000,
                extraCommitLat=1)]
            return unit

        # fpnew's NONCOMP and CONV pipelines hold 1 and 2 registers,
        # a cycle each plus one, as the ADDMUL rows. fmv is NONCOMP,
        # so only fcvt takes the third.
        def fp_cvt():
            unit = MinorFU()
            unit.opClasses = minorMakeOpClassSet(['FloatCvt'])
            unit.opLat = 2
            unit.issueLat = 1
            unit.timings = [MinorFUTiming(
                description=f'FpConv{name}', srcRegsRelativeLats=[0],
                mask=0xE000007F, match=match, extraCommitLat=1)
                for name, match in (('Fp', 0x40000053), ('Int', 0xC0000053))]
            return unit

        def fp_noncomp():
            unit = MinorFU()
            unit.opClasses = minorMakeOpClassSet(['FloatCmp', 'FloatMisc'])
            unit.opLat = 2
            unit.issueLat = 1
            return unit

        fp_divsqrt = MinorFU()
        fp_divsqrt.opClasses = minorMakeOpClassSet(['FloatDiv', 'FloatSqrt'])
        # fpnew's input register, and a divider that writes back out of order.
        # The overlap moves out of opLat into the extra latency, where a held
        # operation skips it.
        overlap = FP_DIVSQRT_QUEUE_OVERLAP if divider_queue else 0
        if divider_queue:
            fp_divsqrt.holdWhileBusy = True
            fp_divsqrt.heldLatencyOverlap = overlap
            fp_divsqrt.extraCommitLatFromFUEnd = True
        if c910_divider:
            fp_divsqrt.opLat = FP_DIVSQRT_BASE_LAT - overlap
            fp_divsqrt.issueLat = FP_DIVSQRT_BASE_LAT - overlap
            fp_divsqrt.timings = fpDivSqrtTimings(overlap)
        else:
            # The flat law, exact for every full-count operation.
            fp_divsqrt.opLat = 15 - overlap
            fp_divsqrt.issueLat = 15 - overlap
            fp_divsqrt.timings = flatDivSqrtTimings(overlap)

        mem_fu = MinorFU()
        mem_fu.opClasses = minorMakeOpClassSet(
            ['MemRead', 'MemWrite', 'FloatMemRead', 'FloatMemWrite'])
        mem_fu.opLat = 2
        mem_fu.issueLat = 1
        mem_fu.timings = [
            MinorFUTiming(
                description='LrScOccupancy',
                srcRegsRelativeLats=[0],
                mask=0xF000007F,
                match=0x1000002F,
                extraCommitLat=10),
            MinorFUTiming(
                description='AmoOccupancy',
                srcRegsRelativeLats=[0],
                mask=0x0000007F,
                match=0x0000002F,
                extraCommitLat=13),
            MinorFUTiming(
                description='FenceOccupancy',
                srcRegsRelativeLats=[0],
                mask=0x0000007F,
                match=0x0000000F,
                extraCommitLat=3),
        ]

        # Vector and SIMD units are inert under CVA6 RVV = 0, retained only for
        # op-class completeness.
        simd_int_fast = MinorDefaultFloatSimdFU()
        simd_int_fast.opClasses = minorMakeOpClassSet([
            'SimdAdd', 'SimdAlu', 'SimdCmp', 'SimdShift', 'SimdShiftAcc',
            'SimdMisc', 'SimdExt', 'SimdConfig'
        ])
        simd_int_fast.timings = [MinorFUTiming(
            description='SimdIntFast', srcRegsRelativeLats=[2])]
        simd_int_fast.opLat = 2
        simd_int_fast.issueLat = 1

        simd_complex = MinorDefaultFloatSimdFU()
        simd_complex.opClasses = minorMakeOpClassSet([
            'SimdAddAcc', 'SimdCvt', 'SimdMult', 'SimdMultAcc',
            'SimdFloatAdd', 'SimdFloatAlu', 'SimdFloatCmp', 'SimdFloatCvt',
            'SimdFloatMisc', 'SimdFloatMult', 'SimdFloatMultAcc',
            'SimdFloatExt',
            'SimdReduceAdd', 'SimdReduceAlu', 'SimdReduceCmp',
            'SimdFloatReduceAdd', 'SimdFloatReduceCmp',
            'SimdAes', 'SimdAesMix', 'SimdSha1Hash', 'SimdSha1Hash2',
            'SimdSha256Hash', 'SimdSha256Hash2', 'SimdShaSigma2',
            'SimdShaSigma3'
        ])
        simd_complex.timings = [MinorFUTiming(
            description='SimdComplex', srcRegsRelativeLats=[2])]
        simd_complex.opLat = 4
        simd_complex.issueLat = 1

        simd_matrix = MinorDefaultFloatSimdFU()
        simd_matrix.opClasses = minorMakeOpClassSet([
            'Matrix', 'MatrixMov', 'MatrixOP',
            'SimdMatMultAcc', 'SimdFloatMatMultAcc'
        ])
        simd_matrix.timings = [MinorFUTiming(
            description='SimdMatrix', srcRegsRelativeLats=[2])]
        simd_matrix.opLat = 6
        simd_matrix.issueLat = 2

        simd_div_sqrt = MinorDefaultFloatSimdFU()
        simd_div_sqrt.opClasses = minorMakeOpClassSet([
            'SimdDiv', 'SimdSqrt', 'SimdFloatDiv', 'SimdFloatSqrt'
        ])
        simd_div_sqrt.timings = [MinorFUTiming(
            description='SimdDivSqrt', srcRegsRelativeLats=[2])]
        simd_div_sqrt.opLat = 15
        simd_div_sqrt.issueLat = 12

        pred = MinorDefaultPredFU()
        pred.opClasses = minorMakeOpClassSet(['SimdPredAlu'])
        pred.timings = [MinorFUTiming(
            description='Pred', srcRegsRelativeLats=[2])]
        pred.opLat = 1
        pred.issueLat = 1

        vec_mem_fast = MinorFU()
        vec_mem_fast.opClasses = minorMakeOpClassSet([
            'SimdUnitStrideLoad', 'SimdUnitStrideStore',
            'SimdUnitStrideMaskLoad', 'SimdUnitStrideMaskStore',
            'SimdUnitStrideFaultOnlyFirstLoad',
            'SimdWholeRegisterLoad', 'SimdWholeRegisterStore'
        ])
        vec_mem_fast.timings = [MinorFUTiming(
            description='VecMemFast', srcRegsRelativeLats=[1],
            extraAssumedLat=2)]
        vec_mem_fast.opLat = 2
        vec_mem_fast.issueLat = 1

        vec_mem_slow = MinorFU()
        vec_mem_slow.opClasses = minorMakeOpClassSet([
            'SimdStridedLoad', 'SimdStridedStore',
            'SimdIndexedLoad', 'SimdIndexedStore',
            'SimdUnitStrideSegmentedLoad', 'SimdUnitStrideSegmentedStore',
            'SimdUnitStrideSegmentedFaultOnlyFirstLoad',
            'SimdStrideSegmentedLoad', 'SimdStrideSegmentedStore'
        ])
        vec_mem_slow.timings = [MinorFUTiming(
            description='VecMemSlow', srcRegsRelativeLats=[1],
            extraAssumedLat=2)]
        vec_mem_slow.opLat = 10
        vec_mem_slow.issueLat = 4

        misc = MinorDefaultMiscFU()
        misc.opClasses = minorMakeOpClassSet(['InstPrefetch', 'IprAccess'])
        misc.opLat = 1
        misc.issueLat = 1

        # CVA6 writes a result into its scoreboard and issues on, where a Minor
        # unit holds it until commit, so each pipelined unit has an instance
        # per entry and executeMaxInFlightInsts is what stops issue.
        copies = SCOREBOARD_ENTRIES
        self.funcUnits = [
            *(make() for make in (int_alu, int_mul) for _ in range(copies)),
            int_div,
            *(make() for make in (fp_addmul, fp_cvt, fp_noncomp)
              for _ in range(copies)),
            fp_divsqrt,
            mem_fu,
            simd_int_fast, simd_complex, simd_matrix, simd_div_sqrt, pred,
            vec_mem_fast, vec_mem_slow, misc,
        ]


class CVA6CPU(RiscvMinorCPU):
    def __init__(self, direct_targets=True, store_forwarding_model=True,
                 fence_signal=True, ras_no_recovery=True,
                 fence_squash=True, icache_hold=True,
                 kill_on_redirect=True, fetch_limit=None,
                 fetch2_buffer=None, c910_divider=True, divider_queue=True,
                 drop_killed_lines=True, int_divider_wait=True,
                 atomic_squash=True, scoreboard=True, flush_at_once=True,
                 cold_static=True):
        super().__init__()

        self.executeFuncUnits = CVA6FUPool(
            c910_divider=c910_divider, divider_queue=divider_queue,
            int_divider_wait=int_divider_wait)

        # This config adopts depth 3 and gem5_config_CVA6.py keeps 2, so a
        # parity run against the stock build needs a way to make them equal.
        self.fetch1FetchLimit = (
            3 if fetch_limit is None else fetch_limit)
        self.fetch1LineSnapWidth = 4
        self.fetch1LineWidth = 4
        self.fetch1ToFetch2ForwardDelay = 1
        self.fetch1ToFetch2BackwardDelay = 0
        self.fetch2InputBufferSize = (
            3 if fetch2_buffer is None else fetch2_buffer)
        self.fetch2ToDecodeForwardDelay = 1
        self.fetch2CycleInput = True
        self.decodeInputBufferSize = 1
        self.decodeToExecuteForwardDelay = 1
        self.decodeInputWidth = 1
        self.decodeCycleInput = False
        self.executeInputWidth = 1
        self.executeCycleInput = flush_at_once
        self.executeIssueLimit = 1
        self.executeMemoryIssueLimit = 1
        self.executeCommitLimit = 2
        self.executeMemoryCommitLimit = 1
        self.executeInputBufferSize = 8
        self.executeMemoryWidth = 8
        self.executeMaxAccessesInMemory = 8
        self.executeLSQMaxStoreBufferStoresPerCycle = 1
        self.executeLSQRequestsQueueSize = 2
        self.executeLSQTransfersQueueSize = 8
        self.executeLSQStoreBufferSize = 4
        self.executeBranchDelay = 1
        self.executeSetTraceTimeOnCommit = True
        self.executeSetTraceTimeOnIssue = False
        self.executeAllowEarlyMemoryIssue = True
        self.threadPolicy = 'SingleThreaded'
        self.enableIdling = False
        # Requires the MinorCPU patch.
        self.fetch1WaitsForIcache = icache_hold
        self.fetch1KillsOnRedirect = kill_on_redirect
        self.fetch1DropsKilledLines = drop_killed_lines
        self.executeLSQNoStoreForwarding = store_forwarding_model
        self.executeLSQStoreCollisionReplayDelay = (
            STORE_COLLISION_REPLAY_DELAY if store_forwarding_model else 0)
        self.executeLSQFenceSignalsDcache = fence_signal
        self.executeFenceSquashesPipeline = fence_squash
        self.executeAtomicSquashesPipeline = atomic_squash
        self.executeMaxInFlightInsts = SCOREBOARD_ENTRIES if scoreboard else 0
        self.executeInFlightReleaseDelay = (
            SCOREBOARD_RELEASE_DELAY if scoreboard else 0)

        # Branch predictor.
        self.branchPred = LocalBP(
            localPredictorSize=256,
            localCtrBits=2,
            instShiftAmt=1,
        )
        self.branchPred.btb = SimpleBTB(
            numEntries=32 if direct_targets else STOCK_BTB_ENTRIES,
            tagBits=20,
            associativity=1,
            instShiftAmt=1,
            btbReplPolicy=LRURP(),
        )
        self.branchPred.ras = ReturnAddrStack(
            numEntries=2,
        )
        # Taken direct branches and jumps take their target from decode, and
        # the tagless BTB serves only indirect control, as CVA6's front end.
        if direct_targets:
            self.branchPred.directTargetsFromDecode = True
            self.branchPred.indirectBranchPred = NULL
            self.branchPred.btb.tagBits = 0

        if ras_no_recovery:
            self.branchPred.rasNoRecovery = True
        # A BHT entry with its valid bit clear predicts by the offset's sign.
        self.branchPred.coldStaticPrediction = cold_static


class CVA6Processor(BaseCPUProcessor):
    def __init__(self, direct_targets=True, store_forwarding_model=True,
                 fence_signal=True, ras_no_recovery=True,
                 fence_squash=True, icache_hold=True,
                 kill_on_redirect=True, fetch_limit=None,
                 fetch2_buffer=None, c910_divider=True, divider_queue=True,
                 drop_killed_lines=True, int_divider_wait=True,
                 atomic_squash=True, scoreboard=True, flush_at_once=True,
                 cold_static=True):
        cpu = CVA6CPU(direct_targets=direct_targets,
                      store_forwarding_model=store_forwarding_model,
                      fence_signal=fence_signal,
                      fence_squash=fence_squash,
                      ras_no_recovery=ras_no_recovery,
                      icache_hold=icache_hold,
                      kill_on_redirect=kill_on_redirect,
                      fetch_limit=fetch_limit,
                      fetch2_buffer=fetch2_buffer,
                      c910_divider=c910_divider,
                      divider_queue=divider_queue,
                      drop_killed_lines=drop_killed_lines,
                      int_divider_wait=int_divider_wait,
                      atomic_squash=atomic_squash,
                      scoreboard=scoreboard,
                      flush_at_once=flush_at_once,
                      cold_static=cold_static)
        core = BaseCPUCore(core=cpu, isa=ISA.RISCV)
        super().__init__(cores=[core])


class Axi2MemPortedMemory(SingleChannelSimpleMemory):
    """SingleChannelSimpleMemory with the Axi2MemPort model in front."""

    def __init__(self, latency, latency_var, bandwidth, size):
        super().__init__(
            latency=latency,
            latency_var=latency_var,
            bandwidth=bandwidth,
            size=size,
        )
        self.port_model = Axi2MemPort()
        self.port_model.mem_side = self.module.port

    def get_mem_ports(self):
        return [(self.module.range, self.port_model.cpu_side)]


class Axi2MemPortedDDR3(ChanneledMemory):
    """SingleChannelDDR3_1600 with the Axi2MemPort model in front."""

    def __init__(self, size):
        super().__init__(DDR3_1600_8x8, 1, 64, size=size)
        self.port_model = Axi2MemPort()
        self.port_model.mem_side = self.mem_ctrl[0].port

    def get_mem_ports(self):
        return [(self.mem_ctrl[0].dram.range, self.port_model.cpu_side)]


# =============================================================================
# Procesadores del laboratorio
# =============================================================================
from m5.objects import RiscvO3CPU  # type: ignore
import sys


def fail(message):
    """Termina con un mensaje de error. gem5 aborta con un SystemExit que
    lleva texto, asi que se imprime el mensaje y se sale con codigo 1."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)

# Lo unico que se lee de las clases de cache de los archivos de procesador.
CACHE_PARAMS = ("size", "assoc")


def cache_params(cache_class, role):
    """(size, assoc) de una clase de cache de un archivo de procesador.
    Cualquier otro atributo es un error: el resto de la cache
    esta fijo en este archivo, y un atributo ignorado en silencio haria creer
    que se cambio algo que no cambio."""
    extra = [k for k in vars(cache_class)
             if not k.startswith("_") and k not in CACHE_PARAMS]
    missing = [k for k in CACHE_PARAMS if not hasattr(cache_class, k)]
    if extra or missing:
        problems = []
        if extra:
            problems.append("sobra " + ", ".join(extra))
        if missing:
            problems.append("falta " + ", ".join(missing))
        fail(
            f"la cache {role} ({cache_class.__name__}) solo admite "
            f"{' y '.join(CACHE_PARAMS)}: {'; '.join(problems)}")
    return str(cache_class.size), int(cache_class.assoc)


# ---- CVA6 (in order) --------------------------------------------------------

def cva6_branch_pred(bp_class):
    """El predictor elegido con el front-end de CVA6, como lo arma CVA6CPU:
    BTB solo para saltos indirectos, destinos directos desde decode y RAS de
    2 entradas. coldStaticPrediction (una entrada sin usar predice por el signo
    del offset) solo existe en LocalBP."""
    bp = bp_class()
    bp.btb = SimpleBTB(
        numEntries=32,
        tagBits=20,
        associativity=1,
        instShiftAmt=1,
        btbReplPolicy=LRURP(),
    )
    bp.ras = ReturnAddrStack(
        numEntries=2,
    )
    bp.directTargetsFromDecode = True
    bp.indirectBranchPred = NULL
    bp.btb.tagBits = 0
    bp.rasNoRecovery = True
    if isinstance(bp, LocalBP):
        bp.coldStaticPrediction = True
    return bp


def cva6_processor(bp_class):
    processor = CVA6Processor()
    for core in processor.get_cores():
        core.core.branchPred = cva6_branch_pred(bp_class)
    return processor


def _init_cva6_l1(self, l1i_assoc, l1d_assoc):
    """Los mecanismos de las L1 de CVA6, todos activados, como los deja
    CVA6CacheHierarchy por defecto."""
    self._l1i_assoc = l1i_assoc
    self._l1d_assoc = l1d_assoc
    self._fill_at_response = True
    self._icache_structure = True
    self._evict_on_allocate = True
    self._victim_readout_stall = True
    self._cva6_victim_policy = True
    self._l1d_plru = False
    self._victim_readable_until_fill = True
    self._fill_phase = True
    self._window_charge = True
    self._fence_flush = True
    self._icache_policy = True


def _tune_cva6_membus(self):
    # The HPDcache reaches AXI with minimal interconnect delay, so the
    # gem5 crossbar latencies are trimmed to remove overhead CVA6 does
    # not incur.
    self.membus.frontend_latency = 1
    self.membus.forward_latency = 1
    self.membus.response_latency = 1
    self.membus.width = 8


def _tune_cva6_l1(self, board):
    """Las L1 de CVA6CacheHierarchy, con las vias como parametro."""
    for i, core in enumerate(board.get_processor().get_cores()):
        # L1I: 16 KiB, 4-way, 128-bit line.
        self.l1icaches[i].assoc = self._l1i_assoc
        self.l1icaches[i].tag_latency = 1
        self.l1icaches[i].data_latency = 1
        self.l1icaches[i].response_latency = 0
        self.l1icaches[i].mshrs = 1
        if self._icache_structure:
            self.l1icaches[i].fill_ready_at_fill = True
            self.l1icaches[i].reopen_at_ready = True
        self.l1icaches[i].tgts_per_mshr = 16
        self.l1icaches[i].is_read_only = True
        self.l1icaches[i].sequential_access = False
        self.l1icaches[i].writeback_clean = False
        if self._icache_policy:
            # Transcribed from cva6_icache.sv, so victims follow its LFSR.
            self.l1icaches[i].replacement_policy = CVA6IcacheRandomRP()
        else:
            self.l1icaches[i].replacement_policy = RandomRP()

        # L1D: 32 KiB, 8-way, 128-bit line.
        self.l1dcaches[i].assoc = self._l1d_assoc
        self.l1dcaches[i].tag_latency = 1
        self.l1dcaches[i].data_latency = 1
        self.l1dcaches[i].response_latency = (
            L1D_RESPONSE_LATENCY if self._fill_phase
            else FROZEN_L1D_RESPONSE_LATENCY)
        self.l1dcaches[i].fill_delay = (
            0 if self._window_charge
            else (L1D_FILL_DELAY if self._fill_phase
                  else FROZEN_L1D_FILL_DELAY))
        # The victim dies in the core-response cycle, as the HPDcache
        # rewrites its directory then.
        self.l1dcaches[i].fill_at_response = self._fill_at_response
        self.l1dcaches[i].fence_flushes_dcache = self._fence_flush
        self.l1dcaches[i].mshrs = 8
        self.l1dcaches[i].tgts_per_mshr = 16
        self.l1dcaches[i].write_buffers = 8
        self.l1dcaches[i].is_read_only = False
        self.l1dcaches[i].sequential_access = False
        self.l1dcaches[i].writeback_clean = False
        self.l1dcaches[i].prefetcher = NULL

        # Eviction mechanisms, L1D only: the read-only L1I produces no
        # writebacks.
        if self._l1d_plru:
            self.l1dcaches[i].replacement_policy = TreePLRURP()
        elif self._cva6_victim_policy:
            self.l1dcaches[i].replacement_policy = HPDcacheRandomRP()
        else:
            self.l1dcaches[i].replacement_policy = RandomRP()
        self.l1dcaches[i].evict_on_allocate = self._evict_on_allocate
        self.l1dcaches[i].victim_readout_stall = \
            self._victim_readout_stall
        self.l1dcaches[i].victim_readable_until_fill = \
            self._victim_readable_until_fill
        self.l1dcaches[i].window_accept_and_charge = self._window_charge
        self.l1dcaches[i].victim_readout_store_extra = (
            VICTIM_READOUT_STORE_EXTRA if self._window_charge else 0)
        self.l1dcaches[i].victim_readout_first_load_extra = (
            VICTIM_READOUT_FIRST_LOAD_EXTRA if self._window_charge
            else 0)


class CVA6Caches(PrivateL1CacheHierarchy):
    """L1 de CVA6 directo a memoria, sin L2, como el CVA6 real."""

    def __init__(self, l1i, l1d):
        super().__init__(l1d_size=l1d[0], l1i_size=l1i[0])
        _init_cva6_l1(self, l1i[1], l1d[1])

    def incorporate_cache(self, board):
        super().incorporate_cache(board)
        _tune_cva6_membus(self)
        _tune_cva6_l1(self, board)


# ---- O3 (out of order) ------------------------------------------------------

class LabO3CPU(RiscvO3CPU):
    """Anchos, colas y registros del ex5_big (Cortex-A15) del out_of_order.py
    de 2025. Las unidades funcionales son las de O3CPU por defecto."""
    LQEntries = 16
    SQEntries = 16
    LSQDepCheckShift = 0
    LFSTSize = 1024
    SSITSize = "1024"
    decodeToFetchDelay = 1
    renameToFetchDelay = 1
    iewToFetchDelay = 1
    commitToFetchDelay = 1
    renameToDecodeDelay = 1
    iewToDecodeDelay = 1
    commitToDecodeDelay = 1
    iewToRenameDelay = 1
    commitToRenameDelay = 1
    commitToIEWDelay = 1
    fetchWidth = 3
    fetchBufferSize = 16
    fetchToDecodeDelay = 3
    decodeWidth = 3
    decodeToRenameDelay = 2
    renameWidth = 3
    renameToIEWDelay = 1
    issueToExecuteDelay = 1
    dispatchWidth = 6
    issueWidth = 8
    wbWidth = 8
    iewToCommitDelay = 1
    renameToROBDelay = 1
    commitWidth = 8
    squashWidth = 8
    trapLatency = 13
    backComSize = 5
    forwardComSize = 5
    numPhysIntRegs = 90
    numPhysFloatRegs = 256
    numIQEntries = 48
    numROBEntries = 60


def o3_branch_pred(bp_class):
    """El predictor elegido con el BTB y el RAS del out_of_order.py de 2025."""
    bp = bp_class()
    bp.btb = SimpleBTB(numEntries=128, tagBits=18)
    bp.ras = ReturnAddrStack(numEntries=8)
    return bp


def o3_processor(bp_class):
    cpu = LabO3CPU()
    cpu.branchPred = o3_branch_pred(bp_class)
    return BaseCPUProcessor(cores=[BaseCPUCore(core=cpu, isa=ISA.RISCV)])


def _tune_o3_l1(self, l1i_assoc, l1d_assoc):
    """Las L1 del out_of_order.py de 2025: 2 ciclos de latencia. Sin L2 no
    hay victim cache, asi que las lineas limpias no se escriben al desalojarse.
    Cada MSHR admite 16 accesos a la misma linea, como en CVA6: con 8, una
    linea de 64 B (8 doubles) llena el MSHR y gem5 bloquea toda la cache."""
    for cache in list(self.l1icaches) + list(self.l1dcaches):
        cache.tag_latency = 2
        cache.data_latency = 2
        cache.response_latency = 2
        cache.tgts_per_mshr = 16
        cache.writeback_clean = False
        cache.prefetcher = NULL
    for cache in self.l1icaches:
        cache.assoc = l1i_assoc
        cache.mshrs = 2
        cache.is_read_only = True
    for cache in self.l1dcaches:
        cache.assoc = l1d_assoc
        cache.mshrs = 6
        cache.write_buffers = 16


class O3Caches(PrivateL1CacheHierarchy):
    """L1 del O3 directo a memoria."""

    def __init__(self, l1i, l1d):
        super().__init__(l1d_size=l1d[0], l1i_size=l1i[0])
        self._l1i_assoc = l1i[1]
        self._l1d_assoc = l1d[1]

    def incorporate_cache(self, board):
        super().incorporate_cache(board)
        _tune_o3_l1(self, self._l1i_assoc, self._l1d_assoc)


# ---- Armado -----------------------------------------------------------------

CORES = {
    "cva6": (cva6_processor, CVA6Caches),
    "o3": (o3_processor, O3Caches),
}


def build_processor_and_caches(cpu_spec):
    """El procesador y la jerarquia de caches de un cpu_spec
    (core, ICache, DCache, BP)."""
    core, icache, dcache, bp_class = cpu_spec
    if core not in CORES:
        fail(f"core '{core}' desconocido, las opciones son "
             f"{', '.join(CORES)}")
    make_processor, make_caches = CORES[core]
    caches = make_caches(cache_params(icache, "L1I"), cache_params(dcache, "L1D"))
    return make_processor(bp_class), caches


def build_memory(mem):
    """La memoria de cpu_config.toml. type = "CVA6" es la memoria con la que
    se calibro el modelo: latencia 0 detras del puerto AXI de CVA6."""
    if mem["type"] == "CVA6":
        return Axi2MemPortedMemory(latency=MEM_LATENCY, latency_var="0ns",
                                   bandwidth="12.8GiB/s", size=mem["size"])
    import m5.objects
    dram = getattr(m5.objects, mem["type"], None)
    if dram is None:
        fail(f"memoria '{mem['type']}' desconocida")
    memory = ChanneledMemory(dram, mem["channels"], mem["cache_line_size"],
                             size=mem["size"])
    if mem["ranks"] > 0:
        for ctrl in memory.mem_ctrl:
            ctrl.dram.ranks_per_channel = mem["ranks"]
    return memory
