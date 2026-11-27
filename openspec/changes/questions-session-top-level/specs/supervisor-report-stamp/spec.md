# Spec Delta — supervisor-report-stamp

## Purpose

Defines when the Stop hook of a supervisor records that its closing message was a status report, so that a report
written on a turn the hook blocked, or on a turn another block fired, still resets the report clock.

## ADDED Requirements

### Requirement: A report always writes the stamp
On every `Stop` event of a supervisor lock owner whose closing message is a report (`guard_report.looks_report`), the
hook SHALL write the report stamp (`<home>/backlog/<key>.last-report`) with the current time, whatever
`stop_hook_active` says, whether or not a watcher is armed, and whether or not another block of the Stop hook is
returned on that event. Writing the stamp SHALL never raise and SHALL never change the hook's decision.

#### Scenario: Retry after a block
- **WHEN** a supervisor with a watcher armed stops with `stop_hook_active: true` and a closing message that is a report
- **THEN** the stamp file holds the current time and the hook prints nothing

#### Scenario: Another block comes first
- **WHEN** a supervisor stops with `stop_hook_active: false`, a closing message that is a report, and an earlier block
  of the chain fires (for example the English-language block)
- **THEN** the hook returns that block and the stamp file holds the current time

#### Scenario: No watcher armed
- **WHEN** a supervisor stops without a watcher armed and its closing message is a report
- **THEN** the hook returns the no-watcher block and the stamp file holds the current time

#### Scenario: Not a report
- **WHEN** the closing message is short or has fewer than two quoted proofs
- **THEN** the stamp is not touched

#### Scenario: Next turn after a stamped retry
- **WHEN** the stamp was written on a retry and the next turn ends with a short message within the report interval
- **THEN** no report block is returned

### Requirement: The report block stays one per turn
The report block SHALL only be returned when `stop_hook_active` is false and no earlier block of the chain returned a
reason, exactly as before this change, and SHALL never be returned for a closing message that is a report.

#### Scenario: Retry is never blocked for the report
- **WHEN** a supervisor stops with `stop_hook_active: true` and its last report is older than the interval
- **THEN** the hook prints nothing

#### Scenario: Due report on a normal stop
- **WHEN** a supervisor stops with `stop_hook_active: false`, no earlier block fires, the last report is older than the
  interval and the closing message is not a report
- **THEN** the hook returns the report block, as before

### Requirement: Self-test probe for the stamp
`supervisor-lock self-test` SHALL include a check that drives the hook (not `report_block` directly) with
`stop_hook_active: true` and a report as closing message, and a check where an earlier block fires, and SHALL verify
the stamp in both.

#### Scenario: Probe through the hook
- **WHEN** the self-test runs in its sandbox
- **THEN** both checks pass, and they would fail on the code before this change
