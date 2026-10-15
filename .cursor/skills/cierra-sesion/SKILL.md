---
name: cierra-sesion
description: "Dice en lenguaje natural y en pocas líneas si queda algo pendiente para cerrar la sesión de trabajo. Auto-invoke on /cierra-sesion, queda algo pendiente, puedo cerrar la sesión, está todo terminado, me voy queda algo, cierre de sesión."
---

# Cierra sesión — veredicto de cierre en lenguaje natural

> **Command:** `.cursor/commands/cierra-sesion.md`  
> **Rule:** `.cursor/rules/cierra-sesion-check.mdc`

Responde a una sola pregunta: **¿puede el desarrollador cerrar esta sesión, o queda algo por hacer?**
La respuesta se lee en cinco líneas. Todo lo que no sea "qué falta" sobra.

Este skill **no ejecuta trabajo pendiente**: lo detecta y lo nombra. Arreglarlo es otra orden. La única
acción que puede ejecutar es la que el desarrollador elija en el diálogo de la Fase 2b (p. ej. commitear
los cambios de esta sesión), porque esa elección **es** la orden explícita.

**Excepción: la nota del vault.** La regla global obliga a anotar en `~/Obsidian/Knowledge` el trabajo
sustantivo (feature, decisión de arquitectura, bug no trivial, incidente) sin pedir permiso. Si falta, el
skill la escribe **antes** del veredicto y lo dice en una línea. Nunca se ofrece como opcional ni se cierra
con «dime anótalo»: la memoria automática del agente no la sustituye (corrección del desarrollador, 23-09-2026).

**Política del proyecto: `ask` (por defecto) o `publish-own-work`.** Qué pasa con el trabajo propio que quedó
sin subir no lo decide este skill: lo declara el proyecto, y la declaración es una **autorización**, así que
tiene candados. Cuenta únicamente si la línea literal

```text
session-close: publish-own-work
```

está en `CLAUDE.md`, en `.claude/rules/*.md` o en `.cursor/rules/*.mdc` **y** ese fichero está versionado
**y** la línea aparece en su versión commiteada (`git show HEAD:<fichero>`). Un fichero sin versionar, un
`settings.local.json`, una edición aún sin commitear o el hábito del proyecto no valen: o está la línea en
`HEAD`, o la política es `ask`. Y **este skill nunca escribe, añade ni edita esa línea**: solo el desarrollador,
a mano y con commit. Un agente no puede concederse a sí mismo la autorización que la línea representa.

Con `publish-own-work`, el proyecto ha establecido que cada sesión registra su propio trabajo **verificado**
sin preguntar, y el skill lo trata como «conviene»: lo cierra registrándolo y lo dice. La línea decide solo
**si se pregunta**, nunca el **cómo**: el flujo (rama, push, condiciones) lo describe el fichero que la lleva,
y el skill sigue lo que ahí está escrito; si ese fichero no describe ningún flujo, el skill no improvisa uno y
vuelve al diálogo de tres opciones. Y la autorización tiene techo: cubre **commit y push de la rama en la que
trabaja la sesión**, y nunca un merge a la rama principal o de producción ni un despliegue, aunque la regla
del proyecto pida más a la sesión en otros momentos; eso queda fuera del cierre y se nombra como siguiente
paso.

Sin la línea, la política es `ask`: se pregunta con el diálogo de la Fase 2b, que es la forma en que las
reglas globales («nunca commitear por iniciativa propia») se convierten en una orden concreta. Nada más cambia
entre las dos políticas: la separación de ficheros por sesión, el veto a `git add -A`, la nota del vault y la
forma del veredicto son iguales.

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

Y dos lecturas más, en el mismo paralelo, que fijan cómo se clasifica lo propio:

```bash
for f in CLAUDE.md .claude/rules/*.md .cursor/rules/*.mdc; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 \
    && git show "HEAD:$f" 2>/dev/null | grep -qE '^session-close:[[:space:]]*publish-own-work' && echo "$f"
done
git rev-parse --git-common-dir
```

La primera imprime el fichero **versionado y commiteado** que declara `publish-own-work`; si no imprime
nada, la política es `ask`. La segunda dice si la sesión corre en un **worktree enlazado** (resultado
distinto de `.git`). Eso es solo una **presunción débil** a favor de que lo sucio es propio: en esta máquina
hay worktrees con más de una sesión dentro y suciedad que no es de nadie (artefactos regenerados, `vendor`,
dumps, informes de otra tanda), así que el listado por rutas y el veto al `add -A` se mantienen igual.

