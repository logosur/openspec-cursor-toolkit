---
name: 40-openspec-safe-apply
description: Safe APPLY phase for OpenSpec — gates, scope control, and evidence-backed completion
---

Use this rule during the **APPLY** step of OpenSpec (after VERIFY returns **READY TO APPLY**).

## Preconditions

- `proposal.md`, `tasks.md`, and any `specs/` deltas are read first.
- Scope and non-goals are explicit; treat anything outside them as out of scope.
- If VERIFY is not **READY TO APPLY**, do not implement production changes except to unblock verification (e.g., read-only investigation).

## Implementation rules

1. Execute `tasks.md` **in order** unless a task is truly parallelizable and the spec says so.
2. Do not "drive-by" refactor unrelated subsystems or directories.
3. Do not weaken tests, silence assertions, or delete scenarios to get green CI.
4. If code contradicts the spec, **stop** and reconcile spec vs code explicitly.
5. Prefer minimal diffs that satisfy the task’s acceptance criteria.

## Testing discipline

- Read the target project's stack rule (`.claude/skills/00-openspec-stack-agnostic/SKILL.md`) for test/lint commands.
- Run the **most specific** automated check first (narrowest PHPUnit/Jest/pytest/Make target that covers the change).
- Expand to broader suites only when the change footprint justifies it.
- Report failures with file/line and fix forward or update the spec if the failure reveals a spec error.

## Completion criteria

- All tasks in `tasks.md` are done or explicitly deferred with recorded rationale.
- Acceptance criteria and scenarios are satisfied or explicitly marked NOT VERIFIABLE with no impact on correctness.
- Automated tests relevant to the change pass, or failures are explained with next steps.
