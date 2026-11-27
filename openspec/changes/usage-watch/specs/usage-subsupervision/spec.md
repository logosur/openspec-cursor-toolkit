# Spec Delta — usage-subsupervision

## Purpose

Defines the consumption sub-supervision: one session per machine that turns `usage-watch` findings into questions for the developer, records the answers and applies only what was authorised, plus the support it needs from `supervisor-lock`, the question queue and the supervision skill.

## ADDED Requirements

### Requirement: One usage role per machine, registered with supervisor-lock
`supervisor-lock usage-role --claim` SHALL keep one machine-wide record of the usage role (`session_id`, `cli_session_id`, `home_project`, `title`, `heartbeat`) under the same lock as the project locks. It SHALL take a free role, print `RESUMED` for the holder, print `HELD` and exit 3 while another holder is live, and print `STALE` and exit 4 while another holder is stale; `--claim --from <old id>` SHALL then take it over.

#### Scenario: Second claim
- **WHEN** session A holds the usage role with a fresh heartbeat and session B claims it
- **THEN** B gets `HELD` and exit 3, and the record still names A

#### Scenario: Takeover of a stale holder
- **WHEN** A's heartbeat is older than the running TTL and B claims with `--from A`
- **THEN** the record names B

### Requirement: The holder keeps, releases and shows the usage role
`supervisor-lock usage-role --beat` SHALL refresh the holder's heartbeat and exit 3 for any other session. `--release` SHALL drop the record for the holder only. `list --json` SHALL include a `usage_role` object, null when the role is free.

#### Scenario: Listing
- **WHEN** the role is held
- **THEN** `supervisor-lock list --json` has a `usage_role` object with the holder's id and home project

#### Scenario: Release by someone else
- **WHEN** session B runs `--release` while A holds the role
- **THEN** the record still names A

### Requirement: The usage role is never counted as a project's work
In every project, the census helpers SHALL treat the usage role holder like the questions and closing sessions: `open`, `closable` and `backlog` SHALL leave it out, and no closing session SHALL be told to archive it.

#### Scenario: Usage session inside a supervised project
- **WHEN** the usage role holder's working directory is a supervised project and it is idle
- **THEN** `supervisor-lock open` and `supervisor-lock closable` for that project do not list it

### Requirement: The usage watcher wakes only for a new finding or an answer
`usage-watch wait --session ID` SHALL exit 0 after printing `FINDING <id> <rule> <scope>` for every `new` finding not announced before, or `ANSWER <id>` for every `asked` finding whose queue item became `answered` or `closed`, each event once. With no such event it SHALL print nothing and keep waiting.

#### Scenario: Nothing new
- **WHEN** the store holds only findings already announced and no queue item changed, and `wait --timeout 2` runs with a simulated clock
- **THEN** stdout is only `TIMEOUT 2s`

#### Scenario: New finding
- **WHEN** `detect` adds a finding while `wait` runs
- **THEN** `wait` prints one `FINDING` line for it and exits 0, and the next `wait` does not print it again

#### Scenario: Answer
- **WHEN** the queue item of an `asked` finding is answered while `wait` runs
- **THEN** `wait` prints `ANSWER <id>` and exits 0, once

### Requirement: The usage watcher's timeout and holder check
With `--timeout 0`, the default, `wait` SHALL never time out; with a positive timeout it SHALL print `TIMEOUT <s>s` and exit 0. It SHALL exit 5 with `NOT HOLDER` on stderr when another live session holds the usage role.

#### Scenario: Not the holder
- **WHEN** session B runs `wait` while session A holds the usage role
- **THEN** B gets exit 5 and `NOT HOLDER`

### Requirement: Questions go through the existing queue, once per finding
`usage-watch ask ID --question TEXT` SHALL accept only a `new` finding and register it with `ask-queue add` (key `usage-watch:<id>`, the question followed by a `change` line naming the exact change `apply` would make and by `authorize_hint`, default `no_default`, the evidence as reason, `--order <order_text>` only when `order_text` is not empty), record the queue id and the asker's session ids, and move the finding to `asked`. The usage role SHALL NOT open a dialog itself.

