---
description: "Start OpenSpec work from master prompt (explore -> propose -> hydrate -> verify; no product code)"
argument-hint: "[slug] [descripción]"
---

# Prepara tarea (OpenSpec)

> **MANDATORY — this same user message**  
> **Do not implement yet.** / **No implementes todavía.** — no **`/opsx:apply`**, **`/aplica-tarea`**, or **`openspec instructions apply`** for implementation in this turn. No flipping **product** `tasks.md` checkboxes (anything outside `openspec/changes/<slug>/`).  
> You only run **EXPLORE → PROPOSE → HYDRATE → VERIFY** for **OpenSpec markdown** under `openspec/changes/<slug>/`. After VERIFY, **stop** and tell the user to run **`/aplica-tarea <slug>`** in a **new** message.

You are running **prepara-tarea**: bootstrap an OpenSpec change from the repository master prompt.

## 1. Parse input (same user message)

**Change slug (kebab-case):** on the **first line**, after the command keyword, the slug is the **first whitespace-separated token** (no `:` before the slug). The command keyword is `prepara-tarea` with an optional leading `/`.

**Canonical message shape** (recommended in docs and when pasting into chat; **line 1** carries the command + slug for parsing):

```text
/prepara-tarea [nombre-slug]
 [descripcion problema o tarea]
```

**First-line slug examples** (same parsing rules; body may follow on the same line or on lines below):

- `/prepara-tarea watchdog-sandbox-tpl`
- `prepara-tarea task-commands`

If that token is missing or not kebab-case, ask **once** for the slug and stop until provided.

**User request body (multiline):**

- Prefer **all lines after the first line** of the same message (entire body joined with newlines).
- If there is only one line: use any text **after** the slug on that same line (trim leading whitespace after the slug); if still empty, ask **once** for the problem description **before** EXPLORE — do **not** treat the slug token alone as the full user request (avoids mistaking a phrase like `generar-doc-openspec-explicativo` for both slug and scope).

## 2. Build the prompt

1. `Read` `docs/openspec/prompts/master-openspec-prompt.md`.
2. Copy the full block under `## Prompt`, **from the first line of that section through the end of `## Mandatory closing (after VERIFY)`** (inclusive). Do **not** omit the mandatory closing subsection.
3. Replace `[spec-name]` with the parsed slug.
4. Replace `[PASTE REQUEST HERE]` with the user request body from step 1.

## 3. Execute (no product implementation)

Send the composed text as your **operating instructions** for this turn and follow it exactly:

- EXPLORE → PROPOSE → HYDRATE → VERIFY as defined in the master prompt.
- **HYDRATE** here means **OpenSpec markdown artefacts** under `openspec/changes/<slug>/` only (proposal, design, specs, tasks, VERIFY, READY-TO-APPLY, etc.) — **not** executing product work from `tasks.md` (no edits to application source outside `openspec/changes/<slug>/`; see `.claude/skills/00-openspec-stack-agnostic/SKILL.md`) in this turn.

### Hard stop after VERIFY (same turn)

When this turn started **only** from `/prepara-tarea` plus the composed master prompt, you MUST:

1. Deliver VERIFY output and a clear readiness verdict (`READY TO APPLY` / `NEEDS HYDRATION` / `BLOCKED…`).
2. Print an explicit **stop line**, e.g.: **Stop here. Run `/aplica-tarea <slug>` (or send a new message) when you want implementation.**
3. **NOT** in this same turn or same user message: start `/opsx:apply` or read `openspec instructions apply` for implementation; flip `- [ ]` → `- [x]` on **product** items in `tasks.md` (anything outside `openspec/changes/<slug>/` paths); edit application product trees.

If the user (or master prompt) wrote **No implementes todavía.** or **Do not implement yet.**, treat it as the same stop constraint as in `docs/openspec/prompts/master-openspec-prompt.md`.

## 4. Evidence

Separate **FACT** / **INFERENCE** / **HYPOTHESIS** / **UNKNOWN** where relevant. Do not declare verification passed without evidence.

## 5. Terminal reminder (repeat in your reply)

Your final reply after VERIFY MUST end with these lines **verbatim**, then the stop line referencing **`/aplica-tarea <slug>`** (substitute the real slug):

Do not implement yet.

No implementes todavía.

**Stop.** Run **`/aplica-tarea <slug>`** in a **new** message when you want implementation (including edits outside `openspec/changes/<slug>/`). Do not append anything after that suggests continuing apply in this same turn.
