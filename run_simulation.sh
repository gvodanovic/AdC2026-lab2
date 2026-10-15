#!/bin/bash

IMAGE_NAME="gvodanovic/famaf_adc2026:lab2"
RESULT_PATH="se_results"


# Definir el benchmark a correr, opciones: ej_daxpy, ej_branchPred
BENCHMARK="${BENCHMARK:-ej_daxpy}"

# Definir el procesador a utilizar, opciones: in_order, out_of_order, etc.
PROCESSOR="${PROCESSOR:-in_order}"

# Generar la traza de la ejecucion y abrir su visualizador (1) o no (0):
# MinorFlow para los procesadores in-order, Konata para los out-of-order.
TRACE="${TRACE:-1}"


# Sin codigo de arranque nadie inicializa gp, asi que el linker no debe
# convertir accesos a datos en accesos relativos a gp (--no-relax).
CFLAGS="-static -mcmodel=medany -nostdlib -nostartfiles -e main -Wl,--no-relax \
-march=rv64gc_zba_zbb_zbs_zbc_zbkb_zbkx_zkne_zknd_zknh -mabi=lp64d \
-I /gem5/include"

# Abre un archivo en el navegador, en Linux, macOS, WSL o Git Bash (Windows).
open_viewer() {
    if command -v wslview > /dev/null; then
        wslview "$1"
    elif command -v xdg-open > /dev/null; then
        xdg-open "$1" > /dev/null 2>&1 &
    elif command -v open > /dev/null; then
        open "$1"
    elif command -v cygpath > /dev/null; then
        cmd.exe /c start "" "$(cygpath -w "$1")"
    else
        echo "Abrir en el navegador: $1"
    fi
}

# El tipo de core sale del cpu_spec del archivo de procesador: "cva6"
# (in-order) u "o3" (out-of-order).
CORE=$(sed -n 's/^cpu_spec = ("\([a-z0-9]*\)".*/\1/p' "scripts/$PROCESSOR.py" 2>/dev/null)

TRACE_FLAGS=""
if [ "$TRACE" = "1" ]; then
    if [ "$CORE" = "cva6" ]; then
        # La traza de MinorFlow pesa varios GB: se escribe en /tmp dentro del
        # contenedor, que se borra al terminar, y afuera queda solo el JSON.
        TRACE_FLAGS="--debug-flags=Minor,MinorTrace,CacheAll,ExecAll,Fetch,Decode,RAS --debug-file=/tmp/trace.txt"
        TRACE_FILE="minorflow/${BENCHMARK}_${PROCESSOR}.json"
        VIEWER="visores/MinorFlow.html"
    elif [ "$CORE" = "o3" ]; then
        # gem5 escribe la traza de Konata ya comprimida.
        TRACE_FLAGS="--debug-flags=O3PipeView,Rename,MemDepUnit,LSQUnit --debug-file=/local/konata/${BENCHMARK}_${PROCESSOR}.trace.gz"
        TRACE_FILE="konata/${BENCHMARK}_${PROCESSOR}.trace.gz"
        VIEWER="visores/Konata.html"
        mkdir -p konata
    else
        echo "info: no se reconoce el core de $PROCESSOR, no se genera la traza"
        TRACE=0
    fi
fi

docker run --rm -v "$(pwd)":/local -w /local --user "$(id -u):$(id -g)" $IMAGE_NAME /bin/bash -c "
set -e
riscv64-unknown-elf-gcc benchmarks/$BENCHMARK.s /gem5/util/m5/src/abi/riscv/m5op.S $CFLAGS -o benchmarks/$BENCHMARK.img
/gem5/build/RISCV_PATCH/gem5.opt $TRACE_FLAGS -d $RESULT_PATH scripts/se.py scripts/cpu_config.toml $PROCESSOR benchmarks/$BENCHMARK.img > sim.log 2>&1 || { grep '^error:' sim.log || tail -n 20 sim.log; exit 1; }
python3 scripts/stat-collect.py $RESULT_PATH/stats.txt
if [ $TRACE = 1 ] && [ '$CORE' = cva6 ]; then
    mkdir -p minorflow
    echo
    echo 'Generando el JSON de MinorFlow...'
    python3 /gem5/MinorFlow/MinorFlow_tracer.py /tmp/trace.txt -o $TRACE_FILE --quiet > /dev/null 2> /tmp/tracer.log || { cat /tmp/tracer.log; exit 1; }
    grep -v '^\[INFO\]' /tmp/tracer.log || true
fi
" || exit 1

if [ "$TRACE" = "1" ]; then
    echo
    echo "Traza: $TRACE_FILE"
    echo "Se abre $VIEWER: arrastrar la traza a la ventana del navegador (o usar Open / Load JSON)."
    open_viewer "$VIEWER"
fi
