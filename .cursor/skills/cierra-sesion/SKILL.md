---
name: cierra-sesion
description: "Dice en lenguaje natural y en pocas líneas si queda algo pendiente para cerrar la sesión de trabajo. Auto-invoke on /cierra-sesion, queda algo pendiente, puedo cerrar la sesión, está todo terminado, me voy queda algo, cierre de sesión."
---

# Cierra sesión — veredicto de cierre en lenguaje natural

> **Command:** `.cursor/commands/cierra-sesion.md`  
> **Rule:** `.cursor/rules/cierra-sesion-check.mdc`

Responde a una sola pregunta: **¿puede el desarrollador cerrar esta sesión, o queda algo por hacer?**
La respuesta se lee en cinco líneas. Todo lo que no sea "qué falta" sobra.

Este skill **no ejecuta trabajo pendiente**: lo detecta y lo nombra. Arreglarlo es otra orden.

---

## Fase 1 — Recoger señales (solo lectura, en paralelo)

Lanzar en el mismo mensaje, sin serializar:

```bash
git status --porcelain=v1
git status -sb
git stash list
git log --oneline @{upstream}..HEAD 2>/dev/null
```

Y, si el repo tiene `openspec/`:

```bash
openspec list --json 2>/dev/null
```

Para el change tocado en la sesión (si lo hubo), contar tareas marcadas vs totales en `openspec/changes/<slug>/tasks.md`.

Además, revisar **el hilo de esta conversación** (no todo el repo) buscando:

| Señal | Qué cuenta como pendiente |
|-------|---------------------------|
| Petición sin cerrar | El desarrollador pidió algo y no se entregó resultado, o se entregó a medias |
| Rojo conocido | Tests, lint o build que fallaron y no se volvieron a ejecutar en verde |
| Verificación que falta | Se cambió código con UI observable y no se verificó en navegador |
| Entregable anunciado | Informe, captura, PDF o artefacto prometido y no producido ni abierto |
| Pregunta abierta | Decisión que se le trasladó al desarrollador y sigue sin respuesta |
| Proceso vivo | Servidor de desarrollo, watcher, tarea en segundo plano o worktree levantado en la sesión |
| Código temporal | Depuración, `dd()`, logs o mocks introducidos para avanzar y no retirados |
| Conocimiento sin anotar | Trabajo sustantivo (feature, decisión de arquitectura, bug no trivial) no anotado en el vault |

Si una señal no se puede comprobar (comando ausente, repo sin upstream), **no se inventa**: o se omite, o se dice en una línea que no se ha podido comprobar.

---

## Fase 2 — Clasificar

| Clase | Criterio | Va en la respuesta |
|-------|----------|--------------------|
| **Bloquea** | Trabajo pedido sin terminar, rojo sin resolver, entregable prometido y ausente, pregunta abierta que frena el trabajo | Sí, como viñeta |
| **Conviene** | Proceso levantado, código temporal, anotación de conocimiento, verificación no repetida | Sí, como viñeta, marcado como opcional |
| **Informativo** | Cambios sin commitear cuando nunca se pidió commitear, rama por delante del remoto sin orden de push | Una línea informativa, nunca como bloqueo |
| **Ruido** | Todo lo ya hecho, logs, rutas, detalles de implementación | No aparece |

Regla dura de las reglas globales: **no commitear ni pushear** por iniciativa propia. Que haya cambios sin subir es un dato, no una tarea pendiente, salvo que el desarrollador ya hubiera pedido subirlos en esta sesión.

---

## Fase 2b — Dudas: abrir diálogo, no adivinar

Si después de clasificar queda algo **que solo el desarrollador sabe**, se abre un diálogo de preguntas (AskQuestion en Cursor, o pregunta explícita en el chat) **antes** del veredicto.

