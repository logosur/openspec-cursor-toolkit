# Tasks — usage-watch

Requirement references: **UW** = `specs/usage-watch/spec.md`, **US** = `specs/usage-subsupervision/spec.md`. Design decisions: **D1**–**D13** in `design.md`.

Rules for every task: one goal, its own check, run before the next task starts. Tests run only in a temporary `HOME` (`python3 -m unittest scripts.toolkit.tests.pieces.test_usage_watch -k <name>`), with synthetic transcripts and `USAGE_WATCH_NOW`. Never copy figures, prices, ids, names or paths from the prototype audit script. Do not touch `global/hooks/agent-model-gate` or its config, contract and rule. The whole-tree `unittest discover` is CI's (it is not run locally); local gates run the touched test modules.

Part A (sections 1 to 5) must be complete and checked before Part B (sections 6 to 10) starts.

## Part A — measuring and detecting

### 1. Module skeleton and configuration

- [x] 1.1 Add `global/scripts/usage-watch` (argparse with every subcommand of D7, D9, D11, D12, D13 returning exit 2 "not implemented" for now) and the package `global/scripts/lib/usage_watch/__init__.py`; config read with `toolkit_config.load_checked`; `--now` / `USAGE_WATCH_NOW` clock helper, and `global/config/usage-watch.json` with every key of `design.md` § Configuration and generic provisional defaults (one `prices` entry `"."`, `order_text` empty, `weekly_budget_units` 0), with the nested checks of § Configuration (UW: thresholds are configuration; nested configuration entries; D13). Check: `--help` lists every subcommand; tests with a corrupt config, a wrong-shape value and a bad price entry get the defaults.
- [x] 1.2 Add `global/modules/usage.yaml` (`depends: [core]`, opt-in note, `timer install` note, `project_provided: [scripts/ask-queue, scripts/supervisor-lock]`, files `scripts/usage-watch` and `scripts/lib/usage_watch/`, config `[usage-watch]`) (D1), and name the module wherever modules are listed: `examples/override-full/override.yaml` and its `README.md` (count and list), the `README.md` module table and the repo `CLAUDE.md` optional-module list (UW: the full example installs and checks the usage module). Check: `python3 scripts/validate-toolkit.py` exits 0; `grep` finds `usage` in the four lists.
- [x] 1.3 Add the test module `scripts/toolkit/tests/pieces/test_usage_watch.py` with a fixture builder for main transcripts, subagent transcripts with `.meta.json`, app records, supervision locks and git repositories, all under a temporary `HOME` (Testing strategy); the builder lives in `usage_watch/fixtures.py` so that `self-test` (5.3) uses the same shapes. Check: a smoke test builds one fixture of each kind and the real home is never read (assert on the env).

### 2. Counting core

- [x] 2.1 Parse responses: usage, cache split, advisor iterations, context size, `<synthetic>` and usage-less lines skipped, malformed lines counted in `skipped_lines` (UW: counted per response; cache and advisor split; malformed input). Check: tests for each scenario of those three requirements.
- [x] 2.2 Incremental cursors and day files with last-wins dedup by message id across files and runs; re-read on inode change or shrink (UW: each response counted once; D2). Check: one-pass equals two-pass totals; three lines one id; same id in two transcripts; replaced file.
- [x] 2.3 Turn records with origin classification and the tie between main calls and their turn (UW: each turn records what started it). Check: one test per origin, including `routine` from the app record.
- [x] 2.4 Weighting with the `prices` table and `unpriced_models` (UW: weighted with the price table; D3). Check: dot-product test and unpriced-model test.
- [x] 2.5 Project and role attribution from the supervision data files, read as JSON only, with `target_app_id` on each session (UW: attributed without machine-specific names; supervision data is only read; D4). Check: worktree test, `mailbox` role test with distinct app and CLI ids, released-lock test, no-supervision test; `grep` finds no `supervisor-lock` call and no `supervisor` import in the package, and no home path or project name in the package or default config.
- [x] 2.6 Retention pruning (UW: old records are pruned). Check: 20-day records go with `retention_days` 15; findings stay.

