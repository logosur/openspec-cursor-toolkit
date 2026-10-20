---
name: cierra-sesion
description: Abre un único diálogo de selección múltiple que explica en lenguaje natural qué queda pendiente de esta sesión, de otras sesiones (con dueña) y lo huérfano, y deja marcar qué hacer con cada cosa (commit, push, deploy, avisar, retomar, cerrar worktrees, cerrar la sesión). Auto-invoke on /cierra-sesion, queda algo pendiente, puedo cerrar la sesión, está todo terminado, me voy queda algo, cierre de sesión.
---

# Cierra sesión — un diálogo con casillas

> **Command:** `.claude/commands/cierra-sesion.md`
> **Censo de propietarias:** `.claude/skills/cierra-sesion/session-owners.py`

El resultado de esta orden es **un solo diálogo** (`AskUserQuestion`, **todas las preguntas con
`multiSelect: true`**) en el que el desarrollador **lee** qué falta y **marca varias casillas** a la vez.
El diálogo **es** el informe: no se escribe antes un listado aparte que lo repita. Como la interfaz
enseña **una pregunta cada vez**, **cada pregunta abre con el mismo resumen de tres líneas** (de esta sesión,
de otras sesiones, huérfano; ver Fase 2). Tiene cuatro bloques de casillas, siempre en este orden:

| Bloque (`header`) | Contenido |
|-------------------|-----------|
| **Esta sesión** | Lo pendiente de esta sesión y las acciones sobre lo suyo (commit, push, deploy, verificar) |
| **Con dueña** | Lo de otras sesiones **vivas**: se puede avisar a su dueña |
| **Huérfanos** | Lo que ninguna sesión viva tiene: worktrees, cambios sueltos, stashes. Se puede cerrar o retomar |
| **Al terminar** | Cerrar el worktree de esta sesión y/o archivar esta sesión |

Lo pendiente se **detecta y se nombra**; arreglarlo es otra orden. Las únicas acciones que este skill
ejecuta son las **casillas que el desarrollador marca**, porque marcarlas **es** la orden explícita (solo
para esos ficheros, esa rama y ese momento). Sin ninguna casilla marcada no se ejecuta nada.

**Excepción: la nota del vault.** La regla global obliga a anotar en `~/Obsidian/Knowledge` el trabajo
sustantivo (feature, decisión de arquitectura, bug no trivial, incidente) sin pedir permiso. Si falta, el
skill la escribe **antes** del diálogo y lo dice en una línea. Nunca se ofrece como casilla: la memoria
automática del agente no la sustituye (corrección del desarrollador, 23-09-2026).

**Política del proyecto: `ask` (por defecto) o `publish-own-work`.** La declara el proyecto y es una
**autorización**, así que tiene candados: cuenta únicamente si la línea literal

```text
session-close: publish-own-work
```

está en `CLAUDE.md`, en `.claude/rules/*.md` o en `.cursor/rules/*.mdc`, ese fichero está versionado **y** la
línea aparece en su versión commiteada (`git show HEAD:<fichero>`). Este skill **nunca escribe, añade ni
edita esa línea**. Con ella, el proyecto ya autorizó commit y push de la rama de la sesión para el trabajo
**verificado**: esas dos casillas no se ofrecen, se ejecutan y se dicen; el resto del diálogo se abre igual.
La autorización tiene techo: nunca un merge a la rama principal o de producción ni un despliegue sin marcarlo.

---

## Fase 1 — Recoger señales (solo lectura, en paralelo)

```bash
git status --porcelain=v1
git status -sb
git stash list
git log --oneline @{upstream}..HEAD 2>/dev/null
python3 .claude/skills/cierra-sesion/session-owners.py
git rev-parse --git-dir --git-common-dir
```

Y, si el repo tiene `openspec/`: `openspec list --json 2>/dev/null`, y las tareas marcadas frente a las
totales del change tocado en la sesión (`openspec/changes/<slug>/tasks.md`).

Y la política de publicación (si no imprime nada, es `ask`):

```bash
for f in CLAUDE.md .claude/rules/*.md .cursor/rules/*.mdc; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 \
    && git show "HEAD:$f" 2>/dev/null | grep -qE '^session-close:[[:space:]]*publish-own-work' && echo "$f"
done
```

`session-owners.py` censa lo que no es de esta sesión: cada worktree del repositorio (cambios sin commitear,
commits sin fusionar), los cambios sin commitear del checkout principal y los stashes. Para cada uno dice si
una **sesión viva** lo posee (su directorio de trabajo registrado es ese árbol; «viva» = el pid existe y su
hora de arranque coincide) o si está **huérfano**. Si el script no existe o falla, se dice en el propio
diálogo que la propiedad no se ha podido comprobar y se usan `git worktree list` y `ListAgents`; nunca se
inventa una dueña.