#### Scenario: Supervised project
- **WHEN** a finding belongs to a project with a live lock that has a `mailbox`
- **THEN** its question goes to that project's queue


#### Scenario: Ask
- **WHEN** `ask` runs for a `new` finding in a temporary queue directory
- **THEN** the queue has one open item with key `usage-watch:<id>` whose question ends with `authorize_hint`, and the finding is `asked` with that queue id

#### Scenario: Asking twice
- **WHEN** `ask` runs again for the same finding
- **THEN** it exits 3 and the queue still has one item for it

#### Scenario: Empty order text
- **WHEN** `order_text` is empty
- **THEN** the queue item carries no `order`

### Requirement: Questions that no questions session would present go to the role's home project
A machine-wide finding, or one whose project has no live lock with a `mailbox`, SHALL be registered in the queue of the usage role's `home_project`.

#### Scenario: Unsupervised project
- **WHEN** a finding belongs to a project with no supervision lock
- **THEN** its question goes to the queue of the role's `home_project`

### Requirement: The outcome of a question is read from the queue, never chosen by the role
`usage-watch decide ID` SHALL take no outcome argument. For an `asked` finding with a trusted answer it SHALL move the finding to `authorized` when the normalised answer (case-folded, outer whitespace and punctuation stripped) is in `authorize_answers`, else to `rejected`; a `closed` item SHALL give `rejected`. It SHALL store the answer, `answered_by` and `answered_ts`. An `open`, `asked` or missing item SHALL exit 3 and change nothing.

#### Scenario: Queue item still open
- **WHEN** `decide` runs while the queue item is `open` or `asked`
- **THEN** it exits 3 and the finding stays `asked`

#### Scenario: Authorising answer from the questions session
- **WHEN** the questions session (an id other than the asker's and the role holder's) answered `Apply.`
- **THEN** `decide` moves the finding to `authorized`, with the answer text and `answered_by` in its history

#### Scenario: Any other answer
- **WHEN** the questions session answered with the `no_default` text
- **THEN** `decide` moves the finding to `rejected`

#### Scenario: Closed without an answer
- **WHEN** the queue item was closed without an answer
- **THEN** `decide` moves the finding to `rejected`

### Requirement: An answer recorded by the role or by nobody is not trusted
An answer SHALL be trusted only when its `answered_by` is not empty and is none of the ids that registered the queue item, the asker's ids recorded by `ask`, or the usage role holder's ids. `decide` on an untrusted answer SHALL exit 3 and change nothing.

#### Scenario: The role answers its own question
- **WHEN** the queue item was answered `apply` with `answered_by` equal to the usage role holder's id or to the session that ran `ask`
- **THEN** `decide` exits 3 and the finding stays `asked`

#### Scenario: Answer recorded by nobody
- **WHEN** the queue item was answered `apply` with an empty `answered_by`
- **THEN** `decide` exits 3 and the finding stays `asked`

### Requirement: Nothing is applied without a recorded answer
`usage-watch apply ID` SHALL be the only command that changes anything outside the state directory or issues a session-tool ticket. For every proposal kind it SHALL exit 3, writing nothing and issuing no ticket, when the finding is not `authorized`, or when its queue item, read again at that moment, is not a trusted authorising answer with the text recorded by `decide`. After a successful `apply` the finding SHALL be `applied`.

#### Scenario: Every other state is refused, for both kinds
- **WHEN** `apply` runs on a `config` finding and on a `session-model` finding in each of the states `new`, `asked`, `rejected`, `applied` and `measured`
- **THEN** every call exits 3, no file outside the state directory changes, and `tickets.json` holds no ticket

