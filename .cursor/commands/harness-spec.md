---
name: /harness-spec
id: harness-spec
category: Quality
description: "Harness persistente + supervisor independiente en contexto fresco para verificar cumplimiento de una spec/change OpenSpec"
---

# Harness spec (harness persistente + supervisor independiente)

Cuando el desarrollador invoca **`/harness-spec [<target>]`**, **`crea un harness para la spec`**, **`harness de verificación`**, **`supervisor de la spec`** o **`verificador independiente`**, construye — si procede — un **harness de tests persistente y re-ejecutable** mapeado a los Requirements/Scenarios de una spec/change OpenSpec, y lo hace pasar por un **supervisor independiente** (subagente en contexto fresco, sin memoria de esta conversación) antes de dar el cambio por verificado.

**No sustituye** `/verifica-tarea` ni `/comando-verificar` — son matrices de un solo uso, de la misma sesión que implementó/revisó. `/harness-spec` es para cuando el auto-informe de esa misma sesión no es prueba suficiente: auth/autorización, scoping multi-tenant, ciclos regulatorios, billing, acciones destructivas.

## Obligatorio (este turno)

1. Leer **`.claude/skills/harness-spec/SKILL.md`** en el mismo turno antes de ejecutar nada.
2. Ejecutar **Fase 0** (resolver target) y luego el **gate de completitud (Fase 0.25)**: si el target es un change con tareas de `tasks.md` sin marcar, **negarse a construir el harness** y parar (ver abajo), salvo override explícito del desarrollador en este mismo turno.
3. Solo si el gate pasa: ejecutar **Fase 0.5** (evaluar proporcionalidad) **antes** de tocar ningún fichero — si las señales están en contra o son mixtas, puede terminar en "no procede" o en un diálogo `AskUserQuestion`, sin llegar a construir nada.
4. Solo si la Fase 0.5 concluye que procede: ejecutar Fases 1–6 del skill (inventario → construir/actualizar harness → ejecutar → supervisor independiente → bucle acotado ≤3 ciclos → cierre).

## Gate de completitud del target (Fase 0.25 — bloqueante)

Un harness verifica que las conductas implementadas cumplen la spec; **no** verifica que la implementación esté terminada. Un harness verde sobre un change a medio implementar (p.ej. `tasks.md` a 32/35) es una **falsa señal de cierre**. Por eso, cuando el target es un change (`openspec/changes/<slug>/`), antes de Fase 0.5:

- Comprobar completitud con evidencia real: `openspec status --change "<slug>" --json` y el conteo de `- [ ]` pendientes en `openspec/changes/<slug>/tasks.md`.
- **Si queda cualquier tarea sin completar → negarse**: no crear tests, no ejecutar `run.sh`, no lanzar el supervisor, no escribir artefactos. Reportar `hechas/total`, la lista literal de tareas pendientes, y remitir a terminar la implementación (`/aplica-tarea <slug>`) antes de volver a `/harness-spec`.
- **Override único:** solo si el desarrollador pide a sabiendas construirlo sobre el change incompleto en este mismo turno; dejar constancia en `STATUS.md` y en el cierre. La sola invocación de `/harness-spec` no es override.
- Spec canónica (`openspec/specs/<capability>/`): el gate no bloquea (ya es estable).

## Resolución del target

Igual que `/sumario-spec` y `/verifica-tarea`:

1. **Argumento explícito** — `/harness-spec <slug-o-capability>`.
2. **Sin argumento** — detectar en la ventana de chat actual qué spec/change se ha mencionado.
   - Ninguna detectada → `openspec list --json` + `openspec list --specs --json`, y **AskUserQuestion** listando candidatas recientes. No adivinar.
   - Exactamente una → usarla, sin preguntar.
   - Varias → **AskUserQuestion** con cada una como opción, explicando de qué trata cada una.

## Evaluación de proporcionalidad (Fase 0.5 — nunca omitir)

Antes de construir cualquier test o lanzar al supervisor, valorar con evidencia real del repo (`openspec status`, `openspec validate`, matrices previas, `git log`) si esta spec/change **merece** el coste de un harness completo. Señales a favor: auth/autorización, scoping multi-tenant, regulatorio (EINF/APA-EGAR/submission gateway), dinero, acciones destructivas/irreversibles, gaming detectado antes. Señales en contra: doc-only/infra-only/copy, spec aún inestable, ya cubierta al 100% sin cambios desde entonces, cambio trivial.

