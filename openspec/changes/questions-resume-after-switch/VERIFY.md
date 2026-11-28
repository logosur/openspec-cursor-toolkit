# VERIFY — questions-resume-after-switch

> Branch `feature/questions-resume-after-switch` @ `6794491`, written by `/prepara-tarea` (phase P1 of `/run-spec`).
> This verifies the documents against the code as it is now; nothing is implemented.

## Gates

| Gate | Command / check | Result |
|------|-----------------|--------|
| Artefacts present | `ls openspec/changes/questions-resume-after-switch/` | `proposal.md`, `design.md`, `specs/account-switch-questions-resume/spec.md`, `tasks.md`, `VERIFY.md` |
| Strict validation | `openspec validate questions-resume-after-switch --strict` | valid (exit 0) |
| Spec inventory | `grep -c '^### Requirement'` / `'^#### Scenario'` | 5 requirements / 16 scenarios |
| Tasks | `grep -cE '^[[:space:]]*- \[ \]' tasks.md` | 10 open, 0 `[prod-verify]`; none needs a push to be ticked |
| Baseline tests | `python3 -m unittest scripts.toolkit.tests.pieces.test_account_switch` | 123 tests, OK |
| Privacy | `python3 scripts/privacy-check.py --require-private` | 0 findings (exit 0) |

## Requirement → code today → task

| Requirement | Code today (FACT) | Task |
|---|---|---|
| A switch lists the questions session | `lock_roles` reads `session_id` and `closer` only; `stopped_sessions` | 1.1, 1.2 |
| Exclusions and missing queue | `stopped_sessions` exclusions; no queue read | 1.1, 1.2 |
| Own text, `mine`, notice | `resume_text`, `watcher_text`, `steps`, `session_line`, `cmd_mine`, `cmd_on_switch` | 2.2, 2.3 |
| Row stays pending | `pending_sessions` knows `watcher` and cut kinds | 2.1 |
| Gate accepts the text | `account_switch_resume` reads marker, claim, list, delivery | 3.1 |
| Documents (design D5, D6; optional dependency) | rule, task prompt, manifest, `README.md`, supervision reference | 4.1–4.3 |

## Unknowns and limits

- UNKNOWN: the transcript entries a rejected dialog leaves, and when they are written. The design does not use them
  to select; the ask gate's backstop is covered by its self-test for an errored result and for no result.
- UNKNOWN: whether a message queued to a session survives its process. The text covers a missing question.
- Not checked here: the behavior in the real desktop app (nothing is installed by this change).

## Verdict

**READY TO APPLY**

## After apply (phase P2, `repasa-spec`)

The sections above describe the documents before the code. This one is the state after it.

| Check | Result |
|-------|--------|
| `python3 -m unittest scripts.toolkit.tests.pieces.test_account_switch` | 151 tests, OK (exit 0) |
| `python3 -m unittest scripts.toolkit.tests.pieces.test_cross_project_message_gate` | 63 tests, OK (exit 0) |
| `python3 -m unittest scripts.toolkit.tests.test_installer` (the `accounts` manifest changed) | 29 tests, OK (exit 0) |
| `supervisor-lock skill-lint` on the repository skill, temporary `HOME` (a reference changed) | `SKILL_LINT ok` (exit 0) |
| `python3 scripts/validate-toolkit.py` | 0 errors, 0 warnings (exit 0) |
| `python3 -m unittest scripts/test_validate_toolkit.py` | 59 tests, OK (exit 0) |
| `bash examples/override-full/try.sh` | every step passed (exit 0) |
| `openspec validate questions-resume-after-switch --strict` | valid (exit 0) |
| `python3 scripts/privacy-check.py --require-private` | 0 findings (exit 0) |
| Tasks | 0 open, 0 `[prod-verify]` |

The piece tests ran with a temporary `HOME`. No supervisor self-test probe was added, so its floor is unchanged. The
whole self-test and the whole test tree were not run.

Not verified: the behavior in the real desktop app (nothing is installed by this change).

## Confirm review (phase P4)

| Check (temporary `HOME`) | Result |
|-------|--------|
| `python3 -m unittest scripts.toolkit.tests.pieces.test_account_switch` | 151 tests, OK (exit 0) |
| `python3 -m unittest scripts.toolkit.tests.pieces.test_cross_project_message_gate -k questions` | 1 test, OK (exit 0) |
| End-to-end run with synthetic lock, queue, app records and transcripts (throwaway script, not kept) | 16 checks passed (exit 0) |
| `python3 scripts/validate-toolkit.py` | 0 errors, 0 warnings (exit 0) |
| `openspec validate questions-resume-after-switch --strict` | valid (exit 0) |
| `python3 scripts/privacy-check.py --require-private`, local denylist read through `CLAUDE_TOOLKIT_OVERRIDE` | 0 findings (exit 0) |

Three gaps found and fixed (G-11 to G-13 in `GAPS.md`). The other checks of the table above were not run again.
