# Tasks — questions-session-top-level

Requirement references: **QS** = `specs/questions-session-top-level/spec.md`, **RS** =
`specs/supervisor-report-stamp/spec.md`, **SS** = `specs/supervisor-selftest-stability/spec.md`. Design decisions
**D1**–**D7** in `design.md`. Points of the proposal: a = section 2, b = 3, c = 4, d = 6.1–6.3 and 6.5, e = 7, f = 5,
6.4 and 6.6, g = 10.
One implementer, in this order; each task has its own check, run before the next task starts. All commands are light
(a single test class or id); never wrap them in `heavy-job`, never run the self-test against the real HOME.
`T=scripts.toolkit.tests.pieces.test_supervisor_lock`.

## 1. Lineage rule (QS: one lineage rule; D1)

- [x] 1.1 Add `hangs_from(record)` and `app_record_of_cli(cli_session_id)` to `global/scripts/lib/supervisor/session_roles.py` (never raise). Check: a new unit test class `LineageRuleTest` covering the D1 truth table passes (`python3 -m unittest $T.LineageRuleTest`); `python3 -m py_compile global/scripts/lib/supervisor/session_roles.py` exits 0.

## 2. DETACH for the questions role (QS: DETACH line; closing keeps ADOPT; D2)

- [x] 2.1 `titles.py`: `adopt_lines` only for the closing role; new `detach_lines`; `hint_lines` returns rename + adopt + detach; update the module and `lock.py` `rename_hint` docstrings. Check: `python3 -m py_compile global/scripts/lib/supervisor/titles.py global/scripts/lib/supervisor/lock.py` exits 0.
- [x] 2.2 Update the three existing tests that assert `ADOPT` for the questions role (`test_adopt_lists_the_helpers_that_are_not_children_of_the_supervisor`, `test_adopt_prints_nothing_without_a_record_or_without_the_fields`, `test_beat_shows_the_adopt_lines_too`) to the new contract, keeping every closing-role assertion as it is; add tests for each QS DETACH scenario (owner parent, other parent, detached, no parent, `beat` stderr). Check: `python3 -m unittest $T.TitlesCommandTest` passes.

## 3. Ask gate deny-once (QS: the ask gate denies once, then allows; D3)

- [x] 3.1 `deny.py`: `deny_attached_mailbox(parent)` (Spanish, one line, names the parent, `detach_session`, `"self"`, retry the same question, the retry passes). Check: `python3 -m py_compile global/scripts/lib/supervisor/deny.py` exits 0.
- [x] 3.2 `ask_gate.py`: lineage check at the `role == 'mailbox'` exit only, marker under `ask_gate_dir()/detach-asked/`, decision-log entries `deny-mailbox-attached` / `allow-mailbox-attached`, fail open on any error; applies to every `role == 'mailbox'` (title match without a lock included). Check: `python3 -m py_compile global/scripts/lib/supervisor/ask_gate.py` exits 0.
- [x] 3.3 Unit tests through the `hook` command with synthetic PreToolUse payloads, CLI and app records and a live lock: first attempt denied (fragments asserted), retry allowed, detached allowed with `allow-mailbox`, title match without a live lock denied once then allowed, no record allowed, a corrupt (non-JSON) app record allowed, an empty or corrupt marker counts as already denied, a marker older than 30 days pruned on the next write, unwritable marker allowed, a supervised session unchanged. Check: `python3 -m unittest $T.<new class>` passes.

## 4. ANSWERED watcher event (QS: the watcher wakes the supervisor; D4)

- [x] 4.1 New module for `ANSWERED`: queue trigger (path resolved once per wait, 24 h window, `announce_once` with the 48 h history). Check: a unit test on the queue function alone (answered, old, unparsable, repeated) passes.
- [x] 4.2 Same module: turn trigger with `<home>/announced/<key>.questions-turns.json` (first sight, new id, lower count, corrupt file, higher count). Check: a unit test on the turn function alone passes.
- [x] 4.3 `watch.py`: call both every poll with `--owner`, from the unfiltered rows, one combined line per poll, the queue trigger held while the registered questions session is live and busy (up to 600 s), skip while paused, errors to `wait-errors.log`; add `ANSWERED` to `GUARD_EVENTS`. Check: `python3 -m py_compile` on the new module and `watch.py` exits 0, and `grep -n "'ANSWERED'" global/scripts/lib/supervisor/watch.py` finds it in `GUARD_EVENTS`.
- [x] 4.4 Unit tests through `wait --owner … --guard --exclude <questions> --interval 0.2` with `SUPERVISOR_WAIT_READY` and a temp queue (`ASK_QUEUE_BIN`): answer on guard, a second guard wait right after prints no `ANSWERED` for the same id, turn on guard, a second wait at the same count prints nothing, turn ended between waits, both in one poll (one line), answers in two polls then the turn (one line), busy past 600 s (line without the turn), no registered questions session, first sight silent, `TURN`/`STATUS` for the excluded session still hidden. Check: `python3 -m unittest $T.<new class>` passes.

## 5. Report stamp (RS: a report always writes the stamp; the block stays one per turn; D5)

