# Arquitectura de Computadoras - 2026

## Estructura de archivos

- `run_simulation.sh`: Archivo para correr la simulación, en él se debe elegir el benchmark a correr y la configuración del procesador a utilizar. También genera la traza de la ejecución y abre su visualizador (ver más abajo).
- `visualizadores`: Visualizadores de la ejecución en el pipeline, `MinorFlow.html` (in-order) y `Konata.html` (out-of-order).
- `benchmarks`: Carpeta donde se encuentran los templates de los ejercicios a resolver, en assembler RISC-V.
- `scripts`: Carpeta que incluye todos los scripts de ejecución y configuración de la simulación de ejecución del procesador.
  + `cpu_config.toml` - archivo que tiene configuraciones generales del micro, aplican a cualquier configuración de procesador que ejecuten.
  + `in_order.py` - procesador in order: CVA6, un RISC-V real de 6 etapas.
  + `out_of_order.py` - procesador out of order (O3CPU de gem5).
  + `se.py` - script principal que ejecuta las simulaciones en base a las configuraciones especificadas. Carga el procesador elegido por el nombre de su archivo. No modificar.
  + `devices.py` - script que efectivamente crea el CPU que gem5 va a correr. No modificar.
  + `stat-collect.py` - script que recolecta y recalcula algunos resultados de la simulación, con los mismos nombres y definiciones que el panel de métricas de MinorFlow.

## Requisitos

- **Docker**, para correr gem5 y el compilador de RISC-V sin instalarlos (ver abajo cómo instalarlo).
- **Una terminal con bash**: la de Linux o macOS, o la de Ubuntu en WSL en Windows.
- **Un navegador** actual (Chrome, Firefox, Edge o Safari), para los visualizadores.
- **Espacio en disco**: unos 10 GB libres.
  + La imagen del laboratorio, `gvodanovic/famaf_adc2026:lab2`, se descarga una sola vez: son alrededor de 1,4 GB de descarga y ocupa 3,1 GB instalada.
  + Al generar la traza de un procesador in-order, gem5 usa hasta 3 GB temporales dentro de Docker, que se liberan al terminar.
- **Memoria**: la simulación usa menos de 300 MB. Alcanza con una computadora de 4 GB de RAM, contando lo que usa Docker.

### Instalar Docker

**Linux (Ubuntu, Debian y derivados)**

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Después cerrar la sesión y volver a entrar, para poder usar `docker` sin `sudo`. Para otras distribuciones: https://docs.docker.com/engine/install/

**Windows**

1. Instalar WSL con Ubuntu: en una PowerShell abierta como administrador, `wsl --install`, y reiniciar.
2. Instalar [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) con el backend WSL 2, y en *Settings → Resources → WSL integration* activar la integración con Ubuntu.
3. Trabajar siempre desde la terminal de Ubuntu, con el repositorio clonado dentro de la carpeta personal de Ubuntu (`~/`), no en `/mnt/c/...`: ahí Docker es mucho más lento.

**macOS**

Instalar [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/). En las Mac con procesador Apple (M1 a M4) la imagen corre emulada, porque está hecha para procesadores x86: funciona, pero más lento. Conviene activar *Settings → General → Use Rosetta for x86_64/amd64 emulation on Apple Silicon*.

### Probar la instalación

```sh
docker run --rm hello-world
docker pull gvodanovic/famaf_adc2026:lab2
```

El primer comando debe mostrar un mensaje de bienvenida. El segundo descarga la imagen del laboratorio. No es obligatorio, porque se descarga sola la primera vez que se corre la simulación, pero así esa primera corrida no tarda.

## Cómo crear una configuración

Cada procesador es un archivo `.py` en la carpeta `scripts`, y se elige por su nombre sin el `.py`. Para crear uno nuevo, por ejemplo a partir del in-order, copiar su archivo con otro nombre:

```sh
cp scripts/in_order.py scripts/nuevo_cpu.py
```

y modificar en la copia:

