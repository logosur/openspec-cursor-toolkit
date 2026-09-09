# Spec — run-spec-loop

Capability: **top-level unattended OpenSpec run loop** — command `/run-spec`, skill `run-spec`, Cursor L2 rule, persistent `RUN-LOOP.md`, gap-closure gate, `[prod-verify]` marker, tests + regression gates, delegated deploy, paced (`/loop`) mode.

## ADDED Requirements

### Requirement: REQ-RS-CMD-01 — Command, skill and rule exist in both toolkits

The toolkit SHALL provide `.claude/commands/run-spec.md` and `.claude/skills/run-spec/SKILL.md` (Claude Code) and `.cursor/commands/run-spec.md`, `.cursor/skills/run-spec/SKILL.md`, `.cursor/rules/run-spec-openspec-loop.mdc` (Cursor). Frontmatter SHALL follow the existing parity convention (`repasa-spec` as reference): Claude Code command `description` + `argument-hint`; Cursor command `name`, `id`, `category`, `description`; skills `name`, `description`, `disable-model-invocation: true`; Cursor rule `alwaysApply: false` with `globs: openspec/changes/**/*`.

#### Scenario: Files present with parity frontmatter

- **GIVEN** the apply phase completed for `loop-skill`
- **WHEN** a developer lists the five paths above
- **THEN** every file exists
- **AND** `.claude/commands/run-spec.md` frontmatter contains `argument-hint: "[slug] [--no-deploy] [--max-iter N]"` (or equivalent wording naming both flags)
- **AND** `.cursor/commands/run-spec.md` frontmatter contains `id: run-spec`
- **AND** both `SKILL.md` files contain `disable-model-invocation: true`

#### Scenario: Command delegates to the skill

- **GIVEN** either command file
- **WHEN** an agent reads it
- **THEN** it instructs reading the matching `run-spec/SKILL.md` in the same turn before executing any phase

---

### Requirement: REQ-RS-INPUT-01 — Input parsing and single clarification

The command SHALL parse line 1 as `run-spec <slug> [--no-deploy] [--max-iter N]` (optional leading `/`, whitespace separated, no `:`) and lines 2..n as the **description** (multiline, verbatim). `<slug>` SHALL be kebab-case. `--max-iter N` SHALL accept 1–5 (values above 5 clamp to 5 and are logged). When `<slug>` is missing or not kebab-case the agent SHALL ask **once** and stop. When the description is empty **and** `openspec/changes/<slug>/` does not exist the agent SHALL ask **once** for the description and stop. When the description is empty and the folder exists the agent SHALL enter **resume mode** (REQ-RS-STATE-01).

#### Scenario: Canonical two-line invocation

- **WHEN** the user sends `/run-spec rider-eta\nShow live ETA on the rider card`
- **THEN** `slug = rider-eta`, `description = "Show live ETA on the rider card"`, `no_deploy = false`, `max_iter = 3`

#### Scenario: Flags on line 1

- **WHEN** the user sends `/run-spec rider-eta --no-deploy --max-iter 2\n<description>`
- **THEN** `no_deploy = true` and `max_iter = 2`
- **AND** the flags are not treated as part of the description

#### Scenario: Missing slug

- **WHEN** the user sends `/run-spec\nsome description`
- **THEN** the agent asks once for a kebab-case slug and stops without creating files

#### Scenario: Resume without description

- **GIVEN** `openspec/changes/rider-eta/` exists
- **WHEN** the user sends `/run-spec rider-eta`
- **THEN** the agent does not ask for a description and resumes from `RUN-LOOP.md`

---

### Requirement: REQ-RS-STATE-01 — Persistent, resumable loop state

The skill SHALL maintain `openspec/changes/<slug>/RUN-LOOP.md` following `docs/openspec/templates/RUN-LOOP-template.md`. The file SHALL be written **after every phase transition** and SHALL contain: header (`slug`, `mode` inline|paced, `no_deploy`, `max_iter`, `iteration`, `started`, `updated`), a phase table with one row per phase P0–P7 (`status` ∈ `pending|running|done|skipped|blocked`, evidence, timestamp), the last gate reading (`gaps_pending`, `tasks_unchecked`, `tasks_prod_verify`), an iteration log, and the current verdict. On start with an existing file the skill SHALL resume from the first phase whose status is not `done`/`skipped`, SHALL NOT re-run `done` phases, and SHALL re-check the exit gate of any phase left `running` (crash-safe).

