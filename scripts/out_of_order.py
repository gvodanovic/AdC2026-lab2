from m5.objects import *

# O3CPU de gem5: procesador fuera de orden generico, con los anchos y colas del
# ex5_big (Cortex-A15) de 2025 (ver devices.py).


# Predictor de 2 bits (local): una tabla (BHT) de contadores de 2 bits indexada
# por el PC, sin historia.
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
    size = "32KiB"
    assoc = 2

class DCache:
    size = "32KiB"
    assoc = 2

cpu_spec = ("o3", ICache, DCache, BP_tournament)
