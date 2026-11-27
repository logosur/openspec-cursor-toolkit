# Design — omniroute-llm-pool

Every statement below is marked **FACT** (measured or read in a source), **INFERENCE**, **HYPOTHESIS** (to be proven by a task) or **UNKNOWN** (a task answers it before anything depends on it). The gap review of this change is in `GAPS.md`; decisions changed by it carry the gap id (G-nn).

## Context

| Statement | Kind | Evidence |
|---|---|---|
| A supervisor wake re-reads the whole context: 0.4–3 M tokens, typically 1 M, in 3–5 model calls, over 97 % cache reads | FACT | Transcripts of three supervisors, measured for this change |
| Soft wakes (a timeout with no event, or a session going from idle to busy) cost about 3.8 M raw tokens/h across three supervisors, 24 % of their main-transcript flow, at 3.6 wakes/h | FACT, small sample | Same measurement, 3.07 h window: 11 wakes, 11.7 M tokens |
| OmniRoute serves an OpenAI-compatible `/v1` and a dashboard on a loopback port by default; `omniroute serve --headless` runs without the dashboard | FACT | README, release line 3.8 |
| `omniroute run claude --model <provider/model>` starts Claude Code with the gateway URL and key in its environment and writes nothing to disk; `omniroute configure claude` writes the global Claude settings | FACT | README, "Compatible CLIs" |
| A combo is a named list of targets with a strategy and automatic fallback on quota, provider failure or model lockout; combos can be created from the CLI | FACT | README, "Combos" |
| OmniRoute has usage analytics, cost estimation, per-key limits, a free-tier quota page, a model allow/deny list, a strict zero-cost mode, webhooks, log export, a compression pipeline, `--output json` on its CLI and an MCP server | FACT | README, documentation index |
| The free quota that can really be used is about 90 M tokens a month, with the user's own provider accounts | FACT | README, "Free Tokens a Month" |
| The watcher exits on the first poll that has events; every edge event is a difference against one snapshot taken when the wait started | FACT | `global/scripts/lib/supervisor/watch.py:284`, `:346-362`, `:398-400` |
| `ALLIDLE`, `QUEUED`, `SLOTHELD`, `CLOUD` and `BACKLOG` record "already announced" when the line is generated, before anyone decides what to do with it | FACT | `watch.py:132-133`; `global/scripts/lib/supervisor/cloud.py:328` |
| The deadlines of the work in flight exist only as free text in a table the supervisor writes; no script reads them | FACT | `global/skills/supervisa-sesiones/reference/registro-y-cierre.md:60-61`; `reference/vigilancia.md:57-58` |
| A config piece and its override merge key by key at the top level; a list or a table in the override replaces the shipped one whole | FACT | `scripts/toolkit/config.py:23`; `global/scripts/lib/toolkit_config.py:32` |
| The installer writes only under the Claude directory and refuses to reinstall over a file edited in place | FACT | `scripts/toolkit/modules.py:26`; `scripts/toolkit/apply.py:46-64`; `scripts/toolkit/cli.py:71-78` |
| The privacy checker is a tool of this repository: it is not installed, needs a YAML library and knows four secret shapes | FACT | `README.md:164`; `scripts/privacy-check.py:41`; `scripts/privacy-patterns.yaml:47-59` |
| Several free tiers may use what they receive to train models | INFERENCE | Provider terms vary; each must be read (task 1.4) |
| The exact CLI and HTTP calls to list models, read quota and usage per key, and update a combo; whether compression, telemetry, webhooks and log export can be switched off per key | UNKNOWN | Tasks 1.3 and 1.6 |
| Whether a gateway response carries a request id that joins it to OmniRoute's own call log, and the model that really answered | UNKNOWN | Task 1.3 |
| The usage limit weighs a cache-read token at about a fiftieth of a cache-write token (0.02, range 0 to 0.05); output against cache write is weak (1, range 0 to 3) | FACT, one machine, two weeks | `evidence/cache-weights.md` (task 1.7) |
| How the usage limit weighs any of them against fresh input | UNKNOWN, and the data cannot separate it | `evidence/cache-weights.md`: fresh input is 0.001 % of the tokens |
| A fixed rule that sleeps every soft wake would have slept 22 needed wakes in 202 over seven days (10.9 per 100), and saved at most 5.6 % of the supervisors' flow at the central weights | FACT, with one wake in three unclassified, so the go/no-go stays open | `evidence/what-if.md` (tasks 6.1–6.3) |
| Whether a pool model given the same structured brief sleeps the soft wakes more safely than the rule | UNKNOWN, and the question the whole triage rests on | The shadow test of D15, after task 6.5 |
| Whether small free models classify soft wakes well enough | HYPOTHESIS | Shadow mode, task 7.1 |
| Whether the desktop app can start a session against another endpoint | UNKNOWN | Task 8.3; nothing in groups 1–7 depends on it |

## The idea in one paragraph

The pool is a lever, not a replacement. With about 3 M free tokens a day against hundreds of millions spent, the only sensible use is the one where a small pool call avoids a large main-model call. A triage call of about 2 000 tokens that keeps a supervisor asleep avoids about 1 M raw tokens: a raw leverage in the hundreds. **Raw leverage overstates the saving**, because 98 % of a wake is cache reads and the usage limit probably counts them at a fraction: with a weight of 0.1, taken only as an example, the same wake is worth about 118 000 units and the leverage is in the tens. Measured since (task 1.7): a cache read weighs about 0.02 of a cache write, so a soft wake is worth about 42 000 cache-write tokens and the leverage of a 2 000-token triage call is about 20. **Weighted leverage (main-model units avoided ÷ pool tokens spent) is the figure this design optimises and reports**; raw figures are always shown beside it. HYPOTHESIS, from the measured wake rate: triaging every soft wake of three supervisors needs under 10 M pool tokens a month, well inside the free quota.

