# Proposal — omniroute-llm-pool

> **Created by:** `/prepara-tarea omniroute-llm-pool` — 2026-11-27; gap review (`GAPS.md`) and hydration the same day.
> **Origin:** a request to have OmniRoute, with a pool of LLMs that can be switched on and off by prompt or from a desktop app, used for now only by the supervisor session and its child sessions, with tight control of which model does what and when. **The goal is to spend fewer tokens.**
> **Status:** EXPLORE → PROPOSE → HYDRATE → VERIFY (`VERIFY.md`); **nothing is implemented**.
> **Related:** `watcher-wake-backoff` (the first step of the same goal, already installed).

## Why

Supervision is where the tokens go, and most of them buy nothing.

- FACT (measured on one machine over 24 h): about 790 million input tokens a day, 97.9 % of them cache reads, 96 % on the strongest model. Two supervisors alone account for about 150 million a day each.
- FACT (measured on three supervisors over 7 h): a watcher wake costs between 0.4 and 3 million tokens, typically one million, in 3 to 5 model calls. Soft wakes (a timeout with no event, or a session that merely started working) cost about 3.8 million raw tokens per hour across the three, a quarter of everything those supervisors spent. Small sample: 11 wakes in 3 hours.
- FACT (OmniRoute README, release line 3.8): OmniRoute is an MIT-licensed local gateway that puts many providers behind one endpoint, with named routing combos, quota-aware fallback, usage and cost tracking, a dashboard, a CLI with JSON output and an MCP server. Its own catalog puts the free quota that can really be used at about 90 million tokens a month, with the developer's own provider accounts.

So the free quota of a month is about a tenth of one day of use: **a pool of free models cannot replace the main model**. What it can do is act as a lever. A pool call of a few thousand tokens that lets a supervisor stay asleep avoids a million raw tokens of the main model. Raw tokens overstate it: nearly all of a wake is cache reads, which the usage limit probably counts at a fraction. The pool is worth having only where each of its tokens avoids many of the main model's **after that weighting**, and this change measures the weighting before building anything.

Three things are missing to use it that way:

1. **Control.** Nothing says which models are in the pool, which are on, what each is good for, how strong it is, what it may be given and at what hours.
2. **Routing by task.** Nothing decides that a given kind of supervision work may go to the pool, to which member, and when it must go back to the main model.
3. **Evidence.** Nothing records what the pool did, what it cost and what it saved, so nobody could tell whether it helps.

## What the gap review found, in one paragraph

The first draft had the watcher "keep waiting" on a pool verdict. The watcher cannot do that today, and making the triage safe for privacy reduces its input to a handful of structured fields (statuses, counts, ages). A fixed rule with no model can read the same fields. So it is an open question whether a pool model adds anything to the triage over such a rule. This change now starts by answering it: a simulator replays real wakes and says for each soft one whether the supervisor turned out to be needed. If a fixed rule that sleeps them all within the bounds almost never sleeps a needed one, the rule is enough and it is proposed on its own. The pool's triage is built only if the rule is unsafe and a pool model is then shown to be safe and to keep a good part of the saving; how that is shown is specified with the report in hand. The pool's other use, digesting long private outputs for child sessions, does not depend on that answer, but it saves reading, not wakes, and needs a provider that neither trains on prompts nor keeps them long, or a local model.

## What Changes

A new optional module, `llm-pool`, on top of an OmniRoute gateway that the developer installs and connects.

