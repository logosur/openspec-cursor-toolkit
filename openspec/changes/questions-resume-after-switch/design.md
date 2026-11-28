# Design — questions-resume-after-switch

## Context

The questions session of a supervision is registered in the lock as `mailbox` (`supervisor-lock beat --mailbox`). The
supervisor marks every question it sends with `ask-queue asked <ids> --to <questions session>`, and the questions
session records each human answer with `ask-queue answer`. So «registered mailbox with `asked` items addressed to it»
is exactly «questions presented and not answered», without reading any transcript.

## Decision D1 — a row in the account-switch resume list (option 1), no watcher signal

**Option 1** (chosen): `account-switch` lists the questions session and one session resumes it.

**Option 2** (rejected): a watcher signal when `asked` items exist for a questions session that has not been running
for a while.

Why option 1 alone:

- It covers the whole case. The cause is the switch, and the switch is exactly what `account-switch` detects.
- It acts at once, from data (`mailbox` + `asked_to`). Option 2 needs a time threshold, persisted state, a new guard
  event and a supervisor procedure to send the questions again.
- Option 2 depends on a supervisor whose own process the same switch closed, and which only comes back through this
  resume list.
- Option 2 cannot tell a dialog the developer dismissed on purpose from a lost one, so it would keep presenting it.

Doing both is not justified: nothing in the described case is left for option 2. A dialog lost for another reason
(reboot, app crash) stays out of scope and is still caught by the queue's re-ask threshold.

## D2 — who is a questions session

`lock_roles` (owner, closer, 6-hour heartbeat) is left untouched. A separate reader returns the `mailbox` ids of the
lock files whose heartbeat is at most 24 hours old (and at most 300 s in the future).

24 hours, not `LOOKBACK`: it is the window in which the supervision code still treats a quiet, unreleased lock as
supervising (`STALE_LOCK_SUPERVISED_S` in `lib/supervisor/lock.py`). INFERENCE: a switch can come hours after the old
account ran out, when no watcher is beating the lock any more. The constant is repeated with a comment, because
`account-switch` must work without the supervision module.

Order inside `stopped_sessions`:

1. Today's exclusions stay first for every row: archived, own session, no CLI id, run of the resume task, paused
   project.
2. A session that is an owner or a closer keeps today's handling, even if some lock also names it `mailbox`.
3. A mailbox with `asked` items addressed to its local id or CLI id gets kind `questions`. Neither the age of
   `lastActivityAt` nor the transcript is consulted: an open dialog moves neither, and the kind wins over
   `hard`/`soft` because only this text asks it to present the questions again.
