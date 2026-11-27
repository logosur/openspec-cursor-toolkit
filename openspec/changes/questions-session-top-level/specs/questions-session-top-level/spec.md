# Spec Delta — questions-session-top-level

## Purpose

Defines where a supervision's questions session lives in the app's sidebar (at the top level, so its dialogs do not
appear in the supervisor's window), how `supervisor-lock` and the ask gate keep it there, and how the supervisor learns
that a question was answered once the app no longer tells it.

## ADDED Requirements

### Requirement: One lineage rule decides whether a session hangs from another
`supervisor-lock` SHALL treat an app session record as hanging from another session if and only if its
`spawnedFrom.sessionId` is a non-empty string and its `lineageDetached` is not `true`. Any other record SHALL count as
top level. The rule SHALL never raise on a malformed record.

#### Scenario: Child record
- **WHEN** a record has `spawnedFrom: {"sessionId": "local_sup"}` and no `lineageDetached`
- **THEN** it hangs from `local_sup`

#### Scenario: Detached record keeps its old parent field
- **WHEN** a record has `spawnedFrom: {"sessionId": "local_sup"}` and `lineageDetached: true`
- **THEN** it is top level

#### Scenario: No parent
- **WHEN** a record has no `spawnedFrom`, an empty object, an empty `sessionId` or a non-object `spawnedFrom`
- **THEN** it is top level, whatever `lineageDetached` says

### Requirement: A questions session that hangs from any session gets a DETACH line
`titles` and `beat` SHALL print `DETACH <questions id> questions (cuelga de <parent id>)` for the lock's registered
questions session when its app record hangs from any session, the lock owner included. They SHALL NOT print an `ADOPT`
line for the questions role in any case. A questions session with no record, or a top-level one, SHALL print neither.

#### Scenario: Child of the supervisor
- **WHEN** the lock's questions session record hangs from the lock owner
- **THEN** `titles --session <owner>` prints `DETACH <id> questions (cuelga de <owner>)` and no `ADOPT` line for it

#### Scenario: Child of another session
- **WHEN** the questions session record hangs from a previous supervisor `local_old`
- **THEN** the line is `DETACH <id> questions (cuelga de local_old)`

#### Scenario: Top level
- **WHEN** the questions session record has `lineageDetached: true`, or no parent
- **THEN** no `DETACH` and no `ADOPT` line names it

#### Scenario: beat shows it
- **WHEN** `beat --session <owner>` runs, titles sync is on (as for `RENAME` and `ADOPT` today) and the questions
  session hangs from some session
- **THEN** the `DETACH` line is on stderr and stdout is unchanged

### Requirement: The closing session keeps the ADOPT rule
For the closing role `titles` and `beat` SHALL keep printing `ADOPT <id> closer (abierta por <parent or ->)` exactly
when they did before this change (the parent is another session than the owner, or the record is detached), and SHALL
never print `DETACH` for it.

#### Scenario: Closing session detached
- **WHEN** the closing session record has `lineageDetached: true`
- **THEN** the output has `ADOPT <id> closer (abierta por …)` as before, and no `DETACH` line for it

#### Scenario: Closing session child of the owner
- **WHEN** the closing session record hangs from the lock owner and is not detached
- **THEN** nothing is printed for it

### Requirement: The ask gate denies an attached questions session once
When a session the ask gate recognises as a questions session (by title, or as the `mailbox` of a live, stale or
recently released lock) asks the developer (`AskUserQuestion`, or a
`wrap_up` with `ask` or `actions`) and its app record hangs from another session, the ask gate SHALL deny its first
such attempt with a one-line Spanish reason that names the parent and tells it to call `detach_session` with `"self"`
and repeat the same question. The gate SHALL log `deny-mailbox-attached`.

#### Scenario: First attempt while attached
- **WHEN** the questions session, hanging from `local_sup`, calls `AskUserQuestion` for the first time
- **THEN** the hook denies it, the reason contains `detach_session`, `"self"` and `local_sup`, and the decision log
  has a `deny-mailbox-attached` line

#### Scenario: Recognised by title with no live lock
- **WHEN** a session titled as the questions session, with no live lock in its project, hangs from another session
  and asks for the first time
- **THEN** it is denied once in the same way, and its retry is allowed

### Requirement: The ask gate never blocks the questions session twice
After that one deny, every later attempt of the same session while it still hangs SHALL be allowed and logged
`allow-mailbox-attached`. A top-level questions session SHALL be allowed as before (`allow-mailbox`). Any failure to
read the record or to write the gate's marker SHALL allow the question. Other roles SHALL keep their decisions.

#### Scenario: Retry while still attached
- **WHEN** the same session calls `AskUserQuestion` again and its record still hangs from `local_sup`
- **THEN** the hook allows it and the decision log has an `allow-mailbox-attached` line

#### Scenario: Detached
- **WHEN** the questions session record has `lineageDetached: true`
- **THEN** the question is allowed with `allow-mailbox`, with or without an earlier deny

#### Scenario: Fail open
- **WHEN** the questions session has no app record, its record is not valid JSON, reading it fails, or the gate cannot
  write its marker
- **THEN** the question is allowed and nothing is denied twice

#### Scenario: Once per session
- **WHEN** the questions session was denied once (its marker under the gate's `detach-asked/` directory exists, even
  empty or not valid JSON) and asks again, a different question, while still hanging
- **THEN** it is allowed with `allow-mailbox-attached`; a different questions session (another local id) is denied
  once on its own first attempt

#### Scenario: Marker lifetime
- **WHEN** a marker is older than 30 days when the gate writes a new one
- **THEN** the old marker is pruned, so at most one deny per session per 30 days remains possible

#### Scenario: Other sessions unchanged
- **WHEN** a supervised session, a free session or a lock owner asks
- **THEN** the decision is the one the gate gave before this change

### Requirement: ANSWERED reports an answered queue item
`supervisor-lock wait --owner <id>` SHALL print an `ANSWERED` line naming each item of the project's queue that became
`answered` within the last 24 hours and was not announced before. Each id SHALL be announced at most once.

#### Scenario: Answer on guard with the questions session excluded
- **WHEN** a supervisor waits with `--owner <id> --guard --exclude <questions id>`, the questions session is not busy, and
  an item of the project's queue moves to `answered`
- **THEN** within one poll interval the watcher prints a line starting with `ANSWERED` that lists that item id, and
  exits

#### Scenario: Old or repeated answers
- **WHEN** an item was answered more than 24 hours ago, or its id was already announced
- **THEN** no `ANSWERED` line names it

#### Scenario: One wake per answer on guard
- **WHEN** one item becomes answered, a guard watcher (`--owner <id> --guard --exclude <questions id>`) prints its
  `ANSWERED` line, and the supervisor re-arms the same watcher at once with nothing new in the queue or the census
- **THEN** the second wait prints no `ANSWERED` line (it ends at `TIMEOUT` or on another event), and within one wait
  no later poll repeats the id

### Requirement: ANSWERED reports a finished turn of the questions session
The watcher SHALL print an `ANSWERED` line when the questions session registered in the lock has completed more turns
than the watcher last recorded for it. The recorded count SHALL persist between waits. A first sight, a new session id
or a lower count SHALL be recorded without a line.

#### Scenario: Turn of the questions session
- **WHEN** the registered questions session's `completedTurns` goes from 3 to 4 while the watcher runs with `--guard`
- **THEN** the watcher prints one `ANSWERED <questions id>` line that contains `3->4`

#### Scenario: Turn ended between waits
- **WHEN** the recorded count is 3, the session reaches 4 while no watcher runs, and a new wait starts
- **THEN** that wait prints the `ANSWERED` line at its first poll

#### Scenario: First sight
- **WHEN** the watcher sees the registered questions session for the first time
- **THEN** it records the count and prints nothing for it

#### Scenario: One wake per turn
- **WHEN** the turn line for `3->4` was printed and a new wait starts while the count is still 4
- **THEN** no `ANSWERED` line is printed for that session until its count rises again

### Requirement: One batch of answers wakes the supervisor once
While the registered questions session is live and busy, the watcher SHALL hold the queue trigger and announce the
held ids together with that session's turn line, unless the oldest held answer is older than 600 seconds. Without a
live, busy registered questions session the queue trigger SHALL fire on its own.

#### Scenario: Answers recorded, then the turn ends
- **WHEN** the busy questions session records two answers in two different polls and then ends its turn
- **THEN** the watcher prints exactly one `ANSWERED` line, carrying the turn and both ids

#### Scenario: Busy for too long
- **WHEN** an answer is recorded and the questions session is still busy 600 seconds later
- **THEN** the watcher prints the `ANSWERED` line for that id without waiting for the turn

#### Scenario: No registered questions session
- **WHEN** the lock has no `mailbox` and an item of the queue becomes answered
- **THEN** the `ANSWERED` line is printed within one poll

### Requirement: ANSWERED is one guard event that sees past exclude
`ANSWERED` SHALL be a guard event, SHALL be computed even when the questions session is in `--exclude`, and SHALL be
one line per poll. It SHALL print nothing while the project is paused or when reading fails.

#### Scenario: Both triggers in one poll
- **WHEN** an item becomes answered and the questions session ends its turn in the same poll
- **THEN** exactly one `ANSWERED` line is printed, carrying both the turn and the id

#### Scenario: Ordinary events still hidden
- **WHEN** the questions session is in `--exclude` and changes status or turns
- **THEN** no `TURN`, `STATUS` or `IDLE` line names it; only `ANSWERED` does

#### Scenario: Unreadable queue
- **WHEN** the queue file is missing or the ask-queue module cannot be loaded
- **THEN** the watcher behaves as before for every other event and prints no `ANSWERED` line for the queue

### Requirement: The shipped skill text keeps the questions session at the top level
The generic supervision skill in this repository SHALL NOT say that the questions session must hang from the
supervisor, SHALL keep the closing session hanging from it, and SHALL tell the questions session's brief to detach
itself when the gate asks.

#### Scenario: Lineage wording
- **WHEN** the repository's `global/skills/supervisa-sesiones/` is searched
- **THEN** no sentence requires the questions session to be a child of the supervisor, and the closing session is
  still described as a child

### Requirement: The shipped skill text documents the new lines
The skill in this repository SHALL say what to do on `DETACH`, describe `ANSWERED` in its signals table and guard event
list, and carry a new top entry in `reference/cambios.md`. `supervisor-lock skill-lint` on the repository copy SHALL
report no finding that it did not report before this change.

#### Scenario: Text check
- **WHEN** the repository's `global/skills/supervisa-sesiones/` is searched
- **THEN** `DETACH` and `ANSWERED` are each documented, and the skill lint reports no new finding

### Requirement: Probes cover the change
`supervisor-lock self-test` SHALL include checks, with synthetic app records, queue items and hook payloads in its
sandbox, for the `DETACH` line, the closing role's unchanged `ADOPT`, the gate's deny-once-then-allow, and the
`ANSWERED` line on guard with the questions session excluded.

#### Scenario: Self-test
- **WHEN** `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock.SelfTestTest` runs in a temp HOME
- **THEN** it passes, and the new checks are among the `ok` lines
