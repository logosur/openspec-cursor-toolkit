# Spec Delta — agent-model-gate

## ADDED Requirements

### Requirement: The gate ships disabled
The default of `enabled` SHALL be false. While it is false the hook SHALL allow every call and write no state or log.

#### Scenario: Disabled
- **WHEN** `enabled` is false or absent and an `Agent` call has no `model`, or the advisor is called past any cap
- **THEN** the hook exits 0 with no output and creates no file

### Requirement: Subagent calls name a model
The gate SHALL deny an `Agent` or `Task` call whose `model` is absent, empty or `inherit`, unless `subagent_type` is `fork`.
The denial SHALL say how to send the call again.

#### Scenario: No model
- **WHEN** an `Agent` call has no `model` and is not a fork
- **THEN** the call is denied and the reason names `model: "sonnet"` and `"haiku"`

#### Scenario: Fork
- **WHEN** an `Agent` call has `subagent_type: fork` and no `model`
- **THEN** the call passes with no output

### Requirement: Opus and Fable need a written reason
The gate SHALL deny a call whose model contains `opus` or `fable` (any case) unless `description` or `prompt` carries
`[opus: <reason>]` with a reason of at least 10 characters, or `description` matches `panel_pattern` (default `^Panel`).

#### Scenario: Expensive model without a reason
- **WHEN** an `Agent` call has `model: opus` and no mark
- **THEN** it is denied and the reason shows the mark to write

#### Scenario: Mark or panel
- **WHEN** the call carries a valid mark, or its description starts with `Panel`
- **THEN** it passes

### Requirement: Started sessions name a model
The gate SHALL deny `mcp__ccd_session__start_session` with a `prompt` and no `proposal_id` when `model` is missing, and
SHALL require the mark in `prompt` or `background` for an Opus or Fable id. A title-only offer SHALL pass.

#### Scenario: Offer
- **WHEN** `start_session` has a title and no prompt
- **THEN** it passes

### Requirement: The advisor is capped per session
The gate SHALL deny an `advisor` call once the session has made `advisor_max_per_day` calls in the last 24 hours (0 denies
all), keeping the count under the cache folder by session id.

#### Scenario: Over the cap
- **WHEN** the session calls the advisor one time more than the cap
- **THEN** the call is denied and the reason says to carry on without it

### Requirement: Austerity
With `austerity` on, the gate SHALL deny Opus and Fable even with a mark (the panel excepted) and cap the advisor at 1.

#### Scenario: Mark under austerity
- **WHEN** austerity is on and an `Agent` call has `model: opus` with a valid mark
- **THEN** it is denied; a `Panel` call or a Sonnet call passes

### Requirement: The gate never breaks a session
Any exception, malformed input or broken config SHALL let the call through with no output and a line in the hook's log.
Folders listed in `exempt_paths` SHALL be left alone, and no other tool SHALL be touched.

#### Scenario: Malformed input
- **WHEN** stdin is not JSON
- **THEN** the hook exits 0 with no output
