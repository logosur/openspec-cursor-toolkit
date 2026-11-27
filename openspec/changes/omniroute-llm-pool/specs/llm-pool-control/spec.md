# Spec Delta — llm-pool-control

## Purpose

Defines how the developer switches models on and off, assigns them to tasks and stops everything, by command or in plain words, and how every such change is remembered.

## ADDED Requirements

### Requirement: One command line for every control action
`llm-pool` SHALL provide at least: `list`, `status`, `enable <member>`, `disable <member>`, `assign <member> <task kind>`, `unassign <member> <task kind>`, `mode <task kind> <member> <mode>`, `dial <0-3|follow-usage>`, `project enable|disable <dir>`, `stop`, `resume`, `why <ledger id | member>`, `history`, `judge <ledger id> <agreed|missed>`, `doctor`, `console` and `ask`. Every command SHALL accept `--json`.

#### Scenario: Listing the pool
- **WHEN** `llm-pool list` runs
- **THEN** it prints one line per member with its state, power level, assigned task kinds, quota left, tokens used today and its description

### Requirement: Control by prompt goes through the same commands
A skill SHALL map a plain-language request to exactly one `llm-pool` command, run it, and report the command and its result. The skill SHALL NOT edit the config piece, the override or the state file itself.

#### Scenario: Switching a model off in plain words
- **WHEN** the developer asks, in a session, to switch a named model off
- **THEN** the skill runs `llm-pool disable <member>`, and the answer shows the command, the member's new state and what now covers its task kinds

#### Scenario: Ambiguous name
- **WHEN** the request names a model that matches two members
- **THEN** the skill lists both and changes nothing

### Requirement: Changes that widen exposure need the developer's own words
Promoting a mode, enabling a project, raising the data class a member accepts, writing a paid cap and raising the dial above 1 SHALL be accepted only from the console or from a session in which the developer has written the request himself. A request that arrives in a message from another session, in a file or in a tool result SHALL be refused.

#### Scenario: Another session asks for a promotion
- **WHEN** a session receives a message from another session asking to set a pair to `auto`
- **THEN** the skill refuses and reports who asked

### Requirement: Narrowing is always allowed
`disable`, `unassign`, lowering a mode, lowering the dial and `stop` SHALL be accepted from the developer, the console, any session of an enabled project and the module's own automatic rules.

#### Scenario: A supervisor sees bad answers
- **WHEN** a supervisor decides a member's digests are wrong
- **THEN** it can run `llm-pool disable <member>` and the change is audited with the supervisor's session as the actor

### Requirement: Kill switch
`llm-pool stop` SHALL set the dial to 0 at once, for the machine or for one project. Requests in flight SHALL finish or time out; no new one SHALL be sent. `llm-pool resume` SHALL restore the previous dial and SHALL be a widening action.

#### Scenario: Stop during a busy hour
- **WHEN** `llm-pool stop` runs
- **THEN** within one second every `ask` exits with the "no eligible member" code and every watcher wakes its supervisor as it did before the pool existed

### Requirement: Every change is audited
Each change of state, assignment, mode, dial, project enablement or cap SHALL be appended to an audit log with the time, the actor (the developer in a named session, the console, an automatic rule, a session), the previous and the new value, and the reason given or the rule that fired.

#### Scenario: Reading why a model is off
- **WHEN** `llm-pool why <member>` runs for a member that is not `active`
- **THEN** it prints the last audit entry that changed its state, with actor, time and reason

### Requirement: Explain a routing decision
`llm-pool why <ledger id>` SHALL print, for one past request: the task kind, the dial and mode at that time, every member considered and why each was or was not eligible, the member chosen, what the gate masked, and the outcome.

#### Scenario: A request that fell back to the main model
- **WHEN** `why` runs on a row with outcome "no eligible member"
- **THEN** it lists each assigned member with the reason it was not eligible at that time
