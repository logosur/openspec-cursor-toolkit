---
name: openspec-apply-change
description: Implement tasks from an OpenSpec change in unattended multi-agent mode. Use when the user wants to start implementing, continue implementation, apply, or work through tasks.
license: MIT
compatibility: Requires openspec CLI when available.
metadata:
  author: openspec
  version: "1.1"
---

Implement tasks from an OpenSpec change.

## Unattended Multi-Agent Contract

Read and follow `.claude/skills/multiagente/SKILL.md` when present. Treat apply as:

```text
usa el modo multiagente para aplicar la tarea OpenSpec <change>, de forma desatendida. No pares hasta terminarlo todo.
```

Do not stop for ordinary fixable failures. Iterate until tasks are complete and verified, or a real blocker is explicit.

## Steps

1. Select the change. If omitted and ambiguous, ask or list active changes.
2. Run `openspec status --change "<change>" --json` when available.
3. Run `openspec instructions apply --change "<change>" --json` when available.
4. Read every path returned in `contextFiles`; also read `VERIFY.md` and `READY-TO-APPLY.md` if present.
5. Show schema, progress, pending tasks, and dynamic instruction.
6. For each pending task, in order:
   - Implement minimal scoped changes.
   - Use subagents for focused implementation, testing, investigation, or review when useful.
   - Verify the task with the narrowest reliable command or browser check.
   - Mark `- [ ]` to `- [x]` only after verification.
7. Run `openspec validate "<change>"` when available and relevant.
8. Run project-specific tests or browser checks required by the touched behavior.

## Completion Rules

Final output must include:

- Tasks completed this session.
- Overall checkbox progress.
- `## Verification` with concrete evidence.
- Remaining unchecked tasks, blockers, and exact next action if anything is incomplete.

Never imply that apply is complete while tasks, acceptance criteria, tests, or user-visible behavior remain unverified.
