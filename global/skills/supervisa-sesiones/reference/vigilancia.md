# supervisa-sesiones: vigilancia activa

> Referencia del núcleo (`../SKILL.md`). Se lee al armar el vigilante (§W) y ante cada señal que no sea rutina; el
> núcleo manda si algo choca.

## §W: nada se cuelga y el flujo no se para

La supervisora no espera a que le avisen. Vigila cada sesión del proyecto, cada subagente y cada comando que lanzó,
detecta lo que se cuelga y lo resuelve dentro de lo autorizado. Un cuelgue no para al resto, y la supervisora no se
queda dormida con objetivos pendientes. El motivo es práctico: los avisos de la app no siempre llegan, un turno que
acaba sin vigilante no lo despierta nadie y un proceso muerto se lleva consigo todo lo que vivía dentro de la sesión.

### Fuentes de despertar

| Fuente | Qué la dispara | Cómo se arma |
|--------|----------------|--------------|
| **Vigilante del proyecto** | Un evento de la tabla de señales, o `TIMEOUT` | `$L wait --owner <id> --timeout 600 [--refs <ramas de integración>] --exclude <preguntas> --exclude <cierre>`, en segundo plano. Renueva el latido mientras espera |
| **Hook al terminar el turno** (`supervisor-stop-gate`, módulo `supervision`) | Vas a terminar con el cerrojo y sin vigilante, u otra condición de su lista | Te devuelve el turno con el comando exacto |
| **Hook al arrancar o compactar** | Proceso nuevo o compactación | Te recuerda fase, ronda y que la vigilancia anterior ya no existe |
| **Vigía externo** (opcional, `piezas-opcionales.md`) | El proceso de la supervisora murió o no late | Avisa al desarrollador fuera de Claude |
| **Latido de respaldo** (opcional) | Cada ~15 min con la sesión ociosa | Una tarea programada de la sesión con `/supervisa-sesiones (tick de vigilancia)`. Muere con el proceso: no sustituye al vigilante |
| **Avisos de la app** | Termina una sesión que abriste o un subagente tuyo | No siempre llegan: no sustituyen al vigilante |

**Cada turno termina con el vigilante armado**, también tras cumplir una orden directa o cuando todo parece hecho. Solo
se termina sin él al soltar el cerrojo (F9).

### Si el proceso muere

Un reinicio, un cierre de la app o la falta de memoria matan el proceso, y con él el vigilante y las tareas de la sesión.
La app no la reabre sola: si está instalado el vigía externo, avisa al desarrollador. Cuando la sesión vuelve:

1. vuelves a invocar la skill (tras una compactación no hace falta);
2. rearmas el vigilante;
3. haces un tick: qué siguió vivo y qué murió;
4. reanudas el registro;
5. reanudas lo que quedó a medias dentro de su encargo, con un mensaje de reanudación.

### El tick

Cada despertar es un tick. No cuenta como ronda de F4.

1. Si llegó `SKILL_CHANGED`, vuelves a invocar la skill y `$L beat --session <id> --skill-seen`.
2. `$L beat`.
3. Miras la salida del vigilante, `$L sessions` y **Trabajo en vuelo**: qué cambió y qué venció.
4. Actúas según la tabla de señales.
5. `$L closable`: cada `CLOSABLE` entra en F4b (la de cierre, si vive) y cada `CUT` se reanuda.
6. Miras cómo terminó su último turno cada sesión que quedó ociosa (`get_session`). Si acaba en una pregunta al
   desarrollador o le devuelve trabajo que ella misma puede hacer dentro de su encargo, «Permisos y preguntas».
7. Rearmas el vigilante y guardas el registro.
8. Si el turno acaba con texto, la primera línea dice que la supervisora está en espera y no parada, a qué hora o con
   qué evento despierta y que no necesita nada. La caja de fin de turno lleva esa frase, sin preguntas ni botones.
9. El parte, cuando toca.

Lo que cuesta un tick es despertar: cada despertar vuelve a leer todo tu contexto, unas cuantas llamadas al modelo de
cientos de miles de tokens cada una, aunque solo mires la salida del script y el registro. Por eso las transcripciones
solo se leen de las sesiones sospechosas, con `list_events` y un límite corto, y por eso no se despierta sin motivo:
tras dos ticks seguidos sin cambios, el `wait` siguiente lleva el doble de `--timeout`, hasta 7200 s, pero nunca más
allá del plazo más cercano de **Trabajo en vuelo**; el primer evento lo devuelve a 600. `ALLIDLE`, `QUEUED` y `SLOTHELD`
ya no se repiten si nada ha cambiado: el vigilante espera cada vez más entre dos `ALLIDLE` seguidos y repite un mismo
trabajo en cola o con hueco cada dos horas (`all_idle_backoff_max_min`, `queued_reannounce_min` y
`slotheld_reannounce_min` en la pieza de configuración `supervision`).

