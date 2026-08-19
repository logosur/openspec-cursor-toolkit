---
description: "OpenSpec change verification — 100% scenario matrix, honest evidence, NL summary (extends 00-verification-gate)"
argument-hint: "[slug]"
---

# Verifica tarea (OpenSpec)

When the developer invokes **`/verifica-tarea [<slug>]`**, **`verifica la tarea`**, **`verify openspec change`**, or **`verificación honesta openspec`**, run **OpenSpec change compliance verification** before claiming the change is fully verified.

**Does not replace** L1 `00-verification-gate.mdc`. **Extends** it with a **100% scenario matrix** for the resolved `openspec/changes/<slug>/`.

## Mandatory (this turn)

1. Read **`.claude/skills/verifica-tarea/SKILL.md`** in the same turn before executing.
2. Load **`.claude/skills/verifica-tarea/SKILL.md`** (L2).
3. Execute Phase 0–5 from the skill; write matrix at `openspec-<slug>/`.
4. Close in order: **`## Verification`** → **`## Qué se ha verificado`** → **`## Resumen`** (VR-14).

## Slug resolution (REQ-VT-SLUG-01)

**`<slug>` is optional** in the command token. Resolve target slug in order:

1. **Command token** — first kebab-case token after `verifica-tarea` when `openspec/changes/<slug>/` exists → `slug_source: command-token`
2. **Prompt context** — same message names the change (slug in backticks, path, or «verifica el change X», «esta tarea») → exactly one folder match → `slug_source: prompt-context`
3. **Conversation context** — same turn already scoped one slug (`/aplica-tarea foo`, `/mejora-tarea foo`, attached path) → `slug_source: conversation-context`
4. **Ambiguous or zero** → ask once, list `openspec/changes/*` candidates, stop

Examples:

```
/verifica-tarea boton-cancelar
/verifica-tarea verifica el change verifica-tarea que acabamos de aplicar
/verifica-tarea comprueba esta tarea
```

## Phases (summary)

| Phase | Action |
|-------|--------|
| **0** | Slug resolve + lock; read target artefacts; `openspec status` + `openspec validate`; host scope (local dev default) |
| **1** | Inventory — every REQ + `#### Scenario:`; assign `SC-<slug>-NN`; classify form/service/UI/config/infra/doc-only |
| **2** | Matrix build — ≥1 row per scenario + VERIFY.md gates; `slug_source` in header; combinatorial expansion for form/service |
| **3** | Execute rows — real commands; FACT evidence only; stable `row_id` on re-run |
| **4** | Regression — tasks.md cross-check, lint, project tests, cache/config per stack rule, E2E gate when UI |
| **5** | Close — matrix + trace table + Verification + **Qué se ha verificado** + Resumen |

Full detail: `.claude/skills/verifica-tarea/SKILL.md`.

## Close format (REQ-VT-NL-REPORT-01)

| Section | Purpose |
|---------|---------|
| `## Verification` | Technical — commands, M/N, row_ids, FACT lines |
| `## Qué se ha verificado` | **At-a-glance** — 5–12 plain-language bullets (what was checked, gaps, product vs meta) |
| `## Resumen` | VR-14 compressed recap |

## Matrix artifact

Path: **`.claude/context/verification/openspec-<slug>/matrix.md`**

Header includes: timestamp, slug, **`slug_source`**, commit/branch, `strategy:`, coverage `M/N`.

HTML twin when **>8** data rows: `matrix.html` per `documents-md-and-html.mdc`.

## Related commands

| Command | Role |
|---------|------|
| **`/verifica-tarea [<slug>]`** | **OpenSpec change** — 100% scenario matrix + VERIFY gates + honest evidence + NL summary |
| **`/comando-verificar`** | **Diff-scoped** combinatorial verification for current implementation scope |
| **`/verifica-cierra`** | Minimum close gate only — use after matrix or when scope is trivial |
| **`/gaps-spec <slug>`** | Pre-apply spec gaps → `GAPS.md` — no runtime execution |
| **`/aplica-tarea <slug>`** | Implement pending tasks — separate turn unless explicitly requested |

## Prohibited

- Claiming OpenSpec PASS without matrix file on disk and N/N scenario rows addressed.
- Closing form/UI scenario rows with PHPUnit or curl-only proof (VR-09).
- Skipping validation-error combinatorial rows when the scenario requires them.
- Host-run tests outside project-documented runtime when in-container execution is required.
- «Debería funcionar», «the code looks correct», «tests cover this», «grep shows the handler exists» without runtime evidence.
- «Recarga y comprueba» (VR-07).
- Weakening E2E tests to green matrix rows.
- Verifying PRO/QA hosts without explicit scope in the user message (REQ-VT-SCOPE-HOST-01).
- Forcing slug re-type when prompt already identifies the target unambiguously.

## Related rules

- `.cursor/rules/00-verification-gate.mdc` (L1 — never weakened)
- `.claude/skills/verifica-tarea/SKILL.md` (L2)
- `.claude/skills/comando-verificar/SKILL.md` (L2 — diff-scoped cousin)
- `.cursor/rules/ai-verify-result-before-response.mdc` (VR-09…15)
- `.cursor/rules/auth-credential-failure-no-retry.mdc`
- `.claude/skills/00-openspec-stack-agnostic/SKILL.md`