**What the gap review changed (G-40).** Once the triage brief is reduced to structured fields for privacy (D8), a fixed rule can read the same fields. So the first thing this change builds is not the pool but the comparison: a simulator that replays real wakes and says, for each soft one, whether the supervisor turned out to be needed. If a fixed rule that sleeps every soft wake within the bounds almost never sleeps a needed one, the rule is enough and no model is used for triage. `wake-triage` is built only if the rule is unsafe and a pool model is then shown to be safe and to keep a good part of the saving (D15).

## Goals / Non-Goals

**Goals:**
- The developer sees and controls the pool: which models exist, which are on, what for, how strong, at what cost, and when.
- Supervision spends fewer main-model tokens, and the saving is measured, not assumed.
- A wrong pool answer cannot stall or damage work: every path falls back to the main model.
- Nothing private reaches a provider that may train on it.

**Non-Goals:**
- A general LLM router for all sessions.
- A second dashboard for providers and keys.
- A security boundary between processes of the same user (D16).

## Architecture

```
developer ── prompt ──► skill llm-pool ─┐
developer ── console (app window) ──────┼─► llm-pool CLI / local API ──► definitions (config piece + override)
                                        │                               ├─► decisions (written by commands only)
                                        │                               ├─► observed state
                                        │                               └─► ledger (SQLite) and audit log
supervisor watcher ── soft event ──► llm-pool ask ──► privacy gate ──► OmniRoute (loopback) ──► providers
child session ─────── digest ──────►      │
                                          └─► any refusal or failure ──► caller does what it did before
```

- **OmniRoute owns** providers, keys, quotas and its own call log.
- **`llm-pool` owns** the policy (who is on, for what, in which mode, when), the gate, the budgets, the attribution of each call to a session, a project and a task, and the combos whose name starts with `llm-pool-`. It never edits another combo (G-42).
- The module reaches a member through one combo per member or per task kind (decided in task 1.5), so OmniRoute's fallback never silently picks a model the policy has switched off. `ask` also compares the model named in the response with the member's target and discards the answer when they differ (G-42).

## Decisions

### D1 — An optional module beside supervision, each working without the other
`llm-pool` depends on `core` only. Every other piece it uses is optional and reached through a provider that answers "absent" when the piece is missing (G-21):

| Piece | Module | Used for | When absent |
|---|---|---|---|
| `supervisor-lock` | `supervision` | who the caller is (D16), whether the developer is present for a widening command (D13) | every `ask` is refused with "caller not allowed"; widening only from the console or a terminal |
| `project-pause` | `supervision` | paused projects | no project counts as paused |
| `account-switch` | `accounts` | the main model's usage for `follow-usage` (D7) | the dial stays manual |
| `port-lease` | `devtools` | a warning when a configured port lies inside a leased block | no warning |
| `heavy-job` | `heavy-jobs` | starting a local model (D14) | local members cannot be started by the module |

Each is declared under `project_provided` in `llm-pool.yaml`, and `supervision.yaml` declares `scripts/llm-pool` the same way: the validator fails a manifest that cites a piece its closure does not install (`scripts/validate-toolkit.py:635`). `supervision` works without `llm-pool`: the watcher's triage step is a provider that answers "wake" when the module or the gateway is missing.

