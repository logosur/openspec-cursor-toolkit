# Design — cloud-per-test-and-backlog-ref

## D1. One process runs the request (kit `run`)
The cause of the missing files is that the runner's tool calls do not share an environment. Instead of more
instructions, the brief hands the runner one script: `python3 /tmp/cloud-tests-kit.py run /tmp/<run>.request.json`.
It sets the hooks' environment, runs `bash -c <command>` in its own process group with the log in `/tmp/<run>.log`,
kills the group at `timeout_min` (exit 124), then collects. Its last line on stdout and `/tmp/<run>.result.json` carry
`exit`, `duration_s`, `cores`, `tests_file` and `tests_counts`. The runner still writes the summary, failures and
publishes, as in v2. Long runs: the runner starts it with `nohup … &` and waits for the result file.

## D2. pytest without PYTEST_ADDOPTS
Rejected: `PYTEST_ADDOPTS` (projects replace it), `PYTEST_PLUGINS` (if a project resets `PYTHONPATH` but keeps the
variable, pytest fails to import the plugin and the suite breaks), `sitecustomize` (shadows a project's own).
Chosen: a folder on `PYTHONPATH` holding `cloud_tests_pytest.py` and `cloud_tests_pytest-1.dist-info/` with a
`pytest11` entry point. pytest auto-loads it; if a project resets `PYTHONPATH`, both disappear together and nothing
breaks. `PYTEST_DISABLE_PLUGIN_AUTOLOAD` disables it (fallback D4). The plugin keeps one outcome per node id from
`pytest_runtest_logreport` (error for a failed setup or teardown, failed for a failed call, skipped, passed for a
passed call) and appends a TSV at `pytest_sessionfinish`, only in the controller (not in xdist workers). Several
pytest sessions in one command each write their own file.

## D3. jest through a Node preload
`NODE_OPTIONS=--require <dir>/cloud_tests_node.js` (appended to an existing value). In the process whose main script
resolves to `jest/bin/jest.js` or `jest-cli/bin/jest.js`, and only when the arguments have no `--json`,
`--outputFile`, `--watch` or `--watchAll`, it appends `--json --outputFile=<dir>/jest-<pid>.json`. Any error is
swallowed: the preload can never break a command. The kit converts `testResults[].assertionResults[]`
(`passed`, `failed`, `pending`/`skipped`/`todo` → skipped) to TSV lines `outcome<TAB>file › full name`.

## D4. JUnit fallback
Only when D2 and D3 recorded nothing: the request's `junit` file, else XML files modified after the start under the
checkout, `/tmp` and `~/.cache` (depth-limited, at most 50 files read) whose root is `testsuite(s)`.

## D5. Runner retirement by kit digest
`brief_version` becomes 3 and the runner record also keeps `kit_sha` (sha256 of the kit text the brief embeds). A runner
is reused only with the same version and digest, so any later edit of the kit retires old runners without a manual
bump; `runner_usable` keeps its signature because the digest does not depend on the project. The brief announces the
digest and the runner checks the file it wrote with `sha256sum`, which catches a mistyped copy.

## D6. Backlog from the integration branch
Integration ref: `git rev-parse --abbrev-ref origin/HEAD`, else local `main`, else `master`. If the checkout is not a
repository, has no such ref, or HEAD already contains it (`merge-base --is-ancestor ref HEAD`), the working tree is read
as today (no change for up-to-date checkouts). Otherwise: changes come from `git ls-tree` / `git cat-file --batch` of the
ref; archived names are the `YYYY-MM-DD-<name>` folders of `openspec/changes/archive/` in the ref; the working tree adds
only changes whose name is neither in the ref nor archived there. No `fetch`. Any git failure falls back to the working
tree; the function never raises.