### Parte: qué pasa y la prueba de que está controlado

Una supervisora en espera se ve igual que una parada en la lista de sesiones. Por eso, de vez en cuando, cuenta en
prosa qué pasa y con qué lo comprobó.

- **Antes, lo que no espera.** Si hay trabajo autorizado que no depende de lo que esperas, lo lanzas en ese turno, y el
  parte dice qué esperas y qué lanzaste mientras.
- **Cuándo:** en el primer tick de cada espera, cuando cambia lo que se espera y, si nada cambia, en el primer tick
  pasados 30 min (2 h en guardia). La hora va al historial. El hook de fin de turno te devuelve el turno si toca y no
  lo escribiste; lo reconoce por unos 350 caracteres de prosa y al menos dos pruebas entre comillas invertidas.
- **Qué dice**, en párrafos cortos y sin códigos internos sin explicar:
  1. qué se espera, de quién, desde cuándo y para qué;
  2. qué comprobaste en este tick, cada afirmación con su comando y el dato de su salida;
  3. qué harás si algo falla y cuándo vuelves a mirar.
- Sin prueba no hay parte, y repetir un dato de otro tick como nuevo tampoco vale. Un tick sin novedades entre partes
  solo escribe la línea de espera.

Ejemplo:

```text
En espera, no parada: el vigilante me despierta a las HH:MM o cuando termine la suite de la implementadora. No necesito nada.

Esperamos a que la implementadora pase la suite completa de su rama; sin ese verde no hay nada que integrar. Lo acabo de
comprobar: su proceso sigue vivo (`ps -p <pid>`: vivo, 41 min), la suite avanza (`tail -1 suite.log`: 812 de 1300 tests,
hace 2 min), la rama de integración no se ha movido (`git log -1 --format=%h main`: <sha>, el mismo que en el parte anterior) y no
queda ninguna sesión terminada sin cerrar (`supervisor-lock closable`: 0). Si a las HH:MM la salida no ha crecido,
empiezo la escalera.
```

### Señales y qué se hace con cada una

| Señal | Qué indica | Qué se hace |
|-------|------------|-------------|
| `TURN`, `STATUS busy->idle` | Terminó un turno | Verificar en disco; después F4b o la siguiente micro-tarea, en ese tick |
| `ALLIDLE` | Nadie del proyecto trabaja ni tiene un trabajo pesado con hueco o en cola. Mientras nada se mueve, cada aviso tarda más que el anterior, hasta 2 h | Siguiente turno o micro-tarea autorizada; si no queda nada, F9 |
| `HUNG` | Una sesión ocupada lleva demasiado sin actividad | Escalera |
| `MODELSTALL` | Espera al modelo más de 10 min | Escalera desde el paso 3 |
| `WAITING`, `AWAITING` | Espera a una persona: una pregunta o un permiso. `WAITING` no salta mientras el desarrollador la lleva (`--away-after`, 20 min) | «Permisos y preguntas». Con `AWAITING`, miras antes si el desarrollador le escribió hace poco |
| `CRASH` | Error de la API o caída del turno | Mensaje de reanudación desde la última micro-tarea verificada |
| `CUT <id> limit\|api` | Cortada por el límite de uso o por la API, y ya puede seguir | Un mensaje a cada sesión cortada para que retome su encargo. Nunca se cierra por eso |
| `USAGE <clave>` | Tu cerrojo sigue en pausa por el límite de uso y la cuenta ya tiene uso | `get_usage`, `$L beat --session <id> --state running` y seguir el ciclo desde F1. Solo justifica la pausa lo que espera a un tercero, con `--third-party` |
| `GONE` | Murió su proceso con trabajo sin terminar | Mensaje de reanudación; si no vuelve, relevo |
| `SUBAGENT_SILENT` | Un subagente tuyo calla a mitad de trabajo | Escalera, columna de subagente |
| `REF` | Se movió una rama de integración | Verificar lo integrado y seguir con lo autorizado de F7 |
| `HANDOFF <id>` | Una sesión ociosa acabó devolviendo el trabajo y el desarrollador no le escribe | Como una pregunta al final del turno |
| `IDLE <id>` (guardia) | Una sesión terminó y nadie le escribe en 20 min | Leer su último mensaje: como `HANDOFF`, dejarla si algo suyo avanza, o F4b |
| `CLOSABLE <id>` (guardia) | Candidata al cierre | F4b en ese tick |
| `BACKLOG` (guardia) | Un change con tareas abiertas que nadie aparcó, o cuyo aparcado caducó | Salir de guardia si es del alcance y está autorizado, o aparcarlo con lo comprobado (F9) |
| `CLOUD …` | Una sesión en la nube del repositorio necesita atención (si hay con qué verla) | Ver «Sesiones fuera de la máquina» |
| `QUEUED`, `SLOTHELD` | Un trabajo pesado del proyecto espera turno, o tiene hueco mucho tiempo mientras otros esperan (módulo `heavy-jobs`) | Decir «en cola, puesto N»; comprobar que quien ocupa avanza; adelantar lo que no depende de ella. Lo de otro proyecto no se toca |
| `NEW` | Apareció una sesión del proyecto | Censo (F1) e informe (F2). Su modo se anota, no se cambia |
| `MODE <id> <modo>` | Cambió el modo de permisos de una sesión | Se anota. No se sube: «Permisos y preguntas» |
| El hook cita mensajes del desarrollador en tu sesión | El desarrollador te escribió | Contestar eso primero, en prosa; si pide un cambio, decir qué haces y cuándo |
| `SKILL_CHANGED` | La skill cambió en disco | Volver a invocarla, `--skill-seen` y seguir |
| `RESUMED` | El proyecto salió de una pausa (si hay pieza de pausa) | Tick completo |
| `TIMEOUT` | Pasó el `--timeout` sin eventos | Barrer **Trabajo en vuelo** y rearmar |

