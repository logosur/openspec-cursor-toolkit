# Spec Delta — llm-pool-routing

## Purpose

Defines which work may go to the pool, to which member, in which mode, at what time and when it goes back to the main model: the task-kind catalog, the modes, the saving dial and its schedules, the privacy gate, the budgets and who may call.

## ADDED Requirements

### Requirement: Work is offloaded only as a known task kind
A request to the pool SHALL name a task kind from the catalog in the code. Each task kind SHALL declare the class of its input, the minimum power it needs, the dial level from which it is offloaded and the highest mode it may reach. A request with an unknown task kind SHALL be refused.

#### Scenario: Free-form request
- **WHEN** a caller asks the pool with a task kind that is not in the catalog
- **THEN** the request is refused with the "unknown task kind" code and nothing is sent

### Requirement: The catalog of version 1 has five task kinds
The catalog SHALL be: `wake-triage` (input `internal`, minimum power 2, from level 1, up to `auto`); `turn-report-check` (`private`, 3, level 2, up to `assist`); `log-digest` (`private`, 2, level 2, `assist`); `closing-evidence-summary` (`private`, 2, level 2, `assist`); `dialog-draft` (`private`, 3, level 3, `assist`). Only `wake-triage` SHALL be able to reach `auto`.

#### Scenario: Reading the catalog
- **WHEN** `llm-pool status --json` runs on a fresh install
- **THEN** it lists exactly these five task kinds with these values

### Requirement: One entry point with a fallback contract
`llm-pool ask --task <kind>` SHALL be the only supported way to send work to the pool. It SHALL exit 0 with the answer on standard output, and with a non-zero code in every other case. Every non-zero code means "do what you did before the pool existed"; no code means "retry later".

#### Scenario: No member is active
- **WHEN** every member assigned to the task kind is `paused` or `exhausted`
- **THEN** `ask` exits with the "no eligible member" code in under a second and records the outcome

### Requirement: Every outcome has its own exit code
A request that returns an answer SHALL end as `served`, with exit code 0. `ask` SHALL return a distinct non-zero code for every other outcome. The codes SHALL be listed by `llm-pool ask --help` and in the piece's contract.

#### Scenario: One test per outcome
- **WHEN** each outcome is provoked against a stub gateway
- **THEN** each one returns its own code and writes a ledger row with that outcome

