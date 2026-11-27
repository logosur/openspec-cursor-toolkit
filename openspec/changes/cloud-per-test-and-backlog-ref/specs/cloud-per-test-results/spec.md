# Spec Delta — cloud-per-test-results

## Purpose

Makes the per-test result file of a cloud run appear for pytest and jest suites without any change to the projects'
recipes or repositories.

## ADDED Requirements

### Requirement: The request runs in one process with the hooks
The runner SHALL run each request through the kit script embedded in the brief, which sets the hooks' environment and
runs the command in a single process, so no environment has to survive between the runner's tool calls.

#### Scenario: Hooks reach the command
- **WHEN** the kit runs a request whose command starts a pytest session
- **THEN** the session sees the kit's plugin folder on `PYTHONPATH` and its results folder in `CLOUD_TESTS_RESULTS_DIR`

#### Scenario: Timeout
- **WHEN** the command runs longer than `timeout_min`
- **THEN** the kit stops its process group and reports exit 124

### Requirement: pytest results without PYTEST_ADDOPTS
The pytest plugin SHALL be loaded through a `pytest11` entry point on `PYTHONPATH`, and SHALL record one outcome per
test even when the project replaces `PYTEST_ADDOPTS` or passes its own `--junitxml`.

#### Scenario: Project replaces PYTEST_ADDOPTS
- **WHEN** the command runs `PYTEST_ADDOPTS=-q pytest tests/`
- **THEN** the run's TSV lists every test with passed, failed, error or skipped

#### Scenario: Failed setup
- **WHEN** a fixture fails during setup
- **THEN** the test is listed as error

### Requirement: jest results through a preload
The Node preload SHALL add `--json --outputFile` only to the jest CLI process and only when the command does not set
them; it SHALL never make a command fail.

#### Scenario: npm test runs jest
- **WHEN** the command is `npm test -- --maxWorkers=3` and the script runs jest
- **THEN** a jest JSON file is written and converted into TSV lines

#### Scenario: Other node processes
- **WHEN** node runs any other script
- **THEN** its arguments are unchanged

### Requirement: JUnit fallback
When the hooks recorded nothing, the kit SHALL convert JUnit XML files written during the run.

#### Scenario: Suite writes its own JUnit under the cache
- **WHEN** pytest plugin autoload is disabled and the suite writes `~/.cache/x/junit.xml`
- **THEN** the TSV comes from that file

### Requirement: Old runners retire with the brief
A runner SHALL be reused only when it was started with the same brief version and kit digest.

#### Scenario: Kit changed
- **WHEN** the kit's digest differs from the one a runner was started with
- **THEN** the next request starts a new runner
