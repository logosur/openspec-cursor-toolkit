# Spec Delta — supervision-offload

## Purpose

Defines what a supervisor and its child sessions hand to the pool, and the rules that keep a wrong pool answer from stalling or damaging work.

## ADDED Requirements

### Requirement: The pool is optional for supervision
Supervision SHALL work unchanged when the `llm-pool` module is not installed, the dial is 0, the project is not enabled or the gateway is unreachable. Every offload point SHALL have the behaviour it had before as its fallback.

#### Scenario: Module not installed
- **WHEN** the supervision module runs on a machine without `llm-pool`
- **THEN** the watcher wakes the supervisor for every event exactly as before and prints nothing about the pool

### Requirement: Hard events are never triaged
The watcher SHALL send to triage only soft events: a timeout with no event, a status change that is not the end of a turn, and the repeated notices of the wake-economy rules. Every other event SHALL wake the supervisor at once and SHALL NOT be sent to the pool. The list of soft events SHALL be configuration that can only be narrowed in an override.

#### Scenario: A session crashes while the pool is in auto
- **WHEN** the watcher sees a crash event
- **THEN** the supervisor is woken at once and no pool request is made

#### Scenario: A message from the developer
- **WHEN** the developer writes in the supervisor's session
- **THEN** no triage runs for that wake

### Requirement: The triage brief carries no private content
The brief sent for `wake-triage` and `wake-digest` SHALL contain only: the event lines, counts and ages, session titles, the supervisor's list of work in flight with its deadlines, and the last lines of the supervisor's own register. It SHALL NOT contain transcript text, code, command output or file contents.

#### Scenario: Building the brief
- **WHEN** a brief is built for a timeout
- **THEN** its size is below the configured limit (default 4 000 tokens) and a test shows that no transcript text can enter it

### Requirement: A sleep is bounded
In `auto`, the watcher SHALL honour a `sleep` verdict by continuing to wait instead of exiting, only if all of these hold: the next forced wake is not later than the nearest deadline of the work in flight; the time since the supervisor's last wake stays below the maximum silent time (default 2 hours); and fewer than the configured number of consecutive sleeps (default 4) have been honoured. Otherwise it SHALL wake the supervisor.

#### Scenario: Fifth soft event in a row
- **WHEN** four consecutive sleeps were honoured and a fifth soft event arrives
- **THEN** the supervisor is woken, with the digest of the five events

#### Scenario: Deadline inside the wait
- **WHEN** a `sleep` would keep the supervisor asleep past the deadline of a job in flight
- **THEN** the supervisor is woken at that deadline at the latest

### Requirement: Anything but a clean sleep is a wake
A triage that ends in a timeout, an error, a refusal, a malformed answer, any exit code other than success, or a verdict other than `sleep` SHALL wake the supervisor. The triage's own time limit SHALL be short (default 20 seconds).

#### Scenario: The model answers with prose
- **WHEN** the triage answer is not one of the two verdicts in the required format
- **THEN** the supervisor is woken and the ledger row is "malformed answer"

### Requirement: A wake after sleeps says what was slept
When the supervisor is woken after one or more honoured sleeps, the watcher's output SHALL list each slept event with its time and the reason the pool gave, before the event that woke it.

#### Scenario: Reading the wake
- **WHEN** a supervisor wakes after two honoured sleeps
- **THEN** the first lines of the watcher's output name both slept events and their ledger ids

### Requirement: The supervisor judges the sleeps at each wake
The supervision skill SHALL tell the supervisor to judge, at each wake that follows sleeps, whether any slept event needed action earlier, and to record it with one command per miss. Sleeps not marked as missed by the end of that tick SHALL count as agreed.

#### Scenario: Nothing was missed
- **WHEN** the supervisor's tick ends without recording a miss
- **THEN** the slept rows are marked `agreed`

### Requirement: Shadow triage changes nothing
In `shadow`, the watcher SHALL run the triage, record the verdict and wake the supervisor exactly as without the pool. The row SHALL later be judged by what the supervisor did on that wake: a wake after which the supervisor only re-armed the watcher agrees with `sleep`; any other action agrees with `wake`.

#### Scenario: Shadow sleep, supervisor acted
- **WHEN** the pool said `sleep` in shadow and the supervisor sent a message to a child session on that wake
- **THEN** the row is judged `missed`

### Requirement: Digests are read by the main model, never acted on alone
`turn-report-check`, `log-digest`, `closing-evidence-summary` and `dialog-draft` SHALL be used by a session only as input it reads: the session SHALL be able to open the original, and SHALL do so before any action that cannot be undone. A digest SHALL say what it left out (size of the original, number of lines dropped).

#### Scenario: A test log of two megabytes
- **WHEN** a child session asks for a `log-digest` of a long test output and a member that accepts private data is active
- **THEN** it receives the failing tests with their locations and the count of lines dropped, and reads the original only for the failures it will fix

#### Scenario: No member accepts private data
- **WHEN** no active member accepts `private`
- **THEN** the session reads the output itself, as before

### Requirement: Scope is the supervisor and its child sessions
Only the live supervisor of an enabled project and the sessions its census lists SHALL use these offload points. The supervision skill and the briefs it gives its child sessions SHALL name the task kinds each role may use.

#### Scenario: A session opened by the developer in a supervised project
- **WHEN** the census lists it as a session of the project
- **THEN** it may use the digest task kinds, and not `wake-triage`

### Requirement: The report carries the saving
The supervisor's periodic report SHALL include one line with the pool tokens spent, the main-model tokens avoided, the leverage and the misses since the previous report, taken from the ledger. With the dial at 0 the line SHALL be absent.

#### Scenario: A day with misses
- **WHEN** two misses were recorded since the last report
- **THEN** the line names them and says which pair was demoted
