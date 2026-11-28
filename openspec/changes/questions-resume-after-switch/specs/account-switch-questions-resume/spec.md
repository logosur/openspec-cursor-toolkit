## ADDED Requirements

### Requirement: A switch lists the questions session with unanswered questions

At a switch, `account-switch` SHALL list with kind `questions`, carrying the ids, the `mailbox` session of a
supervisor lock with a heartbeat at most 24 hours old that has at least one ask-queue item in status `asked`
addressed to its local or CLI id, whatever its transcript shape and however old its last activity. Each such
session SHALL get one row with only its own ids. An item that was answered, or dismissed with `ask-queue close`, SHALL
give no row.

#### Scenario: Dialog open and quiet for hours

- **GIVEN** a lock with `mailbox` `local_box`, one item `asked` to `local_box`, a transcript ending in a question tool
  call with no result and a last activity older than 6 hours
- **WHEN** the stopped sessions are collected
- **THEN** `local_box` is listed with kind `questions` and that item's id

#### Scenario: Cut by the limit with unanswered questions

- **GIVEN** the same lock and item and a transcript whose last answer is the limit error
- **WHEN** the stopped sessions are collected
- **THEN** its kind is `questions`, not `hard`

#### Scenario: Nothing asked to it

- **GIVEN** a registered mailbox whose items are all `open` or `asked` to another session, or that has no item, and an
  idle transcript
- **WHEN** the stopped sessions are collected
- **THEN** it is not listed

#### Scenario: Answered or dismissed items

- **GIVEN** a registered mailbox whose only items were `asked` to it and are now `answered` or `closed`
- **WHEN** the stopped sessions are collected
- **THEN** it is not listed

#### Scenario: Several projects

- **GIVEN** two locks of different projects with different mailboxes, each with its own `asked` item
- **WHEN** the stopped sessions are collected
- **THEN** each mailbox has one row of kind `questions` with its own id only

### Requirement: Existing exclusions and a missing queue keep the earlier behavior

Archived sessions, the caller's own session, resume-task runs and paused projects SHALL stay excluded, an owner or
closer of a lock SHALL keep its current handling, no session SHALL be listed twice, and an ask queue that cannot be
read SHALL NOT remove or change any other row.

#### Scenario: Excluded or stale

- **GIVEN** an `asked` item for the mailbox, and either a lock heartbeat older than 24 hours, an archived record or a
  paused project
- **WHEN** the stopped sessions are collected
- **THEN** it is not listed as `questions`

#### Scenario: Heartbeat of 20 hours

- **GIVEN** the same item and a lock whose heartbeat is 20 hours old
- **WHEN** the stopped sessions are collected
- **THEN** the mailbox is listed with kind `questions`

#### Scenario: Mailbox named by two locks

- **GIVEN** two locks naming the same mailbox, each project with an `asked` item addressed to it
- **WHEN** the stopped sessions are collected
- **THEN** it is listed once, with both ids

#### Scenario: One project's queue is corrupt

- **GIVEN** two mailboxes of two projects with `asked` items and one project's queue file holding bytes that are not
  UTF-8, which makes the whole listing fail
- **WHEN** the stopped sessions are collected
- **THEN** the other project's mailbox is still listed with kind `questions`, the rows of other kinds are unchanged and
  nothing raises

#### Scenario: The queue cannot be read

- **GIVEN** a registered mailbox and an `ask-queue` that is missing, fails or prints something that is not a JSON list
- **WHEN** the stopped sessions are collected
- **THEN** no row has kind `questions`, the other sessions are listed as before and nothing raises

#### Scenario: Owner or closer also named as mailbox

- **GIVEN** a session that is the `session_id` of one lock and the `mailbox` of another, with an `asked` item
- **WHEN** the stopped sessions are collected
- **THEN** its kind is the one it would have had without the `mailbox` entry, and it is listed once

### Requirement: The questions session is told to present its pending questions again

The claim steps SHALL give each listed questions session its own text, which starts with the account-switch marker,
names its pending ids with `ask-queue pending`, and orders it to present again those still `asked` with the same
questions and options without changing a word, in chained dialogs of up to four, each carrying `ask-queue:<id>,<id>`
in `metadata.source`, never the generic resume text. `mine` SHALL repeat it and the switch
notice SHALL count these sessions.

