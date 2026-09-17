---
name: /repasa-spec
id: repasa-spec
category: Workflow
description: "Pipeline OpenSpec secuencial — gaps → hidratar → aplicar → gaps, repitiendo la ronda hasta que no queda ningún hueco pendiente (desatendido, multiagente)"
---

# Repasa spec (OpenSpec pipeline)

Cuando el desarrollador invoca **`/repasa-spec [<slug>]`** (o lenguaje natural equivalente), ejecuta el **pipeline completo** de revisión e implementación OpenSpec **en secuencia estricta** — cada fase debe **terminar por completo** antes de iniciar la siguiente. **Nunca** ejecutar fases en paralelo.

## Cómo invocar (slash + lenguaje natural)

| Vía | Ejemplos |
|-----|----------|
| **Slash command** | `/repasa-spec background-permission` |
| **Alias corto** | `repasa-spec stats-net` |
| **Lenguaje natural (ES)** | `repasa la spec stats-net`, `repasa el change background-permission`, `pipeline openspec stats-net`, `ejecuta el ciclo completo del change` |
| **Lenguaje natural (EN)** | `run repasa-spec stats-net`, `full openspec pipeline stats-net`, `review and apply change stats-net` |

**Regla:** si el mensaje encaja con **pipeline completo** / **repasa spec** con un change-id, el agente **debe** cargar y seguir **`.cursor/skills/repasa-spec/SKILL.md`** aunque no aparezca `/repasa-spec`.

## Slug (obligatorio)

- Parsear el **primer token kebab-case** tras `repasa-spec` (slash opcional, **sin** `:` antes del slug).
- Ejemplo: `/repasa-spec background-permission` → slug `background-permission`.
- Debe existir (o crearse en fase 1 vía gaps Mode A) `openspec/changes/<slug>/`.
- Si falta slug → preguntar **una vez**: *"Indica el change-id (slug kebab-case bajo openspec/changes/)"* y parar.

## Pipeline secuencial (orden fijo)

Ejecutar **exactamente** estas fases, **una tras otra**, esperando el criterio de cierre de cada skill antes de continuar:

| Fase | Comando equivalente | Skill delegada | Propósito |
|------|---------------------|----------------|-----------|
| **1** | `/gaps-spec <slug>` | `openspec-gap-analysis` | Gaps pre-hydrate → `GAPS.md` |
| **2** | `/mejora-tarea <slug>` | `mejora-tarea` | Hidratar artefactos → READY TO APPLY |
| **3** | `/aplica-tarea <slug>` | `aplica-tarea` + `multiagente` | Implementar `tasks.md` |
| **4** | `/gaps-spec <slug>` | `openspec-gap-analysis` | Gaps post-apply → `GAPS.md` actualizado |


## El ciclo se repite hasta que no queda nada que arreglar

La fase 4 **no es el final**: es un punto de decisión. La fase 1 se ejecuta **una vez**; las fases
**2 → 3 → 4** son una **ronda**, y las rondas se repiten:

```text
Fase 1 (gaps, una vez)
  └─ ronda N:  Fase 2 (hidratar)  →  Fase 3 (aplicar)  →  Fase 4 (gaps)
        ├─ gaps_pending = 0 ......................... CICLO TERMINADO
        └─ gaps_pending > 0 ......................... ronda N+1 (vuelta a la fase 2)
```

El número sale del apartado `## Pending count` de `GAPS.md`, que es el mismo entero que la skill de
gaps escribe como última línea obligatoria.

| La ronda termina con | Qué hacer |
|---|---|
| `gaps_pending` = 0 | **Terminar** y dar el informe |
| `gaps_pending` > 0, la ronda cerró al menos un hueco y vamos por la ronda < 5 | **Otra ronda**, desde la fase 2 |
| `gaps_pending` > 0 y la ronda no cerró **ninguno** | **Parar**: repetir una ronda idéntica repite el trabajo. Explicar, hueco por hueco, qué se resistió |
| Ronda 5 con `gaps_pending` > 0 | **Parar** y decir qué necesita cada hueco que queda |

**Terminar con `gaps_pending > 0` sin que se cumpla ninguna de esas paradas es un fallo del ciclo**, no
un resultado: significa que encontró defectos y los dejó apuntados en vez de arreglados.

Los huecos que el ciclo **no puede cerrar solo** —hace falta autorización del desarrollador, acceso a
producción o una decisión de negocio— no mantienen el bucle girando: se anotan en `GAPS.md` con el
motivo, se listan en el informe bajo «necesita al desarrollador» y **no cuentan** en `gaps_pending`.

**Un hueco que aparece durante la fase 3 se arregla en la fase 3**, si está al alcance del trabajo que
ya se tiene entre manos (toca ficheros que esa ronda ya está cambiando, o cuesta menos arreglarlo que
escribirlo). Dejarlo para el informe de la fase 4 es justo lo que hace que un ciclo acabe con huecos
pendientes que nunca lo estuvieron de verdad.

**Prohibido en este comando:**

- Lanzar fases 2–4 mientras la fase anterior no haya cerrado con su criterio de salida.
- Ejecutar dos fases en paralelo (p. ej. `mejora-tarea` + `aplica-tarea` a la vez).
- Saltarse fases salvo bloqueo documentado (ver skill — § Stop conditions).
- **Cerrar el ciclo con `gaps_pending > 0`** sin que se cumpla una de las paradas de arriba.

## Qué ejecutar (obligatorio)

1. Resolver slug (arriba).
2. Leer y seguir **`.cursor/skills/repasa-spec/SKILL.md`** (orquestación completa).
3. Aplicar **`.cursor/rules/repasa-spec-openspec-pipeline.mdc`** (L2).
4. Operar en **modo multiagente** — orquestador coordina; subagentes por fase según skill delegada.
5. Entregar resumen por fase + **`## Verification`** global al cierre.

## Salida esperada

- `openspec/changes/<slug>/GAPS.md` — actualizado en fases 1 y 4.
- Artefactos hidratados + `READY-TO-APPLY.md` — fase 2.
- `tasks.md` con checkboxes aplicables marcados — fase 3.
- Resumen en chat: estado **por ronda y por fase** (OK / parcial / bloqueado), conteos de gaps de cada
  ronda y tareas pendientes.
- Última línea del informe: el entero `gaps_pending`, que debe ser **0** salvo que se explique qué
  parada del bucle se cumplió.
- **`## Verification`** con evidencia de la fase 3 (apply) y coherencia post-gaps.

## Relación

| Artefacto | Rol |
|-----------|-----|
| `.cursor/skills/repasa-spec/SKILL.md` | Orquestación secuencial del pipeline |
| `.cursor/rules/repasa-spec-openspec-pipeline.mdc` | Reglas L2 + triggers NL |
| `.cursor/skills/openspec-gap-analysis/SKILL.md` | Fases 1 y 4 |
| `.cursor/skills/mejora-tarea/SKILL.md` | Fase 2 |
| `.cursor/skills/aplica-tarea/SKILL.md` + `multiagente` | Fase 3 |
| `/gaps-spec`, `/mejora-tarea`, `/aplica-tarea` | Fases individuales (no encadenar solas salvo petición explícita) |
| `/run-spec <slug>` | **Capa superior** — ejecuta este pipeline como fases P2–P4 y sigue hasta tests, regresión y publicación de la rama, parando en la puerta de aprobación del deploy. No encadenar `/repasa-spec` a mano mientras `run-spec` está corriendo. |
