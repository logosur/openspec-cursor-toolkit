# supervisa-sesiones: registro, parada, modo manual, presupuesto e informe

> Referencia del núcleo (`../SKILL.md`). Se lee en F0b (esquema del registro), al parar o reanudar y en F9 (informe);
> el núcleo manda si algo choca.

## §2 Esquema del registro (`SUPERVISOR-*.md`)

El registro guarda el estado actual, reescrito en su sitio, porque se relee tras cada compactación: si crece con cada
tick, vuelve a llenar el contexto. La historia de ticks y rondas va a `HISTORIAL-<stamp>.md`, que no se lee entero.

```markdown
# Supervisión: <proyecto>, <YYYY-MM-DD HH:MM>

| Clave | Valor |
|-------|-------|
| proyecto | <nombre> · `<checkout principal>` · clave `<key>` |
| alcance | <texto, o «lo que las sesiones abiertas tienen entre manos»> |
| flags | no_deploy=<b> max_rondas=<N> |
| supervisora | <rol y esfuerzo> · complejidad: <simple|compleja, motivo> · ¿encaja?: <sí|un modelo más capaz encajaría mejor> |
| ronda | <n> |
| iniciado | <ISO8601> |
| actualizado | <ISO8601> |
| cerrojo | adquirido · reanudado · reclamado (de <id>) · de guardia · liberado |
| veredicto | RUNNING \| DEPLOYED — TANDA FINAL \| INTEGRATED — TANDA FINAL \| READY — TANDA FINAL \| BLOCKED (<motivo>) \| BLOCKED (supervisora duplicada) \| NO PROGRESS |

## Meta (F0b)
<la meta escrita del proyecto y su fuente>

## Objetivos (F0b)
| Objetivo | Criterio de hecho | Estado | Fuente |
|----------|-------------------|--------|--------|

## Autorizaciones
| Operación | Alcance (proyecto, rama, entorno) | Fuente comprobable | Vigente |
|-----------|-----------------------------------|--------------------|---------|

## Encaje (F0c)
| Asunto | Valor | Fuente |
|--------|-------|--------|
| rama principal / integración | | |
| integración (merge o PR) y push | | |
| puertas (tests, lint) y duración | | |
| comando de despliegue | | |
| exclusiones | | |
| recursos compartidos | | |
| copias locales de esta skill | presentes/ausentes (no se usan) | |

## Fases
| Fase | Estado | Evidencia | Actualizado |
|------|--------|-----------|-------------|

## Sesiones
| Sesión | id | Checkout | Rama | Rol | Permisos | Canal | Sucio | Sin subir | Estado | Última señal |
|--------|----|----------|------|-----|----------|-------|-------|-----------|--------|--------------|

## Colisiones y turnos
| Recurso | Sesiones | Turno | Motivo |
|---------|----------|-------|--------|

## Trabajo en vuelo (§W)
| Unidad | Tipo | Dueño | Inicio | Plazo | Última señal | Estado |
|--------|------|-------|--------|-------|--------------|--------|

## Cola de decisiones
| # | Origen | Decisión abierta | Fuentes miradas y por qué no bastan | Decidió | Decisión | Fuente | Cómo se deshace | Hora |
|---|--------|------------------|-------------------------------------|---------|----------|--------|-----------------|------|

## Cierres (F4b)
| Sesión | Verificación (comando y resultado) | Veredicto propio | Permiso de archivado | Estado |
|--------|------------------------------------|------------------|----------------------|--------|

## Hallazgos sin dueño
<!-- literales, con la sesión de origen -->

## Integración y despliegue
| Paso | Autorización | Merges (SHA) | Verificación | Despliegue | Resultado |
|------|--------------|--------------|--------------|------------|-----------|

<!-- En guardia: la sección de guardia que nombra el núcleo, una línea por fuente
     (mensajes del desarrollador, respuestas, backlog, meta) con lo que miraste. -->

## Log de rondas
| Ronda | Sesiones abiertas | Pendientes | Decisiones abiertas | Nota |
|-------|------------------:|-----------:|--------------------:|------|
```

Estados de sesión: `WORKING` · `READY_TO_CLOSE` · `RELEASED` (terminada y verificada, sigue abierta) · `ARCHIVED`
(archivada con verificación y permiso) · `ON HOLD` (solo con un `$L hold` vigente; se copian motivo y caducidad) ·
`BLOCKED` · `NO CONTACTABLE`. El **Log de rondas** guarda solo las cinco últimas.

## §8 Convergencia, parada y reanudación

