---
name: account-switch-resume
description: Tras un cambio de cuenta en la app, reanuda las sesiones que paró la cuenta anterior (account-switch).
---

Tarea de account-switch (regla ~/.claude/rules/cambio-de-cuenta.md). El desarrollador acaba de cambiar de cuenta de Claude en la app y quiere que sea transparente para él.

1. Ejecuta `~/.claude/scripts/account-switch brief`. Te dice qué sesiones paró la cuenta anterior y cómo reanudarlas; si dice que no queda trabajo, termina con una sola línea.
2. Haz lo que diga, sin preguntar: envía con mcp__ccd_session_mgmt__send_message, a cada sesión de la lista, exactamente el texto que indica, con su marca. Esta sesión corre en Bypass permissions, así que también aceptan el mensaje las que se cortaron con el error del límite.
3. Si un envío sale `undelivered` o `refused`, reinténtalo una vez pasado un minuto. Si sigue igual, díselo al desarrollador en una línea con el enlace de esa sesión.
4. Si `brief` dice que faltan conectores, llama a mcp__mcp-registry__suggest_connectors con los uuids que indica, para que el desarrollador tenga los botones de Conectar. No conectes nada tú: la autorización es suya.
5. Al terminar, ejecuta `~/.claude/scripts/account-switch done`.
6. Archiva las ejecuciones anteriores de esta tarea, para que no se acumulen en la barra lateral: mcp__ccd_session_mgmt__list_sessions; con mcp__ccd_session_mgmt__archive_session archiva las que tengan exactamente el título de esta tarea, no estén en marcha y no sean esta sesión.
7. Resume en dos líneas qué sesiones reanudaste y qué conectores faltan.

No hagas nada más: no toques repositorios ni sesiones que no estén en la lista.
