---
name: verifica-tarea
description: OpenSpec change verification — 100% scenario matrix, VERIFY gates, honest evidence. Auto-invoke on /verifica-tarea, verifica la tarea, verify openspec change, verificación honesta openspec, comprueba el change.
---

# Verifica tarea — OpenSpec verification skill

> **Command:** `.claude/commands/verifica-tarea.md`  
> **Rule (L2):** `.claude/skills/verifica-tarea/SKILL.md`  
> **OpenSpec:** `openspec/changes/<slug>/specs/**/spec.md`

When `/verifica-tarea [<slug>]` runs, **read this skill in the same turn** and execute Phases 0–5. Complements (does not replace) `/comando-verificar`, `/verifica-cierra`, `/gaps-spec`.


## Preconditions

- **`<slug>` optional** — resolve per REQ-VT-SLUG-01 (command token → prompt → conversation context).
- **Local stack** running for tests/CLI when rows need runtime — resolve commands from the target project's stack rule (`.claude/skills/00-openspec-stack-agnostic/SKILL.md`); do not assume DDEV/Drupal.
- **Host scope:** default **local dev** documented for the project; no PRO/staging unless user explicitly scopes host in the same message (REQ-VT-SCOPE-HOST-01).
- UI rows: base URL from project docs (Compose, `.env`, documented smoke script) — never hardcode host/port from another repo (REQ-VT-URL-01).
- Auth: use the **project E2E auth helper** when documented; one attempt per user; flood → `BLOCKED (credentials)` (`auth-credential-failure-no-retry.mdc`).


## Phase 0 — Slug resolve + lock + artefact read (REQ-VT-PHASE0-01, SLUG-01)

### Slug resolution

1. **Command token:** first kebab-case token after `verifica-tarea` if `openspec/changes/<slug>/` exists → record `slug_source: command-token`.
2. **Prompt context (same message):** explicit slug (backticks, `openspec/changes/<slug>/`), or natural reference («verifica el change X», «esta tarea», «lo que acabamos de aplicar») mapping to **exactly one** folder → `slug_source: prompt-context`.
3. **Conversation context (same turn):** prior `/aplica-tarea <slug>`, `/mejora-tarea <slug>`, or attached OpenSpec path — use when **one** slug matches → `slug_source: conversation-context`.
4. **Zero or multiple candidates:** ask once, list `openspec/changes/*` folder names, stop — do not guess.

Do **not** force slug re-type when the prompt already identifies the target unambiguously.

### After slug lock

1. Read when present under `openspec/changes/<slug>/`:
   - `proposal.md`, `design.md`, `tasks.md`, `VERIFY.md`, `GAPS.md`, `READY-TO-APPLY.md`, `specs/**/spec.md`
3. Run readonly gates; record in matrix header / Phase 0 notes:

```bash
openspec status --change "<slug>" --json
openspec validate "<slug>"
```

4. Document host scope: `local dev` (default, per project stack rule) or explicit `staging` / `production` if user named it.
5. If `VERIFY.md` absent → header note `VERIFY: absent — spec scenarios only`.


## Phase 1 — Requirement & scenario inventory (REQ-VT-PHASE1-01)

1. Parse every `### Requirement` and `#### Scenario:` in target `specs/**/spec.md`.
2. Assign stable ids:
   - **`scenario_id`:** `SC-<slug>-NN` (maps to exact scenario title)
   - **`req_id`:** from target spec (e.g. `REQ-…-NN`)
3. Classify each scenario: **`form` | `service` | `UI` | `config` | `infra` | `doc-only`**
4. If VERIFY.md exists → list gates G1, G2, … for Phase 2 mapping (REQ-VT-VERIFY-01).
5. **Form event map:** for non-trivial **form** scenarios on product changes, update `.claude/context/testing/form-event-map.md` (REQ-VT-MATRIX-08).
6. **Infra-only target** (all scenarios `infra` or `doc-only`) → plan `strategy: trivial` (REQ-VT-MATRIX-01).


## Phase 2 — Matrix build (REQ-VT-COVER-01, VERIFY-01)

Path: **`.claude/context/verification/openspec-<slug>/matrix.md`**

### Header (REQ-VT-MATRIX-01)

Include:

