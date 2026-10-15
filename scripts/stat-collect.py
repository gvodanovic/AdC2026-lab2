import sys

# Muestra las metricas de la region medida (entre m5_reset_stats y
# m5_dump_stats) con los mismos nombres y definiciones que el panel de
# MinorFlow con Main Code activado, para comparar los dos procesadores con un
# mismo criterio: MinorFlow solo muestra el procesador in-order.

CPU = "board.processor.cores.core"
BP = f"{CPU}.branchPred"
L1D = "board.cache_hierarchy.l1dcaches"
L1I = "board.cache_hierarchy.l1icaches"

stat_names = [
    f"{CPU}.numCycles",                                 # Number of cpu cycles simulated (Cycle)
    f"{CPU}.commitStats0.numInsts",                     # Number of instructions committed (Count)
    "board.clk_domain.clock",                           # Clock period (Tick = ps)

    # Un miss es un acceso que tuvo que traer la linea de memoria. Un acceso a
    # una linea que ya se pidio y todavia no llego no es un miss nuevo.
    f"{L1I}.demandMshrMisses::total",                   # I-cache misses
    f"{L1I}.demandAccesses::total",                     # I-cache accesses (hits + misses)
    f"{L1D}.demandMshrMisses::total",                   # D-cache misses
    f"{L1D}.ReadReq.mshrMisses::total",                 # D-cache misses de loads
    f"{L1D}.WriteReq.mshrMisses::total",                # D-cache misses de stores
    f"{L1D}.demandAccesses::total",                     # D-cache accesses (hits + misses)
    f"{L1D}.ReadReq.accesses::total",                   # D-cache accesses de loads
    f"{L1D}.WriteReq.accesses::total",                  # D-cache accesses de stores

    f"{BP}.committed_0::total",                         # Saltos que llegaron a commit
    f"{BP}.mispredictDueToPredictor_0::total",          # Mispredicted: el predictor erro
    f"{BP}.mispredictDueToBTBMiss_0::total",            # Unpredicted: no hubo prediccion
]


def retrieve_stats(filename):
    """Las stats del primer bloque de stats.txt: el que escribe m5_dump_stats
    al final de la region medida (m5_reset_stats las pone en cero al
    empezarla). El segundo bloque, el de la salida del programa, no se usa.
    gem5 omite las stats que valen 0, asi que una stat ausente vale 0."""
    stats = {name: 0.0 for name in stat_names}
    with open(filename) as f:
        for line in f:
            if line.startswith("---------- End Simulation Statistics"):
                break
            fields = line.split()
            if len(fields) >= 2 and fields[0] in stats:
                stats[fields[0]] = float(fields[1])
    return stats


def count(value):
    return f"{int(value):,}"


def show(label, value):
    print(f"{label + ':':20} {value}")


def percent(num, den):
    return "-" if not den else f"{100 * num / den:.2f} %"


s = retrieve_stats(sys.argv[1])
cycles = s[f"{CPU}.numCycles"]
committed = s[f"{CPU}.commitStats0.numInsts"]
d_miss = s[f"{L1D}.demandMshrMisses::total"]
d_miss_ld = s[f"{L1D}.ReadReq.mshrMisses::total"]
d_miss_st = s[f"{L1D}.WriteReq.mshrMisses::total"]
d_acc = s[f"{L1D}.demandAccesses::total"]
d_acc_ld = s[f"{L1D}.ReadReq.accesses::total"]
d_acc_st = s[f"{L1D}.WriteReq.accesses::total"]
i_miss = s[f"{L1I}.demandMshrMisses::total"]
i_acc = s[f"{L1I}.demandAccesses::total"]
branches = s[f"{BP}.committed_0::total"]
mispredicted = s[f"{BP}.mispredictDueToPredictor_0::total"]
unpredicted = s[f"{BP}.mispredictDueToBTBMiss_0::total"]

# Las mismas metricas, en el mismo orden, que el panel de MinorFlow.
show("Cycles", count(cycles))
show("Committed", count(committed))
show("I-cache misses", count(i_miss))
show("D-cache misses", f"{count(d_miss)} ({count(d_miss_ld)} load, {count(d_miss_st)} store)")
show("I-cache accesses", count(i_acc))
show("D-cache accesses", f"{count(d_acc)} ({count(d_acc_ld)} load, {count(d_acc_st)} store)")
show("Branches", count(branches))
show("Mispredicted", count(mispredicted))
show("Unpredicted", count(unpredicted))
show("Time", f"{cycles * s['board.clk_domain.clock'] / 1e6:.3f} µs")
show("IPC", "-" if not cycles else f"{committed / cycles:.3f}")

# Calculadas a partir de las anteriores.
print()
show("CPI", "-" if not committed else f"{cycles / committed:.2f}")
d_hits_ld = d_acc_ld - d_miss_ld
d_hits_st = d_acc_st - d_miss_st
show("D-cache hits", f"{count(d_acc - d_miss)} ({count(d_hits_ld)} load, {count(d_hits_st)} store)")
show("D-cache miss rate", percent(d_miss, d_acc))
show("I-cache miss rate", percent(i_miss, i_acc))
show("Mispredict rate", percent(mispredicted + unpredicted, branches))
