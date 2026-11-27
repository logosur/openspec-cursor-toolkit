# Spec Delta — llm-pool-routing

## Purpose

Defines which work may go to the pool, to which member, in which mode and when it goes back to the main model: the task-kind catalog, the modes, the saving dial, the privacy gate, the budgets and who may call.

## ADDED Requirements

### Requirement: Work is offloaded only as a known task kind
A request to the pool SHALL name a task kind from the catalog. Each task kind SHALL declare the class of its input, the minimum power it needs, the dial level from which it is offloaded and the highest mode it may reach. A request with an unknown task kind SHALL be refused.

#### Scenario: Free-form request
- **WHEN** a caller asks the pool with a task kind that is not in the catalog
- **THEN** the request is refused with a distinct exit code and nothing is sent

### Requirement: One entry point with a fallback contract
`llm-pool ask --task <kind>` SHALL be the only way to send work to the pool. It SHALL exit 0 with the answer on standard output, or a distinct non-zero code for each of: no eligible member, refused by the privacy gate, budget exhausted, gateway unreachable, timeout, malformed answer, caller not allowed. Every non-zero code means "use the main model"; no code means "retry later".

#### Scenario: No member is active
- **WHEN** every member assigned to the task kind is `paused` or `exhausted`
- **THEN** `ask` exits with the "no eligible member" code in under a second and records the outcome

### Requirement: Modes per task kind and member
Each pair (task kind, member) SHALL be in one mode: `off`, `shadow`, `assist` or `auto`. In `shadow` the answer SHALL be recorded and never returned to the caller as usable. In `assist` the answer SHALL be returned marked as a pool answer for the main model to read. In `auto` the caller MAY act on it. A task kind SHALL never run in a mode above its declared maximum.

#### Scenario: Shadow answer
- **WHEN** `ask` runs for a pair in `shadow`
- **THEN** the caller receives the "shadow" code and behaves as if the pool did not exist, and the ledger holds the answer

#### Scenario: Task kind that may not be automatic
- **WHEN** someone sets `dialog-draft` to `auto`
- **THEN** the change is refused: its maximum mode is `assist`

### Requirement: Promotion needs evidence and the developer
A pair SHALL move from `shadow` to `assist` or `auto` only by an explicit command, and only when its scorecard has at least the configured number of judged shadow samples (default 50) and meets the task kind's thresholds. The command SHALL be refused otherwise, saying what is missing.

#### Scenario: Not enough samples
- **WHEN** a pair has 12 judged shadow samples and promotion to `auto` is requested
- **THEN** the command is refused and prints "12 of 50 samples"

### Requirement: Demotion is automatic
A pair in `auto` SHALL move to `probation` when it records the configured number of misses within the configured window (default 2 within 24 hours). In `probation` it runs in `shadow` and needs a new promotion.

#### Scenario: Second miss in a day
- **WHEN** a pair in `auto` records its second miss within 24 hours
- **THEN** it is in `probation` before the next request, and the change is audited with the two ledger rows that caused it

### Requirement: The saving dial selects what is offloaded
A dial from 0 to 3 SHALL decide which task kinds are offloaded: at level 0 none, and at each higher level the task kinds declared for that level or below. A per-project value SHALL override the machine's. The dial SHALL never raise a pair's mode above what it was promoted to.

#### Scenario: Dial at 0
- **WHEN** the dial is 0
- **THEN** `ask` exits with the "no eligible member" code for every task kind and sends nothing

#### Scenario: Dial raised with nothing promoted
- **WHEN** the dial goes from 1 to 3 and every level-3 pair is still in `shadow`
- **THEN** those task kinds run in `shadow` only

### Requirement: The dial can follow the main model's usage
In `follow-usage` mode the dial's level SHALL be computed from the main model's reported usage and thresholds in the config piece. When the usage cannot be read, the dial SHALL keep its last manual value. A manual change SHALL return the dial to `manual` mode.

#### Scenario: Usage provider missing
- **WHEN** the dial is in `follow-usage` and no usage provider is installed
- **THEN** the dial stays at its last manual value and `llm-pool status` says the usage is unknown

### Requirement: Privacy gate before every send
Before sending, the module SHALL check that the member accepts the task kind's input class, SHALL mask secrets and personal identifiers in the payload, and SHALL refuse the send to any non-local member if a secret is still detected after masking. The refusal SHALL be recorded without the payload.

#### Scenario: Private task, public-only member
- **WHEN** `log-digest` (private input) is requested and the only active member accepts `public`
- **THEN** the request is refused by the gate and the caller uses the main model

#### Scenario: Secret in the payload
- **WHEN** a payload contains a string with the shape of an API key
- **THEN** it is masked before sending, and the ledger row says one secret was masked

### Requirement: Only enabled projects use the pool
The pool SHALL serve a request only for a project listed as enabled in the override. A project on the supervision exclusion list SHALL never be enabled.

#### Scenario: Excluded project
- **WHEN** someone enables a project that the supervision config excludes
- **THEN** the command is refused with the reason

### Requirement: Only the supervisor and its child sessions may call
`ask` SHALL identify the calling session and SHALL serve it only if it is the live supervisor of an enabled project or a session of that project that the supervisor's census lists. Any other caller SHALL be refused.

#### Scenario: A session of a project without a supervisor
- **WHEN** a session of a project with no live supervisor calls `ask`
- **THEN** it is refused with the "caller not allowed" code

### Requirement: Billed members are off unless a cap is written
A member with billing `paid` SHALL be `blocked` unless the override holds a monthly cap greater than zero for it or for its provider. When the ledger's recorded spend of the month reaches the cap, the member SHALL become `exhausted` until the next month.

#### Scenario: Paid member with no cap
- **WHEN** a paid member is added and no cap exists
- **THEN** it is `blocked` with the reason "no monthly cap"

### Requirement: The free quota is rationed
Each member SHALL have a daily token budget and each task kind a share of it, with `wake-triage` served first. A request beyond the budget SHALL exit with the "budget exhausted" code.

#### Scenario: Digests use up their share
- **WHEN** `log-digest` has spent its share of a member's daily budget
- **THEN** further `log-digest` requests to that member are refused today and `wake-triage` requests are still served
