# GAPS — omniroute-llm-pool

> **Date:** 2026-11-27 · **Mode:** A (existing change folder) · `main` @ `95991f4`
> **Real status:** gaps verified → hydrated in `proposal.md`, `design.md`, `tasks.md` and the seven spec deltas, in three rounds; **2 gaps are left pending on purpose** (G-83, G-84). No product code was written.
> **Second round:** a fresh reviewer read the hydrated documents (commit `56e46c6`) and found 16 more gaps, section E; they are hydrated too. Rows of that section cite the first hydration as `hyd:<file>`; `git show 56e46c6:openspec/changes/omniroute-llm-pool/<file>` reproduces them.
> **Third round:** a second fresh reviewer read the diff of the second round (commit `d55ab4d`, cited as `hyd2:<file>`) and found defects in what that round had written, section F. They were corrected by narrowing or by choosing one of two conflicting statements, with no new mechanism; the two that needed one are left pending. **This third correction was not read by a fresh reviewer**: the loop's five iterations were spent.
> **Reviewed draft:** the change as first committed (`13b2264`). Rows about the documents themselves cite that draft as `draft:<file>:<line>`; `git show 13b2264:openspec/changes/omniroute-llm-pool/<file>` reproduces them.

Paths are relative to the repository. `sup/` stands for `global/scripts/lib/supervisor/`, `skill/` for `global/skills/supervisa-sesiones/reference/`.

## Methodology — 5-iteration loop

| Iter | Focus | How | Outcome |
|------|-------|-----|---------|
| 1 | Primary code paths: the watcher the triage plugs into | One read-only reviewer over `sup/watch.py`, `cloud.py`, `machine_queue.py`, `lock.py`, `unattended.py`, the skill's references | 15 candidates; 9 FACT after re-check |
| 2 | Adjacent integrations: modules, installer, config merge, validator, tests, CI | One read-only reviewer over `scripts/toolkit/`, `scripts/validate-toolkit.py`, `global/modules/`, `examples/override-full/` | 15 candidates; 13 FACT, 3 "no gap" |
| 3 | Operations, security, economics, internal consistency | One adversarial reviewer over the eleven files of the draft | 25 candidates; 16 FACT, 1 already covered |
| 4 | Cross-verify: every citation re-opened on the merged tree by the orchestrator; then a fresh reviewer over the hydrated documents | `grep -n` / `sed -n` on each cited line; reviewer given the files, not the findings | Citations: 5 line numbers corrected, 2 downgraded to INFERENCE. Reviewer: 16 gaps in the hydration itself (section E), two of them High; all hydrated in a second round |
| 5 | Re-check of the second round | A second fresh reviewer over the diff of the second round; a script that matches every requirement title against the tasks | 15 more rows (section F): 11 hydrated in a third, bounded correction, 2 left pending, 2 rejected. Stop: the cap of five iterations is reached |

The 55 raw candidates of iterations 1 to 3 overlap; they consolidate into rows G-01 to G-65 (some candidates were split, several merged). Iteration 4 added G-66 to G-82 and iteration 5 added G-83 to G-97.

**Why the loop did not come back empty, stated:** most findings of iterations 4 and 5 were in text the previous correction had just written. Each correction that added a mechanism added surface for the next review. The third correction therefore added none.

## Consolidated matrix

Legend: **FACT** (pending) | **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN**

Requirement names: **GW** gateway, **RG** registry, **RT** routing, **CT** control, **LG** ledger, **CS** console, **SO** supervision-offload; **D** a design decision; **T** a task.

