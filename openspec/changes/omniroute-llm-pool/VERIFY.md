# VERIFY — omniroute-llm-pool

> **Date:** 2026-11-27 · `main` @ `95991f4` · written by `/prepara-tarea` after the gap review (`GAPS.md`), and brought up to date after its second and third rounds.
> Nothing of this change is implemented. VERIFY checks the documents against each other, against the request and against the code they will touch.

## Gates

| Gate | Command / check | Result |
|------|-----------------|--------|
| Artefacts present | `ls openspec/changes/omniroute-llm-pool/` | `proposal.md`, `design.md`, `tasks.md`, seven `specs/*/spec.md`, `GAPS.md`, `VERIFY.md`, `READY-TO-APPLY.md` |
| `openspec validate omniroute-llm-pool --strict` | OpenSpec CLI 2.1.1 | `Change 'omniroute-llm-pool' is valid` |
| Spec inventory | `grep -c '^### Requirement'` / `'^#### Scenario'` | 97 requirements / 169 scenarios in 7 specs; every requirement has at least one scenario |
| Tasks | `grep -c '^- \[ \]' tasks.md` | 58, none done; 3 are the developer's (1.2, 7.1, 7.3) |
| Gap review | `GAPS.md` | 97 rows: 80 hydrated, 15 non-blocking, **2 pending** (G-83, G-84), both outside stage 0. Three rounds: the first two corrections were each read by a fresh reviewer; the third was checked mechanically only |
| Request → requirement | table below | every element of the request has at least one requirement |
| Requirement → task | table below, checked by a script against the spec titles and the task ids | 97 / 97 |
| Code citations | each `path:line` of `design.md` and `GAPS.md` opened on `95991f4` | match |
| Go/no-go is decidable | the eight combinations of its three inputs against the table of design D15 | each falls on exactly one row |
| Product files untouched | `git diff --stat origin/main -- . ':!openspec'` | empty |
| Privacy | `scripts/privacy-check.py` on the tree and on the staged files | 0 findings |

## Request → requirement

| What was asked | Where it is specified |
|---|---|
| Have OmniRoute | GW, all ten requirements; installed and connected by the developer (task 1.2) |
| Switch models on and off by prompt | CT "Control by prompt goes through the same commands"; CT "One command line for every control action" |
| …or from a desktop app that lists them | CS "A local app window with no external dependency"; CS "The pool view lists every member"; CS "Switches act at once and through the same rules as the commands"; CS "The launcher is installed by the piece, not by the installer" |
| Their state | RG "Member states"; CS "The pool view lists every member" (state, since when, why, how it returns) |
| A short description of the kind of task each can be assigned to | RG "Each member has a described identity" (160 characters); CS "The pool view lists every member" (description, and one line per task kind) |
| Their power level | RG "Each member has a described identity" (1 to 5); RG "A member only takes a task kind it is fit for"; CS pool view |
| Small statistics of token use and possible cost | CS "Each card shows usage and cost"; CS "The header shows the whole picture"; LG "Totals show spend, saving and leverage, raw and weighted" |
| A link to a history, in another window, paginated, of where it was used and what it did | CS "A link opens the history in a second window"; LG "History is paginated and filterable"; LG "The payload is kept redacted and for a bounded time" |
| Extend the setup creatively | RT "Schedules decide when the pool is used"; RT "The dial can follow the main model's usage"; RT "The member is chosen by a fixed order"; SO simulator; CS "Shadow answers can be reviewed"; RG "Local models can be members"; CT "Explain a routing decision"; design D14 |
| Only the supervisor session and its child sessions | RT "Only the supervisor and its child sessions may call"; SO "Scope is the supervisor and its child sessions" (open question in design D16 about sessions the developer opens himself) |
| Tight control of which models are active | CT commands and "Kill switch"; RG "Definitions, decisions and observed state are stored apart"; RT budgets; CT "Every change is audited" |
| …what each is used for | RT "Work is offloaded only as a known task kind"; RT "Modes per task kind and member"; RG "A member only takes a task kind it is fit for" |
| …at what moment, in which situations or tasks | RT "Schedules decide when the pool is used"; RT "The saving dial selects what is offloaded"; SO "Only two shapes of event are soft"; SO "A sleep is bounded" |
| The goal is to spend fewer tokens | SO "A simulator replays recorded wakes before any triage is built"; SO "The simulator compares today with a fixed rule"; SO "Nothing is built for a small saving, and a safe fixed rule wins"; SO "Triage is built only if a model is safer than the fixed rule"; SO "The triage is switched off when it does not pay"; LG avoided-token and totals requirements; SO "The report carries the saving" |

