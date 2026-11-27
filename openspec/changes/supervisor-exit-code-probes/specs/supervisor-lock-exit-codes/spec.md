# Spec Delta — supervisor-lock-exit-codes

## Purpose

`supervisor-lock` answers with exit codes 3, 4, 6, 7, 8 and 9 that supervisors and hooks branch on. These requirements pin
each exit site of those codes with a check of `supervisor-lock self-test`, and require evidence that each check fails when its
site changes. They add tests only: no command, flag, hook, exit code or message of `supervisor-lock` changes. Site names (S3a
… S9a) are those of `design.md` D2.

## ADDED Requirements

### Requirement: Every exit site of codes 3, 4, 6, 7, 8 and 9 has a self-test check
`supervisor-lock self-test` SHALL contain, for every exit site listed in `design.md` D2, at least one check that runs the
command in the self-test sandbox under the site's condition and asserts the exit code together with one distinguishing token
of its output.

#### Scenario: Cloud provider absent (S3c)
- **GIVEN** a project with a GitHub remote and `SUPERVISOR_CLOUD_TESTS` pointing at a file that does not exist
- **WHEN** `supervisor-lock cloud --dir <repo>` runs
- **THEN** the exit code is 3 and stdout starts with `CLOUD-UNAVAILABLE`

#### Scenario: Cloud provider absent, JSON (S3c)
- **GIVEN** the same project and setting
- **WHEN** `supervisor-lock cloud --dir <repo> --json` runs
- **THEN** the exit code is 3 and stdout is a JSON object with `"ok": false` and `"available": false`

#### Scenario: Cloud rows unreadable when archiving or sending (S3e)
- **GIVEN** a project whose lock is held by session O and whose cloud API cannot be read
- **WHEN** O runs `supervisor-lock cloud-archive --target <id> --reason <text>` or `supervisor-lock cloud-send --target <id>
  --text <text>`
- **THEN** the exit code is 3 and stderr contains `CLOUD-UNKNOWN`

#### Scenario: Refused for the skill and for the pause at once (S8b)
- **GIVEN** a lock held by session S in state `running`, a skill file present, a transcript of S with no load of the skill,
  and the account reported as having usage
- **WHEN** S runs `supervisor-lock beat --skill-seen --state paused` without `--third-party`
- **THEN** the exit code is 8 (not 9) and stderr contains both `PAUSE REFUSED` and `SKILL SEEN REFUSED`

#### Scenario: Sites already probed keep their checks
- **GIVEN** the checks named in `design.md` D2 for S3a, S3b, S3d, S4a, S6a, S6b, S6c, S7a, S7b, S8a and S9a
- **WHEN** the change is applied
- **THEN** each of those labels is still present in `selftest.py` with an assertion at least as strict as before

### Requirement: A refused command leaves its state as it was
Where the code does not write on the refusal path, the check of that site SHALL also assert that the state the command would
have changed is unchanged.

#### Scenario: Refused acquire on a fresh lock (S3a)
- **GIVEN** a fresh lock held by session A
- **WHEN** session B runs `supervisor-lock acquire`
- **THEN** the exit code is 3 and the lock file reads exactly as before the command

#### Scenario: Nothing archived or sent when the cloud rows are unreadable (S3e)
- **GIVEN** the condition of the S3e scenario above
- **WHEN** `cloud-archive` or `cloud-send` exits 3
- **THEN** stdout contains neither `ARCHIVED` nor `SENT`, and the cloud actions log has no new line

#### Scenario: State kept on the double refusal (S8b)
- **GIVEN** the condition of the S8b scenario above
- **WHEN** the beat exits 8
- **THEN** the lock's `state` is still `running`, it has no `pause_cause`, and `skill_seen` is unset

### Requirement: Each probe is shown to fail when its site changes
For every exit site of `design.md` D2, a mutation of that site SHALL have been run once against the final self-test, and the
change SHALL record its evidence in `evidence/mutations.md`.

#### Scenario: A mutated site turns its check red
- **GIVEN** a throw-away copy of the final code with one batch of `design.md` D5 mutated, no two sites of the batch sharing a
  check or a statement
- **WHEN** `supervisor-lock self-test` runs
- **THEN** at least one `FAIL` line names a check of each mutated site, and every `FAIL` line names a check of a mutated site

#### Scenario: The mutation is reverted
- **GIVEN** a mutation run has finished
- **WHEN** the mutation is reverted (or the throw-away copy is discarded)
- **THEN** the product files under `global/scripts/` differ from the starting commit only in `selftest.py`

#### Scenario: A mutation that turns nothing red
- **GIVEN** a mutation whose self-test run shows no `FAIL` for that site
- **WHEN** the record is written
- **THEN** the site's check is strengthened and the mutation is run again; the mutation itself is never weakened

### Requirement: Tests only, and the self-test stays green
The change SHALL NOT alter the behaviour of `supervisor-lock`, and `supervisor-lock self-test` SHALL pass on the final tree.

#### Scenario: Product code untouched
- **GIVEN** the starting commit of the change
- **WHEN** the change is complete
- **THEN** `git diff --stat <start> -- global/` lists only `global/scripts/lib/supervisor/selftest.py`

#### Scenario: Green self-test
- **GIVEN** the final tree
- **WHEN** the piece test runs the self-test in a temporary `HOME` (`python3 -m unittest
  scripts.toolkit.tests.pieces.test_supervisor_lock.SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home`)
- **THEN** it passes: the self-test exits 0, prints no `FAIL` line, and its last line ends with `ok: 0 failed`

#### Scenario: Piece test floor follows the new checks
- **GIVEN** the final tree with N new checks
- **WHEN** `scripts/toolkit/tests/pieces/test_supervisor_lock.py` is read
- **THEN** its minimum count of `ok` lines is the previous floor plus N (both the with-skill and the without-skill floors)
