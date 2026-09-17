---
name: /cierra-sesion
id: cierra-sesion
category: Workflow
description: "Dice en lenguaje natural si queda algo pendiente para cerrar la sesión, sin detalle secundario"
---

# Cierra sesión — ¿queda algo pendiente?

Cuando el desarrollador invoca **`/cierra-sesion`**, **`¿queda algo pendiente?`**, **`¿puedo cerrar la sesión?`**, **`¿está todo terminado?`**, **`me voy, ¿queda algo?`** o **`cierra la sesión`**, responde con un **veredicto corto en lenguaje natural**: si puede cerrar ya, o qué falta para poder cerrar.

El objetivo es que lo sepa **leyendo 5 líneas**, sin abrir archivos, sin leer logs y sin repasar la conversación.

## Obligatorio (en el mismo turno)

1. Leer y seguir **`.cursor/skills/cierra-sesion/SKILL.md`**.
2. Recoger señales reales (git, OpenSpec, procesos en segundo plano, hilo de la conversación) **antes** de responder. Nada de veredicto por intuición.
3. Si queda una **duda que solo el desarrollador puede resolver**, abrir un diálogo de preguntas (AskQuestion en Cursor, o pregunta explícita en el chat) **antes** de dar el veredicto — nunca adivinar ni dar por cerrado lo dudoso.
4. Responder con el formato de salida de abajo. Sin tablas, sin volcados, sin recapitular lo ya hecho.

## Qué se revisa

| Señal | Cómo se comprueba |
|-------|-------------------|
| Trabajo pedido y no terminado | Peticiones del desarrollador en esta conversación sin resultado entregado |
| Tests / lint en rojo | Última ejecución de la sesión; si no se ejecutaron tras el último cambio, se dice |
| Código sin commitear o sin subir | `git status --porcelain`, `git status -sb`, `git stash list` |
| Change OpenSpec a medias | `openspec list --json` + tareas sin marcar del change tocado en la sesión |
| Procesos levantados | Servidores de desarrollo, watchers o tareas en segundo plano arrancados en la sesión |
| Entregable prometido | Informe, captura o artefacto anunciado y no entregado |
| Pregunta sin responder | Decisión que se le pidió al desarrollador y sigue abierta |
| Nota de conocimiento | Anotación en el vault de Obsidian cuando el trabajo fue sustantivo |

## Formato de salida (máx. 10 líneas)

1. **Primera línea = veredicto.** «Sí, puedes cerrar.» o «No: quedan 2 cosas.»
2. **Hasta 5 viñetas**, una línea cada una, en lenguaje llano: qué falta y qué costaría cerrarlo. Sin jerga, sin rutas largas, sin nombres de función salvo que sean imprescindibles.
3. **Última línea = acción concreta**: el comando exacto que lo cierra, o la frase que hay que decirme para que lo termine yo.

Si algo no se puede afirmar con certeza (p. ej. no se sabe si los tests siguen verdes), decirlo en esa misma viñeta: «no lo he vuelto a comprobar desde el último cambio». Nunca dar por bueno lo no verificado.

## Dudas → diálogo de preguntas

Si el estado de algo **no se puede determinar leyendo el repo ni el hilo**, no se asume: se abre un diálogo (AskQuestion, o pregunta explícita en el chat) con la pregunta en lenguaje natural y opciones bien explicadas (qué significa elegir cada una y qué pasa después). Casos típicos:

- No está claro si algo que pidió a medio camino sigue en pie o lo descartó.
- Hay trabajo a medias y no se sabe si quiere terminarlo ahora o dejarlo para mañana.
- Hay cambios sin commitear y no se sabe si quiere subirlos antes de cerrar.
- El alcance de lo pedido admite dos lecturas y de ello depende si queda pendiente o no.

**No se pregunta** lo que el agente puede comprobar por sí mismo (ejecutar los tests, mirar `git status`, leer `tasks.md`): eso se comprueba. Una vez respondido el diálogo, se da el veredicto incorporando la respuesta, sin volver a preguntar.

## Argumento `detalle`

`/cierra-sesion detalle` añade, debajo del veredicto, una línea por pendiente con la evidencia concreta (comando, archivo o salida decisiva). Sin el argumento, esa evidencia **no** se incluye.

## Prohibido

- Resumir lo que ya se hizo en la sesión: solo importa lo que queda.
- Listar cambios sin commitear como bloqueo cuando el desarrollador nunca pidió commitear — se menciona en una línea informativa, no como pendiente.
- Commitear, pushear, arreglar o cerrar nada por iniciativa propia: este comando **solo informa**.
- Dar un veredicto «todo cerrado» cuando hay una duda real sin resolver: primero el diálogo, después el veredicto.
- Abrir diálogo para cosas comprobables por el agente, o encadenar varios diálogos seguidos.
- Tablas, bloques de log, rutas completas innecesarias o párrafos de contexto.

## Relacionado

| Item | Ruta |
|------|------|
| Skill | `.cursor/skills/cierra-sesion/SKILL.md` |
| Regla | `.cursor/rules/cierra-sesion-check.mdc` |
| Sumario de spec | `.cursor/commands/sumario-spec.md` |
| Cierre de spec | `.cursor/commands/finaliza-spec.md` |
