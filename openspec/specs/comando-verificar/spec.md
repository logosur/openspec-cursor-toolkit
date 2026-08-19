# Spec — comando-verificar

Capability: **Deep combinatorial verification** — Cursor command `/comando-verificar`, skill, L2 rule, matrix artifacts under `.cursor/context/verification/`.

## ADDED Requirements

### Requirement: REQ-CV-CMD-01 — Deep verification command and skill exist

The project SHALL provide a Cursor command `/comando-verificar` and a matching skill at `.cursor/skills/comando-verificar/SKILL.md` that implement the phased deep-verification workflow defined in `design.md` (inventory → matrix → execute → regression → close).

The command SHALL accept an optional scope on following lines (route, module name, form_id, service id, OpenSpec slug, or “current diff”). When scope is **current diff**, Phase 0 SHALL follow **REQ-CV-SCOPE-01**.

When the user invokes `/comando-verificar`, the agent SHALL read the skill in the same turn before executing verification.

#### Scenario: Command file is present and parseable

- **GIVEN** the apply phase completed for `comando-verificar`
- **WHEN** a developer opens `.cursor/commands/comando-verificar.md`
- **THEN** the front matter includes `id: comando-verificar` and description mentioning combinatorial / deep verification
- **AND** the body references the skill path `.cursor/skills/comando-verificar/SKILL.md`

#### Scenario: Skill defines all workflow phases

- **GIVEN** the skill file exists
- **WHEN** an agent reads it at command invocation
- **THEN** the skill documents Phase 0 through Phase 5 (scope, inventory, matrix, execute, regression, close)
- **AND** the skill includes project stack command examples (project base URL resolution, project test command, project lint command, project cache rebuild when applicable)
- **AND** the skill references VR-09, VR-10, VR-11, VR-12, VR-13, VR-14, VR-15 from `ai-verify-result-before-response.mdc`

---

### Requirement: REQ-CV-CMD-02 — Command complements existing verify commands

The deep verification command SHALL NOT replace `/verifica-cierra` or `/verifica-tarea`. Documentation in the command and skill SHALL state:

- `/verifica-cierra` — minimum close gate only.
- `/verifica-tarea <slug>` — OpenSpec change verification.
- `/comando-verificar` — combinatorial/casuistic verification for the current implementation scope.

When scope includes an OpenSpec slug, the workflow SHALL read `openspec/changes/<slug>/VERIFY.md` and merge OpenSpec gates into the matrix where applicable.

#### Scenario: Command documents differentiation

- **GIVEN** `.cursor/commands/comando-verificar.md` exists
- **WHEN** a developer reads the “Related commands” section
- **THEN** it lists `verifica-cierra`, `verifica-tarea`, and `gaps-spec` with distinct roles
- **AND** it does not claim to supersede `00-verification-gate.mdc`

#### Scenario: OpenSpec scope merges VERIFY.md

- **GIVEN** the user runs `/comando-verificar botones-activos`
- **WHEN** the agent executes the workflow
- **THEN** the agent reads `openspec/changes/botones-activos/VERIFY.md` if present
- **AND** matrix rows include or reference OpenSpec scenario IDs where they overlap with runtime checks

---

### Requirement: REQ-CV-RULE-01 — L2 rule binds matrix methodology

The project SHALL provide `.cursor/rules/comando-verificar-a-fondo.mdc` with `alwaysApply: false` that:

- Loads when `/comando-verificar` runs or when the user requests deep verification (trigger phrases documented in the rule).
- Requires a verification matrix artifact before overall PASS.
- Extends `00-verification-gate.mdc`; does not weaken L1 requirements.

The rule SHALL be registered in the L2 section of `00-rules-priority-index.mdc` and SHALL NOT be added to L1 always-on list.

#### Scenario: Rule metadata and triggers

- **GIVEN** the rule file exists after apply
- **WHEN** inspecting `.cursor/rules/comando-verificar-a-fondo.mdc` front matter
- **THEN** `alwaysApply` is `false`
- **AND** the description mentions `/comando-verificar` and combinatorial verification
- **AND** trigger phrases include Spanish and English variants

#### Scenario: Index lists rule as L2 only

- **GIVEN** apply updated `00-rules-priority-index.mdc`
- **WHEN** counting L1 always-on rules via `.cursor/scripts/count-always-on-rules.sh` (if available)
- **THEN** `comando-verificar-a-fondo.mdc` is not in the L1 table
- **AND** L1 count remains ≤ 12

