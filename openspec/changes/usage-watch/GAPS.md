# GAPS — usage-watch (honest multiagent review)

> **Date:** 2026-11-27
> **Mode:** A
> **Real status:** Part A and Part B applied (P3 iteration 1); earlier: gaps verified → hydrated (design D1, D2, D4, D7, D12, D14, § Configuration; both spec deltas; tasks 1.1, 1.2, 2.5, 5.3, 5.4, 6.1, 7.1, 7.2, 8.1–8.6, 9.3, 10.1, 10.2, 11.1)

## Review objective

Phase P2 of `/run-spec usage-watch`. Two points had to be settled before any code: (1) the authorised state must
come only from an answer recorded in the question queue, never from a command the role can run on its own, and `apply`
must refuse and write nothing in every other state for both kinds of optimisation (config values and a session's
model or effort), testably; (2) the module direction (`usage` depends only on `core`, yet the cycle touches the question
queue and `supervisor-lock`) checked against the validator's `global-*` rules before the first file lands.

## Methodology — 5-iteration loop (early stop allowed)

| Iter | Focus | Honest result |
|------|-------|---------------|
| **1** | Point 1: who can write `authorized`; what `apply` gates for each kind | 2 FACT (G-01, G-02) |
| **2** | Point 2: validator experiment in a scratch copy of the repository with a draft `usage` manifest | 1 FACT (G-03), reproduced with the validator's own output |
| **3** | Part A testability: undefined quantities, config shapes, data sources of the attribution | 5 FACT (G-07 … G-11) |
| **4** | Task list against the phase's rules (no post-push task, no whole-tree discover locally, override-full coverage) | 3 FACT (G-04 … G-06) |
| **5** | STOP check | 1 more FACT (G-12, found while writing G-02's ticket); no new FACT after it → stop |

### Validator experiment (iteration 2, scratch copy, not the branch)

| Draft | `python3 scripts/validate-toolkit.py` |
|---|---|
| `usage.yaml` `depends: [core]`, a script citing `~/.claude/scripts/ask-queue` and `~/.claude/scripts/supervisor-lock`, no `project_provided` | 2 errors `[global-citation] cites ~/.claude/scripts/ask-queue / supervisor-lock, which module 'usage' and its dependencies do not install` |
| same, with `project_provided: [scripts/ask-queue, scripts/supervisor-lock]` | 0 errors |
| `lib/supervisor/backlog.py` citing `~/.claude/scripts/usage-watch` (D10) without listing it in `supervision.yaml` | 1 error `[global-citation] … module 'supervision' …` |
| a `usage` hook with its own fragment and no contract | 1 error `[global-contract] hook hooks/usage-apply-gate has no contract` |

`scripts/toolkit/modules.py:103` detects cycles on `depends` only; `project_provided` never enters the install order.

## Consolidated matrix

Legend: **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN**

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-01 | High | The role picks the outcome: `decide ID --authorized\|--rejected` only checks that the queue item is `answered`, and `ask-queue answer` has no caller check, so the role can answer its own question and then authorise it. Nothing re-reads the queue at `apply` time either. | `design.md` D7 (`decide ID --authorized\|--rejected`); `global/scripts/ask-queue:526-528` (`cmd_answer` records `answered_by` and nothing else) | HYDRATED | (proposed) US: the outcome is read from the queue; apply re-checks the answer |
| G-02 | High | `apply` gates `session-model` and `session-effort` only procedurally: the app's session tools are called by the role directly and nothing mechanical stops a call without an authorised finding. | `design.md` D7 ("The gate is procedural for these kinds") and Risks ("for session model and effort it is procedural") | HYDRATED | (proposed) US: a hook only lets the usage role change a session's model or effort with a ticket from `apply` |
| G-03 | High | Module direction: D4 makes Part A read roles through `supervisor-lock list --json` (a script of `supervision`) and D10 makes `supervision` call `usage-watch`; both are citations the validator rejects unless declared, and the G-02 hook needs a contract. | validator experiment above; `scripts/validate-toolkit.py:632-651` (`check_citations`), `:613-630` (`check_contracts`) | HYDRATED | (proposed) design D1/D4: Part A reads supervision data files only; citations declared both ways; hook in `usage` with contract |
| G-04 | Med | `examples/override-full` does not install `usage` and its `try.sh` runs no `usage-watch` check; the task that adds it (10.2) is in Part B. | `examples/override-full/override.yaml:4` (nine modules, no `usage`); `examples/override-full/try.sh` (self-tests of `supervisor-lock`, `test-account`, `process-kill-gate` only); `tasks.md` 10.2 | HYDRATED | (proposed) tasks 1.2 and 5.3 |
| G-05 | Med | `usage-watch self-test` exists only in Part B (9.3), so after Part A nothing but the contract covers the module in `try.sh`. | `tasks.md` 9.3; `proposal.md` lists `self-test` in Part A | HYDRATED | (proposed) task 5.3: Part A self-test (counting and rules), extended in 9.3 |
| G-06 | Med | Task 5.4 requires the whole-tree `unittest discover`, and 11.1 requires "CI `Validate toolkit` green on the branch", which can only be ticked after a push. | `tasks.md` 5.4, 11.1 | HYDRATED | (proposed) reword both to local checks; CI is the orchestrator's |
| G-07 | Med | "Context size of the call" is used by `large-context` and `idle-rewrite` but never defined. | `specs/usage-watch/spec.md` (counting requirement, large-context, idle-rewrite); `design.md` D2 | HYDRATED | (proposed) UW counting: context = input + both cache writes + cache read |
| G-08 | Med | `toolkit_config.load_checked` checks only the top-level type, so a `prices` entry with three weights or a `proposals` entry that is not text would reach the rules. | `global/scripts/lib/toolkit_config.py:36-47` (`_same_shape` for dict is `isinstance`) | HYDRATED | (proposed) UW thresholds: nested entries validated one by one |
| G-09 | Low | `week_start` ("weekday and hour, UTC") has no shape a test can set. | `design.md` D12 | HYDRATED | (proposed) two numeric keys `week_start_weekday`, `week_start_hour` |
| G-10 | Low | The write-scope requirement lists `self-test`, which by design writes a throwaway home outside `state_dir`. | `specs/usage-watch/spec.md` (write-scope requirement) | HYDRATED | (proposed) UW write scope: except its own temporary directory, removed at exit |
| G-11 | Med | The attribution's data sources are unnamed: app records live at `<app_sessions_dir>/*/*/local_*.json`, locks at `<supervisor home>/locks/*.json` with a released flag; the "without supervision" scenario is phrased as "`supervisor-lock` is not installed", which Part A can no longer observe once it reads files. | `global/scripts/lib/supervisor/settings.py:77`; `global/scripts/ask-queue` `live_lock_files`; `lock.py:23,34` | HYDRATED | (proposed) design D4 and UW attribution |
| G-12 | Med | The session tools take the app id (`local_…`), while a finding's session is the transcript's CLI id; a `session-model` finding without that join cannot be applied or gated. | `design.md` D4 (ids joined through app records); `global/scripts/lib/supervisor/census.py:129-135` | HYDRATED | (proposed) US apply: target app id required, else the proposal is a `note` |

## Post-apply review (round 1, Part A applied)

| Iter | Focus | Honest result |
|------|-------|---------------|
| **1** | Part A code against both spec deltas and design D1–D5, D12, § Configuration | 2 documentation gaps found mid-apply and fixed in place (`cheap_model` and `origin_text_prefixes` were config keys the design did not list; D5 did not say what a `session-model` proposal sets); no behaviour gap |
| **2** | Module direction as built: `usage.yaml` `depends: [core]`; the package cites and imports nothing of `supervision` (test `test_no_supervision_code_and_no_machine_names`) | 0 FACT |
| **3** | Part B rows G-01, G-02, G-12 and the D14 hook | still HYDRATED, unapplied by scope (Part B is the next phase); not counted as pending |
| **4** | STOP check | no new FACT |

## Pre-apply check (round 2, Part B — P3 iteration 1)

| Iter | Focus | Honest result |
|------|-------|---------------|
| **1** | Part B rows (G-01, G-02, G-03, G-12) and tasks 6.1–11.2 against the code on the branch | still HYDRATED; no new FACT before code |
| **2** | STOP check | no new FACT → hydrate phase has nothing to add; `openspec validate usage-watch --strict` exit 0 |

## Post-apply review (round 2, Part B applied)

| Iter | Focus | Honest result |
|------|-------|---------------|
| **1** | Part B code against `usage-subsupervision` and D7–D14 | 3 FACT found mid-apply and **fixed in the same phase** (G-13 … G-15); D15 records the details settled while applying |
| **2** | Every US scenario against a named test (VERIFY.md, implementation table) | 0 FACT: every requirement has a passing test |
| **3** | Boundaries: Part A still cites no supervision script; role modules run `ask-queue` and `supervisor-lock` only as subprocesses from `role.py`; validator citations both ways | 0 FACT (`AttributionTest.test_no_supervision_code_and_no_machine_names`, validator 0 errors) |
| **4** | STOP check | no new FACT |

| ID | Sev | Gap | Evidence (FACT) | Status |
|----|-----|-----|-----------------|--------|
| G-13 | Med | A finding stored only the project *name*; `ask` needs the main checkout to find the project's lock and queue | `rules.py` `candidate` (no checkout field before this round) | FIXED (`project_root` on every finding; D15) |
| G-14 | Med | `apply` read the installed piece with a helper that returns the default for any value whose type differs from it (`None`), so every config apply refused | `state.read_json` type check; `ConfigApplyTest` failed before the fix | FIXED (`read_json_quiet`) |
| G-15 | Med | The config write did not keep the installed file's mode, so `drift` reported `chmod` for the piece | `drift` output in `ConfigApplyTest` before the fix | FIXED (mode kept; D15) |

## Independent confirm review (P4 of `/run-spec`, re-derived from the specs and the code)

| Iter | Focus | Honest result |
|------|-------|---------------|
| **1** | Every rule's firing and healthy case (`scenarios.CASES`, `RuleCasesTest.test_every_rule`, nine rules) | 0 FACT |
| **2** | The walk and the watcher (`WalkTest`, `WaitTest`, `watcher.events`) | 0 FACT |
| **3** | Every write path outside `state_dir`: `flow.apply` (config, ticket), `flow.decide`, `gate.check`, the hook | 1 FACT (G-16) |
| **4** | Module ownership and contracts (validator 0 errors); `agent-model-gate` untouched against `origin/main`; privacy | 0 FACT |
| **5** | STOP check | no new FACT |

| ID | Sev | Gap | Evidence (FACT) | Status |
|----|-----|-----|-----------------|--------|
| G-16 | High | The developer's answer was not bound to the change `apply` makes. `ask` registers the role's free `--question` text plus `authorize_hint`; the concrete change (config piece, key and value, or the target session, field and value) was never in the queue item, and `apply` re-read only the answer text, then applied whatever `proposal` and `target_app_id` the store held at that moment. A question that misdescribes the change, or a store whose proposal was edited after the answer, still applied. | `flow.ask` (question = role text + hint); `flow.apply` (verdict compares the answer text only); `flow._apply_config` / `_issue_ticket` read `proposal` and `target_app_id` from the store | FIXED: `ask` always writes a `change` line (`flow.change_text`) into the question; `apply` refuses (exit 3, nothing written, no ticket) unless the queue item's question, read again, still holds the change text of the finding as stored now. Tests `ApplyRefusalTest.test_a_change_edited_after_the_answer_is_refused`, `AskTest` (change line in the question) |

Non-blocking note: `origin/main` moved after this branch was cut and also edits `global/scripts/lib/supervisor/backlog.py`,
`selftest.py` and `scripts/toolkit/tests/pieces/test_supervisor_lock.py`; the integration phase merges them.

## Useful casuistics (documentation, not always new REQ)

- An item answered from a plain terminal has an empty `answered_by` (`ask-queue:527`). It is not trusted: the finding
  stays `asked` and `decide` says why. The developer answers through the questions session, which runs in the app.
- The role could still forge an answer by setting the environment variables `ask-queue` reads. That is deliberate
  circumvention by a shell-capable agent, out of reach of any script; the rule text forbids it and `decide` records
  `answered_by` so it is visible.

## Out of v1 (does not block APPLY)

- Whether a hook process sees `CLAUDE_CODE_HOST_SESSION_ID` is UNKNOWN; the role record stores both ids and the hook
  compares the hook input's `session_id` too, so the gate does not depend on it.

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED, still to apply | 0 |
| Applied (G-01 … G-12) or fixed mid-apply (G-13 … G-15) or in the confirm review (G-16) | 16 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 0 (the hook-environment UNKNOWN is out of v1) |

## Verification (this document)

- **Verified:** every evidence cell by reading the cited file; the validator rows by running it in a scratch copy.
- **Not verified:** the hook environment (UNKNOWN above); the real-machine walk (tasks 12.x, `[prod-verify]`).

Gaps pending (mejora + apply): 0
