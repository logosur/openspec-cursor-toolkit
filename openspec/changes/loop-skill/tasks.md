# Tasks — loop-skill (`/run-spec`)

> Every task maps to a requirement (REQ-RS-*) or a design risk. Flip `- [ ]` → `- [x]` only when implemented **and** verified. Tasks tagged `[prod-verify]` are verifiable only outside this repo and never block the `run-spec` gate.

## 1. Claude Code command and skill

- [x] 1.1 Create `.claude/commands/run-spec.md` — frontmatter `description` + `argument-hint: "[slug] [--no-deploy] [--max-iter N]"`; parsing rules (line 1 slug + flags, body = description, single clarification, resume mode); mandatory "read `.claude/skills/run-spec/SKILL.md` in the same turn"; phase summary table; canonical two-line invocation example (REQ-RS-CMD-01, REQ-RS-INPUT-01)
- [x] 1.2 Create `.claude/skills/run-spec/SKILL.md` with `name: run-spec`, `description` (EN/ES triggers: `/run-spec`, `build spec`, `construye la spec`, `idea a deploy`), `disable-model-invocation: true` (REQ-RS-CMD-01)
- [x] 1.3 Skill §Phases: P0–P7 fixed order, fresh-context subagent per phase, pipeline override of inner stop lines, P1 skip when `proposal.md` exists (REQ-RS-PHASES-01)
- [x] 1.4 Skill §State: `RUN-LOOP.md` schema, write-after-every-transition, resume rules, crash-safe re-check of `running` phases (REQ-RS-STATE-01)
- [x] 1.5 Skill §Gate: exact `grep`/`tail` commands for `gaps_pending`, `tasks_unchecked`, `tasks_prod_verify`; PASS/FAIL/UNKNOWN table; report-vs-file mismatch rule (REQ-RS-GATE-01)
- [x] 1.6 Skill §Loop: `max_iter` default 3, clamp 1–5, convergence guard `NO PROGRESS`, `BLOCKED (max-iter reached)`, shared budget with P5/P6 fix-forward (REQ-RS-LOOP-01)
- [x] 1.7 Skill §Marker: `[prod-verify]` semantics, when subagents may add it, never auto-check, verbatim listing in Residual (REQ-RS-PRODTASK-01)
- [x] 1.8 Skill §Confirm review: fresh reviewer prompt text ("do not assume prior results"), return-to-P3 rule (REQ-RS-CONFIRM-01)
- [x] 1.9 Skill §Tests + §Regression: `/ejecuta-tests-reporte`, project full tests + E2E from stack rule, classification per `openspec-e2e-regression-guard`, fix-forward via `/aplica-tarea`, `ambiguous → BLOCKED`, no-signal downgrade to `READY TO DEPLOY` (REQ-RS-TESTS-01, REQ-RS-REGRESSION-01)
- [x] 1.10 Skill §Publish (P7): commit all pending work + `git push -u origin <current-branch>` in the main agent; nothing else authorized (no merge/rebase/tag/force-push/other branch); `skipped (nothing to publish)` on a clean synced tree; `blocked (on production branch)` with no git mutation on the production branch (REQ-RS-PUBLISH-01)
- [x] 1.15 Skill §Deploy gate (P8): mandatory `AskUserQuestion` before any deploy — evidence to gather first, first option *deploy now, unattended*, second *stop here*, up to three extra doubt questions, never pre-answered, never inferred from the invocation; `--no-deploy` skips the dialog; no deploy command → `BLOCKED (no deploy command)`; no dialog channel → `AWAITING DEPLOY APPROVAL` + printed command (REQ-RS-DEPLOY-01)
- [x] 1.16 Skill §Report + §Stop conditions + §Paced mode: add the `AWAITING DEPLOY APPROVAL` verdict everywhere (report line, stop table, paced `stop: true` on the gate) (REQ-RS-REPORT-01, REQ-RS-PACED-01, REQ-RS-SAFETY-01)
- [x] 1.11 Skill §Report: mandatory sections and last line `Run-spec verdict: <VERDICT>` with the four allowed verdict forms (REQ-RS-REPORT-01)
- [x] 1.12 Skill §Paced mode: `/loop /run-spec <slug>` contract — one phase per tick, `ScheduleWakeup` semantics (`noop`, `stop`, `prompt`, `delaySeconds` guidance), Cursor monitored-shell fallback, inline degradation when no primitive (REQ-RS-PACED-01)
- [x] 1.13 Skill §Token budget + §Stop conditions: read-once, subagent report shape (6 keys, ≤ 15 lines), gate-by-grep, skip-on-satisfied-gate, no `.md` outside change folder; blocker list and git boundary (REQ-RS-TOKEN-01, REQ-RS-SAFETY-01)