---

### Requirement: REQ-CV-MATRIX-01 — Verification matrix artifact

When `/comando-verificar` runs, the agent SHALL produce a matrix artifact at:

`.cursor/context/verification/<scope-slug>/matrix.md`

Each row SHALL include: stable **`row_id`** (e.g. `R-01`, `R-02`, monotonic within the matrix file), factor values, verification layer, command/tool used, expected outcome, observed outcome, and verdict (`PASS` | `FAIL` | `BLOCKED` | `NOT VERIFIABLE`).

The matrix header SHALL include a generation timestamp with timezone per `qa-reports-timestamp-mandatory.mdc` (internal artefact format).

When the matrix has more than **8** data rows, the agent SHALL also produce an HTML twin at `.cursor/context/verification/<scope-slug>/matrix.html` per `documents-md-and-html.mdc`.

#### Scenario: Matrix created for form scope

- **GIVEN** scope targets a form with three binary factors (8 combinations)
- **WHEN** `/comando-verificar` completes successfully
- **THEN** `matrix.md` exists with at least 8 data rows (one per combination) or explicit BLOCKED reasons per row
- **AND** the final chat response includes a matrix summary table or link to the artifact path

#### Scenario: Matrix created for service scope

- **GIVEN** scope targets a service class with enumerated input states in `design.md` D10 style
- **WHEN** `/comando-verificar` completes
- **THEN** each enumerated casuistic appears as at least one matrix row
- **AND** rows cite project test command or runtime evidence — not code reading alone

#### Scenario: Trivial scope uses minimal matrix

- **GIVEN** scope is CSS/copy-only with zero discrete combinatorial factors
- **WHEN** Phase 0 completes
- **THEN** the matrix contains a minimal row set (render/lint or equivalent) — not a forced 32-row cartesian
- **AND** the matrix header documents `strategy: trivial`

---

### Requirement: REQ-CV-MATRIX-02 — Form combinatorial coverage

For form-scoped verification, the agent SHALL enumerate discrete inputs: select/radio/checkbox options, conditional `#states`, required vs optional, and role/access variants that change the form.

The agent SHALL test outcomes through the **browser/form path** (Playwright or Browser DevTools MCP fill→submit) unless the row is explicitly marked backend-only with justification.

#### Scenario: All select options exercised

- **GIVEN** a form field `#type` select with options A, B, C and no other combinatorial factors
- **WHEN** `/comando-verificar` runs on that form
- **THEN** the matrix includes at least three rows covering A, B, and C submit outcomes (or validation messages)
- **AND** **Verified (E2E/form)** appears in the closing `## Verification` block

#### Scenario: Validation error paths included

- **GIVEN** a form with a required field and a business validation in `#validate`
- **WHEN** `/comando-verificar` runs
- **THEN** the matrix includes at least one row with invalid input expecting inline error (not WSOD)
- **AND** the row verdict is PASS only if error message or form error state was observed

---

### Requirement: REQ-CV-MATRIX-03 — Service and business-logic casuistics

For service-scoped verification, the agent SHALL enumerate public method inputs, entity preconditions, configuration flags, and documented edge cases from code or spec — not only the happy path.

Each row SHALL map to the project's unit/integration test command, or a runtime check with observable outcome.

#### Scenario: Happy path plus edge row

- **GIVEN** a service method with branching on entity field values
- **WHEN** `/comando-verificar` targets that service
- **THEN** the matrix includes a happy-path row and at least one edge row (empty, stale, denied, or invalid state)
- **AND** **Verified** lines cite test command exit code 0 or explicit FAIL with output snippet

---

### Requirement: REQ-CV-LIMIT-01 — Combinatorial explosion policy

When the cartesian product of discrete factors exceeds **32**, the agent SHALL use pairwise covering or documented equivalence classes and SHALL list **UNCOVERED** combinations in the matrix header.

The agent SHALL NOT claim full combinatorial coverage without executing all rows in a ≤32 matrix or documenting waivers.

#### Scenario: Small form uses full cartesian

- **GIVEN** 4 binary factors (16 combinations)
- **WHEN** `/comando-verificar` runs
- **THEN** the matrix contains 16 rows (or 16 rows with BLOCKED reason, not omitted)
- **AND** the closing message does not use “all combinations” if any row is NOT RUN without BLOCKED