### 3. Detection rules (each with its firing case and its healthy case)

- [x] 3.1 Findings store: id derivation, machine-wide config findings deduplicated by piece, key and value and skipped when already in effect, required fields, `flock`, corrupt store moved aside, never-repeat rule (UW: a finding is complete and never raised twice; D6). Check: run `detect` twice; one-config-proposal and value-in-effect scenarios; pre-seeded `asked` and `rejected` findings are untouched.
- [x] 3.2 `loop` rule (UW: loop rule). Check: both scenarios.
- [x] 3.3 `empty-wakes` rule (UW: empty-wakes rule). Check: both scenarios.
- [x] 3.4 `role-model` and `expensive-automation` rules (UW: role-model rule; expensive-automation rule). Check: the four scenarios.
- [x] 3.5 `expensive-subagents` and `advisor-excess` rules, proposing `agent-model-gate` `enabled` = true (UW: expensive-subagents rule; advisor-excess rule). Check: the four scenarios.
- [x] 3.6 `large-context` and `idle-rewrite` rules (UW: large-context rule; idle-rewrite rule). Check: the four scenarios.
- [x] 3.7 `pace` rule for sessions and projects, own-mean and sustainable halves (UW: pace rule). Check: the four scenarios.

### 4. Reporting

- [x] 4.1 `status` and `status --json`: week share, units, pace colour from `weekly_budget_units`, findings per state, `unpriced_models`, `skipped_lines`, home-project mailbox warning (UW: one status line; D12). Check: red-pace and no-budget scenarios; empty-home scenario prints zeros and `pace unknown`.
- [x] 4.2 `page`: static HTML with refresh meta, light and dark, phone width, no network references, labels from config (UW: a self-refreshing page). Check: content test; open the page from the temporary state directory in a browser at phone and desktop width and look at it once.
- [x] 4.3 `show ID` and `list [--project] [--state] [--applier] [--json]` (D7, D10). Check: tests on fixtures; unknown id exits 2.

### 5. Timer, contract and Part A gate

- [x] 5.1 `tick`, `timer print|install|uninstall|status` (UW: a user timer runs the measuring cycle; D11). Check: print writes nothing; install and uninstall with a fake `systemctl` on `PATH`.
- [x] 5.2 Write-scope test: a full `tick` in a temporary `HOME` changes only `state_dir` and `page_path` (UW: measuring commands write only to their state directory). Check: file-tree snapshot before and after.
- [x] 5.3 `usage-watch self-test` for counting and every rule (firing and healthy case) in its own temporary directory, `global/contracts/usage-watch.yaml` with safe probes only, and a `usage-watch self-test` step in `examples/override-full/try.sh` when the script is installed (UW: a self-test and a contract cover the measuring half; the full example installs and checks the usage module). Check: `self-test` exits 0, and exits 1 naming the rule when one threshold comparison is inverted in a scratch copy; the toolkit's contract runner passes in a temporary `HOME`.
- [x] 5.4 Part A gate: `python3 -m unittest scripts.toolkit.tests.pieces.test_usage_watch`, `python3 -m unittest scripts/test_validate_toolkit.py && python3 scripts/validate-toolkit.py`, `bash examples/override-full/try.sh`, `openspec validate usage-watch --strict`, `python3 scripts/privacy-check.py --require-private`. Check: all exit 0.

## Part B — the consumption sub-supervision

### 6. Role record in supervisor-lock

