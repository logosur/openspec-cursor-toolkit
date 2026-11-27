# Spec Delta — heavy-job-semaphore-gaps

## Purpose

Closes the holes through which heavy work escaped the machine-wide `heavy-job` semaphore: suites cut into batches,
descendants that outlive their job, and cloud results too coarse to be cited instead of a local rerun.

## ADDED Requirements

### Requirement: Many explicit test files are heavy
The classifier SHALL judge heavy (`tests`, or `e2e` for Playwright) a pytest, phpunit, jest, vitest or Playwright run
that names more than 5 distinct test files; node ids and line suffixes of the same file count once. A name filter
(`-k`, `--filter`, `-t`, `--grep`) without files stays light.

#### Scenario: Six spec files
- **WHEN** the line is `npx playwright test a.spec.ts b.spec.ts c.spec.ts d.spec.ts e.spec.ts f.spec.ts`
- **THEN** it is heavy with kind `e2e`

#### Scenario: Five files and node ids of one file
- **WHEN** the line is `pytest t1.py t2.py t3.py t4.py t5.py t1.py::test_x`
- **THEN** it is light

### Requirement: A test runner in a loop or a batcher is heavy
A test runner invoked inside a `for`, `while` or `until` body, or as the command of `xargs`, `parallel` or
`find -exec`, SHALL be heavy whatever its operands.

#### Scenario: Shell loop over batches
- **WHEN** the line is `for b in batch_*; do uv run pytest -q $(cat $b); done`
- **THEN** it is heavy with kind `tests`

#### Scenario: Arithmetic loop
- **WHEN** a line contains `for ((i=0; i<n; i+=5)); do pytest $batch; done`
- **THEN** it is heavy

#### Scenario: xargs
- **WHEN** the line is `ls tests/*.py | xargs -n 5 pytest`
- **THEN** it is heavy

#### Scenario: A single run outside a loop
- **WHEN** the line is `pytest tests/test_one.py`
- **THEN** it stays light

### Requirement: An executed script is judged by its content
When a simple command executes a script file (directly, through a shell, or behind `nohup`, `setsid` and the other
wrappers), the classifier SHALL read it if it is a regular file of at most 256 KiB that a shell runs, and SHALL judge it
heavy when one of its commands is heavy, naming the script in the reason. A script that really runs
`heavy-job run|hold` SHALL not be judged.

#### Scenario: Batches script launched detached
- **WHEN** a script holds a loop that runs pytest on batches and the line is `S=/dir; nohup setsid $S/run.sh >/dev/null 2>&1 &`
- **THEN** the line is heavy and the reason names `run.sh`

#### Scenario: Self-gated script
- **WHEN** the script runs `exec heavy-job run --kind tests -- pytest`
- **THEN** executing it is light

#### Scenario: Missing, large or binary file
- **WHEN** the path does not exist, is larger than 256 KiB or is not a shell script
- **THEN** the script is not read and the command is judged as before

### Requirement: Script paths and running scripts are resolved
To find the script, variables assigned earlier in the same line, `~` and `$HOME` SHALL be expanded. `scan` SHALL apply
the same content reading to running shell processes.

#### Scenario: Scan sees the script
- **WHEN** `bash /dir/run.sh` with such content runs without the semaphore
- **THEN** `heavy-job scan` lists it once as a `tests` job

### Requirement: Project-declared heavy commands
A simple command equal to one of the `local_commands` of the cloud recipe (`.claude/cloud-tests.json`) of the
checkout it runs in SHALL be heavy with kind `gate`, comparing argv with leading assignments dropped.

#### Scenario: Declared target
- **WHEN** the recipe lists `make slow-check` in `local_commands` and the line is `cd repo && make slow-check`
- **THEN** it is heavy with kind `gate`

#### Scenario: Undeclared target
- **WHEN** the recipe does not list it
- **THEN** `make slow-check` stays light

### Requirement: A series of light batches is one heavy job
The PreToolUse gate SHALL record, per session and checkout, the distinct test files of each light test run outside the
semaphore, and SHALL deny as heavy the run that takes the distinct files of the last `series_window_min` minutes
(default 60) above `series_max_files` (default 10). It SHALL not record a denied run, a run under `heavy-job run|hold`,
or a run of another session or checkout, and SHALL fail open on any error.

#### Scenario: Third batch of five
- **WHEN** one session runs pytest on files 1-5, then 6-10, then 11-15 in the same checkout within an hour
- **THEN** the first two pass and the third is denied with a message about a suite cut into batches

#### Scenario: Repeating the same test
- **WHEN** a session runs `pytest tests/test_a.py` twenty times in an hour
- **THEN** none is denied

#### Scenario: Another session or an old series
- **WHEN** the earlier batches were run by another session, in another checkout, or more than the window ago
- **THEN** the run is not denied

