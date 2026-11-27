# Proposal — cloud-per-test-and-backlog-ref

> **Created by:** `/prepara-tarea cloud-per-test-and-backlog-ref` — 2026-11-27
> **Status:** ordered by the global configuration session on 2026-11-27 (what to close is fixed; how is decided here).
> **Related:** `heavy-job-batch-and-orphan-gaps` (archived; it introduced the per-test file), `global-claude-toolkit`.

## Why

1. **Per-test results never appear in real runs.** FACT: after `heavy-job-batch-and-orphan-gaps` was installed, the 8
   real cloud runs of three projects (two with pytest, one with jest) all reported «no per-test result (no JUnit file
   produced)». The brief (v2) told the runner to `export PYTEST_ADDOPTS=--junitxml=…` in one step and run the command
   in another, but a cloud session's environment does not survive between its tool calls. In addition, one project's
   suite script replaces `PYTEST_ADDOPTS` with its own value, another passes its own `--junitxml` on the command line,
   and jest has no built-in JUnit reporter.
2. **The supervisor's backlog is blind when the main checkout lags.** FACT: `backlog_items` reads
   `openspec/changes/*/tasks.md` from the checkout's working tree. The toolkit's main checkout sits on an old `develop`
   (143 commits behind `origin/main`) with another session's uncommitted files, so the supervisor sees 2 changes with
   open tasks and misses 6 that `origin/main` has. Work ordered by the developer is never picked up.

## What Changes

- **cloud-tests runner kit** (`global/scripts/lib/cloud_tests_kit.py`): one stdlib script that the brief embeds
  verbatim and the runner writes once. `kit.py run <request.json>` runs the command in a single process with the
  hooks set in its environment, enforces `timeout_min`, writes the log and timing, collects per-test results and
  writes `<run>.result.json`. The hooks do not depend on `PYTEST_ADDOPTS`:
  - pytest: a plugin found through a `pytest11` entry point of a `.dist-info` folder on `PYTHONPATH`; it records the
    outcome of every test from the run reports (xdist workers included) and writes a TSV at the end of the session;
  - jest: a `NODE_OPTIONS=--require` preload that, only in the jest CLI process, appends `--json --outputFile=…`
    unless the command already sets them;
  - fallback: JUnit XML files written during the run (the request's `junit`, or any `*.xml` with `<testsuite` under
    the checkout, `/tmp` or `~/.cache`), used only when the hooks recorded nothing.
- **Brief v3:** run the request through the kit; one run, one process; runners on an older brief or kit (`kit_sha`) are retired.
- **Backlog from the integration branch:** when the checkout does not contain its integration branch (`origin/HEAD`,
  else local `main` or `master`), the changes are read from that branch with `git` (no network) and the working tree
  only adds changes the branch neither has nor archived. A checkout that contains its integration branch is read as
  before.

## Impact

- `global/scripts/cloud-tests`, new `global/scripts/lib/cloud_tests_kit.py`, `global/scripts/lib/supervisor/backlog.py`,
  their tests and the supervisor-lock self-test. No project repository is touched; no recipe has to change.
- Vitest and other runners keep the JUnit fallback only.
