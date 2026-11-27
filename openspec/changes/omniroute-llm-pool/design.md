# Design — omniroute-llm-pool

Every statement below is marked **FACT** (measured or read in a source), **INFERENCE**, **HYPOTHESIS** (to be proven by a task) or **UNKNOWN** (a task answers it before anything depends on it).

## Context

| Statement | Kind | Evidence |
|---|---|---|
| A supervisor wake re-reads the whole context: 0.4–3 M tokens, typically 1 M, in 3–5 model calls, over 97 % cache reads | FACT | Transcripts of three supervisors, 2026-11-26/27 |
| Soft wakes (`TIMEOUT`, `STATUS`) cost about 4.1 M tokens/h across three supervisors, 26 % of their main-transcript flow, at 4.6 wakes/h | FACT | Same measurement, 3.07 h window |
| OmniRoute serves an OpenAI-compatible `/v1` and a dashboard on loopback port 20128 by default; `omniroute serve --headless` runs without the dashboard | FACT | README, release line 3.8 |
| `omniroute run claude --model <provider/model>` starts Claude Code with the gateway URL and key in its environment and writes nothing to disk; `omniroute configure claude` writes the global Claude settings | FACT | README, "Compatible CLIs" |
| A combo is a named list of targets with a strategy and automatic fallback on quota, provider failure or model lockout; combos can be created from the CLI | FACT | README, "Combos" |
| OmniRoute has usage analytics, cost estimation, per-key limits, a free-tier quota page, a model allow/deny list, a strict zero-cost mode, webhooks, log export, `--output json` on its CLI and an MCP server | FACT | README, documentation index |
| The free quota that can really be used is about 90 M tokens a month, with the user's own provider accounts | FACT | README, "Free Tokens a Month" |
| Several free tiers may use what they receive to train models | INFERENCE | Provider terms vary; each must be read (task 1.4) |
| The exact CLI and HTTP calls to list models, read quota and usage per key, and update a combo | UNKNOWN | Task 1.2 |
| Whether a gateway response carries a request id that joins it to OmniRoute's own call log | UNKNOWN | Task 1.2 |
| Whether small free models classify soft wakes well enough | HYPOTHESIS | Shadow mode, tasks 5.x |
| How the main model's usage limit weighs cache reads against fresh input | UNKNOWN | Task 7.2 |
| Whether the desktop app can start a session against another endpoint | UNKNOWN | Task 8.3; nothing in phases 1–7 depends on it |

## The idea in one paragraph

The pool is a lever, not a replacement. With about 3 M free tokens a day against hundreds of millions spent, the only sensible use is the one where a small pool call avoids a large main-model call. A triage call of about 5 000 tokens that keeps a supervisor asleep avoids about 1 M tokens: a leverage near 200. **Leverage (main-model tokens avoided ÷ pool tokens spent) is the figure this design optimises and reports.** HYPOTHESIS, from the measured wake rate: triaging every soft wake of three supervisors needs about 17 M pool tokens a month, well inside the free quota.

## Goals / Non-Goals

**Goals:**
- The developer sees and controls the pool: which models exist, which are on, what for, how strong, at what cost.
- Supervision spends fewer main-model tokens, and the saving is measured, not assumed.
- A wrong pool answer cannot stall or damage work: every path falls back to the main model.
- Nothing private reaches a provider that may train on it.

**Non-Goals:**
- A general LLM router for all sessions.
- A second dashboard for providers and keys.

## Architecture

```
developer ── prompt ──► skill llm-pool ─┐
developer ── console (app window) ──────┼─► llm-pool CLI / local API ──► registry + policy (config piece, state)
                                        │                               ├─► ledger (SQLite, local)
supervisor watcher ── soft event ──► llm-pool ask ──► privacy gate ──► OmniRoute (loopback) ──► providers
child session ─────── digest ──────►      │
                                          └─► no eligible member / budget / gate ──► caller uses the main model
```