### A. The watcher and the supervision side

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-01 | High | The watcher cannot "keep waiting": it prints the first batch and exits, and every edge event is a difference against one snapshot taken at start, so a slept event would repeat on every poll or, with a refreshed snapshot, be lost | `sup/watch.py:284`, `:346-362`, `:398-400` | HYDRATED | SO "A sleep is recorded on disk and refreshes the watcher's baseline"; D8 |
| G-02 | High | Repeated notices record "already announced" when the line is generated, before any decision; a slept notice would not come back for hours | `sup/watch.py:132-133`; `sup/cloud.py:328`; `sup/machine_queue.py:81` | HYDRATED | SO "Guard mode and repeated notices are never triaged"; D8 (out of version 1) |
| G-03 | High | "The nearest deadline of the work in flight" has no machine-readable source: it is a free-text column the supervisor writes, and the supervisor applies it by choosing `--timeout` | `skill/registro-y-cierre.md:60-61`; `skill/vigilancia.md:57-58` | HYDRATED | SO "The deadline is an argument, and nothing is triaged while something waits"; T 5.3 |
| G-04 | Med | A wake can come from elsewhere (the developer, a hook) while a watcher still holds slept events in memory; "time since the supervisor's last wake" had no source | `sup/hook.py:17-28` (any matching process counts as the armed watcher) | HYDRATED | SO "A wake after sleeps says what was slept"; D8 (journal holds the stretch) |
| G-05 | Med | Some things fall due by time alone (an unattended item after 45 min, the periodic report after 30 min) and a 2-hour sleep overlaps them | `sup/unattended.py:9`; `sup/guard_report.py:13` (thresholds; the overlap is INFERENCE) | HYDRATED | SO "A sleep is bounded"; SO "The deadline is an argument…" |
| G-06 | High | Event lines carry text that is not internal: job labels and other projects' names, a fragment of a session's last message, the first open task, session titles | `sup/machine_queue.py:66-76`; `sup/watch.py:195-202`, `:314`; `sup/cloud.py:212` | HYDRATED | SO "The triage brief is built from structured fields only"; RT "Internal payloads are built by the module"; D5 |
| G-07 | Med | The brief included the register's last lines, which are free text, and design and spec disagreed on it | `skill/registro-y-cierre.md:72`, `:82`; `draft:specs/supervision-offload/spec.md:32` against `draft:design.md:113` | HYDRATED | SO brief requirement; `wake-digest` removed (D5) |
| G-08 | Med | First and repeated `ALLIDLE` lines are identical, and `ALLIDLE` is the signal that a project has stalled | `sup/watch.py:134`; `skill/vigilancia.md:97` | HYDRATED | same as G-02 |
| G-09 | Med | "Live supervisor" and "calling session" were undefined; `--owner` is a plain argument | `sup/lock.py:14`, `:59`; `sup/census.py:201-207` | HYDRATED | RT "Only the supervisor and its child sessions may call"; RT "The caller check is scope, not security"; D16 |
| G-11 | Med | "The supervision exclusion list" means "never deployed without the developer" in the code and has no matcher | `sup/settings.py:122` | HYDRATED | RT "Only enabled, unpaused projects use the pool"; D9 |
| G-12 | Med | Every supervision component skips a paused project; the pool's eligibility did not | `sup/watch.py:67-70`; `sup/hook.py:96`; `sup/guard_report.py:36` | HYDRATED | RT "Only enabled, unpaused projects use the pool" |
| G-13 | Med | "Soft" and "hard" did not map onto the watcher's vocabulary: `STATUS` is any change of status, guard mode filters events, and a mixed batch had no rule | `sup/watch.py:79-80`, `:355-356`, `:396-397` | HYDRATED | SO "Only two shapes of event are soft" |
| G-14 | Med | "By the end of that tick" and "only re-armed the watcher" have no detector in the code | — (INFERENCE: no such boundary exists in `sup/`) | HYDRATED | SO "The supervisor judges the sleeps with an explicit command" |
| G-15 | Low | The skill already doubles `--timeout` up to 2 h; a new step and new code need an entry in the skill's change log and in its list of optional pieces | `skill/vigilancia.md:57-58`; `sup/cli.py:96`; `global/skills/supervisa-sesiones/SKILL.md:108-109` | HYDRATED | T 5.6 |
| G-30 | Low | Supervision chores: the skill's size limits, the environment prefixes the supervisor tests scrub | `sup/lint.py:74-75`; `scripts/toolkit/tests/pieces/test_supervisor_lock.py:27` | HYDRATED | T 2.9, T 5.6 |