## Requirement → task

| Spec | Requirement | Task |
|---|---|---|
| GW | The gateway is reached on loopback from configuration | 3.1 |
| GW | The gateway key stays in its file | 3.1, 3.9 |
| GW | Global Claude configuration is never modified | 2.8 |
| GW | One pinned gateway version | 3.9 |
| GW | The answering model is checked | 3.4 |
| GW | The module works without the gateway | 3.1 |
| GW | Doctor reports the whole chain | 3.9 |
| GW | Doctor lists what the gateway sends elsewhere | 3.9 (inputs from 1.6) |
| GW | The gateway is installed and connected by the developer | 2.1, 2.8 (and 1.2, his) |
| GW | State lives apart from the installed files | 2.2 |
| RG | Each member has a described identity | 2.3 |
| RG | Definitions, decisions and observed state are stored apart | 2.3, 3.12 |
| RG | Decision and state files survive concurrent commands | 2.2 |
| RG | What an override may not loosen is fixed in the code | 2.3, 3.9 |
| RG | Member states | 2.3, 3.12 |
| RG | A member only takes a task kind it is fit for | 2.6, 3.2 |
| RG | Provider terms decide the data class | 2.3 (data from 1.4) |
| RG | The shipped registry is empty | 2.1, 2.9 |
| RG | Local models can be members | 8.4 |
| RT | Work is offloaded only as a known task kind | 3.1 |
| RT | The catalog of version 1 has five task kinds | 3.1 |
| RT | One entry point with a fallback contract | 3.1 |
| RT | Every outcome has its own exit code | 3.1 |
| RT | The outcomes are a fixed list | 3.1 |
| RT | Modes per task kind and member | 3.2, 3.11 |
| RT | Promotion needs evidence and the developer | 3.6 |
| RT | Assist-only task kinds are promoted by review | 3.6, 4.4 |
| RT | Demotion is automatic | 3.6 |
| RT | The saving dial selects what is offloaded | 3.2 |
| RT | Schedules decide when the pool is used | 3.8 |
| RT | The dial can follow the main model's usage | 3.8 |
| RT | Usage thresholds have defaults and do not flap | 3.8 |
| RT | Privacy gate before every send | 3.3 (class mismatch in 3.2) |
| RT | The member is chosen by a fixed order | 3.2 |
| RT | Requests are sent the same way every time | 3.11 |
| RT | Internal payloads are built by the module | 3.3 |
| RT | Only enabled, unpaused projects use the pool | 3.2 |
| RT | Only the supervisor and its child sessions may call | 3.2 |
| RT | The caller check is scope, not security | 3.2, 2.1 (notes) |
| RT | Billed members are off unless a cap and a price are written | 3.5 |
| RT | The cost of a call is known and reserved before it is sent | 3.5 |
| RT | The free quota is rationed | 3.5 |
| CT | One command line for every control action | 2.6 |
| CT | Commands for evidence and upkeep, all machine-readable | 2.6 |
| CT | Control by prompt goes through the same commands | 4.5 |
| CT | Widening actions are checked by the command itself | 2.6 |
| CT | A widening action is accepted only from the developer | 2.6 |
| CT | Money and data classes are not commands | 2.6 |
| CT | Narrowing is always allowed | 2.6 |
| CT | Kill switch | 2.6 |
| CT | A stop reaches the requests in flight | 3.1 |
| CT | Every change is audited | 2.5 |
| CT | Explain a routing decision | 3.7 |
| LG | One row per request | 2.4 |
| LG | The row exists before the request leaves | 2.4 |
| LG | The payload is kept redacted and for a bounded time | 2.4 |
| LG | Avoided tokens are an estimate with a stated rule | 3.10 (reader from 6.1) |
| LG | Digests, shadow rows and fallbacks have their own rule | 3.10 |
| LG | Rows are judged by an explicit act | 3.10 |
| LG | Scorecards per pair | 3.6 |
| LG | Totals show spend, saving and leverage, raw and weighted | 3.10 (weights from 1.7) |
| LG | Usage is reconciled with the gateway | 3.9 (only if 1.3 finds the call) |
| LG | History is paginated and filterable | 2.4 |
| CS | A local app window with no external dependency | 4.1 |
| CS | The console server has a chosen port and a bounded life | 4.1 |
| CS | The launcher is installed by the piece, not by the installer | 4.6 |
| CS | The pool view lists every member | 4.2 |
| CS | Each card shows usage and cost | 4.2 |
| CS | The header shows the whole picture | 4.2 |
| CS | Switches act at once and through the same rules as the commands | 4.2 |
| CS | A link opens the history in a second window | 4.3 |
| CS | Shadow answers can be reviewed | 4.4 |
| CS | The console never shows a secret | 4.3 |
| CS | Every request to the console is protected | 4.1 |
| CS | Readable on a laptop screen and by keyboard | 4.2 |
| CS | Extended views appear only when their extension is on | 4.7, 8.1 |
| SO | The pool is optional for supervision | 5.1 |
| SO | A simulator replays recorded wakes before any triage is built | 6.1 |
| SO | The simulator compares today with a fixed rule | 6.1, 6.2 |
| SO | Nothing is built for a small saving, and a safe fixed rule wins | 6.3 |
| SO | Triage is built only if a model is safer than the fixed rule | 6.3 (third case needs 1.2) |
| SO | Only two shapes of event are soft | 5.2 |
| SO | Guard mode and repeated notices are never triaged | 5.2 |
| SO | The triage brief is built from structured fields only | 5.4 |
| SO | The answer is a verdict in a fixed format | 5.4 |
| SO | The triage has a short time limit | 5.4 |
| SO | A sleep is recorded on disk and refreshes the watcher's baseline | 5.3 |
| SO | A sleep is bounded | 5.3 |
| SO | The deadline is an argument, and nothing is triaged while something waits | 5.3, 5.6 |
| SO | A wake after sleeps says what was slept | 5.3 |
| SO | The supervisor judges the sleeps with an explicit command | 5.3, 5.6 |
| SO | Shadow triage changes nothing and is judged by the same question | 5.5, 5.6 |
| SO | Digests are data the main model reads, never instructions | 5.7 |
| SO | A digest says what it left out, and the original stays the authority | 5.7 |
| SO | Scope is the supervisor and its child sessions | 3.2, 5.7 |
| SO | The report carries the saving | 5.6, 3.10 |
| SO | The triage is switched off when it does not pay | 7.4 |