- [x] 6.1 `supervisor-lock usage-role --claim [--from ID]|--beat|--release --session ID [--dir DIR]` with `RESUMED`, `HELD` (3), `STALE` (4), the record carrying `cli_session_id`; `list --json` `usage_role` (US: one usage role per machine; the holder keeps, releases and shows the usage role; D8). Check: the five scenarios in `test_supervisor_lock.py`.
- [x] 6.2 Helper-row exclusion of the holder in `open`, `closable` and `backlog` (US: never counted as a project's work). Check: the scenario, plus the existing supervisor-lock tests unchanged.
- [x] 6.3 Self-test probes in `selftest.py` for claim, `HELD`, takeover and exclusion (US: self-test and contract). Check: `global/scripts/supervisor-lock self-test` reports no failure, and each new probe fails when the code it checks is reverted.

### 7. Question and answer flow

- [x] 7.1 `ask` through `ask-queue add` with key, `authorize_hint`, default, reason, optional order, the asker's ids, queue routing to the finding's project or the role's home project (US: questions go through the existing queue; D7). Check: ask, ask-twice, unsupervised-project and empty-order scenarios with a temporary `ASK_QUEUE_DIR`.
- [x] 7.2 The queue verdict (`pending`, `untrusted`, `authorize`, `reject`) and `decide ID` without an outcome argument (US: the outcome of a question is read from the queue; an answer recorded by the role or by nobody is not trusted; D7). Check: the six scenarios, answering through the real `ask-queue answer` with `CLAUDE_CODE_HOST_SESSION_ID` set to the questions session, to the asker and unset.
- [x] 7.3 Exit 6 for `ask`, `decide` and `wait` without supervision pieces (US: without supervision the role commands say so). Check: the scenario with only `core` and `usage` installed in a temporary `HOME`.

### 8. The single apply point and the measurement

- [x] 8.1 `apply` refusing every state but `authorized` and re-reading the queue verdict, for every kind; `--how` for `note` (US: nothing is applied without a recorded answer; a note finding records how it was applied). Check: the every-other-state scenario for a `config` and a `session-model` finding with a file-tree snapshot and an empty `tickets.json`; the hand-edited-store scenario for both kinds; the missing `--how` scenario.
- [x] 8.2 `config` kind: write override and installed piece, record previous values, refuse without override (US: a config finding is written to the override and the installed piece; D7). Check: authorised-config scenario including a run of the toolkit's `drift` in the temporary `HOME`; no-override scenario.
- [x] 8.3 `session-model` and `session-effort` kinds: ticket in `tickets.json`, exit 3 without `target_app_id` (US: a session finding is applied through a ticket; D7). Check: the ticket scenario and a no-target-id test.
- [x] 8.4 `hooks/usage-apply-gate`, `global/settings/hooks.usage.json` (listed in `usage.yaml` `hooks`), `global/contracts/usage-apply-gate.yaml` with safe probes (US: the usage role changes a session's model or effort only with a ticket; the ticket gate leaves everyone else alone and fails open; D14). Check: the five scenarios driving the hook with JSON input in a temporary `HOME`; `python3 scripts/validate-toolkit.py` exits 0.
- [x] 8.5 `measure` with `measure_window_h` (US: the effect is measured before and after). Check: too-early and measured scenarios.
- [x] 8.6 Full walk with re-detection after each step, answers recorded by a session other than the role (US: the full walk never repeats a question). Check: the scenario.

### 9. Watcher and hand-off

- [x] 9.1 `usage-watch wait` with `FINDING`, `ANSWER`, once-only announcements, `--timeout`, `NOT HOLDER` (US: the usage watcher wakes only for a new finding or an answer; the usage watcher's timeout and holder check; D9). Check: the four scenarios with a short interval and a simulated clock.
- [x] 9.2 `supervisor-lock backlog` `USAGE` lines from `usage-watch list` with fail-safe behaviour (US: work the role cannot apply goes to the project's supervisor; D10). Check: both scenarios.
- [x] 9.3 Extend `usage-watch self-test` with the walk, the refusals (untrusted answer, hand-edited store), the ticket gate and the watcher (US: self-test and contract). Check: it reports no failure, and accepting an untrusted answer in a scratch copy makes it fail.

### 10. Skill text, rule, manifests and docs

- [x] 10.1 Generic reference `global/skills/supervisa-sesiones/reference/subsupervision-consumo.md`, its row in the skill's reference table, the role row in `global/rules/modelo-por-rol.md`, the file entry and `project_provided: scripts/usage-watch` in `global/modules/supervision.yaml` (US: the supervision skill and rule describe the role generically; work the role cannot apply goes to the project's supervisor, citation scenario). Check: `python3 scripts/validate-toolkit.py` and `python3 scripts/privacy-check.py --require-private` exit 0.
- [x] 10.2 Add `usage` to an install test in `scripts/toolkit/tests/test_installer.py`, and describe the role commands and the gate hook in the `README.md` module row added in 1.2 (D1). Check: `python3 -m unittest scripts.toolkit.tests.test_installer` and `examples/override-full/try.sh` exit 0.

## Verification

- [x] 11.1 Full local gate: the touched test modules (`test_usage_watch`, `test_supervisor_lock`, `test_installer`), catalog tests and validator, `examples/override-full/try.sh`, `openspec validate usage-watch --strict`, `python3 scripts/privacy-check.py --require-private`, `global/scripts/usage-watch self-test`, `global/scripts/supervisor-lock self-test`. Check: all exit 0 (the whole-tree discover and CI are the orchestrator's, after the push).
- [x] 11.2 Write `VERIFY.md` for the implementation: requirement → code → test table, with each test run named. Check: every requirement of both specs has at least one passing test.

## Field verification (real machine, after the supervisor installs)

- [x] 12.1 After install, run `usage-watch timer install` and confirm one `tick` ran and the page and status line show real totals. [prod-verify] Evidence (field run, no figures kept here): the timer was installed with `usage-watch timer install`; `usage-watch timer status` reported both units installed; one `tick` ran through the timer with `Result=success` and exit status 0; the next run was scheduled one interval later; the status line and the page showed real totals.
- [ ] 12.2 Walk one real finding through ask, answer, apply and measure, and record the before and after figures outside this repository. [prod-verify]

## What reaches the developer: floor, grouping, live sessions and a cap (design D16)

- [x] 13.1 Materiality floor: the `minor` state, `min_saving_units_per_day` and `min_saving_share`, re-evaluation on each `detect`, `minor` kept out of the watcher, `ask`, the page rows and `list --state new`, `status` showing `minor` next to `new` (UW: a finding under the materiality floor is stored as minor). Check: `MaterialityFloorTest` (at the floor, just under it, re-evaluation, untouched states, out of sight) and the self-test floor checks.
- [x] 13.2 Grouping: session findings of one rule and project fold into one project-scoped note for the project's supervisor (routine, not live, or `group_min_sessions`), with its own proposal and undo texts and the floor applied after grouping (UW: session findings of one rule and project fold into one note). Check: `GroupingTest` with fifty one-run routine sessions, its healthy counterpart, three against two sessions, and the floor after grouping; the self-test grouping checks.
- [x] 13.3 A session-model proposal needs a live session: open in the app and active inside `session_active_window_h` (UW: a session-model proposal needs a live session). Check: `GroupingTest` closed, quiet and live sessions; the self-test live-session checks.
- [x] 13.4 Pace without duplicates with `pace_dedupe_share` (UW: one pace finding where a session is most of its project's pace). Check: `PaceDedupeTest` (not live, live, share out of reach); the self-test pace checks.
- [x] 13.5 Cap on open questions: `max_open_questions`, `FINDING` for the largest savings up to the free slots, `ANSWER` never held back, `list --state new` largest first (US: open questions are capped). Check: `OpenQuestionsCapTest` and the self-test cap checks.
- [x] 13.6 Existing state: a findings file of the previous version loads and its `new` session findings are folded or made `minor` on the next `detect`, asked ones untouched (UW: a findings file from the previous version is migrated). Check: `OldStateTest` and the self-test old-file check.
- [x] 13.7 Generic reference text of the role: what `minor` is, that grouped findings are notes for the project's supervisor, and the cap on open questions. Check: `python3 scripts/validate-toolkit.py` and `python3 scripts/privacy-check.py --range origin/main..HEAD` exit 0.
