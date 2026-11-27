# Spec Delta — llm-pool-registry

## Purpose

Defines what the pool knows about each model: what a person decided about it, what commands changed and what the machine observes, so that the developer can see at a glance which models exist, which are on, what each is for and how strong it is.

## ADDED Requirements

### Requirement: Each member has a described identity
A pool member SHALL have: an id (kebab-case, unique), the gateway target it maps to, a display name, a description of at most 160 characters saying what kind of task it is good for, a power level from 1 to 5, the data class it accepts (`public`, `internal` or `private`), its billing (`free`, `plan`, `paid` or `local`), its provider, a daily token budget unless it is local, and, when its billing is `paid`, a price per million tokens in and out.

#### Scenario: Member without a description
- **WHEN** the definitions hold a member with no description
- **THEN** loading the registry reports an error for that member and the member is `blocked`; the other members load

#### Scenario: Power level out of range
- **WHEN** a member's power level is 0 or 6
- **THEN** the member is `blocked` with the reason "power level"

### Requirement: Definitions, decisions and observed state are stored apart
Definitions (the members, provider terms, prices, caps, excluded projects, schedules, limits) SHALL live in the config piece and its override, which no command writes. Decisions (enabled members, assignments, modes, the dial, enabled projects, stop flags) SHALL live in a file written only by `llm-pool` commands. Observed state (member state, quota, reset time, health, last error) SHALL live in a third file.

#### Scenario: A member runs out of quota
- **WHEN** the gateway reports a member's quota as exhausted
- **THEN** the state file marks it `exhausted` with the reset time, and neither the config piece nor the decisions file changes

#### Scenario: A command changes an assignment
- **WHEN** `llm-pool assign` runs
- **THEN** only the decisions file and the audit log change, and the next toolkit install is not refused for an edited file

### Requirement: Decision and state files survive concurrent commands
The decisions file and the state file SHALL be replaced atomically under a lock.

#### Scenario: Two commands at once
- **WHEN** two `llm-pool` commands change the decisions file at the same moment
- **THEN** both changes are present afterwards and the file is valid

### Requirement: What an override may not loosen is fixed in the code
The task-kind catalog (each kind's input class, minimum power and highest mode), the list of soft events and the hard limits of the routing and offload rules SHALL be constants of the code. Configuration SHALL be able to switch a task kind off and to set numbers within the hard limits; a value outside a hard limit SHALL be replaced by the default and reported by `llm-pool doctor`.

#### Scenario: An override lowers a task kind's input class
- **WHEN** an override tries to declare `log-digest` as `internal`
- **THEN** the task kind keeps the class `private` and doctor reports the ignored key

#### Scenario: A limit set beyond its hard limit
- **WHEN** an override sets the maximum silent time to 6 hours
- **THEN** 2 hours is used and doctor reports it

### Requirement: Member states
A member SHALL be in exactly one state: `active`, `paused`, `exhausted`, `cooldown` or `blocked`. Only `active` members receive traffic. A member that is defined but not enabled by command is `paused`.

#### Scenario: Quota reset
- **WHEN** an `exhausted` member's reset time passes and the gateway reports quota again
- **THEN** the member returns to `active` without anyone acting

#### Scenario: Paused by a person stays paused
- **WHEN** a `paused` member's quota resets
- **THEN** it stays `paused`

#### Scenario: Repeated provider errors
- **WHEN** a member fails three calls in a row, timeouts included
- **THEN** it enters `cooldown` for 5 minutes, doubling on each consecutive cooldown up to 2 hours

#### Scenario: A member removed from the definitions
- **WHEN** a member with ledger rows and assignments is deleted from the override
- **THEN** its assignments are ignored and reported by doctor, and the history still shows its rows with its id marked as removed

### Requirement: A member only takes a task kind it is fit for
A member SHALL be eligible for a task kind only if it is assigned to it, its power level is at least the task kind's minimum, and it accepts the task kind's input class.

#### Scenario: Weak model assigned to a demanding task
- **WHEN** a member of power 1 is assigned to a task kind whose minimum power is 3
- **THEN** the assignment is refused with the reason

### Requirement: Provider terms decide the data class
The definitions SHALL hold, per provider: whether its terms allow training on submitted data, how long it retains prompts, a source link and the date the terms were read. A member SHALL accept `internal` only when its provider's terms were read within 90 days and do not allow training, and `private` only when, in addition, the stated retention is 30 days or less. In every other case it SHALL accept `public` only, whatever its definition says. A `local` member needs no terms.

#### Scenario: Terms entry is stale
- **WHEN** a provider's terms were read 100 days ago and its member is defined as accepting `internal`
- **THEN** the member is treated as accepting `public` only and the console shows why

#### Scenario: No training but long retention
- **WHEN** a provider does not train on prompts and keeps them for a year
- **THEN** its members accept `internal` at most

### Requirement: The shipped registry is empty
The config piece in the repository SHALL contain an empty list of members and no real provider account, key or private choice. Example members SHALL exist only in the example override of the repository, with invented names. Real members live in the machine's override, which replaces the shipped list whole.

#### Scenario: Fresh install
- **WHEN** the module is installed with no override
- **THEN** `llm-pool list` shows no member and says how to add one

### Requirement: Local models can be members
With the `local-models` extension on, a member with billing `local` SHALL be reached through the gateway like any other, SHALL be exempt from provider terms and SHALL accept `private` when its definition says so. Starting a local model SHALL go through the machine's heavy-job queue when it is installed; without it the module SHALL NOT start one. With the extension off, a local member SHALL be `blocked`.

#### Scenario: Local member, queue not installed
- **WHEN** a local member is not running and the machine has no heavy-job queue
- **THEN** the member is `blocked` with the reason "not running" and nothing is started

#### Scenario: Extension off
- **WHEN** the `local-models` extension is off and a local member is defined
- **THEN** it is `blocked` with the reason "extension off"
