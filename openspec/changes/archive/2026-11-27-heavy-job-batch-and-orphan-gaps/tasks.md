# Tasks — heavy-job-batch-and-orphan-gaps

Requirement references: **HS** = `specs/heavy-job-semaphore-gaps/spec.md`. Design decisions: **D1**–**D6**.

## 1. Classifier (D1–D3)

- [x] 1.1 More than 5 explicit test files is heavy (HS: many explicit test files).
- [x] 1.2 Loop depth and batchers (`xargs`, `parallel`, `find -exec`) (HS: runner in a loop or a batcher).
- [x] 1.3 Script reading with line variables and self-gating; `classify_process` for `scan` (HS: executed script).
- [x] 1.4 `local_commands` of the cloud recipe (HS: project-declared heavy commands).
- [x] 1.5 Unit tests for every scenario, with sanitised copies of the real batch scripts.

## 2. Gate (D1)

- [x] 2.1 `light_test_files` in the classifier; `series.json` in the gate; `series_max_files`, `series_window_min` in
      `global/config/heavy-job.json` (HS: series of light batches).
- [x] 2.2 Tests for the series scenarios; contract probe still green.

## 3. heavy-job orphans (D4)

- [x] 3.1 Mark in env, lock and json (HS: mark).
- [x] 3.2 Sweep at the end of `run`; `KillMode=control-group` (HS: no descendant outlives).
- [x] 3.3 Orphans in `scan`/`status`, previous-version rule, admission thresholds (HS: orphans).
- [x] 3.4 Tests for every scenario (real processes in a temporary state dir).

## 4. cloud-tests (D5)

- [x] 4.1 Brief v2, `brief_version` on the runner, older runners not reused.
- [x] 4.2 `result --tests [--grep]`; self-test or unit tests with a local origin.

## 5. Texts (D6)

- [x] 5.1 `global/rules/trabajos-pesados.md`, supervision references and `cambios.md`, `verifica-tarea` (both trees).
- [x] 5.2 Port to the machine override (rules, rules-detail, skill references, tests copies).

## 6. Close

- [x] 6.1 Privacy check, validator, piece tests (through heavy-job, detached). Evidence (2026-11-27): the piece tests were verified through CI, not locally: the local detached `heavy-job` run was stopped while it was still queued, and CI ran the same tests. CI run 45952297396 (pull request) and CI run 45953485219 (main) are green; `python3 scripts/privacy-check.py --range e8d02f3..390d733 --require-private` reports 0 findings.
- [x] 6.2 PR develop→main, merge, sync develop, install, drift, skill-lint. Evidence (2026-11-27): PR #33 merged (`8caf574`); installed; `drift` in sync; `supervisor-lock skill-lint` ok.
- [x] 6.3 Live check: an orphan of a test job is listed by `scan`; a series of batches is denied. Evidence (2026-11-27, installed copy): a job whose command started a detached server process that closed its file descriptors and exited was run, its wrapper was killed with SIGKILL, and after the job command ended both `heavy-job scan` and `heavy-job status` listed the surviving server as an orphan of a finished job with its `kill <PID>` hint, marked small and quiet (listed, not counted against a slot); after that one process was stopped, `scan` reported nothing and every slot of that group was free. The run used the light pool because the tests pool had no free slot, and the orphan code path is the same for both pools; the case of a busy orphan taking a slot was not run live and rests on the unit test `test_busy_orphan_counts_in_admission`. A job whose process tree still holds its slot is alive even when its wrapper is killed (design decision D4, unit test `test_child_still_holding_the_slot_keeps_the_job_alive`). The "series of batches is denied" half was re-checked with `heavy-job classify`: six test files in one call and a runner in a loop over a glob both classify as heavy.
