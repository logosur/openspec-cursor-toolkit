---
description: "Abre un único diálogo de selección múltiple que explica qué queda pendiente de esta sesión, de otras (con dueña) y lo huérfano, y deja marcar qué hacer con cada cosa"
argument-hint: "[detalle]"
---

# Cierra sesión — un diálogo con casillas

Cuando el desarrollador invoca **`/cierra-sesion`**, **`¿queda algo pendiente?`**, **`¿puedo cerrar la sesión?`**, **`¿está todo terminado?`**, **`me voy, ¿queda algo?`** o **`cierra la sesión`**, haz tres cosas en este orden: **censar** lo pendiente, **abrir un único diálogo de selección múltiple** que lo explique y deje marcar acciones, y **ejecutar lo marcado**.

El diálogo **es** el informe: no se escribe antes un listado que lo repita. El desarrollador lo entiende leyendo las preguntas, sin abrir archivos ni repasar la conversación.

## Obligatorio (en el mismo turno)

1. Leer y seguir **`.claude/skills/cierra-sesion/SKILL.md`**.
2. Recoger señales reales (git, OpenSpec, procesos, hilo de la conversación y el censo de propietarias `python3 .claude/skills/cierra-sesion/session-owners.py`) **antes** de montar el diálogo. Nada por intuición.
3. Abrir **una sola llamada** a `AskUserQuestion` (AskQuestion en Cursor) con **hasta 4 preguntas, todas de selección múltiple** (`multiSelect: true`). Un bloque sin nada que decidir no se pregunta:

   | Bloque | Qué explica | Casillas posibles |
   |--------|-------------|-------------------|
   | **Esta sesión** | Lo que falta de esta sesión | Commit de mis ficheros, push, deploy (nunca recomendado), terminar lo que falta |
   | **Con dueña** | Pendientes ajenos con sesión viva (no se tocan) | Avisar a cada dueña (mismo proyecto; el aviso no autoriza nada) |
   | **Huérfanos** | Lo que ninguna sesión viva tiene | Cerrar los worktrees huérfanos limpios, retomar un huérfano con trabajo (solo lectura), revisar stashes |
   | **Al terminar** | Dónde está esta sesión | Cerrar el worktree, archivar la sesión |

4. **La interfaz enseña una pregunta cada vez**, así que **el texto de TODAS las preguntas abre con el mismo resumen de tres líneas, siempre las tres**: `De esta sesión:` / `De otras sesiones:` (con dueña viva, con su nombre) / `Huérfano, sin sesión:`; «Nada.» si no hay nada, y nunca una línea omitida porque ese bloque no tenga casillas. Va en **frases llanas**, diciendo qué es y de quién, sin jerga («orden tuya», «solo lectura», «árbol limpio»). Tras el resumen y una línea en blanco va la pregunta propia del bloque y cada opción dice su efecto. Máximo 4 opciones por pregunta: lo que sobre se **agrupa** («los 7 worktrees limpios»). La herramienta no preselecciona: lo recomendado va **primero** y con «(Recomendada)»; **solo se ejecuta lo marcado** y sin casillas no se hace nada.
5. Ejecutar lo marcado en este orden: terminar lo que falta, commit, push, deploy, avisos, huérfanos, cierre del worktree, informe y, lo último, archivar la sesión. Cada paso que no pueda completarse corta los que dependían de él y se dice.
6. Cerrar con el informe corto de abajo. Sin tablas, sin volcados, sin recapitular lo ya hecho.

## Qué se revisa

| Señal | Cómo se comprueba |
|-------|-------------------|
| Trabajo pedido y no terminado | Peticiones del desarrollador en esta conversación sin resultado entregado |
| Tests / lint en rojo | Última ejecución de la sesión; si no se ejecutaron tras el último cambio, se dice |
| Cambios sin commitear o sin subir | `git status --porcelain`, `git status -sb`, `git stash list`; separar los ficheros de esta sesión de los de otras |
| Pendientes de otras sesiones y su dueña | `session-owners.py`: worktrees, checkout principal, stashes y stacks sin carpeta frente a las sesiones vivas (pid existente y hora de arranque coincidente) **y a su actividad** (procesos dentro del árbol, ediciones recientes, stack encendido): una sesión que trabaja por ruta absoluta cuenta como dueña. `HUÉRFANO` no prueba que nadie lo lleve; se repite el censo antes de actuar |
| Change OpenSpec a medias | `openspec list --json` + tareas sin marcar del change tocado en la sesión |
| Procesos levantados | Servidores de desarrollo, watchers o tareas en segundo plano arrancados en la sesión |
| Entregable prometido | Informe, captura o artefacto anunciado y no entregado |
| Pregunta sin responder | Decisión que se le pidió al desarrollador y sigue abierta |
| Nota de conocimiento | Si el trabajo fue sustantivo y falta en el vault de Obsidian, se escribe antes del diálogo sin preguntar; nunca es una casilla |
| Política de publicación | Línea literal `session-close: publish-own-work` en `CLAUDE.md` o en una regla del proyecto, **versionada y presente en `HEAD`**; sin ella, `ask`. El skill nunca la escribe |

## Informe final (máx. 10 líneas)

1. **Primera línea = veredicto.** «Sí, puedes cerrar.» solo si no queda nada de **esta** sesión; si no, «No: quedan 2 cosas de esta sesión.» Lo de otras sesiones no cambia el veredicto.
2. **Hecho:** commit con su hash, qué se subió, avisos enviados, worktrees cerrados.
3. **Sigue pendiente:** una viñeta por cosa, con su dueña o «huérfano»; «Nada.» si no queda.
4. **Siguiente orden posible:** la frase exacta que cierra lo que falte.

Si algo no se puede afirmar con certeza (no se sabe si los tests siguen verdes, no se pudo hacer el censo de propietarias), decirlo. Nunca dar por bueno lo no verificado.

## Argumento `detalle`

`/cierra-sesion detalle` añade a la descripción de cada opción la evidencia concreta (comando, ruta del worktree, pid de la sesión propietaria). Sin el argumento, esa evidencia **no** se incluye.

## Prohibido

- Preguntas de selección única, varias tandas, o un listado previo que repita el diálogo.
- Resumir lo que ya se hizo en la sesión: solo importa lo que queda.
- Mezclar los bloques, o afirmar una propietaria que el censo no respalda.
- Tocar, commitear, fusionar o borrar trabajo de otra sesión (huérfano incluido) o cerrar otra sesión. Un huérfano solo admite las casillas del diálogo: cerrarlo si está limpio, retomarlo en solo lectura, revisar sus stashes. Fusionarlo o commitear sus cambios pide una orden aparte, por nombre.
- Avisar a sesiones de otro proyecto o redactar un aviso que parezca autorizar commit, push, merge o deploy.
- Commit, push, deploy o cierre sin la casilla correspondiente; recomendar el deploy; forzar un push, saltarse los hooks de git o usar `git add -A`.
- Tratar un proyecto como `publish-own-work` sin la línea literal versionada en `HEAD`, escribir esa línea, o pasar de la rama de la sesión (merge a la principal, deploy) sin marcarlo.
- Dar un veredicto «todo cerrado» cuando hay una duda real sin resolver.

## Relacionado

| Item | Ruta |
|------|------|
| Skill | `.claude/skills/cierra-sesion/SKILL.md` |
| Censo de propietarias | `.claude/skills/cierra-sesion/session-owners.py` |
| Sumario de spec | `.claude/commands/sumario-spec.md` |
| Cierre de spec | `.claude/commands/finaliza-spec.md` |
