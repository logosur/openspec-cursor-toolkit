# Trabajos pesados: un semáforo común a todos los proyectos (regla global)

Por qué: cada proyecto puede ordenar sus trabajos pesados, pero nadie ordena los de varios proyectos a la vez. Sin un
semáforo de máquina, las suites, los builds y los emuladores se amontonan hasta que el equipo se queda sin memoria.

- **Pesado:** emulador Android; e2e (Maestro, Playwright, `ddev e2e`); build de Gradle, `npm ci` o instalación completa;
  suite completa de pytest, PHPUnit, Jest o Vitest y las puertas `make ci|test|smoke|…e2e…`; modelos de ML (whisper,
  torch…: `--kind ml`, 2 huecos); render de vídeo (`--kind render`; un fotograma o un audio no lo es).
- **Ligero:** un test concreto (hasta 5 ficheros o ids explícitos, `-k`, `--filter`, `--group`, `-t`, `--grep`,
  `--collect-only`, `--list-*`) o un directorio con 5 ficheros de test o menos. En la duda:
  `~/.claude/scripts/heavy-job classify -- '<comando>'`.
- **Una suite troceada es una suite:** más de 5 ficheros de test en una orden, un runner dentro de un bucle (`for`,
  `while`) o bajo `xargs`, `parallel` o `find -exec`, un script que hace eso (se lee al ejecutarlo, también lanzado con
  `nohup setsid`) y una serie de lotes de la misma sesión en el mismo checkout (más de 10 ficheros distintos en una
  hora) son pesados. Se corre en una sola pasada: con `heavy-job run`, o en la nube si el proyecto la declara. Lo que
  un proyecto declara en `local_commands` de `.claude/cloud-tests.json` también es pesado: un objetivo propio que
  tarda (un `make …-check` de CPU) se declara ahí.
- **Se lanza** con `~/.claude/scripts/heavy-job run --kind <tipo> --label '<qué>' -- <comando>`: espera un hueco en toda
  la máquina (cola por orden de llegada y memoria libre), lo ocupa y lo suelta al terminar, aunque el trabajo muera.
  Emulador que debe seguir encendido: `heavy-job hold --kind emulator --label '<avd>' -- <comando>`.
- **Dos grupos, cada uno con su cola:** compilar apps y correr tests comparten los huecos de CPU (`default_slots` de la
  pieza de configuración `heavy-job`, 4 por defecto); instalar dependencias, comprobar tipos y lint tienen los suyos
  («resto», 3 por defecto), que no esperan detrás de una suite. Decide el comando, no `--kind`. Un script va al resto
  solo con `--kind install|typecheck|lint|light`, y usarlo para un script que compila o corre tests es esquivar el
  semáforo.
- `tsc`, eslint, ruff y similares son ligeros: no hace falta envolverlos. phpstan y psalm no, porque usan todos los
  núcleos.
- Si hay que esperar, se lanza en segundo plano y mientras se hace trabajo ligero. Existen `--max-wait N`, `--no-wait`
  (sale con 75) y `--weight N`; `--weight 1` no sirve para colarse.
- **Desacoplado:** `heavy-job run --detach …` devuelve un id al momento y el trabajo espera y corre fuera de la sesión
  (una unidad de `systemd --user`, o una sesión propia), así que un corte de la sesión no lo mata ni le quita el turno.
  Después: `heavy-job wait <id>` (código y final de la salida), `logs <id>`, `stop <id>` y `jobs`.
- **Prioridad, solo por orden del desarrollador:** `heavy-job priority <pid> --order '<sus palabras>'` pone primero un
  trabajo que espera, y `run|hold --priority-order '<sus palabras>'` lo lanza ya primero. Exige que el desarrollador
  haya escrito en esa misma sesión en los últimos `presence_min` minutos (necesita el módulo `supervision`; sin él no
  hay prioridad). Lo que ya corre no se para.
- **Ningún proceso sobrevive a su trabajo:** todo proceso de un trabajo lleva su marca (`HEAVY_JOB_ID`) y, al terminar
  o al pararlo (`run`, también `--detach`), `heavy-job` para los que queden vivos. Un daemon que un build deja «para el
  siguiente» muere con él.
- `heavy-job status` dice quién ocupa cada hueco, la cola, la memoria y los HUÉRFANOS: workers de un runner muerto y
  procesos de un trabajo ya terminado, con el `kill <PID>` que los para. Un huérfano que gasta memoria o CPU ocupa
  hueco hasta que se para. Quien mata un runner comprueba con `heavy-job scan` que no deja nada suyo vivo.
- **Tests en la nube:** en un proyecto con `.claude/cloud-tests.json`, las suites que declara se piden con
  `~/.claude/scripts/cloud-tests request --suite <suite>` y se esperan con `cloud-tests wait <run>` en segundo plano.
  Las dos cosas son ligeras, porque la suite no corre en esta máquina. Se vuelve a `heavy-job` si contesta `LOCAL`,
  `LAUNCH_FAILED`, `EXPIRED` o `MISMATCH`, y el resultado local se anota con `record-local`. `QUEUED` es esperar turno,
  y `PREFLIGHT_FAILED` (6) se arregla y se vuelve a pedir, nunca en local. Mientras la misma suite corre en la nube
  para el mismo código, o si ya pasó en verde, `heavy-job` no la lanza (sale con 76): un 76 no se reintenta, se
  espera ese run.
- **Un run en verde de la nube es la evidencia:** para el mismo commit se cita (`cloud-tests result <run>`, y por test
  `result <run> --tests --grep <patrón>`) en lugar de repetir la suite en local. Ningún encargo prohíbe `cloud-tests` a
  una sesión o a un subagente.
- Lo impone `~/.claude/hooks/heavy-job-gate`. No se esquiva: ni mencionar `heavy-job` sin usarlo, ni esconder el comando
  en un script. Se suma a los candados de cada proyecto.
