---
name: /run-spec
id: run-spec
category: Workflow
description: "Top layer — drive one OpenSpec change from idea to a published branch unattended (prepara → repasa → gap-closure loop → confirm → tests → regression → commit + push), then stop at a deploy-approval dialog"
---

# Build spec (OpenSpec top-level loop)

Cuando el desarrollador invoca **`/run-spec <slug>`** (con la descripción en las líneas siguientes) o lenguaje natural equivalente (`construye la spec entera`, `de la idea al deploy`, `loop openspec completo`), lleva **un** change OpenSpec desde una descripción en texto plano hasta la feature desplegada, **de forma desatendida**, parando solo ante un bloqueo real.

## Obligatorio (este turno)

1. Leer **`.cursor/skills/run-spec/SKILL.md`** en el mismo turno **antes** de ejecutar ninguna fase.
2. Aplicar **`.cursor/rules/run-spec-openspec-loop.mdc`** (L2).
3. Crear o reanudar el fichero de estado **`openspec/changes/<slug>/RUN-LOOP.md`**.
4. Ejecutar las fases P0 → P8 en orden, una a una, cada una delegada a su skill canónica en un subagente de contexto fresco (la publicación y la puerta de deploy corren en el agente principal).
5. Cerrar con el informe obligatorio y la última línea canónica `Run-spec verdict: <VERDICT>`.

## Invocación

```text
/run-spec [slug]
[descripción del problema o de la feature]
```

Ejemplos:

```text
/run-spec rider-eta
Mostrar el ETA en vivo en la tarjeta del rider, recalculado en cada poll.
```

```text
/run-spec rider-eta --no-deploy --max-iter 2
Mostrar el ETA en vivo en la tarjeta del rider.
```

```text
/run-spec rider-eta
```

La tercera forma es **modo reanudación**: el change ya existe, no hace falta descripción y el bucle continúa desde `RUN-LOOP.md`.

## Parsing

| Campo | Regla |
|-------|-------|
| `slug` | Primer token tras `run-spec` (barra inicial opcional, separado por espacios, **sin** `:`). Debe ser kebab-case. |
| `--no-deploy` | Salta la puerta de deploy y termina en `READY TO DEPLOY`. P7 sí commitea y empuja la rama actual. |
| `--max-iter N` | Presupuesto del bucle de gaps, `1 ≤ N ≤ 5` (más de 5 se recorta a 5 y se registra). Por defecto **3**. |
| descripción | Todas las líneas tras la primera, verbatim. Los flags nunca forman parte de ella. |

Preguntar **una vez** y parar cuando: falta el slug o no es kebab-case; o la descripción está vacía **y** `openspec/changes/<slug>/` no existe.

## Fases

| # | Fase | Delegada | Criterio de salida |
|---|------|----------|--------------------|
| P0 | Parse + estado | — | slug válido; `RUN-LOOP.md` creado o reanudado |
| P1 | Bootstrap | `/prepara-tarea <slug>` + descripción | proposal + tasks + specs en disco (se salta si ya hay `proposal.md`) |
| P2 | Pipeline de revisión | `/repasa-spec <slug>` | línea pendiente en `GAPS.md` + `READY-TO-APPLY.md` |
| P3 | Bucle de cierre de gaps | `/repasa-spec <slug>` × ≤ `max_iter` | `gaps_pending = 0` **y** 0 tareas sin marcar que no lleven `[prod-verify]` |
| P4 | Repaso de confirmación | `/repasa-spec <slug>` (revisor fresco) | el gate sigue pasando |
| P5 | Tests de la feature | `/ejecuta-tests-reporte <slug>` | exit 0 |
| P6 | Regresión | tests completos + E2E del proyecto | exit 0 (si no hay ninguno documentado, degrada P7) |
| P7 | Publicación | `git commit` + `git push -u origin <rama>` | rama empujada (o nada que publicar) |
| P8 | Puerta de deploy | **diálogo de aprobación** → `/deploy` del proyecto | aprobado y deploy correcto → `DEPLOYED` |

Las líneas internas de tipo «para aquí, ejecuta el siguiente comando en un mensaje nuevo» de las skills delegadas quedan **anuladas** dentro de este bucle — mismo override de pipeline que `/repasa-spec`.

## Gate y `[prod-verify]`

El gate de cierre de gaps se lee de disco, nunca de la prosa de un agente:

- `gaps_pending` — última línea `Gaps pending (mejora + apply): N` de `GAPS.md`.
- `tasks_unchecked` — líneas `- [ ]` de `tasks.md` **sin** el token literal `[prod-verify]`.
- `tasks_prod_verify` — líneas sin marcar **con** ese token: nunca bloquean, nunca se auto-marcan, siempre se listan verbatim en el informe final.

## Git y deploy

**La publicación (P7) es automática; el deploy (P8) no.**

Invocar `/run-spec` autoriza exactamente **una** mutación git: commitear el trabajo pendiente y empujar la **rama actual** (`git push -u origin <rama>`). El bucle nunca mergea, rebasa, etiqueta, fuerza push ni empuja otra rama, y no toca git en absoluto si estás en la rama de producción del proyecto.

El deploy queda **bajo puerta**: el bucle para y abre un diálogo `AskUserQuestion` — *desplegar ahora, desatendido* / *parar aquí* — tras exponer el commit empujado, los resultados de tests y regresión, las tareas `[prod-verify]` residuales y qué hará realmente el comando de deploy del proyecto. Puede añadir hasta tres dudas genuinas sobre ese deploy. La aprobación nunca se infiere de la invocación y el silencio nunca es un sí. Al aprobar, el `/deploy` del proyecto corre intacto, con sus propios diálogos.

| Situación | Veredicto |
|-----------|-----------|
| El desarrollador aprueba y el deploy va bien | `DEPLOYED` |
| El desarrollador para en la puerta, o `--no-deploy` | `READY TO DEPLOY` |
| Sin canal de diálogo (no interactivo, background, tick paced) | `AWAITING DEPLOY APPROVAL` |
| El proyecto no tiene comando de deploy | `BLOCKED (no deploy command)` |

## Modo paced

`/loop /run-spec <slug>` ejecuta **una fase por tick** y arma el siguiente despertar con el mecanismo de salida de shell monitorizada de `/loop` (sentinela único `AGENT_LOOP_WAKE_build_spec_<slug>` + payload JSON con el prompt). En Claude Code el contrato equivalente usa `ScheduleWakeup`. Sin primitiva de despertar, el bucle lo dice y corre inline.

## Salida

`## Run loop — <slug>` (tabla de fases) → `## Verification` → `## Residual` → `## Resumen`, y como última línea, verbatim:

```text
Run-spec verdict: DEPLOYED | READY TO DEPLOY | AWAITING DEPLOY APPROVAL | BLOCKED (<reason>) | NO PROGRESS
```

## Relación

| Comando | Rol |
|---------|-----|
| `/run-spec <slug>` | **Capa superior** — idea → rama publicada, desatendido, parando en la puerta de deploy |
| `/repasa-spec <slug>` | Capa inferior — un ciclo de revisión y aplicación (P2/P3/P4 aquí) |
| `/prepara-tarea`, `/gaps-spec`, `/mejora-tarea`, `/aplica-tarea` | Fases individuales — no encadenarlas a mano mientras corre `run-spec` |
| `/ejecuta-tests-reporte`, `/verifica-tarea`, `/harness-spec` | Tests y verificación profunda |
| `/finaliza-spec`, `/archiva-tarea` | Commit + archivado — manual, después del bucle |