- [x] 1.14 Skill §Preconditions: target project must expose the OpenSpec CLI (`openspec status`/`validate` are used by the delegated phases); missing binary → `BLOCKED (openspec CLI unavailable)` in the stop-conditions table of both skills and the Cursor rule (REQ-RS-SAFETY-01, gap G-03)

- [x] 1.17 Skill §Gate + §Confirm review: report-vs-file mismatch resolves to the **more pessimistic** value; a reviewer reporting more gaps has its findings written into `GAPS.md` before the gate is re-read, so the gate cannot pass by discarding a real finding (REQ-RS-GATE-01, REQ-RS-CONFIRM-01 — found by the end-to-end fixture test, 2026-09-09)

- [x] 1.18 Skill §Publish: never `git add -A` blindly — inspect `git status --porcelain`, stage only the change's paths, ask when the split is unclear, and record the staged file list as evidence (REQ-RS-PUBLISH-01 — found by the end-to-end fixture test, which committed `__pycache__/*.pyc`, 2026-09-09)

## 2. Template

- [x] 2.1 Create `docs/openspec/templates/RUN-LOOP-template.md` — header keys, P0–P7 table, gate block, iteration log, verdict line; short usage note including `[prod-verify]` (REQ-RS-STATE-01, REQ-RS-DOCS-01)

- [x] 2.2 Update `docs/openspec/templates/RUN-LOOP-template.md` — P7 publish / P8 deploy-gate rows, the new verdict, and a Deploy-gate block recording the developer's answer (REQ-RS-STATE-01, REQ-RS-DEPLOY-01)

## 3. Cursor parity

- [x] 3.1 Create `.cursor/commands/run-spec.md` — frontmatter `name: /run-spec`, `id: run-spec`, `category: Workflow`, `description`; same parsing and phase summary; reads `.cursor/skills/run-spec/SKILL.md` (REQ-RS-CMD-01)
- [x] 3.2 Create `.cursor/skills/run-spec/SKILL.md` — same content as Claude Code skill with `.cursor/` paths, `Task` subagents, Cursor `/loop` monitored-shell pacing (REQ-RS-CMD-01, REQ-RS-PACED-01)
- [x] 3.3 Create `.cursor/rules/run-spec-openspec-loop.mdc` — `alwaysApply: false`, `globs: openspec/changes/**/*`, triggers, phase gates, stop conditions, relation table (REQ-RS-CMD-01)

## 4. Documentation and cross-links

- [x] 4.1 Update `README.md` — contents table rows, "Recommended flow" gains a **Top layer (unattended)** block for `/run-spec` with flags, `[prod-verify]`, paced mode (REQ-RS-DOCS-01)
- [x] 4.2 Update `.claude/skills/README.md` and `.cursor/skills/README.md` — OPSX map row + "Top layer (`/run-spec`)" section (REQ-RS-DOCS-01)
- [x] 4.3 Update `docs/openspec/README.md` — commands table row + template link (REQ-RS-DOCS-01)
- [x] 4.4 Add `/run-spec` relation-table row to `.claude/commands/repasa-spec.md` and `.cursor/commands/repasa-spec.md` ("layer above; do not chain manually when running inside run-spec") (REQ-RS-DOCS-01)

