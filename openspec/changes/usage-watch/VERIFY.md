# VERIFY — usage-watch (preparation)

> Written by `/prepara-tarea usage-watch` (phase P1 of `/run-spec`). This checks the documents before any code exists; the implementation gets its own VERIFY in task 11.2.

## Gates

| Gate | Command / check | Result |
|------|-----------------|--------|
| Artefacts present | `ls openspec/changes/usage-watch/` | `proposal.md`, `design.md`, `specs/usage-watch/spec.md`, `specs/usage-subsupervision/spec.md`, `tasks.md`, `VERIFY.md` |
| Strict validation | `openspec validate usage-watch --strict` | `Change 'usage-watch' is valid` (exit 0) |
| Spec inventory | `grep -c '^### Requirement'` / `'^#### Scenario'` | usage-watch 23 / 50; usage-subsupervision 16 / 30 |
| Requirement → task | matched by hand; tasks cite requirements by short name | 39 / 39 covered (see below) |
| Every task maps to a requirement or a risk | read of `tasks.md` | yes: 1.3, 5.4, 11.x and 12.x map to the testing strategy, the Part A gate and the field risks |
| Product files untouched | `git status --short` on the branch | only `openspec/changes/usage-watch/` |
| Privacy | `python3 scripts/privacy-check.py --require-private` | 0 findings (exit 0) |

## Requirement → task

- usage-watch: counting 2.1, 2.2, 2.4; turns 2.3; attribution 2.5; retention 2.6; configuration 1.1, 1.2; findings 3.1; the nine rules 3.2 to 3.7; status 4.1; page 4.2; write scope 5.2; timer 5.1.
- usage-subsupervision: role record 6.1; exclusion 6.2; ask and home-project routing 7.1; decide 7.2; no supervision 7.3; apply 8.1, 8.2; measure 8.3; walk 8.4; watcher 9.1; backlog 9.2; skill and rule 10.1; self-test and contract 5.3, 6.3, 9.3.

## FACT / INFERENCE / HYPOTHESIS / UNKNOWN

- **FACT:** config precedence and drift scope, override location, lock fields and helper rows, the `ask-queue` key and order options, the `acquire` exit codes, the installer's no-unit policy and the `claude-sessions-sync install` precedent, `agent-model-gate` disabled by default with its expensive-model pattern and escalation mark (files cited in `design.md`).
- **INFERENCE:** the transcript and app-record field shapes the counting relies on (observed by the prototype, not documented). Mitigated by tolerant parsing and pinned synthetic fixtures.
- **HYPOTHESIS:** default thresholds are reasonable starting points; they are configuration and marked provisional.
- **UNKNOWN:** whether the host ends a background command that runs for days. Not blocking: `wait` has `--timeout` for re-arming, and the reference text says to use it if needed.

## Open design questions closed in this phase

- Where an authorised config change is written: both the override piece and the installed piece, the latter byte-identical to the installer's rendering (D7); `drift` then reads it `in-sync` (FACT from `classify` in `drift.py`); tested in 8.2.
- Repeated questions for one config change: config proposals are machine-wide and deduplicated by piece, key and value (D6).
- Unsupervised projects and closed queue items: routed to the role's home project; `closed` leads only to `rejected` (D7).
- The apply gate is mechanical for config findings and procedural for session model and effort (D7, Risks).
- Which queue gets a machine-wide finding: the queue of the usage role's `home_project`, with a `status` warning when that project has no questions session (D8).

## Verdict

**READY TO APPLY.** Large change: Part A (tasks 1 to 5) is self-contained and gated by 5.4 before Part B starts; if the change has to be split later, that is the seam.

---

# VERIFY — usage-watch (implementation, task 11.2)

Test module: `scripts/toolkit/tests/pieces/test_usage_watch.py` (**TW**), run as
`python3 -m unittest scripts.toolkit.tests.pieces.test_usage_watch`; supervisor-lock: `test_supervisor_lock.py` (**TS**)
and its self-test (`SelfTestTest`, block «5c» of `global/scripts/lib/supervisor/selftest.py`); installer:
`test_installer.py` (**TI**). Every run is in a temporary HOME with a simulated clock.

## Requirement → code → test (usage-watch)

| Requirement | Code | Test |
|---|---|---|
| Counted per model response | `usage_watch/collect.py` | TW `CountingTest.test_main_and_subagent_usage_are_both_counted`, `FixtureSmokeTest` |
| Context size of a call | `collect.py` (`ctx`) | TW `CountingTest.test_context_size` |
| Each response counted once | `collect.py` cursors, `data.py` dedup | TW `CountingTest.test_incremental_equals_full`, `test_three_lines_of_one_response`, `test_same_response_in_two_transcripts`, `test_replaced_or_truncated_file` |
| Cache writes and advisor split | `collect.py` | TW `CountingTest.test_cache_split_and_total_only`, `test_advisor_iteration_is_a_separate_call` |
| Weighted, nothing dropped | `data.py` `price_of` | TW `WeightTest` |
| Malformed input | `collect.py` | TW `CountingTest.test_broken_line_in_the_middle`, `test_unreadable_file_is_skipped_and_counted` |
| Turn origin | `collect.py`, `data.py` | TW `TurnTest` |
| Attribution without machine names | `attribution.py` | TW `AttributionTest` |
| Supervision data only read | `attribution.py` | TW `AttributionTest.test_no_supervision_code_and_no_machine_names`, `test_without_supervision` |
| The nine rules (firing and healthy case each) | `rules.py`, `scenarios.py` | TW `RuleCasesTest` |
| Finding complete, never raised twice | `store.py` | TW `StoreTest` |
| Thresholds are configuration; nested entries | `config.py` | TW `SkeletonTest` |
| Write scope | all measuring commands | TW `WriteScopeTest` |
| Retention | `collect.py` | TW `RetentionTest` |
| Status line | `report.py` | TW `StatusTest` |
| Page | `report.py` | TW `PageTest` |
| Timer | `timer.py` | TW `TimerTest` |
| Self-test and contract (measuring half) | `selftest.py`, `contracts/usage-watch.yaml` | TW `WriteScopeTest.test_self_test_writes_nothing_in_the_home`, `ContractTest` |
| Full example installs and checks usage | `examples/override-full/` | `bash examples/override-full/try.sh` |

