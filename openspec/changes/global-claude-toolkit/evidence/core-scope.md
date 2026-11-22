# Core scope (task 5.2): what entered the toolkit and what stays in the override

Criteria for a piece to enter (design D10): (a) the privacy guard finds nothing in the neutral copy,
(b) its tests or self-test pass from the copy installed in a throwaway HOME (contract probes), and
(c) it has no runtime dependency on the supervision unit.

## Entered

| Module | Piece | Proof |
|---|---|---|
| core | `hooks/commit-authorship-gate` | contract: 3 probes (one documents a fail-open gap, see below) |
| core | `hooks/process-kill-gate` | its `--self-test` from the installed copy; contract |
| core | `hooks/worktree-location-gate` | contract, including a corrupt config |
| core | `scripts/worktree-location` (root from config) | contract; override test with a custom root |
| core | `scripts/lib/toolkit_config.py` | used by every configurable piece; installer tests |
| core | rules: commit authorship, kill only own processes, worktree placement | privacy guard 0 |
| core | `skills/panel-de-decision` (neutral) | privacy guard 0 |
| devtools | `scripts/port-lease` | contract (state under the sandbox HOME) |
| devtools | `scripts/test-account` (forbidden notes folders from config) | its self-test (35 checks) from the installed copy |
| devtools | rules: local ports per project, test accounts | privacy guard 0 |
| openspec | the whole `.claude/` catalog and `docs/openspec/` | validator; installer tests |

## Left in the override for now, with the reason

Counts are privacy findings in the live copy (rule ids only; the text is not repeated here).

| Piece | Why it stays out | What it needs to enter |
|---|---|---|
| `scripts/heavy-job` + `hooks/heavy-job-gate` | 12 findings in 2,500 lines; slot sizes and memory limits are machine values | neutral copy, config piece for slots and limits, its self-test from the sandbox |
| `hooks/unattended-deploy-gate` | 31 findings: it names real projects and hosts | the project list moved to config; generic default empty |
| `hooks/docker-desktop-restart-gate` | 7 findings; specific to one desktop engine setup | config piece; optional module |
| `hooks/contexto-gate`, `harness-contexto.sh` | home path and a private name | config piece |
| `hooks/cross-project-message-gate` | 11 findings, including private quotes; part of the supervision rules | supervision unit (tasks §8) |
| `hooks/ask-queue-prompt`, `scripts/ask-queue` | private quotes; the question queue belongs to supervision | supervision unit (tasks §8) |
| `hooks/start-session-bypass-gate`, `hooks/spawn-task-duplicate-gate` | privacy 0–1, but they guard the supervisor's session tools | supervision unit (tasks §8) |
| `scripts/rewrite-claude-authorship` | 11 findings; it rewrites published history | neutral copy; it stays opt-in |
| `supervisor-lock`, `supervisa-sesiones` and their hooks | personal (94 findings in the skill) and about 500 KB in one file | split planned in tasks §8 with acceptance criteria |
| scheduled routines, account switching, vault sync | personal by nature | not toolkit material |

## Known gap found by a probe

`commit-authorship-gate` exits 1 when stdin holds valid JSON that is not an object, instead of failing
open. The toolkit copy is byte for byte the live gate, which only the developer edits by hand, so it was
not changed. The contract probes the realistic case (unparseable stdin), which passes.
