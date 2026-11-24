# Trabajos pesados: un semáforo común a todos los proyectos (regla global)

Por qué: cada proyecto puede ordenar sus trabajos pesados, pero nadie ordena los de varios proyectos a la vez. Sin un
semáforo de máquina, las suites, los builds y los emuladores se amontonan hasta que el equipo se queda sin memoria.

- **Pesado:** emulador Android; e2e (Maestro, Playwright, `ddev e2e`); build de Gradle, `npm ci` o instalación completa;
  suite completa de pytest, PHPUnit, Jest o Vitest y las puertas `make ci|test|smoke|…e2e…`; modelos de ML (whisper,
  torch…: `--kind ml`, 2 huecos); render de vídeo (`--kind render`; un fotograma o un audio no lo es).
- **Ligero:** un test concreto (ficheros o ids explícitos, `-k`, `--filter`, `--group`, `-t`, `--grep`,
  `--collect-only`, `--list-*`) o un directorio con 5 ficheros de test o menos. En la duda:
  `~/.claude/scripts/heavy-job classify -- '<comando>'`.
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
- `heavy-job status` dice quién ocupa cada hueco, la cola, la memoria y los workers huérfanos (con el `kill` que los
  para). Quien mata un runner comprueba con `heavy-job scan` que no deja workers suyos vivos.
- Lo impone `~/.claude/hooks/heavy-job-gate`. No se esquiva: ni mencionar `heavy-job` sin usarlo, ni esconder el comando
  en un script. Se suma a los candados de cada proyecto.
