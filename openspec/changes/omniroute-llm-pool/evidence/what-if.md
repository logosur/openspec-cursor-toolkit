# What the supervisors' wakes cost, and what a fixed rule would save (task 6.2)

Runs of `evidence/simulate.py` on 2026-11-27, on one developer machine, over the transcripts of every session that armed a supervisor watcher. Supervisors are labelled S1 to S9; nothing here names a project, a session or a person. The cache weights are those of `cache-weights.md`.

## In short

| | Window A: 7 days | Window B: since the watcher's back-off |
|---|---|---|
| Bounds (UTC), pinned | 2026-11-20 04:00 to 2026-11-27 04:00 | 2026-11-26 20:00 to 2026-11-27 04:00 |
| Supervisor transcripts, hours observed | 9, 1,193.7 h | 7, 36.4 h |
| Wakes | 941 | 57 |
| Hard (guard / event / watcher stopped) | 644 (267 / 362 / 15) | 30 (5 / 25 / 0) |
| Soft and classified (idle to busy / timeout) | 202 (20 / 182) | 23 (2 / 21) |
| Unclassified (no output / compaction in the turn) | 95 (89 / 6) | 4 (4 / 0) |
| Unclassified share of soft plus unclassified | 32.0 % | 14.8 % |
| Soft wakes where the supervisor turned out to be needed | 22, that is 10.9 per 100 | 1, that is 4.3 per 100 |
| Wakes the fixed rule would have slept, at most | 201 | 23 |
| Its saving, raw tokens, at most | 282.6 M, 7.46 % of the flow | 38.2 M, 11.96 % of the flow |
| Its saving, central weights, at most | 5.64 % of the flow | 6.82 % of the flow |
| Row of the D15 table | **1, open: too little data** | **1, open: too little data** |

- **Neither window can decide.** Window A has enough soft wakes (202) but one in three cannot be classified. Window B is the system as it runs today, and it holds 23 soft wakes where 100 are asked for.
- **What already shows, whatever the missing wakes hide:**
  - The fixed rule is not safe by the threshold of D15 (at most 1 needed wake in 100). In window A it would have slept 22 needed wakes in 202. If every one of the 95 unclassified wakes were soft and not needed, the rate would still be 22 in 297, that is 7.4 per 100. So row 3, "the rule is enough", cannot come out of these seven days.
  - The saving sits on the threshold of row 2 (5 % of the flow) and depends on the weights: between 3.5 % and 7.5 % in window A, 5.6 % at the central weights. With cache reads counted as free it is under 5 %.
  - The soft wakes are concentrated: two supervisors hold 164 of the 201 wakes the rule would have slept.
- **Why so many wakes cannot be classified, and what it takes to fix it.** The simulator needs the watcher's output of each wake. It finds it when the supervisor read that output with a command (the result is in the transcript), or in the task's output file, which lives in a temporary directory. The machine was restarted on the night of the run and the temporary files were lost. Of the 89 wakes with no output, 38 started no turn at all (another message arrived first). In the other 51 the supervisor acted and the transcript holds no event line: in 31 of them a command did name the output file, and in the one checked it printed only the file's last two lines, which are a blank line and the exit marker, after the events (a surviving output file has that layout); in 20 no command named it. A run the same night before the restart, whose files were lost with it and which cannot be reproduced, classified 67 more wakes of about the same window: 231 classified soft wakes, 30 of them needed (13 per 100), 12.5 % unclassified. Those figures counted a wake that started no turn as soft and not needed whenever its events were known, which lowers the rate; the simulator still does so, and task 6.4 corrects it. Recording more days helps only if the watcher's output is kept somewhere that survives: see "What the next run needs".

## The fixed rule's saving under each weighting

Computed from the class totals of the two runs (a weighted cost is the sum of each class times its weight, so this equals a run with `--weights`). Weights are `fresh, cache read, cache write, output`; fresh input is too small to matter.

| Weights | Window A: saving ÷ flow | Window B: saving ÷ flow | One slept wake, in cache-write tokens (A) |
|---|---|---|---|
| Raw: every token 1 | 7.46 % | 11.96 % | 1,406,000 |
| Cache read free, output 0: `1, 0, 1, 0` | 3.52 % | 1.88 % | 11,500 |
| **Central: `1, 0.02, 1, 1`** | **5.64 %** | **6.82 %** | **42,100** |
| Upper end of the range: `1, 0.05, 1, 3` | 6.38 % | 8.84 % | 89,300 |
| Outer sensitivity: `1, 0.15, 1, 3` | 7.03 % | 10.69 % | 228,500 |
| API prices: `1, 0.1, 1.25, 5` | 6.67 % | 9.68 % | 167,200 |

