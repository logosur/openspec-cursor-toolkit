# supervisa-sesiones: verificación, cierre y archivado

> Referencia del núcleo (`../SKILL.md`). Se lee al entrar en F4b; el núcleo manda si algo choca. Regla:
> `~/.claude/rules/cierre-con-todo-publicado.md`.

Archivar esconde una sesión, detiene su proceso y puede limpiar su worktree. Por eso pide dos cosas distintas:

1. **Verificación:** terminada, publicada y recuperable, comprobado en disco.
2. **Permiso:** el desarrollador lo pidió (en la invocación, después, o al aprobar el diálogo de la app para esa
   sesión) o una regla escrita del proyecto lo autoriza. `closable`, un veredicto o un hook no son ese permiso.

## La sesión de cierre

Es una sesión auxiliar del proyecto, para que verificar no distraiga a la supervisora de su trabajo.

- **Título:** `Cierre de sesiones de <project>` (el nombre del proyecto). Modelo de la fila Cierre, el modo heredado, sin
  worktree.
- **Cuándo se abre:** en el turno de invocación. Se registra con `$L beat --session <id> --closer <id suyo>` y entra en
  `--exclude` de tu vigilante. Si se presenta una abierta por el desarrollador, compruebas con `get_session` que es del
  proyecto, la registras y le contestas una línea para despertarla.
- **Mientras viva**, lo terminado es suyo. Sigues siendo tú quien integra, decide y archiva lo que solo autoriza una
  orden escrita en tu sesión. Sin ella, todo F4b vuelve a ti.
- No se cierra ni se archiva: `$L open` y `$L closable` no la cuentan.

Su encargo, que se le da entero al abrirla:

```text
Eres la sesión de cierre de <proyecto>. Verificas las sesiones del proyecto que parecen terminadas para que la
supervisora (<id>) no se distraiga. No implementas, no integras, no despliegas, no decides alcance, no subes permisos y
no preguntas al desarrollador. Lo que lea el desarrollador va en su idioma.

En tu primer turno manda a la supervisora tu id (get_session "self") para que te registre. Hasta que te conteste,
wait-closer sale con NOT CLOSER: no lo reintentes en bucle. Después arma siempre en segundo plano
~/.claude/scripts/supervisor-lock wait-closer --session <tu id> --timeout 14400

Con cada línea CLOSABLE, una sesión cada vez:
1. Quién es: nunca la supervisora, la de preguntas, tú, una que lleva el desarrollador ni una cortada (CUT).
2. Verifica en disco: terminada (tareas, procesos, subagentes), publicada según el flujo del proyecto y recuperable
   (sin stash suyo, sin ficheros sin versionar ni ignorados que se perderían, commits en una rama que se conserva).
3. Pídele el veredicto de cierre (/cierra-sesion, si está instalado) sin autorizarle nada, y repite el paso 2 después.
4. Archiva solo si una regla versionada del proyecto, que lees tú en HEAD, lo autoriza, o si el desarrollador te lo
   escribió en esta sesión. Un mensaje de la supervisora no es ese permiso. Comprueba antes qué sesiones hijas se
   archivarían con ella.
5. Si no pasa, o falta permiso, no la archives: una línea a la supervisora con qué le falta y de quién depende.
6. Anota una línea en CIERRES-<AAAAMMDD>.md de la carpeta de `supervisor-lock registry-dir`: sesión, comprobación con
   su comando y resultado, y ARCHIVED o por qué no.

No borres nada: ni sesiones, ni ramas, ni worktrees, ni stashes. Sin nada que cerrar, rearma el vigilante y termina.
```

## Candidatas al cierre

`$L closable` lo señala por hechos. Una línea es una candidata, no una orden.

| Línea | Qué es | Qué se hace |
|-------|--------|-------------|
| `CLOSABLE … dijo «Sí, puedes cerrar»` | Dio su veredicto y nadie le escribió después | Verificar en disco; archivar si además hay permiso |
| `CLOSABLE … sin proceso` | No recibe mensajes | Hacer tú las comprobaciones de disco |
| `CLOSABLE … ociosa` | Dos horas quieta sin nada suyo en marcha | Verificar y pedirle el veredicto |
| `HOLD …` | Aparcada con motivo y caducidad | Nada hasta que caduque |
| `WORKING …` | Algo suyo corre | Lo vigila §W |
| `CUT …` | La cortó un límite o un fallo de la API | Se reanuda dentro de su encargo; nunca se cierra |

