"""Tests for global/scripts/lib/cloud_tests_kit.py, the kit the cloud runner writes from its brief.

The pytest plugin is driven with fake reports (and with a real pytest when one is importable); the node preload with
a fake jest bin when node exists. Everything runs in temporary folders.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest

from scripts.toolkit.paths import REPO_ROOT

KIT = str(REPO_ROOT / 'global/scripts/lib/cloud_tests_kit.py')


def load_kit():
    spec = importlib.util.spec_from_file_location('cloud_tests_kit_under_test', KIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_pytest():
    return importlib.util.find_spec('pytest') is not None


class KitCase(unittest.TestCase):
    def setUp(self):
        self.kit = load_kit()
        self.dir = tempfile.mkdtemp(prefix='cloud-tests-kit-')
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        return path

    @staticmethod
    def read(path):
        with open(path, encoding='utf-8') as fh:
            return fh.read()


class PluginTest(KitCase):
    def plugin(self):
        ns = {}
        exec(compile(self.kit.PYTEST_PLUGIN, 'cloud_tests_pytest.py', 'exec'), ns)
        return ns

    @staticmethod
    def report(nodeid, when, outcome):
        return types.SimpleNamespace(nodeid=nodeid, when=when, failed=outcome == 'failed',
                                     skipped=outcome == 'skipped', passed=outcome == 'passed')

    def test_one_outcome_per_test(self):
        ns = self.plugin()
        rec = ns['_Recorder']()
        for args in (('t::ok', 'setup', 'passed'), ('t::ok', 'call', 'passed'), ('t::ok', 'teardown', 'passed'),
                     ('t::bad', 'call', 'failed'), ('t::fix', 'setup', 'failed'), ('t::skip', 'setup', 'skipped'),
                     ('t::td', 'call', 'passed'), ('t::td', 'teardown', 'failed'), ('t::x', 'call', 'skipped')):
            rec.pytest_runtest_logreport(self.report(*args))
        self.assertEqual(rec.out, {'t::ok': 'passed', 't::bad': 'failed', 't::fix': 'error', 't::skip': 'skipped',
                                   't::td': 'error', 't::x': 'skipped'})
        os.environ['CLOUD_TESTS_RESULTS_DIR'] = self.dir
        self.addCleanup(os.environ.pop, 'CLOUD_TESTS_RESULTS_DIR', None)
        rec.pytest_sessionfinish(None)
        files = [n for n in os.listdir(self.dir) if n.startswith('pytest-')]
        self.assertEqual(len(files), 1)
        self.assertIn('error\tt::fix', self.read(os.path.join(self.dir, files[0])))

    def test_only_the_outermost_session_records(self):
        ns = self.plugin()
        registered = []
        manager = types.SimpleNamespace(register=lambda plugin, name: registered.append(name))
        self.addCleanup(os.environ.pop, 'CLOUD_TESTS_PYTEST_ACTIVE', None)
        self.addCleanup(os.environ.pop, 'CLOUD_TESTS_RESULTS_DIR', None)
        os.environ.pop('CLOUD_TESTS_PYTEST_ACTIVE', None)
        os.environ.pop('CLOUD_TESTS_RESULTS_DIR', None)
        ns['pytest_configure'](types.SimpleNamespace(pluginmanager=manager))
        self.assertEqual(registered, [])                      # no results folder: nothing
        os.environ['CLOUD_TESTS_RESULTS_DIR'] = self.dir
        ns['pytest_configure'](types.SimpleNamespace(pluginmanager=manager, workerinput={}))
        self.assertEqual(registered, [])                      # an xdist worker: nothing
        outer = types.SimpleNamespace(pluginmanager=manager)
        ns['pytest_configure'](outer)
        inner = types.SimpleNamespace(pluginmanager=manager)
        ns['pytest_configure'](inner)                         # a pytest inside a test: nothing
        self.assertEqual(registered, ['cloud_tests_recorder'])
        ns['pytest_unconfigure'](inner)
        self.assertTrue(os.environ.get('CLOUD_TESTS_PYTEST_ACTIVE'))
        ns['pytest_unconfigure'](outer)
        self.assertIsNone(os.environ.get('CLOUD_TESTS_PYTEST_ACTIVE'))

    @unittest.skipUnless(has_pytest(), 'pytest is not importable here')
    def test_real_pytest_with_its_own_addopts_and_junitxml(self):
        proj = os.path.join(self.dir, 'proj')
        source = ['import pytest', '', '@pytest.fixture', 'def broken():', '    raise RuntimeError()', '',
                  'def test_ok(): pass', 'def test_bad(): assert 0', 'def test_err(broken): pass', '']
        self.write('proj/tests/test_a.py', '\n'.join(source))
        req = self.write('req.json', json.dumps({
            'run': 'r1', 'timeout_min': 2,
            'command': f'PYTEST_ADDOPTS=-q {sys.executable} -m pytest tests -p no:cacheprovider --junitxml=/dev/null'}))
        tmp = os.path.join(self.dir, 'tmp')
        os.makedirs(tmp)
        out = subprocess.run([sys.executable, KIT, 'run', req], cwd=proj, capture_output=True, text=True,
                             env=dict(os.environ, CLOUD_TESTS_KIT_TMP=tmp), timeout=120)
        result = json.loads(out.stdout.splitlines()[-1])
        self.assertEqual(result['tests_counts'], {'passed': 1, 'failed': 1, 'error': 1, 'skipped': 0}, out.stderr)
        self.assertEqual(result['tests_source'], 'hooks')


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class NodePreloadTest(KitCase):
    def run_node(self, script, *args):
        hooks = self.kit.install(os.path.join(self.dir, 'hooks'))
        env = self.kit.hook_env(os.environ, hooks, os.path.join(self.dir, 'results'))
        out = subprocess.run(['node', script, *args], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_jest_cli_gets_json_output(self):
        jest = self.write('node_modules/jest/bin/jest.js', 'console.log(JSON.stringify(process.argv.slice(2)))\n')
        args = self.run_node(jest, '--maxWorkers=3')
        self.assertEqual(args[:2], ['--maxWorkers=3', '--json'])
        self.assertTrue(args[2].startswith('--outputFile=' + os.path.join(self.dir, 'results', 'jest-')))

    def test_jest_that_already_writes_json_and_other_scripts_are_left_alone(self):
        jest = self.write('node_modules/jest-cli/bin/jest.js', 'console.log(JSON.stringify(process.argv.slice(2)))\n')
        self.assertEqual(self.run_node(jest, '--json', '--outputFile=x.json'), ['--json', '--outputFile=x.json'])
        other = self.write('node_modules/other/bin/jest-like.js', 'console.log(JSON.stringify(process.argv.slice(2)))\n')
        self.assertEqual(self.run_node(other, '-x'), ['-x'])


class CollectTest(KitCase):
    def test_jest_json_to_lines(self):
        data = {'testResults': [
            {'name': os.path.join(self.dir, 't', 'a.test.js'), 'status': 'failed', 'assertionResults': [
                {'status': 'passed', 'fullName': 'math adds'}, {'status': 'failed', 'fullName': 'math  fails'},
                {'status': 'pending', 'title': 'later'}, {'status': 'todo', 'title': 'some day'}]},
            {'name': os.path.join(self.dir, 't', 'broken.test.js'), 'status': 'failed', 'assertionResults': []}]}
        path = self.write('results/jest-1.json', json.dumps(data))
        self.assertEqual(self.kit.jest_lines(path, self.dir), [
            ('passed', 't/a.test.js > math adds'), ('failed', 't/a.test.js > math fails'),
            ('skipped', 't/a.test.js > later'), ('skipped', 't/a.test.js > some day'), ('error', 't/broken.test.js')])

    JUNIT = ('<?xml version="1.0"?><testsuites><testsuite name="s"><testcase classname="t.a" name="ok"/>'
             '<testcase classname="t.a" name="bad"><failure/></testcase><testcase classname="t.a" name="sk"><skipped/>'
             '</testcase><testcase classname="t.a" name="err"><error/></testcase></testsuite></testsuites>')

    def test_junit_fallback_only_without_hook_results(self):
        since = time.time() - 1
        cache = os.path.join(self.dir, 'home', '.cache', 'proj')
        self.write('home/.cache/proj/junit.xml', self.JUNIT)
        self.write('home/.cache/proj/other.xml', '<config/>')
        lines, source = self.kit.collect(os.path.join(self.dir, 'results'), since, self.dir,
                                         roots=[os.path.join(self.dir, 'home')])
        self.assertEqual(source, 'junit')
        self.assertEqual(self.kit.counts_of(lines), {'passed': 1, 'failed': 1, 'error': 1, 'skipped': 1})
        self.assertTrue(os.path.isdir(cache))
        old = os.path.join(cache, 'junit.xml')
        os.utime(old, (since - 100, since - 100))           # written before the run: ignored
        self.assertEqual(self.kit.collect(os.path.join(self.dir, 'results'), since, self.dir,
                                          roots=[os.path.join(self.dir, 'home')]), ([], None))
        os.utime(old, None)
        self.write('results/pytest-1-1.tsv', 'passed\tt::x\nbogus\n')
        lines, source = self.kit.collect(os.path.join(self.dir, 'results'), since, self.dir,
                                         roots=[os.path.join(self.dir, 'home')])
        self.assertEqual((lines, source), ([('passed', 't::x')], 'hooks'))

    def test_gradle_results_five_levels_down_are_found(self):
        self.write('android/quick-actions/build/test-results/testDebugUnitTest/TEST-a.xml', self.JUNIT)
        lines, source = self.kit.collect(os.path.join(self.dir, 'results'), time.time() - 5, self.dir,
                                         roots=[self.dir])
        self.assertEqual((len(lines), source), (4, 'junit'))

    def test_request_junit_path_is_read_from_the_checkout(self):
        self.write('out/j.xml', self.JUNIT)
        lines, source = self.kit.collect(os.path.join(self.dir, 'results'), time.time(), self.dir, junit='out/j.xml')
        self.assertEqual((len(lines), source), (4, 'junit'))


class RunTest(KitCase):
    def run_kit(self, command, timeout_min=1):
        tmp = os.path.join(self.dir, 'tmp')
        os.makedirs(tmp, exist_ok=True)
        req = self.write('req.json', json.dumps({'run': 'rr', 'command': command, 'timeout_min': timeout_min}))
        out = subprocess.run([sys.executable, KIT, 'run', req], cwd=self.dir, capture_output=True, text=True,
                             env=dict(os.environ, CLOUD_TESTS_KIT_TMP=tmp), timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout.splitlines()[-1])
        with open(os.path.join(tmp, 'rr.result.json')) as fh:
            self.assertEqual(json.load(fh), result)
        return result, tmp

    def test_exit_code_log_and_environment_in_one_process(self):
        result, tmp = self.run_kit('echo "dir=$CLOUD_TESTS_RESULTS_DIR"; echo "pp=$PYTHONPATH"; '
                                   'echo "no=$NODE_OPTIONS"; exit 3')
        self.assertEqual(result['exit'], 3)
        self.assertIsNone(result['tests_file'])
        log = self.read(os.path.join(tmp, 'rr.log'))
        self.assertIn('dir=' + os.path.join(tmp, 'rr.results'), log)
        self.assertIn('pp=' + os.path.join(tmp, 'rr.hooks'), log)
        self.assertIn('cloud_tests_node.js', log)
        self.assertTrue(os.path.exists(os.path.join(tmp, 'rr.hooks', 'cloud_tests_pytest-1.dist-info',
                                                    'entry_points.txt')))

    def test_timeout_stops_the_group_with_124(self):
        start = time.time()
        result, _ = self.run_kit('sleep 60 & sleep 60', timeout_min=0.02)
        self.assertEqual(result['exit'], 124)
        self.assertLess(time.time() - start, 30)

    def test_tests_file_from_hook_results(self):
        result, tmp = self.run_kit('mkdir -p "$CLOUD_TESTS_RESULTS_DIR"; '
                                   'printf "passed\\ta::b\\nfailed\\ta::c\\n" > "$CLOUD_TESTS_RESULTS_DIR/pytest-9-9.tsv"')
        self.assertEqual(result['tests_file'], 'runs/rr.tests.tsv')
        self.assertEqual(result['tests_counts'], {'passed': 1, 'failed': 1, 'error': 0, 'skipped': 0})
        self.assertEqual(self.read(os.path.join(tmp, 'rr.tests.tsv')), 'passed\ta::b\nfailed\ta::c\n')


if __name__ == '__main__':
    unittest.main()
