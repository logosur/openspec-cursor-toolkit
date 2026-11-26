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
| supervision | `scripts/supervisor-lock` and its library, `supervisa-sesiones`, `hooks/supervisor-stop-gate` | contracts; self-test; skill lint |
| supervision | `scripts/project-pause`, `scripts/session-nudge`, `scripts/handoff-guard`, the rule on project pauses, the prompt of the app task that revives supervisors (wording and titles from config) | contracts with a corrupt config; their test files in `scripts/toolkit/tests/pieces/` |
| heavy-jobs | `scripts/cloud-tests` (excluded projects from config, none by default) | contract; its test file, with no cloud or network |
| accounts | `scripts/claude-sessions-sync`, `scripts/account-switch` with its hook, rule and app task prompt (task folder and title from config) | self-test; contracts; their test files |
| routines | `scripts/routines` and its rule (permission profiles, notes folder and skipped app tasks from config; no profile of one machine) | contract; its test file |

## Left in the override for now, with the reason

Counts are privacy findings in the live copy (rule ids only; the text is not repeated here).

| Piece | Why it stays out | What it needs to enter |
|---|---|---|
| `hooks/unattended-deploy-gate` | 31 findings: it names real projects and hosts | the project list moved to config; generic default empty |
| `hooks/docker-desktop-restart-gate` | 7 findings; specific to one desktop engine setup | config piece; optional module |
| `hooks/contexto-gate`, `harness-contexto.sh` | home path and a private name | config piece |
| `scripts/rewrite-claude-authorship` | 11 findings; it rewrites published history | neutral copy; it stays opt-in |
| the routines and app tasks of one machine (their prompts and schedules), `scripts/open-in-developer-chrome` | personal by nature | not toolkit material; the engine that runs routines is the `routines` module |

## Known gap found by a probe

`commit-authorship-gate` exits 1 when stdin holds valid JSON that is not an object, instead of failing
open. The toolkit copy is byte for byte the live gate, which only the developer edits by hand, so it was
not changed. The contract probes the realistic case (unparseable stdin), which passes.