## Requirement → code → test (usage-subsupervision)

| Requirement | Code | Test |
|---|---|---|
| One usage role per machine | `lib/supervisor/usage_role.py`, `cli.py` | TW `UsageRoleTest.test_claim_resume_held_and_listing`, `test_stale_holder_and_takeover`; TS self-test 5c |
| Holder keeps, releases, shows it | `usage_role.py`, `lock.py` `cmd_list` | TW `UsageRoleTest.test_beat_and_release_by_the_holder_only` |
| Never a project's work | `closing.is_helper_row`, `census.open_sessions` | TW `UsageRoleTest.test_the_holder_is_never_a_project_session`; TS self-test 5c |
| Watcher wakes only for a finding or an answer | `usage_watch/watcher.py` | TW `WaitTest.test_nothing_new`, `test_new_finding_once`, `test_answer_once` |
| Watcher timeout and holder check | `watcher.py` | TW `WaitTest.test_not_the_holder`, `test_nothing_new` |
| Questions through the queue, once | `flow.ask`, `role.py` | TW `AskTest.test_supervised_project_and_empty_order`, `test_asking_twice`, `test_order_text_from_config` |
| Unpresented questions go to the home project | `flow.queue_project` | TW `AskTest.test_unsupervised_and_machine_wide_go_to_the_home_project` |
| Outcome read from the queue | `role.verdict`, `flow.decide` | TW `DecideTest` (open/asked, authorising, other answer, closed) |
| Untrusted answers | `role.verdict` | TW `DecideTest.test_the_role_holder_answering_is_not_trusted`, `test_the_asker_answering_is_not_trusted`, `test_answer_recorded_by_nobody_is_not_trusted` |
| Nothing applied without a recorded answer; the answer authorises only the change its question names (G-16) | `flow.apply`, `flow.change_text` | TW `ApplyRefusalTest` (incl. `test_a_change_edited_after_the_answer_is_refused`), `AskTest.test_supervised_project_and_empty_order` |
| Config to override and installed piece | `flow._apply_config` | TW `ConfigApplyTest` (bytes equal the installer's rendering; `drift` silent for the piece) |
| Session finding through a ticket | `flow._issue_ticket` | TW `TicketApplyTest` |
| Note records how | `flow.apply` | TW `ApplyRefusalTest.test_note_without_how` |
| Gate: the role only with a ticket | `hooks/usage-apply-gate`, `usage_watch/gate.py` | TW `TicketGateTest` |
| Gate leaves others alone, fails open | same | TW `TicketGateTest.test_another_session_is_left_alone`, `test_no_role_record`, `test_unparseable_input`, `test_an_internal_error_fails_open_and_is_logged` |
| Measured before and after | `flow.measure` | TW `MeasureTest` |
| Full walk never repeats a question | `flow.py`, `store.merge` | TW `WalkTest` |
| Hand-off to the project's supervisor | `lib/supervisor/backlog.py` `usage_items` | TW `BacklogTest`; validator (citations) |
| Without supervision the role says so | `cli._supervision`, `watcher.wait` | TW `NoSupervisionTest`, `SkeletonTest.test_role_commands_without_supervision` |
| Skill and rule describe the role generically | `reference/subsupervision-consumo.md`, `SKILL.md` row, `modelo-por-rol.md` row, `supervision.yaml` | validator, privacy check |
| Self-test and contract cover the role | `usage_watch/selftest.py` `role_checks`, `contracts/usage-apply-gate.yaml`, supervisor self-test 5c | TW `RoleSelfTestTest`, `GateContractTest`; TS `SelfTestTest` |
| Module installs its gate (task 10.2) | `modules/usage.yaml`, `settings/hooks.usage.json` | TI `DefaultModules.test_usage_module_installs_its_script_and_gate_and_is_opt_in` |

## Local gate run (task 11.1)

All exit 0, each run alone: TW (110 tests, about 1 min), TS (82 tests including `SelfTestTest`, about 5 min; self-test
floor raised by 5 for block «5c»), TI (29 tests, about 1.5 min), `scripts/test_validate_toolkit.py` (59 tests),
`scripts/validate-toolkit.py` (0 errors, 0 warnings), `examples/override-full/try.sh`, `openspec validate usage-watch
--strict`, `scripts/privacy-check.py --require-private` (0 findings), `global/scripts/usage-watch self-test` in a
throwaway HOME (33 check groups, 0 failures). The supervisor-lock self-test ran inside `SelfTestTest`'s sandbox. A
mutation that disables the untrusted-answer check makes the usage-watch self-test fail (2 failures, exit 1). Whole-tree
discover and CI are the orchestrator's, after the push.
