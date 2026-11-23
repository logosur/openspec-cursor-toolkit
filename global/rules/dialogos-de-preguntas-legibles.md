# Diálogos de preguntas: se entienden sin haber seguido la sesión (regla global)

Por qué: quien contesta suele llegar de otra tarea. Una pregunta que exige recordar el hilo se contesta mal o no se
contesta. Se aplica a todo diálogo de preguntas (`AskUserQuestion` y equivalentes), también al de cierre de sesión y al
que presenta la cola de preguntas.

## Quien lee no ha seguido la sesión
- Cada pregunta se entiende sola: qué pasa, por qué le toca decidir al desarrollador y qué cambia según lo que elija.
- Ningún código interno sin explicar: números de tarea, IDs de gap, nombres de rama o de worktree, hashes, siglas y
  nombres de ficheros. Si hay que nombrarlo, antes se dice qué es en palabras llanas.
- Una decisión con matices se explica entera: qué se pidió, qué se hizo y la alternativa. Si son varias, cada una en su
  propia pregunta o en un diálogo aparte; nunca en una lista de etiquetas.
- No se mezclan asuntos distintos en una pregunta. Lo que no es una decisión se dice en una frase o no se dice.

## Legible
- El texto va en párrafos cortos separados por una línea en blanco (`\n\n`): primero el contexto, después qué se decide
  y al final qué implica cada camino.
- Frases cortas en lenguaje natural, sin jerga de git ni del proyecto si hay una palabra llana.
- El `label` de cada opción es la acción concreta; la `description` dice qué pasará justo después y lo que cuesta.
- Antes de enviarlo se relee como si se llegara de otra cosa. Si hace falta recordar el hilo para entenderla, se
  reescribe.
