# GAPS — omniroute-llm-pool

> **Date:** 2026-11-27 · **Mode:** A (existing change folder) · `main` @ `95991f4`
> **Real status:** gaps verified → hydrated in `proposal.md`, `design.md`, `tasks.md` and the seven spec deltas. No product code was written.
> **Reviewed draft:** the change as first committed (`13b2264`). Rows about the documents themselves cite that draft as `draft:<file>:<line>`; `git show 13b2264:openspec/changes/omniroute-llm-pool/<file>` reproduces them.

Paths are relative to the repository. `sup/` stands for `global/scripts/lib/supervisor/`, `skill/` for `global/skills/supervisa-sesiones/reference/`.

## Methodology — 5-iteration loop

| Iter | Focus | How | Outcome |
|------|-------|-----|---------|
| 1 | Primary code paths: the watcher the triage plugs into | One read-only reviewer over `sup/watch.py`, `cloud.py`, `machine_queue.py`, `lock.py`, `unattended.py`, the skill's references | 15 candidates; 9 FACT after re-check |
| 2 | Adjacent integrations: modules, installer, config merge, validator, tests, CI | One read-only reviewer over `scripts/toolkit/`, `scripts/validate-toolkit.py`, `global/modules/`, `examples/override-full/` | 15 candidates; 13 FACT, 3 "no gap" |
| 3 | Operations, security, economics, internal consistency | One adversarial reviewer over the eleven files of the draft | 25 candidates; 16 FACT, 1 already covered |
| 4 | Cross-verify: every citation re-opened on the merged tree by the orchestrator; then a fresh reviewer over the hydrated documents | `grep -n` / `sed -n` on each cited line; reviewer given the files, not the findings | Citations: 5 line numbers corrected, 2 downgraded to INFERENCE. Reviewer: see "Verification" |
| 5 | Stop | Remaining candidates are INFERENCE, UNKNOWN or already covered | Early-stop criterion met |

The 55 raw candidates overlap; they consolidate into the 65 rows below (some candidates were split, several merged).

## Consolidated matrix

Legend: **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN**

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
| G-40 | High | No criterion said when the pool has failed, and no baseline without a model was compared | absent from the draft | HYDRATED | SO "A simulator compares three policies before any triage is built"; SO "Triage is built only if the pool beats the fixed rule"; SO "The triage is switched off when it does not pay"; D15 |
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
| G-61 | High | Whether a pool model, given the same structured brief, sleeps more soft wakes safely than a fixed rule | — | UNKNOWN | The question stage 0 answers: T 6.1–6.3. Until then the triage tasks are not built |
| G-62 | Med | A wake after a long silence may cost more if the prompt cache expired meanwhile | — | INFERENCE | Stated as a limit of the estimate in D11; the field result (T 7.4) measures real usage |
| G-63 | Low | Clock changes move the windows "within 24 hours" and the schedule | — | INFERENCE | Not specified; wall-clock time is used and the effect is one window, once |
| G-64 | Low | The ledger file never shrinks | — | INFERENCE | Out of version 1; figures are purged after 400 days |
| G-65 | Med | How the main model's usage limit weighs cache reads | — | UNKNOWN | T 1.7, before anything is built; weighted figures read "not set" until then |

## Useful casuistics

- **A slept session finishes its turn.** After a sleep the snapshot says "busy", so the later change to idle is a new event and wakes at once. With the draft's unrefreshed snapshot it would have shown no difference.
- **A batch with one soft and one hard line** wakes: triage never sees it.
- **Developer writes during a stretch of sleeps.** The judging step reads the journal whatever woke the supervisor.
- **The model always says `sleep`.** It cannot be promoted: ten of the judged samples must be cases where the supervisor was needed.
- **The gateway falls back to another model.** The answer is discarded and the member blocked.
- **A paid model with no reported cost.** The price in the definitions gives the cost; without a price the member is blocked.
- **`stop` while a project has its own dial.** The stop flag is checked first and the machine's wins.
- **An override tries to add a crash to the soft list.** Ignored and reported; the list is a constant.

## Out of v1

- Triage of repeated notices (`ALLIDLE`, `QUEUED`, `SLOTHELD`): their state is consumed when generated and the back-off already rations them.
- `wake-digest`: its input was private register text and the watcher prints the slept list itself.
- A fixed rule in the watcher with no model: it is the comparison of stage 0 and, if it wins, a change of its own.
- Headless pool workers: their own change, after the spike of T 8.3.
- Multi-user machines, SQLite compaction, clock-change handling.

## Pending count

| Class | Rows |
|-------|------|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (spec OK; `/aplica-tarea` only) | 53 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 12 |

**Gaps pending (mejora + apply): 0**

## Verification (this document)

**Verified**
- Every `path:line` in sections A and B was opened on the tree at `95991f4` with `grep -n` or `sed -n` by the orchestrator after the reviewers reported. Five line numbers the reviewers gave had moved with the merge of `main` and were corrected; two claims whose line could not be found were downgraded to INFERENCE (G-05's overlap, G-28's collision).
- Every `draft:` citation was printed from `13b2264` with `git show`.
- `openspec validate omniroute-llm-pool --strict`: valid after hydration (90 requirements, 146 scenarios).
- The privacy check over the tree: 0 findings.

**Not verified**
- Nothing was run against a real gateway: none is installed for this change. Every statement about OmniRoute comes from its README.
- The figures of the measurement (wakes, tokens) are those of the earlier measurement; they were not re-taken.
- Whether the hydrated design is implementable in the watcher as written is INFERENCE until T 5.3 has tests.