| Situación | Qué hace la supervisora |
|-----------|-------------------------|
| Una sesión no ha declarado lo suyo | Sigue: no es un final válido |
| Queda una decisión delegable | La toma, o el panel (F5) |
| Una sesión se liberó y no se informó | Informe de F4b |
| Hay preguntas para el desarrollador | A `ask-queue` y a la tanda (F5, F9); solo un rumbo radical va en el acto. No se espera la respuesta |
| No queda nada autorizado que hacer | F9: tanda, veredicto y trabajo siguiente o guardia |
| Rondas sin progreso agotadas, con la escalera recorrida | `NO PROGRESS` con la lista exacta |
| Una tarea vence su plazo | Escalera de §W; el resto sigue |
| Otra supervisora viva en el proyecto | `BLOCKED (supervisora duplicada)` con quién y desde cuándo (§0) |
| No hay repositorio ni carpeta de trabajo | No arranca |
| Bloqueo real (rojo sin resolver, falta una credencial, una acción destructiva) | Se informa el hecho concreto: comando, salida y línea decisiva |

**Reanudar.** Al volver a invocar la skill, `acquire` responde `RESUMED` o `STALE` (§0). Se lee el último
`SUPERVISOR-*.md` con veredicto `RUNNING` y se sigue desde la primera fase sin cerrar, con presupuesto nuevo. Cada
autorización anotada se vuelve a comprobar en su fuente. Nunca se abre un registro nuevo dejando el anterior a medias.

**Tras un corte por límite de uso** (o un aviso `CUT`): primero el uso real, si la app lo enseña; después el censo
(`$L sessions`, `$L closable`); y, si hay uso, un mensaje a cada sesión cortada para que retome su encargo, en ese
turno. Si no hay uso, se aparcan con `hold` hasta la renovación y se arma el vigilante. Una sesión cortada no vuelve a
trabajar sola.

**Ticks programados** (`/loop /supervisa-sesiones`): no hacen falta, porque §W arma sus propias fuentes. Si se usan,
cada uno es un tick de §W.

## §9 Modo manual, sin herramientas de sesiones

Si no hay herramientas de sesiones de la app (otro editor, por ejemplo), se dice en la primera línea y:

1. el censo sale de lo comprobable: `$L sessions` (lee ficheros), `git worktree list`, ramas sin subir y changes con
   tareas abiertas;
2. si el desarrollador aporta la lista de sesiones al invocar, se usa; si no, lo desconocido se nombra así, sin parar a
   pedirla;
3. F2 se sustituye por la inspección de cada checkout y, si está instalada, `/cierra-sesion`;
4. lo demás funciona igual.

Nunca se simula un censo que no se pudo hacer.

## §10 Presupuesto de contexto

| Regla | Para |
|-------|------|
| Invocar la skill al arrancar el proceso, no tras cada compactación, y leer cada referencia al entrar en su fase | No cargar todo a la vez |
| Leer las reglas del proyecto una vez (F0c) y resumirlas en el registro | No releerlas en cada fase |
| El contexto de la supervisora es su registro, por debajo de unos 40 KB | El historial, con `tail` o `grep` |
| Transcripciones ajenas: `list_events` con límite corto o una búsqueda exacta | Nunca enteras |
| Informes de sesión y subagente: contrato fijo, hasta 15 líneas | |
| Git: `status -sb`, `log --oneline`, `grep` | Nunca diffs enteros |
| Documentos: solo el registro y su historial en la carpeta de `$L registry-dir` | Ningún análisis suelto en la raíz |
| Logs: la línea decisiva | |

## §11 Informe final

```markdown
## Supervisión de <proyecto>, <fecha>
<tabla de sesiones, con rol y estado final>

## Cierres
<sesión → verificación → archivada (con qué permiso) o abierta (qué espera)>

## Decisiones de la supervisora
<decisión → quién (supervisora o panel, con votos) → fuente → cómo se deshace → qué se ejecutó>

## Integración y despliegue
<paso → autorización → merges (SHA) → verificación → despliegue, una línea cada uno>

## Tanda final (la presenta la sesión de preguntas; aquí queda constancia)
1. Dónde quedó: <lo verificado, dónde y cómo> · espera a terceros: <qué y de quién>
2. Rumbos radicales: <pregunta → coste → qué se hizo entretanto → respuesta>
3. Autorizaciones y límites duros: <pregunta → «No hacerlo» → respuesta y fuente>
4. Archivado pendiente: <sesiones → qué permiso falta>
5. Decisiones a confirmar: <qué → por qué → cómo se deshace → respuesta>
6. ¿Algo más?: <su texto, si lo hay>

## Residual
<lo que queda abierto, literal: bloqueos, hallazgos sin aprobar, lo no comprobado y por qué>

## Resumen
<solo hechos verificados · cerrojo conservado o liberado y por qué>
```

**Última línea, literal y sin nada después:**

```text
Supervisor verdict: <VERDICT>
```