#### Scenario: State written after each phase

- **GIVEN** a run that completed P1 and P2
- **WHEN** the developer opens `RUN-LOOP.md`
- **THEN** rows P1 and P2 show `done` with evidence paths and timestamps
- **AND** row P3 shows `running` or `pending`

#### Scenario: Resume skips completed phases

- **GIVEN** `RUN-LOOP.md` with P0–P4 `done` and P5 `pending`
- **WHEN** `/run-spec <slug>` runs again
- **THEN** the agent starts at P5 and does not invoke `/prepara-tarea` or `/repasa-spec` again
- **AND** the header `iteration` value is preserved

#### Scenario: Interrupted phase is re-checked, not blindly trusted

- **GIVEN** `RUN-LOOP.md` with P3 `running`
- **WHEN** the loop resumes
- **THEN** it re-reads the gate from `GAPS.md`/`tasks.md` before deciding whether P3 is done

---

### Requirement: REQ-RS-PHASES-01 — Fixed sequential phase order with delegation

The skill SHALL execute phases in this order and never in parallel: P1 `/prepara-tarea <slug>` + description → P2 `/repasa-spec <slug>` → P3 gap-closure loop (REQ-RS-LOOP-01) → P4 confirm review (REQ-RS-CONFIRM-01) → P5 feature tests (REQ-RS-TESTS-01) → P6 regression (REQ-RS-REGRESSION-01) → P7 publish (REQ-RS-PUBLISH-01) → P8 deploy gate (REQ-RS-DEPLOY-01). Each phase SHALL be delegated to the canonical existing command/skill in a **fresh-context subagent**, and the inner "stop, run the next command in a new message" lines of those skills SHALL be overridden inside `run-spec` (same pipeline override as `repasa-spec`). **Exception:** P7 and P8 SHALL run in the **main agent**, because they mutate git and open decision dialogs (the P8 approval dialog, plus the project deploy command's own prompts) that must reach the developer and cannot be answered inside a subagent. P1 SHALL be `skipped` when `proposal.md` already exists.

#### Scenario: Phase order enforced

- **WHEN** the loop runs from scratch
- **THEN** `RUN-LOOP.md` timestamps for P1 < P2 < P3 < P4 < P5 < P6 < P7 < P8
- **AND** no two phases are ever `running` at the same time

#### Scenario: Existing change skips bootstrap

- **GIVEN** `openspec/changes/<slug>/proposal.md` exists
- **WHEN** P1 is reached
- **THEN** P1 is marked `skipped (proposal exists)` and P2 starts

#### Scenario: Publish and deploy phases are not delegated to a subagent

- **GIVEN** P7 and P8 are reached with `no_deploy = false`
- **WHEN** the loop publishes and then asks for deploy approval
- **THEN** both run in the main agent so the approval dialog and the deploy command's own prompts reach the developer
- **AND** `run-spec` does not pre-answer any of them

#### Scenario: Inner stop lines do not stop the loop

- **GIVEN** the P1 subagent ends with `Do not implement yet.` / `No implementes todavía.`
- **WHEN** the orchestrator receives the report
- **THEN** it records P1 `done` and proceeds to P2 in the same run

---

### Requirement: REQ-RS-GATE-01 — Machine-readable gap-closure gate

The gate SHALL be computed from files only: `gaps_pending` = integer of the **last** line in `openspec/changes/<slug>/GAPS.md` matching, with the surrounding `**` bold markers that `GAPS.md` writes in its `## Pending count` block tolerated and stripped, `^\*{0,2}Gaps pending \(mejora \+ apply\): [0-9]+\*{0,2}$`; `tasks_unchecked` = count of lines in `tasks.md` matching `^\s*- \[ \]` whose text does **not** contain `[prod-verify]`; `tasks_prod_verify` = count of unchecked lines that contain `[prod-verify]`. Gate result SHALL be `PASS` iff `gaps_pending == 0 && tasks_unchecked == 0`; `UNKNOWN` (treated as `FAIL`) when `GAPS.md` or the line is missing. The orchestrator SHALL also require the phase subagent to end its report with the same canonical line and, on mismatch, SHALL take the **more pessimistic** value: a report claiming fewer gaps than the file SHALL NOT lower the count, and a report claiming more SHALL be written into `GAPS.md` before the gate is re-read, so a real finding can never be discarded by the gate. Every mismatch SHALL be logged with its resolution.

#### Scenario: Gate passes

- **GIVEN** `GAPS.md` ends with `Gaps pending (mejora + apply): 0` and `tasks.md` has two unchecked lines both containing `[prod-verify]`
- **WHEN** the gate is evaluated
- **THEN** `gaps_pending = 0`, `tasks_unchecked = 0`, `tasks_prod_verify = 2`, result `PASS`

#### Scenario: Bold pending line in GAPS.md

- **GIVEN** `GAPS.md` writes the count in its `## Pending count` block as `**Gaps pending (mejora + apply): 0**`
- **WHEN** the gate is evaluated
- **THEN** `gaps_pending = 0` — the bold markers are tolerated, not read as a missing line
- **AND** the result is not `UNKNOWN`

#### Scenario: Gate fails on untagged task

- **GIVEN** `Gaps pending (mejora + apply): 0` and one unchecked task without the marker
- **WHEN** the gate is evaluated
- **THEN** result is `FAIL` with `tasks_unchecked = 1`

#### Scenario: Missing pending line

- **GIVEN** `GAPS.md` without the canonical line
- **WHEN** the gate is evaluated
- **THEN** result is `UNKNOWN`, treated as `FAIL`, and the next action is one `/repasa-spec` iteration

#### Scenario: Subagent under-reports gaps

- **GIVEN** the subagent reports `Gaps pending (mejora + apply): 0` but `GAPS.md` says `2`
- **WHEN** the orchestrator reconciles
- **THEN** it uses `2`, logs `gate mismatch (report 0 / file 2) → file wins` in `RUN-LOOP.md`, and does not proceed

#### Scenario: Reviewer finds gaps the file does not list

- **GIVEN** `GAPS.md` says `0` but the confirm reviewer reports `2` with path:line evidence
- **WHEN** the orchestrator reconciles
- **THEN** it uses `2`, writes the two findings into `GAPS.md`, logs `gate mismatch (report 2 / file 0) → findings persisted`
- **AND** the gate does not pass merely because the stale file said `0`

---

### Requirement: REQ-RS-LOOP-01 — Bounded closure loop with convergence guard

P3 SHALL repeat `/repasa-spec <slug>` (fresh-context subagent) until the gate is `PASS`, at most `max_iter` iterations (default 3). After each iteration the pair `(gaps_pending, tasks_unchecked)` SHALL be compared with the previous iteration; if identical the loop SHALL stop with verdict `NO PROGRESS`. Exhausting `max_iter` with the gate still `FAIL` SHALL stop with `BLOCKED (max-iter reached)`. Fix-forward passes in P5/P6 SHALL consume the same budget.

#### Scenario: Converges in two iterations

- **GIVEN** iteration 1 leaves `(3, 2)` and iteration 2 leaves `(0, 0)`
- **WHEN** P3 runs
- **THEN** the loop stops after iteration 2 with gate `PASS` and P4 starts

#### Scenario: No progress stops early

- **GIVEN** iteration 1 leaves `(2, 1)` and iteration 2 leaves `(2, 1)`
- **WHEN** P3 evaluates iteration 2
- **THEN** the verdict is `NO PROGRESS`, no iteration 3 runs, and the report lists the 2 gaps and 1 task verbatim

#### Scenario: Budget exhausted

- **GIVEN** `max_iter = 2` and both iterations improve but the gate is still `FAIL`
- **WHEN** iteration 2 ends
- **THEN** the verdict is `BLOCKED (max-iter reached)` and the report shows the remaining counts

---

### Requirement: REQ-RS-PRODTASK-01 — `[prod-verify]` task marker

Tasks whose verification depends on production SHALL carry the literal token `[prod-verify]` in their `tasks.md` line. The loop SHALL never flip those checkboxes, SHALL exclude them from `tasks_unchecked`, and SHALL list each tagged line verbatim under **Residual (production)** in the final report. The `run-spec` skill SHALL instruct P2/P3 subagents to add the marker only to tasks that genuinely require a production host, provider or data, and the template/docs SHALL document the marker.

#### Scenario: Tagged task does not block

- **GIVEN** `- [ ] 8.1 Run migration on PRO [prod-verify]` is the only unchecked task
- **WHEN** the gate is evaluated
- **THEN** `tasks_unchecked = 0` and the final report lists `8.1 Run migration on PRO [prod-verify]` under Residual (production)

#### Scenario: Marker never auto-checked

- **WHEN** any `run-spec` phase completes
- **THEN** no line containing `[prod-verify]` changed from `- [ ]` to `- [x]` unless a human did it

---

### Requirement: REQ-RS-CONFIRM-01 — Independent confirm review

After P3 `PASS`, P4 SHALL run one `/repasa-spec <slug>` in a **fresh-context subagent** whose prompt forbids assuming prior results, then re-evaluate the gate from files. If `PASS`, P5 starts. If `FAIL`, the reviewer's findings SHALL first be written into `GAPS.md`; control SHALL then return to P3 if budget remains, or the verdict SHALL be `BLOCKED (confirm review found gaps)`.

#### Scenario: Confirm review agrees

- **GIVEN** P3 `PASS`
- **WHEN** P4 finishes with `Gaps pending (mejora + apply): 0` and no untagged unchecked task
- **THEN** P4 `done` and P5 starts

#### Scenario: Confirm review finds new gap

- **GIVEN** P4 leaves `gaps_pending = 1` and one iteration of budget remains
- **WHEN** the orchestrator evaluates
- **THEN** P3 runs one more iteration and `RUN-LOOP.md` iteration log records the return

---

### Requirement: REQ-RS-TESTS-01 — Feature tests with fix-forward, no test weakening

P5 SHALL run `/ejecuta-tests-reporte <slug>` (narrowest project test command per the stack rule). On non-zero exit the loop SHALL classify per `openspec-e2e-regression-guard` and fix forward via `/aplica-tarea <slug>` (budget permitting), re-running the tests; assertions SHALL never be relaxed, skipped or deleted to obtain green. `ambiguous` classification → `BLOCKED (ambiguous test failure)`. When the project documents no test command, P5 SHALL be `skipped (no project test command)`.

#### Scenario: Tests green

- **WHEN** the scoped test command exits 0
- **THEN** P5 `done` with the exact command and exit code as evidence

#### Scenario: Tests red then fixed

- **GIVEN** the first run fails with an application regression and budget remains
- **WHEN** fix-forward runs and the re-run exits 0
- **THEN** P5 `done`, iteration counter incremented, both commands logged

#### Scenario: Ambiguous failure

- **GIVEN** a failing assertion where spec, code and test disagree without evidence of an intended change
- **WHEN** classification yields `ambiguous`
- **THEN** verdict `BLOCKED (ambiguous test failure)` and P6/P7 do not run

---

### Requirement: REQ-RS-REGRESSION-01 — Regression gate before deploy

P6 SHALL run the project's **full** test command and E2E suite as documented in its stack rule. Failures SHALL be classified and handled as in REQ-RS-TESTS-01. If the project documents no full test/E2E command, P6 SHALL be `skipped (no regression signal)` **and** P7 SHALL be downgraded: the loop ends with `READY TO DEPLOY` instead of deploying unattended. The loop SHALL never reach P7 with P5 or P6 red.

#### Scenario: Regression green enables publish and the deploy gate

- **WHEN** full tests and E2E exit 0
- **THEN** P6 `done` and P7 (publish) is eligible, followed by the P8 approval dialog

#### Scenario: No regression signal downgrades deploy

- **GIVEN** the target project's stack rule documents no full test or E2E command
- **WHEN** P6 is reached
- **THEN** P6 `skipped (no regression signal)`, P8 `skipped (downgraded)`, verdict `READY TO DEPLOY`

---

### Requirement: REQ-RS-PUBLISH-01 — Publish the work on the current branch

P7 SHALL run when P5 and P6 are `done`. It SHALL, in the **main agent**: inspect the working tree (`git status -sb`, `git status --porcelain`, `git diff --stat`), stage the work belonging to this change, commit it with a single English imperative message (first line ≤ 72 chars) naming the change, and push the **current branch** to its own remote (`git push -u origin <current-branch>`). It SHALL NOT sweep in files outside the change's declared Impact — unrelated edits, another session's work, build artefacts or caches: it SHALL stage explicit paths in that case and, when the split is not obvious, ask before staging. It SHALL record the staged file list as evidence. Invoking `/run-spec` SHALL be the authorization for exactly this commit and push, and for nothing else: the loop SHALL never merge, rebase, cherry-pick, tag, force-push, or push any branch other than the current one. A clean tree already in sync SHALL be `skipped (nothing to publish)`. When the current branch is the project's **production branch** (`main` by default, or whatever the project's stack rule names), P7 SHALL make **no** git mutation and SHALL be `blocked (on production branch)`, carrying that fact into the P8 dialog. With `no_deploy = true` P7 SHALL still run — publishing is independent of deploying.

