# READY TO APPLY — omniroute-llm-pool (task 6.5 only)

> **Date:** 2026-11-27, after the apply of stage 0 and of task 6.4

## Verdict

**Stage 0 is applied and its go/no-go is open: row 1 of design D15, too little data. Task 6.4 is applied. READY TO APPLY — task 6.5 only, not before 2026-11-29.** Proposal, design (D1–D18), 7 specs (102 requirements / 183 scenarios) and tasks (61: 5 done, 56 open); `openspec validate --strict` passes; 0 gaps pending. See `VERIFY.md` for the gates and the evidence map, `GAPS.md` for what the review and the apply changed, and `evidence/` for the two reports.

## What stage 0 found

- **Cache weights** (`evidence/cache-weights.md`): a cache-read token counts toward the usage limit about a fiftieth of a cache-write token (0.02, range 0 to 0.05). A soft supervisor wake of about 1.4 million raw tokens is worth about 42,000 cache-write tokens.
- **The simulator** (`evidence/what-if.md`): over seven days and nine supervisors, 941 wakes, 202 of them soft and classified. A fixed rule that sleeps every soft wake would have saved at most 5.6 % of the supervisors' flow at the central weights (7.5 % in raw tokens) and would have slept 22 wakes where the supervisor turned out to be needed, 10.9 per 100.
- **Why it does not decide yet:** one wake in three of those seven days cannot be classified, because the watcher's output lived in temporary files that a restart erased; and the hours since the watcher's back-off hold 23 soft wakes where 100 are asked for.
- **What it already shows:** the fixed rule is not safe by the threshold, whatever the unclassified wakes hide; and the saving sits on the 5 % line below which nothing is built.

## Scope of the next apply

1. Task 6.4 is done: the watcher appends the events of each wake to a file beside the supervisor's lock, and the simulator reads it.
2. Task 6.5, from 2026-11-29 (two to three days after the journal was installed): the simulator again, on a window after the back-off with at least 100 classified soft wakes; the row is recorded in `design.md`. **The apply stops there and reports.**
3. In parallel, once the developer has installed the gateway and connected a provider (task 1.2): the spike, tasks 1.1 and 1.3 to 1.6.

## Not in this apply

- Groups 2 to 5 and 7 to 9, and task 6.6 (the shadow test of a member). They wait for 6.5 and, where they talk to the gateway, for 1.2, 1.3 and 1.6.
- Installing the gateway, creating provider accounts, typing any key: the developer's.

## Decisions locked (design.md)

D1 optional module, every other piece through a provider · D2 gateway never wired into global configuration · D4 definitions, decisions and observed state in three places; limits and catalog in code · D5 five task kinds, `internal` is structured fields only · D6 promotion by the developer with judged evidence · D7 dial, schedules, `follow-usage` under a ceiling, stop as a flag · D8 two soft shapes, a journal, five bounds, explicit judging · D9 own redactor · D13 widening checked by the command · D10 a fixed order picks the member · D15 simulate first, a safe fixed rule wins, a member is tested in shadow, removal criterion · D16 caller check is scope, not security · D17 pool text is data.

## Open for the developer

- **Whether to go on at all.** The saving at stake is about 6 % of the supervisors' flow at most, and a model can only save less than the fixed rule. He may close the triage now, keep the pool for digests alone, or wait for task 6.5.
- The thresholds of D15, now that he can read the report.
- Whether "child sessions" includes sessions he opens himself in a supervised project (D16).
- Whether he has or wants a provider that neither trains on prompts nor keeps them long, or a local model: without one the digest task kinds stay closed.

## Next step

`/aplica-tarea omniroute-llm-pool`, in a new message, for task 6.5, from 2026-11-29.
