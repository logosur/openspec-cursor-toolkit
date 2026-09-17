---
description: "Agente supervisor maestro sobre todas las sesiones y proyectos: ordena el trabajo, no para hasta que cada sesión cierre lo suyo, informa de cada sesión liberada y de lo que entregó (nunca la archiva: archivar es decisión tuya, después), pregunta lo que dependa del desarrollador y termina con merge en cascada y deploy desatendido"
argument-hint: "[alcance] [--projects a,b,c] [--no-deploy] [--hasta-main] [--max-rondas N]"
---

# Supervisa sesiones — agente maestro por encima de todas las sesiones

Cuando el desarrollador invoca **`/supervisa-sesiones`**, **`supervisión maestra`**, **`supervisa maestro`**, **`supervisa maestra`**, **`supervisor maestro`**, **`supervisa todas las sesiones`**, **`agente maestro supervisor`**, **`orquesta todas las sesiones y ciérralas`**, **`termina todo lo pendiente de todos los proyectos`** o **`merge en cascada y deploy de todo`**, ejecuta la skill supervisora: una capa por encima de todas las sesiones de trabajo abiertas que las ordena, las cierra una a una y acaba en merge en cascada y deploy desatendido.

## Obligatorio (en el mismo turno)

1. Leer y seguir **`.claude/skills/supervisa-sesiones/SKILL.md`**.
2. Tomar el cerrojo de supervisor único (§0) **antes de nada**; si hay otro supervisor vivo, no arrancar y abrir el diálogo de relevo.
3. Abrir el registro `.claude/context/supervisor/SUPERVISOR-<YYYYMMDD-HHMM>.md` y escribirlo **después de cada transición de fase**.
4. Censar las sesiones reales antes de decidir nada — y verificar el estado de cada repo con git, no con el título de la sesión.
5. No terminar mientras quede una sesión sin declarar resuelto lo suyo o una decisión del desarrollador sin preguntar.
6. Cerrar con el informe de §11, liberar el cerrojo y la línea literal `Supervisor verdict: <VERDICT>`.

## Fases

| # | Fase | Qué hace |
|---|------|----------|
| F0a | Supervisor único | Toma el cerrojo global, o cede ante el supervisor que ya está vivo |
| F0b | Parseo + registro | Alcance, flags, fichero de estado |
| F1 | Censo | Sesiones, proyectos, ramas, worktrees, estado git real |
| F2 | Interrogatorio | Cada sesión reporta lo suyo con contrato fijo |
| F3 | Colisiones + turnos | Un solo escritor por repo, rama y servicio |
| F4 | Convergencia | Rondas de turnos hasta que todas cierran |
| F4b | Liberación | Cada sesión que termina lo suyo → informe en lenguaje natural de que está libre y de lo que entregó; **nunca se archiva**: eso lo decides tú después |
| F5 | Decisiones | Diálogos agrupados al desarrollador |
| F6 | Ejecución | Subagentes supervisados, verificados en disco |
| F7 | Cascada | `main → develop` (recuperar) → feature → `develop` → `main` |
| F8 | Deploy | `unattended-deploy on` → comando del proyecto → verificar → `off` |
| F9 | Cierre | Rezagados, vault, informe y **liberación del cerrojo** |

## Flags

| Flag | Efecto |
|------|--------|
| `--projects a,b,c` | Limita el censo a esos repos |
| `--no-deploy` | Llega hasta el merge autorizado; no despliega |
| `--hasta-main` | Autoriza la cascada hasta `main` en proyectos con ese flujo documentado. **Sin él, para en `develop`** |
| `--max-rondas N` | 1–10, default 5 |

## Liberación de sesiones (F4b)

En cuanto una sesión declara que ya no le queda nada propio —y el supervisor lo ha verificado en el repo: todo commiteado y pusheado, sin stash, sin tareas sin marcar, decisiones y hallazgos ya delegados— **se informa de que está libre**, sin esperar al final. **El supervisor nunca archiva sesiones**: no llama a `archive_session`, no pregunta «¿archivo esta sesión?» ni abre diálogo alguno para ello. Archivarla o no es decisión del desarrollador, después, cuando le convenga.

El informe es un resumen de 2–3 líneas en lenguaje llano, por sesión: qué hacía, dónde quedó (rama, commit, pusheado, qué se verificó) y qué entregó al supervisor (decisiones y hallazgos ya en la cola de F5). Termina siempre con la misma frase: «Queda libre; archivarla es decisión tuya, más adelante».

Tras el informe la sesión pasa a `RELEASED`: no se le da más trabajo, no se vuelve a informar de ella y aparece en el informe final como libre. Un informe por ronda (agrupando las sesiones liberadas en esa ronda), nunca uno por sesión encadenado. La sesión supervisora se lista al final, en F9, con las demás. Si una sesión ya informada vuelve a tocar el repo, vuelve a `WORKING` y se dice en el informe.

