# Proposal — questions-session-top-level

> **Created by:** `/prepara-tarea questions-session-top-level` — 2026-11-27 (phase P1 of a `/run-spec` run).
> **Scope:** program code under `global/scripts/lib/supervisor/`, its tests (`selftest.py`,
> `scripts/toolkit/tests/pieces/test_supervisor_lock.py`) and the generic supervision-skill text shipped in this repo
> (`global/skills/supervisa-sesiones/`). The developer's private override is never edited here; the installed phrases
> it carries that become wrong are listed in `design.md`, «Notes for the override maintainer», by file and heading only.

## Why

The app shows, in the window of a session, the pending question dialogs of the side sessions linked to it. A
supervision's questions session is born as a side session of the supervisor, so its dialogs reach the developer in the
supervisor's window. A session moved to the top level (app tool `detach_session`; its app record then carries
`lineageDetached: true`) does not show its dialog in its former parent's window. The supervisor reported this as
checked with a screenshot (FACT for the supervisor, NOT VERIFIABLE from this repository).

Today the code pushes the other way:

1. `titles.adopt_lines` prints `ADOPT <id> questions (…)` when the questions session is **not** a child of the lock
   owner, including when it was moved to the top level (`lineageDetached`). The skill text then tells the supervisor to
   replace it with a new child session (FACT: `titles.py` `adopt_lines`; `reference/arranque.md`, «Sesiones hijas en la
   barra lateral»).
2. The ask gate lets the questions session open a dialog whatever its lineage (FACT: `ask_gate.py`,
   `if role == 'mailbox': … allow-mailbox`).
3. Once detached, the app stops telling the former parent when the session ends a turn (FACT: the description of the
   app tool `detach_session` says so). The watcher does not cover that gap: the skill arms it with
   `--exclude <preguntas>`, and on guard `TURN` is not a guard event (FACT: `watch.py` `GUARD_EVENTS`,
   `reference/vigilancia.md` and `reference/f6-f9.md`).

A fourth defect, in the same Stop hook a supervisor meets every turn, was reported by the supervisor and checked in the
code for this change:

4. `guard_report.report_block` is the last link of an `or` chain inside `if not payload.get('stop_hook_active')` in
   `hook.py` `hook_decide`. It is therefore not evaluated, and does not write the `.last-report` stamp, on the retry
   after a block (`stop_hook_active` true) nor when an earlier link of the chain returns a reason first (FACT:
   `hook.py`, the `if wait_armed(payload, local):` branch). The same happens when the watcher is not armed, when a
   skill-changed block returns earlier, and when an earlier link raises (the shared `try` turns the reason into `''`)
   (FACT, same function). Result: a supervisor that writes its report on such a turn is asked again for a whole report
   on every following turn.

## What Changes

- **a) `titles.py`.** For the questions role the right state is the top level. No `ADOPT` line for it any more. When
  the registered questions session hangs from any session (its record has a parent and is not detached), a new line
  `DETACH <id> questions (cuelga de <parent id>)`. The closing role keeps today's `ADOPT` behaviour unchanged.
- **b) Ask gate.** When the questions session is about to open a dialog and its app record says it still hangs from
  another session, the gate denies it **once**, telling it to move itself to the top level (`detach_session` with
  `"self"`) and retry. If the retry arrives while it still hangs (the app refused), the gate allows it and logs that
  in the gate's decision log. Nothing stays blocked.
- **c) Watcher.** `supervisor-lock wait --owner …` (also with `--guard`, and even when the questions session is in
  `--exclude`) prints a new guard event `ANSWERED …` when a question of the project's queue becomes answered, or when
  the registered questions session ends a turn after the last time the watcher looked. The supervisor wakes within
  one watcher poll interval.
- **d) Probes** in `selftest.py` for a), b), c) and f), with synthetic app records and hook payloads; unit tests in
  `test_supervisor_lock.py` updated and extended.
- **e) Text.** The generic skill text in this repo that says the questions session must hang from the supervisor is
  corrected, the new `DETACH` and `ANSWERED` lines are documented, and a new top entry goes to `reference/cambios.md`.
- **f) Report stamp.** When a supervisor's closing message is a report (`guard_report.looks_report`), the stamp is
  always written: also with `stop_hook_active`, when another block comes first, without a watcher and when an earlier
  link fails. The block itself stays one per turn.
- **g) Self-test probes that go red on a loaded machine.** On a loaded machine an installed self-test pass failed in
  different probes each time while CI stays green: one compares a clock time formatted at another moment than the text
  it checks (`revive: its text says the truth …`), three expect one particular Stop-hook block among several chained
  ones (`hook: Stop with no task …`, `hook: another owner's or a finished task does not count`,
  `supervisor-stop-gate: passes stdin through to the hook, exit 0`). Those probes must not depend on how long the pass
  takes nor on the minute of the clock: the clock or the synthetic ages are fixed at the point of the check, and a probe
  of a chained Stop block isolates the block it tests. The three `< 0.3` s latency checks (`3 locks + 400 app records`
  for `hook`, `hook PreToolUse` and `hook Stop`) are in scope: their limit is not raised silently, and each touched probe
  keeps its assertion and still fails under a mutation. Method: first reproduce the red under artificial load and keep
  the failing labels; only then fix. Done = three consecutive green self-test passes under artificial load, plus the
  simulated clock crossing a minute boundary.

## Capabilities

### New Capabilities

- `questions-session-top-level`: where the questions session lives in the app's sidebar, how the supervisor and the
  ask gate keep it at the top level, and how the supervisor learns that a question was answered once the app no longer
  tells it.
- `supervisor-report-stamp`: when the Stop hook records that a supervisor wrote its status report.
- `supervisor-selftest-stability`: the self-test's probes give the same verdict whatever the machine load and the
  minute of the clock.

### Modified Capabilities

None. No published spec covers `titles`, the ask gate's questions-session path or the report stamp
(`openspec/specs/developer-question-batches` covers `ASKDUE` and is not changed).

## Impact

- Code: `global/scripts/lib/supervisor/titles.py`, `ask_gate.py`, `session_roles.py` (one shared lineage helper),
  `watch.py` (+ a small new module or functions for `ANSWERED`), `guard_report.py`, `hook.py`, `lock.py` (docstring of
  `rename_hint` only), `selftest.py`.
- Tests: `scripts/toolkit/tests/pieces/test_supervisor_lock.py` (three `ADOPT` tests change for the questions role;
  new classes for `DETACH`, the gate, `ANSWERED` and the stamp; the minimum check count in `SelfTestTest` rises).
- Text: `global/skills/supervisa-sesiones/reference/arranque.md`, `f5-decisiones.md`, `vigilancia.md`, `f6-f9.md`,
  `cambios.md` (and `SKILL.md` only if the skill lint needs it).
- Not touched: the private override, `~/.claude`, `~/.config`, other hooks (`cross-project-message-gate` is read for a
  risk only), `ask-queue` (read through its existing functions).
- Self-test stability (g): `selftest.py` only (the probes named in g and the three latency checks); a test hook for a
  simulated clock if the implementer needs one, documented in `design.md` D7.
- Rollout after the branch (not done by the implementer): CI (the orchestrator's check), install, every live supervisor reloads the skill, the
  override maintainer updates the listed private phrases.
