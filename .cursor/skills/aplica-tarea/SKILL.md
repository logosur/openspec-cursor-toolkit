---
name: aplica-tarea
description: Apply an OpenSpec change (same workflow as /opsx:apply)
disable-model-invocation: true
---

---
name: /aplica-tarea
id: aplica-tarea
category: Workflow
description: "Apply an OpenSpec change (same workflow as /opsx:apply)"
---

# Aplica tarea (OpenSpec)

You are running **aplica-tarea**: implement pending work for `openspec/changes/<slug>/`. Use this **only** after the user explicitly chooses to apply (e.g. after `/prepara-tarea` or `/verifica-tarea` completed and the user wants implementation). **Do not** chain automatically from those commands in the same user message without a new explicit request.

## 1. Resolve `<slug>`

On the **first line**, parse the slug as the **first token after** `aplica-tarea` (optional leading `/`), separated by **whitespace only** — do **not** require a colon. Example: `/aplica-tarea task-commands`. If missing, ask once or run `openspec list --json` and disambiguate.

## 2. Delegate to the canonical apply workflow

Follow the same steps as **`/opsx:apply <slug>`** using the project command definition:

- Read and obey: `.cursor/skills/opsx-apply/SKILL.md`
- Run: `openspec instructions apply --change "<slug>" --json` and process `contextFiles` + task list from the JSON output.

## 3. Implementation rules

- Work `tasks.md` in order; flip `- [ ]` → `- [x]` only when a task is truly done.
- Keep edits minimal and scoped to the change.
- Pause on blockers; do not weaken tests to force green.

## 4. Completion

Re-run `openspec validate "<slug>"` when appropriate. Summarise completed tasks and remaining checkboxes.