### D2 — The gateway is never wired into global configuration
The module calls the gateway's HTTP endpoint itself. `omniroute configure claude` is never run. `omniroute run claude` is used only by the experimental headless workers (D14), per process. The gateway URL comes from the `llm-pool` config piece (default: OmniRoute's own default), so a machine can move it. The key is read from the file the config key `gateway_key_file` names (default: `gateway.key` in the module's state directory, D4), mode 0600; the developer puts it there, the module never reads OmniRoute's own data directory, and the key is never printed, logged or stored.

The module adds no hook fragment and no settings key, and no `llm-pool` command writes the Claude settings file. "Unchanged settings" is tested as exactly that: the same install with and without the module yields the same settings file, and the file's hash is the same before and after a simulated day of commands. The toolkit's uninstall rewrites that file when its manifest recorded hooks of the toolkit (`scripts/toolkit/apply.py:144-154`), so byte identity across uninstall is not something this module can promise (G-22).

### D3 — One pinned gateway version, and third-party features off
`gateway_version` in the config piece. `llm-pool doctor` fails when the running version differs. Updating is an explicit act: when the pin changes, every pair in `auto` moves to `probation`, because its scorecard was earned on another version (G-70). Reason: a gateway of this size changes often, and a routing change could send a task to a model the policy never evaluated.

Doctor also checks every gateway feature that sends data somewhere else or rewrites a request, as far as the gateway lets it be read: HTTP MCP transport, remote or cloud mode, telemetry, webhooks, log export and prompt compression for the module's key. Which of these exist as settings is UNKNOWN until task 1.6; a feature that cannot be read is listed by doctor as "not verifiable", not as passed (G-43).

### D4 — Three places for three kinds of data (G-16, G-19, G-20, G-23)

| Layer | Holds | Written by | Where |
|---|---|---|---|
| **Definitions** | limits, defaults, the list of members (id, target, name, description, power, provider, billing, price, daily token budget, data class accepted), provider terms, paid caps, excluded projects, schedules | a person, in the override | config piece `llm-pool.json` + override |
| **Decisions** | which members are enabled, assignments, mode per pair, the dial of the machine and of each project, enabled projects, stop flags | `llm-pool` commands only, each audited | `decisions.json` in the state directory |
| **Observed state** | member state, quota left, reset time, health, last error | the module, from its own calls and from what the gateway reports (task 3.12) | `state.json` in the state directory |

Reasons: a command cannot write the installed config piece (the next install would refuse to replace an edited file) and no piece writes the override; and what costs money or widens what a provider may receive stays in a file only a person edits.

- The state directory is `llm-pool/` under the Claude directory, replaceable with the environment variable `LLM_POOL_HOME` so tests run in a temporary home. It also holds the ledger, the audit log and, by default, the key file. Uninstall leaves it, as the toolkit does with every piece's state; `llm-pool purge` removes it on request.
- The module validates its own config: the toolkit's checked loader accepts lists of strings only (`global/scripts/lib/toolkit_config.py:43-53`) and `members` is a list of objects. A member that fails validation is `blocked` with the reason, and the rest of the pool goes on.
- JSON files are replaced atomically under an advisory lock, as `port-lease` does. The ledger uses SQLite's write-ahead log with a busy timeout.
- **The shipped `members` list is empty.** A JSON piece cannot carry comments, so examples live in `examples/override-full/config/llm-pool.json` with invented names. Because the merge is shallow, an override's `members` replaces the shipped list whole, which loses nothing.
- **What an override may not loosen is not configuration**: the soft-event list, the task-kind catalog (input class, minimum power, highest mode) and the hard limits of D8 are constants of the code. Configuration can switch a task kind or a soft event off and set numbers inside the hard limits; a value outside them keeps the default (G-10).

Member states: `active`, `paused` (by a person or a command), `exhausted` (quota or cap, returns at reset), `cooldown` (errors, returns after a delay), `blocked` (no key, version mismatch, wrong model, a failed probe, no price or no monthly cap, no daily budget, its extension off, a local model not running). Unknown or stale provider terms do not block: the member then accepts `public` only (D9). A member that is no longer wanted is removed from the override. `probation` is a state of a pair (task kind, member), not of a member (G-47).

Power levels: 1 classification and routing, 2 short summaries and digests, 3 long summaries and plain-language drafting, 4 code reading and multi-step reasoning, 5 reserved for work that today stays on the main model. The level is set by the developer; the console may suggest one from OmniRoute's model data when it exposes it (UNKNOWN, task 1.3).

### D5 — Task kinds are a fixed catalog, each with a data class and a minimum power

| Task kind | What the pool does | Input class | Min power | From dial level | Highest mode | Saves |
|---|---|---|---|---|---|---|
| `wake-triage` | For a soft watcher event, answer `sleep` or `wake` with a reason code | internal | 2 | 1 | `auto` | a whole wake |
| `turn-report-check` | Classify a child's end-of-turn report: done, handed back, asks, blocked | private | 3 | 2 | `assist` | tool calls |
| `log-digest` | Reduce a long command or test output to failures and their locations | private | 2 | 2 | `assist` | reading a long output |
| `closing-evidence-summary` | Summarise the closer's checks for the register | private | 2 | 2 | `assist` | reading |
| `dialog-draft` | Draft the plain-language text of a question for the developer | private | 3 | 3 | `assist` | writing |

Never offloaded: decisions the supervisor or a panel takes, merges, deploys, anything that writes to a repository, anything addressed to the developer without the main model reading it first, security judgements.

Data classes:
- `public`: could be published.
- `internal`: a closed set of structured fields and nothing else: event kinds, session ids, statuses, counts, ages and durations. No title, label, branch name, path or free text of any kind, because those are written by people and agents and can name a customer (G-06).
- `private`: everything else: code, transcripts, logs, session titles, register text, anything from a customer.

`wake-digest`, which the first draft listed, is out of version 1: its input was the supervisor's register, which is private text, and the list of slept events it would summarise is printed by the watcher itself (G-07). `census-summary` is out too: nothing in the supervisor's tick would call it, and a task kind without a caller is only something to maintain (G-66). The catalog of version 1 has five task kinds.

Each task kind has a fixed instruction the caller cannot change, and requests go out with temperature 0 where the provider accepts it, so that a scorecard can be repeated as far as the provider allows.

### D6 — Four modes, promotion by the developer, demotion automatic
Per pair (task kind, member): `off` → `shadow` → `assist` → `auto`. A new assignment starts `off`.

- `shadow`: the pool answers, the caller ignores the answer and does what it did before; the ledger records it for judging.
- `assist`: the answer is given to the main model as data to read, inside a fixed envelope (D17). Saves reading, not wakes.
- `auto`: the caller acts on the answer. Only `wake-triage` may reach `auto`.
- **Every step up is a widening action** (D13), including `off` → `shadow`, because shadow already sends data to a provider.
- **Promoting `wake-triage` to `auto`** needs, in its scorecard: at least 50 judged shadow samples; at least 10 of them judged "the supervisor was needed", so that a model that always answers `sleep` cannot pass; no false `sleep`; and an agreement of 95 % or more. Samples nobody judged are `unknown` and count for nothing (G-35). A scorecard counts the rows judged since the pair last entered `shadow` or `probation`, so a pair that was demoted, or moved by a change of the gateway pin, earns its promotion again from zero (G-89).
- **Promoting an assist-only task kind** to `assist` needs at least 20 shadow samples judged, with 90 % judged acceptable. They are judged in the console's review view, or with `llm-pool review` by a main-model session the developer asks to do it. Shadow answers are never returned to the caller, so this review is the only way they are judged (G-37).
- **Demotion**: two misses in `auto` within 24 hours move the pair to `probation` (it runs in `shadow` and needs a new promotion). An override can only make this stricter: fewer misses, or a longer window. A change of the gateway pin does the same to every `auto` pair (D3). A response from a model other than the member's target blocks the member.

Alternative considered: trust a model by reputation. Rejected: the cost of a false `sleep` is a stalled project.

### D7 — The saving dial, and when it applies
One integer, 0 to 3, for the machine, with an optional lower value per project (`llm-pool dial <level> --project <dir>`, kept in the decisions). The level in force for a request is the lowest of: the machine's dial, the project's value, and the level of the schedule window in force.

| Level | What is offloaded |
|---|---|
| 0 | Nothing |
| 1 | `wake-triage` |
| 2 | Level 1 plus `turn-report-check`, `log-digest`, `closing-evidence-summary` |
| 3 | Level 2 plus `dialog-draft` and the experimental extensions that are switched on |

- **Schedules** are part of the core, because the request asks to control when each model is used: the definitions hold time windows (days of the week, local start and end) with a highest level and, optionally, the members allowed in that window. Outside every window the dial applies as set. A window can only lower what the dial allows.
- **`follow-usage`**: the level is computed from the main model's reported usage, between 0 and **the level the developer last set by hand, which stays the ceiling**. It never raises the dial above that, so it is not a widening action (G-27). Thresholds come in pairs (go up at one percentage, come back down ten points lower) and a level is held for at least 30 minutes, so the dial does not flap. By default it follows the weekly usage: level 1 from 50 %, level 2 from 70 %, level 3 from 85 % (D18). `follow-usage` is a mode of the machine's dial; a project's value is always a fixed number. The usage comes from `account-switch`, loaded as a module the way the supervisor's providers load it (`global/scripts/lib/supervisor/providers.py:18-20`); it only knows the account of the command line. Without it the dial is manual.
- **Stop is not the dial.** `llm-pool stop` sets a flag, for the machine or for one project, that is checked before everything else; the machine's flag wins over any project value. Stopping does not touch the dial or its mode, and `resume` only clears the flag, so the dial is afterwards what it was; `resume` is a widening action (G-31, G-67).
- A mode never exceeds what D6 allows: the dial selects among pairs already promoted.

### D8 — Triage can only be wrong in the safe direction
What the first draft called "keep waiting inside the watcher" does not exist in the code: the watcher prints the first batch of events and exits, and compares against a snapshot taken once. The mechanism is therefore specified here, and narrowed to what can be done safely (G-01, G-02, G-13).

- **Soft events are two exact shapes, fixed in the code:** (a) a batch made only of `STATUS <id> idle->busy` lines; (b) `TIMEOUT`, and only when the watcher was armed with `--wake-by` (below). A batch with any other line wakes at once and nothing is sent to the pool. An event kind the code does not list is hard. Triage never runs under `--guard`.
- **Out of version 1:** the repeated notices `ALLIDLE`, `QUEUED` and `SLOTHELD`. They consume their "already announced" record when generated, their first and repeated lines are identical, and `ALLIDLE` is the signal that a project has stalled. The back-off of `watcher-wake-backoff` already rations them.
- **Sleeping** means: the watcher appends the slept events to a journal on disk (per project, under the supervisor's home), replaces its snapshot with the current one, and goes on polling. The journal, not the process, holds the stretch: when it started, how many sleeps were honoured, and each slept event with its ledger id. It survives the watcher.
- **The deadline is an argument.** `wait` gains `--wake-by <time>`: the supervisor passes the nearest deadline of its work in flight, which today it already uses to choose `--timeout` (G-03). The watcher never reads the register.
- **A `sleep` is honoured only while all of these hold**, and the first of them to pass forces a wake:
  1. `--wake-by`, when given. Without it a `TIMEOUT` is hard and an idle-to-busy sleep never outlasts the `--timeout` the supervisor chose.
  2. The stretch's start plus the maximum silent time (config, default and hard limit 2 h). Outside guard mode the periodic report of bound 3 falls due every 30 minutes, so in practice this bound is a backstop that is rarely reached.
  3. The time the supervisor's periodic report falls due (`global/scripts/lib/supervisor/guard_report.py:13`).
  4. No item of the project is waiting for the supervisor by time alone: if the reviver would count one as unattended (`global/scripts/lib/supervisor/unattended.py:9`), every event is hard (G-05).
  5. Fewer consecutive sleeps than the limit (config, default and hard limit 4).
- **The brief is `internal`**: the event kinds, and per session its id, status, idle age and turn count; the seconds left to each bound above; the sleeps already honoured in the stretch. No title, no raw watcher line, no register text.
- **The answer** is one JSON object, `{"verdict": "sleep" | "wake", "reason": "<code>"}`, with the reason taken from a fixed list of codes (`started-work`, `nothing-changed`, `deadline-near`, `many-sessions`, `long-busy`, `unsure`). Anything else (other text around it, another verdict, an unknown code, a timeout, an error, a refusal, any non-zero exit, a response from another model) is a `wake`. The reason reaches the supervisor as a code, never as text a model wrote (G-34).
- **The added delay is bounded**: the triage has a time limit (default 20 s, hard limit 30 s) and runs inside the watcher, so a hard event that arrives meanwhile waits at most that long.
- **Judging is an explicit act.** The supervisor's tick has a step that lists the journal (`supervisor-lock slept`) and answers one question per entry: was I needed for this event before now? `supervisor-lock slept --judge <id>=needed|not-needed ...` records the answers and passes them to the pool's `judge`; the stretch closes when no entry is left unjudged. In `auto` a `wake` verdict is not journaled, because the supervisor is awake and nothing is at risk: those rows stay `unknown`. In `shadow` the watcher wakes as always and appends its verdict to the same journal, marked as shadow, so the same step and the same question judge it (G-68). The ledger turns the answer into a label: `agreed` (a sleep when not needed, a wake when needed), `missed` (a sleep when needed: the false sleep), `overwake` (a wake when not needed) or, when nobody judged, `unknown` (G-14, G-35, G-36).
- The journal is read by that step whatever woke the supervisor (the watcher, the developer, a hook), so sleeps are never lost when the wake came from elsewhere (G-04).
- A `sleep` costs no main-model token.

### D9 — Privacy gate before every send
1. The task kind's input class must be accepted by the member. This is eligibility: a member that does not accept the class is not a candidate, and when none is left the outcome is `no eligible member`, with the class named as the reason. `refused by gate` is kept for what is found in a payload's content (point 3). A member accepts `internal` only if its provider's terms were read within 90 days and do not allow training; `private` also needs a stated retention of 30 days or less. Otherwise it accepts `public` only, whatever its definition says (G-41).
2. `internal` payloads are built by the module from structured fields and validated against the closed set of D5; a caller cannot pass free text as `internal`.
3. A redactor masks secrets and personal identifiers in every `private` payload. It is the module's own code, standard library only, with its own pattern list: provider key prefixes, bearer tokens, JSON web tokens, PEM blocks, cloud access keys, `name=value` pairs whose name says secret, password, token or key, e-mail addresses, public IP addresses and home paths; plus the words of a private deny-list file when the config names one. It does not reuse the repository's privacy checker, which is not installed (G-18). If a secret is still detected after masking, the send is refused for every member that is not local.
4. The project must be enabled by command and not listed in the definitions' `excluded_projects`. That list belongs to this module: supervision's list of the same name means "never deployed without the developer" and has no matcher (`global/scripts/lib/supervisor/settings.py:122`) (G-11). A paused project is refused (G-12).
5. Tests build secret-shaped strings at run time from fragments, because the repository's privacy check scans test files too (G-26).

### D10 — Budgets, and no billed call by default
- Members are `free`, `plan`, `paid` or `local`. A `paid` member needs, in the definitions, a price per million tokens in and out and a monthly cap greater than zero, for it or for its provider; without either it is `blocked`.
- The cost of a call is the one the gateway reports or, when it reports none, the price times the tokens. Before sending, `ask` reserves the worst case (the request's token limit at the member's price) in the same ledger transaction that checks the cap, so parallel callers cannot pass the check together (G-32, G-50).
- The free quota is rationed: a daily token budget per member and a share per task kind, with half of it reserved for `wake-triage` by default. A day and a month are those of the machine's local time.
- A member that is not local needs a daily token budget in its definition; without one it is `blocked`.
- **Which member answers** is a fixed order among the eligible ones: the lowest power that is enough; then `local` before `free` before `plan` before `paid`; then the larger share of the daily budget left; then the id. `why` prints the order that decided. The gateway's quota expiry is not used: whether it can be read is UNKNOWN until task 1.3 (G-69).

### D11 — The ledger is local SQLite, with a bounded payload
One row per call, written **before** the request leaves, marked `pending` with the budget reserved, and completed when the answer or the failure is known. A `pending` row older than the request's time limit is closed as `lost` by the next command and its reservation counts as spent, so a killed process still leaves its row (G-50).

Each row: time, caller session, project, role (supervisor or child), task kind, member, the model the gateway says answered, mode, level in force, tokens in and out, latency, cost and whether it was reported or computed, outcome, verdict, the main-model tokens estimated as avoided, and the judgement (`agreed`, `missed`, `overwake`, `unknown`). A `missed` row of `wake-triage` is a false sleep; a `missed` row of another task kind is an answer reviewed as not acceptable, and the totals of false sleeps do not count it (G-90). The request and the answer are kept redacted for a configurable number of days (default 7; 0 keeps none); figures are kept for 400 days by default. The purge runs at most once a day at the start of any command; there is no daemon.

Avoided tokens are an estimate with a stated rule (G-38):
- For an honoured `sleep` later judged `agreed`: the median cost of that supervisor's last 20 **soft** wakes, read from its transcript with the same reader the simulator uses (D15). With 5 to 19 the figure is marked "thin baseline"; with fewer than 5 it is "no baseline" and counts as zero. A sleep judged `missed` or left `unknown` counts as zero.
- For a digest in `assist`: the size of the original minus the size of the digest, and zero when the caller reports that it read the original in full.
- Shadow rows and every fallback count as zero.
- The estimate does not include what a wake after a long silence may cost extra if the prompt cache expired meanwhile. The field measurement (task 7.4) compares real usage, not this estimate.

Figures are shown raw and weighted. The weights of cache reads and cache writes have no shipped default: until task 1.7 sets them, weighted figures are shown as "not set" (G-39).

### D12 — The console is a local page in an app window
`llm-pool console` starts a loopback HTTP server from the standard library, serves static files shipped with the module (no build step, no external requests) and opens the page with the command the config key `console_opener` names. With the key empty, which is the default, it uses the standard library's browser opener and, if that opens nothing, prints the address. Reason: the toolkit installs Python and shell pieces into a home directory and has no build chain. OmniRoute's own dashboard is linked for what belongs to it, not rebuilt.

- **Port:** `console_port`, default 0, meaning a free loopback port chosen at start. A fixed port that is taken is an error, never replaced silently.
- **Launcher:** the installer writes only under the Claude directory (`scripts/toolkit/modules.py:26`). So the launcher is the piece's own act: `llm-pool console --install-launcher` writes a desktop entry in the user's applications directory and `--remove-launcher` deletes it, as `claude-sessions-sync install` does for its service. Uninstall does not remove it; the module's notes say so (G-17).
- **Security (G-44):** the server generates a token at start and passes it to the page in the address fragment. Every API request, reads included, must carry it; requests are accepted only when their `Host` header is the loopback address with the server's port and, when they carry an origin, that origin is the console's own. The server stops after 30 minutes without a request, or with `llm-pool console --stop`. Writes go through the same code as the CLI and are audited with `console` as the actor. The console never shows a key. Limit, stated: on a machine with other local users the address passed to the opener is visible in the process list; this design assumes a single-user machine.

### D13 — Control by prompt is a thin skill over the CLI; widening is checked in the CLI
The skill maps a request in plain words to one `llm-pool` command, shows the command and its result, and never edits files itself.

Widening actions are: enabling a member or a project, any step up of a mode, raising the dial of the machine or of a project, and `resume`. The check lives in the command, not only in the skill (G-33). A widening command is accepted when one of these holds:
1. it comes from the console;
2. it is typed in a terminal (standard input is a terminal and no Claude session is in the environment);
3. it is run by a session with `--order '<the developer's words>'`, and the supervision piece confirms that the developer wrote in that same session within the presence window and that his newest message there contains the order (`global/scripts/lib/supervisor/human_turns.py:126` returns that message's text when asked). The presence part is the check `heavy-job` already makes for its priority order (`global/scripts/heavy-job:503-546`). Without the supervision piece, case 3 is refused.

The order is stored in the audit log. This stops mistakes and instructions that arrive in a message, a file or a tool result; it does not stop a hostile process of the same user, which no local command can (D16). What costs money or widens what a provider receives (a paid cap, a price, the data class a member accepts, provider terms) is not a command at all: it is edited in the override by a person.

Narrowing (disable, unassign, a step down, lowering the dial, `stop`) is accepted from anyone. So is `assign`, which only creates a pair in `off` and sends nothing; the step out of `off` is the widening one.

### D14 — Extensions behind their own switches
All off by default; each is switched on by naming its id in the config key `extensions`, has its own tasks and blocks nothing in the core. The ids: `local-models`, `replay`, `scorecards`, `routing-matrix`, `audit-timeline`, `simulator-report`, `canary`, `forecast`, `headless-workers`.

- **Local models as members** (`billing: local`, `accepts: private`): reached through the gateway's self-hosted entry. Private and unmetered, but they use the machine, so starting one is a heavy job of the machine's own queue.
- **Replay**: re-run a stored request on another member and show both answers side by side, to choose who gets a task kind.
- **Console views**, one id each: scorecards per pair (the figures themselves are core, because promotion needs them), the routing matrix of task kinds against members, the timeline of audited changes and the simulator's last report.
- **Canary**: every n-th `auto` verdict is also judged by the supervisor at its next natural wake.
- **Quota forecast and recommendations**: days until a member's quota runs out at the current rate; a suggestion when quota is about to expire unused or when a cheaper member has earned a task kind.
- **Headless pool workers** (experimental, level 3 only): `omniroute run claude` in print mode for bounded micro-tasks with public input. Not specified further here; it gets its own change if the spike (task 8.3) supports it.

Moved into the core by the gap review: schedules (D7), the what-if simulator (D15) and the saving line in the supervisor's report.

### D15 — Simulate first, then decide; and say when to stop (G-40, G-39)
- **The simulator** reads the last days of supervisor wakes from the transcripts. A wake is **soft** when the watcher's output that caused it was only idle-to-busy lines, or only `TIMEOUT`. A soft wake is **needed** when, in the turn that wake started (up to the next message that is not a tool result), the supervisor did any of these: sent a message to a session; started, stopped or archived one; ran a git command that writes; deployed; called a panel; queued a question for the developer. Anything else (census, register, reading files, the periodic report, re-arming) is routine, and the wake is **not needed**. A wake whose turn cannot be read whole (the transcript ends inside it, a compaction falls inside it, or the watcher's output is nowhere to be found) is **unclassified**: it is listed and left out of every rate (G-87). One case is not unclassified: a wake whose notice says the watcher was **stopped** and whose output holds no event is **hard**, because the watcher never finished and there was nothing to triage (G-99). So that the output can be found later, the watcher appends the events of each wake to a file beside the supervisor's lock (owner, start, end, event lines; 30 days), and the simulator reads it when the transcript does not hold them (G-98, task 6.4).
- **What it reports:** (A) today; (B) a fixed rule with no model that sleeps every soft wake, within the two bounds of D8 that history can rebuild (the maximum silent time and the consecutive sleeps). The other three bounds (the deadline, the report falling due, something waiting for the supervisor) are not in the history, and no recorded timeout carries a `--wake-by`. So both of B's figures are **upper bounds**: its saving, and the needed wakes it would have slept. The decision uses each only in the direction that is safe: a saving too small even at its best, or a rule safe even at its worst (G-86).
- **Why not "pool against rule" by saving (G-71):** the first hydration asked the pool to save 1.25 times what the rule saves. That cannot happen: the rule sleeps every soft wake the bounds allow, and a model can only sleep a part of them. What a model can add is safety, by waking for the ones that mattered. So the decision is about misses, not about saving.
- **Go/no-go for `wake-triage` (task 6.3): the first row that applies** (G-85). Rates are per 100 classified soft wakes.

| # | The report shows | Decision | Triage (tasks 5.2–5.6, group 7) | The rest of the pool (groups 2–4, task 5.7) |
|---|---|---|---|---|
| 1 | Fewer than 100 classified soft wakes, or more than one soft wake in ten unclassified | **open**: more days are recorded and the simulator runs again | not built | waits |
| 2 | B's saving under 5 % of the supervisors' weighted flow (raw, with a warning, when task 1.7 set no weights) | **no-go, too small** | closed as not built; the rule is not proposed either | only if the developer wants the pool for digests alone |
| 3 | At most 1 needed wake in 100 | **no-go, the rule is enough**: the fixed rule is proposed as its own change to the watcher | closed as not built | only if the developer wants the pool for digests alone |
| 4 | Anything else: the saving is worth it and the rule is unsafe | **open, a model must be tested**: `wake-triage` is built only if a candidate member is shown to sleep at most 1 needed wake in 100 while keeping at least half of B's saving and no less than 3 % of the flow; shown otherwise, neither is built | not built until that is shown | waits |

- **Row 4 is tested in `shadow`, on live wakes (G-83).** A replay cannot test a member: the brief is built from the state of the sessions when the event fired, and the history keeps the watcher's output, not that state; three of the brief's bounds are not in it either. So the test is the shadow period of task 7.1, moved before the "go": the watcher asks the member for a verdict on each soft wake, records it, and wakes the supervisor as before. Every one of those wakes then has a turn, and the simulator reads from it whether the supervisor was needed, with the same closed rule. The test ends at 100 classified soft wakes with a verdict; a late, failed or malformed answer counts as `wake`. The member passes with the thresholds of row 4. **What it costs:** the soft-event list (5.2), the brief builder and the parser (5.4), shadow mode (5.5) and the pool's `ask` for one task kind (groups 2 and 3 as far as that) are built before a "go", and may be thrown away on a "no-go". They are built only once the developer has installed the gateway and connected a member (task 1.2), which is his alone; until then row 4 builds nothing. Nothing that honours a `sleep` (5.3, 5.6) is built before the "go".
- **Which weights decide (G-101).** The cache weights came out as a range (task 1.7). The central weights decide the row; the report gives the saving at both ends of the range and says so when an end would change the row.
- **Stage 0, first record (2026-11-27, task 6.3): row 1, open, too little data.** Evidence: `evidence/what-if.md` and `evidence/cache-weights.md`.

| | 7 days to 2026-11-27 04:00 UTC | Since the watcher's back-off (8 hours) |
|---|---|---|
| Supervisor transcripts, wakes | 9, 941 | 7, 57 |
| Classified soft wakes | 202 | 23 |
| Unclassified, as a share of soft plus unclassified | 95, 32 % | 4, 15 % |
| Needed, per 100 classified soft wakes | 22, 10.9 | 1, 4.3 |
| The rule's saving over the flow, at most: raw / central weights / range | 7.5 % / 5.6 % / 3.5 to 6.4 % | 12.0 % / 6.8 % / 1.9 to 8.8 % |
| Row | 1: more than one soft wake in ten is unclassified | 1: fewer than 100 classified soft wakes |

  - The 7-day window fails on the unclassified share, because the watcher's output lived in temporary files and a restart erased them (G-98); the window since the back-off, which is the watcher as it runs today, is too short.
  - What the seven days already show: the fixed rule is **not safe** by the threshold (if every unclassified wake were soft and not needed, 22 in 297 would still be 7.4 per 100), so row 3 will not come out of them; and the saving **sits on the 5 % line** and falls under it if cache reads weigh nothing.
  - Cache weights (task 1.7), in units of one cache-write token: cache read 0.02 (0 to 0.05), output 1 (0 to 3); weights against fresh input cannot be separated. A soft wake of about 1.4 M raw tokens is worth about 42,000 cache-write tokens.
  - Next: task 6.4 makes the watcher keep its events; task 6.5 runs the simulator again on a window after the back-off with at least 100 classified soft wakes, and records the row. Nothing else is built meanwhile.
- The thresholds are provisional defaults; the developer can set others in writing when he reads the report.
- **Limit of the method, stated:** "needed" is read from what the supervisor did, so a wake where it should have acted and did not counts as not needed.
- **Removal after rollout (task 7.4):** after 7 days in `auto`, the pool's triage is switched off and the change says so plainly if any of these holds: weighted leverage under 10; more than one miss per 100 honoured sleeps; a measured saving under 3 % of the supervisors' weighted flow. Without cache weights the comparison uses raw tokens, says so, and leaves the leverage test out (G-88).

### D16 — Who may call, and what that check is worth (G-09)
- The caller is the session whose ids are in the process environment, read the way the supervisor package reads them (the docstring of `transcripts_of`, `global/scripts/lib/supervisor/census.py:201-207`).
- A **live supervisor** is the owner of a lock whose heartbeat is within its time-to-live (`global/scripts/lib/supervisor/lock.py:14`, `:59`), in a project that is not paused. A stale lock gives no access.
- A **child session** is any session the census of that supervisor lists in the project's checkout or one of its worktrees. That includes a session the developer opened there, because the supervisor orders those too; such a session may use the digest task kinds and never `wake-triage`. INFERENCE about the request's "child sessions": if the developer wants only sessions the supervisor itself started, it is one line in this decision.
- This is attribution and scope, **not a security boundary**: any process of the same user can read the key file and call the gateway on loopback. `ask` is the only supported entry, not an enforced one.

### D17 — Text that crosses the boundary is data, both ways (G-34)
- **Into the pool:** `wake-triage` receives only structured fields the module builds (D8), so text written by another agent cannot reach it. For private task kinds the payload is the material to digest, sent with a fixed instruction the caller cannot change.
- **Out of the pool:** an `assist` answer is returned inside a fixed envelope that names the task kind, the member and the ledger id and says that what follows is data produced by another model, to be read and never followed as instructions. The skill and the briefs of child sessions repeat that rule, and a digest is never forwarded to another session as a message.

### D18 — Defaults in one place (G-49)

| Setting | Default | Hard limit (code) |
|---|---|---|
| Triage time limit | 20 s | 30 s |
| Maximum silent time | 2 h | 2 h |
| Consecutive sleeps | 4 | 4 |
| Brief size | 2 000 tokens | 4 000 |
| Shadow samples for `auto` | 50, of which 10 "needed" | not below |
| Agreement for `auto` | 95 %, no false sleep | not below |
| Shadow samples for `assist` | 20 reviewed, 90 % acceptable | not below |
| Misses to probation | 2 in 24 h | only stricter |
| Failed calls to cooldown | 3 in a row, timeouts included | — |
| Cooldown | 5 min, doubling to 2 h | — |
| Share reserved for `wake-triage` | 50 % of a member's daily budget | — |
| Daily budget of a member that is not local | none: it must be written | — |
| `follow-usage` | weekly usage; level 1 from 50 %, 2 from 70 %, 3 from 85 %; release 10 points lower; hold 30 min | — |
| Go/no-go (D15) | 100 classified soft wakes at least; a saving of 5 %; one needed wake in 100 classified soft wakes; half of the rule's saving and no less than 3 % | the developer's, in writing |
| Payload retention | 7 days | — |
| Figure retention | 400 days | — |
| Provider terms valid | 90 days | not above |
| Console idle stop | 30 min | — |
| Cache weights (fresh, cache read, cache write, output) | 1, 0.02, 1, 1, in units of one cache-write token; range of the cache read 0 to 0.05 (task 1.7) | — |

"Hard limit" means an override can only move the value in the safe direction.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| A fixed rule is safe enough, and the pool was not needed for triage | D15: the simulator and the go/no-go come before any pool code for triage; a safe rule wins |
| A false `sleep` stalls a project | D8: two soft shapes only, five bounds, forced wake, explicit judging, demotion; shadow before auto |
| Private data reaches a provider that trains on it | D9: closed field set for `internal`, redaction, default deny, terms with a date |
| A digest carries instructions written by someone else | D17: envelope, never acted on alone, never forwarded |
| The saving is smaller than raw tokens suggest | D11 and D15: weighted figures, weights measured first, removal criterion |
| The gateway changes routing under the policy, or another model answers | D3: pinned version; own combos; the answering model is checked on every call |
| A widening command is run by an agent | D13: the check is in the command and needs the developer's presence |
| Free tiers disappear or shrink | States `exhausted` and `blocked`; every path falls back to the main model |
| A large third-party package on the machine | Loopback only, pinned, run as the user, doctor lists every outward feature |
| The console becomes a second place to manage providers | D12: it links to OmniRoute for that |

## Migration Plan

1. **Stage 0, decide whether it pays.** No gateway needed: the cache weights (task 1.7), the simulator and its report (6.1, 6.2), the go/no-go (6.3). In parallel, the spike with the gateway installed and at least one provider connected by the developer (1.1–1.6), which answers the UNKNOWN rows about the gateway. Stage 0 itself never needs the gateway. First record, 2026-11-27: row 1, open; the watcher keeps its events (6.4) and the simulator runs again (6.5). When the fixed rule turns out unsafe on that run, the decision stays open and a member is tested in `shadow` (D15), which does need the gateway.
2. Core with no traffic: definitions, decisions, CLI, ledger, doctor, tests against a stub gateway.
3. `ask` with the gate and the budgets.
4. Console and prompt control.
5. Supervision integration in `shadow` for at least a week (only if 6.3 said go; the digest task kinds do not depend on it).
6. The developer promotes `wake-triage` to `auto` for one project; measurement; removal criterion; then the rest.
7. Extensions, one at a time.

Rollback at any point: `llm-pool stop`. Nothing else depends on the pool.

## Open Questions

- Which providers the developer will connect, and therefore which members exist (his decision; the shipped list is empty).
- Whether an earlier OmniRoute data directory on a machine should be reused or set aside (task 1.1 inspects it without reading credentials).
- Whether "child sessions" should exclude sessions the developer opens himself in a supervised project (D16).
- The thresholds of D15, which are provisional until he reads the simulator's report.
- Whether the saving is worth the work at all: at the central weights the fixed rule saves at most about 6 % of the supervisors' flow, on the 5 % line of D15. He may prefer to close the triage now and keep the pool for digests alone, or not at all.
