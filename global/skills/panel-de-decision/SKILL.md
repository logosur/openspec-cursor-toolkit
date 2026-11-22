---
name: panel-de-decision
description: Decide por consenso de hasta 3 agentes una duda que iba a acabar en una pregunta al desarrollador, la anota con sus votos y sigue. La usa cualquier sesión desatendida que no pueda decidir con lo documentado. Auto-invoke on panel de decisión, decide con agentes, consensúalo con agentes, iba a preguntar al desarrollador, no sé qué opción elegir, decisión sin precedente, las fuentes se contradicen.
---

# Panel de decisión: hasta 3 agentes deciden lo que iba a ser una pregunta

Una sesión desatendida que se para a preguntar deja el trabajo parado hasta que alguien vuelve al ordenador. Este
panel sustituye esa pregunta por una decisión razonada, anotada y reversible.

## Cuándo se usa
- **Sí:** una decisión que las fuentes no zanjan (callan o se contradicen) y que, sin este panel, se le preguntaría al
  desarrollador: alcance ambiguo, una elección de producto sin precedente, dos lecturas de la spec que entregan cosas
  distintas o una prioridad entre objetivos.
- **No hace falta:** si las fuentes ya lo dicen (la orden, el `CLAUDE.md` y las reglas del proyecto, `~/.claude/rules`,
  el registro de decisiones del proyecto, las memorias), se decide directamente. Si es una comprobación, la hace un
  agente y se decide con su resultado.
- **Nunca decide un límite duro.** Los fija el desarrollador en sus reglas; como mínimo:
  - dinero fuera de un presupuesto aprobado;
  - abrir cuentas o generar secretos en un servicio ajeno (dar de alta usuarios de test en una app suya está
    permitido);
  - un dato que solo sabe él (no se inventa: valor provisional razonable o hueco marcado);
  - borrar trabajo ajeno, o datos sin copia;
  - envíos reales a terceros (correo masivo, redes, publicación en tiendas de apps, ediciones públicas en su nombre);
  - reescribir historia publicada y `push --force`.

  Eso no se hace, no para nada más y se apunta en la cola de preguntas del proyecto con «No hacerlo» por defecto.
- **Aprobaciones que una regla le reserva** (una imagen, una voz): el panel elige el candidato provisional para que el
  trabajo no se pare, y la aprobación queda apuntada.

## Cómo
1. **Dossier** (lo escribe quien convoca; menos de una página):
   - la pregunta en palabras llanas;
   - de 2 a 4 opciones, cada una con qué pasa justo después y qué cuesta;
   - las fuentes miradas, con ruta y cita corta, y por qué no bastan;
   - qué es reversible y cómo se desharía;
   - los límites que ninguna opción puede cruzar.

   Varias dudas pendientes van en un solo panel: cada miembro vota todas.
2. **Tres miembros como máximo, lanzados a la vez** en un solo mensaje con la herramienta `Agent`:
   - el modelo más capaz disponible, con esfuerzo alto;
   - solo lectura: no editan, no commitean, no envían nada y no preguntan a nadie;
   - mismo dossier para los tres, cada uno con su enfoque:
     1. **Intención del desarrollador:** qué se sigue de sus órdenes escritas y de sus decisiones anteriores.
     2. **Riesgo y reversibilidad:** qué puede salir mal y cuánto cuesta deshacerlo. El criterio es la opción óptima
        para terminar el trabajo; la reversibilidad solo desempata entre opciones igual de buenas.
     3. **Entrega desatendida:** qué opción termina antes el objetivo con menos trabajo tirado y sin depender de él.
   - **El panel siempre devuelve una opción.** Nunca «preguntar al desarrollador».
   - Cada uno devuelve, por cada duda: la opción y su confianza (alta, media o baja), hasta tres motivos con su fuente,
     el mejor argumento contra su propia elección, qué le haría cambiar de voto y su voto aparte sobre el rumbo
     (paso 4b).
3. **Discusión:** si no hay unanimidad, una segunda ronda. A cada miembro se le manda, con `SendMessage` a su id, la
   posición y los motivos de los otros dos; contesta al argumento contrario más fuerte y mantiene o cambia su voto.
   Como mucho, dos rondas.
4. **Regla de decisión:**
   - Unanimidad o mayoría de 2 contra 1: decidido.
   - Empate a tres bandas: gana la opción más reversible de las votadas; si siguen empatadas, la que no toca usuarios
     reales ni datos sin copia.
   - Quien convoca no vota y no reabre la decisión si no aparece un hecho nuevo.

4b. **Voto aparte: ¿es un rumbo radical?** Es radical si elegir mal obligaría a tirar o rehacer una parte grande del
   trabajo futuro (otra arquitectura o stack, abandonar o redefinir una spec entera). Solo sale «sí» por unanimidad
   3/3, con el coste escrito. Si sale sí, se pregunta al desarrollador en cuanto se pueda, se aparca lo afectado y todo
   lo demás sigue. Si sale no, se aplica la opción del panel y se sigue.
5. **Se anota y se sigue.** En el registro de decisiones del proyecto se escribe una entrada fechada con la pregunta y
   la decisión, los votos (3-0, 2-1), el motivo principal y la objeción del que discrepó, la fuente («panel de N
   agentes»), cómo se deshace, y `radical: sí/no (votos)` con su coste. Después se ejecuta, sin diálogo a mitad del
   flujo.

## Lo que no se hace
- No se convoca un panel para lo que ya dicen las fuentes, ni para un «¿sigo?».
- No más de tres miembros, ni rondas sin fin: tras la segunda, decide la regla del paso 4.
- No se presenta el resultado del panel como respuesta del desarrollador: su fuente es el panel.
- El desarrollador puede revertir cualquier decisión del panel; si lo hace, se anota y manda su respuesta.
