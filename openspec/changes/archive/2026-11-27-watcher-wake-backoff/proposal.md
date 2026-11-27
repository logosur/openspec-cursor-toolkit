# Proposal — watcher-wake-backoff

> **Created by:** `/prepara-tarea watcher-wake-backoff` — 2026-11-27
> **Status:** RETROACTIVE. The code was written, merged and installed on 2026-11-26 (commit `1bce327`, merge `231e4d2`) without an OpenSpec change. This change records what was built as requirements, so the behaviour has a contract, and keeps open the one thing that is not verified yet: its effect over a full day.
> **Related:** `omniroute-llm-pool` (the next step of the same goal: fewer tokens spent by supervision).

## Why

A supervisor is woken by its watcher (`supervisor-lock wait`). Every wake makes the supervisor's model re-read its whole context: a few model calls of several hundred thousand tokens each, even when the wake only says that nothing changed.

Measured on 2026-11-26 on one busy project, over 24 hours (FACT, from the supervisor's transcript):

- 68 watcher wakes, close to one million tokens each.
- 54 of the 68 carried nothing new: 35 `ALLIDLE` and 19 repeated `QUEUED` or `SLOTHELD`.

Three causes (FACT, read in the code before the change):

1. `ALLIDLE` measured quiet time from the watcher's start, so every re-arm restarted the clock and an idle project fired every 15 minutes for as long as it stayed idle.
2. `ALLIDLE` also fired while a heavy job of the project waited in the machine queue, a state `QUEUED` already reports.
3. `QUEUED` and `SLOTHELD` repeated the same job every 30 and 60 minutes.

## What Changes

- `ALLIDLE` measures quiet time from the project's last activity and keeps a persisted back-off per project: each new report of the same quiet stretch needs twice the quiet time, up to a cap. Any new activity starts again at the base threshold.
- `ALLIDLE` does not fire while a job of the project holds a slot or waits in the machine queue.
- `QUEUED` and `SLOTHELD` repeat an unchanged item every 120 minutes by default.
- Three keys in the `supervision` config piece set those intervals: `queued_reannounce_min`, `slotheld_reannounce_min` and `all_idle_backoff_max_min`. A wrong value keeps the default.
- The supervision skill's watcher reference states what a wake costs, lets an unchanged watcher double its `--timeout` up to 7200 s without passing the nearest deadline of the work in flight, and describes the new `ALLIDLE`.

## Capabilities

### New Capabilities

- `supervisor-wake-economy`: the rules that keep the watcher from waking a supervisor when nothing changed (quiet-time back-off, queue awareness, re-announce intervals, their configuration and the guidance the skill gives about wake cost).

### Modified Capabilities

None. No spec existed for the watcher.

## Impact

- Code: `global/scripts/lib/supervisor/watch.py`, `machine_queue.py`, `settings.py`, `selftest.py`; `global/config/supervision.json`; `global/skills/supervisa-sesiones/reference/vigilancia.md`; tests in `scripts/toolkit/tests/pieces/test_supervisor_lock.py`.
- State: one small file per project, `announced/<key>.allidle.json`, under the supervisor's home.
- Behaviour for a consumer: fewer wakes on an idle or queued project. No signal was removed; a quiet project is still reported, later.
- Risk: a project that is idle because something is wrong is reported later than before (worst case, the cap). The hard signals (`HUNG`, `CRASH`, `WAITING`, `GONE`…) are not touched and still wake at once.

## Non-goals

- Changing which model a supervisor runs on, or moving any supervision work to another model (see `omniroute-llm-pool`).
- Reducing the cost of a wake itself (context size, number of calls per tick).
- Touching `TIMEOUT`, `STATUS` or any other signal.