#### Scenario: Large form uses pairwise with header

- **GIVEN** factors yielding 200 combinations
- **WHEN** `/comando-verificar` runs
- **THEN** `matrix.md` header documents strategy `pairwise` and lists UNCOVERED combos or equivalence classes
- **AND** happy path, each validation error, and permission-denied paths remain mandatory rows

#### Scenario: Medium combinatorial space uses pairwise plus edges

- **GIVEN** factors yielding between **33 and 256** combinations
- **WHEN** `/comando-verificar` runs
- **THEN** the matrix header documents strategy `pairwise` plus **single-factor edge rows**
- **AND** all mandatory paths (happy, validation errors, permission denied) remain explicit rows

#### Scenario: Very large combinatorial space uses equivalence classes

- **GIVEN** factors yielding more than **256** combinations
- **WHEN** `/comando-verificar` runs
- **THEN** the matrix header documents **equivalence classes** and pairwise on class representatives
- **AND** UNCOVERED combinations are listed in the header

---

### Requirement: REQ-CV-AUTH-01 — Matrix authentication and flood policy

When matrix rows require distinct authenticated roles or users, the workflow SHALL follow `auth-credential-failure-no-retry.mdc` and `auth-credential-failure-no-retry.mdc`:

- **One login attempt** per `(target, username)` per chat session — no retry loops.
- Prefer **project E2E auth helper** storage-state reuse over repeated form login.
- **Logout** or fresh storage-state before switching users when the project documents one-time login URLs.
- Mark downstream rows **`BLOCKED (credentials)`** when flood, missing env, or login failure occurs — do not re-run the full matrix.

#### Scenario: Flood blocks remaining login rows

- **GIVEN** a matrix includes rows for roles `rider` and `gerente`
- **AND** login for `gerente` fails with flood or still on `/user/login`
- **WHEN** the agent continues the workflow
- **THEN** all remaining login-dependent rows are marked `BLOCKED (credentials)` with evidence
- **AND** the agent does not submit another login with the same credentials in this session

#### Scenario: MCP session uses project auth helper not blind login retry

- **GIVEN** browser matrix rows require an authenticated session
- **WHEN** Phase 3 executes browser rows
- **THEN** the skill documents using project E2E auth helper once per target
- **AND** the workflow cites `auth-credential-failure-no-retry.mdc` for logout-before-uli when applicable

---

### Requirement: REQ-CV-URL-01 — URL and host resolution for matrix rows

All browser, HTTP, and E2E matrix rows SHALL resolve URLs from **project URL resolution** at execution time — never hardcode host/port from another project.

The workflow SHALL:

- Use the canonical base URL from the target project's stack rule.
- When scope spans multiple apps/subdomains, use the project-documented URL map — not a single default host alone.
- Document **environment port differences** when applicable (worktrees, Compose overrides).
- Apply the same port the developer will use (gate: `00-verification-gate.mdc` — no substitute host/port).

When legacy rules cite `:8443` and describe returns a different HTTPS port, **describe wins** for matrix evidence lines.

#### Scenario: Sub-app route uses correct host from project URL map

- **GIVEN** scope includes a route on a secondary app or subdomain
- **WHEN** matrix rows execute browser checks
- **THEN** **Verified (JS)** cites the full URL including host and port from project URL resolution

#### Scenario: No hardcoded host/port in skill examples

- **GIVEN** `.cursor/skills/comando-verificar/SKILL.md` includes URL examples
- **WHEN** a developer reads the project stack table
- **THEN** examples reference project URL resolution — not hardcoded ports from another repo

---

### Requirement: REQ-CV-MATRIX-04 — Form event map inventory

For form-scoped verification, Phase 1 SHALL identify the form chain (form_id, route, `#validate`, `#submit`, `#ajax`, event subscribers, queues) and **create or update** `.cursor/context/testing/form-event-map.md` per `testing-browser-parity-and-form-events.mdc`.

Matrix rows for form submits SHALL trace to an entry in the form-event map when the flow is non-trivial.

#### Scenario: New form scope updates form-event map

- **GIVEN** scope targets a form not yet listed in `form-event-map.md`
- **WHEN** Phase 1 inventory completes
- **THEN** `form-event-map.md` gains a row: business flow → route/form → critical events
- **AND** at least one matrix row references that flow

---

### Requirement: REQ-CV-MATRIX-05 — Multistep and partial AJAX rebuild rows