#### Scenario: Work is committed and pushed to the feature branch

- **GIVEN** P6 `done` on branch `feature/rider-eta` with a dirty tree
- **WHEN** P7 runs
- **THEN** all pending work is committed with one imperative English message naming the change
- **AND** the branch is pushed to `origin/feature/rider-eta`
- **AND** no merge, rebase, tag or force-push happened

#### Scenario: Unrelated files are not swept into the commit

- **GIVEN** the tree contains build artefacts and an edit unrelated to the change
- **WHEN** P7 stages the work
- **THEN** only the change's own paths are staged, or the developer is asked which files belong
- **AND** the commit's file list is recorded as P7 evidence

#### Scenario: Nothing to publish

- **GIVEN** a clean tree whose branch already matches its upstream
- **WHEN** P7 runs
- **THEN** P7 is `skipped (nothing to publish)` and the loop continues to P8

#### Scenario: Production branch is never auto-pushed

- **GIVEN** the current branch is the project's production branch
- **WHEN** P7 runs
- **THEN** no commit and no push happen
- **AND** P7 is `blocked (on production branch)` and the P8 dialog states this first

---

### Requirement: REQ-RS-DEPLOY-01 — Deploy is gated by an explicit developer decision

P8 SHALL **never** deploy unattended. When P7 finished and `no_deploy = false` and a project deploy command exists, the loop SHALL stop and open **one** `AskUserQuestion` dialog in the main agent whose first option is *deploy now, unattended* and whose second is *stop here*. Before asking, the loop SHALL gather what the developer needs to decide: the branch and pushed commit, what the change does, test and regression results, residual `[prod-verify]` tasks, and what the project's deploy command will actually do (cascade merges, target host, migrations). It MAY add up to three further questions in the same dialog for genuine doubts about the deploy, and it SHALL NOT ask about anything the project's own deploy command already asks. The loop SHALL NOT pre-answer the dialog, SHALL NOT infer approval from the invocation, and SHALL NOT treat silence or a non-answer as approval.