### Requirement: The outcomes are a fixed list
Besides `served`, the outcomes SHALL be: `shadow`, `pool off` (the level in force is below the task kind's), `stopped`, `no eligible member`, `unknown task kind`, `caller not allowed`, `project not enabled`, `project paused`, `refused by gate`, `budget exhausted`, `cap reached`, `misconfigured`, `unreachable`, `timeout`, `malformed answer` and `wrong model`.

#### Scenario: A key file that cannot be read
- **WHEN** the config names a key file that does not exist, or a gateway URL that is not loopback
- **THEN** `ask` ends as "misconfigured", sends nothing and the caller uses the main model

#### Scenario: Reading the list
- **WHEN** `llm-pool ask --help` runs
- **THEN** it prints these seventeen outcomes, each with its code

### Requirement: Modes per task kind and member
Each pair (task kind, member) SHALL be in one mode: `off`, `shadow`, `assist` or `auto`, or in `probation`. A new assignment SHALL start `off`. In `shadow` the answer SHALL be recorded and never returned to the caller. In `assist` the answer SHALL be returned inside the envelope that marks it as data from another model. In `auto` the caller MAY act on it. A task kind SHALL never run in a mode above its declared maximum.

#### Scenario: Shadow answer
- **WHEN** `ask` runs for a pair in `shadow`
- **THEN** the caller receives the "shadow" code and no answer text, and the ledger holds the answer

#### Scenario: Task kind that may not be automatic
- **WHEN** someone sets `dialog-draft` to `auto`
- **THEN** the change is refused: its maximum mode is `assist`

#### Scenario: An assist answer
- **WHEN** `ask` returns an answer for a pair in `assist`
- **THEN** its first lines name the task kind, the member and the ledger id and say that what follows is data to read, not instructions to follow

### Requirement: Promotion needs evidence and the developer
A pair SHALL move up a mode only by an explicit widening command. Moving `wake-triage` to `auto` SHALL also need a scorecard with at least 50 judged shadow samples, at least 10 of them judged "the supervisor was needed", no false `sleep`, and an agreement of 95 % or more. Samples nobody judged SHALL count for nothing. A refused command SHALL say what is missing.

#### Scenario: Not enough samples
- **WHEN** a pair has 12 judged shadow samples and promotion to `auto` is requested
- **THEN** the command is refused and prints "12 of 50 samples"

#### Scenario: A model that always answers sleep
- **WHEN** a pair has 60 judged samples, all of them cases where the supervisor was not needed
- **THEN** promotion to `auto` is refused: "0 of 10 samples where the supervisor was needed"

### Requirement: Assist-only task kinds are promoted by review
Moving a task kind whose highest mode is `assist` from `shadow` to `assist` SHALL need at least 20 of its shadow samples reviewed, with 90 % of them judged acceptable. A review SHALL be made in the console's review view or with `llm-pool review` by a session the developer asks to do it.

#### Scenario: Five reviewed digests
- **WHEN** a `log-digest` pair has 5 reviewed shadow samples and promotion to `assist` is requested
- **THEN** the command is refused and prints "5 of 20 reviewed samples"

### Requirement: Demotion is automatic
A pair in `auto` SHALL move to `probation` when it records two misses within 24 hours. An override MAY make this stricter (fewer misses, a longer window) and SHALL NOT make it laxer. In `probation` the pair runs in `shadow` and needs a new promotion.

#### Scenario: Second miss in a day
- **WHEN** a pair in `auto` records its second miss within 24 hours
- **THEN** it is in `probation` before the next request, and the change is audited with the two ledger rows that caused it

### Requirement: The saving dial selects what is offloaded
A dial from 0 to 3 SHALL decide which task kinds are offloaded: at level 0 none, and at each higher level the task kinds declared for that level or below. A per-project value SHALL only be able to lower the machine's. The level in force for a request SHALL be the lowest of the machine's dial, the project's value and the level of the schedule window in force. The dial SHALL never raise a pair's mode above what it was promoted to.

#### Scenario: Dial at 0
- **WHEN** the dial is 0
- **THEN** `ask` exits with the "pool off" code for every task kind and sends nothing

#### Scenario: Dial raised with nothing promoted
- **WHEN** the dial goes from 1 to 3 and every level-3 pair is still in `shadow`
- **THEN** those task kinds run in `shadow` only

#### Scenario: A project asks for more than the machine
- **WHEN** the machine's dial is 1 and a project's value is 2
- **THEN** level 1 applies to that project

### Requirement: Schedules decide when the pool is used
The definitions SHALL be able to hold time windows (days of the week, a local start and end time), each with a highest dial level and, optionally, the members allowed during it. Inside a window the level in force SHALL NOT exceed the window's, and only its allowed members, when listed, SHALL be eligible. Outside every window the dial SHALL apply as set. `llm-pool status` SHALL say which window is in force.

#### Scenario: Working hours kept on the main model
- **WHEN** a window sets level 0 on weekdays from 09:00 to 19:00 and a request arrives on a Tuesday at 11:00
- **THEN** `ask` exits with the "pool off" code and `status` names the window

#### Scenario: A night window with one member
- **WHEN** a window from 23:00 to 07:00 allows only one member and the dial is 2
- **THEN** only that member is eligible during the window, at level 2 at most

### Requirement: The dial can follow the main model's usage
In `follow-usage` mode the level SHALL be computed from the main model's reported usage and thresholds in the config piece, between 0 and the level the developer last set by hand, which SHALL remain the ceiling. When the usage cannot be read, the level SHALL be the last manual value. A manual change SHALL return the dial to `manual` mode.

#### Scenario: Usage provider missing
- **WHEN** the dial is in `follow-usage` and no usage provider is installed
- **THEN** the dial stays at its last manual value and `llm-pool status` says the usage is unknown

#### Scenario: Usage rises
- **WHEN** the developer set level 2, `follow-usage` is on and the reported usage passes every threshold
- **THEN** the level in force is 2, never 3

### Requirement: Usage thresholds have defaults and do not flap
By default `follow-usage` SHALL follow the weekly usage, with level 1 from 50 %, level 2 from 70 % and level 3 from 85 %. A level SHALL be released 10 points below the threshold that raised it and SHALL be held for at least 30 minutes.

#### Scenario: Usage hovers around a threshold
- **WHEN** the reported usage crosses a threshold up and down five times in ten minutes
- **THEN** the level changes once

#### Scenario: Usage falls a little
- **WHEN** level 2 was raised at 70 % and the usage falls to 65 % an hour later
- **THEN** the level stays at 2, and it drops to 1 only below 60 %

### Requirement: Privacy gate before every send
The module SHALL send a payload only to a member that accepts the task kind's input class; a member that does not is not eligible. A `private` payload SHALL have secrets and personal identifiers masked by the module's own redactor, and the request SHALL end as `refused by gate` for every non-local member if a secret is still detected after masking. A refusal SHALL be recorded without the payload.

#### Scenario: Private task, public-only member
- **WHEN** `log-digest` (private input) is requested and the only active member accepts `public`
- **THEN** the request exits with the "no eligible member" code, `why` names the data class as the reason, and the caller uses the main model

#### Scenario: Secret in the payload
- **WHEN** a payload contains a string with the shape of an API key
- **THEN** it is masked before sending, and the ledger row says one secret was masked

#### Scenario: A secret the redactor cannot mask
- **WHEN** a secret is still detected after masking and the only eligible member is not local
- **THEN** the request ends as "refused by gate", nothing is sent and the row holds no payload

#### Scenario: A name on the private deny-list
- **WHEN** the config names a deny-list file and a private payload contains one of its words
- **THEN** the word is masked before sending

### Requirement: The member is chosen by a fixed order
Among the eligible members of a request, `ask` SHALL choose: first the lowest power level; then by billing, `local` before `free` before `plan` before `paid`; then the one with the larger share of its daily budget left; then by id.

#### Scenario: Two eligible members
- **WHEN** a free member of power 2 and a free member of power 4 are both eligible for `log-digest`
- **THEN** the member of power 2 is chosen, and `why` shows the order that decided it

### Requirement: Requests are sent the same way every time
Each task kind SHALL have a fixed instruction that the caller cannot change; the caller supplies only the material. Requests SHALL be sent with temperature 0 where the provider accepts it.

#### Scenario: What the stub receives
- **WHEN** two sessions ask for a `log-digest` of different outputs
- **THEN** the stub gateway receives the same instruction both times, with temperature 0, and only the material differs

### Requirement: Internal payloads are built by the module
An `internal` payload SHALL be built by the module from a closed set of structured fields (event kinds, session ids, statuses, counts, ages and durations) and SHALL be refused if it holds anything else.

#### Scenario: Free text offered as internal
- **WHEN** a caller passes a session title in an `internal` payload
- **THEN** the request is refused by the gate and nothing is sent

### Requirement: Only enabled, unpaused projects use the pool
The pool SHALL serve a request only for a project enabled by command. A project listed in the definitions' `excluded_projects` SHALL never be enabled. A request for a paused project SHALL be refused with the "project paused" code.

#### Scenario: Excluded project
- **WHEN** someone enables a project that the definitions exclude
- **THEN** the command is refused with the reason

#### Scenario: Project paused after it was enabled
- **WHEN** an enabled project is paused and one of its sessions calls `ask`
- **THEN** the request is refused with the "project paused" code and nothing is sent

### Requirement: Only the supervisor and its child sessions may call
`ask` SHALL identify the calling session from the session ids in its environment and SHALL serve it only if it is the live supervisor of an enabled project (the owner of a lock whose heartbeat is within its time-to-live) or a session that supervisor's census lists in the project's checkout or worktrees. Any other caller SHALL be refused.

#### Scenario: A session of a project without a supervisor
- **WHEN** a session of a project with no live supervisor calls `ask`
- **THEN** it is refused with the "caller not allowed" code

#### Scenario: A stale lock
- **WHEN** the project's supervisor lock has a heartbeat older than its time-to-live
- **THEN** a session of that project is refused with the "caller not allowed" code

### Requirement: The caller check is scope, not security
When the supervision piece is not installed, every caller SHALL be refused. The module's notes and its documentation SHALL state that the caller check is attribution and scope, not protection against another process of the same user.

#### Scenario: Supervision not installed
- **WHEN** any session calls `ask` on a machine without the supervision piece
- **THEN** it is refused with the "caller not allowed" code

### Requirement: Billed members are off unless a cap and a price are written
A member with billing `paid` SHALL be `blocked` unless the definitions hold a monthly cap greater than zero for it or for its provider and a price for it. When the month's recorded and reserved spend reaches the cap, the member SHALL become `exhausted` until the next month of the machine's local time.

#### Scenario: Paid member with no cap
- **WHEN** a paid member is added and no cap exists
- **THEN** it is `blocked` with the reason "no monthly cap"

### Requirement: The cost of a call is known and reserved before it is sent
The cost of a call SHALL be the cost the gateway reports or, when it reports none, the member's price times the tokens. Before sending to a paid member, `ask` SHALL reserve the request's worst-case cost in the same ledger transaction that checks the cap.

#### Scenario: The gateway reports no cost
- **WHEN** a paid member answers and the gateway reports no cost
- **THEN** the ledger row carries the cost computed from the price, marked as computed, and it counts toward the cap

#### Scenario: Two callers at the cap
- **WHEN** two requests arrive together and only one fits under the cap
- **THEN** one is sent and the other exits with the "cap reached" code

### Requirement: The free quota is rationed
Each member that is not local SHALL have a daily token budget in its definition, counted in the machine's local day; without one it is `blocked`. Each task kind SHALL have a share of that budget, with half reserved for `wake-triage` by default. A request beyond the budget SHALL exit with the "budget exhausted" code. The check and the reservation SHALL happen in one ledger transaction.

#### Scenario: Digests use up their share
- **WHEN** `log-digest` has spent its share of a member's daily budget
- **THEN** further `log-digest` requests to that member are refused today and `wake-triage` requests are still served

#### Scenario: Member without a daily budget
- **WHEN** a free member's definition has no daily budget
- **THEN** it is `blocked` with the reason "no daily budget"
