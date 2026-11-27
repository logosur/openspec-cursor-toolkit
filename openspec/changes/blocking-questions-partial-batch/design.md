# Design — blocking-questions-partial-batch

## Context

| Fact | Evidence |
|---|---|
| The supervision presents queued questions only in the final batch (F9) or, before it, a radical course voted 3/3 | `reference/f5-decisiones.md` («Rumbo radical: la única pregunta adelantada»), `deny.deny_question` |
| The final batch waits until no authorised work is left | `SKILL.md` («La tanda no sale mientras quede algo autorizado…»), `reference/f6-f9.md` F9 |
| A queue item records `ts`, `status` (`open`, `asked`, `answered`, `closed`), `asked_ts`, `blocks`, `radical` | `global/scripts/ask-queue` (`cmd_add`, `cmd_asked`) |
| The supervisor marks items `asked` before it sends them to its questions session | `reference/f5-decisiones.md`, «La sesión de preguntas», point 3 |
| The questions session may always open dialogs; other supervised sessions only when the developer drives them | `ask_gate.ask_gate_decide` (`role == 'mailbox'` → allow) |
| Watcher signals that must not repeat every poll go through `cloud.announce_once` with a per-signal file under `announced/` | `watch.machine_events` (`BACKLOG`, `CLOUD`), `machine_queue.heavy_events` |
| `supervisor-lock` already loads `ask-queue` as a module, lazily, and fails open when it cannot | `providers.ask_queue_module`, `ask_gate.ask_gate_backstop` |
| Templates that queue with `--blocks "nada"`: decisions to confirm (f5), open dialogs copied by `session-nudge` | `f5-decisiones.md`, `global/scripts/session-nudge` (`queue_dialog`) |
| The archive-permission template leaves `--blocks …` for the supervisor to fill | `closable.py` (`closable_reason`) |

## Goals / Non-Goals

**Goals:**
- A question that blocks real work reaches the developer within a bounded time, even in a project that never runs out of work.
- A question that blocks something the developer ordered reaches him at once.
- He is interrupted at most once per window per project, with everything due in one batch.
- One source of truth for what is due: `ask-queue`. `supervisor-lock` only reports it.

**Non-Goals:**
- A new path to the developer: the partial batch uses the questions session exactly as a radical does.
- Any change to who may open a dialog (the ask gate) or to `ask-queue-prompt`.

## Decisions

### D1 — Blocking-due rule
An item is due when all of these hold:

- `status == 'open'` (never presented; an `asked` item is not due again, whatever its age);
- not `radical` (radicals already go at once);
- and either it has a non-empty `order` (due at once), or `blocks_work(blocks)` and `now - ts >= ask_due_after_h`.

