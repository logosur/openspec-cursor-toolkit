# Design — questions-session-top-level

## Context

Read for this design (FACT unless marked otherwise):

- `global/scripts/lib/supervisor/titles.py`: `adopt_lines` prints `ADOPT` for the questions and closing roles when the
  record's `spawnedFrom.sessionId` is another session than the lock owner, or `lineageDetached is True`.
  `hint_lines` = `rename_lines` + `adopt_lines`; `beat` prints them on stderr (`lock.py` `rename_hint`) and
  `titles` on stdout; the watchdog runs `sync` silently.
- `global/scripts/lib/supervisor/ask_gate.py` `ask_gate_decide`: order is kill switch → answered/duplicate backstop →
  `session_roles.session_role` → parked tools (plan, offer) → `role == 'mailbox'` (allow, `allow-mailbox`) →
  `role == 'supervised'` → free-session logic, which has three more `is_mailbox_session` exits.
- `hook.py` `hook_decide`: a PreToolUse question from a non-owner goes to `ask_gate_decide`; the questions session is
  never a lock owner, so it always takes that path.
- `census.collect_sessions`: rows carry `turns` from the app record's `completedTurns`; the row id is the local id.
  `watch.wait_events` filters `rows` through `visible()` (owner and `--exclude` removed) before computing `TURN`; on
  `--guard` only `GUARD_EVENTS` survive and `TURN` is not one of them.
- The skill arms the watcher with `--exclude <preguntas>` (`reference/vigilancia.md`, `reference/f6-f9.md`).
- `ask-queue`: items are JSON lines with `id`, `status` (`open`, `asked`, `answered`, `closed`), and on answer
  `answered_ts` (ISO with offset) and `answered_by`; helpers `project_root`, `queue_path`, `read_items`, `parse_ts`.
  `providers.ask_queue_module()` loads it.
- `cloud.announce_once(key, name, items, reannounce_s, now)` keeps announced pairs in
  `<home>/announced/<key>.<name>.json` and prunes them after `closable.HOLD_HISTORY_S` (48 h).
- `guard_report.report_block` writes `<home>/backlog/<key>.last-report` only when it is evaluated and the final text
  `looks_report`. In `hook_decide` it is the last link of the chain under `if wait_armed(...)` and
  `if not payload.get('stop_hook_active')`, inside one `try` whose `except` sets the reason to `''`.
- App tool `detach_session` (its description, read in this session): moves a side session to the top level; the former
  parent is no longer told when its turns end; it works on a session this session started, or `"self"` when another
  session's Claude started this one; it is refused for some sessions and is "unavailable in unattended sessions".

## Decisions

### D1. One lineage predicate for titles and the gate

`session_roles.hangs_from(record)` returns the parent's local id when the record hangs from another session, else
`None`:

| `spawnedFrom.sessionId` | `lineageDetached` | Result |
|---|---|---|
| missing, empty, not a string, or `spawnedFrom` not an object | any | `None` (top level) |
| non-empty string | `True` | `None` (top level) |
| non-empty string | anything else (missing, `False`, `null`, a string) | the parent id (hangs) |

A second helper, `session_roles.app_record_of_cli(cli_session_id)`, returns the newest non-archived app record whose
`cliSessionId` matches (newest by `lastActivityAt`, as `titles.app_records` does), or `None`. Both never raise. Like
`is_mailbox_session`, `app_record_of_cli` skips a file whose text does not contain the CLI id before parsing it, so the
lookup costs one substring test per app record; it only runs on the questions-session path of the gate, never on the
non-owner paths that the three `< 0.3` s self-test checks time. An app record that is not valid JSON is skipped by
`census.read_json_files`-style reading, so a corrupt record reads as "no record".

### D2. `DETACH` for the questions role, `ADOPT` unchanged for the closing role

`titles.adopt_lines` only looks at the closing role (same rule as today). A new `titles.detach_lines(lock, records)`
prints `DETACH <questions id> questions (cuelga de <parent id>)` when `hangs_from(record)` is not `None`, whether the
parent is the lock owner or another session. No record, or a top-level record, prints nothing. `hint_lines` returns
`rename_lines + adopt_lines + detach_lines`, so `titles` (stdout) shows it and `beat` (stderr) shows it whenever it
shows `RENAME`/`ADOPT` today (`rename_hint` returns early when `settings.TITLES_SYNC` is off). The `rename_hint`
docstring in `lock.py` names `DETACH` too.