On *deploy now*, the loop SHALL invoke the project deploy command (`.claude/commands/deploy.md`, or `.cursor/commands/deploy.md` in Cursor) in the main agent, exactly as a developer would, letting it run its own preflight and prompts, and SHALL end with `DEPLOYED` on its success. On *stop here* the verdict SHALL be `READY TO DEPLOY`. When the dialog cannot be shown (non-interactive, background, or paced tick) the verdict SHALL be `AWAITING DEPLOY APPROVAL` and the loop SHALL print the exact command to run. With `no_deploy = true` the dialog SHALL be skipped entirely and the verdict SHALL be `READY TO DEPLOY`. With no project deploy command the verdict SHALL be `BLOCKED (no deploy command)`. The loop SHALL never run FTP, SSH or a CI dispatch of its own.

#### Scenario: Developer approves the deploy

- **GIVEN** P7 `done`, `no_deploy = false`, and `.claude/commands/deploy.md` exists
- **WHEN** P8 opens the approval dialog and the developer picks *deploy now, unattended*
- **THEN** the project deploy flow runs in the main agent without further questions from `run-spec`
- **AND** on its success the verdict is `DEPLOYED`

#### Scenario: Developer stops at the gate

- **WHEN** the developer picks *stop here*
- **THEN** the verdict is `READY TO DEPLOY`, no deploy runs, and the pushed branch and commit are reported

