# Spec Delta — usage-watch

## Purpose

Defines how the `usage-watch` script measures token usage from the local transcripts, detects usage far above normal, records each detection as a finding, and reports it, without a model and without changing anything outside its own state directory.

## ADDED Requirements

### Requirement: Usage is counted per model response from the local transcripts
`usage-watch collect` SHALL read every main transcript (`<projects_dir>/<slug>/<session>.jsonl`) and every subagent transcript (`<projects_dir>/<slug>/<session>/subagents/<agent>.jsonl`) and record, for each `assistant` line that carries `message.usage` and a model other than `<synthetic>`, the input, cache-write (5 minutes and 1 hour), cache-read and output tokens, the model, the session, the agent (subagents only), the timestamp and the context size of the call.

#### Scenario: Main and subagent usage are both counted
- **WHEN** a synthetic project holds one main transcript with two responses and one subagent transcript with one response
- **THEN** `status --json` reports three calls, two of them `main` and one `subagent`, with the token sums of the fixtures

#### Scenario: Synthetic and usage-less lines are skipped
- **WHEN** a transcript holds an `assistant` line with model `<synthetic>` and another without `usage`
- **THEN** neither is counted

### Requirement: The context size of a call is everything it read
The context size of a call SHALL be the sum of its input, cache-write and cache-read tokens.

#### Scenario: Context size
- **WHEN** a response reports input 10, cache writes 30 (5 minutes) and 20 (1 hour), and cache read 940
- **THEN** its context size is 1000

### Requirement: Each response is counted once, however it is read
Records SHALL be deduplicated by `message.id` across all files and all runs, the last record of an id winning. Reading the transcripts in one `collect` run and reading them in several runs while they grow SHALL give the same totals.

#### Scenario: Incremental equals full
- **WHEN** a transcript is collected once after half of its lines are written and again after the rest are written
- **THEN** the totals equal those of a single `collect` over the complete file in a fresh state directory

#### Scenario: Several lines of one response
- **WHEN** three `assistant` lines share one `message.id`
- **THEN** one call is counted, with the usage of the last line

#### Scenario: The same response in two transcripts
- **WHEN** a resumed session's transcript repeats a message id already present in its original transcript
- **THEN** the call is counted once

#### Scenario: A replaced or truncated file
- **WHEN** a collected transcript is replaced by a shorter file or a file with another inode
- **THEN** the next `collect` reads it from the start and the totals contain no duplicate

### Requirement: Cache writes and advisor calls are split out
A response's cache writes SHALL be split into 5-minute and 1-hour writes from `cache_creation`; when only `cache_creation_input_tokens` is present, all of it SHALL count as 5-minute writes. Items of `usage.iterations` of type `advisor_message` SHALL be counted as separate advisor calls of the same session with their own model, and the main call SHALL use only the items of type `message` when iterations are present.

#### Scenario: Cache split
- **WHEN** a response reports 100 one-hour and 50 five-minute cache-write tokens
- **THEN** the call records `cw1h` 100 and `cw5` 50

#### Scenario: Only the total is present
- **WHEN** a response reports `cache_creation_input_tokens` 80 and no `cache_creation`
- **THEN** the call records `cw5` 80 and `cw1h` 0

#### Scenario: Advisor iteration
- **WHEN** a response carries one `message` iteration and one `advisor_message` iteration
- **THEN** the session has one main call and one advisor call, each with its own tokens

### Requirement: Usage is weighted with the configured price table and nothing is dropped
Weighted units SHALL be computed per call from the first `prices` entry whose regular expression matches the model id. A model that matches no entry SHALL still be counted in tokens and SHALL be listed under `unpriced_models` by `status --json` and on the page; it SHALL NOT be weighted as 0 silently.

#### Scenario: Configured weights
- **WHEN** the config maps a pattern matching the fixture's model to weights 1, 2, 3, 0.5 and 10 per million tokens
- **THEN** the weighted units of a call equal the dot product of its five token counts with those weights, divided by one million

