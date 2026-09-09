---
name: mejora-tarea
description: Hydrate an OpenSpec change until READY TO APPLY (artefacts + status)
disable-model-invocation: true
---

---
name: /mejora-tarea
id: mejora-tarea
category: Workflow
description: "Hydrate an OpenSpec change until READY TO APPLY (artefacts + status)"
---

# Mejora tarea (OpenSpec)

You are running **mejora-tarea**: bring `openspec/changes/<slug>/` to **READY TO APPLY**.

## 1. Resolve `<slug>`

On the **first line**, parse the slug as the **first token after** `mejora-tarea` (optional leading `/`), separated by **whitespace only** — do **not** require a colon before the slug. Example: `/mejora-tarea task-commands`. If missing, ask once. Slug MUST be kebab-case (folder name under `openspec/changes/`).

## 2. Discover state

```bash
openspec status --change "<slug>" --json
```

Parse `artifacts` and `missingDeps`. Follow **dependency order**: complete `proposal` → then `design` and `specs` in parallel if both ready → then `tasks` when its dependencies are `done`.

## 3. For each pending artefact

For each artefact that is `ready` (dependencies satisfied) but not yet created on disk:

```bash
openspec instructions <artifact-id> --change "<slug>" --json
```

Use the JSON `template`, `instruction`, and `outputPath`. Read completed dependency files listed in the instructions. Write the artefact file under `openspec/changes/<slug>/`.

Re-run `openspec status --change "<slug>" --json` after each artefact until `isComplete` is true (for schema `spec-driven`, all of `proposal`, `design`, `specs`, `tasks` are `done`).

## 4. READY TO APPLY

Update or create `openspec/changes/<slug>/READY-TO-APPLY.md` so it matches the project rubric (validate + status gates, verdict). Run:

```bash
openspec validate "<slug>"
```

Fix any validation errors before stopping.

## 5. Scope

Do **not** implement product application code unless `tasks.md` explicitly mixes hydration with implementation (default: **artefacts only**).

## 6. Apply boundary (human gate)

This command **never** starts `/opsx:apply` or executes product `tasks.md` checklists. When `openspec status` shows `isComplete: true` and `READY-TO-APPLY.md` is updated, **stop**. Tell the user to run **`/aplica-tarea <slug>`** (or a **new** explicit message) before any implementation.