The matrix SHALL support distinct row types for:

1. **Multistep forms** — factor includes wizard step; execution sequence is Next/Back (or equivalent) before final submit assert.
2. **Partial AJAX rebuilds** — after `#ajax` trigger, assert DOM fragment updated, behaviours re-attached, no WSOD; follow `e2e-update-on-code-change.mdc` AJAX patterns (`waitForResponse` + DOM assert).

#### Scenario: Multistep wizard row

- **GIVEN** a multistep form (e.g. courier order wizard)
- **WHEN** `/comando-verificar` includes that form in scope
- **THEN** the matrix includes at least one row per required step transition
- **AND** **Verified (E2E/form)** or **Verified (interactive)** cites step navigation evidence

#### Scenario: Partial AJAX rebuild row

- **GIVEN** a form field triggers `#ajax` that rebuilds part of the form (e.g. address → location fieldset)
- **WHEN** the matrix executes the AJAX row
- **THEN** the row asserts post-rebuild DOM state (not only HTTP 200)
- **AND** the row verdict is FAIL if behaviours fail to attach (console TypeError)

---

### Requirement: REQ-CV-MATRIX-06 — Post-submit side-effect rows

When `testing-browser-parity-and-form-events.mdc` applies, the matrix SHALL include **Layer B** rows for observable side-effects after successful form submit where in scope: queue items, cron side-effects, mail (read-only Mailpit when project documents it), or documented async triggers from `.cursor/context/testing/queue-ui-async-triggers.md`.

Rows MAY be marked `NOT VERIFIABLE` with concrete blocker when side-effect inspection is out of scope (e.g. PRO host).

#### Scenario: Form submit enqueue row

- **GIVEN** form submit enqueues a known queue per form-event map
- **WHEN** the happy-path matrix row passes
- **THEN** a side-effect row documents queue inspection command or `NOT VERIFIABLE` with reason
- **AND** the matrix does not claim full form parity with only the submit row green

---

### Requirement: REQ-CV-MATRIX-07 — Multi-role and permission-negative rows

For scopes affecting access control, the matrix SHALL include rows derived from `qa-local-roles-registry.mdc` for **each affected role** and at least one **`permission_negative`** row (role without permission → access denied in UI).

Credential variables SHALL follow project E2E env conventions (`E2E_*`); never hardcode passwords in matrix artefacts.

#### Scenario: Permission negative row

- **GIVEN** a route requires permission P
- **WHEN** `/comando-verificar` covers that route
- **THEN** the matrix includes a row with a role lacking P
- **AND** expected outcome is access denied (403 page or login redirect) — not WSOD

---

### Requirement: REQ-CV-SCOPE-01 — Current diff scope resolution

When the user scope is **current diff** (or scope is omitted and the agent defaults to the active task diff), Phase 0 SHALL document the exact git command and path list used for inventory and matrix planning:

1. Run `git diff --name-only` for unstaged changes and `git diff --cached --name-only` for staged changes (or `git diff HEAD --name-only` for all local changes against HEAD — pick one strategy and state it in the matrix header).
2. Record the **path list** in the matrix header (or appendix).
3. Limit combinatorial inventory to files and surfaces **in that path list** plus directly dependent routes/forms/services (no whole-repo sweep unless user expands scope).

#### Scenario: Diff scope documented in matrix header

- **GIVEN** the user invokes `/comando-verificar` with scope `current diff`
- **WHEN** Phase 0 completes
- **THEN** the matrix header names the git command used (e.g. `git diff HEAD --name-only`)
- **AND** lists the paths that bound inventory and row generation

#### Scenario: Config sync path triggers CMI note in scope

- **GIVEN** the resolved diff path list includes `config or schema paths/*.yml`
- **WHEN** Phase 4 regression runs
- **THEN** **REQ-CV-EXEC-05** (project config import) applies before dependent UI rows

---

### Requirement: REQ-CV-MATRIX-08 — Stable row identifiers

Every matrix data row SHALL have a unique, stable **`row_id`** within the artifact (format `R-NN` zero-padded or `R-1`, `R-2`, … — consistent within the file).

FAIL summaries, re-run after fix (VR-10), and **Verified** lines SHALL cite the same `row_id` — not only row ordinal or prose description.

#### Scenario: FAIL message cites row_id

- **GIVEN** matrix row `R-07` has verdict FAIL
- **WHEN** the agent prepares the closing message
- **THEN** **Not verified** or FAIL summary includes `R-07` explicitly
- **AND** the same `R-07` label appears in `matrix.md`