#### Scenario: Unpriced model
- **WHEN** the price table has no entry that matches a model of the fixtures
- **THEN** `status --json` lists that model under `unpriced_models` with its token count

### Requirement: Malformed input never stops counting
A line that is not JSON, a field of the wrong type, a missing timestamp or an unreadable file SHALL be skipped and counted under `skipped_lines` in `status --json`; `collect` SHALL exit 0.

#### Scenario: Broken line in the middle
- **WHEN** a transcript holds a valid response, a line of garbage and another valid response
- **THEN** both valid responses are counted and `skipped_lines` is 1

### Requirement: Each turn records what started it
Each user line that starts a turn (not a tool result, not meta) SHALL be recorded with its origin: `human`, `task`, `peer`, `child`, `app`, `routine`, `compact`, `subagent` or `other`, and every main call SHALL be tied to the turn it belongs to. Origins other than `human`, `compact` and `subagent` are automatic.

#### Scenario: Task notification
- **WHEN** a turn starts with a user line whose `origin.kind` is `task-notification`
- **THEN** that turn's origin is `task` and it counts as automatic

#### Scenario: Routine session
- **WHEN** the app record of a session has `scheduledTaskId` set and a turn starts with a typed prompt
- **THEN** that turn's origin is `routine`

### Requirement: Usage is attributed to projects and roles without machine-specific names
The project of a session SHALL be the main checkout of its working directory (git common dir), else the basename of that directory, else `unknown`. The role SHALL be `supervisor`, `questions` or `closer` (supervision locks), `usage` (usage role record), `routine` (app record), `panel` or `subagent` (subagents, by `panel_pattern`), else `worker`. No project name, path pattern or title prefix SHALL be written in the code or the default config.

#### Scenario: Worktree of a project
- **WHEN** a session's working directory is a git worktree of a synthetic repository
- **THEN** its project is the basename of the repository's main checkout

#### Scenario: Questions session of a lock
- **WHEN** a supervision lock names a session's app id as `mailbox`, and an app record maps that app id to a different CLI session id whose transcript is collected
- **THEN** that transcript's session has role `questions`

### Requirement: Supervision data is only read, as files
Roles SHALL be read from the lock files `<supervisor home>/locks/*.json` that are not released, the usage role file `<supervisor home>/usage-role.json` and the app records `<app_sessions_dir>/*/*/local_*.json`, as JSON, with app ids joined to transcript ids through `cliSessionId`. The measuring commands SHALL NOT run or import any piece of the `supervision` module.

#### Scenario: Without supervision
- **WHEN** the supervisor home holds no lock file and no usage role file
- **THEN** roles are only `routine`, `panel`, `subagent` and `worker`, and `collect` exits 0

#### Scenario: Released lock
- **WHEN** a lock file marked released names a session as `mailbox`
- **THEN** that session's role is not `questions`

### Requirement: Loop rule
`detect` SHALL raise a `loop` finding for a session when `loop_same_text_min` consecutive main turns end with the same normalised text, or when one tool call (same name and same canonical input) repeats at least `loop_same_call_min` times within `loop_window_min` minutes in one transcript.

#### Scenario: Same answer again and again
- **WHEN** a session's last six turns each end with "Nothing new, waiting." with only the numbers changing, and `loop_same_text_min` is 5
- **THEN** one `loop` finding is raised for that session

#### Scenario: Healthy repetition
- **WHEN** a session calls the same tool eight times in 30 minutes with eight different inputs, and its turns end with different texts
- **THEN** no `loop` finding is raised

### Requirement: Empty-wakes rule
`detect` SHALL raise an `empty-wakes` finding for a session with at least `empty_wakes_min_per_day` automatic-origin turns in the last 24 hours that each made at most `empty_wake_max_calls` calls and wrote at most `empty_wake_max_output` output tokens.

#### Scenario: A watcher that wakes for nothing
- **WHEN** a session has 30 task-notification turns in 24 hours of one call and 200 output tokens each, and the threshold is 24
- **THEN** one `empty-wakes` finding is raised

#### Scenario: Human turns do not count
- **WHEN** a session has 30 short turns in 24 hours, all typed by the developer
- **THEN** no `empty-wakes` finding is raised

