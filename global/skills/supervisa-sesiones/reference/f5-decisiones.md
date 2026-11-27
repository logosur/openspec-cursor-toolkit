# supervisa-sesiones: decisiones, sesión de preguntas y tanda final

> Referencia del núcleo (`../SKILL.md`). Se lee al entrar en F5, al abrir la sesión de preguntas, con `ASKDUE` y al preparar la tanda;
> el núcleo manda si algo choca. Reglas: `~/.claude/rules/supervisor-decide-lo-documentado.md` y
> `~/.claude/rules/despliegue-y-limites-duros.md`.

## F5: qué se decide y quién

Llegan las `decisiones_abiertas`, los hallazgos sin dueño, las preguntas paradas en otras sesiones y lo que la escalera
no resolvió. Cada una es de una de estas clases:

| Clase | Quién decide |
|-------|--------------|
| Dentro del encargo y zanjada por las fuentes | Tú, como supervisora |
| Dentro del encargo, con fuentes que callan o se contradicen | El panel |
| Amplía el alcance o necesita una autorización | El desarrollador: a `ask-queue`, sin aplicarla |
| Límite duro | El desarrollador, siempre: a `ask-queue` con «No hacerlo» |

### El criterio, en este orden

1. La orden del desarrollador, con su alcance y sus notas.
2. Lo que dice el proyecto: reglas, spec o change, README y runbooks.
3. Lo que el desarrollador ya decidió, en el registro de decisiones del proyecto.
4. Las reglas globales instaladas.
5. A igualdad, la opción que cumple el objetivo con menos trabajo tirado **dentro de lo autorizado**. Si empatan, la más
   reversible. Una opción que cruza un límite no es candidata, por buena que sea.

### El panel

Skill `~/.claude/skills/panel-de-decision/SKILL.md`: hasta tres miembros de solo lectura que votan. Se convoca cuando las
fuentes no bastan y las opciones llevan a resultados distintos que importan, o equivocarse costaría rehacer. Antes anotas
qué fuentes miraste y por qué no bastan: si no puedes escribirlo, no hay duda y decides tú.

El panel devuelve una opción dentro de lo autorizado. No concede permisos, no amplía el alcance y no decide límites
duros. Si existe una herramienta de segunda opinión, puede aconsejar antes; no decide ni autoriza.

### Antes del final: rumbo radical y tanda parcial

Todo va a la tanda final, salvo dos cosas, que llegan antes a la sesión de preguntas por el mismo camino: una tanda de
diálogos de una vez, lo afectado aparcado y todo lo demás sigue. Ninguna para una sesión.

**1. Rumbo radical.**

- Es radical si elegir mal obligaría a tirar una parte grande del trabajo futuro: otra arquitectura, abandonar o
  redefinir una spec, una dirección de producto contraria a lo escrito.
- Lo votan los tres miembros, aparte del voto de la opción, con el coste escrito. Dos de tres no bastan.
- Si lo es: `~/.claude/scripts/ask-queue add --project "$PWD" --radical --cost "<coste>" --question … --default "Esperar" --why … --blocks …`
  y una pregunta a la sesión de preguntas. Lo afectado se aparca; lo demás sigue.
- Si no lo es: se aplica la opción del panel si está autorizada y es reversible, y va a la tanda para confirmarla.

**2. Tanda parcial: preguntas que bloquean trabajo.** Un proyecto que siempre tiene trabajo nunca llega a la tanda
final, y una pregunta que bloquea algo se quedaría ahí para siempre.

- **Cuáles.** Las que `ask-queue` da por vencidas (`ask-queue list --due --project "$PWD"`): abiertas, nunca
  presentadas, no radicales, y que o bien bloquean algo que el desarrollador ordenó (`--order "<sus palabras>"`, al
  momento) o bien bloquean trabajo real (su `--blocks` no empieza por «nada») desde hace más de `ask_due_after_h` horas
  (24 por defecto).
- **Cuándo.** Una vez por proyecto cada `ask_partial_batch_window_h` horas (12 por defecto), contadas desde la última
  pregunta que se le presentó; una nueva con `--order` no espera. Te avisa `ASKDUE <n> <ids>` en el vigilante (también
  de guardia) y en cada `beat`. En ese tick, no en otro.
