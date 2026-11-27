# Design — heavy-job-batch-and-orphan-gaps

## D1. Batches are caught in three places, because each hole has a different shape

- **Command text (classifier, pure):** more than `MAX_LIGHT_TEST_FILES` (5) distinct explicit test files is heavy; a
  test runner inside a loop body or under `xargs`/`parallel`/`find -exec` is heavy whatever its operands (the operand
  is an expansion that walks the suite). Loop depth is tracked over the simple commands of the line: a command whose
  first word is `for`, `while` or `until` opens one, `done` closes it.
- **Script content (classifier, bounded read):** an executed script is read when it is a regular file of at most
  256 KiB whose first line is a shell shebang or that a shell interpreter runs; its text is classified with the same
  rules (depth-limited). Variables assigned earlier in the same line (`S=…; nohup setsid $S/x.sh`) and `~`/`$HOME`
  are expanded for the path only. A script that really runs `heavy-job run|hold` is self-gated and not judged, so a
  project script that re-executes itself under the semaphore keeps working. The same reading serves `scan`, the only
  net when the path never reaches the hook (a script written with the Write tool, a path built at run time).
- **Series (hook, stateful):** the gate keeps `series.json` in its state dir: per `session_id` and checkout (git top
  level of the cwd, else the cwd) the distinct test files run outside the semaphore with their time. A run that takes
  the distinct count above `series_max_files` (10) within `series_window_min` (60) is denied as heavy. Distinct files,
  not invocations, so repeating the same test while fixing it never trips it. A denied run is not recorded. The state
  is pruned on every write and never blocks: any error fails open.

## D2. Costs of reading files in the hook

At most one script read per simple command (256 KiB), depth 8 as for `bash -c`, and one recipe JSON per call (git top
level found by walking up at most 20 directories). No `/proc` walk in the hook.

## D3. Project-declared heavy commands

`local_commands` of `.claude/cloud-tests.json` already lists the local equivalents of a cloud suite. The classifier
treats a simple command whose argv equals one of them (leading `VAR=value` dropped on both sides) as `gate`. A project
whose heavy target is not recognised declares it there; the toolkit does not guess from target names (`*-check` is
light in many projects).

## D4. Orphans: one mark, three launches

- The mark is the environment (`HEAVY_JOB_ID`, `HEAVY_JOB_OWNER=<pid>:<starttime>`, `HEAVY_JOB_STATE=<pool dir>`):
  inherited by every descendant, also those that close their file descriptors (Python's `subprocess` does by default,
  so the slot lock fd is not a reliable mark) and those reparented by `setsid`/`nohup`.
- The id is also written in the slot lock file when the slots are claimed (`<pid> <time> <id>`), so "the job is
  alive" is: its owner is alive (pid and start time match, no pid reuse), or a slot of its pool is held and its lock
  names the id (the wrapper was SIGKILLed but the job's tree still holds the slot). `HEAVY_JOB_STATE` keeps a test's
  temporary state dir from making the real machine's processes look orphaned and the other way round.
- **Previous version:** a process with `HEAVY_JOB_SLOT`/`HEAVY_JOB_LIGHT_SLOT` and no `HEAVY_JOB_ID` is an orphan when
  every slot it names is free, or held by a holder that took it after the process started (it belonged to an earlier
  job). Jobs running at install time keep their slots and are not orphans.
- **Cleanup at the end:** `run` (plain and the detached runner, which runs `run` in-process) sweeps the processes with
  its id after the child exits or is stopped: SIGTERM, up to `reap_grace_s` (10 s), SIGKILL. Under systemd the
  detached unit runs with `KillMode=control-group` (was `process`): a process that dropped the mark still dies with
  the unit. Cost: a Gradle daemon or an emulator child left for "the next build" dies with its job; it was the memory
  that saturated the machine. `hold` execs its command, so no sweep is possible there; its orphans are found by `scan`.
- **Admission:** an orphan group (one job id) counts as one unwrapped job of its pool (weight: the number of slots in
  its `HEAVY_JOB_SLOT`) only if its RSS is at least `orphan_min_rss_mib` (256) or its CPU share at least
  `orphan_min_cpu_pct` (10); a small idle one is only listed. The waiting message lists it with `kill <PID>`.
- Nothing is killed automatically outside the job's own sweep. `process-kill-gate` lets an explicit PID through, so
  the cleanup by PID that `scan` prints is the supervisor's.

## D5. Per-test cloud results

- Brief version 2: before the command the runner exports `CLOUD_TESTS_JUNIT=/tmp/<run>.junit.xml` and, so pytest
  writes it with no change to the recipe, appends `--junitxml=$CLOUD_TESTS_JUNIT` to `PYTEST_ADDOPTS`. A suite may
  name its own JUnit file (`junit`, relative to the checkout) for other runners. After the run, the JUnit file becomes
  `runs/<run>.tests.tsv` (`outcome<TAB>id`, at most 50 000 lines; outcome passed/failed/error/skipped) and the result
  JSON gets `tests_file` and `tests_counts`; without JUnit, `tests_file` is null and `summary` says so.
- A runner launched with an older brief is not reused: the next dispatch launches a fresh one (the old one is retired
  by `sweep` as replaced). Runners record `brief_version`.
- `cloud-tests result RUN --tests [--grep RE]` fetches the results branch and prints the per-test lines (exit 3 if the
  run has none). The JSON result is unchanged otherwise.
- Not verified live by this change: only the offline self-test (fake `claude`, local origin) runs here.

## D6. Texts

The toolkit has no `tests-en-la-nube.md`: its neutral supervision text about cloud tests is
`reference/piezas-opcionales.md`, and the round is in `reference/f1-f4.md` or the vigilance reference. Machine-specific
wording (names of projects) goes only to the private override.