| Duda típica | Por qué no se resuelve sola |
|-------------|------------------------------|
| Una petición del hilo quedó a medias | Solo él sabe si sigue en pie o la descartó |
| Hay trabajo empezado sin terminar | Solo él decide si se acaba ahora o se deja para la próxima sesión |
| Hay cambios sin commitear | Subirlos o no es decisión suya; el agente no commitea por su cuenta |
| Lo pedido admite dos lecturas | De la lectura depende que el trabajo esté completo o no |
| Un rojo parece ajeno al cambio | Solo él sabe si le vale cerrar con ese rojo preexistente |

Reglas del diálogo:

- **Pregunta y opciones en lenguaje natural**, bien explicadas: qué significa elegir cada opción, qué consecuencia tiene y qué pasa justo después. Nada telegráfico. Esto es la excepción explícita a la brevedad: aquí importa que se entienda, no ahorrar palabras.
- **Una sola tanda.** Como mucho las dudas reales (2–3), en un único diálogo. Nada de preguntar, responder, volver a preguntar.
- **Nunca preguntar lo comprobable**: ejecutar los tests, mirar `git status`, leer `tasks.md` o releer el hilo es trabajo del agente, no del desarrollador.
- Con la respuesta en la mano, se da el veredicto de la Fase 3 incorporándola. Si el desarrollador no contesta, el veredicto sale igual y la duda aparece como viñeta: «no sé si X sigue en pie».

---

## Fase 3 — Responder (máx. 10 líneas)

Estructura fija:

```text
<veredicto en una frase>

- <pendiente 1: qué falta y qué cuesta cerrarlo>
- <pendiente 2>
…

<acción concreta para cerrar>
```

Reglas de redacción:

- **Lenguaje natural**, el mismo idioma en que escribe el desarrollador. Nada de jerga innecesaria: «la pantalla de alta de socio no se ha probado en el navegador», no «falta QA del formulario `MemberAddForm` vía FunctionalJavascript».
- **Máximo 5 viñetas.** Si hay más, agrupar las menores en una sola («tres detalles menores de limpieza»).
- **Una línea por viñeta.** Sin sub-viñetas, sin tablas, sin bloques de código salvo un comando corto al final.
- **Nada de recapitular** lo conseguido en la sesión.
- **Incertidumbre explícita**: si algo no se ha vuelto a verificar, se dice en la propia viñeta.
- Si no queda nada: primera línea «Sí, puedes cerrar», una línea informativa opcional (p. ej. cambios sin commitear), y fin.

### Ejemplo — hay pendientes

```text
No: quedan dos cosas.

- La pantalla de alta de socio no se ha probado en el navegador desde el último cambio.
- Prometí el informe de QA en HTML y no está generado.

Dime «termínalo» y hago ambas; si prefieres cerrar ya, ninguna se pierde: el código está en la rama.
```

### Ejemplo — cierre limpio

```text
Sí, puedes cerrar. Todo lo que pediste está hecho y verificado.

Los cambios están sin commitear en la rama actual, por si quieres subirlos antes de salir.
```

---

## Argumento `detalle`

Con `/cierra-sesion detalle`, debajo del veredicto añadir **una línea por pendiente** con la evidencia decisiva: el comando que lo demuestra, el archivo afectado o la línea de salida relevante. Sin el argumento, esa evidencia no se escribe.

---

## Anti-patrones — prohibido

1. Dar veredicto sin haber ejecutado las comprobaciones de la Fase 1.
2. Inventar pendientes plausibles («quizá falten tests») sin señal que lo respalde.
3. Declarar «todo cerrado» cuando algo no se ha vuelto a verificar tras el último cambio.
4. Resolver los pendientes, commitear o pushear sin que el desarrollador lo pida.
5. Dar veredicto con una duda real sin resolver, en vez de abrir el diálogo de la Fase 2b.
6. Abrir diálogo para algo comprobable por el agente, o encadenar varias tandas de preguntas.
7. Responder con tablas, logs, rutas largas o un resumen de la sesión.
8. Superar las 10 líneas sin el argumento `detalle`.
