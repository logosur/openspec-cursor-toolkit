# Master OpenSpec Prompt

Use this prompt when I give a simple idea, bug, feature, refactor, test problem, API change, webhook flow, or backend behavior and I want a strong OpenSpec specification before implementation.

## Prompt

> **Before you act:** This flow is **EXPLORE → PROPOSE → HYDRATE → VERIFY only**. It is **not** permission to run **`/opsx:apply`**, **`/aplica-tarea`**, or **`openspec instructions apply`** in this same turn.  
> **Do not implement yet.**  
> **No implementes todavía.**

OpenSpec mode.
Spec name: [spec-name]
User request:
[PASTE REQUEST HERE]

Use the project OpenSpec prompt architecture:

- EXPLORE
- PROPOSE
- HYDRATE
- VERIFY

For this flow, **HYDRATE** means completing OpenSpec **artefact markdown** under `openspec/changes/<the change folder matching Spec name above>/` only — not executing product work from `tasks.md` in this turn.

If the user ends the message with **No implementes todavía.** (Spanish), treat it as **exactly the same** as **Do not implement yet.** in the callout above — no implementation or product code changes in this turn.

First, explore the existing project:
- existing OpenSpec specs
- source code
- tests
- configuration
- logs if available
- similar implementations
- architecture and conventions

Then create or improve an OpenSpec proposal.

The result must include:
- problem summary
- current behavior
- expected behavior
- included scope
- excluded scope
- source of truth
- evidence map
- requirements
- GIVEN / WHEN / THEN scenarios
- acceptance criteria
- technical design if needed
- risks
- edge cases
- testing strategy
- tasks.md-style checklist
- verification status:
  - READY TO APPLY
  - NEEDS HYDRATION
  - BLOCKED BY UNKNOWN
  - UNSAFE TO APPLY

After you deliver the verification status and artefacts for this turn, **stop**. Do not begin apply (`/aplica-tarea`, `/opsx:apply`, or product `tasks.md` execution) until the user sends a **new** message that explicitly requests it.

Rules:
- Do not implement.
- Do not modify code.
- Do not invent missing business rules.
- Do not invent classes, services, routes, statuses, labels, codes, tables, or config keys.
- Mark unsupported claims as NOT VERIFIABLE.
- Separate FACT, INFERENCE, HYPOTHESIS, UNKNOWN.
- Prefer small, reviewable tasks.
- Every requirement must be testable.
- Every task must map to a requirement or risk.
- Do not weaken tests to make them pass.
- Do not declare success without evidence.

---

## Mandatory closing (after VERIFY)

When this prompt was composed from **`/prepara-tarea`** (or the user asked for the same EXPLORE→VERIFY-only flow), **before you end your reply** you MUST:

1. Print these **two lines verbatim** (exact spelling and punctuation), each on its own line:

Do not implement yet.

No implementes todavía.

2. Print **one** explicit stop line that names the slug and apply command, for example: **Stop.** Run **`/aplica-tarea [spec-name]`** in a **new** message when you want implementation (including any edits **outside** `openspec/changes/[spec-name]/`).

Do not print anything after those lines that suggests continuing into apply in this same turn.

## User message footer (recommended)

End your OpenSpec request with **one** of these lines so the agent stops before apply (same meaning):

- **English (canonical):** `Do not implement yet.`
- **Spanish (team habit):** `No implementes todavía.`

The agent MUST honour either phrase as: **no implementation or product code changes in this turn**; work only through EXPLORE → PROPOSE → HYDRATE → VERIFY until a separate explicit apply step (e.g. `/aplica-tarea` or `/opsx:apply`).