---
name: qa
description: Honest QA HTML report with mobile-first then desktop screenshots, combinatorial matrix, overlay-free captures, natural language. Auto-invoke on /qa, informe qa, reporte qa honesto, dame un reporte QA, qa con capturas.
---

# Comando QA — informe honesto con evidencia visual

> **Command:** `.cursor/commands/qa.md`  
> **Rule (L2):** `.cursor/rules/comando-qa.mdc`  
> **Template:** `qa-report-template-non-technical.mdc`

When `/qa` runs, **read this skill in the same turn** and execute Phases 0–6. Delivers a stakeholder HTML report with verified screenshots (mobile first, desktop second) and a combinatorial matrix — **no hallucinations**.

---

## Preconditions

- Local stack running — resolve from target project stack rule (`00-openspec-stack-agnostic.mdc`).
- Base URL from project docs — never hardcode ports (REQ-QA-URL-01).
- Browser DevTools MCP for UI rows (`browser-devtools-use.mdc`).
- Auth: project E2E helper once per role; no login retries (`auth-credential-failure-no-retry.mdc`).
- Run **without questions** — deliver partial report with BLOCKED sections instead of stopping (`qa-report-template-non-technical.mdc` §0).

---

## Phase 0 — Scope lock

Parse scope from lines after the command:

| Input | Action |
|-------|--------|
| **`current diff`** (default) | `git diff HEAD --name-only`; record paths in matrix header |
| Route | Inventory forms, blocks, libraries on route |
| Module | Routes, forms, services, permissions |
| Role | Load `qa-local-roles-registry.mdc`; bound matrix to role surfaces |
| OpenSpec slug | Read `openspec/changes/<slug>/VERIFY.md`; merge scenario IDs |
| Title / ticket | Report `<h1>` + `<run-slug>` (kebab-case) |

Derive **`<run-slug>`**: e.g. `rider-jornada-toggle`, `cierre-pedido-qa`.

Create run folder:

```text
.cursor/QAtest/<run-slug>/
.cursor/QAtest/<run-slug>/capturas/
```

If config/schema files in diff → run project config import/migrate + cache rebuild before UI rows (per stack rule).

---

## Phase 1 — Surface inventory

Document in matrix header:

**Forms:** `form_id`, fields, `#options`, `#states`, `#ajax`, validators, multistep pages.

**Factors (F1…Fn):** every discrete input that changes output — booleans, enums, roles, preconditions, toggles, permission states.

**UI:** touched assets, exact URLs from describe.

**Roles:** from `qa-local-roles-registry.mdc` when access varies.

**Form event map:** update `.cursor/context/testing/form-event-map.md` when form scope is non-trivial.

---

## Phase 2 — Combinatorial matrix

Path: **`.cursor/QAtest/<run-slug>/matrix.md`**

### Factor enumeration

List F1…Fn with values. Compute cartesian size |F1|×…×|Fn|.

### Combinatorial policy (REQ-QA-LIMIT-01)

| Size | Strategy |
|------|----------|
| ≤ 32 | Full cartesian — one row per combination |
| 33–256 | Pairwise covering + single-factor edge rows; list **UNCOVERED** in header |
| > 256 | Equivalence classes + pairwise on representatives |

**Mandatory rows:** happy path, validation error, permission denied (if access-controlled), empty/null edge where applicable.

**Trivial scope** (CSS/copy only): `strategy: trivial`; minimum 3 rows (render mobile+desktop, lint, regression).

### Matrix columns

| row_id | Factors | Role | Layer | Command / tool | Expected | Actual | Verdict | mobile_png | desktop_png |
|--------|---------|------|-------|----------------|----------|--------|---------|------------|-------------|

Stable **`row_id`:** `R-01`…`R-NN`.

---

## Phase 3 — Execute rows (browser evidence)

Per matrix row:

1. **Authenticate** as required role (storage-state reuse when documented).
2. **Navigate** to exact URL (project base URL + path).
3. **Prepare page** (Phase 4 hygiene) before any capture.
4. **Mobile capture first** — viewport **390×844** (or project mobile default).
5. **Desktop capture second** — viewport **1280×720**.
6. Record observable outcome in **Actual**; set **Verdict:** PASS | FAIL | BLOCKED | NOT VERIFIABLE.

### Capture naming

```text
capturas/R-01-mobile.png
capturas/R-01-desktop.png
```

### Row types

| Type | Minimum |
|------|---------|
| Form combo | Fill → submit via browser; assert UI outcome |
| AJAX / button | Click → DOM/message change (VR-13) |
| Permission negative | 403/login — capture denial state |
| Multistep | One mobile+desktop pair per critical step |

**Never** cite pre-edit evidence after code changed (VR-10).

---

## Phase 4 — Screenshot hygiene (mandatory)

Before saving each PNG, verify the frame is **clean and readable**. If obstructed → fix and **re-capture** (do not attach bad evidence).

### Pre-capture checklist

| Obstruction | Action |
|-------------|--------|
| Cookie / GDPR banner | Accept, dismiss, or use documented local bypass |
| Modal / dialog | Close or complete required action |
| Admin toolbar overlay | Collapse or scroll subject into clear view |
| Debug FAB / floating widgets | Hide or move per project convention |
| Toast / snackbar blocking subject | Wait to dismiss or dismiss explicitly |
| Sticky header covering CTA | Scroll until target control is fully visible |
| Loading spinner | Wait for framework init / network settle |

### Post-capture validation (agent inspects PNG)

- Subject under test is **visible at a glance** — not cropped away, not hidden behind overlay.
- Text readable without zoom (PO must understand what was checked).
- If validation fails → repeat Phase 4 + re-capture; mark previous file `_rejected` or overwrite.

### Console gate (VR-15)

On UI routes: **0** Uncaught / SyntaxError / TypeError attributable to the change. Log in matrix **Actual** if errors present → FAIL unless out of scope.

---

## Phase 5 — HTML + MD report

Primary files:

```text
.cursor/QAtest/<run-slug>/qa-report-<run-slug>.html
.cursor/QAtest/<run-slug>/qa-report-<run-slug>.md
```

Use timestamp from `tests/e2e/scripts/lib/report-timestamp.mjs` semantics (`qa-reports-timestamp-mandatory.mdc`):

```html
<p class="meta">Generado: <time datetime="…">YYYY-MM-DD HH:MM:SS Europe/Madrid</time></p>
```

### Report structure (mandatory)

1. **`<h1>` Title** — scope in plain language (Spanish for stakeholders).
2. **Intro paragraph** — what we are checking, why it matters for the business, environment (local URL, branch, commit short).
3. **Timestamp** — visible with seconds + timezone.
4. **Executive summary** — pass/fail/mixed counts; top risks in natural language.
5. **Scope** — in scope / out of scope / not tested.
6. **Per-row evidence blocks** — for each `row_id`:
   - Factors in plain language (not only codes).
   - Expected vs actual narrative.
   - Verdict badge (PASS/FAIL/BLOCKED).
   - **Mobile figure first** (`<figure>` + `<figcaption>` natural language — what the image proves).
   - **Desktop figure second** (same structure).
   - Images clickable full-size (`<a href="capturas/…" target="_blank"><img …></a>`).
   - Max **2 images per visual row** (mobile | desktop side by side OK per `qa-report-template-non-technical.mdc` §9.1).
7. **Coverage matrix** — roles × areas when multi-surface.
8. **Findings table** — FAIL/BLOCKED rows with severity (S1–S4 plain language).
9. **Combinatorics annex** — link to `matrix.md`; list UNCOVERED if pairwise.

### Anti-hallucination rules (REQ-QA-HONEST-01)

