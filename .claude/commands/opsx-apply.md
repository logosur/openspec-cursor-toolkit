---
description: Implement tasks from an OpenSpec change with unattended multi-agent verification
---

Implement tasks from an OpenSpec change.

## Unattended Multi-Agent Contract

Before starting, read and follow `.claude/skills/multiagente/SKILL.md` when present. Treat this command as:

```text
usa el modo multiagente para aplicar la tarea OpenSpec <name>, de forma desatendida. No pares hasta terminarlo todo.
```

Do not stop after a first failure or partial implementation. Iterate until every required task is complete and verified, or a real blocker is explicit.

## Input

Optionally specify a change name (e.g., `/opsx-apply add-auth`). If omitted, check if it can be inferred from conversation context. If vague or ambiguous, prompt for available changes.

## Steps

1. **Select the change**

   If a name is provided, use it. Otherwise:
   - Infer from conversation context if the user mentioned a change.
   - Auto-select if only one active change exists.
   - If ambiguous, run `openspec list --json` and ask the user to select.

   Always announce: `Using change: <name>` and how to override.

2. **Check status**

   ```bash
   openspec status --change "<name>" --json
   ```

   Parse `schemaName`, artifact status, task source, and apply readiness.

3. **Get apply instructions**

   ```bash
   openspec instructions apply --change "<name>" --json
   ```

   Parse `contextFiles`, progress, pending tasks, state, and dynamic instruction.

   **Handle states:**
   - `blocked`: show the missing artifacts or gate, then fix/hydrate if this is within scope; otherwise report the blocker.
   - `all_done`: verify with `openspec validate "<name>"` when available and summarize.
   - otherwise: proceed to implementation.

4. **Read context files**

   Read every file path listed under `contextFiles`. Also read `VERIFY.md` and `READY-TO-APPLY.md` if present.

5. **Show current progress**

   Display schema, `N/M tasks complete`, remaining tasks, and the current OpenSpec instruction.

6. **Implement tasks until done or genuinely blocked**

   For each pending task, in order:
   - Work on the task with minimal scoped changes.
   - Use subagents for focused implementation, failure investigation, testing, or review when useful.
   - Run the narrowest relevant verification for that task.
   - Mark `- [ ]` to `- [x]` only after implementation and verification.
   - Continue to the next pending task.

   Do **not** pause for ordinary fixable errors. Fix forward and re-run verification.

7. **Final validation**

   Run when available and relevant:

   ```bash
   openspec validate "<name>"
   ```

   Run project-specific tests or browser checks required by the touched behavior.

8. **Completion or explicit partial state**

   Final output must include:
   - Tasks completed this session.
   - Overall progress.
   - Verification evidence.
   - Remaining unchecked tasks, if any, with exact blocker and next action.

## Guardrails

- Always read context files before starting.
- Keep code changes minimal and scoped.
- Never weaken tests to force green.
- Never hide partial state.
- Do not commit, push, merge, or rebase unless explicitly authorized.
