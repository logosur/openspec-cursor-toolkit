# Field measurement — first comparison (2026-11-27)

## Method

- Source: the main transcript of three supervisors that were alive in both windows (A, B and C; project names are kept out of the repository).
- A watcher wake is a task notification of the supervisor's own `supervisor-lock wait` background command. Its cost is the token usage of every model call of the turn it starts, until the next message that is not a tool result. Tokens are input, cache read, cache creation and output added together; more than 97 % are cache reads.
- The signal of each wake is the first line of the watcher's output.
- Before: the 4 hours up to the installation. After: the 3.07 hours from the installation until the supervisors' processes stopped for an unrelated reason. Everything is per hour.

## Result

| Per hour | Before | After |
|---|---|---|
| Targeted notices (`ALLIDLE`, `QUEUED`, `SLOTHELD`) | 3.0 (12 in 4 h) | 1.0 (3 in 3.07 h) |
| Tokens of the targeted notices | 2.5 M | 0.8 M |
| All watcher wakes | 6.5 (26) | 5.5 (17) |
| Tokens of all watcher wakes | 6.7 M | 5.3 M |
| Tokens of every turn of the three supervisors | 13.7 M | 15.8 M |

- Supervisor A had jobs waiting in the machine queue through both windows. `QUEUED` fired every 30 minutes before (7 times) and exactly every 2 hours after (three consecutive reports, 2 h 00 min and 2 h 01 min apart). `SLOTHELD` fired every hour before (4 times) and every 2 hours after.
- The total did not fall. The saving, about 1.7 M tokens per hour, is 12 % of the previous flow and is hidden by the variation of the work itself.

## Limits

- A before/after with few samples (12 and 3), not an experiment.
- `ALLIDLE` cannot be judged: one sample on each side, on supervisor C only. It was the most frequent notice in the 24-hour measurement that motivated the change (35 of 68 wakes), so the larger part of the expected saving is still unmeasured. Task 4.2 covers it.
- For `SLOTHELD`, it is not known whether a slot was held during the first hour and a half of the second window.
- Only main transcripts are counted, not subagents. Cache-read tokens do not weigh the same as fresh input in cost or in usage limits.
- Two other supervisors had no activity in the first window and are left out.

# Field measurement — 24-hour comparison (task 4.2, 2026-11-27)

## Method

Same counting as the first comparison, with two windows of 24 hours: the 24 hours up to the installation of the change and the 24 hours from it. The installation instant is the one at which the changed watcher files were written on the machine. A watcher that was already running kept the old code until it exited, which delays the effect by at most one watcher run.

- Supervisors: the four whose main transcript has watcher wakes in both windows (S1 to S4). The letters of the first comparison are not reused: its supervisor A is S2 here and its supervisor C is S3. Supervisors that had no watcher wake in one of the windows are left out.
- A wake is the task notification of a background `supervisor-lock wait` command, matched to the command by its tool-use id. Its cost is the token usage of every model call of the turn it starts (input, cache read, cache creation and output, counted once per message), until the next message that is not a tool result. Main transcripts only.
- The signal is the first all-capital word of the watcher output that the supervisor read in that turn. 18 wakes (1.2 M tokens) have no readable signal and are counted only in the totals.
- Armed time is estimated from the arm commands and the wakes, with an unfinished run capped at its `--timeout`.

## Two cuts in the "after" window

- An account switch about 3.6 hours after the installation and a machine restart about 19 hours after it stopped the supervisors' processes and their watchers.
- All four supervisors armed a new watcher within about 6 minutes of the account switch and within about 2 minutes of the restart (the instants of the two cuts are approximate). The back-off state lives on disk, so a stretch of idle time continued across both cuts. The cuts therefore do not explain the number of `ALLIDLE` samples below, and both windows hold a full 24 hours.
- Estimated armed time: 66.6 hours before and 87.4 hours after, summed over the four supervisors (96 hours possible). The supervisors were armed less before, so rates per clock hour overstate the "after" flow by about a third compared with rates per armed hour; both are given.

## Result (four supervisors, 24 hours each)

