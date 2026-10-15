from m5.objects import *

# CVA6: procesador RISC-V en orden de 6 etapas (modelo calibrado en devices.py).


# Predictor de 2 bits (local): una tabla (BHT) de contadores de 2 bits indexada
# por el PC, sin historia. Es el predictor que tiene CVA6.
class BP_local_2bits(LocalBP):
    localPredictorSize = 256
    localCtrBits = 2
    instShiftAmt = 1

class BP_tournament(TournamentBP):
    localPredictorSize = 64
    localCtrBits = 2
    localHistoryTableSize = 64
    globalPredictorSize = 1024
    globalCtrBits = 2
    choicePredictorSize = 1024
    choiceCtrBits = 2
    instShiftAmt = 1

# De las caches solo se configuran el tamano y las vias (assoc).
class ICache:
    size = "16KiB"
    assoc = 4

class DCache:
    size = "32KiB"
    assoc = 8

cpu_spec = ("cva6", ICache, DCache, BP_local_2bits)