El directorio registrado de una sesión no basta: una sesión abierta en otro sitio puede trabajar en un
worktree **por ruta absoluta** (el 18-10-2026 el censo dio por huérfanos `einf-paragraph-dialog` y
`einf-performance-measurements` con su sesión dentro). Por eso el script también mira la **actividad**, y su
salida se lee así:

| Línea del censo | Es de… | Va en el resumen y en el diálogo como |
|-----------------|--------|----------------------------------------|
| `PROPIETARIA «x»` | La sesión cuyo directorio registrado es ese árbol | **De otras sesiones** |
| `PROPIETARIA POR ACTIVIDAD «x»` | Una sesión viva con un proceso suyo dentro del árbol | **De otras sesiones** |
| `CON ACTIVIDAD sin sesión identificada` | Alguien: hay un proceso dentro ahora mismo | **De otras sesiones** (sin nombre) |
| `EDITADO HACE …` (< 30 min) o `CREADO HACE …` con stack encendido (< 3 h) | Probablemente alguien | **De otras sesiones** («probablemente en uso») |
| `HUÉRFANO` | Nadie | **Huérfano** (si lleva contenedores encendidos, se dice y no se paran) |
| `STACKS SIN CARPETA` | Nadie: contenedores cuyo worktree ya no existe | **Huérfano** (pararlos lo decide su dueño o el desarrollador) |
| `SIN TOCAR desde hace N d` (checkout principal) | Restos de nadie en particular | **Huérfano**, sin afirmar de quién eran |

Un `HUÉRFANO` del censo **no prueba** que nadie lo lleve: antes de cerrar o descartar nada, se repite el censo
y se mira con `ListAgents` o preguntando a las sesiones del proyecto. Una sesión que lo reclama por mensaje
manda sobre el censo.

Del `git status` hay que separar **dos conjuntos**: los ficheros que ha tocado **esta sesión** (se saben por
el hilo: cada edición, cada script generado) y el resto. Solo el primero es decisión del desarrollador en esta
sesión; el segundo no se toca ni se commitea.

Además, revisar **el hilo de esta conversación** (no todo el repo) buscando:

| Señal | Qué cuenta como pendiente |
|-------|---------------------------|
| Petición sin cerrar | El desarrollador pidió algo y no se entregó resultado, o se entregó a medias |
| Rojo conocido | Tests, lint o build que fallaron y no se volvieron a ejecutar en verde |
| Verificación que falta | Se cambió código con UI observable y no se verificó en navegador |
| Entregable anunciado | Informe, captura, PDF o artefacto prometido y no producido ni abierto |
| Pregunta abierta | Decisión que se le trasladó al desarrollador y sigue sin respuesta |
| Proceso vivo | Servidor de desarrollo, watcher, tarea en segundo plano o stack levantado en la sesión |
| Código temporal | Depuración, `dd()`, logs o mocks introducidos para avanzar y no retirados |
| Cambios sin commitear o sin subir | Ficheros de esta sesión sin commit, o commits propios sin push |

Si una señal no se puede comprobar (comando ausente, repo sin upstream), **no se inventa**: se omite o se dice
en el diálogo que no se ha podido comprobar.

---

## Fase 2 — Montar el diálogo (una sola llamada)

Una llamada a `AskUserQuestion` con **hasta 4 preguntas**, una por bloque, **todas `multiSelect: true`**.
Un bloque sin **casillas que ofrecer** no lleva pregunta propia (no hay huérfanos → no hay pregunta
«Huérfanos»), pero **su explicación no desaparece** (véase el resumen común). Si no queda ni un solo
pendiente, solo «Al terminar».

**La interfaz enseña una pregunta cada vez** («1/2», «Siguiente»): el desarrollador solo ve el texto de la
pregunta en la que está, nunca las demás ni lo que se escribió en el chat antes. Por eso hay un
**resumen común** que **abre el texto de TODAS las preguntas**, sin excepción, con estas tres líneas siempre
presentes y en este orden (con «Nada.» si no hay nada; nunca se omite una):

```text
De esta sesión: <lo que falta de la sesión en la que se ejecuta, o «Nada.»>
De otras sesiones: <lo ajeno que sí tiene una sesión viva (nombre, ocupada o en reposo), o «Nada.»>
Huérfano, sin sesión: <lo que nadie va a recoger, con su coste, o «Nada.»>
```

