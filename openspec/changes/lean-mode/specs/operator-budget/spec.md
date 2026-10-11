# operator-budget

## Purpose

What the toolkit tells an operator about cost and delegation before and
during a run, so that a multi-agent workflow does not spend a week's model
budget in a day. Every requirement here is about documentation the skills and
the operator notes carry; none changes what a command does.

## ADDED Requirements

### Requirement: Serial delegation by default

Every skill that spawns subagents SHALL recommend one subagent at a time, each
given a context packet (the exact files and lines, the commands to run, the
contract to satisfy, the shape of the report), and SHALL present parallel
fan-out as an explicit opt-in for tasks that share no files.

#### Scenario: Reading a skill that delegates
- **WHEN** an operator reads `multiagente` or `openspec-gap-analysis`
- **THEN** the skill says serial is the default, names what the packet contains, and says parallel is an opt-in with its cost named

### Requirement: The delegate never commits

The skills SHALL state that a subagent leaves its changes uncommitted and
never pushes, and that the orchestrator reviews the diff and commits.

#### Scenario: Delegation rules in the skills
- **WHEN** an operator reads `multiagente` or the prohibitions of `harness-spec`
- **THEN** a delegate committing or pushing is listed as forbidden, with the review by the orchestrator as the step that replaces it

### Requirement: Cost is stated in passes

The operator notes SHALL give the measured cost of a lean pass as a share of
the weekly counter, SHALL say that this share does not follow the agent's
token count, and SHALL name the three usage counters and which one binds.

#### Scenario: Operator notes on budget
- **WHEN** an operator opens `docs/openspec/README.md`
- **THEN** a section gives the per-pass share, the per-phase token sizes, the three counters, and the rule to read the counters after every pass

### Requirement: Suites run in the orchestrator's background

The operator notes SHALL say that long suites and the harness are run by the
orchestrator in a background shell, never by a waiting agent, and SHALL warn
against polling a process started from the same shell with `pgrep -f`.

#### Scenario: Waiting on a suite
- **WHEN** an operator reads how to run the harness during a delegated task
- **THEN** the notes say the orchestrator runs it in the background and waits for the notification

### Requirement: Scoped supervisor by default

`harness-spec` SHALL run the fresh-context supervisor scoped to the layers the
change touched, with a context packet, and SHALL reserve the full run for
cross-cutting changes and for the close of a capability.

#### Scenario: Supervisor launch after an engine change
- **WHEN** a change touched the engine and not the painting
- **THEN** the supervisor runs the engine layers only, and the full run is not required until the capability closes

### Requirement: A test counts only after it has failed

`harness-spec` SHALL forbid marking a scenario as covered by a test that was
not seen failing on the tree without the change, unless the manifest row says
why that proof was impossible.

#### Scenario: Prohibitions of harness-spec
- **WHEN** an operator reads the prohibitions
- **THEN** a test never seen failing is listed beside the existing prohibition against loosening an assertion
