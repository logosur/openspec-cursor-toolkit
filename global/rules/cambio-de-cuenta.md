# Cambio de cuenta de Claude: transparente para el desarrollador (regla global)

Por qué: cuando una cuenta se queda sin uso y el desarrollador cambia a otra en la app, las sesiones que paró la cuenta
anterior siguen paradas, y la CLI y las rutinas siguen con la sesión iniciada en la organización vieja. Nadie debería
tener que reanudarlas una a una.

## Lo que hace la máquina sola
- `claude-sessions-sync` copia la lista de sesiones de la app a todas las cuentas y avisa a `account-switch` cuando la
  app cambia de cuenta u organización.
- `account-switch` anota el cambio con las sesiones que la cuenta anterior dejó paradas y comprueba los inicios de sesión
  de la CLI y de las rutinas. Si falta alguno, abre una terminal para que el desarrollador autorice en su navegador.
- La tarea de la app `account-switch-resume`, que `account-switch arm` deja preparada en cada cuenta inactiva, o la
  primera sesión de la app que arranca después (hook `SessionStart`), recibe la lista y reanuda esas sesiones.
- Una sesión con rol de supervisión (la dueña de un cerrojo de `supervisor-lock` o su sesión de cierre) pasa los ratos
  entre turnos esperando a un vigilante en segundo plano, y el cambio de cuenta lo mata sin dejar rastro de corte en su
  transcripción. `account-switch` la anota como «vigilante» si el latido de su cerrojo es reciente, y le envía el aviso
  de reanudación con una frase más: rearmar su vigilante (`supervisor-lock wait`, o `wait-closer` la sesión de cierre).
  Deja de estar pendiente en cuanto recibe el aviso o ejecuta un turno después del cambio.
- La sesión de preguntas de una supervisión (el `mailbox` de su cerrojo) pierde con el cambio el diálogo que tuviera
  abierto. Si `ask-queue` tiene alguna pregunta en `asked` dirigida a ella, `account-switch` la anota como «questions»,
  con su propio texto: volver a presentar esas preguntas sin cambiarlas. Sigue pendiente hasta que recibe ese texto, se
  archiva o ya no queda ninguna sin contestar; haber ejecutado un turno no basta.
- Si la cuenta nueva tampoco tiene uso, el cambio espera a que vuelva (`not_before`) y nadie lo reclama antes.

## Lo que hace el agente
- Si recibe la lista de sesiones que paró la cuenta anterior, las reanuda antes de seguir con lo suyo, sin preguntar,
  aunque sean de otros proyectos o su encargo sea otro. Al terminar ejecuta `account-switch done`. Si la lee pasada la
  hora de «Vale hasta las HH:MM», no envía nada ni pregunta: ya se encarga otra sesión.
  - Antes de enviar, y otra vez si su turno se corta o se compacta, ejecuta `account-switch mine`. Si dice «No», no
    envía nada, no ejecuta `done` y sigue con lo suyo. Si dice «Sí», envía solo a las que lista.
  - Si de verdad no puede enviar, ejecuta `account-switch release`, para que otra sesión tome el aviso.
  - Si el envío sale `refused` o `undelivered`, pide en una línea que se ponga en Bypass permissions la sesión que
    envía, y reintenta. Las sesiones cortadas por el error del límite solo aceptan el aviso de una sesión en Bypass.
- Los avisos de reanudación pasan el control de mensajes entre proyectos solo si la configuración de `supervision` activa
  la excepción `account_switch` (`message_exceptions`). Un mensaje con la marca fuera de ese flujo se rechaza.
- Antes de dar un límite por vigente mira el uso real (`get_usage`): la cuenta puede haber cambiado, y también el plan.
  `account-switch status` lo vuelve a comprobar y dice «sin comprobar» cuando no puede.
- **Conectores** (correo, calendario, documentos…): son de cada cuenta y no se copian. El agente nunca autoriza uno: pone
  el botón de Conectar y autoriza el desarrollador. `account-switch connectors` dice cuáles faltan.
- No viajan con el cambio las sesiones y rutinas de la nube, los artefactos ni los conectores. Viajan las sesiones locales
  y las rutinas de la máquina.
- `account-switch doctor` y `account-switch status` comprueban todas las piezas sin cambiar nada.
