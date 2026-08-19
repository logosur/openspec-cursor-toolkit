---
description: "Run a specified task in unattended multi-agent mode until completion or a real blocker"
argument-hint: "[tarea]"
---

# Multiagente

You are running **multiagente**.

## Input

Parse everything after `/multiagente` as the task. If the first line is only `/multiagente`, use the remaining message body as the task.

Canonical intent:

```text
usa el modo multiagente para [tarea especificada], de forma desatendida. No pares hasta terminarlo todo.
```

If the task is empty, ask once for the task and stop.

## Mandatory Skill

Read and follow `.claude/skills/multiagente/SKILL.md` before doing any substantial work.

## Operating Mode

Run the task as:

> usa el modo multiagente para `<task>`, de forma desatendida. No pares hasta terminarlo todo.

This means:

- Decompose the task into verifiable acceptance criteria.
- Use subagents for exploration, implementation, testing, and review whenever the work is non-trivial or parallelizable.
- The main agent orchestrates, reads results, verifies against the real project, and relaunches subagents with concrete error evidence when checks fail.
- Do not stop after a partial attempt. Continue until all criteria are satisfied or a genuine blocker remains.

## Allowed Stop Conditions

Stop only when one of these is true:

- All acceptance criteria are implemented and verified with concrete evidence.
- A real blocker requires human-only input, credentials, explicit git merge/rebase/commit/push authorization, or a product decision that cannot be inferred.
- The user explicitly interrupts or changes the task.

## Final Output

Always include:

- What was completed.
- What was verified, with commands/tests/browser evidence when applicable.
- Any remaining blocker or unverified item, clearly labeled.
- If anything remains incomplete, say it plainly and include the exact next action needed.