- Timestamp with timezone (`qa-reports-timestamp-mandatory.mdc`)
- Target slug, **`slug_source`** (`command-token` | `prompt-context` | `conversation-context`)
- Host scope
- Git commit + branch when in repo
- `openspec status` + `openspec validate` outcomes
- **`strategy:`** one of: `full-scenario` | `combinatorial-full` | `pairwise` | `equivalence-classes` | `trivial`
- **Coverage:** `M/N scenarios with executed evidence`
- VERIFY gate mapping table when VERIFY.md exists
- UNCOVERED combinations when pairwise/equivalence

### Row columns

| Column | Notes |
|--------|-------|
| `row_id` | `R-01`… stable on FAIL→fix→re-run (VR-10) |
| `scenario_id` | `SC-<slug>-NN` |
| `req_id` | Target requirement id |
| `row_type` | optional: `multistep`, `partial-ajax-rebuild`, `side-effect`, `permission_negative` |
| `destructive` | boolean — default BLOCKED unless authorized (REQ-VT-MATRIX-04) |
| `evidence_class` | FACT \| INFERENCE \| HYPOTHESIS \| UNKNOWN — PASS only FACT |
| verdict | PASS \| FAIL \| BLOCKED \| NOT VERIFIABLE |

**Minimum rows:**

- ≥1 row per target `#### Scenario:` (COVER-01)
- ≥1 row per VERIFY.md gate when file exists (VERIFY-01)
- Form scenarios → combinatorial expansion (MATRIX-02, LIMIT-01)
- Service scenarios → happy + edge (MATRIX-03)

### Combinatorial policy (REQ-VT-LIMIT-01)

| Combinations | Strategy |
|--------------|----------|
| ≤ 32 | `combinatorial-full` or `full-scenario` — one row per combo |
| 33–256 | `pairwise` + single-factor edge rows; list UNCOVERED |
| > 256 | `equivalence-classes` + pairwise on representatives |

**Mandatory rows:** happy path, validation errors when spec requires, permission denied when applicable.

**Trivial** (infra/CSS-copy-only, no discrete form factors): `strategy: trivial`; ≥3 rows (file presence, validate, lint/regression) — no forced cartesian.

### Row types — same vocabulary as `/comando-verificar` (REQ-VT-MATRIX-05…07, D10)

| `row_type` | When |
|------------|------|
| `multistep` | Wizard — Next/Back per step before final assert |
| `partial-ajax-rebuild` | After `#ajax` — DOM fragment + behaviours + console clean (VR-15) |
| `side-effect` | Post-submit queue/cron/mail (Layer B) |
| `permission_negative` | Role without permission → 403/login, not WSOD |
| `destructive: true` | Cancel/delete — default BLOCKED unless scenario authorizes + disposable local fixtures |

### HTML twin

When **>8** data rows → also write `matrix.html` (`documents-md-and-html.mdc`).


## Phase 3 — Execute rows (REQ-VT-EXEC-01)

Per row:

1. Pick layer: E2E form, interactive, unit, HTTP, config/DI, artefact check.
2. Run real command in **this session after last edit** (VR-10).
3. Record **Actual**; set **Verdict** and **evidence_class**.
4. Form/UI rows → **Verified (E2E/form)** or **Verified (interactive)** (VR-09, VR-13).
5. JS rows → **Verified (JS)** on exact URL — 0 Uncaught (VR-15).

Never PASS from code read, grep, or pre-edit tests alone.


## Phase 4 — Regression sweep (REQ-VT-EXEC-02…06)

| Check | When |
|-------|------|
| `openspec validate <slug>` | Always |
| `tasks.md` cross-check | If apply claimed — unchecked required tasks → overall FAIL |
| Cache / rebuild | When DI, routing, assets, or framework bootstrap changed (per project stack rule) |
| Config / schema sync | When migrations or config trees in diff (per project stack rule) |
| Lint | Project linter on touched paths |
| Tests | Narrowest project test target for affected packages/modules |
| JS / asset syntax check | Each touched front-end asset when applicable |
| Console (VR-15) | UI scenarios on exact resolved base URL |
| E2E multilayer gate | When project documents a gate script (optional) |

**Never weaken E2E** to green matrix (EXEC-05).

**Phase 1 QA waiver:** Browser DevTools MCP instead of Playwright when project phase-1 applies — document in matrix header (EXEC-06).


## Phase 5 — Close (REQ-VT-EXEC-03, NL-REPORT-01, TRACE-01)

1. Save matrix (+ HTML if >8 rows).
2. **Trace table** in chat:

| req_id | scenario_id | row_ids | verdict | evidence_class |

