# Tasks — watcher-wake-backoff

Requirement references: **WE** = `specs/supervisor-wake-economy/spec.md`. Design decisions: **D1**–**D5** in `design.md`.

Tasks 1 to 3 were done on 2026-11-26, before this change existed (commit `1bce327`, merge `231e4d2`). They are recorded here with the evidence that was produced then. Task 4 is open.

## 1. Watcher rules

- [x] 1.1 `ALLIDLE` from the project's last activity with a persisted exponential back-off (WE: quiet time from last activity; backs off; activity starts a new stretch; state survives the watcher; D1, D2). Done: `allidle_line` in `global/scripts/lib/supervisor/watch.py`.
- [x] 1.2 `ALLIDLE` silent while a job of the project holds a slot or waits in the queue, without advancing the back-off (WE: silent while queued; D3). Done: `project_job_queued` in `machine_queue.py`, cached 30 s in the watcher.
- [x] 1.3 Re-announce intervals of `QUEUED` and `SLOTHELD` from configuration (WE: re-announced at a configured interval). Done: `machine_queue.py` reads `settings`.

## 2. Configuration and skill

- [x] 2.1 Keys `queued_reannounce_min`, `slotheld_reannounce_min`, `all_idle_backoff_max_min` in `global/config/supervision.json` and `settings.py`, with the default kept on a wrong value (WE: intervals are configuration; D4).
- [x] 2.2 Watcher reference of the supervision skill: cost of a wake, `--timeout` doubling up to 7200 s bounded by the work in flight, new `ALLIDLE` (WE: the skill states the cost of a wake; D5).

## 3. Verification done on 2026-11-26

- [x] 3.1 Unit tests for every rule in `scripts/toolkit/tests/pieces/test_supervisor_lock.py`. Evidence: full suite 741 tests passing with the real home and 741 with an empty home that stays empty.
- [x] 3.2 Five mutations of the rules each make a test fail.
- [x] 3.3 `supervisor-lock self-test`: 633 ok, 0 failed, on the repo copy and on the installed copy.
- [x] 3.4 `examples/override-full/try.sh`, `validate-toolkit` and the privacy check exit 0; CI green on the branch and the pull request.
- [x] 3.5 Installed; the installed config reads 120, 120 and 120; `skill-lint` ok.

## 4. Field verification (open)

- [x] 4.1 First comparison, 4 h before against 3 h after, on three live supervisors. Evidence: `evidence/measurement.md`. Result: the targeted notices fell from 3.0 to 1.0 per hour; `QUEUED` repeats exactly every 2 h.
- [ ] 4.2 24-hour comparison of watcher wakes and their tokens, per signal, against the 24 hours before the change, on the same supervisors. Accept when `ALLIDLE` has at least 10 samples on each side or the report says why it cannot. Add the result to `evidence/measurement.md`.
- [ ] 4.3 Decide from 4.2 whether the `ALLIDLE` cap or base needs another value, and record the decision in `design.md`.
- [ ] 4.4 Archive the change (`/archiva-tarea watcher-wake-backoff`) so `supervisor-wake-economy` becomes a spec under `openspec/specs/`.
