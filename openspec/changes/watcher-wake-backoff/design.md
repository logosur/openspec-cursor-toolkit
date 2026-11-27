# Design — watcher-wake-backoff

## Context

| Fact | Evidence |
|---|---|
| A wake costs the supervisor's whole context again, in 3 to 5 model calls | Supervisor transcripts, 2026-11-26: 0.6 to 1.5 million tokens per watcher wake, more than 97 % read from cache |
| Before the change, `ALLIDLE` computed `quiet = now - max(watcher start, last activity)` | `watch.py` before `1bce327` |
| Before the change, `QUEUED` and `SLOTHELD` re-announced every 30 and 60 minutes | constants in `machine_queue.py` before `1bce327` |
| The watcher exits to wake the supervisor and is re-armed by it, so any state that must survive a wake has to live on disk | `supervisor-lock wait` contract |

## Goals / Non-Goals

**Goals:**
- An idle project produces a number of `ALLIDLE` wakes that grows with the logarithm of the idle time, not linearly.
- A job that waits or holds a slot is reported at most every two hours while nothing about it changes.
- The intervals are configuration, not constants.

**Non-Goals:**
- Any change to the hard signals.
- Any model call inside the watcher.

## Decisions

### D1 — Quiet time runs from the project's last activity
`quiet = now - (now - min(idle_s over the project's sessions))`. Re-arming the watcher no longer restarts the clock. When no session reports an idle time, the recorded activity (or the watcher's start) is used.

### D2 — Back-off is exponential, persisted per project, with a cap
State in `announced/<key>.allidle.json`: `activity` (the last activity the stretch belongs to), `seen` (when the watcher first saw this stretch), `at` (last report), `count` (reports of this stretch).

- Report number `n` (from 0) needs `quiet >= min(base * 2^n, cap)`.
- The first report of a stretch also waits `base` after the watcher first saw it, so a project that was already idle for hours is not reported at the first poll.
- A later report also waits the previous threshold after the last report, so a long stretch cannot repeat at once.
- With `base = 900 s` and `cap = 7200 s` the spacing is 15 min, 15 min, 30 min, 1 h and then 2 h: about 15 reports in a fully idle day, where there were 96.
- Activity newer than the recorded one by more than 5 s starts a new stretch (`idle_s` is an integer, so the same activity reads a second apart between polls).

Alternative considered: a fixed longer interval. Rejected: it delays the first report of a project that has just gone idle, which is the one that matters.

### D3 — A blocked report is not counted
A job of the project holding a slot or waiting in the machine queue blocks `ALLIDLE`. The check runs a process, so it is asked only once the threshold is reached and its queue part is cached for 30 s. A blocked report does not advance `count` or `at`: when the job ends, the report is due at once.

### D4 — Intervals come from the `supervision` config piece
`queued_reannounce_min`, `slotheld_reannounce_min`, `all_idle_backoff_max_min`, default 120 each. A value that is not a positive finite number keeps the default; the cap is never below the base.

### D5 — The skill carries the cost model
The watcher reference tells the supervisor that the cost of a tick is the wake, and allows doubling `--timeout` after two unchanged ticks up to 7200 s, bounded by the nearest deadline of the work in flight. The first event returns it to 600 s.

## Risks / Trade-offs

- A project idle for a bad reason is reported later. Bounded by the cap and by the hard signals, which are unchanged.
- The state file can go stale if the project key changes. A missing or corrupt file starts a new stretch.

## Verification

- Unit tests of `allidle_line` and of the re-announce intervals in `test_supervisor_lock.py`; mutation of each rule makes a test fail.
- `supervisor-lock self-test` on the repo copy and on the installed copy.
- Field measurement: see `evidence/measurement.md`. The 24-hour comparison is the open task.