- **Verdict in report = verdict in matrix** — same `row_id`, same PASS/FAIL/BLOCKED.
- **No screenshot without a captured file on disk** — verify `test -f capturas/R-NN-mobile.png`.
- **No PASS without Actual evidence** — HTTP status, DOM state, or test exit code recorded.
- **Not tested / BLOCKED** instead of inventing coverage.
- Narrative describes **what was observed**, not what “should” happen without proof.

### HTML styling minimum

- Semantic HTML5, inline `<style>` for `file://`.
- Readable typography; section cards; verdict color badges.
- Language: **Spanish** for stakeholder prose (`reports-audits-spanish.mdc`).

---

## Phase 6 — Open in Chrome

Agent runs (same turn):

```bash
bash .cursor/scripts/open-html-in-chrome.sh \
  "$(git rev-parse --show-toplevel)/.cursor/QAtest/<run-slug>/qa-report-<run-slug>.html"
```

Fallbacks per `open-links-in-chrome-not-ide.mdc`: `google-chrome`, `chromium-browser`, `xdg-open`.

**Prohibited:** IDE browser as substitute for developer viewing.

No display → **Not verified:** headless; cite absolute `file://` path.

---

## Phase 7 — Close

1. Save matrix + HTML + MD.
2. Write **`## Verification`**:
   - **Verified:** report path + `N/M PASS` matrix rows + Chrome open command exit code.
   - **Verified (interactive):** row_ids with browser proof.
   - **Verified (JS):** routes with console clean (VR-15).
   - **Not verified:** BLOCKED rows with concrete blockers.
3. **Resumen** — VR-14; no “listo” if FAIL or hallucination risk (missing PNGs, unchecked overlays).

---

## Viewport reference

| Pass | Viewport | Order in report |
|------|----------|-----------------|
| Mobile | 390×844 | **First** |
| Desktop | 1280×720 | **Second** |

Embedded images: respect minimum **768×588** for desktop; mobile may be narrower but must be **legible** and paired with desktop (`qa-report-template-non-technical.mdc` §9).

---

## Project stack commands (resolve from target repo)

| Purpose | Resolve from project stack rule |
|---------|----------------------------------|
| Base URL | Compose, `.env`, smoke script |
| Branch / commit | `git rev-parse --abbrev-ref HEAD` / `--short HEAD` |
| Cache / rebuild | When applicable per stack |
| Config / schema | Import when config in diff |
| Lint | Project linter |
| Tests | Narrowest project test target |
| Open report | `bash .cursor/scripts/open-html-in-chrome.sh <path>` |

---

## Anti-patterns — forbidden

1. **Report without matrix** — combinatorics not documented.
2. **Matrix on paper only** — no browser/commands run.
3. **Desktop-only** when mobile UI exists.
4. **Cookie banner in evidence** — lazy capture accepted as PASS.
5. **Detached screenshot gallery** — images must be inline at the step (`qa-local-natural-language-inline-evidence.mdc`).
6. **Hallucinated PASS** — verdict without Actual column filled.
7. **Skip validation-error combinations** — happy path alone is insufficient.
8. **Pre-edit green tests** after code changed (VR-10).
9. **Close without Chrome** when display available.
10. **Login retry loops** on flood.

---

## Integration

| Related | When |
|---------|------|
| `/comando-verificar` | Technical matrix only — no HTML stakeholder report |
| `/verifica-tarea` | OpenSpec compliance + matrix under `.cursor/context/verification/` |
| `/html` | Re-open report later |
| `qa-local-orchestration-commands.mdc` | Full multi-role suite (L2/L3) — `/qa` is per-scope deep report |
| `browser-product-qa-through-ui` | Form-only persistence policy |

---

## VR reference

- **VR-09** — form/browser path for form rows
- **VR-10** — re-verify after last edit
- **VR-11** — same route/host/port as developer
- **VR-13** — interactive for AJAX/buttons
- **VR-14** — Resumen locked to Verified
- **VR-15** — console clean on UI routes
