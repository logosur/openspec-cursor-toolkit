# supervisa-sesiones: piezas opcionales

> Referencia del núcleo (`../SKILL.md`). Se lee cuando una señal, un hook o el proyecto nombra una pieza que amplía el
> módulo `supervision`.

El método funciona solo con el módulo `supervision` (y `core`). Unas piezas vienen con él y otras con otros módulos
opcionales del toolkit, o las pone la máquina. Si una falta, la función que da no existe: se dice así en el parte o en
el informe y se sigue sin ella, sin imitarla a mano.

| Pieza | Qué aporta | Sin ella |
|-------|------------|----------|
| Módulo `heavy-jobs` | Cola común para suites, builds y emuladores; señales `QUEUED` y `SLOTHELD` | Las suites se lanzan con lo que documente el proyecto, una a una |
| Módulo `sessions` | Exige que las sesiones nazcan sin diálogos de permiso, si el desarrollador lo eligió | El modo de cada sesión es el que tenga |
| Módulo `openspec` | Changes, `tasks.md` y la orden `/cierra-sesion` | El trabajo sale de las reglas y de lo que cada sesión tiene entre manos |
| Módulo `devtools` | Herramientas de desarrollo de la máquina | Las del proyecto |
| Vigía externo | Avisa al desarrollador si el proceso de la supervisora muere | Lo descubre el desarrollador al abrirla |
| Tarea programada de reanimación (su prompt viene con `supervision`; la tarea se crea en la app) | Despierta una supervisora sin proceso, y una viva cuyo turno se cortó (límite de uso, error de la API) y lleva 45 min sin latido fuera de la guardia (el corte por el límite de uso cuenta también en la guardia), y una viva cuyo cerrojo sigue en pausa por el límite de uso, en cuanto la cuenta vuelve a tener uso | Igual que la anterior |
| Detector de devoluciones de trabajo (`handoff-guard`, con `supervision`) | Reconoce textos que dejan trabajo al desarrollador (`HANDOFF`) | `IDLE` en guardia y la lectura del último mensaje |
| Corredor de pruebas en la nube (`cloud-tests`, módulo `heavy-jobs`) | Lanza suites fuera de la máquina | Se corren en local |
| Lector de sesiones en la nube | `$L cloud` y señales `CLOUD` | Esas sesiones no se ven; se dice |
| Cambio automático de cuenta (`account-switch`, módulo `accounts`) | Reanuda sesiones cortadas por un límite en otra cuenta | `CUT` y el mensaje de reanudación de la supervisora |
| Pausa de proyectos (`project-pause`, con `supervision`) | Duerme un proyecto entero (`RESUMED` al volver) | No hay pausas |
| Aviso entre sesiones (`session-nudge`, con `supervision`) | Empuja sesiones ociosas con un mensaje | Lo hace la escalera de §W |
| Rutinas de la máquina (`routines`, módulo `routines`) | Avisos de escritorio (`routines notify`) y tareas programadas que no dependen de la cuenta | Los avisos no salen; se dice en el informe |
| Herramienta de segunda opinión | Un consejo antes de una decisión compleja | El panel |

Con el corredor de pruebas en la nube, al dar un encargo (F2, F6) que vaya a correr tests:

- un conjunto de pasadas que en total es una suite (lotes, varias órdenes seguidas) es una suite: va a la nube si el
  proyecto la declara, o a una sola pasada con `heavy-job run`;
- ningún encargo prohíbe `cloud-tests` a una sesión o a un subagente;
- un run en verde de la nube para el mismo commit se cita como evidencia (`cloud-tests result <run>`, por test con
  `--tests --grep <patrón>`) en vez de repetirlo en local.

Ninguna de estas piezas concede autorizaciones: commit, publicación, despliegue y archivado siguen pidiendo una regla
escrita del proyecto o una orden del desarrollador.