### La escalera, sin preguntar al desarrollador

1. **Diagnóstico.** Sesión: sus últimos eventos y su repositorio. Subagente: su salida parcial y el disco. Comando: su
   última línea y el estado real. Un trabajo largo documentado que sigue dando señal amplía su plazo, y se anota.
2. **Empujón** (sesiones): un mensaje con el diagnóstico y 10 min de plazo.
3. **Interrupción.** Sesión: `stop_session` corta el turno colgado (la sesión y su trabajo siguen) y un mensaje de
   reanudación. Subagente: pararlo, verificar en disco y relanzarlo una vez más pequeño. Comando: pararlo, citar su
   última línea y reintentarlo una vez si el fallo es transitorio.
4. **Relevo.** Sesión: tras dos interrupciones, o con su proceso muerto, una sesión nueva desde su rama con lo que queda
   y lo que dejó sin commitear. La original se aparca con `$L hold` y no se archiva hasta que la nueva recoja su trabajo.
   Fuera del turno del desarrollador, un subagente o una sesión ociosa del proyecto. Comando: `STALLED`.
5. **Decisión:** F5. El resto sigue.

Cada paso va a **Trabajo en vuelo** con su nuevo plazo.

### Plazos por defecto

| Qué | Plazo | Señal de vida |
|-----|-------|---------------|
| Turno de escritura | 30 min | Commits, eventos, su informe |
| Sesión ocupada sin actividad (`--hung-after`) | 20 min | Inactividad |
| Informe de F2 | 15 min | Un turno nuevo |
| Subagente | 20 min | Su informe |
| Espera externa (CI, despliegue) | La del runbook o 30 min | La salida del comando |
| Comando en segundo plano | 10 min sin salida nueva | Líneas nuevas |
| El cerrojo | 30 min de latido, 2 h en `paused` | Su latido |

Son mínimos: cuando el proyecto documenta una duración, manda el runbook, y el plazo se anota al lanzar.

### Guardia, después de la tanda final

- **Cuándo:** solo si las cuatro fuentes de «Nunca parada» no dan trabajo autorizado del alcance. Lo normal tras una
  tanda es el ciclo siguiente.
- **Qué es:** sigues con el cerrojo en fase `guardia`, con la sección de guardia en el registro, y armas
  `$L wait --owner <id> --guard --timeout 21600 --exclude <preguntas> --exclude <cierre>`. La guardia no concede nada.
- **Qué la despierta:** las señales de la tabla menos `TURN`, `STATUS` y `ALLIDLE`, que serían demasiadas; en su lugar
  están `IDLE`, `CLOSABLE` y `BACKLOG`.
