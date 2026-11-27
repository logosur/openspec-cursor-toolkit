# Spec Delta — supervisor-wake-economy

## Purpose

Defines when the watcher of a supervisor (`supervisor-lock wait`) may wake it for a state that has not changed, so that an idle or queued project does not cost a full re-read of the supervisor's context every few minutes.

## ADDED Requirements

### Requirement: ALLIDLE measures quiet time from the project's last activity
The watcher SHALL compute the quiet time of a project from the most recent activity of any of its sessions, not from the moment the watcher started. Re-arming the watcher SHALL NOT restart the quiet time.

#### Scenario: Re-arm does not restart the clock
- **WHEN** a project's last activity was 40 minutes ago and its watcher is re-armed now with a base threshold of 15 minutes
- **THEN** the quiet time the watcher uses is 40 minutes

#### Scenario: A busy session blocks the report
- **WHEN** any live session of the project is busy
- **THEN** no `ALLIDLE` line is produced, whatever the quiet time

#### Scenario: Threshold of zero
- **WHEN** the watcher runs with `--all-idle-after 0`
- **THEN** no `ALLIDLE` line is ever produced

#### Scenario: Guard mode
- **WHEN** the watcher runs with `--guard`
- **THEN** no `ALLIDLE` line is produced, because a supervisor on guard has no next turn to push

#### Scenario: No session reports an idle time
- **WHEN** the project has no session with a known idle time
- **THEN** the quiet time runs from the recorded activity or, without one, from the first wait, and re-arming does not restart it

### Requirement: ALLIDLE backs off while nothing moves
Within one quiet stretch, report number `n` (counting from 0) SHALL require a quiet time of at least `min(base × 2^n, cap)`, where `base` is the watcher's `--all-idle-after` and `cap` comes from configuration. A report after the first SHALL also wait at least the previous threshold since the last report. The first report of a stretch SHALL also wait `base` after the watcher first saw the stretch.

#### Scenario: Spacing with the defaults
- **WHEN** a project stays idle for a day with `base` = 900 s and `cap` = 7200 s
- **THEN** `ALLIDLE` is reported after 15 min, 30 min, 1 h and 2 h of quiet time, and then every 2 h

#### Scenario: Already idle when first seen
- **WHEN** a watcher starts on a project whose last activity was 5 hours ago and no state exists
- **THEN** the first `ALLIDLE` comes `base` seconds after the watcher first saw the project quiet, not at the first poll

### Requirement: Activity starts a new stretch
Any activity newer than the recorded one by more than 5 seconds SHALL start a new stretch: the count returns to zero and the next report is due at the base threshold.

#### Scenario: A turn in the middle of a long idle stretch
- **WHEN** a project has had four `ALLIDLE` reports and one of its sessions runs a turn
- **THEN** the next `ALLIDLE` is due `base` seconds after that turn's last activity

### Requirement: Back-off state survives the watcher
The back-off state SHALL be stored per project on disk under the supervisor's home, so that it survives the exit and re-arm of the watcher. A missing or unreadable state SHALL be treated as a new stretch.

#### Scenario: State after a wake
- **WHEN** the watcher reports `ALLIDLE`, exits, and a new watcher starts for the same project with no new activity
- **THEN** the new watcher continues the same stretch with the same count

### Requirement: ALLIDLE is silent while the project has a job in the machine queue
When the quiet-time threshold is reached, the watcher SHALL NOT report `ALLIDLE` if a job of the project holds a slot or waits in the machine queue. A report blocked this way SHALL NOT advance the back-off.

#### Scenario: Job waiting in the queue
- **WHEN** the threshold is reached and a job of the project waits in the machine queue
- **THEN** no `ALLIDLE` is reported and the count does not change

#### Scenario: The queue check cannot be read
- **WHEN** the machine queue's state cannot be read
- **THEN** the project is treated as not queued and `ALLIDLE` follows its normal rule

### Requirement: Unchanged queue items are re-announced at a configured interval
`QUEUED` and `SLOTHELD` SHALL repeat an unchanged item no more often than `queued_reannounce_min` and `slotheld_reannounce_min` minutes, 120 by default.

#### Scenario: A job waits for five hours
- **WHEN** a job of the project waits in the machine queue for 5 hours with the default configuration
- **THEN** `QUEUED` is reported for it at most three times

### Requirement: Intervals are configuration with safe defaults
The three intervals (`queued_reannounce_min`, `slotheld_reannounce_min`, `all_idle_backoff_max_min`) SHALL be read from the `supervision` config piece. A value that is not a positive finite number SHALL be replaced by the default of 120. The ALLIDLE cap SHALL never be below the base threshold.

#### Scenario: Wrong value in the override
- **WHEN** the override sets `queued_reannounce_min` to `0`
- **THEN** the watcher uses 120 minutes

### Requirement: The skill states the cost of a wake
The supervision skill's watcher reference SHALL state that a tick costs a re-read of the supervisor's context, SHALL allow doubling `--timeout` after two unchanged ticks up to 7200 s without passing the nearest deadline of the work in flight, and SHALL describe the back-off of `ALLIDLE` and the re-announce interval of `QUEUED` and `SLOTHELD` with their configuration keys.

#### Scenario: Reading the watcher reference
- **WHEN** the watcher reference of the installed skill is read
- **THEN** it says that a wake re-reads the whole context, gives 7200 s as the upper bound of the doubled `--timeout` together with the deadline rule, and names `all_idle_backoff_max_min`, `queued_reannounce_min` and `slotheld_reannounce_min`

#### Scenario: Skill lint still passes
- **WHEN** `supervisor-lock skill-lint` runs on the installed skill
- **THEN** it reports no finding