Seguido de una línea en blanco y de la pregunta propia del bloque. Sin ese resumen, el desarrollador decide
sin saber qué es de quién: es un fallo del diálogo, no un detalle de estilo (corrección del
desarrollador, 18-10-2026: «¿cómo voy a tomar decisiones sin saber eso?»).

**Cómo se redacta** (es la excepción explícita a la brevedad; el desarrollador no ve nada más):

- El **resumen común** va primero y dice, en **frases completas y llanas**, qué pasa con cada cosa y de quién
  es, no etiquetas: «el worktree `einf-audit-integration` tiene 8 cambios guardados que aún no están en
  `main`; ninguna sesión lo tiene abierto, así que nadie lo va a terminar». Máximo ~3 líneas por apartado;
  lo que sobre se agrupa («otros 3 worktrees con trabajo»). No usar jerga interna («orden tuya», «solo
  lectura», «árbol limpio») sin explicar qué significa para él.

- El texto de **cada pregunta explica el bloque en lenguaje llano**: qué hay, de quién es y qué pasaría al
  marcar. Va en frases cortas, con los nombres de las sesiones y las ramas, sin rutas largas ni jerga
  («8 cambios guardados que aún no están en `main`», no «ahead 8»).
- Tras el resumen, el texto propio del bloque es **solo la pregunta** y lo que cambia al marcar; lo que
  cada bloque describe en «Texto:» más abajo vive ya en el resumen y **no se repite**.
- Ejemplo de texto de una pregunta (bloque «Huérfanos»):

  ```text
  De esta sesión: Nada; lo que hice ya está fusionado en main.
  De otras sesiones: «Optimizar tests por velocidad» (en reposo) tiene 21 cambios guardados sin fusionar en main; no se tocan.
  Huérfano, sin sesión: 4 carpetas de trabajo limpias que sobran; 5 con trabajo a medias (el que más pesa, einf-audit-integration, 8 cambios sin fusionar) y un stash viejo de septiembre.

  ¿Qué hago con lo huérfano? Solo puedo cerrar lo que sobra o leer y contarte lo que hay en el resto: no fusiono ni borro trabajo a medias sin que me lo pidas por su nombre.
  ```
- Cada **opción** lleva `label` corto (acción concreta) y `description` con el coste o el efecto («un push a
  `main` ejecuta el despliegue automático», «borra la carpeta, la rama ya está fusionada»).
- **Máximo 4 opciones por pregunta.** Si hay más cosas, se **agrupan** por tipo («Cerrar los 7 worktrees
  limpios») y las que más pesan van sueltas. Lo que no cabe se nombra en el texto de la pregunta y el
  desarrollador puede añadirlo en «Otro».
- La herramienta **no permite preseleccionar** casillas. Lo recomendado lleva **«(Recomendada)»** en la
  etiqueta y va **primero**; no hay predeterminado que se ejecute por omisión: **solo se hace lo marcado**.
- **Comprobable no se pregunta** (ejecutar tests, mirar `git status`, leer `tasks.md`).

### Bloque 1 — «Esta sesión»

Texto: qué falta de **esta** sesión, en dos o tres frases (lo que bloquea, lo que conviene, lo que no se ha
podido verificar). Opciones, solo las que aplican:

| Casilla | Aplica si | Nota |
|---------|-----------|------|
| **Commit de mis N ficheros (Recomendada)** | Hay cambios propios sin commitear | Se hace `git add` por nombre y un commit en la rama actual. Si lo propio no está verificado, **no** lleva «(Recomendada)» y la descripción lo dice |
| **Push de `<rama>` a `<destino>`** | Hay o habrá commits propios sin subir | La descripción dice cuántos commits y qué provoca (un push a `main` ejecuta el despliegue automático). Mismo criterio de «verificado» |
| **Desplegar con el flujo del proyecto** | El proyecto documenta un deploy | **Nunca** «(Recomendada)» ni primero |
| **Terminar lo que falta: `<qué>`** | Hay una petición a medias o una verificación pendiente | Una casilla por cosa que el agente pueda cerrar él (probar en navegador, repetir tests) |

Una **duda real** (algo que solo sabe el desarrollador, como si una petición a medias sigue en pie) se
escribe en el texto de la pregunta y se contesta en «Otro»; no es una pregunta aparte.

### Bloque 2 — «Con dueña»

Texto: qué pendientes ajenos tienen una **sesión viva** (con su nombre y si está ocupada o en reposo) y que
**no se tocan**. Opciones:

