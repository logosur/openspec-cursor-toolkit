# supervisa-sesiones: subsupervisión del consumo

> Referencia del núcleo (`../SKILL.md`). Se lee al abrir o reanudar la sesión de consumo de la máquina, y cuando una
> supervisora ve líneas `USAGE` en `$L backlog`. Necesita los módulos `usage` y `supervision`.

Una sola sesión por máquina vigila el consumo de tokens de todas las sesiones y proyectos. Mide, detecta y pregunta;
**nunca aplica nada sin una respuesta registrada en la cola de preguntas**. No es la supervisora de ningún proyecto: no
cuenta como trabajo en el censo de ninguno (`open`, `closable`, `backlog`) y ninguna sesión de cierre la archiva.

`$U` es `~/.claude/scripts/usage-watch` y `$L` es `~/.claude/scripts/supervisor-lock`.

## El rol

- **Tomarlo:** `$L usage-role --claim --session <id local> --dir <proyecto de casa>`. `CLAIMED` o `RESUMED`: es tuyo.
  `HELD` (3): otra sesión viva lo tiene; no se duplica, se cierra esta. `STALE` (4): la que lo tenía calla; se toma con
  `--claim --from <su id>`.
- **Proyecto de casa:** sus preguntas de alcance de máquina, y las de un proyecto sin sesión de preguntas, van a la cola
  de ese proyecto. `$U status` avisa si su supervisión no tiene sesión de preguntas: nadie se las presentaría.
- **Latido:** `$L usage-role --beat --session <id>` al despertar. Al dejar el rol: `--release`.
- **Modelo:** el más barato (regla de modelo por rol). Lee, compara y pregunta; no escribe código.

## El ciclo

1. **Vigilante:** en segundo plano, `$U wait --session <id>`. Solo termina con `FINDING <id> <regla> <ámbito>` (un
   hallazgo nuevo) o `ANSWER <id>` (una pregunta suya contestada). Sin nada nuevo no imprime nada y no cuesta turnos.
   `NOT HOLDER` (5): otra sesión tiene el rol; esta se cierra. Si el anfitrión mata un comando que no termina, se rearma
   con `--timeout` largo. **Tope de preguntas abiertas:** `FINDING` solo sale mientras haya menos de `max_open_questions`
   preguntas sin contestar, y entonces solo para los hallazgos con más ahorro, hasta los huecos libres. Un `ANSWER` nunca
   se retiene. `$U list --state new` los ordena por ahorro, el mayor primero.
   - **`minor`:** un hallazgo cuyo ahorro queda por debajo del umbral de relevancia no es trabajo: se guarda como `minor`,
     el vigilante no lo anuncia, no se pregunta y la página lo muestra en un solo bloque plegado. Cada `detect` lo vuelve
     a evaluar. Un hallazgo ya preguntado no cambia nunca por esto.
   - **Hallazgos agrupados:** los de sesiones sueltas de una misma regla y proyecto (rutinas de una sola ejecución,
     sesiones ya cerradas o sin llamadas recientes, o tres o más) llegan como un único hallazgo del proyecto, una nota
     para su supervisora. Una propuesta de cambiar el modelo de una sesión solo existe para una sesión abierta y activa.
2. **Confirmar un `FINDING`:** `$U show <id>` da las cifras y las posiciones de las transcripciones que lo respaldan. Se
   leen solo esas líneas, nunca transcripciones enteras. Un falso positivo no se pregunta: se anota por qué.
3. **Preguntar:** `$U ask <id> --question "<qué pasa, qué se propone y qué cambia, en palabras llanas>"`. Va a la cola
   de preguntas del proyecto (o del proyecto de casa) con la clave del hallazgo y se presenta como cualquier otra
   pregunta. `ask` añade siempre una línea con el cambio exacto que haría `apply`; la respuesta autoriza ese cambio y
   ningún otro. Esta sesión no abre diálogos ni contesta a la cola: una respuesta registrada por ella, por quien preguntó o
   por nadie no vale.
4. **Decidir con un `ANSWER`:** `$U decide <id>`. No lleva resultado: lo lee de la cola. `authorized` o `rejected`; con
   la pregunta aún abierta o con una respuesta que no vale, sale con 3 y no cambia nada.
5. **Aplicar:** `$U apply <id>`, el único punto que cambia algo, solo con el hallazgo `authorized`, la respuesta aún en
   la cola y el mismo cambio que nombra la pregunta. Según el tipo:
   - **config:** escribe el valor en el override y en la pieza instalada, con los valores de antes para deshacerlo.
   - **modelo o esfuerzo de una sesión:** deja un vale de un solo uso; después se llama a la herramienta de la app que
     cambia el modelo o el esfuerzo de esa sesión, con ese valor exacto. El hook `usage-apply-gate` deniega esa llamada
     de esta sesión sin el vale de `apply`.
   - **nota:** es de la supervisora del proyecto (abajo).
6. **Medir:** pasado `measure_window_h`, `$U measure <id>` guarda la cifra de la regla antes y después.

Un hallazgo preguntado o rechazado no se vuelve a preguntar nunca.

## Lo que este rol no aplica: la supervisora del proyecto

Un hallazgo `authorized` de tipo nota (un bucle, contexto grande, ritmo) aparece en `$L backlog` del proyecto como una
línea `USAGE <id> <regla>: <propuesta>` y cuenta como trabajo para la guardia. Lo aplica la supervisora de ese
proyecto, y al terminar: `$U apply <id> --how "<qué se hizo>"`. Encender una pieza instalada solo se propone y se
aplica con respuesta, como cualquier otro cambio de config.