### D3. The gate denies the attached questions session once, then allows

Only the `role == 'mailbox'` exit of `ask_gate_decide` changes. `session_roles.session_role` returns `'mailbox'`
whenever `is_mailbox_session` is true: by title inside its project (with or without a live lock), as the `mailbox` of a
live or stale lock, or as the `mailbox` of a lock released in the last days (FACT: `session_role`; self-test checks
"no lock at all … still a mailbox" and "released 1 h ago … allow-mailbox"). The deny-once applies to every one of
those cases, because the window problem depends on the app's lineage, not on the lock. The three later
`is_mailbox_session` exits of the free-session path are practically unreachable once `session_role` said `'mailbox'`;
they are left as they are. Not changed: parked tools (plan, offer) and the owner path in `hook.py`.

At that exit, after the kill switch and the backstop (unchanged order):

1. `record = app_record_of_cli(session)`; `parent = hangs_from(record)`. Any error, or no record → today's
   `allow-mailbox` (fail open).
2. `parent is None` → `allow-mailbox` (today's behaviour).
3. Marker `<ask_gate_dir()>/detach-asked/<local id>` (local id from the record; the CLI id if the record has none)
   does not exist → write it (epoch inside), log `deny-mailbox-attached` with the parent id, return the deny json
   from a new `deny.deny_attached_mailbox(parent)`.
4. Marker exists → log `allow-mailbox-attached` with the parent id and allow.

If writing the marker fails, the question is allowed and the error goes to the gate's `errors.log` (fail open: never
two denies, never a loop).

**What "once" means.** The marker is per session (its local id), not per question or per parent: one deny in the
session's life, then every later question of that session is allowed while it still hangs. Only the marker's
existence counts: its content (`{"parent": …, "at": <epoch>}`) is informative, and a marker that is empty or not valid
JSON still counts as "already denied" (allow). Lifetime: markers are pruned when a new one is written, those whose
mtime is older than `DETACH_MARKER_KEEP_DAYS = 30`; a questions session still attached after that could be denied
once more, which keeps "at most one deny per session per 30 days" and the directory bounded. Nothing else resets it: a
new questions session has a new local id, and a detach cannot be undone, so a session that was denied once and then
detached simply takes step 2 from then on. Corrupt inputs fail open: an app record that cannot be read or parsed is
"no record" (step 1, allow); a `spawnedFrom` or `lineageDetached` of the wrong type follows the D1 table.

The deny text is Spanish (like every hook text), one line, and contains: that this is the questions session and it
still hangs from `<parent>` so its dialogs would appear in that session's window; the action `detach_session` with
`session_id` `"self"`; "vuelve a lanzar la misma pregunta"; and that the retry passes even if the app refuses the
detach. The implementer adds a stable fragment list to the tests.

### D4. `ANSWERED`: one guard event, two triggers, persisted state

New module `global/scripts/lib/supervisor/questions_wake.py` (name free for the implementer, but one module):

- **Queue trigger.** The project's queue path is resolved once per wait
  (`q.queue_path(q.project_root(project['checkout']))`). Each poll reads it with `q.read_items`; an item counts when
  `status == 'answered'` and `answered_ts` parses and is not older than `ANSWERED_WINDOW_S = 24 * 3600`. Each id is
  announced once through `cloud.announce_once(key, 'answered', [(id, …)], reannounce_s=closable.HOLD_HISTORY_S)`;
  because the window (24 h) is shorter than the prune age (48 h), an id is never announced twice.
- **Turn trigger.** The lock's `mailbox` is read each poll (`lock_mod.Store().read(project['key'])`). Its row is taken
  from the **unfiltered** census rows of that poll (so `--exclude` does not hide it). State
  `<home>/announced/<key>.questions-turns.json` = `{"id": <mailbox>, "turns": <n>}`. First sight, a different id, or
  fewer turns than recorded → record silently. More turns than recorded → trigger, then record. A turn that ended
  while no watcher ran is therefore reported at the first poll of the next wait.
- **One wake per batch.** The questions session records each answer with `ask-queue answer` and only then ends its
  turn, so the queue trigger would fire on the first id and the turn trigger on the next wait. To keep one batch to one
  wake, the queue trigger is held while the registered questions session's row is live and `busy`, unless the oldest
  not-yet-announced answered item is older than `ANSWERED_HOLD_S = 600` (a hung or very long turn still wakes). The
  held ids are announced with the turn line. The queue trigger fires alone when there is no registered questions
  session, its row is not live, or it is not busy.