#### Scenario: Re-run after fix preserves row_id

- **GIVEN** the agent fixes code after `R-03` FAIL
- **WHEN** re-executing verification
- **THEN** the re-run row retains id `R-03` (updated Actual/Verdict columns)
- **AND** a new id is not invented for the same casuistic unless factors changed

---

### Requirement: REQ-CV-MATRIX-09 — Destructive and irreversible row policy

Matrix rows that trigger **destructive or irreversible** user actions (order cancel, entity delete, payment capture, workflow transitions that cannot be undone on local DB) SHALL be tagged **`destructive: true`** in the matrix.

Default policy:

- Mark **`BLOCKED (destructive)`** unless scope explicitly authorizes the action **and** the environment is disposable (local dev with developer-approved test data).
- Do **not** run destructive rows on shared QA/PRO hosts.
- Follow `unsafe-interactive-click-sweep` policy: no blind click-sweep; destructive rows require explicit scope or OpenSpec scenario authorization.

The agent SHALL NOT execute `/reset-floods` or password resets to unblock matrix login rows (see **REQ-CV-AUTH-01**).

#### Scenario: Cancel order row blocked by default

- **GIVEN** a matrix includes a row for submitting order cancel on a real order id
- **AND** scope did not explicitly authorize destructive verification
- **WHEN** Phase 3 reaches that row
- **THEN** verdict is `BLOCKED (destructive)` with reason
- **AND** overall PASS is not claimed for that casuistic

#### Scenario: Authorized destructive row on disposable local data

- **GIVEN** scope explicitly lists destructive casuistics (e.g. OpenSpec scenario for cancel modal)
- **AND** environment is local dev with test order/rider fixtures
- **WHEN** the row executes
- **THEN** matrix records `destructive: true`, command/tool, and outcome
- **AND** **Verified (interactive)** cites the authorized action only

---

### Requirement: REQ-CV-EXEC-01 — Execute matrix rows with real evidence

Each matrix row marked PASS SHALL cite a command, test, or browser action executed **in the same session after the last code edit** (VR-10).

Paper matrices without runtime execution SHALL NOT produce overall PASS.

#### Scenario: FAIL row blocks listo

- **GIVEN** one matrix row has verdict FAIL
- **WHEN** the agent prepares the closing message
- **THEN** overall status is not PASS / listo
- **AND** **Not verified** or explicit FAIL summary lists the row id and next fix step

#### Scenario: Re-verify after fix

- **GIVEN** the agent fixes code after a FAIL row
- **WHEN** closing after the fix
- **THEN** affected rows were re-executed on the final tree
- **AND** prior PASS rows before the fix are not cited if code changed (VR-10)

---

### Requirement: REQ-CV-EXEC-02 — Regression sweep mandatory

After matrix execution, the workflow SHALL run applicable regression checks:

- project lint command on touched custom code paths.
- project test command on affected modules when services changed.
- `node --check` on touched JS; VR-15 console on exact user URL when UI changed.
- project cache rebuild when applicable when `.module`, `*.services.yml`, routing, or libraries changed.

#### Scenario: UI change includes console gate

- **GIVEN** the scoped change touches JS or `.module` markup on `/rider`
- **WHEN** `/comando-verificar` closes
- **THEN** **Verified (JS)** cites `/rider` with zero Uncaught errors
- **AND** cache rebuild is mentioned if libraries or module changed

---

### Requirement: REQ-CV-EXEC-05 — Config import when diff touches CMI

When the scoped diff includes config or schema paths, Phase 4 regression SHALL run the **project config import/migrate command** (or document equivalent status showing no pending import) before matrix browser/runtime rows that depend on imported config.

#### Scenario: Config sync in diff triggers cim

- **GIVEN** `git diff` includes `config or schema paths/*.yml`
- **WHEN** `/comando-verificar` runs regression sweep
- **THEN** **Verified** includes project config import or equivalent with outcome
- **AND** matrix UI rows run after config is active

---

### Requirement: REQ-CV-EXEC-06 — Multilayer E2E gate when applicable

When the scoped diff touches form routes, UI contract anchors, or journeys listed in `e2e-update-on-code-change.mdc`, Phase 4 SHALL run applicable gates:

```bash
node tests/e2e/scripts/multilayer-gate.mjs --gate
```

