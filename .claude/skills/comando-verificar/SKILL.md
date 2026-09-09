---
name: comando-verificar
description: Deep combinatorial verification with matrix artifact — forms, services, casuistics. Auto-invoke on /comando-verificar, verifica a fondo, verify thoroughly, matriz de verificación, prueba todas las combinaciones.
---

# Comando verificar — deep verification skill

> **Command:** `.claude/commands/comando-verificar.md`  
> **Rule (L2):** `.claude/skills/comando-verificar/SKILL.md`  
> **OpenSpec:** `openspec/specs/comando-verificar/spec.md`

When `/comando-verificar` runs, **read this skill in the same turn** and execute Phases 0–5. Complements (does not replace) `/verifica-cierra`, `/verifica-tarea`, `/gaps-spec`.

---

## Preconditions

- Local stack running for tests/CLI when rows need runtime — resolve from target project stack rule (`.claude/skills/00-openspec-stack-agnostic/SKILL.md`); do not assume DDEV.
- For UI rows: resolve base URL from project docs — never hardcode ports (REQ-CV-URL-01).
- For multi-role rows: use the **project E2E auth helper** once when documented; no login retries (REQ-CV-AUTH-01, `auth-credential-failure-no-retry.mdc`).
- Browser rows: **Browser DevTools MCP** per `browser-devtools-use.mdc` when using MCP; project E2E runner (Playwright/Cypress) when running specs.

---

## Phase 0 — Scope lock

Parse scope from lines after the command:

| Input | Action |
|-------|--------|
| **`current diff`** (or omitted) | Run `git diff HEAD --name-only`; record command + paths in matrix header (REQ-CV-SCOPE-01) |
| Route | e.g. `/admin/...` — inventory forms, blocks, libraries on route |
| `form_id` | Form identifier — combinatorial field factors (Drupal `form_id`, Symfony form type, React form name, etc.) |
| Module | e.g. `my_module` — routes, forms, services, tests |
| Service class | Public methods + edge preconditions |
| OpenSpec slug | Read `openspec/changes/<slug>/VERIFY.md`; merge scenario IDs into matrix rows (REQ-CV-CMD-02) |

Derive **`<scope-slug>`** (kebab-case): e.g. `checkout-guard-smoke`, `comando-verificar-apply`.

If config/schema files appear in diff (framework-specific: YAML export, migrations, env templates) → note **REQ-CV-EXEC-05** (run project config import/migrate) before dependent UI rows.

---

## Phase 1 — Surface inventory

Document in matrix header or appendix:

**Forms:** form identifier, fields, options, conditional visibility, async/partial updates, validators, multistep pages — map to the project's form stack (Drupal Form API, Symfony Form, React Hook Form, etc.).

**Services:** class, public methods, branches, config flags, entity preconditions.

**UI:** touched assets (`*.libraries.yml`, `*.js`, Twig/templates), exact URL from describe.

**Roles:** from project QA role registry when access varies.

**Form event map:** update `.claude/context/testing/form-event-map.md` when form scope is non-trivial (REQ-CV-MATRIX-04).

---

## Phase 2 — Matrix build

### Factor enumeration

List discrete factors F1…Fn with values. Compute cartesian size |F1|×…×|Fn|.

### Combinatorial policy (REQ-CV-LIMIT-01)

| Size | Strategy |
|------|----------|
| ≤ 32 | Full cartesian — one row per combination |
| 33–256 | Pairwise covering + single-factor edge rows; list **UNCOVERED** in header |
| > 256 | Equivalence classes + pairwise on representatives |

**Mandatory rows:** happy path, at least one validation error, permission denied (if route is access-controlled).

**Trivial scope** (CSS/copy only): set header `strategy: trivial`; minimum 3 rows (lint, render/HTTP, regression).

### Row types (REQ-CV-MATRIX-04…07)

| Type | When |
|------|------|
| **multistep** | Wizard — Next/Back per step |
| **partial-ajax-rebuild** | After `#ajax` / fetch partial — assert DOM + console clean |
| **side-effect** | Post-submit queue/cron/mail (Layer B) |
| **permission_negative** | Role without permission → 403/login, not WSOD |
| **multi-role** | One row per affected role from registry |

### Destructive flag (REQ-CV-MATRIX-09)

Mark `destructive: true` for cancel, delete, irreversible workflow. Default verdict **`BLOCKED (destructive)`** unless scope explicitly authorizes + disposable local environment. See `unsafe-interactive-click-sweep` skill — no blind sweep.

### Matrix template

Path: **`.claude/context/verification/<scope-slug>/matrix.md`**

```markdown
# Verification matrix — <scope-slug>

> Generated: YYYY-MM-DD HH:MM TZ
> Scope: …
> Git diff: `git diff HEAD --name-only` → [paths]
> Strategy: full-cartesian | pairwise | trivial
> UNCOVERED: (if pairwise)

| row_id | Factors | Layer | destructive | Command / tool | Expected | Actual | Verdict |
|--------|---------|-------|-------------|----------------|----------|--------|---------|
| R-01 | … | unit | false | `<project test command>` | exit 0 | … | PASS |
```

**Stable `row_id`:** `R-01`…`R-NN` — same id on FAIL→fix→re-run (REQ-CV-MATRIX-08).

