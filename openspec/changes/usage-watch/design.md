# Design — usage-watch

Requirement references: **UW** = `specs/usage-watch/spec.md`, **US** = `specs/usage-subsupervision/spec.md`.

## Context

### Problem summary

Unattended sessions can spend a large share of a weekly quota without anyone noticing: loops, wake-ups that do nothing, roles on models that do not fit them, expensive subagents and advisor calls, large contexts kept for hours, cache rewrites after a pause. The toolkit has no piece that measures this. The developer wants a sub-supervision that audits usage per session and project and asks before applying any optimisation.

### Current behaviour (FACT)

- No file under `global/` reads a response's usage from transcripts (`grep -rln "message\.usage\|get('usage')\|\['usage'\]" global/` finds nothing).
- `agent-model-gate` (module `core`) ships with `enabled: false`; its escalation mark is `[opus: <reason>]` and its panel exemption is `panel_pattern` `^Panel` (`global/hooks/agent-model-gate`, `global/config/agent-model-gate.json`). The family pattern for expensive models is `opus|fable` (`EXPENSIVE` in that hook).
- Supervision locks are per project (`lock.Store().read(project['key'])` in `global/scripts/lib/supervisor/lock.py`). A lock records `session_id`, `mailbox` (questions session) and `closer` (closing session); `closing.is_helper_row` keeps those two out of `open`, `closable` and `backlog`.
- `ask-queue list --json` prints whole items, including `status` and `answer`.
- `ask-queue` is per project, keyed by the main checkout; `add` takes `--key` (an open or asked item with the same key is updated, never duplicated) and `--order` (makes the item blocking-due at once); `pending ID` prints the status (`open|asked|answered|closed|missing`).
- The installer writes no `systemd` unit (`README.md`, module notes of `routines`, `heavy-jobs`, `accounts`). The only script that writes one is `claude-sessions-sync install`, run by the user, which writes `~/.config/systemd/user/<unit>` and calls `systemctl --user`.
- Installed config pieces live in `~/.claude/toolkit/config/<piece>.json`, written from `global/config/<piece>.json` overlaid with `<override>/config/<piece>.json` (`scripts/toolkit/config.py`). `drift` compares `toolkit/config` too (`SCOPES` in `scripts/toolkit/drift.py`): a live file equal to the plan's rendered bytes is `in-sync`, any other bytes are `live-changed`; `override.lock.json` only tracks override `files`, not config (`classify` in `drift.py`). The installer renders a piece as `json.dumps(values, indent=2, ensure_ascii=False, sort_keys=True) + '\n'` (`render` in `scripts/toolkit/config.py`). The override is `CLAUDE_TOOLKIT_OVERRIDE` or `~/.config/claude-toolkit` (`scripts/toolkit/paths.py`).
- The validator enforces one module per `global/` file, a contract per installed hook, config pieces listed by a module, and citations only of what a module or its dependencies install, or of what it declares in `project_provided` (`scripts/validate-toolkit.py`, rules `global-*`).
- `supervisor-lock backlog` lists work left in a project; while there is work, `beat --phase guardia` refuses with exit 7 (`backlog.py` header).

### Source of truth

1. The developer's request for this change (outside the repository): measure, detect, ask; apply nothing without an answer; one role per machine; watcher wakes only for a new finding or an answer.
2. The prototype audit script (outside the repository, read only). Ported: the counting logic (usage per response, the cache-write split, advisor iterations, subagent transcripts, global last-wins dedup by message id, turn-origin classification, the idle-rewrite heuristic). **Not ported:** its price figures, model ids, the hard-coded supervisor id, the account-switch split, the path regexes that name projects, the Spanish title prefixes that name roles, and the hook-log parsing.
3. Existing toolkit code listed under Current behaviour.

### Evidence map