- Las cachés `ICache` y `DCache`: solo su tamaño (`size`) y sus vías (`assoc`). Cualquier otro atributo da error, el resto de las características de la caché están fijas. Los procesadores no tienen caché L2, como el CVA6 real.
- El predictor de saltos que se usa, el último elemento de `cpu_spec`: `BP_local_2bits` (predictor de 2 bits local, el que tiene CVA6) o `BP_tournament` (predictor por torneos). Se pueden cambiar también los tamaños de cada predictor en su clase.

El primer elemento de `cpu_spec` indica el tipo de procesador (`"cva6"` in-order u `"o3"` out-of-order) y no se debe cambiar en la copia. No hace falta modificar ningún otro archivo: el nuevo procesador ya se puede usar con `PROCESSOR=nuevo_cpu`.


## Como correr la simulación

Ejecutar el script `./run_simulation.sh` definiendo las variables de entorno BENCHMARK con 'ej_daxpy' o 'ej_branchPred' y PROCESSOR con el nombre del procesador que quieran usar.

Ejemplo:

```sh
BENCHMARK=ej_daxpy PROCESSOR=out_of_order ./run_simulation.sh
```

El script compila el benchmark, corre la simulación y muestra las métricas. Son las mismas que muestra MinorFlow con *Main Code* activado, así que se pueden comparar los dos procesadores con el mismo criterio aunque MinorFlow solo muestre el in-order. La salida de gem5 queda en `sim.log` y todas las estadísticas en `se_results/stats.txt`. Las estadísticas corresponden solo a la región entre `m5_reset_stats` y `m5_dump_stats` del template, por eso el código debe ir entre `CODE HERE` y `END CODE`.


## Cómo ver la ejecución en el pipeline

Cada vez que se corre `run_simulation.sh` se genera la traza de la ejecución y se abre en el navegador el visualizador que corresponde al procesador:

| Procesador | Visualizador | Traza |
|---|---|---|
| in-order (CVA6) | `visualizadores/MinorFlow.html` | `minorflow/<benchmark>_<procesador>.json` |
| out-of-order | `visualizadores/Konata.html` | `konata/<benchmark>_<procesador>.trace.gz` |

Los visualizadores no cargan la traza solos: hay que arrastrarla a la ventana del navegador, o elegirla con *Load JSON* (MinorFlow) u *Open* (Konata). No hace falta instalar nada. Si el navegador no se abre, abrir el archivo del visualizador con doble click.

En Linux, si el navegador está instalado como snap (por ejemplo Firefox en Ubuntu), solo puede abrir archivos dentro de la carpeta personal y fuera de carpetas ocultas: clonar el repositorio en algún lugar de `~/` que no empiece con `.`, y no en `/tmp` u otro disco.

- [MinorFlow](https://github.com/FaMAF-CVA6-Project/MinorFlow) muestra, ciclo a ciclo, cómo avanza cada instrucción por el pipeline del CVA6: en qué etapa está, cuándo se detiene y por qué (misses de caché, dependencias, saltos mal predichos).
- [Konata](https://github.com/shioyadan/Konata) muestra lo mismo para el procesador out-of-order. Cada fila es una instrucción y cada segmento una etapa: `F` (fetch), `Dc` (decode), `Rn` (rename), `Ds` (dispatch, esperando operandos), `Is` (issue, ejecutando), `Mc` (acceso a memoria completo), `Cm` (complete, terminada) y `Rt` (retire, en orden de programa).

Generar la traza hace la simulación más lenta (en el in-order, con daxpy completo, alrededor de un minuto más). Para correr sin generarla ni abrir el visualizador, por ejemplo al barrer muchas configuraciones de caché:

```sh
TRACE=0 BENCHMARK=ej_daxpy PROCESSOR=in_order ./run_simulation.sh
```


## Agradecimientos

- **Alvaro Roy Schachner**: por la implementación de algunos scripts básicos para automatizar el uso de gem5.
- **Manuel Nieto** y **Francisco Cortez**: por la implementación del visualizador MinorFlow y su presentación en el congreso [CARLA](https://carlaconference.org/rv-converge/).
