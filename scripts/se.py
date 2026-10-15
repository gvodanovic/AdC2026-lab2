# Script principal de la simulacion en modo syscall emulation (SE): arma el
# sistema con la configuracion general de cpu_config.toml y el procesador
# elegido, y corre el programa. El procesador es el nombre de un archivo de
# esta carpeta sin el .py (in_order, out_of_order o uno nuevo), que se carga
# solo: no hace falta modificar este archivo para agregar un procesador.
#
#   gem5.opt -d <resultados> se.py <cpu_config.toml> <procesador> <programa>

import importlib
import os
import sys
import tomllib

from gem5.components.boards.simple_board import SimpleBoard  # type: ignore
from gem5.resources.resource import BinaryResource  # type: ignore
from gem5.simulate.simulator import Simulator  # type: ignore

import devices

SCRIPTS_DIR = os.path.dirname(os.path.abspath(devices.__file__))


def processor_files():
    """Los archivos de procesador de esta carpeta: los que definen cpu_spec."""
    names = []
    for name in sorted(os.listdir(SCRIPTS_DIR)):
        if name.endswith(".py"):
            with open(os.path.join(SCRIPTS_DIR, name)) as f:
                if any(line.startswith("cpu_spec =") for line in f):
                    names.append(name[:-3])
    return names


def load_cpu_spec(cpu_type):
    """El cpu_spec del archivo de procesador scripts/<cpu_type>.py, una tupla
    (core, ICache, DCache, BP)."""
    if cpu_type not in processor_files():
        devices.fail(f"procesador '{cpu_type}' desconocido, las opciones "
                     f"son {', '.join(processor_files())}")
    return importlib.import_module(cpu_type).cpu_spec


def create_board(spec_path, cpu_type, binary):
    with open(spec_path, "rb") as f:
        spec = tomllib.load(f)

    if spec["cpu"]["num_cores"] != 1:
        devices.fail("solo se simula un core (num_cores = 1)")

    processor, cache_hierarchy = devices.build_processor_and_caches(
        load_cpu_spec(cpu_type))

    board = SimpleBoard(
        clk_freq=spec["cpu"]["frequency"],
        processor=processor,
        memory=devices.build_memory(spec["memory"]),
        cache_hierarchy=cache_hierarchy,
    )
    board.cache_line_size = spec["memory"]["cache_line_size"]
    board.set_se_binary_workload(BinaryResource(binary))
    for core in board.get_processor().get_cores():
        core.core.workload[0].cmd = [os.path.basename(binary)]
    return board


def main(argv):
    if len(argv) != 4:
        devices.fail(f"uso: {argv[0]} <spec file> <cpu type> <programa>")
    spec_path, cpu_type, binary = argv[1:]

    board = create_board(spec_path, cpu_type, binary)
    print(f"info: procesador {cpu_type}, programa {binary}")

    # El programa llama a m5_reset_stats al empezar la region medida y a
    # m5_dump_stats al terminarla: el primer bloque de stats.txt es esa region.
    simulator = Simulator(board=board)
    simulator.run()
    print(f"{simulator.get_last_exit_event_cause()} @ "
          f"{simulator.get_current_tick()}")


if __name__ == "__m5_main__":
    main(sys.argv)
