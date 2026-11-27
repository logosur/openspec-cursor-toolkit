#!/usr/bin/env python3
"""cloud-tests runner kit: runs one request in one process and collects its per-test results.

The cloud runner writes this file from its brief (cloud-tests embeds it verbatim) and runs:
  python3 /tmp/cloud-tests-kit.py run /tmp/<run>.request.json
It runs the request's command with `bash -c` in its own process group (stopped at timeout_min, exit 124), with the log
in /tmp/<run>.log, and hooks that record every test without touching PYTEST_ADDOPTS or the project's files:
  - pytest: a plugin found through a pytest11 entry point of a .dist-info folder put first on PYTHONPATH;
  - jest and vitest: a NODE_OPTIONS --require preload that adds JSON output to their CLI process only (vitest only
    when the command sets no reporter, since a command-line reporter replaces the configured ones);
  - otherwise, JUnit XML files written during the run.
It writes /tmp/<run>.tests.tsv (one `outcome<TAB>id` line per test: passed, failed, error, skipped) and
/tmp/<run>.result.json, and prints that JSON as its last line. Stdlib only.
"""
import json
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

MAX_LINES = 50000
TMP = os.environ.get('CLOUD_TESTS_KIT_TMP', '/tmp')
OUTCOMES = ('passed', 'failed', 'error', 'skipped')
SKIP_DIRS = {'node_modules', '.git', '.venv', 'venv', '__pycache__', '.tox', '.mypy_cache', '.pytest_cache'}

PYTEST_PLUGIN = r'''"""cloud-tests: one outcome per test, written as TSV in CLOUD_TESTS_RESULTS_DIR (outermost session only)."""
import os

_FLAG = 'CLOUD_TESTS_PYTEST_ACTIVE'
_RANK = {'passed': 0, 'skipped': 1, 'failed': 2, 'error': 3}


class _Recorder:
    def __init__(self):
        self.out = {}

    def pytest_runtest_logreport(self, report):
        if report.when == 'call':
            outcome = 'failed' if report.failed else 'skipped' if report.skipped else 'passed'
        elif report.failed:
            outcome = 'error'
        elif report.skipped:
            outcome = 'skipped'
        else:
            return
        old = self.out.get(report.nodeid)
        if old is None or _RANK[outcome] > _RANK[old]:
            self.out[report.nodeid] = outcome

    def pytest_sessionfinish(self, session):
        folder = os.environ.get('CLOUD_TESTS_RESULTS_DIR')
        if not folder or not self.out:
            return
        try:
            os.makedirs(folder, exist_ok=True)
            name = os.path.join(folder, 'pytest-%d-%d.tsv' % (os.getpid(), int(__import__('time').time() * 1000)))
            with open(name, 'w', encoding='utf-8') as fh:
                for nodeid, outcome in self.out.items():
                    fh.write(outcome + '\t' + ' '.join(nodeid.split()) + '\n')
        except OSError:
            pass


def pytest_configure(config):
    # xdist workers and pytest runs inside a test inherit the flag: only the outermost session records
    if hasattr(config, 'workerinput') or os.environ.get(_FLAG) or not os.environ.get('CLOUD_TESTS_RESULTS_DIR'):
        return
    os.environ[_FLAG] = str(os.getpid())
    config._cloud_tests_owner = True
    config.pluginmanager.register(_Recorder(), 'cloud_tests_recorder')


def pytest_unconfigure(config):
    if getattr(config, '_cloud_tests_owner', False):
        os.environ.pop(_FLAG, None)
'''

PYTEST_ENTRY_POINTS = '[pytest11]\ncloud_tests = cloud_tests_pytest\n'
PYTEST_METADATA = 'Metadata-Version: 2.1\nName: cloud-tests-pytest\nVersion: 1\n'