- [x] 5.1 `guard_report.py`: `record_report(owner, payload, session, now=None)`; `report_block` uses it for its own stamp. Check: `python3 -m py_compile global/scripts/lib/supervisor/guard_report.py` exits 0 and the existing `report:` self-test lines are unchanged (`git diff -U0 global/scripts/lib/supervisor/selftest.py` shows none of them).
- [x] 5.2 `hook.py`: call `record_report` once per `Stop` of a lock owner, right after `owner = locks[local]`, in its own `try`, whatever `stop_hook_active` says. Check: `python3 -m py_compile global/scripts/lib/supervisor/hook.py` exits 0.
- [x] 5.3 Unit tests through the `hook` command: retry with `stop_hook_active: true` stamps and prints nothing; an earlier block (English closing report) is returned and stamps; no watcher armed returns the no-watcher block and stamps; a short message does not stamp; the report block is still returned once on a due normal stop. Check: `python3 -m unittest $T.<new class>` passes.

## 6. Self-test probes (QS: probes; RS: self-test probe)

- [x] 6.1 `selftest.py`: checks for `DETACH` (owner parent, other parent, detached) and the closing role's unchanged `ADOPT`, next to the existing title checks.
- [x] 6.2 `selftest.py`: checks for the gate (deny once with the fragments, then allow; detached allowed), next to the questions-session checks of section 11b.
- [x] 6.3 `selftest.py`: a check for `ANSWERED` on guard with the questions session in `--exclude`.
- [x] 6.4 `selftest.py`: two checks through `hook` for the stamp (`stop_hook_active: true`; an earlier block), running the hook subprocess with a child environment that does not carry `SUPERVISOR_SELFTEST_NO_REPORT` (popping it in-process is not enough: the self-test sets it in `os.environ`).
- [x] 6.5 Put the checks of 6.1–6.3 in one self-contained block and raise the minimum `ok` count in `SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home` from 564/563 by exactly the number of checks that block adds. Check for 6.1–6.3 and 6.5: `python3 -m unittest $T.SelfTestTest` passes (light, about 6 min, temp HOME).
- [x] 6.6 Raise the floor again by exactly the number of checks added in 6.4. Check: `python3 -m unittest $T.SelfTestTest` passes.

## 7. Skill text in this repo (QS: shipped skill text; D6)

- [x] 7.1 `global/skills/supervisa-sesiones/reference/arranque.md`, «Sesiones hijas en la barra lateral»: questions session at the top level, what to do on `DETACH`, `ADOPT` only for the closing session.
- [x] 7.2 `reference/f5-decisiones.md`, «La sesión de preguntas»: detach after opening and registering (or leave it to the gate), one sentence in the brief, item 5 woken by `ANSWERED`.
- [x] 7.3 `reference/vigilancia.md` (wake sources, signals table, guard list) and `reference/f6-f9.md` (guard watcher still gets `ANSWERED`).
- [x] 7.4 `reference/cambios.md`: new top entry for this change. Check for 7.1–7.4: `grep -rn "deben colgar de ti" global/skills/supervisa-sesiones` shows no sentence that includes the questions session; `grep -c "ANSWERED" global/skills/supervisa-sesiones/reference/vigilancia.md` ≥ 2; `SUPERVISOR_SKILL_FILE=$PWD/global/skills/supervisa-sesiones/SKILL.md python3 global/scripts/supervisor-lock skill-lint` (temp HOME) still reports `SKILL_LINT ok 0`, the baseline re-measured in P2 on the merged base before any edit (see `VERIFY.md`).

## 8. Gates on this machine

- [x] 8.1 `openspec validate questions-session-top-level --strict` exits 0.
- [x] 8.2 Touched unit classes by id, plus `RenameHintTest`, `AskDueTest`, `DegradationTest`, `EntryPointTest`, `ConfigTest`: all pass.
- [x] 8.3 `python3 -m unittest scripts/test_validate_toolkit.py && python3 scripts/validate-toolkit.py` exits 0.
- [x] 8.4 `python3 scripts/privacy-check.py --require-private` reports 0 findings on the tree (no personal data, no private quotes in `design.md`'s override table).

## 9. After this branch (not done by the implementer)

CI on the pushed branch is the orchestrator's check, not a task of this change.

- [ ] 9.2 Install, then every live supervisor reloads the skill (`reference/cambios.md` entry). [prod-verify]
- [ ] 9.3 The override maintainer updates the installed phrases listed in `design.md`, «Notes for the override maintainer». [prod-verify]
- [ ] 9.4 Observe once whether a real questions session can run `detach_session` with `"self"` (UNKNOWN in `design.md`); record the result in the change. [prod-verify]

## 10. Self-test stable under load (SS; D7)

- [x] 10.1 Reproduce: run the self-test in a temp HOME under artificial CPU load (`nice` plus CPU-bound loops, stopped by PID) until it goes red or three passes are done; record each pass's failing labels and the hook output of each failing Stop-hook probe in `VERIFY.md`, before editing any probe. Check: `VERIFY.md` has the section.
- [x] 10.2 Revive probe: expectation from the same instant the code used (or fixed synthetic ages) and a test-supplied reference time; mutation (time one minute off) still fails. Check: the probe passes with the reference time half a second before a minute boundary.
- [x] 10.3 The three chained Stop-block probes isolate the block they test; mutation (no-watcher reason changed) still fails. Check: they pass in a loaded self-test pass.
- [x] 10.4 The three `< 0.3` s latency checks keep their bound; any measure change written in `design.md` D7; mutation (a delay over the bound on the timed path) turns each red, recorded in `VERIFY.md`. Check: `grep -c "took < 0.3" global/scripts/lib/supervisor/selftest.py` is unchanged and the mutation runs are recorded.
- [x] 10.5 Done: three consecutive green self-test passes under artificial load and one with the simulated clock crossing a minute boundary, recorded in `VERIFY.md`; the floor changes only by checks added in 10.x, if any.