#### Scenario: A store edited by hand
- **WHEN** a `config` finding and a `session-model` finding are set to `authorized` in the store while their queue items are still `asked`
- **THEN** `apply` exits 3 for both, the override and the installed piece are unchanged and no ticket is issued

### Requirement: The answer authorises only the change its question names
`ask` SHALL write into the question a `change` line with the exact change `apply` would make: piece, key and value of a `config` finding; target session, field and value of a session finding. `apply` SHALL exit 3, writing nothing and issuing no ticket, when the queue item's question, read again at that moment, does not hold the change the finding holds now.

#### Scenario: A change edited after the answer
- **WHEN** an authorised `config` finding gets another key, and an authorised `session-model` finding another target session, in the store after the developer answered
- **THEN** `apply` exits 3 for both, nothing outside the state directory changes and no ticket is issued

### Requirement: A config finding is written to the override and the installed piece
A `config` finding SHALL be written into the override's piece and into the installed piece, the latter byte-identical to the installer's rendering, after both previous values are recorded. Without an override directory `apply` SHALL exit 3.

#### Scenario: Authorised config change
- **WHEN** an authorised finding proposes `agent-model-gate` `enabled` = true and `apply` runs in a temporary `HOME` with an override directory
- **THEN** both the override's and the installed `agent-model-gate.json` have `enabled` true, the previous values are in the finding, and the toolkit's `drift` reports no difference for that piece

#### Scenario: No override
- **WHEN** an authorised `config` finding is applied with no override directory
- **THEN** it exits 3 and the installed piece is unchanged

### Requirement: A session finding is applied through a ticket
A `session-model` or `session-effort` finding SHALL issue one ticket in `<state_dir>/tickets.json` naming the finding's `target_app_id`, the field, the value and an expiry `ticket_ttl_s` seconds ahead. Without a `target_app_id` it SHALL exit 3.

#### Scenario: Session model ticket
- **WHEN** `apply` runs on an authorised `session-model` finding whose `target_app_id` is known
- **THEN** it exits 0, the finding is `applied` and `tickets.json` holds one unused ticket for that session, field `model` and the proposed model

### Requirement: A note finding records how it was applied
A `note` finding SHALL require `--how` describing what was done, else `apply` SHALL exit 2.

#### Scenario: Note without a description
- **WHEN** `apply` runs on an authorised `note` finding without `--how`
- **THEN** it exits 2 and the finding stays `authorized`

