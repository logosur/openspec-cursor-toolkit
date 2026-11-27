# Tasks — omniroute-llm-pool

Requirement references: **GW** = `specs/llm-pool-gateway/spec.md`, **RG** = `specs/llm-pool-registry/spec.md`, **RT** = `specs/llm-pool-routing/spec.md`, **CT** = `specs/llm-pool-control/spec.md`, **LG** = `specs/llm-pool-ledger/spec.md`, **CS** = `specs/llm-pool-console/spec.md`, **SO** = `specs/supervision-offload/spec.md`. Design decisions: **D1**–**D14** in `design.md`.

Tasks marked **[developer]** are his alone and block only what names them. Everything is built and tested against a stub gateway in a temporary home, so groups 2 to 6 do not wait for group 1.

## 1. Spike: the gateway on one machine (answers the UNKNOWN rows of the design)

- [ ] 1.1 Inspect any earlier OmniRoute data directory on the machine without opening credential files: its size, dates and version. Record whether it is reused or set aside, and why, in `evidence/spike.md`.
- [ ] 1.2 **[developer]** Install the pinned gateway version and connect at least one provider in its dashboard.
- [ ] 1.3 With the gateway running, record in `evidence/spike.md` the exact calls (CLI with JSON output, HTTP) to: list models and their state; read quota and reset per connection; read usage and cost per key and per request; create and update a combo; and whether a response carries an id that joins it to the gateway's call log. Update the Context table of `design.md` from UNKNOWN to FACT. Accept when each call was run and its output shape is written down with secrets removed.
- [ ] 1.4 For each connected provider, read its terms on training and retention; write the result with a source link and the date in the override's registry (RG: provider terms decide the data class). Accept when no connected provider is left "unread".
- [ ] 1.5 Decide one combo per member or per task kind (Architecture, last note) from 1.3 and record the decision in `design.md`.
- [ ] 1.6 Verify the gateway's exposure: loopback only, HTTP MCP transport off, remote mode unused (GW: doctor reports the whole chain). Evidence: the listening sockets and the gateway's own status output.

## 2. Module core, no traffic

- [ ] 2.1 `global/modules/llm-pool.yaml` (depends: `core`; optional), `global/config/llm-pool.json` with the task-kind catalog, defaults and commented example members only (RG: shipped registry contains examples only); verify with the validator's `global-*` rules and the privacy check.
- [ ] 2.2 Registry loader: decided attributes from the config piece, observed state in a state file, validation of each member, member states and their transitions (RG: all requirements; D4); verify with unit tests for each scenario of RG.
- [ ] 2.3 Ledger: SQLite schema, one row per request, redacted payload with retention, owner-only file, paginated and filtered history with a stable cursor (LG: one row per request; payload; history); verify with unit tests, including the second-page scenario with rows written in between.
- [ ] 2.4 Audit log and `llm-pool why <member>` (CT: every change is audited); verify that each state, mode, dial and enablement change writes an entry with actor and reason.
- [ ] 2.5 CLI skeleton with `list`, `status`, `enable`, `disable`, `assign`, `unassign`, `mode`, `dial`, `project`, `stop`, `resume`, `history`, `judge`, `doctor`, all with `--json` (CT: one command line; kill switch; narrowing is always allowed); verify each command against the temporary home.
- [ ] 2.6 A stub gateway for tests (local HTTP server with scripted answers, quotas, errors and delays); verify it is used by every test below and that no test reaches a real network.

## 3. `ask`: gate, budgets, fallback

- [ ] 3.1 `llm-pool ask --task <kind>` with the exit-code contract and a bounded timeout (RT: one entry point; GW: works without the gateway); verify one test per exit code, and that the unreachable case returns within the timeout.
- [ ] 3.2 Eligibility: assignment, minimum power, data class, state, mode, dial, enabled project, allowed caller (RT: modes; dial; only enabled projects; only the supervisor and its child sessions; RG: a member only takes a task kind it is fit for); verify with a table-driven test over every combination that can refuse.
- [ ] 3.3 Privacy gate: class check, redactor built on the privacy checker's patterns plus key shapes, refusal when a secret survives masking (RT: privacy gate; D9); verify with payloads containing each secret shape, and that a refused payload is not stored.
- [ ] 3.4 Budgets: daily budget per member, share per task kind with triage first, paid members blocked without a cap and exhausted at the cap (RT: billed members; free quota is rationed; D10); verify the starvation scenario and the cap scenario.
- [ ] 3.5 Promotion and demotion: scorecard thresholds, refusal with what is missing, automatic probation (RT: promotion needs evidence; demotion is automatic; D6); verify with seeded ledgers.
- [ ] 3.6 `llm-pool why <ledger id>` (CT: explain a routing decision); verify on a served row and on each kind of fallback row.
- [ ] 3.7 Dial in `follow-usage` through a usage provider, manual when it is missing (RT: the dial can follow the main model's usage; D7); verify with a fake provider and with none.
- [ ] 3.8 `doctor` complete, including the pinned version and reconciliation with the gateway's usage when 1.3 found it (GW: one pinned version; doctor; LG: usage is reconciled); verify each failure is listed in one run.

## 4. Console and control by prompt

- [ ] 4.1 `llm-pool console`: loopback server, static files, app window, per-start write token, refusal of other origins (CS: local app window; writes are protected; D12); verify with tests against the server and a check that the page requests no other host.
- [ ] 4.2 Pool view: header and one card per member with every field of CS, the switch, and the not-active explanations (CS: pool view; header; switches act at once); verify in a real browser at 1366×768, light and dark, by keyboard, with screenshots in `evidence/console/`.
- [ ] 4.3 History window: opened from a card or the header, paginated, filtered, with the row detail and the routing explanation (CS: a link opens the history; never shows a secret); verify with a ledger of at least 1 000 seeded rows and a row whose payload had a secret masked.
- [ ] 4.4 Skill `llm-pool`: plain request to one command, ambiguity handling, refusal of widening requests that are not the developer's own words (CT: control by prompt; widening needs the developer's own words; D13); verify with the catalog validator's routing rules and with scripted requests in a temporary home.
- [ ] 4.5 Desktop launcher installed by the module, removed by uninstall; verify with `install` and `uninstall` in a temporary home.