These are upper bounds of the rule's saving: three of the five bounds of D8 are not in the history.

## The row of D15, read both ways

The change as merged counted a wake "whose watcher's output is nowhere to be found" as unclassified. Applying it showed 15 wakes in window A whose notice says the watcher was **stopped**, not finished: it printed no event because it never ended. None was stopped by a stop call of the supervisor in the same transcript; 5 started no turn and in 9 the supervisor ran a recovery turn. Nothing could have been triaged there, so the simulator now counts them as hard wakes, and the design says so. The row does not depend on that choice:

| Reading | Window A | Window B |
|---|---|---|
| As merged (stopped watchers unclassified) | 110 unclassified of 312, 35 %: row 1 | 4 of 27, 15 %, and 23 soft wakes: row 1 |
| As corrected (stopped watchers are hard) | 95 unclassified of 297, 32 %: row 1 | the same: there is no stopped watcher in window B |

A wake whose notice says "stopped" and whose output does hold events never occurs in these seven days outside guard mode (table of notice status against kind: 21 stopped wakes under guard, 15 outside it, none of the 15 with events). Statuses other than "completed" and "stopped" do not occur.

## The baseline task 7.4 will be compared with

Window B is the baseline, because it is the watcher as it runs today. It is **thin** (36.4 supervisor-hours, 23 soft wakes) and has to be taken again with the next run.

| Per supervisor-hour observed | Window B (baseline) | Window A (for reference) |
|---|---|---|
| Wakes | 1.57 | 0.79 |
| Soft wakes, classified | 0.63 | 0.17 |
| Main-model tokens, raw | 8.78 M | 3.17 M |
| Main-model tokens, central weights, in cache-write tokens | 0.387 M | 0.126 M |
| Share of the flow spent in soft wakes, raw / central | 12.0 % / 6.8 % | 7.5 % / 5.7 % |

"Hours observed" runs from the first to the last record of each supervisor transcript inside the window, so window A includes long idle stretches and window B is a working night; that is most of the difference between the two columns.

## What the next run needs

1. **The watcher's output kept where it survives** a restart and the cleaning of temporary files: the event lines of each wake, with the lock's owner and the times the wait started and ended, appended to a file beside the supervisor's lock. This is task 6.4 of the change (GAPS G-98). Without it, "record more days" records nothing the simulator can read later.
   - **That alone may not be enough.** A wake that started no turn stays unclassified even with its events known, because what the supervisor did for it cannot be told apart. In window A those are 38 wakes, and with the 6 compactions that is 44 of 297, about 15 %, before knowing how many of the 38 are soft. If they stay above one in ten, the share threshold of row 1 cannot be met as written, and the developer has to set it.
2. **At least 100 classified soft wakes after the back-off**, with at most one in ten unclassified. At the rate of window B that is two to three days of the same supervisors.
3. Then tasks 6.2 and 6.3 run again on that window alone.

## Limits

- "Needed" is read from what the supervisor did in the turn the wake started. A wake where it should have acted and did not counts as not needed; a wake where it acted on something that could have waited counts as needed. The rule bounds a sleep to four in a row and two hours, so a "needed" wake it sleeps is delayed, not lost; the report does not measure what a delay costs.
- Commands hidden inside quotes, scripts or wrappers are not seen by the detection of git writes and deploys.
- The rule's two figures are upper bounds, as said.
- The usage of a turn is the sum of its main-model messages; subagents and advisor sub-calls are not in it.
- A wake that started no turn and whose events are known is counted as soft and not needed, with no tokens. It adds to the classified wakes and lowers the needed rate; how many of the 202 are of that kind was not counted. *Since task 6.4 the simulator leaves such a wake unclassified ("no turn") and also reads the watcher's journal; the figures of this report were taken before that and were not run again.*
- Two definitions were set after seeing the data: a stopped watcher is a hard wake, and the central weights decide the row. The first does not change the row. The second matters only once row 1 no longer applies: at the central weights the saving is above the 5 % line, and with cache reads counted as free it is below.
- One machine, one week, and the back-off changed the mix of wakes on the last evening of it.

## Reproduce

```
python3 evidence/simulate.py --since 2026-11-20T04:00:00Z --until 2026-11-27T04:00:00Z
python3 evidence/simulate.py --since 2026-11-26T20:00:00Z --until 2026-11-27T04:00:00Z
python3 -m unittest evidence/test_simulate.py
```