### Requirement: Role-model rule
`detect` SHALL raise a `role-model` finding for a session whose role is in `cheap_roles` and that spent at least `role_model_min_share` of its weighted units on a model matching `expensive_model_pattern`.

#### Scenario: Questions session on an expensive model
- **WHEN** the questions session of a lock spends all its units on a model whose id matches `expensive_model_pattern`
- **THEN** one `role-model` finding is raised, with the proposal kind `session-model`

#### Scenario: Worker on an expensive model
- **WHEN** a `worker` session spends all its units on an expensive model
- **THEN** no `role-model` finding is raised

### Requirement: Expensive-subagents rule
`detect` SHALL raise an `expensive-subagents` finding for a session with at least `expensive_subagents_min` subagents in the last 24 hours on a model matching `expensive_model_pattern` whose description and first prompt carry no match of `escalation_mark_pattern` and whose description does not match `panel_pattern`.

#### Scenario: Unmarked expensive subagents
- **WHEN** a session launched three subagents on an expensive model with no escalation mark, and the threshold is 2
- **THEN** one `expensive-subagents` finding is raised, proposing `agent-model-gate` `enabled` = true

#### Scenario: Panel and marked subagents
- **WHEN** the expensive subagents of a session are a panel (description matching `panel_pattern`) and one marked with the escalation mark
- **THEN** no `expensive-subagents` finding is raised

### Requirement: Advisor-excess rule
`detect` SHALL raise an `advisor-excess` finding for a session that made more than `advisor_max_per_day` advisor calls in the last 24 hours.

#### Scenario: Too many advisor calls
- **WHEN** a session made six advisor calls in 24 hours and the cap is 4
- **THEN** one `advisor-excess` finding is raised

#### Scenario: Calls spread over days
- **WHEN** a session made six advisor calls, three on each of two days 30 hours apart, and the cap is 4
- **THEN** no `advisor-excess` finding is raised

### Requirement: Large-context rule
`detect` SHALL raise a `large-context` finding for a session with `large_context_calls` consecutive main calls each reading at least `large_context_tokens` of context.

#### Scenario: Sustained large context
- **WHEN** a session's last 25 main calls each read more than the threshold and `large_context_calls` is 20
- **THEN** one `large-context` finding is raised

#### Scenario: A single peak
- **WHEN** one call of a session reads a context far above the threshold and the calls around it are small
- **THEN** no `large-context` finding is raised

### Requirement: Idle-rewrite rule
`detect` SHALL raise an `idle-rewrite` finding for a session with at least `idle_rewrite_min_count` calls in the last 24 hours that each came more than `idle_rewrite_gap_s` seconds after the previous call of the same transcript, read more than `idle_rewrite_min_context` tokens of context and wrote to the cache at least `idle_rewrite_fraction` of that context.

#### Scenario: Expensive wake-ups after pauses
- **WHEN** a session resumes four times after two-hour pauses and each first call rewrites most of a large context, with a minimum count of 3
- **THEN** one `idle-rewrite` finding is raised

#### Scenario: Pause with a warm cache
- **WHEN** a session resumes four times after two-hour pauses and each first call reads its context from the cache, writing almost nothing
- **THEN** no `idle-rewrite` finding is raised

### Requirement: Pace rule
`detect` SHALL raise a `pace` finding for a session or a project whose weighted units in the last hour are at least `pace_factor` times its mean over the active hours of the previous `pace_baseline_days` days and at least `pace_min_units`, or, when `weekly_budget_units` is above 0, whose units over the last `pace_sustainable_window_h` hours reach `pace_sustainable_share` of the budget's share for that window.

#### Scenario: A sudden burst
- **WHEN** a project used about 10 units per active hour for a week and 60 units in the last hour, with factor 3 and minimum 20
- **THEN** one `pace` finding is raised for the project

#### Scenario: A busy but steady project
- **WHEN** a project used about 50 units per active hour for a week and 55 in the last hour
- **THEN** no `pace` finding is raised