#### Scenario: Steps with a questions session and a cut session

- **GIVEN** an event with a `hard` row and a `questions` row with ids `q1` and `q2`
- **WHEN** a session claims it
- **THEN** the steps contain the generic text for the first, and for the second a text with the marker,
  `ask-queue pending q1 q2`, «sin cambiar una palabra», «hasta cuatro por diálogo» and `ask-queue:<id>,<id>`

#### Scenario: Only a questions session

- **GIVEN** an event whose only row is of kind `questions`
- **WHEN** a session claims it
- **THEN** step 1 carries its text and the `account-switch mine` instruction, and no generic text appears

#### Scenario: The claimant checks again after a compaction

- **GIVEN** a claimed event with a questions row that has no delivery
- **WHEN** the claimant runs `mine`
- **THEN** the output lists the session and the full text to send, and the event file is not written

#### Scenario: The switch notice

- **GIVEN** a new account with usage and one questions row
- **WHEN** `on-switch` runs
- **THEN** the notice says that one questions session will be asked to present its questions again

### Requirement: A questions row stays pending while its questions are unanswered

A questions row SHALL stay pending until its session receives the resume, is archived, or no item in status `asked` is
addressed to it. Having run a turn since the switch SHALL NOT drop it. The ids SHALL be refreshed when the event is
claimed. An id the queue listing does not show at all (the queue cannot be read, or its file or line is corrupt) is
unknown, not answered: the row SHALL keep it.

#### Scenario: Answered before the claim

- **GIVEN** a questions row whose items are all `answered` by the time of the claim, and no other row
- **WHEN** a session claims the event
- **THEN** nobody is asked to send anything and the event is marked done

#### Scenario: Partly answered

- **GIVEN** a row with `q1` and `q2` where `q1` is now `answered`
- **WHEN** a session claims the event
- **THEN** the saved row and the text name only `q2`

#### Scenario: Ran a turn, no delivery

- **GIVEN** a questions session with an assistant entry after the switch, no delivery and an `asked` item
- **WHEN** the pending sessions are computed
- **THEN** it is still pending

#### Scenario: Already delivered

- **GIVEN** the marker delivered in its transcript after the switch
- **WHEN** the pending sessions are computed
- **THEN** it is not pending

#### Scenario: Queue unreadable at claim time

- **GIVEN** a questions row with `q1` and an `ask-queue` that fails
- **WHEN** a session claims the event
- **THEN** the row stays with `q1` and the event is not marked done

#### Scenario: Corrupt line or unreadable file at claim time

- **GIVEN** a questions row with `q1` and a queue file where the line of `q1` is garbage, or the file cannot be opened,
  so the listing succeeds without `q1`
- **WHEN** the pending sessions are computed
- **THEN** the row stays with `q1`

### Requirement: Supervisor and closing rows do not change

A questions row SHALL NOT change which supervisor or closing sessions are listed, their kind, the rule that keeps them
pending, or the text they and the cut sessions receive.

#### Scenario: Supervisor, closer and questions session together

- **GIVEN** idle sessions that are the owner and the closer of a lock, its mailbox with an `asked` item and a cut
  session
- **WHEN** they are collected and the event is claimed
- **THEN** owner and closer are `watcher` rows whose block carries exactly the watcher text, the cut session's block
  carries exactly the generic text, and neither block lists the mailbox

#### Scenario: A watcher still drops after a turn

- **GIVEN** an event with a `watcher` row and a `questions` row, both sessions with a turn after the switch
- **WHEN** the pending sessions are computed
- **THEN** only the `questions` row is left

### Requirement: The message gate accepts the new text without relaxing

The existing account-switch exception of the cross-project gate SHALL let the questions text through to a listed
questions session and SHALL refuse it for a session the event does not list.

#### Scenario: Listed and unlisted recipient

- **GIVEN** a fresh claimed event listing one session with kind `questions`
- **WHEN** the claimant sends to it the questions text exactly as `account-switch` builds it, and then to a session that
  is not listed
- **THEN** the first send is allowed and the second is denied