## Supervisor único y tareas colgadas

**Un solo supervisor maestro vivo.** Antes de nada se toma un cerrojo global del usuario — `~/.claude/supervisor/MASTER.lock.d`, creado con `mkdir` (atómico) — con `owner.json` que guarda sesión, repo, registro, estado y **latido**. El latido se reescribe en cada transición de fase y en cada ronda.

| Situación | Qué hace |
|-----------|----------|
| Otro supervisor vivo y latiendo | **No arranca.** Dice quién supervisa y desde cuándo, y ofrece: dejarle seguir (recomendada) · tomar el relevo (reanudando **su** registro) · mandarle el alcance nuevo y salir |
| Cerrojo sin latido > 30 min **y** sesión dueña inexistente | Huérfano: se reclama y se anota quién era el dueño anterior |
| Es esta misma sesión (reanudación) | Reclama el cerrojo y continúa su registro, sin empezar de cero |
| Cierre | El cerrojo **se libera siempre** en F9, también tras un bloqueo. Solo `AWAITING DEVELOPER DECISION` lo mantiene en `paused`, y caduca a las 2 h |

Nunca se mata la otra sesión ni se borra su cerrojo por iniciativa propia.

**Nada se queda colgado (§W).** Todo lo que el supervisor lanza —turno de escritura, subagente, espera, deploy, comando en segundo plano— se anota en la tabla **Trabajo en vuelo** con `inicio`, `deadline` y `última señal`, y se barre al empezar cada ronda:

| Unidad | Plazo por defecto | Al vencer |
|--------|------------------|-----------|
| Turno de escritura | 30 min | Recordatorio; a la segunda se le retira el turno y pasa a la siguiente sesión |
| Reporte de F2 | 15 min | Se deriva su estado del repo y del transcript; si no, `NO CONTACTABLE` → decisión |
| Subagente de F6 | 20 min | `TaskStop`, se verifica en disco lo que dejó, su decisión vuelve a la cola |
| Espera externa (CI, deploy) | Lo que diga el runbook; si no, 30 min | `STALLED` y se sigue con los demás proyectos |
| Comando en segundo plano | 10 min sin salida nueva | Se para y se cita la última línea que produjo |

Un bloqueo mutuo entre sesiones se rompe por criterio determinista (escribe primero la más avanzada) y, si ninguna lo es, se pregunta. Lo colgado **sale del camino crítico**: los proyectos que no dependen de ello siguen hasta el deploy; el que sí depende queda `READY TO DEPLOY` o `BLOCKED`, nunca se mergea «a ver si cuela». Todo `STALLED` va a la cola de decisiones y, verbatim, al **Residual** del informe.

Se puede parar lo que lanzó este supervisor (`TaskStop`, retirar un turno). Matar procesos, sesiones, worktrees o ramas de otra sesión **se pregunta**.

## Qué se pregunta y qué no

**Se pregunta** (`AskUserQuestion`, en tandas de hasta 4, opciones explicadas en lenguaje natural): hallazgos que no pertenecen a ninguna sesión, alcance ambiguo, prioridad entre sesiones que se estorban, rojos preexistentes, riesgos de publicación, y qué hacer con una sesión que no responde.

**No se pregunta** lo que el agente puede comprobar: si los tests pasan, qué dice `git status`, qué tareas quedan sin marcar, qué rama va por delante.

Silencio o timeout **no** son un sí: el veredicto pasa a `AWAITING DEVELOPER DECISION` con las preguntas escritas.

## Límites duros

- Una sesión no se da por cerrada hasta que **ella** lo declara, o queda documentada como bloqueada con motivo concreto.
- El reporte de una sesión o de un subagente **nunca** decide una puerta: gana lo que diga el repo.
- Nunca dos sesiones escribiendo el mismo repo, rama, worktree o servicio a la vez.
- `main` solo con `--hasta-main` y flujo documentado. Producción solo si la orden la nombra. **Mergear no es desplegar.**
- Nada de `push --force`, reescritura de historia ni borrado por iniciativa propia.
- No archivar **ninguna** sesión, nunca, ni llamar a `archive_session`: el supervisor solo informa de que está libre; archivarla es decisión del desarrollador, después.
- Solo un supervisor maestro vivo: con otro activo no se arranca, y su cerrojo no se reclama sin comprobar latido **y** existencia de la sesión.
- Ninguna espera es indefinida: lo que vence su plazo se aparta y se pregunta; nunca frena a quien no dependa de ello.
- El modo desatendido se desarma, y el cerrojo se libera, siempre al terminar.

## Relacionado

| Item | Ruta |
|------|------|
| Skill | `.claude/skills/supervisa-sesiones/SKILL.md` |
| Cierre de una sesión | `.claude/commands/cierra-sesion.md` |
| Loop de una spec | `.claude/commands/run-spec.md` |
| Pipeline de revisión | `.claude/commands/repasa-spec.md` |