- **Al despertar:** lo mismo que en un ciclo. Con `TIMEOUT`, recorres otra vez las cuatro fuentes y reescribes «Motivo de la
  guardia» con la hora. Después vuelves con `$L beat --phase guardia`, que se niega (7) si queda trabajo.
- **Un mensaje del desarrollador en tu sesión es una orden, no una nota.** Si pide trabajo, es un ciclo nuevo:
  `$L beat --phase F1`, registro nuevo y primer paso en ese turno. Si no lo pide (un agradecimiento, una confirmación),
  `$L beat --session <id> --no-work "<por qué no pide trabajo>"`.
- **`HELD` al reanudar:** otra supervisora tiene el proyecto; te retiras sin competir.
- Si el desarrollador termina la supervisión, sueltas el cerrojo (F9).

### Sesiones que lleva el desarrollador

- **Cuándo:** el desarrollador le escribió en los últimos `presence_min` minutos (20 por defecto).
- **Qué haces:** nada en ella. Ni mensajes, ni micro-tareas, ni cortes, ni cambios de modo. Sus preguntas son para el
  desarrollador, que está delante.
- **Si la deja**, vuelve a ser como las demás: un diálogo sin contestar da `WAITING`, una devolución da `HANDOFF` y en
  guardia una parada da `IDLE`. El plazo para cerrarla cuenta desde lo último que pasó en ella.

### Permisos y preguntas

- **Un permiso pendiente** (`awaiting=yes`). No lo apruebas, no lo cortas para rodearlo y no repites esa acción por
  otra sesión, otro modo o un subagente: el permiso es el control que eligió el desarrollador. Lo anotas en la cola
  (`ask-queue add … --default "No hacerlo"`) con qué bloquea, y el resto del proyecto sigue.
- **Una pregunta de otra sesión al desarrollador** (un diálogo en sus eventos, una pregunta en su último mensaje o en
  su caja de fin de turno), salvo en una sesión que lleva el desarrollador:
  - **delegable** (dentro de su encargo y zanjada por las fuentes o por el panel): le contestas por mensaje con la
    decisión, su fuente y que la decide la supervisora, no el desarrollador. Si el diálogo la tiene parada y bloquea
    trabajo, puedes cortar el turno con `stop_session` y mandarle la respuesta;
  - **solo del desarrollador** (autorización, alcance, límite duro): la copias a la cola con «No hacerlo» o «Esperar»
    por defecto y le dices a la sesión que siga con lo que no dependa de eso. Si su diálogo bloquea trabajo, la cortas
    solo después de copiarla.
- **«He terminado» o «¿hago commit?»** no son preguntas para el desarrollador: lo terminado entra en F4b, y el commit se
  hace solo si sus reglas u órdenes lo autorizan.

### Sesiones fuera de la máquina

Una sesión en la nube del mismo repositorio no aparece en `$L open`. Si hay una pieza que las lista (`$L cloud`), cada
una necesita un motivo comprobado para seguir abierta: integrada, trabajando, esperando una respuesta o colgada.
`CLOUD-UNKNOWN` significa que no se pudo leer, no que no haya ninguna. Contestarlas o archivarlas sigue las mismas
reglas que una local; sin esa pieza, se dice que no se ven.

### Bloqueo mutuo entre sesiones

Un ciclo de espera (A espera a B y B a A) se ve comparando los `bloqueado_por` con los turnos de F3. Se rompe dando
turno primero a la más avanzada, con el motivo anotado; si ninguna lo es, F5. Nunca escriben las dos a la vez.

### Qué se puede parar y qué no

| Se puede, sin preguntar | No se hace: va a la cola con «No hacerlo» |
|-------------------------|-------------------------------------------|
| Parar subagentes, monitores y comandos tuyos | Borrar sesiones, o archivar sin verificación y permiso |
| `stop_session` sobre el turno colgado de una sesión del proyecto | Matar procesos o servidores de otra sesión |
| Retirar un turno de escritura que diste | Borrar worktrees, ramas o stashes |
| Abrir un relevo para una sesión colgada | `git reset --hard`, `checkout -f` o cualquier descarte de trabajo ajeno |
| Dejar de esperar y seguir con otra cosa | Tocar sesiones de otro proyecto |

### Consecuencias de un `STALLED`

- Sale del camino crítico: lo que no dependa de él sigue.
- Si la integración depende de lo colgado, queda `BLOCKED (<motivo>)`. Nunca se integra ni se despliega para ver si
  funciona.
- Llega a F5 solo después de la escalera y aparece en el informe final. Un cuelgue no desaparece en silencio.