#### Scenario: No history
- **WHEN** a session has no usage before the last hour and no budget is configured
- **THEN** no `pace` finding is raised for it

#### Scenario: Above the sustainable pace
- **WHEN** the weekly budget is 168 units, the window is 6 hours, the share is 2, and a project used 15 units in the last 6 hours
- **THEN** one `pace` finding is raised for the project

### Requirement: Expensive-automation rule
`detect` SHALL raise an `expensive-automation` finding for a session that spent at least `automation_min_share` of its weighted units in automatic-origin turns and whose main model matches `expensive_model_pattern`.

#### Scenario: Notices answered by an expensive model
- **WHEN** a session on an expensive model spent 90% of its units in task-notification turns and the share threshold is 0.6
- **THEN** one `expensive-automation` finding is raised, with proposal kind `session-model`

#### Scenario: Developer-driven session
- **WHEN** a session on an expensive model spent 90% of its units in turns typed by the developer
- **THEN** no `expensive-automation` finding is raised

### Requirement: A finding is complete and is never raised twice
Each finding SHALL carry an id `<rule>-<10 hex>` derived only from the rule, the scope and the rule's discriminator, the scope, the evidence in figures, an estimated saving per day, the proposal with its kind (`config`, `session-model`, `session-effort`, `note`), who applies it, how it is undone, its state and its history. `detect` SHALL NOT add a finding whose id is already stored, and SHALL only refresh the evidence of a finding still `new`.

#### Scenario: Detected again while new
- **WHEN** `detect` runs twice over the same fixtures
- **THEN** the store holds one finding per rule and scope, with `last_seen` updated

#### Scenario: One config proposal from many sessions
- **WHEN** three sessions each trigger `expensive-subagents` and `advisor-excess`
- **THEN** the store holds one machine-wide finding proposing `agent-model-gate` `enabled` = true, listing the sessions as evidence

#### Scenario: Value already in effect
- **WHEN** the installed `agent-model-gate` piece already has `enabled` true
- **THEN** no finding proposing that change is raised

#### Scenario: Detected again after being asked or rejected
- **WHEN** a finding is `asked` or `rejected` and `detect` sees the same pattern again
- **THEN** no new finding is added and the stored one is unchanged

### Requirement: Thresholds and paths are configuration with generic defaults
Every threshold, pattern, path, price weight and text of `usage-watch` SHALL come from the `usage-watch` config piece read with `toolkit_config`; a value of the wrong shape SHALL keep the default; a missing or corrupt piece SHALL give the defaults. The default piece SHALL contain no price, figure or name observed on a particular machine, and `order_text` SHALL default to empty.

#### Scenario: Corrupt config
- **WHEN** the installed `usage-watch.json` is not valid JSON
- **THEN** every subcommand runs with the defaults and exits as it would with them

#### Scenario: Wrong shape
- **WHEN** the config sets `advisor_max_per_day` to the string "many"
- **THEN** the rule uses the default cap

### Requirement: Nested configuration entries are checked one by one
A `prices` entry SHALL count only when its key compiles as a regular expression and its value is five numbers of at least 0; when no entry is valid the default table SHALL be used. A pattern key that does not compile SHALL keep its default.

#### Scenario: Bad price entry
- **WHEN** `prices` holds one entry with three weights and one valid entry
- **THEN** only the valid entry weights calls, and a model that only the bad entry would match is listed under `unpriced_models`

### Requirement: Measuring commands write only to their state directory
`collect`, `detect`, `status`, `page`, `show`, `list`, `wait`, `tick` and `self-test` SHALL write nothing outside `state_dir` and `page_path` (`self-test`: nothing outside its own temporary directory, which it removes): no config piece, no override, no session record, no queue item.

#### Scenario: A full tick in a temporary HOME
- **WHEN** `tick` runs in a temporary `HOME` with fixtures, a supervisor home, a queue directory and an override directory
- **THEN** the only files created or changed are under `state_dir` and at `page_path`

### Requirement: Old records are pruned
`collect` SHALL delete stored records older than `retention_days` and SHALL keep findings whatever their age.

