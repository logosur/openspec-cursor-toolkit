# VERIFY — questions-session-top-level

> **Date:** 2026-11-27 · branch `feature/questions-session-top-level` @ `182c084` (no product edits yet) · written by
> `/prepara-tarea` (phase P1 of `/run-spec`). This verifies the documents against the code as it is now; nothing is
> implemented.

## Gates

| Gate | Command / check | Result |
|------|-----------------|--------|
| Artefacts present | `ls openspec/changes/questions-session-top-level/` | `proposal.md`, `design.md`, `specs/questions-session-top-level/spec.md`, `specs/supervisor-report-stamp/spec.md`, `tasks.md`, `VERIFY.md` |
| `openspec validate questions-session-top-level --strict` | OpenSpec CLI 2.1.1 | `Change 'questions-session-top-level' is valid` (exit 0) |
| `openspec status --change questions-session-top-level` | same | proposal, specs, design, tasks complete |
| Spec inventory | `grep -c '^### Requirement'` / `'^#### Scenario'` | 15 requirements / 37 scenarios (12/29 + 3/8) |
| Tasks | `grep -cE '^[[:space:]]*- \[ \]' tasks.md` | 30 open; 4 of them `[prod-verify]` (after the branch) |
| Skill lint baseline (repo copy, before any edit) | `SUPERVISOR_SKILL_FILE=$PWD/global/skills/supervisa-sesiones/SKILL.md python3 global/scripts/supervisor-lock skill-lint` | `SKILL_LINT FAIL 2` (two `ANCHOR_MISSING` lines, pre-existing); task 7.4 compares against this |
| Privacy | `python3 scripts/privacy-check.py --require-private` | 0 findings |
| Product files untouched | `git status --short` | only `openspec/changes/questions-session-top-level/` is new |

## Re-baseline (P2, on the merged base, before any product edit)