3. **`## Verification`** block (technical):
   - **Verified:** matrix path + `M/N` scenario coverage + PASS count
   - **Verified (E2E/form)** / **Verified (interactive)** / **Verified (JS)** when applicable
   - **Not verified:** FAIL / BLOCKED / NOT VERIFIABLE with `row_id` + `scenario_id`

4. **`## Qué se ha verificado`** (REQ-VT-NL-REPORT-01) — plain language, developer's chat language:

   - **5–12 bullets** typical — at-a-glance, not a matrix dump.
   - State: target slug + how resolved (`slug_source`), coverage M/N, main areas checked.
   - Name honest gaps (NOT VERIFIABLE / BLOCKED / FAIL) in human terms.
   - Distinguish **product business logic** runtime-tested vs **meta/infra/doc-only** when relevant.
   - Do **not** duplicate full trace table or long command logs here.

   Example (meta change):

   ```markdown
   ## Qué se ha verificado

   - Change objetivo: `verifica-tarea` (infra — command, skill, regla L2).
   - Slug resuelto desde: command-token / prompt-context (según el caso).
   - Cobertura: 58/62 escenarios con evidencia; 4 requieren runtime en change de producto.
   - Comando, skill y regla documentan slug opcional y cierre en tres secciones.
   - No se probó cancelación de pedido ni formularios reales — fuera de alcance de este change.
   ```

5. **`## Resumen`** — VR-14; no «listo» unless N/N scenarios addressed with zero FAIL.


## Project stack commands (resolve from target repo)

| Purpose | Resolve from project stack rule |
|---------|----------------------------------|
| Base URL | Compose port, `.env`, `APP_URL`, documented smoke script |
| OpenSpec status | `openspec status --change "<slug>" --json` |
| OpenSpec validate | `openspec validate "<slug>"` |
| Auth | Project E2E helper / fixture users (one attempt per user) |
| Cache / rebuild | Framework-specific when bootstrap/assets changed |
| Config / schema | Import/migrate command when config in diff |
| Tests | Narrowest PHPUnit/Jest/pytest/Make target |
| Lint | Project linter on touched paths |
| JS syntax | Project JS check command when applicable |
| L1 budget | `bash .claude/scripts/count-always-on-rules.sh` when present |
| E2E gate | Project-documented multilayer gate script when present |


## Anti-patterns (REQ-VT-HONEST-02) — forbidden

1. **Matrix on paper only** — no commands run (VR-09).
2. **PHPUnit/curl-only** for form-driven rows (VR-09).
3. **Skip validation-error rows** when scenario requires them.
4. **Host-run test binaries** outside the project-documented container/runtime when the stack rule requires in-container execution.
5. **«Recarga y comprueba»** / «tú verifica» (VR-07).
6. **«Debería funcionar»** / **«the code looks correct»** / **«tests cover this»** / **«grep shows the handler exists»** without executed proof.
7. **Pre-edit test evidence** after code changed (VR-10).
8. **Resumen «listo»** with FAIL rows or omitted scenarios (VR-14).
9. **Weakening E2E** to green matrix (EXEC-05).
10. **Login retry loops** on flood.
11. **Hardcoded host/port** — project URL resolution wins (URL-01).
12. **PRO/QA verification** without explicit user scope (SCOPE-HOST-01).


## Integration table

| Command | When |
|---------|------|
| `/verifica-tarea [<slug>]` | OpenSpec compliance — this skill |
| `/comando-verificar` | Extra diff-scoped depth — optional supplement |
| `/verifica-cierra` | Minimum gate challenge after matrix |
| `/gaps-spec <slug>` | Pre-apply gaps — not runtime |
| `/aplica-tarea <slug>` | Implement — separate turn |


## VR reference

| VR | Application |
|----|-------------|
| VR-09 | Form rows need browser/form path |
| VR-10 | Re-run same `row_id` after fix |
| VR-11 | Layer-appropriate evidence |
| VR-12 | Project-documented runtime for PHP/tests |
| VR-13 | Interactive click → outcome |
| VR-14 | Resumen locked to Verified |
| VR-15 | Console clean on exact URL |


## Example: trivial meta change (verifica-tarea dogfood)

Infra-only OpenSpec change (command/skill/rule):

- Header: `strategy: trivial`
- Rows: file presence (G1), `openspec validate`, L1 count script, skill single YAML check
- VERIFY gates G1–G8 → one row each when VERIFY.md exists
- Product form/UI scenarios in spec → `NOT VERIFIABLE (meta infra — no product surface)` or deferred to post-apply dogfood
