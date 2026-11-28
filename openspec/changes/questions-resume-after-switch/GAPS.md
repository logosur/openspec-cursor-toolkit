# GAPS — questions-resume-after-switch

> **Date:** 2026-11-28
> **Mode:** A
> **Real status:** G-01 to G-07 and G-09 hydrated and applied. The independent confirm review found G-11 to G-13;
> all three are fixed.

## Methodology — 5-iteration loop (early stop allowed)

| Iter | Focus | Honest result |
|------|-------|---------------|
| 1 | Spec against `account-switch` and `ask-queue` | G-01, G-02, G-08 |
| 2 | Cases the orchestrator asks the spec to cover | G-03 to G-07 |
| 3 | Tasks against the standing rules of the run | G-09 |
| 4 | Cross-check spec, design and tasks | G-10 (not blocking) |
| 5 | Stop check | no new FACT gap; stopped |

Iterations 1 to 5 were run by the single implementer of this run (no subagents). The queue behavior in G-01 and G-02
was reproduced with synthetic queues in a temporary `HOME`.

## Consolidated matrix

Legend: **HYDRATED** | **ALREADY** | **FACT** | **INFERENCE** | **REJECTED** | **UNKNOWN**

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-01 | high | A pending row is lost when its queue file is unreadable or has a corrupt line: D3 only treats a failed command as "cannot tell" | Reproduced: `ask-queue list --json` exits 0 and silently omits the item (garbage line; `chmod 000`). `read_items` in `global/scripts/ask-queue` skips both | HYDRATED | stays-pending |
| G-02 | high | One corrupt queue file removes the questions rows of every other project | Reproduced: non UTF-8 bytes in one file make `list --json` exit 1; `list --project <other> --json` still works | HYDRATED | missing-queue |
| G-03 | medium | No requirement for the questions sessions of several projects | `spec.md` has only one-mailbox scenarios | HYDRATED | lists |
| G-04 | medium | "Listed once" is not stated: a mailbox named by two locks, or also owner or closer | `spec.md` covers only the kind of an owner also named mailbox | HYDRATED | missing-queue |
| G-05 | low | "Dismissed item" is not defined; the queue has no such status | `ask-queue` statuses are `open`, `asked`, `answered`, `closed` | HYDRATED | lists |
| G-06 | medium | Nothing states that supervisor and closing rows, their texts and their pending rule stay as they are | `spec.md` has one selection scenario only | HYDRATED | unchanged |
| G-07 | low | The gate scenario can pass with a stand-in text instead of the real one | Task 3.1 does not say which text is sent | HYDRATED | gate |
| G-08 | medium | `steps()` would put a questions row in the generic group | `normal = [x for x in event["sessions"] if x["kind"] != "watcher"]` | ALREADY | design D5, scenario "Steps with a questions session" |
| G-09 | medium | Task 5.1 runs a whole-tree `unittest discover`, which this run forbids, and omits `examples/override-full/try.sh` | `tasks.md` 5.1 | HYDRATED | tasks |
| G-10 | low | A questions session cut by the limit error is not counted as `hard` in the notice | Its row has kind `questions`; step 2 of the claim steps and step 3 of the task prompt already cover a refused send | INFERENCE | — |

## Post-apply review (round 1)

The diff was checked against every requirement and scenario of `spec.md`:

| Requirement | Evidence |
|-------------|----------|
| A switch lists the questions session | tests `-k asked_reader` and `-k questions_selection` |
| Exclusions and a missing or corrupt queue | tests `-k questions_selection` |
| Own text, `mine`, notice | tests `-k questions_steps`, `-k questions_mine`, `-k questions_notice` |
| A row stays pending | tests `-k questions_pending` |
| Supervisor and closing rows unchanged | `test_questions_steps_leave_supervisor_closer_and_cut_sessions_as_they_were`, the existing watcher tests |
| Gate accepts the text without relaxing | `-k questions` in the gate tests; the hook is not changed |

No new FACT gap. G-10 stays as a non-blocking inference.

## Independent confirm review (phase P4)

Re-derived from the spec and the code, then run end to end with synthetic state in a temporary `HOME`: real lock, real
queue, real `detect` (only its `systemd-run` launch intercepted), claim hook, message gate, ask gate and `mine`.

| ID | Sev | Gap | Evidence (FACT) | Status |
|----|-----|-----|-----------------|--------|
| G-11 | medium | The resume text asked for the ids in `metadata.source` without their form, so the ask gate's repeat backstop would not see plain ids | `ask_source_ids` in `lib/supervisor/answered.py` only reads `ask-queue:<id>,<id>` | FIXED (text, spec, design, test) |
| G-12 | medium | The text said «en un diálogo»: with more than four pending ids the rest would not be presented | A dialog holds up to four questions; the questions session's brief chains them | FIXED (same) |
| G-13 | low | An existing watchdog test had been edited without need, with a comment contradicting its own assertion | `git diff` of `test_account_switch.py` | FIXED (restored) |

G-10 re-checked: not a gap for this change. No claim or gate rule reads the kind `hard`; a refused send is covered by
step 2 of the claim steps and step 3 of the task prompt, which do not depend on the mark. Only the wording and urgency
of the desktop notice differ.

Confirmed limit, as designed: once a lock is released, its questions session is not listed as `questions`, although
the ask gate still recognises it for some days. If it was cut it gets the generic text; an open quiet dialog is left to
the queue's re-ask threshold.

## Useful casuistics (documentation, not always new REQ)

- Stale lock (heartbeat older than 24 hours): already a scenario; a 20 hour heartbeat is the positive counterpart.
- A dialog the developer dismissed without answering leaves the item `asked`: it is presented again (accepted risk in
  `design.md`).
- A row whose queue file was deleted by hand stays until it gets the resume or the event expires.

## Out of v1 (does not block APPLY)

- Dialogs lost to a reboot or an app crash; questions with no queue item.

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (spec and code done) | 8 |
| FIXED in the confirm review (G-11 to G-13) | 3 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 2 |

## Verification (this document)

- **Verified:** `openspec validate --strict` exit 0; the three queue corruption cases; the checks in `VERIFY.md`.
- **Not verified:** behavior in the real desktop app.

Gaps pending (mejora + apply): 0