| Casilla | Qué hace |
|---------|----------|
| **Avisar a «<sesión>»** (una por dueña, o agrupadas si son muchas) | Le manda un mensaje con `SendMessage` pidiéndole que cierre lo suyo según el flujo del proyecto. Solo a sesiones del **mismo proyecto** (comprobar con `ListAgents`); el mensaje dice expresamente que **no autoriza commit, push, merge ni deploy** |
| **Avisar a las candidatas** | Cambios sueltos del checkout principal con varias sesiones vivas posibles: se les avisa a todas sin afirmar de quién son |

### Bloque 3 — «Huérfanos»

Texto: qué cosas **nadie va a recoger** (ninguna sesión viva las tiene), con su coste («8 cambios guardados
que no están en `main`», «2 ficheros sin guardar»). Los que tienen **trabajo sin guardar** van primero.
Opciones:

| Casilla | Qué hace |
|---------|----------|
| **Cerrar los N worktrees huérfanos limpios (Recomendada)** | Solo los **limpios y sin nada que fusionar** (o ya fusionados). `git worktree remove` sin `--force`, `git branch -d` sin forzar y `port-lease release` si tenían stack. No toca ninguno con cambios o commits sin fusionar |
| **Retomar «<rama>»** (una por huérfano con trabajo, las 2 o 3 que más pesan; el resto, agrupado) | Lo toma esta sesión **en solo lectura**: resume qué contiene, comprueba si se fusiona limpio en `main` (`git merge-tree`) y qué checks le faltan. **No commitea, no fusiona ni borra.** Dice exactamente qué orden la cerraría |
| **Revisar los stashes** | Lista los stashes con fecha y contenido para decidir. **No aplica ni borra** ninguno |

Un huérfano con **cambios sin commitear** no se commitea nunca desde aquí (no son de esta sesión): «retomar»
lo describe y el desarrollador ordena el siguiente paso por nombre.

### Bloque 4 — «Al terminar»

Texto: dónde está esta sesión (en un worktree o en el checkout principal) y qué dejaría cada casilla.

| Casilla | Aplica si |
|---------|-----------|
| **Cerrar el worktree de esta sesión (Recomendada)** | La sesión está en un worktree. Solo se cierra limpio y fusionado donde manda el proyecto |
| **Archivar esta sesión (Recomendada)** | Siempre |

Si la Sección «Esta sesión» tiene **algo que bloquea** (trabajo pedido sin terminar), ninguna de las dos
lleva «(Recomendada)» y el texto dice por qué: cerrar con algo a medias lo pierde de vista.

### Cuándo cambia lo recomendado

- **Trabajo propio sin verificar** (tests sin ejecutar tras el último cambio, rojo sin resolver): commit y
  push pierden «(Recomendada)»; lo no verificado no se sube por defecto.
- **Rama `main`, `master`, `develop` o de producción**: la descripción de commit y de push lo avisa (el flujo
  del proyecto suele pedir rama de tarea) y se deja elegir igual.
- **Cambios de otras sesiones mezclados** en el árbol: la casilla de commit dice que se quedan fuera.

Si el desarrollador **no contesta**, no se ejecuta nada. Una respuesta de solo «Otro» se lee como texto
libre y se atiende como orden explícita sobre lo que nombre.

---

## Fase 3 — Ejecutar lo marcado, en este orden

1. **Terminar lo que falta** (si se marcó): verificar en navegador, repetir tests. Si sale rojo, se dice y
   se cortan commit y push.
2. **Commit** (si se marcó): solo los ficheros de esta sesión, mensaje en inglés, imperativo, primera línea
   ≤ 72 caracteres, **sin líneas de atribución**. Respeta el flujo que describa el proyecto (en algunos hay
   que fusionar la rama de la tarea en la principal local según su regla antes del push). Comprobar con
   `git status -sb` y dar el hash corto.
3. **Push** (si se marcó): solo la rama y el destino que decía la casilla, nunca `--force`. Si el proyecto
   exige una condición previa (un sello de gate, tests en verde) y no se cumple, **no se hace el push** y se
   dice con la causa.
4. **Deploy** (si se marcó): únicamente con el flujo que el proyecto documenta, tras commit y push. Si no hay
   flujo documentado, no se improvisa: se dice.
5. **Avisos** (si se marcaron): un `SendMessage` por dueña, solo a sesiones del mismo proyecto.
6. **Huérfanos** (si se marcaron): primero «retomar» y «revisar stashes» (solo lectura), después «cerrar
   limpios» **repitiendo antes el censo** (`session-owners.py`): si entretanto una sesión viva lo ha
   tomado, se salta y se dice. Cada cierre sin `--force`.