| Item | Then (P1) | Now (P2) | Evidence |
|------|-----------|----------|----------|
| Skill lint, repo copy | `SKILL_LINT FAIL 2` | `SKILL_LINT ok 0`, exit 0 | `SUPERVISOR_SKILL_FILE=$PWD/global/skills/supervisa-sesiones/SKILL.md python3 global/scripts/supervisor-lock skill-lint` in a temp HOME |
| Self-test floor | "rises" (no number) | 564 with the skill, 563 without | `scripts/toolkit/tests/pieces/test_supervisor_lock.py` `SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home` |
| Latency checks (< 0.3 s) | not referenced | `selftest.py` around lines 2127, 2542, 3410 | `grep -n "400 app records" global/scripts/lib/supervisor/selftest.py` |
| Point g | absent | added: `specs/supervisor-selftest-stability/spec.md`, design D7, tasks 10.x | orchestrator brief |
| Task 9.1 | CI as a task | removed (the orchestrator's check) | orchestrator brief |

## Requirement → code → planned test

| Requirement | Code (today) | Task / test |
|---|---|---|
| One lineage rule | none; `titles.adopt_lines` inlines a different rule | 1.1 `LineageRuleTest` |
| DETACH line for the questions role | `titles.py` `adopt_lines`, `hint_lines`; `lock.py` `rename_hint` | 2.1, 2.2 (`TitlesCommandTest`), 6.1 |
| Closing session keeps ADOPT | `titles.py` `adopt_lines` | 2.2 (closing assertions kept), 6.1 |
| Gate denies an attached questions session once | `ask_gate.py` `ask_gate_decide`, `role == 'mailbox'` exit; `deny.py` | 3.1–3.3, 6.2 |
| Gate never blocks it twice | same | 3.2, 3.3, 6.2 |
| ANSWERED for an answered queue item | none; `ask-queue` `read_items`, `answered_ts`; `cloud.announce_once` | 4.1, 4.3, 4.4, 6.3 |
| ANSWERED for a finished turn | none; `census` `turns` from `completedTurns` | 4.2–4.4 |
| One batch of answers wakes the supervisor once | none; census `status`, `live` | 4.3, 4.4 |
| ANSWERED is one guard event past exclude | `watch.py` `GUARD_EVENTS`, `visible()` | 4.3, 4.4, 6.3 |
| Skill text: lineage wording | `reference/arranque.md` «Sesiones hijas en la barra lateral», `reference/f5-decisiones.md` «La sesión de preguntas» | 7.1, 7.2, 7.4 |
| Skill text: new lines documented | `reference/vigilancia.md`, `reference/f6-f9.md`, `reference/cambios.md` | 7.3, 7.4 |
| Probes cover the change | `selftest.py` | 6.1–6.5, `SelfTestTest` |
| A report always writes the stamp | `hook.py` `hook_decide`; `guard_report.py` `report_block` | 5.1–5.3, 6.4 |
| The report block stays one per turn | same | 5.3 |
| Self-test probe for the stamp | `selftest.py` (current report checks call `report_block` directly) | 6.4 |

## Evidence map

| Claim | Class | Evidence |
|---|---|---|
| `report_block` is the last link of the `or` chain inside `if not payload.get('stop_hook_active')`, so the stamp is skipped on the retry and when an earlier link returns | FACT | `global/scripts/lib/supervisor/hook.py`, `hook_decide`, branch `if wait_armed(payload, local):` |
| The stamp is also skipped without a watcher, after a skill-changed block, and when an earlier link raises | FACT | same function: the no-watcher and skill-changed returns precede the chain; one `try` wraps the whole chain |
| The questions role gets `ADOPT` when detached today | FACT | `titles.py` `adopt_lines`; unit test `test_adopt_lists_the_helpers_that_are_not_children_of_the_supervisor` |
| The gate allows the questions session whatever its lineage | FACT | `ask_gate.py` `if role == 'mailbox'` |
| The watcher hides the questions session and `TURN` on guard | FACT | `watch.py` `visible()`, `GUARD_EVENTS`; skill `--exclude <preguntas>` |
| After a detach the former parent is not told of turn ends | FACT | description of the app tool `detach_session`, read in this session |
| A detached session's dialog does not show in its former parent's window | FACT for the supervisor (screenshot), NOT VERIFIABLE here | supervisor's brief |
| The questions role is returned for a title match even with no lock, and for a recently released lock's questions session | FACT | `session_roles.session_role`; self-test checks on the questions session |
| The app keeps `spawnedFrom` and adds `lineageDetached: true` on detach | INFERENCE | existing unit fixtures carry both fields |
| A real questions session can run `detach_session` with `"self"` | UNKNOWN | the tool's description says it is unavailable in unattended sessions and refused in some cases; task 9.4 |
| Messages to the questions session by local id still resolve after a detach | FACT | `global/hooks/cross-project-message-gate` `app_lookup`: a `local_…` name matches `sessionId` |

## Readiness

**READY TO APPLY.** Every requirement has a scenario, a planned test and a task; the one UNKNOWN (whether self-detach
works in practice) does not block, because the gate allows the retry and the supervisor can detach a session it
started; it is tracked as task 9.4. No business rule was invented: the signal name `ANSWERED`, the line `DETACH`, the
24 h window and the marker path are design choices of this change, recorded in `design.md`.

## Round 1 apply (P2): points a–e

Applied: tasks 1.1, 2.1–2.2, 3.1–3.3, 4.1–4.4, 6.1–6.3, 6.5, 7.1–7.4. Not applied (next phase): point f (5.1–5.3,
6.4, 6.6) and point g (10.1–10.5); gates 8.1–8.4 are re-run at the end of the change.

| Check | Result |
|-------|--------|
| `python3 -m unittest $T.LineageRuleTest $T.TitlesCommandTest $T.RenameHintTest $T.WatchdogTitlesTest $T.AskGateDetachOnceTest $T.AnsweredWatchTest $T.AskDueTest $T.DegradationTest $T.EntryPointTest $T.ConfigTest` | 64 tests OK, exit 0 |
| `python3 -m unittest $T.SelfTestTest` | first run: 1 FAIL, the new `ANSWERED` probe (the sandbox lock had no `--skill-seen`, so the watcher stopped at `SKILL_CHANGED`); fixed in the probe's setup; second run OK, exit 0 (floor 572/571); third run on the final code (after the owner check) OK, exit 0 |
| Mutations | `ANSWERED` removed from `GUARD_EVENTS` → the guard test fails; the busy hold disabled → the batch test fails; both restored |
| Skill lint, repo copy (temp HOME) | `SKILL_LINT ok 0`, same as the baseline |
| `python3 -m unittest scripts/test_validate_toolkit.py`, `python3 scripts/validate-toolkit.py` | OK; 0 errors, 0 warnings |
| `openspec validate questions-session-top-level --strict` | valid, exit 0 |

Self-test floor: 564/563 → 572/571 (+8: four `titles` checks, three gate checks, one `ANSWERED` check, all in section
32 of `selftest.py`).

Found and fixed during apply: a watcher left over from a former owner would have recorded the `ANSWERED`
announcements of the current owner; `ANSWERED` is now computed only while `--owner` holds the lock (unit test
`test_a_watcher_of_another_owner_does_not_use_up_the_announcement`).

## Round 2 apply (P3): point f

Applied: tasks 5.1–5.3, 6.4, 6.6. `guard_report.record_report` writes the stamp when the closing message is a report;
`hook_decide` calls it once per `Stop` of a lock owner, before the pause check and every block, whatever
`stop_hook_active` says; `report_block` keeps its place in the chain and its own early return.

| Check | Result |
|-------|--------|
| `python3 -m unittest $T.ReportStampHookTest` (5 tests through the `hook` command) | OK |
| Mutation: the `record_report` call in `hook.py` replaced by `pass` | 3 of the 5 tests fail (retry, earlier block, no watcher); restored, OK again |
| `git diff -U0 global/scripts/lib/supervisor/selftest.py` | no `report:` line changed |
| `python3 -m unittest $T.SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home` (no load) | OK, about 3 min; floor 572/571 → 574/573 (+2: section 33, two stamp probes through the hook with a child environment without `SUPERVISOR_SELFTEST_NO_REPORT`) |

## Point g — reproduction under load (task 10.1, before any probe edit)

Load: one niced CPU-bound Python loop per core, started in the background and stopped afterwards by its PIDs; the
machine was also busy with other work (load average well above the core count). Code: points a–f applied, no point g
edit yet.

| Pass | How | Failing labels | Hook output of failing Stop-hook probes |
|------|-----|----------------|------------------------------------------|
| 1 | `python3 -m unittest $T.SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home`, about 5 min | none | — |
| 2 | same, about 4 min | none | — |
| 3 | the same self-test run directly in a temp HOME to read its stdout, about 4 min | none (`ok: 0 failed`); the three latency checks measured well under the bound | — |

No red in three loaded passes. Following design D7 step 1, only what the code shows to depend on the clock, on the
duration of a pass or on state outside the sandbox is changed:

- the revive probe (and the watchdog texts next to it) formats the expected `HH:MM` at check time while the records
  carry the time they were written: a minute boundary between both turns it red;
- the three latency checks time one single run: one scheduling hiccup on a loaded machine turns them red;
- the three no-watcher Stop probes reach their block only when `wait_armed_in_proc` finds no watcher, and that
  fallback scans every process of the machine: a `supervisor-lock wait --owner local_sup` process of another self-test
  run (the self-test starts two such fake processes) makes the hook take the armed path and answer from the chain.

## Point g — fixes, mutations and the done runs (tasks 10.2–10.5)

What changed is written in `design.md` D7, «As applied». Every touched probe keeps its assertion; the bound of the
latency checks stays `< 0.3` (`grep -c "took < 0.3" global/scripts/lib/supervisor/selftest.py` = 3, as before).

Mutation runs (each a whole self-test in a temp HOME; the code restored afterwards and compared byte for byte):

| Mutation | Probes that went red |
|----------|----------------------|
| M1 `revival.stalled_text` formats the cut one minute later | `revive: its text says the truth …` |
| M3 a 0.35 s sleep at the start of `census.local_owner_of` (on all three timed paths) | the three `3 locks + 400 app records` checks (fastest of three runs well above the bound), plus `wait: HUNG …` as a side effect of the slower hook |
| M4 the sandbox filter removed from `hook.wait_armed_in_proc` | `hook: a watcher process of another self-test sandbox does not arm the owner; one of this sandbox does` |
| M2 the no-watcher reason changed («sin vigilante» → other words) | `hook: Stop with no task …`, `hook: another owner's or a finished task does not count`, `supervisor-stop-gate: passes stdin through to the hook, exit 0` (and the other checks that read that reason) |
| M5 `revival.paused_limit_text` shows a minute one off | `revive: the paused-limit text …` only |

M1, M3 and M4 ran together (they touch different outputs); M2 and M5 each ran alone.

Done runs, under the same artificial load as the reproduction (one niced CPU loop per core, stopped by PID, nothing
left afterwards per `pgrep -af`):

| Run | Result |
|-----|--------|
| First series, pass 1 and 2 (`python3 -m unittest $T.SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home`) | OK, OK |
| First series, pass 3 | **red**: `revive: the paused-limit text …` — another clock-dependent probe of the same family (`desde las {hh(7200)}` against a `paused_at` written earlier). Fixed the same way (`clock['ref']` around its block); mutation M5 above; the series restarted |
| Second series, passes 1, 2 and 3 (same command, one at a time) | OK, OK, OK (about 5 to 6 min each) |
| Simulated clock: the self-test in a temp HOME with `SUPERVISOR_SELFTEST_MINUTE_EDGE=0.5`, under load | `note: clock reference 59.5 s into its minute, check 0.7 s later (crossed a minute boundary: True)`, `ok revive: its text says the truth …`, `ok: 0 failed` |

Self-test floor: 574/573 → 575/574 (+1: section 34, the sandbox-scoped watcher probe). Total for this round: 572/571 →
575/574 (+3).

## Gates (tasks 8.1–8.4, end of round 2)

| Gate | Result |
|------|--------|
| `openspec validate questions-session-top-level --strict` | valid, exit 0 |
| `python3 -m unittest $T.LineageRuleTest $T.TitlesCommandTest $T.RenameHintTest $T.WatchdogTitlesTest $T.AskGateDetachOnceTest $T.AnsweredWatchTest $T.ReportStampHookTest $T.AskDueTest $T.DegradationTest $T.EntryPointTest $T.ConfigTest` | 69 tests OK, exit 0 |
| `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock` (whole module, self-test included, no load) | 105 tests OK, exit 0, about 5 min |
| `python3 -m unittest scripts/test_validate_toolkit.py`; `python3 scripts/validate-toolkit.py` | OK; 0 errors, 0 warnings |
| `bash examples/override-full/try.sh` | every step passed, exit 0 |
| `python3 scripts/privacy-check.py --require-private` | 0 findings, exit 0 |