## 5. Supervision integration, shadow first

- [ ] 5.1 Triage provider in the supervisor package that answers "wake" when the module is absent (SO: the pool is optional; D1); verify the supervision self-test passes unchanged without the module.
- [ ] 5.2 Soft-event list in the supervision config piece, narrowing only (SO: hard events are never triaged; D8); verify that every other event wakes with no pool request, one test per hard event.
- [ ] 5.3 Brief builder for `wake-triage` and `wake-digest` with the size limit and a test that transcript text cannot enter it (SO: the triage brief carries no private content).
- [ ] 5.4 Shadow mode in the watcher: run the triage, record it, wake as before; judgement from what the supervisor did on that wake (SO: shadow triage changes nothing); verify by replaying recorded wakes.
- [ ] 5.5 `auto` in the watcher: honour a bounded sleep, forced wake on deadline, silent-time cap and consecutive-sleep cap, anything but a clean sleep wakes, the wake lists what was slept (SO: a sleep is bounded; anything but a clean sleep is a wake; a wake after sleeps says what was slept); verify each bound with a test and each failure mode of the stub gateway.
- [ ] 5.6 Supervision skill: the judging step at each wake after sleeps, the task kinds each role may use, the saving line in the report (SO: the supervisor judges the sleeps; scope; the report carries the saving); verify with `skill-lint` and the self-test.
- [ ] 5.7 Digest task kinds for child sessions, with "what was left out" in every digest (SO: digests are read by the main model); verify with a long seeded log.

## 6. What-if simulator (before anything is switched on)

- [ ] 6.1 Simulator that reads the last days of supervisor wakes from the transcripts and, for a candidate policy, reports the soft wakes, the tokens they cost, the pool tokens triage would have needed and the saving if a given share had slept (D14); verify on a seeded transcript with a known answer.
- [ ] 6.2 Run it on the machine and write the report, with project names removed, to `evidence/what-if.md`. Accept when it states the baseline that task 7.1 will be compared with.

## 7. Field rollout and measurement

- [ ] 7.1 **[developer]** Enable one project and set the dial to 1. Run `wake-triage` in `shadow` for at least 7 days and 50 judged samples per candidate member. Evidence: the scorecards in `evidence/shadow.md`.
- [ ] 7.2 Measure the main model's usage limit before and during the pool, to learn how it weighs cache reads; set the ledger's weights from it (D11) and record the method.
- [ ] 7.3 **[developer]** Promote `wake-triage` to `auto` for that project on the best member, if its scorecard meets the thresholds.
- [ ] 7.4 After 7 days in `auto`: compare supervisor wakes and tokens per hour with the baseline of 6.2, list every miss with its cause, and write the leverage reached to `evidence/result.md`. Accept when the report says plainly whether the pool saved tokens, how many, and at what risk.
- [ ] 7.5 Decide from 7.4 whether to extend to the other supervisors and to the digest task kinds, and record it in `design.md`.

## 8. Extensions (each one optional, in this order)

- [ ] 8.1 Scorecards and canary checks in the console.
- [ ] 8.2 Replay of a stored request on another member.
- [ ] 8.3 Spike: whether the desktop app can start a session against another endpoint, and whether `omniroute run claude` in print mode completes a bounded public micro-task acceptably on a pool member. Record in `evidence/spike-workers.md`. If it does, headless workers get their own change.
- [ ] 8.4 Local models as members with `billing: local`, started through the machine's heavy-job queue.
- [ ] 8.5 Quota forecast, recommendations and schedules.

## 9. Closing

- [ ] 9.1 Documentation: module section in `README.md`, the module's notes, the watcher reference of the supervision skill.
- [ ] 9.2 `python3 -m unittest discover -s scripts/toolkit/tests -t .`, the catalog validator, `examples/override-full/try.sh` and the privacy check all exit 0.
- [ ] 9.3 `/verifica-tarea omniroute-llm-pool`.