`blocks_work` is false for an empty text and for a text whose first word, case- and accent-folded, is one of `nada`, `nothing`, `none`, `ninguno`, `ninguna`, `ningun`. The decision named `Nada`, `Nothing` and `Ninguno`; the other three are the same word in other forms and keep a template like `--blocks "ninguna"` out. An item with an unreadable `ts` counts as old (the queue's `age_hours` already does this), so a damaged item is presented rather than hidden.

Alternative considered: a new `--blocking` flag. Rejected: old items have no flag, and every item already says what it blocks.

### D2 — The window is read from the queue, not from a new marker
The last partial batch of a project is the newest `asked_ts` among its non-radical items, whatever their status now. A partial batch is allowed when there are due items and either one of them has an `order`, or there is no such `asked_ts`, or it is at least `ask_partial_batch_window_h` old.

Why: the supervisor already runs `ask-queue asked <ids> --to <questions session>` before it sends any batch, so the information is there, and a forgotten extra flag cannot break the window. Radicals are excluded so that a radical asked an hour ago does not delay a blocking question. A final batch also closes the window, which is right: it asked everything open.

### D3 — Thresholds in the `supervision` config piece, read by `ask-queue`
`ask_due_after_h` (24) and `ask_partial_batch_window_h` (12), read through `toolkit_config.load_checked`; a value that is not a finite number ≥ 0 keeps the default. `ask-queue` is the only reader (`supervisor-lock` asks `ask-queue` for the state), so `settings.py` does not repeat them. `0` means "no wait" for both.

### D4 — `ask-queue list --due`
Lists the due items (all projects, or `--project`), oldest first, each with `age_h` and `due_reason` (`order` or `blocks`). Text output ends with one line per project: `partial batch <name>: due now (<n>)` or `partial batch <name>: window closed until <iso> (last asked <iso>)`. JSON is a list of items with the two extra fields. The library function `partial_batch_state(root, now)` returns `{'due': [...], 'allowed': bool, 'last_asked': iso|None, 'opens_at': iso|None}` and is what `supervisor-lock` calls.

### D5 — `--order` is stored as given and only ever added
`add --order "<his words>"` stores `order` on the item. An empty or blank value is refused with exit 2, like `supervisor-lock mode --order`. On a duplicate (same key or same question), a new order text replaces the old one; a plain add never removes it, as with `--radical`.

### D6 — `ASKDUE` from the watcher and from `beat`
New module `askdue.py`:

- `askdue_state(project)`: loads `ask-queue` with `providers.ask_queue_module()`, resolves the queue of the project's checkout and returns the state of D4, or `None` on any error (fail silent: the temp HOME of CI and a machine without the queue have no `ask-queue` installed).
- `askdue_line(project, owner)`: `ASKDUE <n> <ids> (…)` with a Spanish hint, or `None` when nothing is due or the window is closed.
- `askdue_events(project, owner)`: the line through `cloud.announce_once(key, 'askdue', [(sorted ids, line)], ASKDUE_REANNOUNCE_S)`; `ASKDUE_REANNOUNCE_S` is 6 h, like `BACKLOG`. A new due id (a new `--order` item) changes the key and is announced at once.

The watcher polls it every 300 s inside `machine_events` (owner only), from the first poll. `ASKDUE` joins `GUARD_EVENTS`: a supervisor on guard must also present a due batch. `beat` prints the line on stderr after the `NOMAILBOX` hint, every beat, like that hint (it costs no wake).

No new subcommand: `list --due` lives in `ask-queue`, and `supervisor-lock` only signals.

### D7 — Templates keep non-blocking items out
- The archive-permission template in `closable.py` becomes `--blocks "nada: solo su archivado"`: archiving permissions belong in the final batch (F9, point 4), not in a partial one.
- Decisions to confirm (`--blocks "nada"`) and dialogs copied by `session-nudge` (`nada`) are already out.
- The hard-limit templates (`deny_absent` step 3, `deny_supervised`, the rules, f5) tell sessions to write what it really blocks and to add `--order "<sus palabras>"` when it blocks something the developer ordered.

### D8 — Deny texts are extended, never reworded
The self-test asserts literal fragments of the deny texts (`radical por unanimidad`, `--radical --cost`, `sesión hija está archivada o aparcada con su decisión en ask-queue`, one line, no «buzón»). The new sentences are appended next to them and carry `tanda parcial` and `ask-queue list --due`, which new self-test checks and unit tests assert.

### D9 — Skill text
- Core: point 5 of «El concepto» names both early paths in one sentence; the detail goes to `reference/f5-decisiones.md`. The core stays under the `skill-lint` limit.
- `reference/f5-decisiones.md`: «Antes del final: rumbo radical y tanda parcial», with the rule, the window, how to send it and the report rule.
- `reference/vigilancia.md`: the `ASKDUE` row and the guard events.
- `reference/anti-patrones.md`: two new items at the end (no renumbering).
- `reference/registro-y-cierre.md`: §8 row.
- `reference/cambios.md`: a dated top entry with the one-time step on reload.
- No `SKILL_STALE` lint pattern for the old wording: it would turn `skill-lint` red on an installed override that has not been updated yet.

## Risks / Trade-offs

- **Catch-up batch:** after install, every old open item whose `blocks` names work is due at once. Bounded to one batch per window; it is the purpose of the change.
- **A supervisor that ignores `ASKDUE`:** the line repeats every 6 h on the watcher and on every `beat`; the skill and anti-patterns say what to do.
- **Not executed here:** the full self-test and the full unit suite run in CI. The new self-test checks were compiled, and mirrored by unit tests that were run.
