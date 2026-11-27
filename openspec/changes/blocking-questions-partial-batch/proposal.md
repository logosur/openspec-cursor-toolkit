# Proposal — blocking-questions-partial-batch

> **Created by:** `/prepara-tarea blocking-questions-partial-batch` — 2026-11-27
> **Status:** decision taken before this change (what to build is fixed: a partial batch of blocking questions through the radical path). This change records it as requirements before the code.
> **Related:** `watcher-wake-backoff` (the watcher signals and their re-announce pattern).

## Why

The supervision only presents the developer's questions (hard limits, data only the developer knows, missing authorisations) in the final batch, which is sent when no authorised work is left. A project that always has work never reaches it.

Observed case (FACT, from a supervised project's queue and its supervisor's status report):

- A question was registered with `ask-queue add` five days before, as "a datum only the developer knows".
- It blocked a piece of work the developer had ordered himself as a priority.
- The supervisor's status report said the work was "pending, needs answers only you have".
- Nobody had presented the question to the developer: the final batch never came, and the only early path (a radical course voted 3/3 by the panel) did not apply.

So the report told the developer he was the blocker of something he had never been asked about.

## What Changes

- **A question becomes blocking-due** when it is open (never presented), is not radical, and either it blocks something the developer explicitly ordered (`ask-queue add --order "<his words>"`, due at once), or its `blocks` field names real work and it has been open longer than a threshold (24 h by default).
- **`ask-queue list --due [--project DIR] [--json]`** lists those items with their age and why they are due, and says per project whether a partial batch may be sent now.
- **One partial batch per project per window** (12 h by default): the window counts from the last time a non-radical item of the project was presented (`asked`). A due `--order` item opens the window at once.
- **`supervisor-lock`**: the watcher (`wait --owner`, also on `--guard`) and `beat` tell the lock owner `ASKDUE <n> <ids>` when a partial batch is due. The supervisor sends all due items together to its questions session, exactly as it sends a radical question: one batch of dialogs, the affected work parked, nothing else stops.
- **Deny texts** that say "only a radical goes before the end" also name the partial batch, and teach sessions to write a real `--blocks` and to add `--order` when the question blocks an order of the developer.
- **Skill and rules**: the supervision skill (reference files and a short line in the core), the three supervision rules and the decision panel skill describe the same model: the final batch at the end; before it only (i) a radical course voted unanimously, (ii) the partial batch of blocking-due questions. A status report never says that work waits for the developer's answer about a question that was not presented: it triggers the partial batch instead.
- Two keys in the `supervision` config piece: `ask_due_after_h` (24) and `ask_partial_batch_window_h` (12). A wrong value keeps the default.

## Capabilities

### New Capabilities

- `developer-question-batches`: when a queued question is presented to the developer before the final batch (blocking-due rule, partial batch window), how the supervisor learns it (`ASKDUE`), and what sessions and reports may say about questions that were not presented.

### Modified Capabilities

None. No spec existed for the question queue.

## Impact

- Code: `global/scripts/ask-queue`, `global/scripts/lib/supervisor/{askdue,watch,lock,deny,closable,selftest}.py`, `global/config/supervision.json`, `global/contracts/ask-queue.yaml`.
- Text: `global/skills/supervisa-sesiones/SKILL.md` and `reference/{f5-decisiones,vigilancia,anti-patrones,registro-y-cierre,cambios}.md`; `global/rules/{despliegue-y-limites-duros,desatencion-sin-preguntas,supervisor-decide-lo-documentado}.md`; `global/skills/panel-de-decision/SKILL.md`.
- Tests: `scripts/toolkit/tests/pieces/test_ask_queue.py`, `test_supervisor_lock.py`.
- State: none new. The queue items gain an optional `order` field; the partial batch window is read from the `asked_ts` already stored; `ASKDUE` announcements live in `announced/<key>.askdue.json` like the other announced signals.
- Behaviour without a live supervisor: unchanged (`ask-queue-prompt` keeps injecting the unasked items where they belong).
- Risk: a project with many old items whose `blocks` names work gets one partial batch on the first day after install. That is the intended catch-up; it is bounded by the window.

## Non-goals

- Presenting questions from the supervisor's own session, or from any session other than the questions session.
- Changing the final batch, the radical path, the ask gate's permissions or `ask-queue-prompt`.
- Re-asking questions that were presented and not answered (the existing `--unasked` re-ask threshold stays as it is).
- Migrating existing queue items.
