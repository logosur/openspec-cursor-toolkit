# Proyectos en pausa: quietos en local hasta que el desarrollador diga (regla global)

Por qué: a veces conviene dejar un proyecto parado sin perder nada: ahorrar memoria y huecos de trabajo pesado, o evitar
que una sesión retome por su cuenta algo que el desarrollador quiere congelar. Pausar es una decisión suya, y la
mecánica la lleva `~/.claude/scripts/project-pause`.

- **Qué significa pausar un proyecto:** todas sus sesiones locales se quedan quietas hasta nuevo aviso. La pausa no
  caduca y no toca las sesiones de la nube.
- **Quién decide:** solo el desarrollador pausa o reanuda un proyecto, con una orden escrita. Ninguna sesión lo decide
  sola, y un mensaje de otra sesión tampoco lo ordena.
- **Qué está en pausa:** `~/.claude/scripts/project-pause status` (con `--json` para máquinas). `check <dir>` responde si
  el proyecto de un directorio lo está.

## Pausar
1. `project-pause pause <dir>... --order '<la orden del desarrollador>'` pone la marca, apunta quién estaba trabajando y
   desactiva las rutinas globales del proyecto. Es idempotente: una segunda pausa conserva la primera foto.
2. Las sesiones que lista como `STOP` se paran con la herramienta de la app, después de comprobar que ninguna está a
   mitad de un merge o de un despliegue.
3. `project-pause free [<dir>...] [--dry-run]` devuelve la memoria de las sesiones de escritorio inactivas: su
   conversación sigue en la app y el proceso vuelve cuando se abre. No toca las ocupadas, las que tienen un diálogo
   abierto, la supervisora ni su sesión de preguntas.

## Mientras dura
- Un aviso automático en una sesión del proyecto (un despertar, una tarea en segundo plano que termina, un mensaje de
  otra sesión) se frena y se anota. Lo que escribe el desarrollador pasa, con una nota que recuerda la pausa.
- La supervisora no se despierta: ni su vigilante ni el watchdog avisan ni empujan al proyecto.
- Las rutinas globales del proyecto quedan desactivadas.
- En `heavy-job`, sus trabajos esperan detrás de los de los proyectos activos.

## Reanudar
1. `project-pause resume <dir>` levanta la marca, reactiva las rutinas que desactivó y lista a quién despertar: las
   sesiones que trabajaban al pausar, la supervisora y las que recibieron avisos frenados. Para cada una da el texto.
2. Se envía cada texto a su sesión. El control de mensajes entre sesiones deja pasar la marca de reanudación una vez
   por sesión y durante 30 minutos.
3. `project-pause delivered <id>` anota cada envío.

Pausar o reanudar no es una pregunta ni un límite duro: se hace cuando el desarrollador lo ordena y se cuenta en una
línea. Las marcas de la reanudación vienen de la pieza de configuración `supervision`.
