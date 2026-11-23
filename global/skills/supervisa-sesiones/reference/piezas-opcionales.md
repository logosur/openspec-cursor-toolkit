# supervisa-sesiones: piezas opcionales

> Referencia del núcleo (`../SKILL.md`). Se lee cuando una señal, un hook o el proyecto nombra una pieza que no viene
> con el módulo `supervision`.

El método funciona solo con el módulo `supervision` (y `core`). Algunas máquinas añaden piezas que lo amplían. Si una
falta, la función que da no existe: se dice así en el parte o en el informe y se sigue sin ella, sin imitarla a mano.

| Pieza | Qué aporta | Sin ella |
|-------|------------|----------|
| Módulo `heavy-jobs` | Cola común para suites, builds y emuladores; señales `QUEUED` y `SLOTHELD` | Las suites se lanzan con lo que documente el proyecto, una a una |
| Módulo `sessions` | Exige que las sesiones nazcan sin diálogos de permiso, si el desarrollador lo eligió | El modo de cada sesión es el que tenga |
| Módulo `openspec` | Changes, `tasks.md` y la orden `/cierra-sesion` | El trabajo sale de las reglas y de lo que cada sesión tiene entre manos |
| Módulo `devtools` | Herramientas de desarrollo de la máquina | Las del proyecto |
| Vigía externo | Avisa al desarrollador si el proceso de la supervisora muere | Lo descubre el desarrollador al abrirla |
| Tarea programada de reanimación | Despierta una supervisora sin proceso | Igual que la anterior |
| Detector de devoluciones de trabajo | Reconoce textos que dejan trabajo al desarrollador (`HANDOFF`) | `IDLE` en guardia y la lectura del último mensaje |
| Corredor de pruebas en la nube | Lanza suites fuera de la máquina | Se corren en local |
| Lector de sesiones en la nube | `$L cloud` y señales `CLOUD` | Esas sesiones no se ven; se dice |
| Cambio automático de cuenta | Reanuda sesiones cortadas por un límite en otra cuenta | `CUT` y el mensaje de reanudación de la supervisora |
| Pausa de proyectos | Duerme un proyecto entero (`RESUMED` al volver) | No hay pausas |
| Aviso entre sesiones | Empuja sesiones ociosas con un mensaje | Lo hace la escalera de §W |
| Herramienta de segunda opinión | Un consejo antes de una decisión compleja | El panel |

Ninguna de estas piezas concede autorizaciones: commit, publicación, despliegue y archivado siguen pidiendo una regla
escrita del proyecto o una orden del desarrollador.
