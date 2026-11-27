# READY TO APPLY — omniroute-llm-pool (stage 0 only)

> **Date:** 2026-11-27

## Verdict

**READY TO APPLY — stage 0 only. NEEDS HYDRATION for the rest.** Proposal, design (D1–D18), 7 specs (97 requirements / 169 scenarios) and tasks (58, none done); `openspec validate --strict` passes; the gap review, in three rounds, left 2 gaps pending, both outside stage 0 (G-83, G-84). See `VERIFY.md` for the gates and the evidence map, and `GAPS.md` for what the review changed.

## Scope of the apply

1. Task 1.7: how the usage limit weighs cached tokens, from data that already exists.
2. Tasks 6.1 and 6.2: the simulator as one self-contained script, and its report on real wakes: for each soft one, whether the supervisor was needed, and what a fixed rule with no model would have saved and missed.
3. Task 6.3: the go/no-go for the watcher's triage, recorded in `design.md` as one of the four rows of D15: too little data; too small to bother; the fixed rule is enough; or the rule is unsafe and a model must be tested. **The apply stops here and reports.**
4. In parallel, once the developer has installed the gateway and connected a provider (task 1.2): the spike, tasks 1.1 and 1.3 to 1.6.

## Not in this apply

- Groups 2 to 5 and 7 to 9. They wait for 6.3 and, where they talk to the gateway, for 1.3 and 1.6.
- Installing the gateway, creating provider accounts, typing any key: the developer's.

## Decisions locked (design.md)

D1 optional module, every other piece through a provider · D2 gateway never wired into global configuration · D4 definitions, decisions and observed state in three places; limits and catalog in code · D5 five task kinds, `internal` is structured fields only · D6 promotion by the developer with judged evidence · D7 dial, schedules, `follow-usage` under a ceiling, stop as a flag · D8 two soft shapes, a journal, five bounds, explicit judging · D9 own redactor · D13 widening checked by the command · D10 a fixed order picks the member · D15 simulate first, a safe fixed rule wins, removal criterion · D16 caller check is scope, not security · D17 pool text is data.

## Open for the developer

- The thresholds of D15, after he reads the simulator's report.
- If the report says the fixed rule is unsafe: how a pool model is tested before the triage is built (G-83).
- Whether "child sessions" includes sessions he opens himself in a supervised project (D16).
- Whether he has or wants a provider that neither trains on prompts nor keeps them long, or a local model: without one the digest task kinds stay closed.

## Next step

`/aplica-tarea omniroute-llm-pool`, in a new message, for stage 0.
