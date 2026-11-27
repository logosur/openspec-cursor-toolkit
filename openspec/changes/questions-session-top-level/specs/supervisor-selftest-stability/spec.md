# Spec Delta — supervisor-selftest-stability

## Purpose

Defines that `supervisor-lock self-test` gives the same verdict whatever the machine load and the minute of the clock,
without weakening any of its checks.

## ADDED Requirements

### Requirement: The red is reproduced before any fix
Before a probe of this capability is changed, the self-test SHALL be run in a temp HOME under artificial CPU load and
the labels that went red, with what the code under test returned, SHALL be recorded in the change's `VERIFY.md`.

#### Scenario: Reproduction recorded
- **WHEN** the phase that applies point g starts
- **THEN** `VERIFY.md` lists each loaded pass, its failing labels (or "none") and the hook output of each failing
  Stop-hook probe, before any probe is edited

### Requirement: Clock-dependent probes do not depend on the minute
A probe that compares a clock time SHALL compute its expectation from the same instant the code under test used, or
from synthetic ages fixed at the point of the check. Such probes SHALL accept a reference time from the test.

#### Scenario: Pass crossing a minute boundary
- **WHEN** the revive probe (`revive: its text says the truth …`) runs with the reference time half a second before a
  minute boundary and the check happens after it
- **THEN** it passes

#### Scenario: Mutation still caught
- **WHEN** the revive text is changed to carry a time one minute off
- **THEN** the probe fails

### Requirement: A probe of a chained Stop block isolates the block it tests
The probes `hook: Stop with no task -> block with the Spanish reason`, `hook: another owner's or a finished task does
not count` and `supervisor-stop-gate: passes stdin through to the hook, exit 0` SHALL run with every other chained
Stop block unable to fire, so their verdict depends only on the block they test.

#### Scenario: Slow pass
- **WHEN** the self-test runs under artificial load
- **THEN** these three probes pass

#### Scenario: Mutation still caught
- **WHEN** the no-watcher block's reason is changed or removed
- **THEN** these probes fail

### Requirement: Latency checks keep their bound
The three checks `hook: 3 locks + 400 app records, non-owner session …`, `hook PreToolUse: 3 locks + 400 app records …`
and `hook Stop: 3 locks + 400 app records, non-owner …` SHALL keep the bound `< 0.3` s. Any change to how the time is
measured SHALL be written in `design.md` D7, and each check SHALL still fail when the timed path is made slower than the
bound.

#### Scenario: Bound unchanged
- **WHEN** `selftest.py` is searched for the three labels
- **THEN** each still asserts a time below 0.3 s

#### Scenario: Slow path caught
- **WHEN** a delay longer than 0.3 s is injected on the timed path (mutation run)
- **THEN** the matching check fails, and the run is recorded in `VERIFY.md`

### Requirement: Stable under load
The whole self-test SHALL pass three consecutive times in a temp HOME under artificial CPU load, and once with the
simulated clock crossing a minute boundary.

#### Scenario: Three loaded passes
- **WHEN** the self-test runs three times in a row under `nice` with CPU-bound loops in parallel
- **THEN** each pass ends with `ok: 0 failed`, and the three results are recorded in `VERIFY.md`