| Wakes and tokens | Before | After |
|---|---|---|
| `ALLIDLE` | 20 wakes, 27.5 M | 6 wakes, 5.8 M |
| `ALLIDLE` mean tokens per wake | 1.37 M | 0.96 M |
| `ALLIDLE` per armed hour | 0.30 | 0.07 |
| `QUEUED` and `SLOTHELD` repeating a job already announced | 14 wakes, 15.2 M | 6 wakes, 6.1 M |
| `QUEUED` and `SLOTHELD` announcing a job for the first time | 10 wakes, 9.5 M | 39 wakes, 42.8 M |
| `TIMEOUT` | 42 wakes, 53.8 M | 96 wakes, 129.9 M |
| Every other signal | 51 wakes, 49.7 M | 42 wakes, 42.6 M |
| All watcher wakes | 137 wakes, 155.7 M | 189 wakes, 227.3 M |
| All watcher wakes, without S1 | 97 wakes, 111.7 M | 92 wakes, 96.3 M |
| All watcher wakes per armed hour | 2.06 | 2.16 |

- Repeats of one job: the median spacing of a `QUEUED` repeat went from 31 minutes (11 repeats) to 120 minutes (5 repeats), and that of a `SLOTHELD` repeat from 60 minutes (3) to 121 minutes (1). The spacing never fell below the configured interval. These repeats are the notices the change targets: 14 wakes and 15.2 M tokens became 6 wakes and 6.1 M.
- `ALLIDLE` per supervisor, before then after: S2 19 then 3, S3 1 then 2, S4 0 then 1, S1 0 then 0. The fall rests on S2. Its reports before came mostly 15 to 19 minutes apart; after, they came 69 and 50 minutes apart, with quiet times of 5.9, 7.1 and 7.9 hours, and S3's two came 120 minutes apart at a quiet time of 2.0 and 4.0 hours.
- The total did not fall. Two things not touched by this change explain it:
  - S1 armed its watcher 84 times with `--timeout 300` in the "after" window and never before (it used 1500 to 1800 seconds). Its `TIMEOUT` wakes went from 33 to 82, 63 of them within 6 minutes of arming. S1 alone added 57 wakes and 87 M tokens; the other three supervisors together fell by 5 wakes (5 %) and 15 M tokens (14 %).
  - The first announcements of a job in the machine queue grew from 10 to 39 because the supervisors used the queue more in the second window. They are new information, not repeats.

## Why `ALLIDLE` has 6 samples after and not 10

The acceptance asked for 10 on each side. The "before" side has 20; the "after" side has 6, and the report cannot reach 10 on this data, for these reasons:

- By design, one supervisor needs about 14 hours of unbroken idle time with no job of its project in the queue to produce 10 reports (quiet times of 0.25, 0.5, 1, 2, 4, 6, 8, 10, 12 and 14 hours). A fully idle day gives about 15.
- The four supervisors were not idle for that long. S1 woke every 5 to 30 minutes with work in flight. S2 and S3 had jobs waiting in the machine queue repeatedly (33 and 8 queue notices), and a queued job keeps `ALLIDLE` silent by design (D3). S2's first report came after a quiet time that had already lasted 5.9 hours, and its next two followed at 69 and 50 minutes. This is consistent with the rule "a blocked report is not counted": the first report became due when the queue emptied, and the next ones followed at the escalating spacing. The transcripts do not show the queue state during those hours, so this is an inference.
- The cuts did not remove samples (see above).

## Limits

- One day on each side, four supervisors, a different load in the second day: a before/after, not an experiment. The comparison of `ALLIDLE` has 20 and 6 samples, and the three of S2 show the escalation but not the cap spacing in a long unblocked stretch; only S3's two reports (120 minutes apart) show the cap.
- The first announcements of queued jobs and S1's short timeouts change between the windows for reasons that are not the change under test, so the total flow cannot be read as its effect.
- Cache-read tokens (more than 97 % of the total) do not weigh the same as fresh input in cost or in usage limits.
- Main transcripts only. Wakes of a supervisor that had no wake in one of the windows are not included.
- The "idle" reading of a stretch comes from the quiet time that `ALLIDLE` prints. Between reports the idle time of a project is not observed.