| Claim | Kind | Where |
|---|---|---|
| A response's usage is in `message.usage` of an `assistant` line; several lines can share one `message.id` and the last one wins | INFERENCE (observed by the prototype; the transcript format is not documented) | prototype `collect` |
| Advisor calls appear as `usage.iterations[]` items of type `advisor_message`, the main call as `message` | INFERENCE (same) | prototype `collect` |
| Cache writes split into `cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`, with `cache_creation_input_tokens` as the total | INFERENCE (same) | prototype `usage_of` |
| Subagent transcripts are `<projects>/<slug>/<session>/subagents/<agent>.jsonl` with `<agent>.meta.json` next to them | INFERENCE (same) | prototype `collect` |
| Turn origin can be read from `origin.kind`, `turnOrigin`, `promptSource`, `isCompactSummary` and text prefixes | INFERENCE (same) | prototype `classify` |
| App session records carry `cliSessionId`, `title`, `model`, `effort`, `cwd`, `scheduledTaskId` | INFERENCE (same; `supervision` reads the same folder) | prototype `app_records`, `supervision.json` `app_sessions_dir` |
| Config precedence, drift scope, override location | FACT | `scripts/toolkit/config.py`, `drift.py`, `paths.py` |
| Lock fields and helper-row exclusion | FACT | `lock.py`, `closing.py` |
| `ask-queue --key`, `--order`, `pending` | FACT | `global/scripts/ask-queue` docstring |

Because the transcript format is an INFERENCE, the collector tolerates every missing or malformed field (UW: tolerant parsing) and the tests pin the synthetic shape the code expects.

## Goals / Non-Goals

**Goals:** a model-free, incremental measurement; rules with a measurable definition, named thresholds and a healthy-case test each; findings that are asked once; one apply point that cannot change anything without an answered question; a role that costs no turn while nothing happens.

**Non-goals:** an automatic brake or throttle; estimating the plan's official quota (its formula is not public); changing `agent-model-gate`; a desktop notification channel; a dashboard server (the page is a static file).

## Decisions

### D1. Module ownership: a new optional module `usage`, plus role support in `supervision`

The measuring half (collect, detect, status, page, timer) needs nothing from supervision, and it is useful alone. The role half needs `ask-queue` and `supervisor-lock`, which `supervision` installs. So:

- New module `global/modules/usage.yaml`: `depends: [core]`, opt-in, owns `scripts/usage-watch`, `scripts/lib/usage_watch/`, `hooks/usage-apply-gate` (D14) with its fragment `global/settings/hooks.usage.json`, config `usage-watch`, contracts `usage-watch` and `usage-apply-gate`. It lists `scripts/ask-queue` and `scripts/supervisor-lock` under `project_provided`. Without them, `ask`, `decide` and `wait` exit 6 and say that supervision is not installed; everything else works.
- `supervision` owns the role record in `supervisor-lock` (it is lock state), the helper-row exclusion, the backlog lines, the skill reference and the rule row. It lists `scripts/usage-watch` under `project_provided`; every caller works without it (no role, no backlog lines).
- **Direction, checked against the validator before any file landed** (`GAPS.md` G-03, experiment in a scratch copy): `depends` stays one way (`usage → core`, `supervision → core`) and acyclic (`modules.py` checks cycles on `depends` only). The two modules only *call* each other's scripts, optionally, and every such call is declared:
  - **Part A cites nothing outside `core`.** Roles come from supervision's *data files*, read-only and as plain JSON (`<supervisor home>/locks/*.json`, `<supervisor home>/usage-role.json`), the way `ask-queue` already reads lock files (`live_lock_files`). Part A never runs `supervisor-lock` and never imports `scripts/lib/supervisor/`. A draft that ran `supervisor-lock list --json` from Part A made it depend on a script of another module for no gain.
  - **Part B** runs `~/.claude/scripts/ask-queue` and `~/.claude/scripts/supervisor-lock` as subprocesses (never imports): `usage.yaml` `project_provided` (without it the validator reports two `global-citation` errors). `supervision`'s backlog runs `~/.claude/scripts/usage-watch`: `supervision.yaml` `project_provided` (without it, one `global-citation` error).
  - The gate hook belongs to `usage`, cites only its own module from its own fragment (`global-hooks`), and has a contract (`global-contract`).
