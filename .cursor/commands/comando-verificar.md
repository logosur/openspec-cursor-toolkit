---
name: /comando-verificar
id: comando-verificar
category: Quality
description: "Deep combinatorial verification — matrix artifact, casuistics, regression, evidence-backed close"
---

# Comando verificar (deep verification)

When the developer invokes **`/comando-verificar`**, **`comando-verificar`**, **`verifica a fondo`**, **`verify thoroughly`**, **`prueba todas las combinaciones`**, or **`matriz de verificación`**, run the **deep verification workflow** before claiming completion.

**Does not replace** L1 `00-verification-gate.mdc`. **Extends** it with a combinatorial matrix executed first, then the same `## Verification` close.

## Mandatory (this turn)

1. Read **`.cursor/skills/comando-verificar/SKILL.md`** in the same turn before executing.
2. Load **`.cursor/rules/comando-verificar-a-fondo.mdc`** (L2).
3. Execute Phase 0–5 from the skill; write matrix artifact; close with `## Verification` + Resumen (VR-14).

## Scope parsing

Optional scope on following lines (one or more):

| Scope token | Example | Phase 0 action |
|-------------|---------|----------------|
| `current diff` | `/comando-verificar` + `current diff` | **REQ-CV-SCOPE-01**: `git diff HEAD --name-only` + path list in matrix header |
| Route | `/rider` | Inventory forms/UI on that route |
| `form_id` | `my_module_settings_form` | Form combinatorial matrix |
| Module / package | `my_package` | Surfaces + project test command for that package |
| Service | `MyDomainGuard` | Service casuistics + PHPUnit rows |
| OpenSpec slug | `comando-verificar` | Also read `openspec/changes/<slug>/VERIFY.md`; merge scenario IDs into matrix |

If scope omitted, default to **`current diff`** for the active task.

## Phases (summary)

| Phase | Action |
|-------|--------|
| **0** | Scope lock — git diff or explicit target; OpenSpec VERIFY if slug |
| **1** | Surface inventory — forms, services, routes, JS, roles |
| **2** | Matrix build — factors, combinatorial policy (≤32 full, >32 pairwise) |
| **3** | Execute rows — real commands; record PASS/FAIL/BLOCKED/NOT VERIFIABLE |
| **4** | Regression — lint, tests, cache/config sync per stack rule, console (VR-15) |
| **5** | Close — matrix file + `## Verification` locked to row outcomes |

Full detail: `.cursor/skills/comando-verificar/SKILL.md`.

## Matrix artifact

Path: `.cursor/context/verification/<scope-slug>/matrix.md`

Columns: `row_id` | Factors | Layer | destructive | Command/tool | Expected | Actual | Verdict

HTML twin when **>8** data rows: `matrix.html` per `documents-md-and-html.mdc`.

## Related commands

| Command | Role |
|---------|------|
| **`/verifica-cierra`** | Minimum close gate only — use **after** matrix or when scope is trivial |
| **`/verifica-tarea <slug>`** | OpenSpec change PASS/FAIL vs `VERIFY.md` — no combinatorial matrix |
| **`/gaps-spec <slug>`** | Pre-apply spec gaps → `GAPS.md` — no runtime execution |
| **`/ejecuta-tests-reporte`** | Project test battery + honest report — complements Phase 4 |
| **`/supervisa-cobertura`** | E2E coverage anti-gaming — not per-task matrix |

## Prohibited

- Claiming “all combinations tested” without matrix file on disk.
- Closing form/AJAX rows with PHPUnit or curl-only proof (VR-09).
- Host-run test binaries when project stack requires in-container execution.
- “Recarga y comprueba” (VR-07).
- Weakening E2E tests to green matrix rows.

## Related rules

- `.cursor/rules/00-verification-gate.mdc` (L1 — never weakened)
- `.cursor/rules/comando-verificar-a-fondo.mdc` (L2)
- `.cursor/rules/ai-verify-result-before-response.mdc` (VR-09…15)
- `.cursor/rules/auth-credential-failure-no-retry.mdc`
- `.cursor/rules/00-openspec-stack-agnostic.mdc`