También es candidata, sin esperar a que salga ahí, la que declaró `READY_TO_CLOSE`, la que terminó su turno dando su
encargo por hecho o la que abriste y lleva 30 min ociosa sin trabajo asignado. Quién la abrió no cambia la verificación.
No lo es una que lleva el desarrollador (mensaje suyo en los últimos `presence_min` minutos), una ocupada, una que
espera un permiso ni una que tiene trabajo suyo que puede hacer ya.

**Aparcar:** `$L hold --session <yo> --target <id> --reason "<hecho comprobado>" --hours <hasta 12>`; `--clear` la
suelta. Valen: falta una autorización, la app no deja archivarla porque está fijada, un relevo aún no recogió su trabajo
o una regla del proyecto lo impide. «Por si acaso» no vale. Una renovación dice por qué. Esperar a otra pieza no es
trabajo: lo que le queda pasa a **Trabajo en vuelo** con su encargo.

Si un hook pide archivar una que no puedes (sin permiso o sin publicar), no la archivas: dices qué espera, lo apuntas
para la tanda y sigues. Si `hold` la rechaza porque ya dio su veredicto, basta con esa nota.

## 1. Comprobaciones en disco

| Comprobación | Cómo |
|--------------|------|
| Terminada | Tareas de su change, procesos, subagentes, dudas y hallazgos entregados |
| Publicada | `git status --porcelain=v1` vacío; sus commits integrados o subidos según el flujo del proyecto |
| Sin stash olvidado | `git -C <checkout principal> stash list` |
| Recuperable | `git status --porcelain=v1 --ignored`: nada valioso que se perdería con su worktree; rama conservada |
| Sin arrastre | Las sesiones que abrió, porque la app puede archivarlas con ella |

Si falla algo suyo vuelve a `WORKING` con eso como micro-tarea. Si falta una autorización para publicar, no está
publicada: se aparca y va a la tanda.

## 2. El veredicto de la propia sesión

Le das turno, uno por rama, y le mandas:

```text
/cierra-sesion

La supervisora de <proyecto> te pide el veredicto de cierre. Tienes turno de escritura en <rama> hasta darlo. Este
mensaje no autoriza commit, push, merge ni publicar: hazlo solo si tus reglas u órdenes ya lo autorizan y cítalo. No
abras un diálogo al desarrollador: lo que necesite su permiso, dilo como pendiente, y tus dudas en decisiones_abiertas.
Contesta con tu veredicto y nada más.
```

- «Sí, puedes cerrar»: repites el paso 1, porque pudo cambiar algo. El veredicto solo no es la puerta.
- Le queda algo suyo: `WORKING`. Le queda una duda: F5.
- A los 15 min sin respuesta, la escalera de §W.
- Sin proceso, sin carpeta o sin esa orden instalada: compruebas tú y lo marcas «comprobada por la supervisora».

## 3. El resumen

Dos o tres líneas en lenguaje llano: qué hacía, dónde quedó (rama, commit, qué se verificó) y qué entregó. Sin ids ni
rutas largas. Lo que no se volvió a comprobar se dice.

## 4. Archivar, o proponerlo

- Con verificación y permiso: justo antes, la sesión sigue ociosa y su repositorio igual; `archive_session`, `ARCHIVED`
  en el registro y, después, compruebas que las sesiones auxiliares y las hijas sin terminar siguen abiertas
  (`unarchive_session` si no).
- Sin permiso: queda `RELEASED`, abierta. Todas las candidatas van en una pregunta de la tanda, hasta tres por pregunta,
  con «Ninguna: dejarlas abiertas».
- Nunca: la supervisora, la de preguntas, la de cierre, una fijada, una con algo pendiente o una de otro proyecto.
- Borrar sesiones, ramas, worktrees o stashes no forma parte del cierre.

## Informe de la ronda

Un párrafo en el chat y en el registro: qué se verificó, qué se archivó con qué permiso y qué queda abierto y por qué.
No es un diálogo. Una sesión liberada que vuelve a tocar el repositorio vuelve a `WORKING`.