### B. Module, installer and repository

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-10 | High | "Can only be narrowed in an override" cannot be enforced by configuration: the merge replaces a key whole and the checked loader has no subset test | `scripts/toolkit/config.py:23`; `global/scripts/lib/toolkit_config.py:48-53` | HYDRATED | RG "What an override may not loosen is fixed in the code" |
| G-16 | High | Commands had nowhere to write: the installed config piece is the installer's (an edit makes the next install refuse) and no piece writes the override | `scripts/toolkit/cli.py:71-78`; `draft:specs/llm-pool-registry/spec.md:21` against `draft:specs/llm-pool-control/spec.md:10` | HYDRATED | RG "Definitions, decisions and observed state are stored apart"; D4 |
| G-17 | Med | The installer cannot install a desktop launcher: it writes only under the Claude directory and the README promises it never touches the desktop | `scripts/toolkit/modules.py:26`; `scripts/toolkit/apply.py:111`; `README.md:55` | HYDRATED | CS "The launcher is installed by the piece, not by the installer"; T 4.6 |
| G-18 | High | The redactor cannot be built on the privacy checker: it is not installed, needs a YAML library and knows four secret shapes | `README.md:164`; `scripts/privacy-check.py:41`; `scripts/privacy-patterns.yaml:47-59` | HYDRATED | RT "Privacy gate before every send"; D9 |
| G-19 | Med | Shallow merge: an override that tunes one task kind or one member replaces the whole table | `scripts/toolkit/config.py:23`; `global/modules/routines.yaml:20` | HYDRATED | D4 (flat keys; catalog in code); RG "The shipped registry is empty" |
| G-20 | Med | "Commented example members" cannot exist in a JSON piece | `scripts/toolkit/config.py:14` | HYDRATED | RG "The shipped registry is empty"; T 2.1, T 2.9 |
| G-21 | Med | A manifest that cites a piece its closure does not install fails validation; neither direction was declared | `scripts/validate-toolkit.py:635`; `global/modules/supervision.yaml:38-42` | HYDRATED | SO "The pool is optional for supervision"; D1; T 2.1 |
| G-22 | Med | "Byte-identical settings after uninstall" cannot be promised: uninstall rewrites the file for every module | `scripts/toolkit/settings_merge.py:119` | HYDRATED | GW "Global Claude configuration is never modified" |
| G-23 | Med | Where the ledger, state, audit log and key file live, how tests redirect them and what uninstall does were unspecified | `README.md:37`; `sup/util.py:11`; `global/scripts/port-lease:41` (precedents) | HYDRATED | GW "State lives apart from the installed files"; GW "The gateway key stays in its file" |
| G-24 | Med | A new module breaks a test and leaves the full example, the README and `CLAUDE.md` behind | `scripts/toolkit/tests/test_installer.py:327-335`; `examples/override-full/override.yaml:4`; `examples/override-full/README.md:52` | HYDRATED | T 2.9 |
| G-25 | Low | Every script of the toolkit has a contract; the draft promised one "per hook if any" | `scripts/validate-toolkit.py:613`; `global/contracts/` (one file per script) | HYDRATED | T 2.1; RT "Every outcome has its own exit code" |
| G-26 | Med | Test fixtures with the shape of a secret would fail the repository's own privacy check in CI | `scripts/privacy-allow.yaml:5-11`; `.github/workflows/validate-toolkit.yml:27` | HYDRATED | T 2.7; D9 |
| G-27 | Med | No command reports the main model's usage: it is a function inside `account-switch`, of another module, and only for the command line's account | `global/scripts/account-switch:464`; `sup/providers.py:18-20` | HYDRATED | RT "The dial can follow the main model's usage"; D7 |
| G-28 | Low | The gateway's default port lies inside the range the port registry leases | `global/scripts/port-lease:42-43` (the collision itself is INFERENCE) | HYDRATED | GW "Doctor lists what the gateway sends elsewhere"; CS "The console server has a chosen port…" |
| G-29 | Low | "The installer prints the developer's steps" overstated what it does: it prints every module's notes and warns about a missing optional binary | `scripts/toolkit/cli.py:56`; `scripts/toolkit/deps.py:26-28` | HYDRATED | GW "The gateway is installed and connected by the developer" |