A later run of the same windows gives the same wakes only while the temporary output files of that boot still exist.

---

## Appendix 1: the simulator's report, window A (raw tokens)

> WARNING: weights not set. Every token figure below is raw (fresh input, cache read, cache write and output each count as 1) and so is every share of the flow; cache tokens weigh differently on the usage limit.

### Supervisor wake simulation

The figures of rule B are UPPER BOUNDS: the deadline, the time the periodic report falls due and "something waits for the supervisor" are not in the history, so the saving can only be smaller and the needed wakes it would have slept can only be fewer.

#### Window

- Requested: since 2026-11-20T04:00:00, until 2026-11-27T04:00:00 (UTC).
- Observed records: 2026-11-20T04:01:29Z to 2026-11-27T03:58:47Z.
- Supervisor transcripts: 9, 1193.72 hours observed in total.

| Supervisor | Hours observed | Wakes | Hard | Soft idle to busy | Soft timeout | Unclassified | Slept by rule B |
|---|---|---|---|---|---|---|---|
| S1 | 167.83 | 273 | 166 | 18 | 46 | 43 | 64 |
| S2 | 167.8 | 146 | 135 | 0 | 5 | 6 | 5 |
| S3 | 167.66 | 120 | 92 | 1 | 16 | 11 | 17 |
| S4 | 162.78 | 79 | 79 | 0 | 0 | 0 | 0 |
| S5 | 164.56 | 114 | 102 | 0 | 5 | 7 | 5 |
| S6 | 100.56 | 40 | 27 | 0 | 9 | 4 | 9 |
| S7 | 130.1 | 165 | 40 | 0 | 101 | 24 | 100 |
| S8 | 129.07 | 4 | 3 | 1 | 0 | 0 | 1 |
| S9 | 3.36 | 0 | 0 | 0 | 0 | 0 | 0 |

#### Wakes by kind

Total wakes: 941.

| Kind | Wakes |
|---|---|
| hard | 644 |
| soft, idle to busy | 20 |
| soft, timeout | 182 |
| unclassified | 95 |

Hard, by reason: guard 267, event 362, watcher stopped 15.

Unclassified, by reason: compaction in turn 6, no output 89. They are left out of every rate.

#### Soft wakes: needed or not

Classified soft wakes: 202. Needed: 22. Not needed: 180.

Criterion that fired among the needed wakes (a wake can fire several): message 17, session-control 2, git-write 4, deploy 2, panel 0, question 4.

#### Cost of the wakes and the flow

Tokens of the main-model messages of each wake turn. The flow is every message of the supervisor transcripts in the window.

| Kind | Fresh input | Cache read | Cache write | Output | Raw total | Weighted |
|---|---|---|---|---|---|---|
| hard | 9,332 | 1,007,204,953 | 14,290,865 | 2,011,028 | 1,023,516,178 | weights not set |
| soft, idle to busy | 364 | 39,148,858 | 141,669 | 75,379 | 39,366,270 | weights not set |
| soft, timeout | 2,256 | 241,903,247 | 2,170,676 | 474,236 | 244,550,415 | weights not set |
| unclassified | 862 | 103,530,824 | 3,016,055 | 249,033 | 106,796,774 | weights not set |
| turns that are not wakes | 21,786 | 2,321,950,970 | 46,073,361 | 7,188,450 | 2,375,234,567 | weights not set |
| **flow** | 34,600 | 3,713,738,852 | 65,692,626 | 9,998,126 | 3,789,464,204 | weights not set |

#### Rule B: sleep every soft wake within the two bounds (upper bounds)

Bounds: at most 4 sleeps in a row and less than 2 hours since the first sleep of the stretch.

- Wakes it would have slept: 201 (20 idle to busy, 181 timeout).
- Saving, at most: 282,628,950 raw tokens, 7.46 % of the flow (raw basis).
- Needed wakes it would have slept, at most: 22 (10.95 per 100 slept). By criterion: message 17, session-control 2, git-write 4, deploy 2, panel 0, question 4.

#### Rates and decision

- Unclassified share: 31.99 % of classified soft plus unclassified wakes.
- Needed wakes: 10.89 per 100 classified soft wakes.

**Decision, row 1: open: too little data** (95 unclassified of 297, more than one in ten).

#### Calibration: tools in the not-needed soft turns

