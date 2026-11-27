# GAPS — supervisor-exit-code-probes (preparation pass)

> **Date:** 2026-11-27. **Mode:** A (change folder `openspec/changes/supervisor-exit-code-probes/`).
> **Real status:** preparation pass (P1) by one agent plus one advisor consultation; the gaps below were found while reading
> the code and the self-test and are closed in the documents. The independent review (`repasa-spec`) has not run.

| ID | Sev | Gap | Evidence (FACT) | Status | Where closed |
|----|-----|-----|-----------------|--------|--------------|
| G-01 | high | The request says codes 3, 4, 6, 7, 8 and 9 "have no probe at all"; the self-test already asserts every one of them | `selftest.py` labels listed in design D2 (e.g. `acquire: other session, fresh -> HELD, exit 3`, `acquire: other session, stale -> STALE, exit 4`, `release: other live session busy -> exit 6 …`, `backlog: each change … exit 7`, `skill-seen proof: … (exit 8) …`, `beat --state paused with usage and no --third-party: refused (exit 9) …`) | HYDRATED (premise corrected) | proposal "Why" (corrected premise), design D2 |
| G-02 | med | A code can have several exit sites; probing "per code" would leave sites unprobed | code 3 has 5 sites, 6 has 3, 7 has 2, 8 has 2 (`lock.py`, `cloud.py`, `backlog.py`) | HYDRATED | design D2 (matrix by site) |
| G-03 | med | `cloud` with the provider absent (`CLOUD-UNAVAILABLE`, exit 3) has no check | no `CLOUD-UNAVAILABLE` string in `selftest.py`; `cloud.cmd_cloud` | HYDRATED | design D3 N2, task 2.2 |
| G-04 | med | `cloud-archive`/`cloud-send` with unreadable rows (`util.die(…, 3)`) have no check | `cloud.cloud_owned_target`; no check reaches it | HYDRATED | design D3 N3, task 2.3 |
| G-05 | med | A beat refused for both the skill and the pause returns 8 and prints both reasons; no check | `lock.cmd_beat`, the `if refused_pause` print inside the skill branch; no check combines `--skill-seen` with a refused pause | HYDRATED | design D3 N4, task 2.4 |
| G-06 | low | The refused fresh `acquire` (3) does not assert the lock is unchanged, while the stale one (4) and the refused `reclaim` (3) do | labels `acquire: stale lock left untouched`, `reclaim: wrong --from -> HELD, exit 3, untouched` | HYDRATED | design D3 N1, task 2.1 |
| G-07 | med | No evidence exists that any of these checks fails when its site changes | no mutation record anywhere in the repo for `supervisor-lock` | HYDRATED | design D5, tasks 3.1–3.15 |
| G-08 | low | `util.die(…)` exit sites are missed by a grep for `return <n>` | `cloud.py` `cloud_owned_target` | HYDRATED | design D2 basis, task 1.2 re-derives the list |
| G-09 | low | The piece test pins a floor of `ok` lines (558/557); new checks must raise it or a later removal goes unnoticed | `scripts/toolkit/tests/pieces/test_supervisor_lock.py` | HYDRATED | design D4, task 2.5 |
| G-10 | low | "Probes" also names the fast contract probes in `global/contracts/supervisor-lock.yaml`; the request means self-test checks | the contract header says the full self-test runs in the toolkit suite | HYDRATED (out of scope, stated) | proposal Non-goals |
| G-11 | low | A mutation in place could leave product code dirty | — | HYDRATED | design D5 (throw-away copy recommended; revert check per row) |
| G-12 | low | The request asks to record that the private text of the `supervisa-sesiones` skill is not touched | request text | HYDRATED | proposal Non-goals, task 4.3 |
| G-13 | high | The self-test looked red on the unmodified tree (9 `FAIL`) | preparation run made directly under the real `HOME` | SUPERSEDED by G-14 (that run was not the gate) | — |

UNKNOWN (does not block): whether the cloud lock is still held by its owner at the point where N3 runs (design D3 states
the fallback; task 2.3 checks it first).

## repasa-spec — Phase 1, pre-apply gap pass (P2 of `run-spec`)

> Mode A, one iteration (the preparation table above is the base; the orchestrator's corrections and a grep of the code and
> of `selftest.py` are the new evidence). FACT 6, INFERENCE 0, REJECTED 0.

| ID | Sev | Gap | Evidence (FACT) | Status | Where closed |
|----|-----|-----|-----------------|--------|--------------|
| G-14 | high | Tasks 1.1/4.1, design D6 and the spec scenario "Green self-test" use `supervisor-lock self-test` run directly (under the real `HOME`) and a CI run as evidence; the local gate is the piece test, which is green | orchestrator baseline: `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock.SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home` exit 0 in about 7 min on the unmodified tree | HYDRATED (Phase 2) | design D6, tasks 1.1, 4.1, spec "Green self-test", READY-TO-APPLY |
| G-15 | med | D5 asks for 14 sequential full runs, one mutation each (about 7 min each) | `cmd_self_test` is one function with no way to run a subset | HYDRATED (Phase 2) | design D5 (three batches on throw-away copies, sites sharing a statement split, expected labels written first, one run at a time), tasks group 3, spec "A mutated site turns its check red" |
| G-16 | med | D2's "Existing check" column misses checks that assert the same codes, so a batch could show `FAIL` labels nobody expected | `selftest.py`: second busy-release check and the workspace release checks (6), `backlog: a park is void …` (7), the `refused()` family and the other-session beat (8) | HYDRATED (Phase 2) | design D2 column completed; D5 step 3 |
| G-17 | low | The S3c scenario says "a project with no lock", but `cmd_cloud` never reads the lock and the probe runs on the cloud project, which holds one | `cloud.cmd_cloud` | HYDRATED (Phase 2) | spec scenario S3c, design D3 N2 |
| G-18 | low | Task 4.6 accepts "the CI run of the pushed commit"; nothing is pushed in this phase | orchestrator order: no commit, no push | HYDRATED (Phase 2) | task 4.6 (run locally through heavy-job) |
| G-19 | low | D3 N3 left as HYPOTHESIS whether the cloud lock is still held where N3 runs | section 30 of `selftest.py`: no `release` between the cloud `acquire` and the `CLOUD-UNKNOWN` check | HYDRATED (Phase 2) | design D3 N3 (FACT; the check asserts the owner) |