#### Scenario: Approval is never assumed

- **GIVEN** everything is green and the developer has not answered the dialog
- **WHEN** the loop evaluates whether to deploy
- **THEN** it does not deploy
- **AND** it never treats the `/run-spec` invocation itself as deploy approval

#### Scenario: Dialog cannot be shown

- **GIVEN** a non-interactive or background run
- **WHEN** P8 is reached
- **THEN** the verdict is `AWAITING DEPLOY APPROVAL` and the exact deploy command is printed

#### Scenario: `--no-deploy` skips the gate

- **GIVEN** `no_deploy = true`
- **WHEN** P7 completes
- **THEN** no dialog is opened and the verdict is `READY TO DEPLOY`
- **AND** the branch was still committed and pushed by P7

#### Scenario: Project without deploy command

- **GIVEN** neither deploy command file exists
- **WHEN** P8 is reached
- **THEN** the verdict is `BLOCKED (no deploy command)` and no FTP, SSH or CI dispatch was attempted

---

### Requirement: REQ-RS-REPORT-01 — Final report and canonical verdict line

The final chat SHALL contain, in order: `## Run loop — <slug>` (phase table copied from `RUN-LOOP.md`), `## Verification` (commands + exit codes + evidence paths), `## Residual` (production-tagged tasks verbatim, residual gaps, blockers), `## Resumen` (verified facts only). The **last line** SHALL be exactly `Run-spec verdict: <VERDICT>` with `<VERDICT>` ∈ `DEPLOYED | READY TO DEPLOY | AWAITING DEPLOY APPROVAL | BLOCKED (<reason>) | NO PROGRESS`, matching the verdict stored in `RUN-LOOP.md`.