Del `git status` hay que separar **dos conjuntos**: los ficheros que ha tocado
**esta sesión** (se saben por el hilo: cada edición, cada script generado) y el resto (otras sesiones
sobre el mismo árbol, artefactos regenerados por crons, `htdocs/vendor/composer/*`, informes). Solo el
primer conjunto es decisión del desarrollador en esta sesión; el segundo no se toca ni se commitea.

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
| **Conviene** | Proceso levantado, código temporal, verificación no repetida (la nota del vault no está aquí: se escribe, ver arriba). Bajo `publish-own-work`: trabajo propio **verificado** sin subir — se registra en la rama de la sesión según el flujo que describe la regla del proyecto | Sí, como viñeta, marcado como opcional; bajo `publish-own-work` se registra y se dice el hash |
| **Decide el desarrollador** | Bajo `ask`: cambios de **esta sesión** sin commitear (o commiteados y sin push) cuando nunca se pidió subirlos. Bajo cualquier política: trabajo propio **sin verificar**, trabajo empezado a medias, petición que quedó en el aire | **Diálogo de la Fase 2b antes del veredicto**, nunca «por si quieres subirlos» |
| **Informativo** | Cambios sin commitear de **otras sesiones** o preexistentes en el árbol compartido; stashes antiguos | Una línea informativa, o nada |
| **Ruido** | Todo lo ya hecho, logs, rutas, detalles de implementación | No aparece |

Regla dura de las reglas globales: **no commitear ni pushear** por iniciativa propia. Los cambios de la
sesión sin subir no son un bloqueo, pero tampoco se despachan con «por si quieres subirlos antes de
salir»: si el desarrollador tiene que decidir, se le pregunta con opciones (Fase 2b). Su respuesta en
el diálogo es la orden explícita para **ese** cambio, y solo para él. Bajo `publish-own-work` la orden ya
la dio el proyecto en su regla versionada, pero solo para lo **verificado** y solo hasta la rama de la sesión:
lo que no se ha comprobado se pregunta igual, y un merge a la principal o un deploy nunca salen de aquí.

---

## Fase 2b — Dudas: abrir diálogo, no adivinar

Si después de clasificar queda algo **que solo el desarrollador sabe**, se abre un diálogo de preguntas
(`AskUserQuestion` en Claude Code, AskQuestion en Cursor) **antes** del veredicto.

| Duda típica | Por qué no se resuelve sola |
|-------------|------------------------------|
| Una petición del hilo quedó a medias | Solo él sabe si sigue en pie o la descartó |
| Hay trabajo empezado sin terminar | Solo él decide si se acaba ahora o se deja para la próxima sesión |
| Hay cambios de esta sesión sin commitear (política `ask`) | Subirlos o no es decisión suya; el agente no commitea por su cuenta ni lo deja caer en una frase |
| Lo pedido admite dos lecturas | De la lectura depende que el trabajo esté completo o no |
| Un rojo parece ajeno al cambio | Solo él sabe si le vale cerrar con ese rojo preexistente |

### La pregunta de los cambios sin commitear

Solo bajo la política `ask`; bajo `publish-own-work` lo verificado no se pregunta, se registra. Es la más frecuente
y tiene forma fija. Se enumeran en la propia pregunta los ficheros de la sesión
(agrupados: «Makefile, el guard de Xdebug y sus espejos, dos reglas del proyecto») y la rama, y se
ofrecen estas opciones, explicadas:

1. **Commitear ahora, sin push**: se hace `git add` solo de esos ficheros (nunca `git add -A` ni `git add .`
   en un árbol compartido) y un commit en inglés en la rama actual; queda local.
2. **Commitear y hacer push**: lo anterior más `git push` de la rama actual a su upstream. Push ≠ deploy:
   no dispara cascada ni FTP.
3. **Dejarlos sin commitear**: no se toca nada; el veredicto lo dice en una línea.

Elegir 1 o 2 **es** la orden explícita de commit/push que exigen las reglas globales, limitada a esos
ficheros y a ese momento. Si hay ficheros de otras sesiones mezclados, se dice en la pregunta que se
quedan fuera. Si la rama es `main` o `develop`, se avisa en la propia opción (el flujo del proyecto
suele pedir rama de feature) y se deja elegir igual.

