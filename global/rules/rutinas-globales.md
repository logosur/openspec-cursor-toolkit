# Rutinas programadas: siempre con el motor global (regla global)

- Una rutina nueva («rutina», «tarea programada», «avísame cuando…», «cada día…») se crea con
  `~/.claude/scripts/routines add`, no con la app: las tareas de la app quedan ligadas a la cuenta con la que se
  crearon y se paran cuando se cambia de cuenta. El motor guarda la agenda en `~/.claude/routines/` y la lanza un
  temporizador de systemd de usuario con el CLI de Claude Code, con el login que el CLI tenga en ese momento. Una tarea
  creada ya en la app se adopta con `routines import` y se desactiva en la app.
- El prompt vive en `~/.claude/scheduled-tasks/<id>/SKILL.md` y nombra los ficheros del repositorio que hay que leer,
  sin repetirlos. Corre con `dontAsk`: solo puede lo que permiten la lista común y los perfiles que la rutina declara
  (`--profile`, definidos en la configuración del módulo; `routines perms <id>` muestra el resultado). Un permiso nuevo
  se añade como perfil, no ampliando el de otra rutina.
- Una rutina no tiene las herramientas de la app. Para avisar al desarrollador usa `routines notify "<título>"
  "<texto>"` (notificación de escritorio, también anotada en un registro); lo que requiere una decisión suya va como
  «Necesita decisión» en el resumen, sin preguntar.
- `notify` sirve también a otras piezas del sistema (la supervisión lo usa para sus avisos), así que
  su forma no cambia.
- Si las rutinas se quedan sin credenciales, el propio motor avisa con un botón que abre `routines login`, que les
  da su propio token de un año. Quien lo vea sin sesión lo dice, no lo arregla por su cuenta.
- Las rutinas que dependen del navegador del desarrollador solo funcionan si la extensión y el CLI usan la misma cuenta;
  si no, quedan desactivadas y se dice.
- Toda rutina que cree el agente se anota donde el proyecto lleve sus notas.