### C. The documents themselves: consistency, safety and economics

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-31 | High | The kill switch contradicted itself (requests in flight "finish or time out" but "within one second every `ask` exits") and a project's dial overrode the machine's | `draft:specs/llm-pool-control/spec.md:42` against `:46`; `draft:specs/llm-pool-routing/spec.md:49` | HYDRATED | CT "Kill switch"; CT "A stop reaches the requests in flight"; RT "The saving dial selects what is offloaded" |
| G-32 | High | A paid cap was checked against a cost recorded as zero when the gateway reports none, and after spending | `draft:specs/llm-pool-ledger/spec.md:10`; `draft:specs/llm-pool-routing/spec.md:92` | HYDRATED | RT "Billed members are off unless a cap and a price are written"; RT "The cost of a call is known and reserved before it is sent" |
| G-33 | High | "Only the developer may widen" lived in the skill; any session could run the command | `draft:specs/llm-pool-control/spec.md:28`; `draft:design.md:141`; precedent for a real check: `global/scripts/heavy-job:503-546` | HYDRATED | CT "Widening actions are checked by the command itself"; CT "A widening action is accepted only from the developer"; CT "Money and data classes are not commands" |
| G-34 | High | Prompt injection was not addressed in either direction | absent from the draft (searched "injection", "untrusted", "instruction") | HYDRATED | SO "The answer is a verdict in a fixed format"; SO "Digests are data the main model reads, never instructions"; RT "Modes per task kind and member"; D17 |
| G-35 | High | Unjudged sleeps counted as agreed, so a model that always says `sleep` could never be demoted | `draft:specs/supervision-offload/spec.md:64` | HYDRATED | LG "Rows are judged by an explicit act"; RT "Promotion needs evidence and the developer" |
| G-36 | High | Shadow rows were judged by a different rule from the one that defines a miss in `auto` | `draft:specs/supervision-offload/spec.md:71` against `draft:design.md:116` | HYDRATED | SO "Shadow triage changes nothing and is judged by the same question" |
| G-37 | High | The digest task kinds could never be promoted: shadow answers are returned to nobody | — (INFERENCE from `draft:specs/llm-pool-routing/spec.md:24`, `:35`) | HYDRATED | RT "Assist-only task kinds are promoted by review"; CS "Shadow answers can be reviewed" |
| G-38 | High | The "avoided tokens" estimate was inflated: the median included hard wakes, unjudged sleeps counted, a digest counted even if the original was read | — (INFERENCE from `draft:specs/llm-pool-ledger/spec.md:24`) | HYDRATED | LG "Avoided tokens are an estimate with a stated rule"; LG "Digests, shadow rows and fallbacks have their own rule" |
| G-39 | High | The headline leverage was in raw tokens and the weighting that decides the economics was measured last | `draft:design.md:25`; `draft:tasks.md:64` | HYDRATED | T 1.7; LG "Totals show spend, saving and leverage, raw and weighted"; D11 |
| G-40 | High | No criterion said when the pool has failed, and no baseline without a model was compared | absent from the draft | HYDRATED | SO "A simulator replays recorded wakes before any triage is built"; SO "The simulator compares today with a fixed rule"; SO "Nothing is built for a small saving, and a safe fixed rule wins"; SO "The triage is switched off when it does not pay"; D15 (rewritten by G-71) |
| G-41 | Med | `internal` allowed session titles; provider retention was read and never used | `draft:design.md:86`; `draft:specs/llm-pool-registry/spec.md:50` | HYDRATED | RG "Provider terms decide the data class"; D5 |
| G-42 | Med | Nothing checked which model answered; the gateway's compression was ignored; proposal and design disagreed on who owns combos | `draft:proposal.md:73` against `draft:design.md:52` | HYDRATED | GW "The answering model is checked"; GW "Doctor lists what the gateway sends elsewhere" |
| G-43 | Med | Gateway features that send data elsewhere were not all checked | `draft:specs/llm-pool-gateway/spec.md:42` | HYDRATED | GW "Doctor lists what the gateway sends elsewhere"; T 1.6 |
| G-44 | Med | Console security: how the token reaches the page, reads without a token, no host check, nobody stops the server | — (INFERENCE from `draft:specs/llm-pool-console/spec.md:64`) | HYDRATED | CS "Every request to the console is protected"; CS "The console server has a chosen port and a bounded life" |
| G-45 | Med | The exit-code list was incomplete and lumped a stop with an empty pool | `draft:specs/llm-pool-routing/spec.md:17` against `:28` | HYDRATED | RT "Every outcome has its own exit code" |
| G-46 | Med | `follow-usage` could raise the dial by itself, which the control spec reserved for the developer, and had no hysteresis | `draft:specs/llm-pool-routing/spec.md:60` against `draft:specs/llm-pool-control/spec.md:28` | HYDRATED | RT "The dial can follow the main model's usage" |
| G-47 | Med | `probation` was a member state in one place and a pair state in another | `draft:specs/llm-pool-registry/spec.md:28` against `draft:specs/llm-pool-routing/spec.md:42` | HYDRATED | RG "Member states"; RT "Demotion is automatic" |
| G-49 | Med | Values the specs depended on were never defined: the verdict format, thresholds for non-triage kinds, when a day and a month start, cooldown, shares, weights | absent from the draft | HYDRATED | D18 and the scenarios that now carry the numbers |
| G-50 | Med | Concurrent callers and killed processes: a budget check could be passed twice, and a killed request left no row | absent from the draft (searched "lock", "concurren", "race") | HYDRATED | LG "The row exists before the request leaves"; RG "Decision and state files survive concurrent commands" |
| G-51 | Med | Requirements with no task that both implements and verifies them (loopback URL and key file, known task kind, extended views, greyscale) | `draft:tasks.md` against the draft's 58 requirement titles | HYDRATED | `tasks.md` rewritten; coverage table in `VERIFY.md` |
| G-52 | Med | Tasks with no requirement behind them, and the request's "at what moment" served only by an extension | `draft:tasks.md:58-59`, `:74-75`; `draft:design.md:152` | HYDRATED | RT "Schedules decide when the pool is used"; RG "Local models can be members"; SO simulator requirements |
| G-54 | Low | Edge cases: a member removed while rows reference it; the mode of a new assignment; whether `off`→`shadow` widens; `local` missing from the design's billing list; a slow triage delaying a hard event | `draft:design.md:126` against `draft:specs/llm-pool-registry/spec.md:10` (the enum); the rest absent | HYDRATED | RG "Member states"; RT "Modes per task kind and member"; SO "The triage has a short time limit" |
| G-55 | Low | Scorecards could not be repeated (no temperature), and nobody deleted old payloads | absent from the draft | HYDRATED | LG "The payload is kept redacted and for a bounded time"; D11 |