7. **Cerrar el worktree de esta sesión** (si se marcó): solo si está limpio y su trabajo está fusionado donde
   manda el proyecto. Sigue el procedimiento de cierre de ese proyecto (parar su stack, soltar sus puertos,
   `git worktree remove <ruta>`, `git branch -d <rama>`), nunca con `--force` ni borrando una rama sin
   fusionar. Si algo lo impide, se deja abierto y se dice el motivo exacto.
8. **Archivar la sesión** (si se marcó): es lo último. Se escribe antes el informe de la Fase 4 y, a
   continuación, se archiva esta sesión (`mcp__ccd_session_mgmt__archive_session` con el id de esta sesión
   si la herramienta existe; si no, se le dice al desarrollador que cierre la ventana o salga con `/exit`).
   Nunca se cierra ni archiva **otra** sesión.

Cada paso que no pueda completarse corta lo que dependía de él (sin commit no hay push; sin push no hay
deploy) y se dice en el informe, sin reintentar con otra vía. **Merge de un huérfano, commit de sus cambios
y borrado de una rama sin fusionar no son casillas**: requieren una orden aparte del desarrollador, por
nombre, y la confirmación extra que el proyecto exija.

---

## Fase 4 — Informe final (máx. 10 líneas)

Solo **lo que pasó** y **lo que sigue pendiente**; el diálogo ya explicó el resto. Sin tablas ni logs:

```text
<veredicto en una frase>

Hecho: <commit a1b2c3d en `rama`, subido a `origin`; 3 avisos enviados; 5 worktrees cerrados; …>
Sigue pendiente: <viñeta por cosa, con su dueña o «huérfano»; o «Nada.»>
Siguiente orden posible: <la frase exacta que cierra lo que falta>
```

- **Veredicto** = «Sí, puedes cerrar.» solo si no queda nada de **esta** sesión; si no, «No: quedan N cosas de
  esta sesión.» Lo de otras sesiones no cambia el veredicto.
- Lo no verificado o no comprobable (propiedad sin censo) se dice como tal.
- Lenguaje natural, en el idioma del desarrollador.

---

## Argumento `detalle`

Con `/cierra-sesion detalle`, la `description` de cada opción añade la evidencia decisiva: el comando que lo
demuestra, la ruta del worktree o el pid de la sesión propietaria. Sin el argumento, esa evidencia no se escribe.

---

## Anti-patrones — prohibido

1. Montar el diálogo sin haber ejecutado las comprobaciones de la Fase 1 (incluido el censo de propietarias).
2. **Preguntas de selección única o varias tandas.** Es una sola llamada y todas las preguntas son multiselección.
3. **Escribir antes un listado de pendientes y luego repetirlo en el diálogo**: el diálogo es el informe.
   Lo que sí se repite, a propósito, es el **resumen común** al principio de cada pregunta.
3b. **Una pregunta sin el resumen común de tres líneas** (esta sesión / otras sesiones / huérfano), o con
   alguna línea omitida porque «no hay casillas» o «no hay nada»: la interfaz muestra una pregunta cada vez y
   el desarrollador no puede decidir sin saber qué es de quién.
4. Inventar pendientes plausibles («quizá falten tests») sin señal que lo respalde.
5. Mezclar los bloques, o poner lo de otras sesiones en «Esta sesión».
6. Afirmar que algo tiene sesión propietaria sin que el censo lo respalde, o llamar «huérfano» a lo que una
   sesión viva tiene abierto. Sin censo, se dice que no se ha podido comprobar.
7. Tocar, commitear, fusionar o borrar trabajo de otra sesión. Del huérfano solo se hace lo que dice una
   casilla marcada, que nunca es commit, merge ni borrado de lo no fusionado. Cerrar o archivar **otra** sesión.
8. Avisar a sesiones de otro proyecto, o redactar un aviso que parezca autorizar commit, push, merge o deploy.
9. Commit, push, deploy o cierre sin la casilla correspondiente (o, para commit y push de lo verificado, sin
   la línea `publish-own-work` versionada en `HEAD`).
10. `git add -A` / `git add .` en un árbol compartido: solo los ficheros de esta sesión, uno a uno.
11. `--force`, `--no-verify` o saltar un gate para que el push o el cierre salgan.
12. Marcar el deploy como recomendado, o improvisar un deploy que el proyecto no documenta.
13. Cerrar un worktree con cambios sin guardar o con la rama sin fusionar, o borrar una rama sin fusionar.
14. Escribir, añadir o editar la línea `session-close:` en cualquier fichero: la concede el desarrollador.
15. Bajo `publish-own-work`, subir trabajo sin verificar, hacer merge a la principal o desplegar sin marcarlo.
16. Dar por bueno lo no verificado, o declarar «todo cerrado» cuando algo no se ha vuelto a comprobar.
