---
name: reanimar-supervisoras
description: Cada 15 min despierta, con supervisor-lock revive, a las supervisoras cuyo proceso murió, a las vivas cuyo turno cortó el límite de uso y llevan 45 min sin latido cuando la cuenta vuelve a tener uso, y a las que llevan 45 min sin atender sesiones de su proyecto.
---

Tarea de la app que reanima supervisoras. Vive en la app a propósito: una sesión cuyo proceso murió (reinicio de la app, cambio de cuenta) solo la puede despertar la propia app, y una rutina de la máquina no tiene esa herramienta. Cubre tres casos, que cada elemento de `targets` dice en `reason`: `dead` (el proceso murió), `stalled` (el turno lo cortó el límite de uso o un error de la API y lleva 45 min sin latido fuera de la guardia, o ese corte lo causó el límite de uso, también en la guardia, y la cuenta ya tiene uso) y `unattended` (lleva 45 min sin atender sesiones de su proyecto). El envío es el mismo en los tres.

1. Ejecuta `~/.claude/scripts/supervisor-lock revive --json`.
2. Para cada elemento de `targets`: envía con mcp__ccd_session_mgmt__send_message, a `session_id`, exactamente el texto de `message`, sin cambiar nada. Lleva la marca de reanimación, que el control de mensajes deja pasar solo para lo que acaba de señalar ese comando. Después ejecuta `~/.claude/scripts/supervisor-lock revive --sent <session_id> --delivery <delivered|queued|error>` con el resultado del envío.
3. Archiva las ejecuciones anteriores de esta tarea, para que no se acumulen en la barra lateral: mcp__ccd_session_mgmt__get_session con "self" te da el título de esta sesión; con mcp__ccd_session_mgmt__list_sessions y mcp__ccd_session_mgmt__archive_session archiva las que tengan exactamente ese título, no estén en marcha y no sean esta sesión.
4. Termina con una sola línea. Si `targets` estaba vacío, «Nada que reanimar» o lo que digan `notes`. Si no, una línea por supervisora con su proyecto, el motivo (proceso muerto, turno cortado o sesiones sin atender) y el resultado del envío.

No hagas nada más: no toques repositorios, no escribas a otras sesiones ni preguntes nada. Si un comando falla, dilo en esa línea final y termina.
