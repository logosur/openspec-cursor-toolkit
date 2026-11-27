# developer-question-batches Specification

## Purpose

Defines when a question queued for the developer (`ask-queue`) is presented to him before the supervision's final batch, how the supervisor learns that it must do so, and what sessions and reports may say about questions that were not presented.

## Requirements

### Requirement: A queued question is blocking-due by order or by age
`ask-queue` SHALL treat an item as blocking-due when its status is `open`, it is not radical, and either it carries a non-empty `order`, or its `blocks` field names real work and the item is at least `ask_due_after_h` hours old. A `blocks` field names real work unless it is empty or its first word, case- and accent-folded, is `nada`, `nothing`, `none`, `ninguno`, `ninguna` or `ningun`.

#### Scenario: An order makes it due at once
- **WHEN** a session runs `ask-queue add --order "<the developer's words>" …` and lists `ask-queue list --due` a second later
- **THEN** the new item is listed with `due_reason` `order`

#### Scenario: Real work blocked for longer than the threshold
- **WHEN** an open item with `blocks` "el envío de la candidatura" is 25 hours old and `ask_due_after_h` is 24
- **THEN** it is listed by `ask-queue list --due` with `due_reason` `blocks` and its age in hours

#### Scenario: Too young
- **WHEN** the same item is 23 hours old
- **THEN** it is not listed

#### Scenario: Blocks nothing
- **WHEN** an open item 100 hours old has `blocks` "Nada", "nada: solo su archivado", "Ninguno" or an empty text
- **THEN** it is not listed

#### Scenario: Already presented, answered, closed or radical
- **WHEN** an item is `asked`, `answered`, `closed`, or radical
- **THEN** it is not listed, whatever its age or order

#### Scenario: Items queued before this change
- **WHEN** an item written before this change has no `order` field
- **THEN** only the age rule applies to it, and every other subcommand treats it as before

### Requirement: The order flag is validated and only ever added
`ask-queue add` SHALL refuse an empty or blank `--order` with exit code 2. On a duplicate (same key or same normalized question) a given `--order` SHALL replace the stored order, and an add without `--order` SHALL leave the stored order in place.

#### Scenario: Blank order
- **WHEN** `ask-queue add … --order "  "` runs
- **THEN** it exits 2 and no item is written

#### Scenario: A later plain add keeps the order
- **WHEN** an item was added with `--order "hazlo ya"` and the same question is added again without `--order`
- **THEN** the item keeps `order` "hazlo ya" and the same id is printed

### Requirement: One partial batch per project per window
`ask-queue` SHALL allow a partial batch for a project when it has blocking-due items and either one of them carries an `order`, or no non-radical item of the project has an `asked_ts`, or the newest such `asked_ts` is at least `ask_partial_batch_window_h` hours old. `ask-queue list --due` SHALL report, per project, whether the batch is allowed now or when the window opens.

#### Scenario: Window open
- **WHEN** a project has two due items and its newest non-radical `asked_ts` is 13 hours old with a 12-hour window
- **THEN** the text output of `list --due` says the partial batch is due now with 2 items

#### Scenario: Window closed
- **WHEN** the newest non-radical `asked_ts` is 2 hours old and no due item carries an order
- **THEN** the items are still listed and the project line says the window is closed until the time it opens

#### Scenario: A new order opens the window
- **WHEN** the window is closed and a due item carrying an order appears
- **THEN** the partial batch is allowed now

#### Scenario: A radical asked recently does not close it
- **WHEN** the only recent `asked_ts` belongs to a radical item
- **THEN** the window is open

### Requirement: Thresholds are configuration
`ask-queue` SHALL read `ask_due_after_h` (default 24) and `ask_partial_batch_window_h` (default 12) from the `supervision` config piece. A value that is not a finite number greater than or equal to 0 SHALL keep the default. The shipped config piece SHALL carry the defaults.

#### Scenario: Configured values
- **WHEN** the piece sets `ask_due_after_h` to 2 and an open item blocking work is 3 hours old
- **THEN** the item is due

#### Scenario: Wrong value
- **WHEN** the piece sets `ask_due_after_h` to "soon", -1 or true
- **THEN** the threshold is 24 hours

### Requirement: The supervisor is told when a partial batch is due
`supervisor-lock` SHALL report `ASKDUE <n> <ids> (…)` to the owner of a project's lock when `ask-queue` allows a partial batch for that project: on stderr after every `beat`, and as an event of `wait --owner`, also with `--guard`. The watcher SHALL announce the same set of due ids at most once per 6 hours and SHALL announce a set that gained an id at once. Any failure to read the queue SHALL produce no line and SHALL NOT change the exit code or the other output.

#### Scenario: Beat with a due batch
- **WHEN** the lock owner runs `beat` and its project has one due item carrying an order
- **THEN** stderr carries a line starting with `ASKDUE 1 ` that names the item id and `ask-queue list --due`

#### Scenario: Window closed
- **WHEN** the project's due items carry no order and the window is closed
- **THEN** neither `beat` nor the watcher prints `ASKDUE`

#### Scenario: Guard
- **WHEN** the watcher runs with `--guard`
- **THEN** `ASKDUE` is one of the events it reports

#### Scenario: Unchanged set
- **WHEN** the watcher has announced a set of due ids and is re-armed an hour later with the same set
- **THEN** it does not announce it again

#### Scenario: No queue available
- **WHEN** `ask-queue` cannot be loaded
- **THEN** `beat` exits as it would without this change and prints no `ASKDUE` line

### Requirement: Deny texts name both early paths
The deny texts of the ask gate that say only a radical course goes to the questions session before the final batch SHALL also name the partial batch of blocking-due questions (`ask-queue list --due`).

#### Scenario: Owner deny text
- **WHEN** the ask gate denies a question to the lock owner
- **THEN** the text names the radical path and the partial batch, in one line

### Requirement: Queueing texts teach blocks and order
The texts that tell a session how to queue a hard limit SHALL tell it to write what it really blocks and to add `--order "<the developer's words>"` when it blocks something the developer ordered.

#### Scenario: Supervised and absent deny texts
- **WHEN** the gate denies a question to a supervised session or to a free session whose developer is away
- **THEN** the text mentions `--order` for questions that block an order of the developer

### Requirement: Skill and rules describe the same model
The supervision skill, the three supervision rules and the decision panel skill SHALL describe the final batch at the end and, before it, only a unanimous radical course and the partial batch of blocking-due questions.

#### Scenario: Reading any of them
- **WHEN** a session reads the supervision skill core, `f5-decisiones.md`, any of the three rules or the panel skill
- **THEN** each names the final batch and the same two early paths, and none says that only a radical goes before the end

### Requirement: No report blames an unasked question
The supervision skill SHALL forbid saying, in a status report, a summary or a session's final message, that work waits for the developer's answer, or needs something only he has, about a question that was not presented to him; the supervisor SHALL trigger the partial batch instead, and say in one line in which session the dialog will open.

#### Scenario: Status report with an unpresented blocking question
- **WHEN** a supervisor writes a status report and a queued question that blocks work has never been presented
- **THEN** the report does not say the work waits for his answer; the supervisor runs `ask-queue list --due` and sends the partial batch to its questions session, or says when the window opens

### Requirement: Behaviour without a live supervisor is unchanged
`ask-queue-prompt` SHALL keep its current behaviour: without a live supervision lock it injects the unasked items into the session that queued them or into the project's questions session; with one it injects nothing.

#### Scenario: Free project
- **WHEN** no supervision lock is alive and the developer writes in the session that queued an item carrying an order
- **THEN** the hook injects that item exactly as it injects any other unasked item