NODE_PRELOAD = r''''use strict';
// cloud-tests: in the jest or vitest CLI process only, write the results as JSON in CLOUD_TESTS_RESULTS_DIR. Never throws.
try {
  const fs = require('fs');
  const path = require('path');
  const dir = process.env.CLOUD_TESTS_RESULTS_DIR;
  let main = process.argv[1] || '';
  try { main = fs.realpathSync(main); } catch (e) {}
  const jest = /[\\/]jest(-cli)?[\\/]bin[\\/]jest(\.js)?$/.test(main);
  const taken = process.argv.slice(2).some(a => a === '--json' || a === '--watch' || a === '--watchAll'
    || a.startsWith('--outputFile') || a.startsWith('--watch=') || a.startsWith('--watchAll='));
  if (dir && jest && !taken) {
    fs.mkdirSync(dir, { recursive: true });
    process.argv.push('--json', '--outputFile=' + path.join(dir, 'jest-' + process.pid + '-' + Date.now() + '.json'));
  }
  // vitest: on the command line --reporter replaces the configured reporters, so only when the command sets none
  const vitest = /[\\/]vitest[\\/]vitest\.mjs$/.test(main);
  const vtaken = process.argv.slice(2).some(a => a.startsWith('--reporter') || a.startsWith('--outputFile')
    || a === '--watch' || a === '-w' || a === 'watch' || a === 'dev' || a === '--ui' || a === 'list');
  if (dir && vitest && !vtaken) {
    fs.mkdirSync(dir, { recursive: true });
    process.argv.push('--reporter=default', '--reporter=json',
      '--outputFile.json=' + path.join(dir, 'vitest-' + process.pid + '-' + Date.now() + '.json'));
  }
} catch (e) {}
'''


def install(hooks):
    """Write the pytest plugin and the node preload under `hooks`; return the folder."""
    dist = os.path.join(hooks, 'cloud_tests_pytest-1.dist-info')
    os.makedirs(dist, exist_ok=True)
    for path, text in ((os.path.join(hooks, 'cloud_tests_pytest.py'), PYTEST_PLUGIN),
                       (os.path.join(dist, 'entry_points.txt'), PYTEST_ENTRY_POINTS),
                       (os.path.join(dist, 'METADATA'), PYTEST_METADATA),
                       (os.path.join(hooks, 'cloud_tests_node.js'), NODE_PRELOAD)):
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
    return hooks


def hook_env(env, hooks, results):
    env = dict(env)
    env['CLOUD_TESTS_RESULTS_DIR'] = results
    env['PYTHONPATH'] = hooks + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    preload = '--require ' + os.path.join(hooks, 'cloud_tests_node.js')
    env['NODE_OPTIONS'] = (env.get('NODE_OPTIONS', '') + ' ' + preload).strip()
    env.pop('CLOUD_TESTS_PYTEST_ACTIVE', None)
    return env


def _clean(text):
    return ' '.join(str(text or '').split())


def tsv_lines(path):
    out = []
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                outcome, _, ident = line.rstrip('\n').partition('\t')
                if outcome in OUTCOMES and ident:
                    out.append((outcome, ident))
    except OSError:
        pass
    return out


def jest_lines(path, cwd):
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for suite in data.get('testResults') or []:
        name = suite.get('name') or suite.get('testFilePath') or '?'
        try:
            name = os.path.relpath(name, cwd) if os.path.isabs(name) else name
        except ValueError:
            pass
        cases = suite.get('assertionResults') or []
        if not cases and suite.get('status') == 'failed':
            out.append(('error', _clean(name)))  # the file failed to run: no test inside it ran
        for case in cases:
            status = case.get('status')
            outcome = 'passed' if status == 'passed' else 'failed' if status == 'failed' else 'skipped'
            out.append((outcome, _clean(name + ' > ' + (case.get('fullName') or case.get('title') or '?'))))
    return out