| Tool | Calls |
|---|---|
| Bash | 661 |
| mcp__*__wrap_up | 79 |
| mcp__*__update_plan | 42 |
| Agent | 12 |
| mcp__*__get_usage | 11 |
| ToolSearch | 8 |
| mcp__*__browser_batch | 6 |
| mcp__*__computer | 5 |
| mcp__*__search_threads | 5 |
| Write | 5 |

---

## Appendix 2: the simulator's report, window B (raw tokens)

> WARNING: weights not set. Every token figure below is raw (fresh input, cache read, cache write and output each count as 1) and so is every share of the flow; cache tokens weigh differently on the usage limit.

### Supervisor wake simulation

The figures of rule B are UPPER BOUNDS: the deadline, the time the periodic report falls due and "something waits for the supervisor" are not in the history, so the saving can only be smaller and the needed wakes it would have slept can only be fewer.

#### Window

- Requested: since 2026-11-26T20:00:00, until 2026-11-27T04:00:00 (UTC).
- Observed records: 2026-11-26T20:00:00Z to 2026-11-27T03:58:47Z.
- Supervisor transcripts: 7, 36.4 hours observed in total.

| Supervisor | Hours observed | Wakes | Hard | Soft idle to busy | Soft timeout | Unclassified | Slept by rule B |
|---|---|---|---|---|---|---|---|
| S1 | 7.98 | 28 | 8 | 0 | 18 | 2 | 18 |
| S2 | 7.62 | 12 | 8 | 1 | 2 | 1 | 3 |
| S3 | 5.9 | 3 | 3 | 0 | 0 | 0 | 0 |
| S4 | 3.85 | 3 | 3 | 0 | 0 | 0 | 0 |
| S5 | 4.16 | 7 | 5 | 0 | 1 | 1 | 1 |
| S6 | 3.53 | 4 | 3 | 1 | 0 | 0 | 1 |
| S7 | 3.36 | 0 | 0 | 0 | 0 | 0 | 0 |

#### Wakes by kind

Total wakes: 57.

| Kind | Wakes |
|---|---|
| hard | 30 |
| soft, idle to busy | 2 |
| soft, timeout | 21 |
| unclassified | 4 |

Hard, by reason: guard 5, event 25, watcher stopped 0.

Unclassified, by reason: no output 4. They are left out of every rate.

#### Soft wakes: needed or not

Classified soft wakes: 23. Needed: 1. Not needed: 22.

Criterion that fired among the needed wakes (a wake can fire several): message 1, session-control 0, git-write 0, deploy 1, panel 0, question 0.

#### Cost of the wakes and the flow

Tokens of the main-model messages of each wake turn. The flow is every message of the supervisor transcripts in the window.

| Kind | Fresh input | Cache read | Cache write | Output | Raw total | Weighted |
|---|---|---|---|---|---|---|
| hard | 426 | 45,531,589 | 786,181 | 79,487 | 46,397,683 | weights not set |
| soft, idle to busy | 24 | 2,903,548 | 14,215 | 7,324 | 2,925,111 | weights not set |
| soft, timeout | 298 | 35,121,391 | 114,807 | 64,056 | 35,300,552 | weights not set |
| unclassified | 4 | 165,972 | 370 | 235 | 166,581 | weights not set |
| turns that are not wakes | 2,054 | 228,145,682 | 5,976,468 | 818,857 | 234,943,061 | weights not set |
| **flow** | 2,806 | 311,868,182 | 6,892,041 | 969,959 | 319,732,988 | weights not set |

#### Rule B: sleep every soft wake within the two bounds (upper bounds)

Bounds: at most 4 sleeps in a row and less than 2 hours since the first sleep of the stretch.

- Wakes it would have slept: 23 (2 idle to busy, 21 timeout).
- Saving, at most: 38,225,663 raw tokens, 11.96 % of the flow (raw basis).
- Needed wakes it would have slept, at most: 1 (4.35 per 100 slept). By criterion: message 1, session-control 0, git-write 0, deploy 1, panel 0, question 0.

#### Rates and decision

- Unclassified share: 14.81 % of classified soft plus unclassified wakes.
- Needed wakes: 4.35 per 100 classified soft wakes.

**Decision, row 1: open: too little data** (23 classified soft wakes, fewer than 100).

#### Calibration: tools in the not-needed soft turns

| Tool | Calls |
|---|---|
| Bash | 103 |
| mcp__*__wrap_up | 20 |
| Agent | 4 |
| mcp__*__update_plan | 3 |
| Write | 2 |
| mcp__*__get_session | 2 |
| ToolSearch | 1 |
| mcp__*__get_usage | 1 |
| mcp__*__list_events | 1 |