Tasks with no requirement of their own, on purpose: the spike (1.1, 1.3–1.6, 8.3), which produces evidence; repository chores (2.7, 2.9, 9.x); and the extension views of 8.1, 8.2 and 8.5, which are described in design D14 and get requirements when one of them is taken up.

## Evidence map

| Claim | Class | Evidence |
|-------|-------|----------|
| A supervisor wake costs 0.4–3 M raw tokens, typically 1 M, over 97 % cache reads | FACT, not reproducible from the repository | Measured from three supervisors' transcripts for this change |
| Soft wakes were 24 % of three supervisors' flow, at 3.6 an hour | FACT, small sample (11 wakes, 3 hours) | Same measurement |
| OmniRoute's features as listed in the design's Context table | FACT about its README, release line 3.8 | Read, not run: no gateway was installed for this change |
| The watcher exits on the first batch and compares against one snapshot | FACT | `global/scripts/lib/supervisor/watch.py:284`, `:346-362`, `:398-400` |
| Repeated notices consume their state when generated | FACT | `watch.py:132-133`; `global/scripts/lib/supervisor/cloud.py:328` |
| Config merge is shallow; the installer writes only under the Claude directory | FACT | `scripts/toolkit/config.py:23`; `scripts/toolkit/modules.py:26` |
| The developer's presence can be checked by a command | FACT | `global/scripts/heavy-job:503-546` does it today |
| The hydrated sleep mechanism (journal, refreshed snapshot, five bounds) can be built into the watcher as specified | INFERENCE | No code yet; task 5.3 proves it with tests |
| A fixed rule with no model sleeps the soft wakes safely | UNKNOWN | Tasks 6.1–6.3 |
| If it does not, a pool model reading the same fields does | UNKNOWN, and how to test it is not specified yet | GAPS G-83, pending |
| The closed list that defines when the supervisor was "needed" matches what supervisors do | INFERENCE | Task 6.1 on real transcripts; unclassified wakes are listed |
| The developer's words can be read by a command, to check an order against them | FACT | `global/scripts/lib/supervisor/human_turns.py:126` |
| The usage limit weighs a cache-read token at a fraction of a fresh one | UNKNOWN | Task 1.7 |
| The gateway's calls for quota, usage, combos; whether compression and telemetry can be switched off per key | UNKNOWN | Tasks 1.3 and 1.6, after the developer installs it (1.2) |
| Small free models triage well enough | HYPOTHESIS | Task 7.1 (shadow) |
| The thresholds of design D15 (100 classified soft wakes; a saving of 5 %; one needed wake in 100; half of the rule's saving and no less than 3 %; after rollout: leverage 10, one miss per 100 honoured sleeps, 3 %) | Provisional defaults, not evidence | The developer confirms or changes them at task 6.3 |

## Honest limits

- **The central idea is not proven.** The gap review showed that a safe triage brief is a handful of numbers, which a fixed rule can read as well as a model. A model cannot save more than a rule that sleeps every soft wake; it can only be safer. Whether that safety is needed is the first thing the tasks find out, and the answer may be that the rule is enough and no model is used for triage.
- **Both corrections had defects of their own.** The first hydration's go/no-go could never be passed, and its shadow verdicts were never shown to the supervisor (GAPS, section E). The second correction's go/no-go was still not decidable, its simulator could not rebuild what it needed from history, and its scorecards never started again after a demotion (section F). Each was found by a fresh reviewer and corrected. **The third correction was not read by one**; it was kept to narrowing and choosing, and checked mechanically. An apply should expect to find more.
- **Two gaps are left pending on purpose** (G-83: how a model is tested if the fixed rule is unsafe; G-84: who calls three of the digest task kinds). Neither touches stage 0. Both are better specified with the simulator's report in hand.
- The simulator decides "needed" from what the supervisor did in a tick. A wake where it should have acted and did not counts as not needed.
- The fixed rule's figures from the simulator are upper bounds, both its saving and its misses: three of the five bounds of a sleep cannot be rebuilt for past wakes. The decision uses each only where an upper bound is safe; in between, it stays open.
- Nothing was run against a gateway. Every requirement about OmniRoute's behaviour rests on its README until the spike.
- The measurement behind the figures is a 3-hour window on three supervisors.
- The digest task kinds need a provider that neither trains on prompts nor keeps them beyond 30 days, or a local model. Whether the developer has or wants one is his to say; without one those task kinds stay refused by the gate.
- `repasa-spec` as written ends by applying the change. That step was not run: nobody asked for implementation.
- `/verifica-tarea` checks an implemented change against its scenarios; there is nothing implemented to check.

## Verification status

**READY TO APPLY — stage 0 only. NEEDS HYDRATION for the rest** (2 gaps pending).

- **Ready now:** tasks 1.7, 6.1, 6.2 and 6.3 (the cache weights, the simulator, its report and the go/no-go). They need no gateway and no module. Task 6.3 records one of four results; two of them are "open" (too little data; or the rule is unsafe and a model must be tested).
- **Ready as soon as the developer has done 1.2** (install the gateway, connect a provider, place the key): the rest of the spike, 1.1 and 1.3 to 1.6.
- **BLOCKED BY UNKNOWN until 6.3 is recorded:** tasks 5.2 to 5.6 and group 7 (the watcher's triage and its rollout). **NEEDS HYDRATION besides:** if 6.3 records "a model must be tested", G-83 is hydrated before any of them is built.
- **NEEDS HYDRATION:** the digest task kinds other than `log-digest` (G-84), before task 5.7 covers them.
- **BLOCKED BY UNKNOWN until 1.3 and 1.6 are recorded:** the parts of groups 2 to 4 that talk to the gateway beyond its OpenAI-compatible endpoint (quota, usage, combos, outward features). The rest of groups 2 to 4 can be built against the stub, but it is only worth building if 6.3 says "go" or the developer wants the pool for digests alone.

An apply of this change must stop at task 6.3 and report.