### D. Not hydrated: already covered, rejected, inference or unknown

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-48 | Med | The proposal says "the supervisor and its child sessions"; the spec lets a session the developer opened in a supervised project use the digests | `draft:proposal.md:36` against `draft:specs/supervision-offload/spec.md:91-93` | INFERENCE | Kept, because the supervisor orders those sessions too; written as an open question for the developer in D16 |
| G-53 | Low | "The card lacks a short description of what tasks a model is for" | — | ALREADY | `draft:specs/llm-pool-console/spec.md:21` and `draft:specs/llm-pool-registry/spec.md:10` had it; the card now also gets one line per task kind |
| G-56 | — | A supervisor asleep for 2 h would look dead to the watchdog | — | REJECTED | The watcher itself beats every 60 s while it waits (`sup/watch.py:337-339`, `sup/cli.py:113`) and the lock's time-to-live is 30 min (`sup/lock.py:14`) |
| G-57 | — | The installer cannot ship a directory of static files or let a piece keep state | — | REJECTED | A directory entry is copied recursively (`scripts/toolkit/modules.py:55-59`); pieces create their state at run time |
| G-58 | — | The catalog's routing rules do not apply to a skill under `global/skills` | — | REJECTED | `scripts/validate-toolkit.py:457-461` runs the routing check and the `global-skill` collision rule there |
| G-59 | Med | How long the gateway keeps its own call log, and whether that can be bounded | — | UNKNOWN | T 1.6 records it; until then `private` goes only to members whose terms allow it, and the gateway's log stays on the same machine |
| G-60 | Low | On a machine with other local users, the console's address (with its token) is visible in the process list | — | INFERENCE | Stated as a limit in D12; single-user machine assumed |
| G-61 | High | Whether a fixed rule with no model can sleep the soft wakes safely and, if not, whether a pool model given the same brief can | — | UNKNOWN | The question stage 0 answers: T 6.1–6.3. Until then the triage tasks are not built |
| G-62 | Med | A wake after a long silence may cost more if the prompt cache expired meanwhile | — | INFERENCE | Stated as a limit of the estimate in D11; the field result (T 7.4) measures real usage |
| G-63 | Low | Clock changes move the windows "within 24 hours" and the schedule | — | INFERENCE | Not specified; wall-clock time is used and the effect is one window, once |
| G-64 | Low | The ledger file never shrinks | — | INFERENCE | Out of version 1; figures are purged after 400 days |
| G-65 | Med | How the main model's usage limit weighs cache reads | — | UNKNOWN | T 1.7, before anything is built; weighted figures read "not set" until then |