#### Scenario: Retention
- **WHEN** the state directory holds records 20 days old and `retention_days` is 15
- **THEN** after `collect` they are gone and the findings store is unchanged

### Requirement: One status line with an informational pace
`usage-watch status` SHALL print one line with the share of the week elapsed, the weighted units of the week, the pace and the number of findings per state. With `weekly_budget_units` above 0, the pace SHALL be `green` while the projected week total is at most `pace_amber_ratio` of the budget, `amber` up to the budget, `red` above it; with no budget it SHALL be `unknown`. No rule or command SHALL act on the pace.

#### Scenario: Red pace
- **WHEN** a quarter of the week has passed, the budget is 100 units and 40 have been used
- **THEN** the line says `pace red`

#### Scenario: No budget
- **WHEN** `weekly_budget_units` is 0
- **THEN** the line says `pace unknown`

### Requirement: A self-refreshing page
`usage-watch page` SHALL write a single static HTML file at `page_path` that refreshes itself every `page_refresh_s` seconds, shows the ranking by session, project, model and origin and the findings with their state, works in light and dark colour schemes and at phone width, and loads nothing from the network.

#### Scenario: Page content
- **WHEN** `page` runs over fixtures with one finding
- **THEN** the file contains a refresh meta tag, the finding id and its state, and no `http://` or `https://` resource reference