Reglas del diálogo:

- **Pregunta y opciones en lenguaje natural**, bien explicadas: qué significa elegir cada opción, qué consecuencia tiene y qué pasa justo después. Nada telegráfico. Esto es la excepción explícita a la brevedad: aquí importa que se entienda, no ahorrar palabras.
- **Una sola tanda.** Como mucho las dudas reales (2–3), en un único diálogo. Nada de preguntar, responder, volver a preguntar.
- **Nunca preguntar lo comprobable**: ejecutar los tests, mirar `git status`, leer `tasks.md` o releer el hilo es trabajo del agente, no del desarrollador.
- Con la respuesta en la mano, se ejecuta lo elegido (si toca), se comprueba (`git status -sb`, hash del commit) y se da el veredicto de la Fase 3 incorporándola. Si el desarrollador no contesta, el veredicto sale igual y la duda aparece como viñeta: «no sé si X sigue en pie».

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
- Si no queda nada: primera línea «Sí, puedes cerrar», una línea con el resultado del diálogo (commit hecho y hash corto, o «quedan sin commitear como has pedido») —o, bajo `publish-own-work`, con el registro hecho y su hash—, y fin.

### Ejemplo — hay pendientes

```text
No: quedan dos cosas.

- La pantalla de alta de socio no se ha probado en el navegador desde el último cambio.
- Prometí el informe de QA en HTML y no está generado.

Dime «termínalo» y hago ambas; si prefieres cerrar ya, ninguna se pierde: el código está en la rama.
```

### Ejemplo — cierre limpio (tras el diálogo de la Fase 2b)

```text
Sí, puedes cerrar. Todo lo que pediste está hecho y verificado.

Los cambios de esta sesión están commiteados en `feature/xdebug-guard` (a1b2c3d), sin push, como has elegido.
```

O, si eligió dejarlos:

```text
Sí, puedes cerrar. Todo lo que pediste está hecho y verificado.

Los cambios de esta sesión quedan sin commitear en la rama actual, como has pedido.
```

Y bajo `publish-own-work`, sin diálogo:

```text
Sí, puedes cerrar. Todo lo que pediste está hecho y verificado.

Lo verificado de esta sesión queda registrado y empujado en `feature/alta-socio` (a1b2c3d), como fija la regla del proyecto; el merge a la principal lo haces tú.
```

Lo que **no** vale como cierre limpio: «los cambios están sin commitear, por si quieres subirlos antes
de salir». Eso es devolverle la decisión sin preguntársela.

---

## Argumento `detalle`

Con `/cierra-sesion detalle`, debajo del veredicto añadir **una línea por pendiente** con la evidencia decisiva: el comando que lo demuestra, el archivo afectado o la línea de salida relevante. Sin el argumento, esa evidencia no se escribe.

---

## Anti-patrones — prohibido

1. Dar veredicto sin haber ejecutado las comprobaciones de la Fase 1.
2. Inventar pendientes plausibles («quizá falten tests») sin señal que lo respalde.
3. Declarar «todo cerrado» cuando algo no se ha vuelto a verificar tras el último cambio.
4. Resolver los pendientes, commitear o pushear sin que el desarrollador lo pida (elegirlo en el diálogo cuenta como pedirlo; solo para esos ficheros).
5. Dar veredicto con una duda real sin resolver, en vez de abrir el diálogo de la Fase 2b. Incluye despachar los cambios de la sesión con «por si quieres subirlos».
6. Abrir diálogo para algo comprobable por el agente, o encadenar varias tandas de preguntas.
7. Responder con tablas, logs, rutas largas o un resumen de la sesión.
8. Superar las 10 líneas sin el argumento `detalle`.
9. `git add -A` / `git add .` en el árbol compartido: solo los ficheros de esta sesión, uno a uno.
10. Tratar un proyecto como `publish-own-work` sin la línea literal en un fichero versionado y en `HEAD`: deducirlo de la prosa, de la costumbre o de una edición sin commitear no cuenta.
11. Bajo `publish-own-work`, registrar trabajo propio que no se ha verificado: eso sigue siendo una pregunta.
12. Escribir, añadir o editar la línea `session-close:` en cualquier fichero: la autorización la concede el desarrollador, nunca el agente.
13. Bajo `publish-own-work`, hacer merge a la rama principal o de producción, o desplegar: el cierre llega hasta el push de la rama de la sesión y ahí para.