- **Stage 0: decide whether it pays.** Measure how the usage limit weighs cached tokens; replay recorded wakes under today's behaviour and under a fixed rule with no model; record a go/no-go for the watcher's triage.
- **Gateway contract.** OmniRoute pinned to one version, loopback only, never written into the global Claude settings. The module talks to it through its HTTP endpoint and its CLI, checks on every call that the model it asked for is the one that answered, and works (by doing nothing) when the gateway is absent.
- **Pool registry.** One entry per model: state, power level from 1 to 5, a one-line description of what it is good for, the task kinds it is assigned to, what class of data it may receive, how it is billed and its quota. Definitions are written by a person in the override; what commands decide and what the machine observes are kept in separate files.
- **Task routing.** A fixed catalog of supervision task kinds (wake triage, turn-report check, log digest and others), each with the data class of its input and the minimum power it needs. A task kind runs in one of four modes per member: `off`, `shadow` (the pool answers, nothing uses the answer, it is judged afterwards), `assist` (the answer is shown to the main model as data) or `auto` (the answer is acted on; wake triage only). Promotion is the developer's; demotion is automatic.
- **A saving dial with schedules.** One setting from 0 to 3 decides how much is offloaded; time windows decide when, and with which models. The dial can follow the main model's usage limit, up to the level the developer set.
- **Privacy gate and budgets.** Nothing private goes to a provider whose terms allow training on it or keep it long; secrets are masked before sending; billed models stay off unless a written monthly cap and a price exist; the free quota is rationed per day and per task kind.
- **Control by prompt and by CLI.** `llm-pool` commands and a skill that maps plain requests to them (switch a model on or off, assign it to a task, change the dial, stop everything). Anything that widens what the pool does is checked by the command itself and needs the developer. Every change is audited with who, when and why.
- **Usage ledger.** Every pool call is recorded with where it ran, what it was for, which model answered, tokens, cost, outcome and the main-model tokens it is estimated to have avoided, raw and weighted.
- **Desktop console.** A local app window that lists the pool with each model's state, description, power level, assignments, quota, tokens and cost, with a switch on each. A link opens a second window with the paginated history of where each model was used and what it did. A review view lets shadow answers be judged.
- **Supervision integration.** If stage 0 says go, the watcher asks the pool before waking the supervisor for two kinds of soft event, within five bounds, and the supervisor judges every sleep. Child reports and long outputs can be digested by the pool before the main model reads them. Scope for now: the supervisor session and its child sessions, nothing else.
- **Extensions**, each behind its own switch: local models as private pool members, replay of a past request on another model, scorecard and forecast views, headless pool workers for bounded micro-tasks.

## Capabilities

### New Capabilities

- `llm-pool-gateway`: how the module finds, checks and uses the OmniRoute gateway without touching global configuration.
- `llm-pool-registry`: the pool's members, their states and their attributes, and where each kind of data lives.
- `llm-pool-routing`: task kinds, modes, the saving dial and its schedules, the privacy gate, budgets and the scope of callers.
- `llm-pool-control`: commands, control by prompt, widening and narrowing, the kill switch and the audit trail.
- `llm-pool-ledger`: the record of every pool call, its judging and the saving figures derived from it.
- `llm-pool-console`: the desktop console, its history window and its review view.
- `supervision-offload`: the simulation that decides whether triage is built, what the supervisor and its child sessions hand to the pool, and the safety rules of doing so.

### Modified Capabilities

None in `openspec/specs/`. `supervisor-wake-economy` (in `watcher-wake-backoff`) is not modified: its repeated notices are left out of the triage.

## Impact

- New: `global/modules/llm-pool.yaml`, `global/scripts/llm-pool` with its library, `global/config/llm-pool.json`, `global/contracts/llm-pool.yaml`, a skill, tests in a temporary home with a stub gateway, the console's static files, and the example override's entry for the module.
- Touched, only if stage 0 says go: the watcher (`global/scripts/lib/supervisor/watch.py`) gains an optional triage step, a `--wake-by` argument and a sleep journal; `supervisor-lock` gains a command to read it; the supervision skill's tick gains a judging step.
- Touched in any case: `supervision.yaml` (declares the pool's command as provided elsewhere), `README.md`, `CLAUDE.md`, the example override.
- External: OmniRoute, installed and connected by the developer. Provider accounts are his; the module never creates one and never sees a provider key.
- No change to which model any session runs on. The pool works beside the main model.

## What only the developer can do

- Sign up with providers, connect them in OmniRoute's own dashboard and put the gateway key in its file.
- Write, in the override: the members, any billed model's price and monthly cap, what each provider's terms allow, the excluded projects and the schedules.
- Enable a member or a project, move a task kind up a mode, raise the dial, resume after a stop.
- Read the simulator's report and confirm or change the go/no-go thresholds.

## Non-goals

- Running supervisor or implementer sessions entirely on pool models.
- Using the pool outside the supervisor session and its child sessions.
- Replacing OmniRoute's dashboard: providers and keys are managed there. The module manages only the combos it names with its own prefix.
- Any model call that writes to a repository, decides a merge or a deploy, or answers the developer.
- Protecting the pool from another process of the same user: the caller check is attribution and scope, not a security boundary.