### Requirement: A user timer runs the measuring cycle
`usage-watch tick` SHALL run `collect`, `detect` and `page` in that order. `usage-watch timer print` SHALL print a `systemd --user` service (`Type=oneshot`, running `tick` with the script's own path) and timer (every `timer_interval_min` minutes) without writing anything; `timer install` SHALL write both units under the user's `systemd` folder and enable the timer; `timer uninstall` SHALL disable and remove them. The toolkit installer SHALL NOT write these units.

#### Scenario: Print touches nothing
- **WHEN** `timer print` runs in a temporary `HOME`
- **THEN** stdout holds both units with the configured interval and no file is written

#### Scenario: Install with a fake systemctl
- **WHEN** `timer install` runs in a temporary `HOME` with a fake `systemctl` first on `PATH`
- **THEN** both unit files exist under the temporary `HOME` and the fake recorded `daemon-reload` and the enabling of `usage-watch.timer`

### Requirement: A self-test and a contract cover the measuring half
`usage-watch self-test` SHALL build synthetic transcripts in its own temporary directory, check the counting (dedup, cache split, advisor split) and every rule's firing and healthy case there, print one line per failed check, and exit 0 only when none failed. `global/contracts/usage-watch.yaml` SHALL hold safe probes only (help, empty status, empty page, `timer print`, corrupt config).

#### Scenario: Self-test passes
- **WHEN** `usage-watch self-test` runs from the repository copy
- **THEN** it exits 0 and reports no failed check

#### Scenario: Self-test catches a broken rule
- **WHEN** one rule's threshold comparison is inverted
- **THEN** `self-test` exits 1 and names that rule

#### Scenario: Contract probes
- **WHEN** the toolkit runs the `usage-watch` contract in a temporary `HOME`
- **THEN** every probe passes and nothing outside the temporary `HOME` changes

### Requirement: The full example installs and checks the usage module
`examples/override-full` SHALL install the `usage` module, and its `try.sh` SHALL run `usage-watch self-test` when the script is installed.

#### Scenario: Full example
- **WHEN** `examples/override-full/try.sh` runs
- **THEN** its install includes `usage`, the contract probes include `usage-watch`, and a `usage-watch self-test` step passes

### Requirement: A finding under the materiality floor is stored as minor and never reaches the developer
The floor SHALL be the larger of `min_saving_units_per_day` (default 0) and `min_saving_share` (default 0.01) times the mean daily units of the baseline's active days. A finding saving less than the floor SHALL be stored as `minor`, never announced or asked. Each `detect` SHALL re-evaluate it: `minor` at or above the floor becomes `new`, `new` below it becomes `minor`. Findings in any other state SHALL never be changed by the floor.

#### Scenario: Exactly at the floor and just under it
- **GIVEN** a finding whose saving is S
- **WHEN** the floor is S, and in another run S plus a hundredth of a thousandth
- **THEN** the first finding is `new` and the second is `minor`

#### Scenario: The floor is re-evaluated
- **WHEN** `detect` runs with a floor above the saving, then with a floor of 0, then above the saving again
- **THEN** the finding goes `minor`, `new`, `minor`, each step recorded in its history

#### Scenario: Other states are untouched
- **WHEN** a finding is `asked`, `authorized`, `rejected`, `applied` or `measured` and `detect` runs with a floor far above and far below its saving
- **THEN** the stored finding is byte-identical

#### Scenario: Minor stays out of sight
- **WHEN** every finding is `minor`
- **THEN** `wait` prints no `FINDING`, `ask` refuses each one, `list --state new` is empty, the page holds one collapsed block with the count and no row per finding, and the status line shows the `minor` count

### Requirement: Session findings of one rule and project fold into one note for the project's supervisor
Session findings of one rule and project SHALL fold into ONE project-scoped `note` for `project-supervisor`, with its own texts, when the session is a `routine`, is not live (next requirement), or `group_min_sessions` (default 3) sessions raise that rule. Its saving is the sum; its evidence is the count, the top five sessions and a few locations. The floor applies after grouping.

#### Scenario: Fifty one-run routine sessions
- **WHEN** fifty one-run sessions of a scheduled routine in one project raise `role-model`
- **THEN** exactly one finding exists for that rule and project, project-scoped, with `evidence.sessions` 50 and five top sessions, and its applier is `project-supervisor`

#### Scenario: Healthy routines
- **WHEN** the same routines run on the cheaper model
- **THEN** no finding is raised

#### Scenario: Three live sessions fold and two do not
- **WHEN** three open, active sessions of one project raise `large-context`, and in another run only two do
- **THEN** the first run gives one project-scoped finding and the second gives two session-scoped findings

#### Scenario: The floor after grouping
- **WHEN** every session's saving is under the floor but the sum is over it
- **THEN** the grouped finding is `new`

### Requirement: A session-model proposal needs a live session
A finding whose proposal changes the model or effort of one session (applier `usage-role`, with `target_app_id`) SHALL only be produced for a session that is open in the app and has had a call inside `session_active_window_h`; any other session SHALL go through grouping.

#### Scenario: Closed session
- **WHEN** a session whose app record is archived answers automatic notices on the expensive model
- **THEN** the finding is a project-scoped note for the project's supervisor, never a `session-model` proposal

#### Scenario: Open but quiet session
- **WHEN** an open session has had no call inside the window
- **THEN** the same fold applies

#### Scenario: Live session
- **WHEN** an open session with a recent call answers automatic notices on the expensive model
- **THEN** its `session-model` proposal is kept, with its `target_app_id`

### Requirement: One pace finding where a session is most of its project's pace
When a session-scoped `pace` finding has a saving of at least `pace_dedupe_share` (default 0.8) of its project's `pace` finding, `detect` SHALL keep one of them: the session's when that session is live, else the project's. A stored `new` finding that is no longer raised for this reason SHALL become `minor`.

#### Scenario: Session not live
- **WHEN** one session accounts for the whole burst of its project and is not open
- **THEN** only the project finding is raised

#### Scenario: Session live
- **WHEN** the same session is open
- **THEN** only the session finding is raised

#### Scenario: Share out of reach
- **WHEN** `pace_dedupe_share` is far above 1
- **THEN** both findings are raised

### Requirement: A findings file from the previous version is migrated on the next detect
A store written before the `minor` state and grouping SHALL load. On the next `detect`, its `new` session-scoped findings of a rule that is now folded, or of a session that is not live, SHALL become `minor` (with the id of the grouped finding when folded); a finding in any other state SHALL not change.

#### Scenario: Old file
- **WHEN** the store holds fifty `new` per-run findings of one rule, one of them `asked`, and `detect` runs
- **THEN** the asked one is byte-identical, the other forty-nine are `minor` pointing at the grouped finding, and the grouped finding is `new`