- **OmniRoute owns** providers, keys, quotas, combos and its call log.
- **`llm-pool` owns** the policy (who is on, for what, in which mode), the gate, the budgets and the attribution of each call to a session, a project and a task.
- The module reaches a member through one combo per member or per task kind (decided in task 1.2), so OmniRoute's fallback never silently picks a model the policy has switched off.

## Decisions

### D1 — An optional module beside supervision, not inside it
`llm-pool` depends on `core` only. `supervision` works without it; the watcher's triage step is a provider that answers "wake" when the module or the gateway is missing. Reason: the toolkit's rule that a piece only cites what its module or its dependencies install, and that every caller works without optional pieces.

### D2 — The gateway is never wired into global configuration
The module calls the gateway's HTTP endpoint itself. `omniroute configure claude` is never run. `omniroute run claude` is used only by the experimental headless workers (D14), per process. The gateway URL comes from the `llm-pool` config piece (default: OmniRoute's own default), so a machine can move it to a leased port. The key is read from a file outside the repository and outside the config piece, mode 0600, and is never printed.

### D3 — One pinned gateway version
`gateway.version` in the config piece. `llm-pool doctor` fails when the running version differs. Updating is an explicit act with the shadow scorecards re-checked afterwards. Reason: a gateway of this size changes often, and a routing change could send a task to a model the policy never evaluated.

### D4 — Registry: static description in config, dynamic state apart
The config piece holds what a person decides (description, power, assignments, data class accepted, billing). A state file holds what the machine observes (state, quota left, health, last error). Reason: the override stays readable and reviewable, and an automatic state change never rewrites the developer's file.

Member states: `active`, `paused` (by a person), `exhausted` (quota, returns at reset), `cooldown` (errors, returns after a delay), `probation` (quality fell, returns to `shadow` only), `blocked` (no key, unknown terms, version mismatch), `retired`.

Power levels: 1 classification and routing, 2 short summaries and digests, 3 long summaries and plain-language drafting, 4 code reading and multi-step reasoning, 5 reserved for work that today stays on the main model. The level is set by the developer; the console may suggest one from OmniRoute's model data when it exposes it (UNKNOWN, task 1.2).

### D5 — Task kinds are a catalog, each with a data class and a minimum power

| Task kind | What the pool does | Input class | Min power | Leverage |
|---|---|---|---|---|
| `wake-triage` | For a soft watcher event, answer `sleep` or `wake` with a reason | internal | 2 | very high |
| `wake-digest` | Turn the event, the register's tail and the work in flight into five lines for the supervisor | internal | 2 | high |
| `turn-report-check` | Classify a child's end-of-turn report: done, handed back, asks, blocked | private | 3 | high |
| `log-digest` | Reduce a long command or test output to failures and their locations | private | 2 | medium |
| `census-summary` | Say in words what changed between two censuses | internal | 1 | medium |
| `closing-evidence-summary` | Summarise the closer's checks for the register | private | 2 | medium |
| `dialog-draft` | Draft the plain-language text of a question for the developer | private | 3 | low |

Never offloaded: decisions the supervisor or a panel takes, merges, deploys, anything that writes to a repository, anything addressed to the developer without the main model reading it first, security judgements.

Data classes: `public` (could be published), `internal` (signal names, counts, session titles, timings: no code, no customer data, no secrets), `private` (code, transcripts, logs, anything from a customer).

### D6 — Four modes, promotion by the developer, demotion automatic
Per pair (task kind, member): `off` → `shadow` → `assist` → `auto`.

- `shadow`: the pool answers, the caller ignores the answer and does what it did before; the ledger records both, and agreement is computed later from what really happened.
- `assist`: the answer is given to the main model as input, marked as a pool answer. Saves tool calls, not wakes.
- `auto`: the caller acts on the answer. Only `wake-triage` and `census-summary` may ever reach `auto`; every digest stops at `assist`, because a session must be able to read the original before it acts.
- Promotion needs a scorecard: at least 50 shadow samples and, for `wake-triage`, no false `sleep` (see D8) and an agreement of 95 % or more. The developer promotes, by prompt or in the console. Two misses in `auto` within a day move the pair to `probation`.