### E. Found in the hydrated documents by the fresh reviewer (iteration 4)

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-66 | Med | `census-summary` was in the catalog and nothing would ever call it | `hyd:design.md` D5 table; no task and no SO requirement named it | HYDRATED | Removed. RT "The catalog of version 1 has five task kinds"; D5 |
| G-67 | Med | `stop` was said to leave `follow-usage`, and `resume` to restore the previous dial: two rules for one flag | `hyd:design.md` D7 against `hyd:specs/llm-pool-control/spec.md` "Kill switch" | HYDRATED | CT "Kill switch" (scenario "Stop and resume"); D7 |
| G-68 | High | In `shadow` the verdict went to the ledger only, so the judging step, which reads the journal, never showed it to the supervisor: shadow rows could not be judged and no pair could reach 50 judged samples | `hyd:specs/supervision-offload/spec.md` "Shadow triage…" against "The supervisor judges the sleeps…" | HYDRATED | SO "Shadow triage changes nothing and is judged by the same question"; D8; T 5.5 |
| G-69 | Med | Nothing said which member answers when several are eligible, and "quota close to expiry first" relied on data the gateway may not give | `hyd:design.md` D10 | HYDRATED | RT "The member is chosen by a fixed order"; D10 |
| G-70 | Med | After a change of the gateway pin, `auto` pairs stayed trusted on a scorecard earned with another version | `hyd:design.md` D3 ("re-checked afterwards", no rule) | HYDRATED | GW "One pinned gateway version" (scenario "The pin is updated"); D3 |
| G-71 | High | The go/no-go could not be passed as written: it asked the pool to save 1.25 times what the fixed rule saves, and a model can only sleep a part of what the rule sleeps | `hyd:design.md` D15; `hyd:specs/supervision-offload/spec.md` "Triage is built only if the pool beats the fixed rule" | HYDRATED | SO "Nothing is built for a small saving, and a safe fixed rule wins"; SO "Triage is built only if a model is safer than the fixed rule"; D15; T 6.1, 6.3 |
| G-72 | High | The judging vocabulary did not hold together: "agreed" and "missed" were answers and labels at once, "agreement" had no formula, and a model that always wakes scored as perfect | `hyd:specs/llm-pool-ledger/spec.md` "Rows are judged…", "Scorecards per pair" | HYDRATED | LG "Rows are judged by an explicit act"; LG "Scorecards per pair" (scenario "A model that always wakes"); D8 |
| G-73 | Med | No command carried the supervisor's answers from the journal to the pool's ledger | `hyd:design.md` D8 ("records the answers with one command", unnamed) | HYDRATED | SO "The supervisor judges the sleeps with an explicit command"; T 5.3 |
| G-74 | Med | A member that does not accept the data class had two outcomes, `refused by gate` and `no eligible member` | `hyd:specs/llm-pool-routing/spec.md` "Privacy gate before every send" | HYDRATED | RT "Privacy gate before every send"; D9 |
| G-75 | Med | The outcome list had no name for success and none for a key file or URL the module refuses to use | `hyd:specs/llm-pool-routing/spec.md` "Every outcome has its own exit code" | HYDRATED | RT "The outcomes are a fixed list" |
| G-76 | Med | Three things the design used had no command or field: the dial of one project, the class of `assign` (widening or not), a member's daily budget | `hyd:design.md` D7, D10, D13 | HYDRATED | CT "One command line for every control action"; CT "Narrowing is always allowed"; RG "Each member has a described identity"; RT "The free quota is rationed" |
| G-77 | Med | The `--order` check looked only at whether the developer was present, not at whether he wrote that order | `sup/human_turns.py:126` (returns his text when asked) | HYDRATED | CT "A widening action is accepted only from the developer" (scenario "The developer wrote about something else"); D13 |
| G-78 | Low | Left to the implementer: the thresholds of `follow-usage`, the list of reason codes, the fixed instruction and temperature of a request | `hyd:design.md` D7, D8, D11 | HYDRATED | RT "Usage thresholds have defaults and do not flap"; SO "The answer is a verdict in a fixed format"; RT "Requests are sent the same way every time"; D18 |
| G-79 | Low | Loose ends in the specs: a `retired` state with no transition; a scenario that cannot be tested because the watcher never watches its owner's session; extensions with no named switch; the opener's default | `sup/watch.py:144-145` | HYDRATED | RG "Member states"; RG "Local models can be members"; CS "A local app window with no external dependency"; CS "Extended views appear only when their extension is on" |
| G-80 | Low | Four citations of the hydrated design did not support their sentence, and the toolkit's checked loader cannot validate a list of members | `scripts/toolkit/apply.py:46-64`, `:144-154`; `scripts/toolkit/modules.py:26`; `global/scripts/lib/toolkit_config.py:48-53`; `sup/census.py:201-207` | HYDRATED | D2, D4, D12, D16 corrected |
| G-81 | Low | Tasks cited a requirement title that does not exist, and no task read the members' quota and state from the gateway | `hyd:tasks.md` 1.6, group 3 | HYDRATED | T 1.6, T 3.12 (new) and the requirement lists of T 2.6, 3.1–3.11, 4.1–4.7, 5.3–5.7 |
| G-82 | Med | The simulator reads "needed" from what the supervisor did: a wake where it should have acted and did not counts as not needed | — | INFERENCE | Stated as a limit of the method in D15; unclassifiable wakes are listed, not guessed |