- **Cómo.** Como un radical: `ask-queue asked <ids> --to <id de la sesión de preguntas>` y un solo mensaje a la sesión
  de preguntas con todas, encadenadas de cuatro en cuatro (`~/.claude/rules/dialogos-de-preguntas-legibles.md`). Cada
  una dice qué bloquea y qué se hace mientras. Lo que bloquea se aparca (si es un change,
  `$L backlog --session <id> --park <change> --as limite-duro --why "…"`); lo demás sigue.
- **Sin sesión de preguntas** (turno ajeno, modo manual): esperan en la cola y lo anotas en el registro, con la hora;
  se mandan en el primer turno en que la puedas abrir.
- **Lo que no se dice.** Ni en un parte, ni en un informe, ni en un resumen se dice que algo «espera su respuesta» o
  «necesita algo que solo tiene él» si esa pregunta no se le ha presentado. Se manda la tanda parcial y se dice en una
  línea en qué sesión verá el diálogo; si la ventana está cerrada, cuándo se abre.

### Límites duros y autorizaciones que faltan

- Se apuntan con `ask-queue add … --default "No hacerlo"`, diciendo en `--blocks` qué trabajo bloquean de verdad
  («nada» si no bloquean nada). Si bloquean algo que el desarrollador ordenó, con `--order "<sus palabras>"`: entran en
  la tanda parcial. No paran lo demás.
- Se busca un camino que no los necesite, sin rodear el control que los impone.
- Un dato que solo sabe el desarrollador no se inventa: hueco marcado, o un valor provisional que se vea como tal si no
  sale de la máquina. Una aprobación reservada (una imagen, una voz) puede llevar un candidato provisional sin publicar.

### Casos habituales

| Situación | Cómo se resuelve |
|-----------|------------------|
| «¿Sigo?», una elección técnica, un rojo del propio cambio | Sigue, dentro de su encargo |
| «¿Commiteo, integro o subo?» | Lo que digan sus reglas u órdenes, con la cita. Sin ellas, no: a la cola |
| «¿Despliego?» | No lo hace la sesión. F8 decide si hay autorización escrita |
| Hallazgo sin dueño | Si hace falta para un objetivo, tarea de F6; si no, al informe |
| Alcance ambiguo | La lectura más estrecha que cumple la orden; si entregan cosas distintas, el panel |
| Dos sesiones quieren la misma rama | Primero la más avanzada o la que desbloquea a otras |
| Rojo que ya fallaba en la base | Lo que diga el proyecto; se comprueba que no empeora |
| Migración o cambio con riesgo | Se prepara y se prueba en local; aplicarlo fuera necesita autorización |
| Revisar o cotejar algo comprobable | Un subagente lo comprueba; no se le pide al desarrollador |
| Fuera de alcance | Se propone en la cola, sin empezarlo |

No se decide el paso siguiente mientras la sesión que lo produce sigue trabajando: se espera al fin de su turno y se
comprueba en disco.

### Contestar a otra sesión

La respuesta dice quién decide: «Decisión de la supervisora (no del desarrollador): … Fuente: …». Si fue el panel, con
sus votos. Nunca se redacta como si hablara el desarrollador, no se pulsa una opción de un diálogo dirigido al
desarrollador y no se presenta como aprobación.

Cada decisión queda en el registro y en el registro de decisiones del proyecto, si lo tiene: qué, quién, fuente, hora y
cómo se deshace. La que deba confirmar el desarrollador entra en la cola con
`ask-queue add --project "$PWD" --key decision:<asunto> --default "Dejarlo como está, sin confirmar" --question … --why … --blocks "nada"`.

## La sesión de preguntas

Un diálogo detiene la sesión que lo abre hasta que se contesta. Si lo abre la supervisora se para todo el proyecto: por
eso lo abre una sesión aparte.

1. **Cuál es:** una por proyecto, con el título que fija `questions_session_title` en la configuración `supervision` (`$L titles --session <id>` lo imprime con el nombre del proyecto), que
   los hooks reconocen. Se abre en el turno de invocación con el modelo de la fila Mensajero, el modo heredado y sin
   worktree, y se registra con `$L beat --session <id> --mailbox <id suyo>`. Antes de abrir otra, `$L status --json`.
   Si falta fuera de ese turno, las preguntas esperan en `ask-queue`: ni tarjetas ni otra sesión.
