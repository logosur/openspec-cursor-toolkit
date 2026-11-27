# Spec Delta — llm-pool-registry

## Purpose

Defines what the pool knows about each model: what a person decided about it and what the machine observes, so that the developer can see at a glance which models exist, which are on, what each is for and how strong it is.

## ADDED Requirements

### Requirement: Each member has a described identity
A pool member SHALL have: an id (kebab-case, unique), the gateway target it maps to, a display name, a description of at most 160 characters saying what kind of task it is good for, a power level from 1 to 5, the task kinds it is assigned to, the data class it accepts (`public`, `internal` or `private`), its billing (`free`, `plan`, `paid` or `local`) and its provider.

#### Scenario: Member without a description
- **WHEN** the config piece defines a member with no description
- **THEN** loading the registry reports an error for that member and the member is `blocked`; the other members load

#### Scenario: Power level out of range
- **WHEN** a member's power level is 0 or 6
- **THEN** the member is `blocked` with the reason "power level"

### Requirement: Decided attributes and observed state are stored apart
What a person decides SHALL live in the `llm-pool` config piece (and its override). What the machine observes (state, quota left, reset time, health, last error, last change) SHALL live in a state file. An automatic state change SHALL NOT rewrite the config piece.

#### Scenario: A member runs out of quota
- **WHEN** the gateway reports a member's quota as exhausted
- **THEN** the state file marks it `exhausted` with the reset time and the config piece is unchanged

### Requirement: Member states
A member SHALL be in exactly one state: `active`, `paused`, `exhausted`, `cooldown`, `probation`, `blocked` or `retired`. Only `active` members receive traffic that is used; `probation` members receive `shadow` traffic only.

#### Scenario: Quota reset
- **WHEN** an `exhausted` member's reset time passes and the gateway reports quota again
- **THEN** the member returns to `active` without anyone acting

#### Scenario: Paused by a person stays paused
- **WHEN** a `paused` member's quota resets
- **THEN** it stays `paused`

#### Scenario: Repeated provider errors
- **WHEN** a member fails a configured number of consecutive calls
- **THEN** it enters `cooldown` for a delay that doubles on each consecutive cooldown, up to a cap

### Requirement: A member only takes a task kind it is fit for
A member SHALL be eligible for a task kind only if it is assigned to it, its power level is at least the task kind's minimum, and it accepts the task kind's input class.

#### Scenario: Weak model assigned to a demanding task
- **WHEN** a member of power 1 is assigned to a task kind whose minimum power is 3
- **THEN** the assignment is refused with the reason, and listed by `llm-pool doctor`

### Requirement: Provider terms decide the data class
The registry SHALL hold, per provider, whether its terms allow training on submitted data, a source link and the date the terms were read. A member of a provider whose terms are unread, allow training, or were read more than 90 days ago SHALL accept `public` only, whatever its entry says.

#### Scenario: Terms entry is stale
- **WHEN** a provider's terms were read 100 days ago and its member is set to accept `internal`
- **THEN** the member is treated as accepting `public` only and the console shows why

### Requirement: The shipped registry contains examples only
The config piece in the repository SHALL contain no real provider account, key or private choice: only commented examples and the task-kind catalog. Real members live in the override.

#### Scenario: Fresh install
- **WHEN** the module is installed with no override
- **THEN** `llm-pool list` shows no member and says how to add one
