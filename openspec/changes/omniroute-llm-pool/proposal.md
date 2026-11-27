# Proposal — omniroute-llm-pool

> **Created by:** `/prepara-tarea omniroute-llm-pool` — 2026-11-27
> **Origin:** a request to have OmniRoute, with a pool of LLMs that can be switched on and off by prompt or from a desktop app, used for now only by the supervisor session and its child sessions, with tight control of which model does what and when. **The goal is to spend fewer tokens.**
> **Status:** EXPLORE → PROPOSE → HYDRATE → VERIFY; **no implementation in this turn**.
> **Related:** `watcher-wake-backoff` (the first step of the same goal, already installed).

## Why

Supervision is where the tokens go, and most of them buy nothing.

- FACT (measured 2026-11-26, one machine, 24 h): about 790 million input tokens a day, 97.9 % of them cache reads, 96 % on the strongest model. Two supervisors alone account for about 150 million a day each.
- FACT (measured 2026-11-27, three supervisors, 7 h): a watcher wake costs between 0.4 and 3 million tokens, typically one million, in 3 to 5 model calls. Wakes that only confirm that nothing needs a decision (`TIMEOUT` heartbeats and `STATUS` changes) cost about 4 million tokens per hour across the three, a quarter of everything those supervisors spent.
- FACT (OmniRoute README, release line 3.8, read 2026-11-27): OmniRoute is an MIT-licensed local gateway that puts many providers behind one endpoint, with named routing combos, quota-aware fallback, usage and cost tracking, a dashboard, a CLI with JSON output and an MCP server. Its own catalog puts the free quota that can really be used at about 90 million tokens a month, with the developer's own provider accounts.

So the free quota of a month is about a tenth of one day of use: **a pool of free models cannot replace the main model**. What it can do is act as a lever. A pool call of a few thousand tokens that lets a supervisor stay asleep avoids a million tokens of the main model. The pool is worth having only where each of its tokens avoids many of the main model's.

Three things are missing to use it that way:

1. **Control.** Nothing says which models are in the pool, which are on, what each is good for, how strong it is and what it may be given.
2. **Routing by task.** Nothing decides that a given kind of supervision work may go to the pool, to which member, and when it must go back to the main model.
3. **Evidence.** Nothing records what the pool did, what it cost and what it saved, so nobody could tell whether it helps.

## What Changes

A new optional module, `llm-pool`, on top of an OmniRoute gateway that the developer installs and connects.

- **Gateway contract.** OmniRoute pinned to one version, loopback only, never written into the global Claude settings. The module talks to it through its HTTP endpoint and its CLI, and works (by doing nothing) when the gateway is absent.
- **Pool registry.** One entry per model: state, power level from 1 to 5, a one-line description of what it is good for, the task kinds it is assigned to, what class of data it may receive, how it is billed and its quota.
- **Task routing.** A catalog of supervision task kinds (wake triage, wake digest, turn-report check, log digest and others), each with the data class of its input and the minimum power it needs. A task kind runs in one of four modes per member: `off`, `shadow` (the pool answers, nothing uses the answer, agreement is measured), `assist` (the answer is shown to the main model) or `auto` (the answer is acted on). Promotion is the developer's; demotion is automatic.
- **A saving dial.** One setting from 0 to 3 decides how much is offloaded. It can follow the main model's usage limit: the closer the limit, the more goes to the pool.
- **Privacy gate and budgets.** Nothing private goes to a provider whose terms allow training on it; secrets are masked before sending; billed models stay off unless a written monthly cap exists; the free quota is rationed per day and per task kind.
- **Control by prompt and by CLI.** `llm-pool` commands and a skill that maps plain requests to them (switch a model on or off, assign it to a task, change the dial, stop everything). Every change is audited with who, when and why.
- **Usage ledger.** Every pool call is recorded with where it ran, what it was for, which model answered, tokens, cost, outcome and the main-model tokens it is estimated to have avoided.
- **Desktop console.** A local app window that lists the pool with each model's state, description, power level, assignments, quota, tokens and cost, with a switch on each. A link opens a second window with the paginated history of where each model was used and what it did.
- **Supervision integration.** The watcher asks the pool before waking the supervisor for soft events; child reports and long outputs are digested by the pool before the main model reads them. Scope for now: the supervisor session and its child sessions, nothing else.
- **Extensions**, each behind its own switch: local models as private pool members, a what-if simulator, replay of a past request on another model, scorecards per model and task, quota forecasts and recommendations, headless pool workers for bounded micro-tasks.

## Capabilities

### New Capabilities

- `llm-pool-gateway`: how the module finds, checks and uses the OmniRoute gateway without touching global configuration.
- `llm-pool-registry`: the pool's members, their states and their attributes.
- `llm-pool-routing`: task kinds, modes, the saving dial, the privacy gate, budgets and the scope of callers.
- `llm-pool-control`: commands, control by prompt, the kill switch and the audit trail.
- `llm-pool-ledger`: the record of every pool call and the saving figures derived from it.
- `llm-pool-console`: the desktop console and its history window.
- `supervision-offload`: what the supervisor and its child sessions hand to the pool, and the safety rules of doing so.

### Modified Capabilities

None in `openspec/specs/`. `supervisor-wake-economy` (in `watcher-wake-backoff`) is extended in behaviour by `supervision-offload`, not modified.

## Impact

- New: `global/modules/llm-pool.yaml`, `global/scripts/llm-pool` with its library, `global/config/llm-pool.json`, a skill, a contract per hook if any, tests in a temporary home with a stub gateway, and the console's static files.
- Touched: the watcher (`global/scripts/lib/supervisor/watch.py`) gains an optional triage step that is off by default; the supervision skill's watcher reference describes it.
- External: OmniRoute, installed and connected by the developer. Provider accounts are his; the module never creates one and never sees a provider key.
- No change to which model any session runs on. The pool works beside the main model.

## What only the developer can do

- Sign up with providers and connect them in OmniRoute's own dashboard.
- Approve any billed model and its monthly cap.
- Promote a task kind from `shadow` to `assist` or `auto`.
- Enable a project for the pool.

## Non-goals

- Running supervisor or implementer sessions entirely on pool models.
- Using the pool outside the supervisor session and its child sessions.
- Replacing OmniRoute's dashboard: providers, keys and combos are managed there.
- Any model call that writes to a repository, decides a merge or a deploy, or answers the developer.