Alternative considered: trust a model by reputation. Rejected: the cost of a false `sleep` is a stalled project.

### D7 — The saving dial
One integer, 0 to 3, per machine with an optional value per project.

| Level | What is offloaded |
|---|---|
| 0 | Nothing. The pool is off (also the kill switch) |
| 1 | `wake-triage`, `wake-digest`, `census-summary` |
| 2 | Level 1 plus `turn-report-check`, `log-digest`, `closing-evidence-summary` |
| 3 | Level 2 plus `dialog-draft` and the experimental extensions that are switched on |

The dial can be `manual` or `follow-usage`: a provider reports the main model's usage (weekly and short-window percentage) and thresholds in the config piece map it to a level. Without the provider, the dial stays manual. A mode never exceeds what D6 allows: the dial selects among task kinds already promoted.

### D8 — Triage can only be wrong in the safe direction
- Hard events always wake and are never sent to the pool: anything that says a session crashed, hung, waits for a person, appeared, disappeared, was cut, can be closed, that the skill changed, or that the developer wrote.
- Soft events are the candidates: a timeout with no event, a status change with no turn end, and the repeated notices of `supervisor-wake-economy`.
- The brief sent is `internal` only: signal lines, counts, ages, the supervisor's own list of work in flight with its deadlines. No transcript text.
- A `sleep` is honoured only if the next forced wake is not later than the nearest deadline of the work in flight and not later than a maximum silent time (config, default 2 h). After a configured number of consecutive sleeps (default 4) the next soft event wakes.
- Anything other than a well-formed `sleep` (timeout, error, refusal, malformed answer, no eligible member, budget, gate) is a `wake`.
- A false `sleep` is defined afterwards: the supervisor, at its next wake, took an action that the slept event should have triggered. The supervisor's tick records it with one command; it is the miss that demotes.
- The triage runs inside the watcher process before it exits, so a `sleep` costs no main-model token at all.

### D9 — Privacy gate before every send
1. The task kind's input class must be accepted by the member (`accepts`). A member whose provider terms are unread or allow training accepts `public` only.
2. A redactor masks secrets and personal identifiers with the privacy checker's patterns plus key and token shapes. If a secret is still detected after masking, the send is refused for every member that is not local.
3. The project must be enabled for the pool, and projects on the supervision exclusion list are never enabled.
4. Provider terms are recorded per provider with a source link and the date they were read; an entry older than 90 days falls back to `public` until re-read.

### D10 — Budgets, and no billed call by default
- Members are `free`, `plan` or `paid`. `paid` members are `blocked` unless the config piece holds a monthly cap greater than zero, and stop when the ledger's spend reaches it.
- The free quota is rationed: a daily budget per member and a share per task kind, so a burst of digests cannot starve triage. Triage has the first claim.
- Quota close to expiry is spent first when two members are otherwise equal.

### D11 — The ledger is local SQLite, with a bounded payload
One row per call: time, caller session, project, role (supervisor or child), task kind, member, mode, tokens in and out, latency, cost reported by the gateway, outcome, the verdict, the main-model tokens estimated as avoided, and the later judgement (agreed, missed, unknown). The request and the answer are kept redacted for a configurable number of days (default 7; 0 keeps none) so the history window can show what a model did. Reason for SQLite: pagination and filters over months of rows with the standard library only.

Avoided tokens are an estimate with a stated rule: for a `sleep` in `auto`, the supervisor's median wake cost over its last 20 wakes; for a digest in `assist`, the size of what the main model did not read. Shadow rows count as zero. Figures are shown raw and weighted, with the weights of cache reads and cache writes taken from the config piece.

