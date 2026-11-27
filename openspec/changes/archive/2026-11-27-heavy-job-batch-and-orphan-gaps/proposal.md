# Proposal — heavy-job-batch-and-orphan-gaps

> **Created by:** `/prepara-tarea heavy-job-batch-and-orphan-gaps` — 2026-11-27
> **Status:** ordered by the developer after a machine saturation (what to close is fixed; how is decided here).
> **Related:** `global-claude-toolkit` (heavy-job, cloud-tests and the supervision skill come from it).

## Why

FACT (machine diagnosis of 2026-11-27, kept outside the repository): the laptop reached a load of 70-119 on 8 threads
with 8-16 GB of swap, and the desktop app hung twice in one hour. The machine-wide semaphore `heavy-job` only counted
one job; most of the load came through four holes:

1. **Suites cut into batches.** The classifier calls light a test run with explicit files, a small directory or a
   path in a variable. Agents ran whole suites as a series of 5-file batches, from a shell loop inside a script they
   wrote to the scratchpad and launched with `nohup setsid`, or as six explicit end-to-end spec files in one call.
   Each batch was "light"; the series was a full suite outside the semaphore.
2. **Orphans of finished jobs.** A detached ML job ended (code 143) while a server it had started kept running for
   28 minutes with 3.4 GB of RAM, reparented to the user's systemd. `scan` skips every process whose environment has
   `HEAVY_JOB_SLOT`, so it was invisible to `status` and `scan`, and admission took its slots for free.
3. **Cloud runs not used as evidence.** The supervision text does not say that a set of batches adding up to a suite
   is a suite (cloud), that no brief may forbid `cloud-tests` to an agent, or that a green cloud run for the same
   commit is cited instead of rerun. `cloud-tests result` only gives a summary, the failures and a log tail, so a
   verifier cannot point at a scenario's test and reruns the suite locally.
4. **Project-specific heavy targets.** A project's CPU-heavy check (a `make` target running a Python module for 25-30
   minutes) is light for the classifier, and nothing lets the project declare it.

## What Changes

- **heavy-job classifier:** a test run naming more than 5 test files is heavy; a test runner inside a shell loop
  (`for`, `while`, `until`) or under `xargs`, `parallel` or `find -exec` is heavy; a shell script that is executed
  (`./x.sh`, `bash x.sh`, `nohup setsid $DIR/x.sh` with `DIR` assigned earlier in the line) is read, bounded, and is
  heavy when its own commands are, unless it really runs `heavy-job run|hold` itself; a command the project lists in
  `local_commands` of its cloud recipe (`.claude/cloud-tests.json`) is heavy.
- **heavy-job-gate:** remembers, per session and checkout, the distinct test files run outside the semaphore in a
  window, and denies the run that takes the series above a threshold (default 10 files in 60 minutes): a suite cut in
  batches is one heavy job.
- **heavy-job jobs carry a mark:** `HEAVY_JOB_ID`, `HEAVY_JOB_OWNER` (pid and start time of the wrapper) and
  `HEAVY_JOB_STATE` (its pool directory) in the environment of every process of the job, and the id in the slot lock.
- **No descendant outlives its job:** when `run` (plain or detached) ends or is stopped, every process with the job's
  mark is sent SIGTERM and, after a grace period, SIGKILL. A detached job under systemd runs with
  `KillMode=control-group`.
- **`scan` and `status` list orphans:** a process with the mark of a job that is no longer alive (or, for jobs of the
  previous version, a process whose slot is free or held by a later job) is shown as HUÉRFANO with `kill <PID>`.
  Orphans with real weight (RSS or CPU above a threshold) count as unwrapped jobs in admission, so their slots are not
  given away.
- **cloud-tests:** a runner brief version 2 (runners on an older brief are replaced) publishes the per-test outcome
  (`runs/<run>.tests.tsv`, from a JUnit file) next to the result; `cloud-tests result RUN --tests [--grep RE]` prints
  it.
- **Texts:** the heavy-jobs rule, the supervision reference (round: `heavy-job scan` and cleanup by PID of orphans
  whose owner ended; cloud runs as evidence; batches that add up to a suite go to the cloud; no brief forbids
  `cloud-tests`), the `cambios.md` log and `verifica-tarea` (cite the per-test cloud result).

## Capabilities

- New: `heavy-job-semaphore-gaps` (this delta).

## Impact

- `global/scripts/heavy-job`, `global/scripts/lib/heavy_job_classifier.py`, `global/hooks/heavy-job-gate`,
  `global/config/heavy-job.json`, `global/scripts/cloud-tests`, their tests under `scripts/toolkit/tests/pieces/`,
  their contracts, `global/rules/trabajos-pesados.md`, `global/skills/supervisa-sesiones/reference/*`, and the
  `verifica-tarea` skill (`.claude/` and `.cursor/`).
- Cost: a build that used to leave a Gradle daemon or an emulator child alive for the next build now loses it when the
  job ends (D4). The hook reads small script files and one JSON recipe per call (bounded, D2).
- Out of scope: changing any consuming project's repository (its recipe or Makefile); a project can declare its heavy
  targets itself (D3).