def junit_lines(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    out = []
    for case in root.iter('testcase'):
        kinds = [child.tag for child in case]
        outcome = ('error' if 'error' in kinds else 'failed' if 'failure' in kinds
                   else 'skipped' if 'skipped' in kinds else 'passed')
        ident = '::'.join(x for x in (case.get('classname') or case.get('file'), case.get('name')) if x)
        out.append((outcome, _clean(ident)))
    return out


def junit_candidates(roots, since, skip, limit=50, depth=7):  # Gradle: <dir>/<module>/build/test-results/<task>/
    """XML files modified at or after `since` whose root is a JUnit testsuite(s), under `roots`."""
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        base = root.rstrip(os.sep).count(os.sep)
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and os.path.join(folder, d) not in skip
                       and folder.count(os.sep) - base < depth]
            for name in files:
                if not name.endswith('.xml'):
                    continue
                path = os.path.join(folder, name)
                try:
                    if os.path.getmtime(path) < since:
                        continue
                    with open(path, 'rb') as fh:
                        head = fh.read(2048)
                except OSError:
                    continue
                if b'<testsuite' in head:
                    found.append(path)
                    if len(found) >= limit:
                        return found
    return found


def collect(results, since, cwd, junit=None, roots=None, skip=()):
    """(lines, source): the per-test lines of a run, from the hooks or else from JUnit files."""
    lines = []
    if os.path.isdir(results):
        for name in sorted(os.listdir(results)):
            path = os.path.join(results, name)
            if name.startswith('pytest-') and name.endswith('.tsv'):
                lines += tsv_lines(path)
            elif name.startswith(('jest-', 'vitest-')) and name.endswith('.json'):  # vitest's json is jest's format
                lines += jest_lines(path, cwd)
    if lines:
        return lines, 'hooks'
    if junit:
        paths = [junit if os.path.isabs(junit) else os.path.join(cwd, junit)]
    else:
        default_roots = [cwd, TMP, os.path.join(os.path.expanduser('~'), '.cache')]
        paths = junit_candidates(roots or default_roots, since, set(skip))
    for path in paths:
        lines += junit_lines(path)
    return lines, ('junit' if lines else None)


def counts_of(lines):
    counts = dict.fromkeys(OUTCOMES, 0)
    for outcome, _ in lines:
        counts[outcome] += 1
    return counts


def run_command(command, env, cwd, log_path, timeout_s):
    with open(log_path, 'wb') as log:
        proc = subprocess.Popen(['bash', '-c', command], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            for sig, grace in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
                try:
                    os.killpg(proc.pid, sig)
                except OSError:
                    pass
                try:
                    proc.wait(timeout=grace)
                    break
                except subprocess.TimeoutExpired:
                    continue
            return 124
    return 128 - code if code < 0 else code


def cmd_run(request_path):
    with open(request_path, encoding='utf-8') as fh:
        req = json.load(fh)
    rid = req['run']
    base = os.path.join(TMP, rid)
    hooks = install(base + '.hooks')
    results = base + '.results'
    os.makedirs(results, exist_ok=True)
    cwd = os.getcwd()
    timeout_s = float(req.get('timeout_min') or 60) * 60
    started = time.time()
    code = run_command(req['command'], hook_env(os.environ, hooks, results), cwd, base + '.log', timeout_s)
    finished = time.time()
    lines, source = collect(results, started, cwd, req.get('junit'), skip=(hooks, results))
    tests_file = None
    if lines:
        with open(base + '.tests.tsv', 'w', encoding='utf-8') as fh:
            fh.writelines(outcome + '\t' + ident + '\n' for outcome, ident in lines[:MAX_LINES])
        tests_file = f'runs/{rid}.tests.tsv'
    result = {'run': rid, 'exit': code, 'duration_s': int(round(finished - started)), 'cores': os.cpu_count(),
              'tests_file': tests_file, 'tests_counts': counts_of(lines) if lines else None, 'tests_source': source,
              'log': base + '.log'}
    with open(base + '.result.json', 'w', encoding='utf-8') as fh:
        json.dump(result, fh)
    print(json.dumps(result))
    return 0


def main(argv):
    if len(argv) == 2 and argv[0] == 'run':
        return cmd_run(argv[1])
    if len(argv) == 2 and argv[0] == 'install':
        print(install(argv[1]))
        return 0
    print('usage: cloud-tests-kit.py run <request.json> | install <dir>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