4. A mailbox with no such item is an ordinary session (today's behavior).

Rows are built from the app's session records, so a session is listed once even when several locks name it; its row
carries every `asked` id addressed to it.

## D3 — reading the queue

Run the public CLI, `ask-queue list --json` (`$ASK_QUEUE_BIN`, default `~/.claude/scripts/ask-queue`, run with
`sys.executable`, timeout 5 s because `claim` runs under the event flock inside a 10 s hook). Every status is read,
not only the unanswered ones: pending needs to see that an item was answered. Read the env var at call time. Run it
only when there is a mailbox or a `questions` row to judge, once per selection or pending pass.

The reader returns `{id: item}` of what it could read, possibly empty, and never raises (missing script, timeout,
output that is not a JSON list → empty). `ask-queue` itself cannot be trusted to say that something is missing:

- a garbage line or a file it cannot open is skipped silently (exit 0);
- one file with bytes that are not UTF-8 makes the listing of every project exit non-zero. On a non-zero exit only,
  the reader asks again project by project, `list --project <checkout> --json`, with the `checkout` of each lock file,
  and merges what succeeds, so one corrupt queue does not hide the others. A timeout is not retried.

The one rule that follows: **an id the reader does not show is unknown, never answered** (`ask-queue` changes the
status of items and never deletes them). Selection needs a positive `asked` item, so unknown gives no new row; pending
keeps an unknown id, so a corrupt or unreadable queue cannot mark the event done and lose the resume.

`ask-queue` is not changed: making it tolerate those bytes would let its next write drop the lines it could not read.

## D4 — pending, claim and ids

The row is `{sessionId, cliSessionId, title, cwd, kind: "questions", asked: [ids]}`. `pending_sessions` drops it when
`leave_alone` says so, when `delivered_at` finds the resume, or when no id is left. The ids left are: the stored ones
that are unknown (D3) or still `asked` to this session, plus any other `asked` to it now (so `claim` saves current
ids). Unlike a `watcher`, having run a turn since the switch does not drop
it: a turn does not prove the dialog came back. If it did come back by itself, the queued message is read after the
answer, `ask-queue pending` shows nothing `asked` and nothing is asked twice.

## D5 — the text

Each questions session gets its own text, because it names that session's ids. It starts with the configured marker
(the gate looks for it) and does not include `resume_text()`, whose «without repeating what was done» contradicts the
request. Product text, in Spanish like the other resume texts:

> `<marker>` La cuenta de Claude cambió y tu proceso se cerró: el diálogo de preguntas que tuvieras abierto quedó sin
> contestar y nadie lo está viendo. Ejecuta `~/.claude/scripts/ask-queue pending <ids>` y vuelve a presentar ahora las
> que sigan `asked`, en diálogos de hasta cuatro por diálogo y encadenados hasta la última, con las mismas preguntas y
> opciones que te mandó la supervisora, sin cambiar una palabra, y con `ask-queue:<id>,<id>` (los ids de ese diálogo)
> en `metadata.source`. Si alguna ya la contestó el desarrollador en un diálogo y no quedó anotada,
> anótala con `~/.claude/scripts/ask-queue answer` y no la repitas. Si de alguna no tienes la pregunta con sus
> opciones en tu conversación, o sale `missing`, no la presentes ni la inventes: di sus ids al terminar tu turno. Si
> el comando falla, presenta las que en tu conversación no tengan respuesta del desarrollador.

- Up to four per dialog, chained: a final batch holds more than one dialog. `ask-queue:<id>,<id>` is the only form
  of `metadata.source` that the ask gate's repeat backstop and `ask_source_ids` read.
- `pending` and `answer` are the two commands the questions session's own brief already allows
  (`f5-decisiones.md`), so sessions opened with that brief can obey.
- The second to last sentence covers a supervisor message that was still queued when the process closed (whether a queued
  message survives is UNKNOWN). The last one covers a corrupt queue file, which makes `ask-queue pending` fail. Ending the turn wakes the supervisor through the existing `ANSWERED` turn trigger.
- The text must not match `LIMIT_TEXT`, or a transcript quoting it would read as a limit cut.

`steps()` leaves `questions` rows out of the two existing groups (whose texts and members do not change) and adds one
block per questions session after them, keeping step 1's `mine` instruction on
whichever block comes first. `session_line` marks the row and lists its ids. `mine` prints the full text under each
pending questions row, so a claimant that was compacted can rebuild it. `on-switch` adds one notice line with their
number (not when the new account is out of usage, like the watcher line). The module docstring describes the kind.

## D6 — the gates need no change (verified by reading, to be pinned by a test)

- `cross-project-message-gate` `account_switch_resume` checks marker, event, claim, listed recipient and delivery; the
  new text passes for a listed questions session and is refused for an unlisted one.
- The ask gate lets a `mailbox` role open dialogs. Its repeat backstop skips errored dialog results and dialogs with
  no result, and denies only ids already `answered`/`closed`; the self-test already covers both («an earlier dialog
  that errored», «a dialog nobody has answered yet», «an `asked` id is still pending»).
- `ask-queue-prompt` and the presence scan already ignore prompts that start with the marker.

## Contract

`global/contracts/account-switch.yaml` is unchanged: no subcommand, flag or exit code changes, and a probe cannot
build the lock, queue and event fixtures. The behavior is covered by piece tests.

## Tests

Synthetic state only, in `scripts/toolkit/tests/pieces/test_account_switch.py`: `env()` gets a temporary `HOME`,
`ASK_QUEUE_DIR` and `ASK_QUEUE_BIN` (the repository's `ask-queue`) next to the existing temporary folders, so no test
can read a real queue. Items are created with the real `ask-queue add` and `asked --to`. `detect` is never run.

## Risks and limits

| Risk | Handling |
|------|----------|
| A dialog dismissed on purpose, left `asked`, is presented again after a switch | Accepted: it is still unanswered; once per switch |
| An item marked `asked` without `--to`, or with an id that is neither the local nor the CLI id | Not seen; the supervision reference always passes `--to` |
| A row whose queue file was deleted by hand | Its ids stay unknown; it ends with the delivery or the event's expiry |
| Lock heartbeat older than 24 hours | Not listed; the queue's re-ask threshold still applies |
| The questions session of a released lock | Not listed (the lock file is gone) |
| The developer answers between the claim and the send | `ask-queue pending` shows `answered`; nothing is asked |
| Installed copies are not updated by this change | Installing is outside this change |

## Rollback

Revert the commit. An event written with `questions` rows expires on its own; an older script treats the unknown kind
through `stop_kind`, which at worst drops the row.