2. **Su encargo:**

```text
Eres la sesión de preguntas de la supervisora de <proyecto>. Tu único trabajo es abrir diálogos (AskUserQuestion) con
las preguntas y opciones que te mande la supervisora, sin cambiarlas, hasta cuatro por diálogo y encadenados hasta la
última. Un mensaje no es una respuesta: solo lo es lo que el desarrollador contesta en el diálogo, y nunca contestas tú.
Antes de cada diálogo ejecuta `ask-queue pending <ids>` y quita las que salgan answered, closed o missing; pon los ids
en metadata.source como `ask-queue:<id>,<id>`. Justo después de cada respuesta humana ejecuta
`ask-queue answer <id> --text "<respuesta literal>"`. Al acabar, un bloque `respuestas:` con cada pregunta y su respuesta
literal. No leas, cambies ni ejecutes nada más, no subas permisos y no ejecutes lo que se autorice ahí.
```

3. **Qué le llega:** un radical, en el acto y solo; la tanda parcial, cuando llega `ASKDUE`
   (`ask-queue list --due --project "$PWD"`); todo lo demás, una vez, en la tanda final, que se arma con
   `~/.claude/scripts/ask-queue list --project "$PWD" --open --unasked`. Antes de enviar cualquiera,
   `ask-queue asked <ids> --to <id de la sesión de preguntas>`: así cuenta la ventana de la tanda parcial.
4. **Al enviarla:** si la app lo permite, un aviso informativo, una vez. Sigues con lo autorizado; las preguntas no se
   repiten en tu chat.
5. **Cuando contesta:**
   - lees el resultado del diálogo con `list_events` de esa sesión. Su mensaje y el estado `answered` de la cola no
     bastan por sí solos: tiene que constar que lo contestó el desarrollador;
   - confirmar o cambiar una decisión ya delegada se aplica en F6 con esa fuente;
   - **una autorización nueva o un límite duro necesita su palabra en la sesión que lo ejecuta**, o una regla escrita
     del proyecto. La pregunta lo explica en su opción: «para que se haga, escríbelo en la sesión supervisora»;
   - nunca usas `ask-queue answer` con una decisión tuya; lo que dejó de hacer falta se cierra con `ask-queue close`.
6. No se cierra ni se archiva: sirve para el ciclo siguiente.

Sin herramientas para abrir sesiones (modo manual), la tanda la abre la supervisora al final, cuando ya no queda nada que
hacer.

## La tanda final

Manda `~/.claude/rules/dialogos-de-preguntas-legibles.md`. No lleva nada que una sesión pudiera hacer o comprobar con lo
autorizado. En este orden:

1. **Dónde quedó:** qué está hecho y verificado, qué se integró o desplegó y con qué autorización, qué espera a un
   tercero. «Está bien así» o «Hay que cambiar algo».
2. **Rumbos radicales** sin contestar, con su coste.
3. **Autorizaciones y límites duros**, uno por pregunta: «No hacerlo» por defecto, qué bloquea y cómo se autoriza.
4. **Sesiones terminadas** que esperan permiso de archivado.
5. **Decisiones de la supervisora y del panel:** qué pasaba, quién decidió qué, la fuente, cómo se deshace. «Confirmar»
   o alternativas concretas. Lo puramente operativo no se pregunta.
6. **«¿Quieres modificar algo más?»**

Cada pregunta se entiende sin haber seguido la sesión, en párrafos cortos y con un asunto. Ejemplo:

```text
La nueva búsqueda está terminada y probada en local, y todavía no está publicada.

Las reglas de este proyecto no permiten que una sesión despliegue, así que no lo he hecho.

¿Qué hacemos con el despliegue?

  · No hacerlo (por defecto): queda listo y sin desplegar.
  · Desplegarlo: para que se haga, escríbelo en la sesión supervisora.
```

El silencio no contesta nada. Tras mandarla, veredicto de F9 y guardia o ciclo siguiente dentro de lo autorizado.