- Rejected: putting everything in `supervision` (measuring would require the whole supervision stack); `usage` `depends: [core, supervision]` (same); a hook in `supervision` that reads `usage-watch` tickets (supervision would then depend on usage's state format).

### D2. Storage: normalised records per day, aggregates rebuilt on read

`collect` keeps a per-file cursor (path, inode, size, byte offset) in `<state_dir>/cursors.json` and appends normalised records to `<state_dir>/calls/<YYYY-MM-DD>.jsonl` (one per response: message id, session, agent, model, the five token counts, advisor iterations, context size, timestamp, turn index, tool-call signatures, normalised text hash) and `<state_dir>/turns/<YYYY-MM-DD>.jsonl` (one per user turn: session, origin, timestamp). Readers rebuild aggregates from the retention window and deduplicate by message id, last record wins. That gives the same totals for one full pass and for any split into incremental passes, and counts an id once when a resumed or forked transcript repeats it. The **context size** of a call is `input + cw5 + cw1h + cache_read` (everything the call read); `large-context` and `idle-rewrite` use it. A file whose inode changed or that shrank is read again from the start (dedup absorbs the repeats). Records older than `retention_days` are deleted by `collect`.

### D3. Weighting: a price table in configuration, in weighted units

`prices` maps a regular expression on the model id to five per-million-token weights (input, cache write 5 min, cache write 1 h, cache read, output). The default has one entry, `"."`, with generic relative weights, so every model is weighted the same until the override sets real prices. A model that matches no entry is still counted in tokens and listed under `unpriced_models` in `status --json` and on the page; it is never silently weighted 0. Output says "units", never a currency, unless the override sets `unit_label`.

### D4. Projects and roles without machine-specific strings

- Project of a session: the main checkout of its `cwd` (git common dir, same rule as `ask-queue`); when the path no longer exists or is not in git, the basename of `cwd`; when `cwd` is unknown, `unknown`.
- Ids: locks hold app ids (`local_…`) while transcripts are named by the CLI session id; the two are joined through the app records (`sessionId` ↔ `cliSessionId`). Fixtures use distinct ids for both, so a wrong join makes the role tests fail instead of silently classifying everyone as `worker`.
- Data sources, all read-only JSON (D1): app records `<app_sessions_dir>/*/*/local_*.json` (the layout `supervision` globs, `settings.py` `APP_SESSIONS_GLOB`), fields `sessionId` (app id), `cliSessionId`, `cwd`, `title`, `model`, `effort`, `scheduledTaskId`, `isArchived`; supervision locks `<supervisor home>/locks/*.json` (fields `session_id`, `mailbox`, `closer`, `checkout`), skipping released ones (`released` true or `state` `released`) and ignoring staleness, like `ask-queue`; the usage role `<supervisor home>/usage-role.json` (`session_id`, `cli_session_id`). `<supervisor home>` is `SUPERVISOR_LOCK_HOME`, else the config key `supervisor_home` (`~/.claude/supervisor`). A missing or corrupt file is skipped.
- Role of a session: from the lock files: `supervisor` (lock owner), `questions` (`mailbox`), `closer` (`closer`); from the usage role file: `usage`. From the app record: `routine` (`scheduledTaskId` set). Subagents: `panel` when the description matches `panel_pattern`, else `subagent`. Everything else is `worker`. With no lock file and no usage role file (supervision not installed or never used), only `routine`, `panel`, `subagent` and `worker` exist.
- Every session-scoped finding records `target_app_id`, the app id joined from the CLI id through the app records, or null. The app's session tools take that id (G-12).

### D5. Detection rules

Every rule works on the retention window as of `now` (`--now` or `USAGE_WATCH_NOW`, default the clock) and only on scopes whose evidence passes all its thresholds. Every threshold is a key of the `usage-watch` piece; a value of the wrong shape keeps the default (`toolkit_config.load_checked`). Defaults are provisional and listed as such in the config.

| Rule id | Fires when | Scope | Proposal kind and applier |
|---|---|---|---|
| `loop` | in one transcript, `loop_same_text_min` consecutive main turns end with the same normalised text (lower case, digits and whitespace collapsed), or the same tool call (name plus canonical JSON of its input) repeats `loop_same_call_min` times within `loop_window_min` | session | note; project supervisor |
| `empty-wakes` | a session has at least `empty_wakes_min_per_day` automatic-origin turns in 24 h that each made at most `empty_wake_max_calls` calls and wrote at most `empty_wake_max_output` output tokens | session | note; project supervisor |
| `role-model` | a session whose role is in `cheap_roles` spent at least `role_model_min_share` of its weighted units on a model matching `expensive_model_pattern` | session | session model; usage role |
| `expensive-subagents` | at least `expensive_subagents_min` subagents in 24 h ran on a model matching `expensive_model_pattern` without the escalation mark (`escalation_mark_pattern`) and without matching `panel_pattern` | session | config `agent-model-gate.enabled = true`; usage role |
| `advisor-excess` | a session made more than `advisor_max_per_day` advisor calls in 24 h | session | config `agent-model-gate.enabled = true`; usage role |
| `large-context` | `large_context_calls` consecutive main calls of a session each read at least `large_context_tokens` of context | session | note; project supervisor |
| `idle-rewrite` | a session has at least `idle_rewrite_min_count` calls in 24 h that came more than `idle_rewrite_gap_s` after the previous call of the same transcript, with context above `idle_rewrite_min_context` and cache writes of at least `idle_rewrite_fraction` of it | session | note; project supervisor |
| `pace` | the weighted units of a session or project in the last hour are at least `pace_factor` times its mean over the active hours of the previous `pace_baseline_days`, and at least `pace_min_units`; or, with `weekly_budget_units` > 0, its units over the last `pace_sustainable_window_h` hours are at least `pace_sustainable_share` of the budget's hourly share times that window | session or project | note; project supervisor |
| `expensive-automation` | a session with at least `automation_min_share` of its weighted units in automatic-origin turns (task notices, peer and child messages, app notices, routines) runs its main model on `expensive_model_pattern` | session | session model; usage role |

"Automatic origin" is every origin except `human`, `compact` and `subagent`. A `session-model` proposal sets the session to `cheap_model`; without a `target_app_id` (D4) or with an empty `cheap_model` it is a `note` for the project supervisor. The proposal and undo texts come from `proposals.<rule>` in the config (generic defaults, translated in the override).

### D6. Finding identity, machine-wide findings and the never-repeat rule

A finding whose proposal is a `config` change is **machine-wide**: its scope is `machine` and its id is derived from the rule family of the proposal and `piece|key|value`, not from a session. So `expensive-subagents` and `advisor-excess` in any number of sessions produce at most one finding per config change, whose evidence lists the sessions. `detect` raises no config finding whose value is already in effect in the installed piece. Concretely its id is `config-<first 10 hex of sha1(config | machine | piece|key|value)>`, its `rule` names the first rule that raised it and `evidence.rules` every rule that did. Every other finding is scoped to a session or project as below. Session rules look at the last 24 hours (`pace` at its own windows).

`id = <rule>-<first 10 hex of sha1(rule | scope kind | scope id | discriminator)>`. The discriminator is the repeated text hash or call signature for `loop`, the model for `role-model` and `expensive-automation`, and empty for the others. `detect` adds a finding only when its id is not in the store, whatever its state. A finding that is detected again only refreshes `last_seen` and its evidence while it is `new`; in any later state it is left untouched. So a question already asked or rejected is never asked again.

### D7. State machine and the single apply point

States: `new → asked → authorized | rejected → applied → measured`. Each transition is a subcommand and appends `{state, at, by, ref}` to the finding's history under an exclusive `flock` on the store.

- `ask ID --question TEXT [--project DIR]`: from `new`. Calls `ask-queue add --project P --question TEXT --default <config no_default> --why <evidence line> --blocks nothing --key usage-watch:ID [--order <config order_text>]`, records the queue project and id. `P` is the finding's project when that project has a live supervision lock with a `mailbox`; otherwise (no questions session would ever present it) and for machine-wide findings, `P` is the usage role's `home_project` (D8). With the default empty `order_text` and `--blocks nothing`, the item is never blocking-due, so it waits for the project's final batch; the override sets `order_text` to have it presented in a partial batch at once. `--order` is passed only when `order_text` is not empty; the default is empty, and the developer's own words belong in the override, never in this repository.
  The question text is the role's `--question`, a blank line, a `change` line (`labels.change`: the exact change `apply` would make, `flow.change_text`; G-16), a blank line and `authorize_hint` (config; default: answer `apply` to authorise, anything else leaves things as they are). `ask` also records the asker's ids (`CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_HOST_SESSION_ID`) in the finding.

**Where `authorized` comes from (G-01).** Only the queue decides; no command takes the outcome as an argument.

- **Queue verdict** (one function, used by `decide`, `apply` and `wait`): read the item with `ask-queue list --project P --json` and classify it:
  - `pending`: the item is `open` or `asked`, or missing;
  - `untrusted`: `answered`, but `answered_by` is empty, or is one of the ids that registered the item (`session`, `host_session` of the item, the asker's ids recorded by `ask`), or one of the usage role holder's ids (`usage-role.json`). The role cannot authorise its own question by running `ask-queue answer` itself;
  - `authorize`: `answered`, trusted, and the answer, normalised (case-folded, outer whitespace and punctuation stripped), is one of `authorize_answers` (config list, default `["apply"]`);
  - `reject`: `answered` and trusted with any other answer, or `closed` (closed without an answer).
- `decide ID` (no outcome flag): from `asked`. `authorize` → `authorized`; `reject` → `rejected`; both record the answer text, `answered_by` and `answered_ts` in the history. `pending` or `untrusted` → exit 3, nothing written, one line on stderr saying which.
- `apply ID [--how TEXT]`: from `authorized` only, **and** the queue verdict, read again at that moment, is still `authorize` with the same answer text that `decide` recorded. Any other state or verdict exits 3 and writes nothing, for every kind; a store edited by hand to `authorized` is therefore refused. Kinds:
  - `config`: writes `key = value` into `<override>/config/<piece>.json` and into `~/.claude/toolkit/config/<piece>.json`, after recording the previous values of both for the undo text. The installed piece is written byte-identical to the installer's rendering of defaults plus override, so `drift` reads it `in-sync`. Without an override directory, exit 3 (the change would be lost at the next install).
  - `session-model`, `session-effort`: the change itself is made with the app's session tool, which the script cannot run. `apply` needs the finding's `target_app_id` (else exit 3; `detect` already gives such findings the kind `note`) and writes a **ticket** `{finding, session: target_app_id, field: model|effort, value, issued_at, expires_at: now + ticket_ttl_s, used: false}` to `<state_dir>/tickets.json`, then moves the finding to `applied`. The hook of D14 lets the usage role's session-tool call through only against such a ticket. No `--how` is needed.
  - `note`: whoever applies it (normally the project supervisor) passes `--how`, else exit 2.
- `measure ID`: from `applied`, once `measure_window_h` have passed since `applied_at`; recomputes the rule's metric for the same scope over the window before and after and records both. Too early: exit 4.

Nothing else in `usage-watch` writes outside its state directory. `collect`, `detect`, `status`, `page`, `show`, `wait`, `tick` and `self-test` never write a config piece, the override, a session or the queue (`self-test` works in its own temporary directory and removes it).

### D8. The usage role (one per machine)

`supervisor-lock usage-role --claim|--beat|--release --session ID [--dir DIR]` keeps `<supervisor home>/usage-role.json` (`session_id`, `cli_session_id` from `CLAUDE_CODE_SESSION_ID` at claim time, `home_project`, `heartbeat`, `title`) under the same `Store` flock as the project locks, with the `running` TTL. Like `acquire`: a claim while another holder is live prints `HELD` and exits 3; while the other holder is stale it prints `STALE` and exits 4, and `--claim --from <old id>` takes the role over. The holder's own claim prints `RESUMED`. `list --json` adds a `usage_role` object. `closing.is_helper_row` also treats the holder as a helper row, so no project's `open`, `closable` or `backlog` counts it as work and no closing session archives it. `home_project` is the project of `--dir` (default the cwd); machine-wide findings go to its queue, and `status` warns when that project has no lock with a `mailbox` (nobody would present the questions).

### D9. The watcher

`usage-watch wait --session ID [--timeout S] [--interval S]` polls the store and the queue:

- `FINDING <id> <rule> <scope>` for each `new` finding not announced yet;
- `ANSWER <id>` for each `asked` finding whose queue item became `answered` or `closed`;
- each event is announced once (`<state_dir>/announced.json`), then `wait` exits 0;
- `--timeout 0` (default) never times out; a positive timeout prints `TIMEOUT <s>s` and exits 0;
- when `supervisor-lock` names another live holder of the usage role, `NOT HOLDER` on stderr and exit 5; when supervision is not installed, exit 6.

With no new finding and no answer, `wait` prints nothing, so the role gets no turn.

### D10. Hand-off to project supervisors

`supervisor-lock backlog` (project P) runs `usage-watch list --project P --state authorized --applier project-supervisor --json` when the script exists, and adds one `USAGE <id> <rule>: <proposal>` work line per finding. Those lines are work for the guard check like any open task, until the supervisor applies the finding (`usage-watch apply ID --how TEXT`). A failure of that call adds nothing and is logged, never raised.

### D11. Timer

`usage-watch timer print` renders `usage-watch.service` (`Type=oneshot`, `ExecStart=/usr/bin/python3 <script> tick`) and `usage-watch.timer` (`OnBootSec`, `OnUnitActiveSec = timer_interval_min`) to stdout; `timer install` writes them to `~/.config/systemd/user/` and runs `systemctl --user daemon-reload` and `enable --now usage-watch.timer`; `timer uninstall` disables and removes them; `timer status` reports whether they exist. The installer itself still writes no unit; the module note says to run `timer install` once. Tests use `print` and a fake `systemctl` on `PATH`.

### D12. Status line and page

- `status`: one line, e.g. `usage-watch: week 41% elapsed, 38% of budget, pace green · findings new 2, asked 1, authorized 0 · unpriced 0`. Pace: with `weekly_budget_units > 0`, projected week total over budget, green up to `pace_amber_ratio`, amber up to 1.0, red above; with no budget, `pace unknown` and no colour. The week starts at `week_start_weekday` (0 = Monday … 6) and `week_start_hour` (0 … 23), UTC; an out-of-range value keeps the default (Monday, 0). Information only: no rule or action reads the colour.
- `page`: a static HTML file at `page_path` with `<meta http-equiv="refresh">` every `page_refresh_s`, light and dark colours, readable at phone width, built from the same aggregates as `status` (ranking by session, project, model and origin, then the findings with their state). Labels come from `labels` in the config.

### D13. Exit codes of `usage-watch`

`0` ok · `2` usage error or unknown finding id · `3` refused transition (wrong state, queue verdict not `authorize`, untrusted answer, no override for a config change, no target app id) · `4` too early to measure · `5` not the usage role holder · `6` supervision pieces not installed.

### D14. The session-tool gate (`hooks/usage-apply-gate`, module `usage`)

A `PreToolUse` hook on the app's session tools that change a model or an effort (fragment matcher `mcp__ccd_session_mgmt__set_session_model|mcp__ccd_session_mgmt__set_session_effort`, the full tool names as in the existing fragments; the hook itself tells the two apart by the name's suffix). Rules:

- The caller is the usage role holder when the hook input's `session_id` or `CLAUDE_CODE_HOST_SESSION_ID` equals `session_id` or `cli_session_id` of `<supervisor home>/usage-role.json`. Any other caller, or no role file: allowed, silently. The gate restricts the role only; a supervisor or the developer changing a model is outside this change.
- For the holder: allowed only when `<state_dir>/tickets.json` (state dir from the `usage-watch` piece) holds a ticket with `used` false, `expires_at` after now (`USAGE_WATCH_NOW` or the clock), `session` equal to the tool input's `session_id`, `field` matching the tool (`model` or `effort`) and `value` equal to the tool input's value. The ticket is marked `used` under the store's `flock`, so one ticket allows one call. Otherwise: a `deny` decision whose reason names `usage-watch apply`.
- Unparseable input or an internal error: allowed, with the traceback in `<state_dir>/gate-errors.log` (the toolkit's fail-open rule for hooks). A deny is never the result of a crash.

This turns the procedural step of the first draft into a mechanical one: the role's tool call fails unless `apply` ran on a finding that the queue authorised (D7), and tests drive the hook with JSON input in a temporary `HOME`.

### D15. Details settled while applying Part B

- **Queue routing needs the checkout, not the name.** Every finding carries `project_root` (the main checkout of its
  session's `cwd`, or of the project for a project-scoped `pace` finding; null for machine-wide ones). `ask` sends the
  question to `project_root` when a live lock with a `mailbox` names that checkout, else to the role's `home_project`;
  `--project` is used only when neither exists. `--question` is optional: without it the proposal text is asked.
- **Role record words.** `usage-role --claim` prints `CLAIMED` (free role), `RESUMED` (the holder), `TAKEN` (with
  `--from` naming the holder), `HELD` (3) or `STALE` (4); `--beat` and `--release` by anyone but the holder exit 3 and
  change nothing. `list` prints a `USAGE-ROLE` line when the role is held. `wait` does not refresh the heartbeat: the
  holder runs `--beat` when it wakes, and a role left idle long enough reads `STALE`, which only a deliberate
  `--claim --from` takes over.
- **`FINDING` scope** is printed as `<scope kind>:<scope id>`.
- **`apply` of a config value** refuses (3) when the installed piece is missing or unreadable, writes the override
  piece with the same JSON layout, and keeps each file's mode (the installer's 0644), so `drift` reads it `in-sync`.
- **`measure` metric per rule:** advisor calls (`advisor-excess`); units of subagent calls on an expensive model
  (`expensive-subagents`); units of main calls on an expensive model (`role-model`, `expensive-automation`); automatic
  turns (`empty-wakes`); units of all calls of the scope (the rest). A machine-wide finding measures the whole machine.
- **Self-tests.** `usage-watch self-test` runs the role checks only when `ask-queue` and `supervisor-lock` sit next to
  it (an install with `supervision`); otherwise it says so in one line and runs the measuring half.

## Configuration (`global/config/usage-watch.json`, all defaults generic)

`projects_dir`, `app_sessions_dir`, `supervisor_home`, `state_dir`, `page_path`, `page_refresh_s`, `retention_days`, `prices`, `unit_label`, `expensive_model_pattern` (`opus|fable`, like `agent-model-gate`), `escalation_mark_pattern`, `panel_pattern`, `cheap_roles` (`questions`, `closer`, `usage`, `routine`, after the rule table of `modelo-por-rol.md`), `cheap_model` (the value a `session-model` proposal sets; empty turns those proposals into notes), `origin_text_prefixes` (text prefixes that mark an automatic turn, e.g. `<task-notification>` → `task`), every threshold of D5, `measure_window_h`, `weekly_budget_units` (0), `week_start_weekday`, `week_start_hour`, `pace_amber_ratio`, `timer_interval_min`, `order_text` (empty), `no_default`, `authorize_answers`, `authorize_hint`, `ticket_ttl_s`, `proposals`, `labels`. The exact default values are written in task 1.1 and are provisional; none is a figure observed on any machine.

Shapes (G-08). Top-level keys go through `toolkit_config.load_checked`, which checks only the top-level type, so the nested ones are checked entry by entry: a `prices` entry counts only when its key compiles as a regular expression and its value is a list of five numbers ≥ 0 (if no entry is valid, the default table is used); `proposals` maps a rule id to `{proposal, undo}` strings and `labels` maps a key to a string, and an entry of the wrong shape keeps that entry's default; a regular-expression key (`expensive_model_pattern`, `escalation_mark_pattern`, `panel_pattern`) that does not compile keeps its default.

## Risks / Trade-offs

- **Undocumented transcript format** → tolerant parsing, synthetic fixtures that pin the expected shape, and `status` reports how many lines were skipped as malformed.
- **False positives cost the developer's attention** → each rule has a healthy case in the tests; thresholds are config; a rejected finding is never asked again.
- **A config change outside the override would be undone or flagged** → D7 writes both files, the installed one byte-identical to the installer's rendering, and a test runs `drift` in a temporary `HOME` after `apply`.
- **The role could authorise itself** → the outcome is read from the queue, an answer by the asker or the role holder is untrusted, and `apply` re-reads the queue (D7). Residual: a shell-capable session that forges the environment `ask-queue` reads when it records `answered_by`; that is deliberate circumvention, the history keeps `answered_by` visible and the rule text forbids it.
- **Session model and effort are changed by an app tool the script cannot run** → the D14 hook makes the role's call depend on a ticket that only an authorised `apply` writes.
- **The host may end a background command that never exits** → UNKNOWN. `--timeout` exists so the skill can re-arm with a long timeout if that proves necessary; the reference text says so.
- **Large change** → tasks are ordered so Part A (sections 1 to 5) is complete and checked before Part B starts; the natural split, if needed later, is at that seam.

## Edge cases

- Empty projects directory: `collect` writes no records, `status` prints zero totals and `pace unknown`.
- A line with `model` `<synthetic>` or without `usage`: skipped.
- A response with only advisor iterations: the main part counts the top-level usage, the advisor part its iterations.
- `cache_creation` absent but `cache_creation_input_tokens` present: all of it counts as 5-minute writes.
- Transcript truncated or replaced (inode or size drop): read again from the start; dedup keeps totals right.
- A finding whose session has gone: it stays in the store; `measure` reports the after window as empty and still records it.
- Clock going backwards (simulated `now` earlier than records): records after `now` are ignored.
- Corrupt state or config file: defaults for the config; a corrupt store is moved aside as `<name>.corrupt-<n>` and a new one started, never raised.

## Testing strategy

All tests run in a temporary `HOME` with `CLAUDE_TOOLKIT_CONFIG_DIR`, `ASK_QUEUE_DIR`, `SUPERVISOR_LOCK_HOME` and `CLAUDE_TOOLKIT_OVERRIDE` pointing inside it, synthetic transcripts written by a small builder in the test module, and a simulated clock (`USAGE_WATCH_NOW`). For each rule: one test where it fires and one healthy case where it must not. For counting: one-pass equals two-pass totals, cross-file dedup, cache split, advisor split, unpriced model, rotated file. For the store: the full walk `new → … → measured`, every refused transition, no repeat after `asked` or `rejected`. For `decide`: the outcome follows the answer text, and an answer recorded by the asker, by the role holder or by nobody is refused. For `apply`, for a `config` finding and for a `session-model` finding alike: no file outside the state directory changes and no ticket is written in any state other than `authorized`, nor when the store says `authorized` but the queue item is not an authorising answer; after a config `apply` the toolkit's `drift` reports nothing for that piece. For the D14 hook: the holder is denied without a ticket, allowed once with one, denied with an expired or mismatched one, and other sessions are never touched. `usage-watch self-test` repeats the counting and rule cases in its own throwaway home (Part A) and the walk, refusals and watcher (Part B); `examples/override-full/try.sh` installs `usage` and runs it. For `wait`: silent with nothing new; one `FINDING`; one `ANSWER`; no second announcement; exit 5 for a non-holder. `supervisor-lock` tests and self-test probes cover the role record and the helper-row exclusion. Contracts get safe probes only.

## Private override: what has to be added there (by file and heading only)

This change does not edit the override. After it is merged, the override owner adds:

- `config/usage-watch.json`: `prices`, `unit_label`, `weekly_budget_units`, `week_start`, `order_text`, and any translated `proposals` and `labels`.
- `files/skills/supervisa-sesiones/SKILL.md`: heading `## Núcleo y referencias` (a row for the new reference) and heading `## Modelo por rol` (the new role).
- `files/skills/supervisa-sesiones/reference/subsupervision-consumo.md`: a new file, starting from the generic one this change adds.
- `files/skills/supervisa-sesiones/reference/arranque.md`: heading `## §0: el cerrojo, antes de nada` (check the usage role and open it when missing).
- `files/skills/supervisa-sesiones/reference/f5-decisiones.md`: heading `## La sesión de preguntas` (present the usage questions like any other queue item).
- `files/skills/supervisa-sesiones/reference/cambios.md`: a new dated entry under its entry template heading.
- `override.yaml`: add `usage` to `modules`.
