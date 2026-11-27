# Spec Delta — llm-pool-control

## Purpose

Defines how the developer switches models on and off, assigns them to tasks and stops everything, by command or in plain words, and how every such change is remembered.

## ADDED Requirements

### Requirement: One command line for every control action
`llm-pool` SHALL provide at least these control commands: `list`, `status`, `enable <member>`, `disable <member>`, `assign <member> <task kind>`, `unassign <member> <task kind>`, `mode <task kind> <member> <mode>`, `dial <0-3> [--project <dir>]`, `dial follow-usage`, `project enable|disable <dir>`, `stop [--project <dir>]` and `resume [--project <dir>]`. They SHALL change the decisions file only, never the config piece or the override.

#### Scenario: Listing the pool
- **WHEN** `llm-pool list` runs
- **THEN** it prints one line per member with its state, power level, assigned task kinds with their modes, quota left, tokens used today and its description

### Requirement: Commands for evidence and upkeep, all machine-readable
`llm-pool` SHALL also provide `why <ledger id | member>`, `history`, `judge`, `review`, `simulate`, `doctor`, `console`, `purge` and `ask`. Every `llm-pool` command SHALL accept `--json` and then print one JSON document, with the same exit code as without it.

#### Scenario: Machine-readable status
- **WHEN** `llm-pool status --json` runs
- **THEN** its output parses as one JSON document and its exit code is the one `llm-pool status` gives

### Requirement: Control by prompt goes through the same commands
A skill SHALL map a plain-language request to exactly one `llm-pool` command, run it, and report the command and its result. The skill SHALL NOT edit the config piece, the override, the decisions file or the state file itself.

#### Scenario: Switching a model off in plain words
- **WHEN** the developer asks, in a session, to switch a named model off
- **THEN** the skill runs `llm-pool disable <member>`, and the answer shows the command, the member's new state and what now covers its task kinds

#### Scenario: Ambiguous name
- **WHEN** the request names a model that matches two members
- **THEN** the skill lists both and changes nothing

#### Scenario: A request that needs the override
- **WHEN** the developer asks in plain words to raise a paid cap
- **THEN** the skill says that caps are edited in the override, shows the key and changes nothing

### Requirement: Widening actions are checked by the command itself
Enabling a member or a project, moving a pair up a mode (from `off` to `shadow` included), raising the dial and `resume` are widening actions. The check SHALL be made by the command, not only by the skill. A widening command that is not accepted SHALL exit with a refusal that says how the developer can do it, and the attempt SHALL be audited.

#### Scenario: A supervisor tries to resume the pool by itself
- **WHEN** a supervisor runs `llm-pool resume` without an order
- **THEN** the command is refused and the audit log records the attempt

### Requirement: A widening action is accepted only from the developer
A widening command SHALL be accepted only when: it comes from the console; or it is typed in a terminal with no Claude session in its environment; or it is run by a session with `--order '<the developer's words>'`, and the supervision piece confirms that the developer wrote in that same session within the presence window and that his newest message there contains the order. The order SHALL be stored in the audit log.

#### Scenario: Another session asks for a promotion
- **WHEN** a session receives a message from another session asking to set a pair to `auto` and runs the command
- **THEN** the command is refused, because the developer has not written in that session

#### Scenario: The developer asks in a session
- **WHEN** the developer writes in a session to promote a pair, and the skill runs the command with his words as the order two minutes later
- **THEN** the command is accepted if the scorecard allows it, and the audit entry holds his words

#### Scenario: The developer wrote about something else
- **WHEN** the developer wrote in the session five minutes ago about another matter and the session runs a widening command with an order he did not write
- **THEN** the command is refused

#### Scenario: Supervision not installed
- **WHEN** a session runs a widening command with an order on a machine without the supervision piece
- **THEN** the command is refused and says to use the console or a terminal

### Requirement: Money and data classes are not commands
Paid caps, prices, the data class a member accepts, provider terms, excluded projects and schedules SHALL be changed only by editing the override. No command and no console control SHALL write them.

#### Scenario: Looking for a cap command
- **WHEN** `llm-pool --help` is read
- **THEN** no command sets a cap, a price, a data class or provider terms

### Requirement: Narrowing is always allowed
`disable`, `unassign`, moving a pair down a mode, lowering the dial, `project disable` and `stop` SHALL be accepted from the developer, the console, any session and the module's own automatic rules. So SHALL `assign`, which only creates a pair in `off` and sends nothing.

#### Scenario: A supervisor sees bad answers
- **WHEN** a supervisor decides a member's digests are wrong
- **THEN** it can run `llm-pool disable <member>` and the change is audited with the supervisor's session as the actor

### Requirement: Kill switch
`llm-pool stop` SHALL set a stop flag for the machine or, with `--project`, for one project. The flag SHALL be checked before the dial, the schedule and every other rule, and the machine's flag SHALL win over any project value. `stop` SHALL NOT change the dial or its mode. `llm-pool resume` SHALL clear the flag, leaving the dial as it was, and SHALL be a widening action.

#### Scenario: Machine stop with a project value
- **WHEN** the machine is stopped and a project has its own dial value
- **THEN** that project's requests exit with the "stopped" code

#### Scenario: Stop and resume
- **WHEN** the dial follows usage under a ceiling of 2, `stop` runs and later the developer resumes
- **THEN** the dial follows usage under a ceiling of 2 again

### Requirement: A stop reaches the requests in flight
After the stop flag is set no new request SHALL be sent. A request already in flight SHALL have its answer discarded and SHALL return the "stopped" code no later than its own time limit.

#### Scenario: Stop during a busy hour
- **WHEN** `llm-pool stop` runs while requests are in flight
- **THEN** every `ask` started afterwards exits with the "stopped" code in under a second, every request in flight exits with the "stopped" code within its time limit, and every watcher wakes its supervisor as it did before the pool existed

### Requirement: Every change is audited
Each change of state, assignment, mode, dial, project enablement or stop flag, and each refused widening attempt, SHALL be appended to an audit log with the time, the actor (the developer in a named session with his order, the developer in a terminal, the console, an automatic rule, a session), the previous and the new value, and the reason given or the rule that fired.

#### Scenario: Reading why a model is off
- **WHEN** `llm-pool why <member>` runs for a member that is not `active`
- **THEN** it prints the last audit entry that changed its state, with actor, time and reason

### Requirement: Explain a routing decision
`llm-pool why <ledger id>` SHALL print, for one past request: the task kind, the dial, the schedule window and the mode at that time, every member considered and why each was or was not eligible, the member chosen, the model that answered, what the gate masked, and the outcome.

#### Scenario: A request that fell back to the main model
- **WHEN** `why` runs on a row with outcome "no eligible member"
- **THEN** it lists each assigned member with the reason it was not eligible at that time