#### Scenario: Last line parseable

- **WHEN** any run ends
- **THEN** the last non-empty chat line matches `^Run-spec verdict: (DEPLOYED|READY TO DEPLOY|AWAITING DEPLOY APPROVAL|BLOCKED \(.+\)|NO PROGRESS)$`
- **AND** the same verdict string appears in `RUN-LOOP.md`

---

### Requirement: REQ-RS-PACED-01 — Paced mode via loops primitives

The skill SHALL support paced execution when invoked through `/loop /run-spec <slug>`: each tick SHALL read `RUN-LOOP.md`, execute at most **one** phase (or one P3 iteration), persist state, and yield with `ScheduleWakeup` semantics — `noop: false` when state advanced, `noop: true` when only waiting on an external signal, `stop: true` on a terminal verdict — including `AWAITING DEPLOY APPROVAL`, since a paced tick cannot ask the developer — `prompt` = the same `/run-spec <slug>` text, `delaySeconds` = 60 when the next phase can start immediately and matched to the awaited external duration otherwise; it SHALL NOT schedule short polls for harness-tracked subagents. In Cursor the same one-phase-per-tick contract SHALL use the Cursor `/loop` monitored-shell mechanism. When no wake-up primitive is available the skill SHALL say so and run inline.

#### Scenario: One phase per tick

- **GIVEN** paced mode and P2 `pending`
- **WHEN** a tick fires
- **THEN** only P2 executes, `RUN-LOOP.md` shows P2 `done`, and the tick yields `noop: false` with `delaySeconds ≥ 60`

#### Scenario: Waiting on deploy CI

