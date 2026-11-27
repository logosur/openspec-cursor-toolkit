# Proposal — usage-watch

> **Created by:** `/prepara-tarea usage-watch` (phase P1 of `/run-spec usage-watch`).
> **Related:** `agent-model-gate` (already on `main`, installed disabled; turning it on is one of the optimisations this change asks about, never applies by itself), `watcher-wake-backoff` (an earlier cut of supervision wake cost).
> **Excluded on purpose:** an automatic brake. A previous idea of an automatic usage governor was dropped in favour of this one: nothing here stops, slows or reconfigures a session by itself.

## Why

On a machine that runs many unattended sessions, nobody sees which session or project spends tokens far above normal (a loop, wake-ups that do nothing, a role running on a model that does not fit it, subagents or the advisor on the most expensive model, a large context kept for hours, expensive cache rewrites after a pause) until the weekly quota is gone. A one-off audit script written outside this repository showed that this can be measured from the local transcripts alone, without a model. What is missing is a generic, repeatable piece that measures, detects and turns each detection into a question, plus a session role that confirms findings, asks the developer through the existing question flow and applies only what the developer authorised.

The principle is absolute: **nothing is applied without a recorded answer.** Measuring, detecting and asking are the only automatic steps.

## What Changes

**Part A: measuring and detecting (new optional module `usage`)**

- New script `usage-watch` (no model, read-only on transcripts):
  - `collect` counts, incrementally, the usage of every model response in the local transcripts (main sessions and subagents), deduplicated by message id across files and runs, weighted with a price table from configuration.
  - `detect` runs nine rules with configurable thresholds and writes findings with a stable id, evidence in figures, an estimated saving, a proposed optimisation, who applies it and how it is undone.
  - `status` prints one line with the week's pace (green, amber, red or unknown; information only) and the findings per state.
  - `page` writes a self-refreshing HTML page with the ranking and the findings.
  - `tick` runs `collect`, `detect` and `page`; `timer install|uninstall|print` manages a `systemd --user` timer that runs `tick`, following the `claude-sessions-sync install` precedent (the installer itself still writes no unit).
  - `show` prints one finding with the transcript locations that back it, for bounded confirmation reads.
  - `self-test` checks the rules, the state machine and the watcher on throwaway data.
- New config piece `usage-watch` with generic defaults (no prices, figures or names of any machine) and new contract `usage-watch`.

**Part B: the consumption sub-supervision role (module `supervision` plus the script above)**

- One sub-supervision session per machine. `supervisor-lock` gets a machine-wide role record (`usage-role`): claim, heartbeat, release, listing. Every project's census, `open` and `closable` leave that session out.
- `usage-watch wait` is the role's watcher: it exits only when a new finding appears or a question it registered is answered. With neither, it prints nothing and never ends on its own, so the role costs no model turn.
- Findings move through `new → asked → authorized | rejected → applied → measured`. `ask` registers the question in the existing `ask-queue` (stable key per finding) so the project's questions session presents it. `decide` takes no outcome argument: it reads the outcome from the queue item, and an answer recorded by the role itself (or by nobody) is not trusted. `apply` is the single place where anything changes; it refuses every finding that is not `authorized` and re-reads the queue before acting. A session's model or effort is changed with the app's tool, which a new hook (`usage-apply-gate`) lets the role use only against a one-use ticket that an authorised `apply` writes. A config change is written to the override and to the installed piece, so neither `install` nor `drift` undoes or flags it. `measure` compares the rule's metric before and after the change.
- Optimisations the role cannot apply (anything other than a config value, a session's model or effort, or turning on an installed guard) stay `authorized` and are listed in the project's `supervisor-lock backlog` for that project's supervisor.
- Generic skill reference `global/skills/supervisa-sesiones/reference/subsupervision-consumo.md` and a row in `global/rules/modelo-por-rol.md`. The installed skill text comes from a private override that this change does not edit. `design.md` lists by file and heading what has to be added there.

## Capabilities

### New Capabilities

- `usage-watch`: counting, detection rules, findings store, status line, page, timer and watcher of the `usage-watch` script.
- `usage-subsupervision`: the machine-wide role, the question and answer flow, the single apply point, the hand-off to project supervisors and the skill text.

### Modified Capabilities

- None under `openspec/specs/`. `supervisor-lock` behaviour changes are specified in `usage-subsupervision`.

## Impact

- Added: `global/scripts/usage-watch`, `global/scripts/lib/usage_watch/` (package), `global/config/usage-watch.json`, `global/contracts/usage-watch.yaml`, `global/modules/usage.yaml`, `global/hooks/usage-apply-gate`, `global/settings/hooks.usage.json`, `global/contracts/usage-apply-gate.yaml`, `global/skills/supervisa-sesiones/reference/subsupervision-consumo.md`, `scripts/toolkit/tests/pieces/test_usage_watch.py`.
- Edited: `global/scripts/lib/supervisor/` (`cli.py`, `lock.py`, `closing.py`, `backlog.py`, `selftest.py`), `global/modules/supervision.yaml` (`project_provided`, new reference file), `global/skills/supervisa-sesiones/SKILL.md` (reference table row), `global/rules/modelo-por-rol.md` (one row), `scripts/toolkit/tests/pieces/test_supervisor_lock.py`, `examples/override-full/override.yaml`, its `README.md` and `try.sh`, `README.md` (module table), `CLAUDE.md` (optional-module list).
- Not touched: `global/hooks/agent-model-gate` and its config, contract and rule.
- Risks: double counting or missed calls (incremental dedup), false positives that waste the developer's attention (each rule has a healthy-case test), a config written outside the override (single apply point, drift test), a watcher the host kills (UNKNOWN, see `design.md`).
- Size: large. Part A is self-contained and can be delivered first; the task list is ordered so that Part A lands and is checked before any of Part B.
