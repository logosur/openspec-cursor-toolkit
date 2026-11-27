# Tasks — cloud-per-test-and-backlog-ref

Requirement references: **CP** = `specs/cloud-per-test-results/spec.md`, **BI** = `specs/backlog-integration-branch/spec.md`.
Design decisions: **D1**–**D6**.

## 1. Runner kit (D1–D4)

- [x] 1.1 `cloud_tests_kit.py`: `install`, `run`, `collect`; timeout by process group (CP: one process).
- [x] 1.2 pytest plugin with `pytest11` entry point; controller-only TSV (CP: pytest results).
- [x] 1.3 Node preload for the jest CLI; JSON → TSV (CP: jest results).
- [x] 1.4 JUnit fallback (CP: JUnit fallback).
- [x] 1.5 Unit tests: plugin hooks with fake reports, a real pytest run when pytest is available, the preload with a
      fake jest bin, conversion, timeout.

## 2. Brief v3 (D1, D5)

- [x] 2.1 Brief embeds the kit; steps use `kit.py run`; `brief_sha` retires old runners (CP: old runners retire).
- [x] 2.2 cloud-tests self-test and tests updated.

## 3. Backlog (D6)

- [x] 3.1 Integration ref, ancestor check, read from the ref with archive filter, working-tree additions (BI).
- [x] 3.2 Self-test cases: lagging checkout, archived in ref, worktree-only, up-to-date checkout unchanged.

## 4. Publish and verify

- [x] 4.1 PR develop→main, CI read once, merge, develop synced; install, drift, skill-lint.
- [x] 4.2 `supervisor-lock backlog` in the toolkit's main checkout lists the changes of `origin/main`.
- [x] 4.3 A natural cloud run after install lists tests with `cloud-tests result <run> --tests` (jest, 2300 lines).

## 5. Found in the first real runs

- [x] 5.1 The JUnit fallback reaches Gradle results (`<dir>/<module>/build/test-results/<task>/`): depth 7.
- [x] 5.2 A pump started before an install re-executes itself when the script is replaced, so it never dispatches
      runs to a runner of the previous brief.
- [x] 5.3 vitest: JSON reporter from the preload when the command sets none (D3b); real vitest 5 checked locally.
- [x] 5.4 A natural pytest run in the cloud lists its tests (13800 lines, in a project whose suite replaces PYTEST_ADDOPTS).
