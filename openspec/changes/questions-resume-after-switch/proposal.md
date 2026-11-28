# Proposal — questions-resume-after-switch

> **Created by:** `/prepara-tarea questions-resume-after-switch` — phase P1 of a `/run-spec` run, on branch
> `feature/questions-resume-after-switch` @ `6794491`. Nothing is implemented in this phase.

## Why

An account switch in the desktop app closes the CLI processes. A question dialog that a questions session had open is
rejected with them. Its questions stay `asked` in the ask queue, so nobody sees them until the re-ask threshold of the
queue (`ASK_QUEUE_REASK_H`, 12 hours by default). The resume list that `account-switch` hands to one session after a
switch does not include questions sessions, and a message queued to a session that is inside a dialog does not
interrupt it, so nothing else recovers the dialog.

## Current behavior (FACT, read from the tree)

- `global/scripts/account-switch`, `stopped_sessions`: a session is listed when `stop_kind` finds a cut turn in its
  transcript, or when it is the `session_id` or `closer` of a supervisor lock with a recent heartbeat (`lock_roles`,
  kind `watcher`). The `mailbox` key of a lock, where the questions session is registered, is never read.
- `stopped_sessions` skips a session without such a role whose `lastActivityAt` is older than `LOOKBACK` (6 hours): a
  dialog left open longer than that is not looked at.
- `stop_kind` returns `None` when the last assistant entry is a tool call with no later `user` entry.
- When a questions session is listed because its transcript does show a cut, it gets `resume_text()`, which says to
  continue without repeating what was done: nothing asks it to present the questions again.
- `global/scripts/ask-queue`: `asked --to <session>` records `asked_to`; `list --open --json` prints every `open` and
  `asked` item of every project with that field.
- `global/hooks/cross-project-message-gate`, `account_switch_resume`: judges the marker, the claim, whether the
  recipient is listed in the event and whether it already got a delivery. It never reads the rest of the text nor the
  row's kind.
- UNKNOWN: the exact transcript entries left by a dialog that the switch rejects, and whether the app writes them
  before `detect` runs. The design does not depend on either.

## What Changes

- `account-switch` lists, with a new kind `questions`, the session registered as `mailbox` in a supervisor lock that
  has at least one ask-queue item in `asked` addressed to it.
- That session gets its own resume text: check its pending ids with `ask-queue pending` and present the ones still
  `asked` again, with the same questions and options, without changing a word.
- It stays pending until it receives the resume, is archived, or the queue shows that none of its items is still
  `asked` to it (a corrupt or unreadable queue keeps it).
- `mine` repeats the text of a pending questions session; the switch notice counts them.
- Rule `cambio-de-cuenta.md`, the app task prompt, the `accounts` module manifest, `README.md` and the supervision
  reference on the questions session say so.

## Scope

**Included:** `global/scripts/account-switch`; its piece tests and one gate test; the documents listed above.

**Excluded:**

- A new signal in the supervisor's watcher (see design, «Option 2»).
- Any change to `ask-queue`, `supervisor-lock`, `cross-project-message-gate` or the ask gate.
- Recovering a dialog lost to something other than an account switch (reboot, app crash).
- Questions of a dialog that have no queue item (for instance a closing «anything else?»).
- Dialogs of sessions that are not a registered questions session.
- Installing, or editing the installed copies and the private override.

## Source of truth

- The orchestrator's brief for this change (private, not quoted here): the problem and the two candidate solutions.
- `global/scripts/account-switch`, `global/scripts/ask-queue`, `global/scripts/lib/supervisor/`,
  `global/hooks/cross-project-message-gate`.
- `global/skills/supervisa-sesiones/reference/f5-decisiones.md`, «La sesión de preguntas».

## Impact

- Optional dependency: `account-switch` (module `accounts`) reads `ask-queue` (module `supervision`) through its CLI.
  Without it the behavior is today's.
- No new subcommand, flag or exit code. `status` and the claim steps may show the kind `questions`.
- Event rows of that kind carry one new key, `asked` (list of ids). Other readers of the event ignore it.