- **GIVEN** P7 delegated deploy reports "CI running, ~8 min"
- **WHEN** the tick yields
- **THEN** `noop: true`, `delaySeconds` ≈ 480, `reason` names the CI wait

#### Scenario: Terminal verdict stops the loop

- **WHEN** the verdict becomes `DEPLOYED`, `AWAITING DEPLOY APPROVAL` or any `BLOCKED (...)`
- **THEN** the tick yields `stop: true` and no further wake-ups are scheduled

---

### Requirement: REQ-RS-TOKEN-01 — Token-efficiency contract

The skill SHALL state and the orchestrator SHALL obey: read `run-spec/SKILL.md` once per run; do not re-read delegated skills (subagents read their own); hold only the state table in context; evaluate gates with `grep`/`tail` on the three gate sources, never by reading whole artefacts; skip a phase whose exit gate already holds on resume; create no `.md` outside `openspec/changes/<slug>/`; require subagent reports ≤ 15 lines with fixed keys (`phase_status`, `evidence`, `gaps_pending`, `tasks_unchecked`, `tasks_prod_verify`, `blocker`).

#### Scenario: Orchestrator never reads whole GAPS.md

- **WHEN** the gate is evaluated
- **THEN** the orchestrator's tool calls on `GAPS.md` are pattern searches or tail reads, not full-file reads

#### Scenario: Subagent report shape

- **WHEN** any phase subagent returns
- **THEN** its report contains the six fixed keys and is ≤ 15 lines

---

### Requirement: REQ-RS-SAFETY-01 — Stop conditions and git boundary

The loop's **only** git mutation SHALL be P7: commit and push of the **current** branch (REQ-RS-PUBLISH-01). It SHALL never merge, rebase, cherry-pick, tag, force-push, or push another branch, and it SHALL never deploy without the P8 approval. It SHALL stop with `BLOCKED (<reason>)` on: missing credentials or human-only access, ambiguous product decision, destructive or high-risk operation needing confirmation, an unavailable OpenSpec CLI in the target project, or explicit user interrupt. Blockers SHALL be visible in both `RUN-LOOP.md` and the final report; partial state SHALL never be hidden.

#### Scenario: Credentials missing mid-apply

- **GIVEN** a P3 subagent reports `blocker: missing credentials for provider X`
- **WHEN** the orchestrator receives it
- **THEN** verdict `BLOCKED (missing credentials for provider X)`, `RUN-LOOP.md` row P3 `blocked`, and P4–P8 do not run

#### Scenario: Target project has no OpenSpec CLI

- **GIVEN** the `openspec` CLI is not installed or not on `PATH` in the target project
- **WHEN** P1 or P2 needs `openspec status` / `openspec validate`
- **THEN** the loop stops with `BLOCKED (openspec CLI unavailable)` naming the missing binary
- **AND** it does not silently continue with unvalidated artefacts

#### Scenario: No git mutation before the publish phase

- **WHEN** a run ends before P7 with any verdict
- **THEN** `git log` shows no commit created by the loop
- **AND** nothing was pushed

#### Scenario: Only the current branch is pushed

- **GIVEN** P7 pushed `feature/rider-eta`
- **WHEN** the run ends with any verdict
- **THEN** no other branch was pushed and no merge or rebase was performed

---

### Requirement: REQ-RS-DOCS-01 — Documentation and cross-links

`README.md`, `.claude/skills/README.md`, `.cursor/skills/README.md` and `docs/openspec/README.md` SHALL document `/run-spec` (purpose, invocation, phases, flags, `[prod-verify]`, paced mode). `docs/openspec/templates/RUN-LOOP-template.md` SHALL exist. Both `repasa-spec` command files SHALL gain a relation-table row pointing to `/run-spec` as the layer above.

#### Scenario: Docs mention the command

- **WHEN** grepping the four README files for `/run-spec`
- **THEN** each file has at least one match

#### Scenario: Template exists and matches state schema

- **WHEN** opening `docs/openspec/templates/RUN-LOOP-template.md`
- **THEN** it contains the header keys, the P0–P7 phase table, the gate block and the verdict line described in REQ-RS-STATE-01
