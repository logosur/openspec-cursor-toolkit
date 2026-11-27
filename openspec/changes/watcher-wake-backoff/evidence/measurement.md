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
