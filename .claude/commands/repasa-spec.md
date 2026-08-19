---
description: "Pipeline OpenSpec secuencial — gaps → hydrate → apply → gaps (desatendido, multiagente)"
argument-hint: "[slug]"
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

**Regla:** si el mensaje encaja con **pipeline completo** / **repasa spec** con un change-id, el agente **debe** cargar y seguir **`.claude/skills/repasa-spec/SKILL.md`** aunque no aparezca `/repasa-spec`.

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

**Prohibido en este comando:**

- Lanzar fases 2–4 mientras la fase anterior no haya cerrado con su criterio de salida.
- Ejecutar dos fases en paralelo (p. ej. `mejora-tarea` + `aplica-tarea` a la vez).
- Saltarse fases salvo bloqueo documentado (ver skill — § Stop conditions).

## Qué ejecutar (obligatorio)

1. Resolver slug (arriba).
2. Leer y seguir **`.claude/skills/repasa-spec/SKILL.md`** (orquestación completa).
3. Aplicar **`.claude/skills/repasa-spec/SKILL.md`** (L2).
4. Operar en **modo multiagente** — orquestador coordina; subagentes por fase según skill delegada.
5. Entregar resumen por fase + **`## Verification`** global al cierre.

## Salida esperada

- `openspec/changes/<slug>/GAPS.md` — actualizado en fases 1 y 4.
- Artefactos hidratados + `READY-TO-APPLY.md` — fase 2.
- `tasks.md` con checkboxes aplicables marcados — fase 3.
- Resumen en chat: estado por fase (OK / parcial / bloqueado), conteos gaps, tareas pendientes.
- **`## Verification`** con evidencia de la fase 3 (apply) y coherencia post-gaps.

## Relación

| Artefacto | Rol |
|-----------|-----|
| `.claude/skills/repasa-spec/SKILL.md` | Orquestación secuencial del pipeline |
| `.claude/skills/repasa-spec/SKILL.md` | Reglas L2 + triggers NL |
| `.claude/skills/openspec-gap-analysis/SKILL.md` | Fases 1 y 4 |
| `.claude/skills/mejora-tarea/SKILL.md` | Fase 2 |
| `.claude/skills/aplica-tarea/SKILL.md` + `multiagente` | Fase 3 |
| `/gaps-spec`, `/mejora-tarea`, `/aplica-tarea` | Fases individuales (no encadenar solas salvo petición explícita) |
