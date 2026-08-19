---
name: /archiva-tarea
id: archiva-tarea
category: Workflow
description: "Archive an OpenSpec change (same workflow as /opsx:archive)"
---

# Archiva tarea (OpenSpec)

You are running **archiva-tarea**: archive `openspec/changes/<slug>/` when work is complete.

## 1. Resolve `<slug>`

On the **first line**, parse the slug as the **first token after** `archiva-tarea` (optional leading `/`), separated by **whitespace only** — do **not** require a colon. Example: `/archiva-tarea task-commands`. If missing, run `openspec list --json` and let the user pick an active change (do not guess).

## 2. Delegate to the canonical archive workflow

Follow the same steps as **`/opsx:archive <slug>`**:

- Read and obey: `.cursor/commands/opsx-archive.md`
- Respect warnings for incomplete artefacts or unchecked tasks; obtain explicit user confirmation if the archive instructions require it.

## 3. Repository conventions

Use the team’s archive layout (e.g. `openspec/changes/archive/...`) and any moves/updates defined in `opsx-archive.md` or project docs. Do not archive unrelated changes.

## 4. Summary

Report what was moved/deleted/updated and the final path of the archived change.