### Requirement: The usage role changes a session's model or effort only with a ticket
The hook `usage-apply-gate` SHALL run before the app's tools that set a session's model or effort. When the caller is the usage role holder (by the hook input's `session_id` or `CLAUDE_CODE_HOST_SESSION_ID`), it SHALL deny the call unless an unused, unexpired ticket names the tool input's session, the tool's field and the tool input's value, and SHALL mark that ticket used when it allows the call.

#### Scenario: No ticket
- **WHEN** the role holder calls the set-model tool for a session with no ticket
- **THEN** the hook denies the call and its reason names `usage-watch apply`

#### Scenario: One ticket, one call
- **WHEN** the role holder calls the set-model tool twice with the session and model of one ticket
- **THEN** the first call passes and the ticket is marked used, and the second call is denied

#### Scenario: Expired or mismatched ticket
- **WHEN** the ticket has expired, or names another session, field or value
- **THEN** the hook denies the call

### Requirement: The ticket gate leaves everyone else alone and fails open
Calls by a session that is not the usage role holder, or with no usage role record, SHALL pass untouched. Unparseable input or an internal error SHALL let the call pass and be logged.

#### Scenario: Another session
- **WHEN** a session that is not the role holder calls the set-model tool with no ticket
- **THEN** the hook passes the call and writes nothing

#### Scenario: Unparseable input
- **WHEN** the hook receives input that is not JSON
- **THEN** it exits 0 with no output

### Requirement: The effect is measured before and after
`usage-watch measure ID` SHALL accept only an `applied` finding at least `measure_window_h` hours after it was applied, SHALL compute the rule's metric for the same scope over that window before and after the apply time, store both and move the finding to `measured`. Too early, it SHALL exit 4 and change nothing.

#### Scenario: Too early
- **WHEN** `measure` runs one hour after `apply` with a 24-hour window
- **THEN** it exits 4 and the finding stays `applied`

#### Scenario: Measured
- **WHEN** `measure` runs 24 hours after `apply` with fixtures that halve the metric
- **THEN** the finding is `measured` with both values recorded

### Requirement: The full walk never repeats a question
A finding SHALL be able to go `new → asked → authorized → applied → measured` and `new → asked → rejected`, with every answer recorded in the queue by a session other than the role, and `detect` SHALL NOT raise its id again in any of those states.

#### Scenario: Walk and re-detect
- **WHEN** a finding goes through every state with a simulated clock and `detect` runs after each step over fixtures that still show the pattern
- **THEN** the store never holds a second finding with that id and the queue holds one item for it

### Requirement: Work the role cannot apply goes to the project's supervisor
Authorised findings whose applier is `project-supervisor` SHALL appear in that project's `supervisor-lock backlog` as one `USAGE <id> <rule>: <proposal>` work line each until applied. Without `usage-watch` installed, or when it fails, `backlog` SHALL behave as before and log the failure.

#### Scenario: Backlog line
- **WHEN** an authorised `note` finding belongs to project P
- **THEN** `supervisor-lock backlog` for P lists it as work, and after `usage-watch apply ID --how ...` it no longer does

#### Scenario: Script missing
- **WHEN** `usage-watch` is not on the installed path
- **THEN** `supervisor-lock backlog` output is the same as without this change

#### Scenario: Citation declared
- **WHEN** `scripts/validate-toolkit.py` runs on the branch
- **THEN** it reports no `global-citation` error for `supervision` citing `usage-watch` or for `usage` citing `ask-queue` and `supervisor-lock`

### Requirement: Without supervision the role commands say so
When `ask-queue` or `supervisor-lock` is not installed, `ask`, `decide` and `wait` SHALL exit 6 with one line saying that the supervision module is needed; measuring commands SHALL work as usual.

#### Scenario: Measuring only
- **WHEN** only the `core` and `usage` modules are installed in a temporary `HOME`
- **THEN** `tick` exits 0 and `wait --session X` exits 6

### Requirement: The supervision skill and rule describe the role generically
The repository SHALL ship a generic reference `global/skills/supervisa-sesiones/reference/subsupervision-consumo.md`, installed by `supervision`, covering the claim, watcher, `show`, ask, decide, measure and hand-off, and saying that the ticket gate refuses a session tool call without `apply`. The skill's reference table SHALL name it, `global/rules/modelo-por-rol.md` SHALL give the role the cheaper model, and no machine-specific name, figure or quote SHALL appear.


#### Scenario: Validator and privacy
- **WHEN** `scripts/validate-toolkit.py` and `scripts/privacy-check.py --require-private` run on the branch
- **THEN** both exit 0

### Requirement: Self-test and contract cover the role and the watcher
`usage-watch self-test` SHALL also check, in its throwaway home, the state walk, the refused transitions (including an untrusted answer and a hand-edited store), the ticket gate, and the watcher's silence, `FINDING`, `ANSWER` and `NOT HOLDER`. `supervisor-lock self-test` SHALL check the usage-role claim, `HELD`, takeover and helper-row exclusion. `global/contracts/usage-apply-gate.yaml` SHALL hold safe probes only (an unrelated tool, a non-holder call, unparseable input).

#### Scenario: Self-tests pass
- **WHEN** `usage-watch self-test` and `supervisor-lock self-test` run from the repository copy
- **THEN** both report no failed check

#### Scenario: Contract probes
- **WHEN** the toolkit runs the `usage-apply-gate` contract in a temporary `HOME`
- **THEN** every probe passes and nothing outside the temporary `HOME` changes
