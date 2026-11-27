# VERIFY — watcher-wake-backoff

> **Date:** 2026-11-27 · `main` @ `95991f4` (the code this change describes was merged in `231e4d2`) · written by `/prepara-tarea`, retroactively.
> This change documents code that is already merged, so VERIFY checks the documents against that code instead of against a plan.

## Gates

| Gate | Command / check | Result |
|------|-----------------|--------|
| Artefacts present | `ls openspec/changes/watcher-wake-backoff/` | `proposal.md`, `design.md`, `specs/supervisor-wake-economy/spec.md`, `tasks.md`, `evidence/measurement.md`, `VERIFY.md` |
| `openspec validate watcher-wake-backoff --strict` | OpenSpec CLI 2.1.1 | `Change 'watcher-wake-backoff' is valid` |
| `openspec status --change watcher-wake-backoff --json` | same | complete; proposal, specs, design and tasks `done` |
| Spec inventory | `grep -c '^### Requirement'` / `'^#### Scenario'` | 8 requirements / 15 scenarios |
| Requirement → test | table below | 8 / 8 have at least one test in the repository |
| Requirement → task | each requirement matched by hand to the task that cites it (tasks use short names, not full titles) | 8 / 8: task 1.1 covers the first four, 1.2 the queue silence, 1.3 the re-announce interval, 2.1 the configuration, 2.2 the skill |
| Tasks | `grep -c` on `tasks.md` | 11 done (with evidence), 3 open (4.2, 4.3, 4.4) |
| Product files untouched by this change | `git diff --stat origin/main -- . ':!openspec'` on the branch, with `main` at `95991f4` merged in | empty |
| Privacy | `scripts/privacy-check.py --staged --require-private` | 0 findings |

## Requirement → code → test

Tests are in `scripts/toolkit/tests/pieces/test_supervisor_lock.py` unless another file is named. The 18 tests named below were re-run for this document on 2026-11-27 (`python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock -k AllIdleBackoffTest -k QueuedJobSuppressesAllIdleTest -k ReannounceIntervalTest -k test_the_watcher_intervals_are_read`), on the tree with `main` at `95991f4` merged in: 18 passed. The full suite and the self-test were not re-run for this document; the supervisor code and its tests have changed on `main` since they last ran for this change, so their earlier figures are not repeated here.

| Requirement | Code | Tests |
|---|---|---|
| ALLIDLE measures quiet time from the project's last activity | `watch.py` `allidle_line` (`activity = now - min(idles)`); `--guard` skips it at `watch.py:388`; default `--all-idle-after 900` in `cli.py:101` | `test_re_arming_does_not_restart_the_quiet_clock`, `test_re_arming_before_the_first_report_does_not_restart_the_clock_either`, `test_a_busy_session_or_a_zero_threshold_reports_nothing`, `test_without_sessions_the_clock_runs_from_the_first_wait_and_survives_re_arming`; self-test check "wait without --guard: no IDLE" |
| ALLIDLE backs off while nothing moves | `allidle_line` (`need = min(base * 2 ** count, cap)`, `previous`, `seen`) | `test_the_first_report_comes_at_the_threshold_and_the_next_ones_double_up_to_the_cap`, `test_a_stretch_already_long_at_the_first_look_is_reported_after_the_threshold_and_does_not_repeat_at_once`; three self-test checks in `selftest.py` |
| Activity starts a new stretch | `allidle_line` (`ALLIDLE_ACTIVITY_TOLERANCE_S = 5`) | `test_any_activity_resets_the_back_off` |
| Back-off state survives the watcher | `allidle_path` → `announced/<key>.allidle.json` | `test_the_state_is_per_project_and_lives_under_announced`, `test_a_corrupt_state_file_starts_over` |
| ALLIDLE is silent while the project has a job in the machine queue | `machine_queue.project_job_queued`; `blocked()` in `allidle_line`; 30 s cache in `wait_events` | `test_a_job_of_the_project_waiting_in_the_machine_queue_holds_ALLIDLE_back`, `test_a_blocked_report_is_not_recorded_so_it_fires_as_soon_as_it_is_unblocked`, `test_without_a_readable_heavy_job_the_watcher_behaves_as_before`, `test_project_job_queued_is_a_plain_yes_or_no` |
| Unchanged queue items are re-announced at a configured interval | `machine_queue.py` `QUEUED_REANNOUNCE_S`, `SLOTHELD_REANNOUNCE_S` | `test_an_unchanged_item_is_announced_first_and_again_after_the_default_two_hours`, `test_the_configured_intervals_apply_to_each_kind` |
| Intervals are configuration with safe defaults | `settings.py` `_positive`; `global/config/supervision.json` | `test_the_watcher_intervals_are_read_and_a_wrong_value_keeps_the_default`, `test_a_wrong_interval_keeps_the_default`, `test_the_cap_never_goes_below_the_base_threshold` |
| The skill states the cost of a wake | `global/skills/supervisa-sesiones/reference/vigilancia.md`, the paragraph after the tick steps | No automated test of the wording. Checked by reading: the paragraph names 7200 s, the deadline rule and the three keys |

## Evidence map

| Claim | Class | Evidence |
|-------|-------|----------|
| The code was merged without an OpenSpec change | FACT | `git show --stat 1bce327` touches no path under `openspec/` |
| 68 watcher wakes in 24 h on one supervisor, 54 with nothing new | FACT, not reproducible from the repository | Counted on 2026-11-26 from that supervisor's transcript by the session that wrote the code |
| Spacing with the defaults is 15 min, 15 min, 30 min, 1 h, then 2 h | FACT | Derived from `need` and `previous` in `allidle_line` with base 900 and cap 7200 |
| `QUEUED` first fires after 20 min of waiting, `SLOTHELD` after 60 min while others queue | FACT | `QUEUED_AFTER_S`, `SLOTHELD_AFTER_S` in `machine_queue.py` |
| Targeted notices fell from 3.0 to 1.0 per hour | FACT, small sample | `evidence/measurement.md` |
| `ALLIDLE` back-off reduces wakes in the field | HYPOTHESIS | One sample on each side; task 4.2 |
| The base or the cap need other values | UNKNOWN | Task 4.3, after 4.2 |

## Honest limits

- The wording requirement has no automated test; `skill-lint` does not check that paragraph.
- Only the 18 tests of this change were re-run, not the full suite or the self-test.
- The field effect of `ALLIDLE`, the notice that motivated the change, is not measured yet.

## Verification status

**READY TO APPLY** — for the open tasks only (4.2 measurement, 4.3 decision, 4.4 archive). Tasks 1 to 3 are already applied and match the requirements.