- [x] 4.5 State the toolkit's own OpenSpec tree explicitly: correct the `README.md` sentence that claims no product `openspec/` tree, and record in `.gitignore` that `openspec/changes/` is versioned **in this toolkit repo** on purpose (gaps G-01, G-02)

- [x] 4.6 Update the four README files and both `repasa-spec` cross-links with the new authorization model (publish is automatic on the current branch, deploy is gated) and the five-verdict list (REQ-RS-DOCS-01)

## 5. Verification (toolkit is markdown — evidence is file inspection + a fixture dry-run)

- [x] 5.1 Structural checks: `ls` the five REQ-RS-CMD-01 paths; `grep -c 'disable-model-invocation: true'` both skills; `grep 'argument-hint' .claude/commands/run-spec.md`; `grep -l '/run-spec' README.md .claude/skills/README.md .cursor/skills/README.md docs/openspec/README.md` → 4 files (REQ-RS-CMD-01, REQ-RS-DOCS-01)
- [x] 5.2 Gate fixture dry-run in the scratch sandbox: create `openspec/changes/fixture-build/{GAPS.md,tasks.md}` with `Gaps pending (mejora + apply): 0`, one `- [ ] … [prod-verify]` and one untagged `- [ ]`; run the skill's documented `grep`/`tail` commands and record `gaps_pending=0`, `tasks_unchecked=1`, `tasks_prod_verify=1`, result `FAIL`; then check the untagged task and record `PASS` (REQ-RS-GATE-01, REQ-RS-PRODTASK-01)
- [x] 5.3 Template conformance: the skill's `RUN-LOOP.md` example and `docs/openspec/templates/RUN-LOOP-template.md` share the same header keys and P0–P7 rows (diff of key lines) (REQ-RS-STATE-01)
- [x] 5.4 Parity diff: `diff` Claude Code vs Cursor skill after normalising `.claude/`↔`.cursor/`, `Agent`↔`Task` and pacing paragraph — only expected deltas remain (REQ-RS-CMD-01)
- [x] 5.5 `openspec validate loop-skill` exit 0 in the sandbox copy (toolkit repo has no `openspec init`), and `openspec status --change loop-skill --json` → `isComplete: true` (VERIFY gate)
- [ ] 5.6 End-to-end dry-run on a real consumer project with `--no-deploy` on a trivial slug: run `/run-spec <slug> --no-deploy` and confirm `RUN-LOOP.md` shows P1–P6 rows, verdict `READY TO DEPLOY`, last chat line `Run-spec verdict: READY TO DEPLOY`, and `git log` unchanged (REQ-RS-REPORT-01, REQ-RS-SAFETY-01, REQ-RS-DEPLOY-01)
      Attempted 2026-09-08 in a sandbox consumer project (`scratchpad/consumer`): the smoke-test subagent stalled (watchdog, no progress 600 s) and was not relaunched — cost was not worth it. Run it manually: `/run-spec <slug> --no-deploy` in a real project.
- [x] 5.8 Gate-model checks: `grep` proves both skills, both commands and the Cursor rule contain the P7 publish rules, the P8 `AskUserQuestion` requirement and `AWAITING DEPLOY APPROVAL`; no file still claims the invocation is a deploy order; parity diff still shows only the expected deltas (REQ-RS-PUBLISH-01, REQ-RS-DEPLOY-01, REQ-RS-DOCS-01)
- [ ] 5.7 Deploy path on a consumer project with a `/deploy` command, first real feature: the P8 dialog appears, approving it yields verdict `DEPLOYED` with the deploy evidence line, and the only loop-made git mutation is the P7 commit + push of the current branch [prod-verify] (REQ-RS-PUBLISH-01, REQ-RS-DEPLOY-01)