- **One wake per answer.** Both triggers persist what they announced before printing, under `lock_mod.Store()` (the
  queue ids through `announce_once`, which already takes it; the turn state with its own read-modify-write inside the
  same lock), so a second poll, a second wait, or a guard watcher re-armed right after the wake never prints the same
  id or the same turn again. Held ids are not recorded until they are printed.
- **One line per poll.** When either trigger fires in a poll, exactly one line:
  `ANSWERED <mailbox id or -> [turno <a>-><b>] [contestadas <id>,<id>]` followed by a short Spanish hint (read the
  dialog's result with `list_events` of the questions session, `f5-decisiones.md`). The parts that did not fire are
  omitted.
- **Where.** In `watch.wait_events`, every poll (`--interval`), only with `--owner` and only while that id still holds
  the project's lock (a watcher left over from a former owner must not use up the announcements), after the other events are
  computed and before the `--guard` filter. `ANSWERED` is added to `GUARD_EVENTS`. It is not computed while the
  project is paused (`providers.pause_of`), and any error is written to `wait-errors.log` and gives no line.
- **No `--exclude` change.** The skill keeps excluding the questions session from the ordinary events (`TURN`,
  `STATUS`, `IDLE`…); only `ANSWERED` sees it.

### D5. The report stamp is its own step, before every block

New `guard_report.record_report(owner, payload, session, now=None)`: when the final text `looks_report`, write the
stamp exactly as `report_block` does today and return `True`; else `False`. It never raises (errors go to
`hook-errors.log`) and, like `report_block`, does nothing while `SUPERVISOR_SELFTEST_NO_REPORT` is set or the project
is paused.

`hook_decide` calls it once per `Stop` of a lock owner, right after `owner = locks[local]` and before the pause check,
the skill-changed blocks, the watcher check and the chain, in its own `try`, whatever `stop_hook_active` says.
A self-test probe that drives the hook in a subprocess must pass a child environment without
`SUPERVISOR_SELFTEST_NO_REPORT` (the self-test sets it in `os.environ`, and children inherit it).

`report_block` keeps its place in the chain and its own `looks_report` early return, so the block is still at most one
per turn and still never fires on a report. Covered by "always": `stop_hook_active` true; an earlier link of the chain
returns a reason; a skill-changed block returns; no watcher armed; an earlier link raises.

### D6. Skill text in this repo

- `reference/arranque.md`, «Sesiones hijas en la barra lateral»: the closing session hangs from the supervisor; the
  questions session lives at the top level. On `DETACH <id> questions (cuelga de <parent>)`: if the parent is you and
  `detach_session` with its id works, use it; otherwise do nothing more, the ask gate makes the questions session
  detach itself before its next dialog. `ADOPT` is for the closing session only.
- `reference/f5-decisiones.md`, «La sesión de preguntas»: after opening and registering it, detach it (or leave it to
  the gate); its brief gains one sentence: when the gate says so, `detach_session` with `"self"` and retry the same
  question. Item 5: the supervisor learns of an answer through `ANSWERED`, not through an app notice.
- `reference/vigilancia.md`: «Fuentes de despertar» (the app no longer notifies about the detached questions session),
  the signals table (rows for `ANSWERED`, and `DETACH` as a `beat` line), «Guardia» (guard event list gains
  `ANSWERED`). `reference/f6-f9.md`: the guard watcher keeps `--exclude <sesión de preguntas>` and still gets
  `ANSWERED`.
- `reference/cambios.md`: a new top entry for this change (what to do once on reload: run `titles`, act on `DETACH`,
  re-arm the watcher). The old entry is history and is not rewritten.
- The skill lint (`supervisor-lock skill-lint` on the repo copy) must still pass.

### D7. Self-test probes that do not depend on load or on the clock (point g)

Baseline of this branch (line numbers only as of the merge this change starts from; the probes are named by label):

| Label (start) | Where | Why it can go red under load |
|---|---|---|
| `revive: its text says the truth …` | `selftest.py` around 1343 (expected time from `hh(4000)`, defined around 1260) | the expected `HH:MM` is formatted at check time, the text under test at plan time; a pass crossing a minute boundary between both differs |
| `hook: Stop with no task -> block with the Spanish reason` | around 2055 | expects the no-watcher block; hypothesis to check first: another chained Stop block (or real state leaking into the sandbox) answers first on a slow pass |
| `hook: another owner's or a finished task does not count` | around 2059 | same family |
| `supervisor-stop-gate: passes stdin through to the hook, exit 0` | around 2140 | same family |
| `hook: 3 locks + 400 app records, non-owner session …` (< 0.3) | around 2127 | wall-clock latency of one subprocess run |
| `hook PreToolUse: 3 locks + 400 app records …` (< 0.3) | around 2542 | same |
| `hook Stop: 3 locks + 400 app records, non-owner …` (< 0.3) | around 3410 | same |

Method, in this order:

1. **Reproduce first.** Run the self-test in a temp HOME under artificial load (the self-test under `nice` with as
   many CPU-bound loops in parallel as the machine has cores, stopped afterwards by PID) until it goes red; keep the
   failing labels and what the hook returned in `VERIFY.md`. If no red appears in three loaded passes, record that and
   fix only what the code shows to be clock- or duration-dependent.
2. **Fix the probe, never the product's verdict.** A clock-dependent expectation is computed from the same instant the
   code under test used (a fixed `now` passed to it, or the time read back from its own output), or the synthetic ages
   are fixed at the point of the check. A probe of one Stop block isolates it: the other chained blocks are made
   unable to fire (their state absent or their switch set), so the probe fails only when its own block changes.
3. **Latency checks keep `< 0.3`.** The bound is not raised. The implementer may change how the time is taken (for
   example the best of three runs, or excluding the interpreter start measured by an empty run) and says which in this
   section; whatever the measure, a mutation that makes the timed path slower than the bound (for example a 0.35 s
   sleep or a full parse of the 400 records injected on that path) must turn the check red, and that mutation run is
   recorded in `VERIFY.md`.
4. **Simulated clock.** The clock-dependent probes accept a reference time from the test (an environment variable
   read only inside the sandbox, or an argument), so a run can start them half a second before a minute boundary and
   delay the check past it.

**Done** = three consecutive green self-test passes under artificial load, plus one run with the simulated clock
crossing a minute boundary; each touched probe still fails under its mutation.

**As applied** (P3; the reproduction found no red in three loaded passes, so only what the code shows to depend on the
clock, the duration of a pass or state outside the sandbox was changed):

- *Clock.* The self-test keeps a reference "now" (`clock['ref']`) that `iso`, `hb_ago` and `hh` read while it is set:
  around the watchdog `--notify` texts and around the revive plan, the synthetic records and the expected `HH:MM` come
  from the same instant. `SUPERVISOR_SELFTEST_MINUTE_EDGE=<s>` (kept by the sandbox, read only by the self-test) takes
  the revive reference `<s>` seconds before a minute boundary and waits past the boundary before the check, printing a
  `note:` line that says whether it crossed.
- *Latency.* The bound stays `< 0.3` s. What changed is the measure: each of the three checks runs the in-process
  `hook_decide` call three times and keeps the fastest run (`best_of_three`); the three outputs must agree, or the
  check fails. A path slower than the bound is slower in every run, so it still fails.
- *Chained Stop blocks.* With no watcher task, the hook falls back to scanning `/proc` (`wait_armed_in_proc`), which
  sees every process of the machine, including the fake `wait --owner local_sup` processes of another self-test run.
  Inside the self-test sandbox (`SUPERVISOR_SELFTEST_SANDBOX` set) the scan now counts only processes whose environment
  names the same sandbox, so the chain cannot answer instead of the no-watcher block. The three probes now assert the
  whole no-watcher reason (`no_watcher_reason`): a changed or removed reason fails each of them. A new probe (section
  34) checks that a fake watcher of another sandbox does not arm the owner and one of the same sandbox does.

## Notes for the override maintainer

The installed skill text comes from the developer's private override, which this change does not edit. These installed
places say or assume the opposite of this change (file under the override's copy of `skills/supervisa-sesiones/`,
then the heading it sits under; no private text is quoted):

| File | Heading | What is wrong after this change |
|---|---|---|
| `reference/arranque.md` | «F0b — Parseo y registro», bold paragraph «Sesiones hijas en la barra lateral» | Requires the questions session to hang from the supervisor and applies the `ADOPT` procedure to it |
| `reference/cambios.md` | The 2026-11-27 entry about session names and child sessions, item 4 | Tells the supervisor to act on `ADOPT` for the questions session; needs a new top entry like the repo's |
| `reference/f5-decisiones.md` | «La sesión de preguntas…», item 1 and the brief in item 2 | Opens it as a side session and never detaches it; the brief has no detach instruction |
| `reference/f5-decisiones.md` | «La sesión de preguntas…», the part on how the supervisor learns of an answer | Relies on being told when that session ends a turn |
| `reference/vigilancia.md` | «Fuentes de despertar», row «Avisos de la app» | Counts on the app notice for a session the supervisor opened |
| `reference/vigilancia.md` | «Señales y qué se hace con cada una» | No row for `ANSWERED`, no `DETACH` line |
| `reference/vigilancia.md` | «Guardia (después de la tanda final)» | The guard event list lacks `ANSWERED` |
| `reference/f6-f9.md` | «F9 — Tanda final, trabajo siguiente y guardia», guard watcher command | Still correct, but should say `ANSWERED` arrives despite `--exclude` |

## Risks

| Risk | Class | Mitigation |
|---|---|---|
| `detach_session` with `"self"` is unavailable or refused for a real questions session (unattended, shares the supervisor's checkout) | UNKNOWN | D3 allows the retry; `DETACH` keeps showing on `beat`, and the skill says who may act. Recorded as a follow-up observation, not a gate |
| The app keeps `spawnedFrom` after a detach and adds `lineageDetached: true` | INFERENCE (existing unit fixtures carry both fields; the supervisor's report says `lineageDetached: true`) | D1 treats `lineageDetached: true` as top level whatever `spawnedFrom` says |
| `cross-project-message-gate` resolves short names through the `spawnedFrom` family | FACT (lines around `app_lookup`) | The supervisor addresses its questions session by local id, which resolves by `sessionId` (FACT, same function); not edited |
| The first wait after install announces answers of the last 24 h once | INFERENCE | One extra wake, once; accepted |
| `ANSWERED` for an answer the supervisor already read | INFERENCE | Once per id; the hint says to check `list_events`, which is idempotent |
| A held answer is late by up to `ANSWERED_HOLD_S` when the questions session stays busy | INFERENCE | Bounded; the turn line usually comes first |
| Reading the queue every poll | INFERENCE | One small JSONL read; the path (a `git` call) is resolved once per wait |
| Unrelated self-test checks write a stamp | INFERENCE | `record_report` honours `SUPERVISOR_SELFTEST_NO_REPORT`; the probes for D5 lift it locally, like the existing report probes |

## Edge cases

- Questions session with no app record, or archived → no `DETACH`, gate allows (fail open), no turn trigger.
- `mailbox` not registered in the lock → no turn trigger; the queue trigger still works.
- The questions session hangs from the lock owner itself → `DETACH` (the old code printed nothing).
- Closing session detached → `ADOPT … closer (abierta por …)` exactly as today.
- Corrupt `questions-turns.json` → treated as first sight (record silently).
- Questions session whose cwd is outside the project → not in the census: no turn trigger; the queue trigger still
  works (INFERENCE from `census.collect_sessions`).
- `answered_ts` missing or unparsable → the item is not announced.
- `completedTurns` missing → no turn trigger for that poll.
- Several answered ids in one poll → one line listing all of them, sorted.
- A gate marker exists but the session is now detached → `allow-mailbox`, marker ignored.

## Testing strategy

- Unit tests in `scripts/toolkit/tests/pieces/test_supervisor_lock.py`, each class runnable by id (light commands):
  `DETACH`/`ADOPT` (through `titles --session` and `beat`), the gate (through the `hook` command with a synthetic
  PreToolUse payload and app records), `ANSWERED` (through `wait --owner … --guard --exclude <questions>` with the
  `SUPERVISOR_WAIT_READY` pattern and a temp `ASK_QUEUE_BIN` queue), the stamp (through the `hook` command with
  `stop_hook_active` true, and with an earlier block firing).
- Self-test probes in `selftest.py` next to the existing ones (titles, ask gate section 11b, the report checks), all
  with synthetic records in the sandbox. The minimum check count in `SelfTestTest` rises by the number of new checks.
- Gate: `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock.SelfTestTest` (light, about 6 min, temp
  HOME). Never run the self-test against the real HOME. The floor of `test_the_whole_self_test_passes_in_a_temp_home` is
  564 (563 without the skill) on this branch's base; each phase raises it by exactly the number of `ok` checks it adds.
- A latency check that goes red once on a loaded machine before point g is applied is rerun once alone and both
  results are recorded; it is not fixed outside point g.
