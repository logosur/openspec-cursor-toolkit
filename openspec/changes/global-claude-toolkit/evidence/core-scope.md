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
| sessions | `hooks/start-session-bypass-gate` (neutral header) | contract: 5 probes, including a deny |
| sessions | `hooks/spawn-task-duplicate-gate` (neutral header and deny message) | contract: 3 probes |
| supervision | `scripts/ask-queue`, `hooks/ask-queue-prompt`, `hooks/cross-project-message-gate` (exceptions off by default) | contracts; gate tests in `scripts/toolkit/tests/pieces/` |
| supervision | rules: messages only within the project, readable question dialogs | privacy guard 0 |
| heavy-jobs | `scripts/heavy-job`, `hooks/heavy-job-gate`, the classifier library both import (slots from config) | contracts; both test files in `scripts/toolkit/tests/pieces/` |
| openspec | the whole `.claude/` catalog and `docs/openspec/` | validator; installer tests |

## Left in the override for now, with the reason

Counts are privacy findings in the live copy (rule ids only; the text is not repeated here).

| Piece | Why it stays out | What it needs to enter |
|---|---|---|
| `hooks/unattended-deploy-gate` | 31 findings: it names real projects and hosts | the project list moved to config; generic default empty |
| `hooks/docker-desktop-restart-gate` | 7 findings; specific to one desktop engine setup | config piece; optional module |
| `hooks/contexto-gate`, `harness-contexto.sh` | home path and a private name | config piece |
| `scripts/rewrite-claude-authorship` | 11 findings; it rewrites published history | neutral copy; it stays opt-in |
| `supervisor-lock`, `supervisa-sesiones` and their hooks | personal (94 findings in the skill) and about 500 KB in one file | split planned in tasks §8 with acceptance criteria |
| `account-switch`, `session-nudge`, `cloud-tests` | they handle session tokens, an app socket or OAuth credentials | not toolkit material while they need them; optional for the pieces that name them |
| `project-pause`, `handoff-guard` | one machine's way of working | neutral copy and tests; optional until then |
| scheduled routines and other machine services | personal by nature | not toolkit material |

## Known gap found by a probe

`commit-authorship-gate` exits 1 when stdin holds valid JSON that is not an object, instead of failing
open. The toolkit copy is byte for byte the live gate, which only the developer edits by hand, so it was
not changed. The contract probes the realistic case (unparseable stdin), which passes.