when map/registry files changed or when the agent claims E2E coverage for the scope. Document **Not verified** if gates are skipped with reason.

#### Scenario: Form diff runs multilayer gate

- **GIVEN** scope includes a form route with existing E2E inventory entry
- **WHEN** `/comando-verificar` closes after product-impacting work (not infra-only apply)
- **THEN** **Verified** cites multilayer gate exit code or **Not verified** with skip reason

---

### Requirement: REQ-CV-EXEC-07 — Do not weaken E2E to green matrix

Resolving a matrix row FAIL SHALL NOT weaken, delete, or skip E2E assertions per `openspec-e2e-regression-guard.mdc`. Conflicts between matrix pass and E2E fail require code fix or spec update — not test aflojamiento.

#### Scenario: Matrix FAIL fixed in production not in test

- **GIVEN** a matrix row FAILs on form validation
- **WHEN** the agent fixes the issue
- **THEN** the agent does not remove E2E validation assertions to match
- **AND** E2E specs are updated only to reflect intentional spec change

---

### Requirement: REQ-CV-EXEC-08 — QA phase 1 Playwright waiver

When `qa-local-no-playwright-phase1.mdc` applies (local QA phase 1, MCP/browser only), matrix rows SHALL use Browser DevTools MCP instead of Playwright when Playwright is not run, provided:

- Each skipped Playwright row is marked `NOT VERIFIABLE (phase-1 MCP-only)` or executed via MCP with equivalent fill→submit evidence.
- **Not verified** lists any dimension not exercised (e.g. full journey registry).

#### Scenario: Phase 1 documents Playwright waiver

- **GIVEN** the session is local QA phase 1 without Playwright
- **WHEN** `/comando-verificar` closes
- **THEN** **Not verified** or matrix header notes phase-1 waiver
- **AND** MCP/browser evidence exists for every form row marked PASS

---

### Requirement: REQ-CV-E2E-01 — Optional coverage map alignment

When matrix verification closes form/route work with new or updated E2E specs, the agent SHALL document covered inventory dimensions in the matrix header or appendix and SHOULD update `tests/e2e/coverage-map.json` via project sync scripts when the scope includes new E2E specs.

Mapping matrix row IDs to dimensions (`route`, `validation`, `ajax`, `permission_negative`, etc.) MUST appear in the matrix header or appendix when E2E inventory applies.

Infra-only apply (command/skill/rule) MUST NOT be blocked by missing coverage-map sync.

#### Scenario: Matrix documents inventory dimensions

- **GIVEN** matrix rows cover form validation and AJAX
- **WHEN** the matrix artifact is written
- **THEN** the header or appendix lists covered dimensions matching `coverage-denominator.json` vocabulary where applicable

---

### Requirement: REQ-CV-EXEC-03 — Closing Verification block format

The final response SHALL include `## Verification` per `00-verification-gate.mdc` with at least:

- **Verified:** matrix artifact path and count of PASS rows vs total mandatory rows.
- **Verified (E2E/form)** or **Verified (interactive)** when form/UI rows exist.
- **Verified (JS)** when JS/UI rows exist.
- **Not verified:** any BLOCKED or NOT VERIFIABLE rows with concrete blockers.

**Resumen** SHALL follow VR-14 (no success words without matching Verified lines).

#### Scenario: Resumen locked to matrix

- **GIVEN** 8 matrix rows with 6 PASS and 2 BLOCKED (missing test data)
- **WHEN** the agent writes Resumen
- **THEN** Resumen states partial coverage (6/8) and does not say “listo” or “verificado” for full coverage
- **AND** **Verified** mentions 6/8 PASS with artifact path

---

### Requirement: REQ-CV-EXEC-04 — Anti-patterns forbidden

The command, skill, and rule SHALL explicitly forbid:

- Closing with PHPUnit/curl-only proof for form-driven matrix rows (VR-09).
- Skipping validation-error rows.
- Host-run tests outside project-documented runtime.
- Delegating checks to the developer (“recarga y comprueba”).
- Weakening tests to green matrix rows.

#### Scenario: Skill lists anti-patterns

- **GIVEN** `.cursor/skills/comando-verificar/SKILL.md` exists
- **WHEN** an agent reads the Anti-patterns section
- **THEN** at least five forbidden behaviours are listed matching REQ-CV-EXEC-04
- **AND** each references an existing project rule id (VR-07, VR-09, etc.)