### Requirement: Every process of a job carries the job's mark
`heavy-job run` and `hold` SHALL give the job's command `HEAVY_JOB_ID` (unique), `HEAVY_JOB_OWNER` (`<pid>:<start
time>` of the process that owns the slots) and `HEAVY_JOB_STATE` (the pool's state dir), and SHALL write the id in the
slot lock file and the slot json when the slots are claimed. A detached job's id is its detached id.

#### Scenario: Mark in the environment
- **WHEN** `heavy-job run -- env` runs
- **THEN** its output has the three variables and the slot json has the same `job_id`

### Requirement: No descendant outlives its job
When the command of `heavy-job run` (plain or detached) ends or is stopped, the wrapper SHALL send SIGTERM to every
process with its `HEAVY_JOB_ID` and `HEAVY_JOB_STATE`, wait up to `reap_grace_s` (default 10) and send SIGKILL to the
survivors, and SHALL say on stderr how many it stopped. A detached job started through systemd SHALL run with
`KillMode=control-group`.

#### Scenario: Background child left behind
- **WHEN** the command is `sh -c 'sleep 300 & exit 0'`
- **THEN** when `heavy-job run` returns, the `sleep` is gone and stderr names it

#### Scenario: Detached job stopped
- **WHEN** `heavy-job stop <id>` stops a detached job whose command started a background child
- **THEN** no process with that job's mark is left

### Requirement: Orphans of finished jobs are listed
`heavy-job scan` and `status` SHALL list as an orphan (`HUÉRFANO`, with `kill <PID>`) a process with the mark of a job
of this state dir that is no longer alive (owner dead and no held slot names its id), grouped per job id with summed
RSS and CPU. A process of a live job SHALL never be an orphan.

#### Scenario: Server left by a killed wrapper
- **WHEN** the wrapper of a job is killed with SIGKILL after its child started a server that closed its file
  descriptors, and the child has exited
- **THEN** `heavy-job scan` lists the server as HUÉRFANO with `kill <its PID>`, and `status --json` counts it in
  `unwrapped`

#### Scenario: Live job
- **WHEN** a job is running under `heavy-job run`
- **THEN** none of its processes is listed as an orphan

#### Scenario: Another state dir
- **WHEN** the orphan's `HEAVY_JOB_STATE` is another directory
- **THEN** this state dir does not list it

### Requirement: Orphans of the previous version and their weight
For processes of the previous version (slot variable, no id) a process SHALL be an orphan when every slot it names is
free or held by a holder that claimed it after the process started. An orphan group with RSS of at least
`orphan_min_rss_mib` (256) or CPU share of at least `orphan_min_cpu_pct` (10) SHALL count as an unwrapped job of its
pool; a smaller one SHALL only be listed.

#### Scenario: Small idle orphan
- **WHEN** an orphan group has 20 MiB of RSS and no CPU
- **THEN** it is listed but does not reduce the free slots

#### Scenario: Previous version, slot still held by the same job
- **WHEN** a process without `HEAVY_JOB_ID` names a slot held since before the process started
- **THEN** it is not an orphan

### Requirement: Per-test cloud results
The runner brief (version 2) SHALL tell the cloud runner to produce JUnit (`CLOUD_TESTS_JUNIT`, pytest through
`PYTEST_ADDOPTS`, or the suite's `junit` path) and to publish `runs/<run>.tests.tsv` (`outcome<TAB>id`, at most 50 000
lines) beside the result, with `tests_file` and `tests_counts` in it. A runner recorded with an older brief SHALL not
receive new runs. `cloud-tests result RUN --tests [--grep RE]` SHALL print those lines (exit 3 when the run has none).

#### Scenario: Old runner
- **WHEN** the ledger's runner has no `brief_version` or a lower one and a run is dispatched
- **THEN** a new runner is launched with the current brief

#### Scenario: Per-test lines
- **WHEN** the results branch has `runs/R.tests.tsv` with `passed\ttests/test_a.py::test_x`
- **THEN** `cloud-tests result R --tests --grep test_a` prints that line

#### Scenario: No per-test file
- **WHEN** the run published no tests file
- **THEN** `cloud-tests result R --tests` exits 3 and says so

### Requirement: The texts teach the same model
The heavy-jobs rule and the supervision references SHALL say: a set of passes that adds up to a suite is a suite (cloud
when the project declares it, else one `heavy-job run`); no brief may forbid `cloud-tests` to an agent; a green cloud
run for the same commit is cited as evidence instead of a local rerun (per test with `result --tests`); the
supervisor's round runs `heavy-job scan` and stops by PID the orphans whose owner ended. `verifica-tarea` SHALL say how
to cite the per-test cloud result.

#### Scenario: Supervisor round
- **WHEN** a supervisor reads the round in its references
- **THEN** it finds `heavy-job scan` and the cleanup by PID of orphans