- Claro a favor → seguir sin preguntar, dejando la justificación en una línea.
- Claro en contra → no construir el harness completo; explicar por qué en 2-3 frases y sugerir `/verifica-tarea` o `/gaps-spec` según el caso; parar salvo que el desarrollador ya haya insistido explícitamente en el mismo mensaje.
- Mixto/ambiguo → **AskUserQuestion** en lenguaje natural y bien explicado, ofreciendo como mínimo: harness completo + supervisor / solo harness sin supervisor / usar `/verifica-tarea` en su lugar. Esperar respuesta.

Detalle completo de la escala de señales en el skill.

## Fases (resumen)

| Fase | Acción |
|------|--------|
| **0** | Resolver target (spec/change) — argumento, chat, o diálogo |
| **0.25** | **Gate de completitud** — change con `tasks.md` incompleto → negarse y parar (salvo override explícito) |
| **0.5** | Evaluar proporcionalidad — señales a favor/en contra, diálogo si es ambiguo |
| **1** | Inventario — cada Requirement + `#### Scenario:` → `SC-<slug>-NN` |
| **2** | Construir/actualizar harness — tests PHPUnit/Playwright reales, tag `@scenario`, checklist anti-gaming |
| **3** | Ejecutar el harness — `run.sh`, resultado en `run-<timestamp>.json` |
| **4** | Supervisor independiente — subagente en contexto fresco, re-ejecuta él mismo, checklist adversarial, veredicto por requirement |
| **5** | Bucle evaluator-optimizer — corregir y relanzar supervisor (nueva llamada), máx. 3 ciclos |
| **6** | Cierre — `## Verification` → `## Qué se ha verificado` → `## Resumen` |

Detalle completo: `.claude/skills/harness-spec/SKILL.md`.

## Artefactos

| Path | Contenido |
|------|-----------|
| `.claude/context/verification/harness-<slug>/harness-manifest.md` (+ `.json`) | req_id → scenario_id → test_id → layer → status |
| `apps/api/tests/Harness/<PascalSlug>HarnessTest.php` | Tests PHPUnit reales |
| `apps/web/e2e/harness-<slug>.spec.ts` | Tests Playwright reales |
| `.claude/scripts/harness/<slug>/run.sh` | Runner re-ejecutable |
| `.claude/context/verification/harness-<slug>/run-<timestamp>.json` | Resultado crudo de la última ejecución |
| `.claude/context/verification/harness-<slug>/supervisor-verdict-<timestamp>.md` (+ `.html`) | Veredicto del supervisor independiente |
| `.claude/context/verification/harness-<slug>/STATUS.md` | Estado vigente: iteración, veredicto, pendientes |

## Related commands

| Comando | Rol |
|---------|-----|
| **`/harness-spec [<target>]`** | Harness persistente + supervisor en contexto fresco — alto riesgo |
| **`/verifica-tarea [<slug>]`** | Matriz de un solo uso, misma sesión — cierre habitual |
| **`/comando-verificar`** | Matriz combinatoria acotada al diff actual |
| **`/gaps-spec <slug>`** | Gaps pre-implementación, sin runtime |
| **`/ejecuta-tests-reporte`** | Batería de tests + reporte, sin mapeo a escenarios ni supervisor |

## Prohibido

- Construir el harness sobre un change incompleto (`tasks.md` con `- [ ]` pendientes) sin override explícito del desarrollador en el mismo turno — ver Fase 0.25.
- Saltarse la Fase 0.5 y construir el harness directamente sin valorar si procede.
- Declarar `PASS` sin `supervisor-verdict-<timestamp>.md` en disco con veredicto global `PASS`.
- Que el orquestador redacte o suavice el veredicto del supervisor.
- Reutilizar la misma llamada de subagente para relanzar el supervisor (pierde independencia de contexto).
- Bucle sin límite — parar honestamente a los 3 ciclos si sigue en FAIL.
- Aflojar una aserción del harness para forzar un PASS.

## Related skills

- `.claude/skills/harness-spec/SKILL.md` — workflow completo, fundamento investigado y checklist anti-gaming.
