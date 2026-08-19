---
description: "Informe QA honesto con capturas mobile→desktop, matriz combinatoria completa, evidencia verificada y apertura en Chrome"
---

# Comando QA — informe honesto con evidencia visual

When the developer invokes **`/qa`**, **`comando qa`**, **`informe qa`**, **`reporte qa honesto`**, **`dame un reporte QA`**, or **`qa con capturas`**, run the **full honest QA report workflow** before claiming completion.

**Combines:** combinatorial coverage (`/comando-verificar`), stakeholder HTML report (`qa-report-template-non-technical.mdc`), visual evidence hygiene, and Chrome open.

**Does not replace** L1 `00-verification-gate.mdc`. **Extends** it with a visual HTML deliverable + matrix executed first.

## Mandatory (this turn)

1. Read **`.claude/skills/qa/SKILL.md`** in the same turn before executing.
2. Load **`.claude/skills/qa/SKILL.md`** (L2).
3. Execute Phases 0–6 from the skill; write HTML + MD report; open Chrome; close with `## Verification` + Resumen (VR-14).

## Scope parsing

Optional scope on following lines (one or more):

| Scope token | Example | Phase 0 action |
|-------------|---------|----------------|
| `current diff` | `/qa` + `current diff` | `git diff HEAD --name-only` → bound inventory |
| Route | `/qa /rider` | QA that route + dependents |
| Module | `/qa rider_schedule` | Module surfaces + combinatorial rows |
| Role | `/qa rider` | Auth as role from registry; role-scoped matrix |
| OpenSpec slug | `/qa cierre-pedido` | Merge `VERIFY.md` scenarios into matrix |
| Ticket / title | `/qa SWT4348 toggle jornada` | Use as report title + scope slug |

If scope omitted, default to **`current diff`** for the active task.

## Phases (summary)

| Phase | Action |
|-------|--------|
| **0** | Scope lock — git diff or explicit target; derive `<run-slug>` |
| **1** | Surface inventory — forms, factors, roles, routes, JS |
| **2** | Combinatorial matrix — all input combinations (policy REQ-QA-LIMIT-01) |
| **3** | Execute rows — browser MCP; **mobile capture first**, then desktop per row |
| **4** | Screenshot hygiene — dismiss overlays; reject/re-capture if obstructed |
| **5** | HTML + MD report — title, intro, timestamp, inline evidence (mobile→desktop) |
| **6** | Open Chrome — `open-html-in-chrome.sh` on primary `qa-report-*.html` |

Full detail: `.claude/skills/qa/SKILL.md`.

## Report artifact

Primary output:

```text
.claude/QAtest/<run-slug>/qa-report-<run-slug>.html
.claude/QAtest/<run-slug>/qa-report-<run-slug>.md
.claude/QAtest/<run-slug>/capturas/
```

Supporting matrix (always):

```text
.claude/QAtest/<run-slug>/matrix.md
```

## Related commands

| Command | Role |
|---------|------|
| **`/comando-verificar`** | Technical verification matrix only — no stakeholder HTML |
| **`/verifica-tarea <slug>`** | OpenSpec 100% scenario compliance |
| **`/html`** | Re-open an existing report in Chrome later |
| **`/verifica-cierra`** | Minimum close gate when QA report not needed |

## Prohibited

- Claiming “100% tested” without matrix + HTML on disk.
- Screenshots with cookie banners, modals, or debug overlays obscuring the subject.
- Hallucinated PASS rows — every verdict needs command/browser evidence in **Actual**.
- Desktop-only report when mobile applies.
- Closing without opening Chrome (`qa-reports-open-chrome.mdc`).
- “Recarga y comprueba” (VR-07).

## Related rules

- `.claude/skills/qa/SKILL.md` (L2)
- `.cursor/rules/qa-report-template-non-technical.mdc`
- `.cursor/rules/qa-local-natural-language-inline-evidence.mdc`
- `.cursor/rules/qa-reports-timestamp-mandatory.mdc`
- `.cursor/rules/qa-reports-open-chrome.mdc`
- `.cursor/rules/00-verification-gate.mdc` (L1)