Gaps pending after Phase 1 (before mejora + apply): 6, all closed in the documents by Phase 2.

## repasa-spec — Phase 4, post-apply gap pass (round 1)

> Mode A, one iteration over the applied tree: `selftest.py` (6 new checks), the piece-test floors, and
> `evidence/mutations.md`. FACT 0 new gaps, INFERENCE 1 (below, out of scope), REJECTED 0.

| Requirement | Evidence (FACT) | Status |
|-------------|-----------------|--------|
| R-SITE: every exit site of D2 has a check | S3c, S3e and S8b now have checks (D3 N2, N3, N4); all 14 sites' labels print `ok` on the final tree (652 `ok`, 0 `FAIL`) | met |
| R-STATE: refused commands leave their state | N1 (fresh `acquire`), N3 (no archive or send logged), N4 (state `running`, no `pause_cause`, `skill_seen` unset) print `ok` | met |
| R-MUT: each probe fails when its site changes | three batches, 14 of 14 sites with at least one `FAIL` of their own, no unexpected `FAIL`, `ok + FAIL` = 652 in each batch (`evidence/mutations.md`) | met |
| R-ONLY: tests only, self-test green | `git diff --stat 182c084 -- global/` lists only `selftest.py` (32 lines added, none removed); the piece-test module passes (82 tests); floors raised by 6 | met |

Observation, not a gap of this change: the pre-existing check `watchdog --notify: idle text, unknown text (time from the
heartbeat)` failed once in six runs (the baseline count run) and passed in the other five. INFERENCE: a minute boundary
between two `HH:MM` texts. Outside the scope (no exit code; existing checks are not changed here); recorded in
`evidence/mutations.md`.

## Verification (this document)

- **Verified:** every row above against the code (`lock.py`, `cloud.py`, `backlog.py`, `selftest.py`) and the runs recorded in
  `evidence/mutations.md` (local gate, final count, three mutation batches, toolkit suite).
- **Not verified:** the minute-boundary cause of the intermittent watchdog check (INFERENCE, out of scope).

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (closed in the documents and applied) | 18 |
| Non-blocking (G-13 superseded; the watchdog observation, INFERENCE) | 2 |

The loop ends after round 1 (`gaps_pending` = 0).

## repasa-spec — independent confirm review (P4 of `run-spec`)

> Mode A, one iteration, re-derived from the spec and the code without relying on the earlier passes. FACT 0 new gaps,
> INFERENCE 2 observations (below, not gaps of this change), REJECTED 0.

| Check | Evidence (FACT) | Result |
|-------|-----------------|--------|
| Exit sites of 3, 4, 6, 7, 8, 9 | grep of `global/scripts/lib/supervisor/*.py` (without `selftest.py`) and `global/scripts/supervisor-lock` for `return [3-9]`, `report_held`, `not_owner`, `SKILL_NOT_LOADED`, `PAUSE_REFUSED`, `sys.exit(`, `die(`: 14 sites, the same as design D2 (`report_held` gives S3a/S3b/S4a, `cloud_owned_target` the only `die(…, 3)`, every other `die` is 2, `not_owner` is 5); the entry script returns no code of its own | every site has a check |
| New checks | diff adds N1–N4 (six labels) next to their sites, additions only | met |
| Mutations | `evidence/mutations.md`: 14 rows, each with its own `FAIL` labels; batch `FAIL` counts add up (17 = 3+2+2+2+8, 9 = 1+1+3+3+1, 9 = 3+2+2+2); `ok + FAIL` = 652 per batch | met (not rerun here) |
| Scope | `git diff --stat origin/main -- global/ scripts/` (origin/main = 182c084): only `selftest.py` (+32) and `test_supervisor_lock.py` (floor 558/557 → 564/563); the only removed line is the old floor | met |
| Non-goals | proposal Non-goals: the private `supervisa-sesiones` skill text is not touched; nothing under `global/skills/` in the diff | met |
| Gates | `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock.SelfTestTest` exit 0 (3 tests, about 5 min, temp `HOME`); `python3 scripts/validate-toolkit.py` exit 0; `openspec validate supervisor-exit-code-probes --strict` exit 0; `python3 scripts/privacy-check.py` exit 0 (0 findings, untracked files included) | met |

Observations (INFERENCE, outside the scope; recorded, not counted):

- The `ok` floor of the piece test (564/563) sits well below the measured count (652), so it catches the loss of many checks,
  not of one. The spec asks only for "previous floor plus N", which holds; tightening the floor would change an existing check.
- S3e has two messages in one statement (`CLOUD-UNAVAILABLE` or `CLOUD-UNKNOWN`, both exit 3); N3 reaches the `CLOUD-UNKNOWN`
  one. The exit code of the statement is pinned by the S3e mutation, which is what R-SITE requires.

Pending count: 0 FACT gaps open after the confirm review.

Gaps pending (mejora + apply): 0