### F. Found in the second round's corrections by the second fresh reviewer (iteration 5)

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-83 | High | When the fixed rule turns out unsafe, nothing says how a candidate member is tested: stage 0 has no pool code, the brief builder was gated on the "go" it is needed for, and three of the brief's bounds are not in the history | `hyd2:tasks.md` 5.4 ("only if 6.3 is go"), 6.1; `hyd2:design.md` D15 case 3 | **FACT** | Pending: `/mejora-tarea` once the simulator's report exists (replay on rebuilt briefs, or rule and model side by side in `shadow`). Until then D15 row 4 keeps the decision open and nothing is built |
| G-84 | Med | Three task kinds have no caller: nothing says which session asks for `turn-report-check`, `closing-evidence-summary` and `dialog-draft`, nor at which step | `hyd2:tasks.md` 5.6, 5.7 | **FACT** | Pending: `/mejora-tarea` if the developer wants the pool for digests. T 5.7 covers `log-digest` only until then |
| G-85 | High | The task proposed the fixed rule after every no-go, also when the rule is unsafe; and a rule both safe and too small had two decisions | `hyd2:tasks.md` 6.3 against `hyd2:specs/supervision-offload/spec.md` "…neither is built" | HYDRATED | D15 as one ordered table, first row wins; SO "Nothing is built for a small saving, and a safe fixed rule wins" (scenario "Safe and too small"); T 6.3 |
| G-86 | High | The simulator could not tell which past timeouts were soft, nor rebuild three of the five bounds for past wakes | `hyd2:design.md` D8 bound 1 ("without it a `TIMEOUT` is hard"); no recorded wake has a `--wake-by` | HYDRATED | SO "The simulator compares today with a fixed rule" (soft by the watcher's output; figures labelled upper bounds); D15; T 6.1 |
| G-87 | Med | The decision's terms were loose: "one in 100" of what, no minimum sample, an open list for "needed", no place for a wake that cannot be classified, an "open" result no task handled | `hyd2:design.md` D15; `hyd2:tasks.md` Order | HYDRATED | SO "A simulator replays recorded wakes before any triage is built"; D15 table row 1; D18; tasks, Order |
| G-88 | Med | A "go" could sit below the line at which the triage is later removed, and the removal rule could not be computed without cache weights | `hyd2:design.md` D15 (half of 5 % against 3 %) | HYDRATED | SO "Triage is built only if a model is safer than the fixed rule" (no less than 3 %); SO "The triage is switched off when it does not pay" (raw fallback) |
| G-89 | High | Scorecards never started again: after probation a pair could either never be promoted or be promoted at once on samples earned before | `hyd2:specs/llm-pool-ledger/spec.md` "Scorecards per pair" ("from judged rows only") | HYDRATED | LG "Scorecards per pair" (since the pair last entered `shadow` or `probation`); D6; T 3.6 |
| G-90 | Med | A digest reviewed as not acceptable was counted as a false sleep; the review view could judge triage rows | `hyd2:specs/llm-pool-ledger/spec.md`, `hyd2:specs/llm-pool-console/spec.md` "Shadow answers can be reviewed" | HYDRATED | LG "Scorecards per pair", "Totals show spend, saving and leverage"; CS "Shadow answers can be reviewed", "The header shows the whole picture"; D11 |
| G-91 | Low | Judging a part of the journal: whether the stretch closes was not said; a `wake` verdict in `auto` is never judged | `hyd2:specs/supervision-offload/spec.md` "The supervisor judges the sleeps…" | HYDRATED | Same requirement (the stretch closes when no entry is left unjudged); D8 |
| G-92 | Med | Four statements with two versions: stale terms (refused assignment or `public` only); the reasons for `blocked`; a member blocked for a wrong model that doctor never probed again; no outcome for a task kind above a level in force that is not 0 | `hyd2:specs/llm-pool-console/spec.md` scenario "Switching on a member with stale terms"; `hyd2:design.md` D4; `hyd2:specs/llm-pool-gateway/spec.md` "Doctor reports the whole chain" | HYDRATED | CS same scenario; D4; GW "Doctor reports the whole chain"; RT "The outcomes are a fixed list"; LG "The row exists before the request leaves" (`pending` and `lost` are states) |
| G-93 | Low | The ids an extension is named by were not listed; `follow-usage` for one project was allowed by the command and defined nowhere | `hyd2:specs/llm-pool-control/spec.md` "One command line…" | HYDRATED | D14 (ids); CT "One command line for every control action" (`dial follow-usage` is the machine's); D7 |
| G-94 | Low | Three statements about the code went further than the code: the order check assumed all of the developer's text is returned and only his newest message is; uninstall removes the whole toolkit, not one module; the strings-only rule is three lines above the range cited | `sup/human_turns.py:126-129`; `scripts/toolkit/apply.py:103-104`; `global/scripts/lib/toolkit_config.py:43-44` | HYDRATED | CT "A widening action is accepted only from the developer"; D13, D2, D4 |
| G-95 | Low | Two requirements were cited by no task by name, and five citations were clipped | `hyd2:tasks.md` 1.7, 2.1, 2.4, 3.2, 4.3, 5.2 | HYDRATED | Tasks corrected; VERIFY's table is generated by a script that fails on a title or a task id that does not exist |
| G-96 | Low | "Five bounds" in the design against four in SO "A sleep is bounded" | — | REJECTED | Not a contradiction: the fifth bound is its own requirement, SO "The deadline is an argument, and nothing is triaged while something waits" |
| G-97 | Low | `scripts/toolkit/apply.py:46-64` does not show the refusal to reinstall | — | REJECTED | The same row of the Context table cites `scripts/toolkit/cli.py:71-78` for the refusal; `apply.py` is cited for where the installer writes |

## Useful casuistics

- **A slept session finishes its turn.** After a sleep the snapshot says "busy", so the later change to idle is a new event and wakes at once. With the draft's unrefreshed snapshot it would have shown no difference.
- **A batch with one soft and one hard line** wakes: triage never sees it.
- **Developer writes during a stretch of sleeps.** The judging step reads the journal whatever woke the supervisor.
- **The model always says `sleep`.** It cannot be promoted: ten of the judged samples must be cases where the supervisor was needed.
- **The gateway falls back to another model.** The answer is discarded and the member blocked.
- **A paid model with no reported cost.** The price in the definitions gives the cost; without a price the member is blocked.
- **`stop` while a project has its own dial.** The stop flag is checked first and the machine's wins. After `resume` the dial is what it was.
- **The model always says `wake`.** It never misses and it saves nothing: its wakes when the supervisor was not needed are `overwake` and pull its agreement down.
- **The fixed rule turns out safe.** Then no model is used for triage and the rule becomes a change of its own.
- **The rule is safe and saves almost nothing.** The first row that applies wins: too small, and nothing is proposed.
- **A pair comes back from probation.** Its scorecard starts empty; old samples do not promote it.
- **Forty soft wakes in the window.** Too few to decide: more days are recorded.
- **The developer wrote in the session about something else.** A widening command with an order he did not write is refused.
- **An override tries to add a crash to the soft list.** Ignored and reported; the list is a constant.

## Out of v1

- Triage of repeated notices (`ALLIDLE`, `QUEUED`, `SLOTHELD`): their state is consumed when generated and the back-off already rations them.
- `wake-digest`: its input was private register text and the watcher prints the slept list itself.
- `census-summary`: no caller.
- A fixed rule in the watcher with no model: it is the comparison of stage 0 and, if it wins, a change of its own.
- Headless pool workers: their own change, after the spike of T 8.3.
- Multi-user machines, SQLite compaction, clock-change handling.

## Pending count

| Class | Rows |
|-------|------|
| FACT pending hydrate (`/mejora-tarea`) | 2 (G-83, G-84) |
| HYDRATED (spec OK; `/aplica-tarea` only) | 80 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 15 |

Both pending gaps are outside stage 0 (tasks 1.7 and 6.1 to 6.3) and inside what `VERIFY.md` marks as blocked. They are left pending on purpose: each needs a mechanism that is better designed with the simulator's report in hand than guessed now.

**Gaps pending (mejora + apply): 2**

## Verification (this document)

**Verified**
- Every `path:line` in sections A and B was opened on the tree at `95991f4` with `grep -n` or `sed -n` by the orchestrator after the reviewers reported. Five line numbers the reviewers gave had moved with the merge of `main` and were corrected; two claims whose line could not be found were downgraded to INFERENCE (G-05's overlap, G-28's collision).
- Every `draft:` citation was printed from `13b2264` with `git show`.
- `openspec validate omniroute-llm-pool --strict`: valid after each of the three rounds (now 97 requirements, 169 scenarios).
- Second round: each `path:line` the fresh reviewer gave was opened before it was used.
- Third round, mechanically: the eight combinations of the three inputs of the go/no-go (enough data, saving worth it, rule safe) each fall on exactly one row of D15's table; every phrase the second reviewer quoted as wrong was searched for and is gone; the three code claims of that reviewer were opened (`sup/human_turns.py:126-129`, `scripts/toolkit/apply.py:103-104`, `global/scripts/lib/toolkit_config.py:43-44`); a script checks that each of the 97 requirements has a scenario and a task, and that every task id cited exists.
- The privacy check over the tree: 0 findings.

**Not verified**
- **The third correction was not read by a fresh reviewer.** Both earlier corrections had defects that only a fresh reader found; this one may too. It was kept small for that reason.
- Whether the closed list that defines "needed" matches what a supervisor really does in a tick. Task 6.1 tests it on real transcripts and lists what it cannot classify.
- Nothing was run against a real gateway: none is installed for this change. Every statement about OmniRoute comes from its README.
- The figures of the measurement (wakes, tokens) are those of the earlier measurement; they were not re-taken.
- Whether the hydrated design is implementable in the watcher as written is INFERENCE until T 5.3 has tests.
