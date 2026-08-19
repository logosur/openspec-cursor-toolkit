---
description: "Apply an OpenSpec change in unattended multi-agent mode"
argument-hint: "[slug]"
---

# Aplica tarea (OpenSpec)

You are running **aplica-tarea**: implement pending work for `openspec/changes/<slug>/`.

Treat this command as:

```text
usa el modo multiagente para aplicar la tarea OpenSpec <slug>, de forma desatendida. No pares hasta terminarlo todo.
```

Read and follow `.claude/skills/multiagente/SKILL.md` before substantial work.

## 1. Resolve `<slug>`

On the first line, parse the slug as the first token after `aplica-tarea` (optional leading `/`), separated by whitespace only. Example: `/aplica-tarea task-commands`. If missing, ask once or run `openspec list --json` and disambiguate.

## 2. Delegate to the canonical apply workflow

Follow the same steps as `.claude/commands/opsx-apply.md` using this slug:

- Run `openspec status --change "<slug>" --json` when available.
- Run `openspec instructions apply --change "<slug>" --json` and process `contextFiles` plus pending tasks.
- Read `proposal.md`, `design.md`, `tasks.md`, `VERIFY.md`, `READY-TO-APPLY.md`, and `specs/**/spec.md` when present.

## 3. Implementation rules

- Work `tasks.md` in order.
- Use subagents for focused implementation, failure investigation, testing, and review when useful.
- Flip `- [ ]` to `- [x]` only when the task is implemented and verified.
- Keep edits minimal and scoped to the change.
- Do not weaken tests to force green.
- Do not stop for fixable failures; fix forward and re-run checks.

## 4. Completion

Run `openspec validate "<slug>"` when available and relevant. Run the narrowest project checks that prove the touched behavior.

Final output must include a `## Verification` section and the current checkbox status. If anything remains incomplete, list the exact unchecked tasks, why they remain, and the next action needed.