**HTML twin:** when **>8** data rows, also write `matrix.html` (`documents-md-and-html.mdc`).

Subfolder **`verification/`** lives under `.claude/context/` per `ai-helper-files.mdc`.

---

## Phase 3 — Execute rows

Per row:

1. Pick layer: E2E form, interactive, unit, HTTP, config/DI.
2. Run real command — record stdout, HTTP status, or browser outcome in **Actual**.
3. Set **Verdict:** PASS | FAIL | BLOCKED | NOT VERIFIABLE.
4. On FAIL: fix allowed in session; re-run **same row_id** on final tree (VR-10).

**Form rows:** browser/form path required (VR-09) — Playwright fill→submit or Browser DevTools MCP — not PHPUnit alone.

**Interactive rows:** click → observable outcome (VR-13).

**Auth rows:** one attempt; flood → `BLOCKED (credentials)`.

Never cite pre-edit green tests after code changed (VR-10).

---

## Phase 4 — Regression sweep

After matrix rows (or in parallel for infra-only scope):

| Check | When |
|-------|------|
| Cache / rebuild | When bootstrap, DI, routing, or assets changed (per project stack rule) |
| Config / schema import | When config/migration paths in diff (REQ-CV-EXEC-05) |
| Lint | Project linter on touched code |
| Tests | Narrowest project test command for touched packages |
| JS syntax | Project JS check on each touched asset |
| Console clean (VR-15) | UI scope — exact resolved base URL |
| E2E multilayer gate | When project documents gates (REQ-CV-EXEC-06) |

**Never weaken E2E** to green matrix (REQ-CV-EXEC-07).

**Phase 1 QA waiver:** when project QA phase-1 applies, use Browser DevTools MCP instead of Playwright if Playwright not run — document in matrix (REQ-CV-EXEC-08).

Optional: sync project E2E coverage map when inventory aligns (REQ-CV-E2E-01).

---

## Phase 5 — Close

1. Save matrix (and HTML twin if >8 rows).
2. Write **`## Verification`** (REQ-CV-EXEC-03):
   - **Verified:** matrix path + `N/M PASS` mandatory rows.
   - **Verified (E2E/form)** / **Verified (interactive)** / **Verified (JS)** as applicable.
   - **Not verified:** BLOCKED / NOT VERIFIABLE with `row_id` cited.
3. **Resumen** — VR-14; no “listo” if FAIL or >20% NOT RUN without waiver.

Embed minimum close-gate semantics (`/verifica-cierra` or `00-verification-gate.mdc`) in the final block.

---

## Project stack commands (resolve from target repo)

| Purpose | Resolve from project stack rule |
|---------|----------------------------------|
| Base URL | Compose, `.env`, documented smoke URL |
| Auth | Project E2E auth helper when documented |
| Cache / rebuild | Framework-specific when applicable |
| Config / schema | Import/migrate when config in diff |
| Tests | PHPUnit / Jest / pytest / Make target |
| Lint | Project linter |
| JS syntax | Project JS check command |
| OpenSpec | `openspec validate <slug>` |

---

## Anti-patterns (REQ-CV-EXEC-04) — forbidden

1. **Matrix on paper only** — no commands run (VR-09).
2. **Skip validation-error rows** — “happy path passed” is insufficient.
3. **Host-run test binaries** outside project-documented runtime when in-container execution is required (VR-09).
4. **curl HTML grep for AJAX/button fixes** — need interactive or E2E (VR-13).
5. **“Recarga y comprueba”** — agent runs checks (VR-07).
6. **Pre-edit test evidence** after code changed (VR-10).
7. **Resumen “listo”** with FAIL rows or >20% NOT RUN (VR-14).
8. **Weakening E2E** to green matrix.
9. **Login retry loops** on flood (`auth-credential-failure-no-retry.mdc`).
10. **Hardcoded ports** in evidence URLs — use project URL resolution (REQ-CV-URL-01).

---

## Example: service matrix (illustrative)

`ScheduleGuard` (grep actual API at apply time):

| row_id | Factors | Layer | Expected |
|--------|---------|-------|----------|
| R-01 | active shift | unit | allow |
| R-02 | no shift | unit | block |
| R-03 | stale flag | unit | reconciled |

Run: project test command for the owning module/package.

---

## Example: form matrix (3 binary → 8 rows)

Factors: `field_a` × `field_b` × `field_c` (three binary inputs).

Each row: MCP or Playwright fill→submit; verdict from UI state.

---

## Integration with other commands

| After deep verify | Use |
|-------------------|-----|
| Minimum gate only next time | `/verifica-cierra` |
| OpenSpec compliance report | `/verifica-tarea <slug>` |
| Pre-apply spec gaps | `/gaps-spec <slug>` |
| Full test battery | `/ejecuta-tests-reporte` |

Matriz per-task: `.claude/context/verification/` — **not** the same as multi-role HTML QA reports.

---

## VR reference (must cite in close)

- **VR-09** — form/browser path, not PHPUnit-only for forms
- **VR-10** — re-verify after last edit
- **VR-11** — same route/host/port as developer
- **VR-12** — evidence in Verification block
- **VR-13** — interactive for AJAX/buttons
- **VR-14** — Resumen locked to Verified
- **VR-15** — console clean on UI routes

See `ai-verify-result-before-response.mdc` or `00-verification-gate.mdc` for full list.