### D12 — The console is a local page in an app window
`llm-pool console` starts a loopback HTTP server from the standard library, serves static files shipped with the module (no build step, no external requests) and opens the page in a browser app window; the installer can add a desktop launcher. Reason: the toolkit installs Python and shell pieces into a home directory and has no build chain; a packaged desktop framework would be the largest thing in the repository. OmniRoute's own dashboard is linked for what belongs to it (providers, keys, combos), not rebuilt.

Writes from the console go through the same code as the CLI, need a per-start token and are audited with `console` as the actor. The console never shows a key.

### D13 — Control by prompt is a thin skill over the CLI
The skill maps a request in plain words to one `llm-pool` command, shows the command and its result, and never edits files itself. Anything that widens exposure (promoting a mode, enabling a project, approving a paid cap, accepting a data class) needs the developer's own words in that session; the skill refuses when the request comes from another session or from a file.

### D14 — Extensions behind their own switches
All off by default; each has its own task group and none blocks the core.

- **Local models as members** (`billing: local`, `accepts: private`): reached through the gateway's self-hosted entry. Private and unmetered, but they use the machine, so starting one is a heavy job of the machine's own queue.
- **What-if simulator**: replays the last days of supervisor wakes from the transcripts against a candidate policy and reports the wakes it would have slept and the pool tokens it would have cost, before anything is switched on.
- **Replay**: re-run a stored request on another member and show both answers side by side, to choose who gets a task kind.
- **Scorecards**: agreement, miss rate, latency and tokens per (task kind, member), from shadow and canary rows.
- **Canary**: every n-th `auto` verdict is also judged by the main model at its next natural wake, at no extra wake.
- **Quota forecast and recommendations**: days until a member's quota runs out at the current rate; a suggestion when quota is about to expire unused or when a cheaper member has earned a task kind.
- **Schedules**: a dial level per time window, for unattended hours.
- **Weekly saving line** in the supervisor's report: pool tokens spent, main-model tokens avoided, leverage, misses.
- **Headless pool workers** (experimental, level 3 only): `omniroute run claude` in print mode for bounded micro-tasks with public input. Not specified further here; it gets its own change if the spike (task 8.3) supports it.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| A false `sleep` stalls a project | D8: hard events never triaged, bounded silence, forced wake, demotion on the first misses, shadow before auto |
| Private data reaches a provider that trains on it | D9: class per task kind and per member, redaction, default deny, terms with a date |
| The saving is smaller than raw tokens suggest, because cache reads are cheap | D11: weighted figures; task 7.2 measures the usage limit before and after |
| The gateway changes routing under the policy | D3: pinned version; one combo per member or task kind; doctor |
| Free tiers disappear or shrink | States `exhausted` and `blocked`; every path falls back to the main model; forecast |
| A large third-party package on the machine | Loopback only, pinned, run as the user, MCP over HTTP left disabled, no remote mode |
| The console becomes a second place to manage providers | D12: it links to OmniRoute for that |

## Migration Plan

1. Spike with the gateway installed and at least one provider connected by the developer (task group 1). It ends with the UNKNOWN rows answered and written here.
2. Core with no traffic: registry, CLI, ledger, doctor, tests against a stub gateway.
3. `ask` with the gate and the budgets.
4. Console and prompt control.
5. Supervision integration in `shadow` for at least a week.
6. The developer promotes `wake-triage` to `auto` for one project; measurement; then the rest.
7. Extensions, one at a time.

Rollback at any point: dial to 0. Nothing else depends on the pool.

## Open Questions

- Which providers the developer will connect, and therefore which members exist (his decision; the registry ships with examples only).
- Whether an earlier OmniRoute data directory on a machine should be reused or set aside (task 1.1 inspects it without reading credentials).
- The port: OmniRoute's default or one from the machine's port registry (decided per machine in the override).
