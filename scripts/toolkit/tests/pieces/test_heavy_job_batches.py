"""Tests for suites cut into batches: the classifier (lib/heavy_job_classifier.py) and the gate's series.

The two batch scripts below are sanitised copies of real ones that ran a whole suite outside the semaphore.
Everything runs in temporary directories; the gate's state dir is a temporary one.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.toolkit.paths import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / 'global/scripts/lib'))
import heavy_job_classifier as C  # noqa: E402

HOOK = str(REPO_ROOT / 'global/hooks/heavy-job-gate')
SCRIPT = str(REPO_ROOT / 'global/scripts/heavy-job')

PASSES_SH = '''#!/bin/bash
cd /some/repo
S=/some/scratch
files=( $(ls tests/test_v4_*.py) )
: > $S/passes.log
for ((i=0; i<${#files[@]}; i+=5)); do
  batch="${files[@]:i:5}"
  echo "PASS $i: $batch" >> $S/passes.log
  uv run --no-sync pytest -q -m "not heavy" -p no:cacheprovider $batch 2>&1 | tail -4 >> $S/passes.log
done
echo DONE >> $S/passes.log
'''

BATCHES_SH = '''#!/bin/bash
cd /some/repo
for b in /some/scratch/batch_*; do
  n=$(basename $b)
  echo "START $n $(date +%T)" >> /some/scratch/progress.log
  uv run --no-sync pytest -q -p no:cacheprovider $(cat $b | tr '\\n' ' ') > /some/scratch/$n.log 2>&1
  echo "END $n exit=$? $(date +%T)" >> /some/scratch/progress.log
done
'''

SELF_GATED_SH = '''#!/bin/bash
[ -n "$HEAVY_JOB_SLOT" ] || exec heavy-job run --kind tests -- "$0" "$@"
pytest
'''


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='heavy-job-batches-')
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, name, text, mode=0o755):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as handle:
            handle.write(text)
        os.chmod(path, mode)
        return path

    def kind(self, command):
        result = C.classify_outside_semaphore(command, self.root)
        return result[0] if result else None


class ManyFilesTest(TempDirTest):
    def test_six_spec_files_are_heavy(self):
        cmd = 'npx playwright test ' + ' '.join(f'e2e/{c}.spec.ts' for c in 'abcdef')
        self.assertEqual(self.kind(cmd), 'e2e')

    def test_five_files_and_a_node_id_of_one_are_light(self):
        self.assertIsNone(self.kind('pytest t1.py t2.py t3.py t4.py t5.py t1.py::test_x'))

    def test_six_python_files_are_heavy(self):
        self.assertEqual(self.kind('uv run pytest ' + ' '.join(f't{i}.py' for i in range(6))), 'tests')

    def test_glob_counts_its_files(self):
        for i in range(7):
            self.write(f'tests/test_v{i}.py', '')
        self.assertEqual(self.kind('pytest tests/test_v*.py'), 'tests')

    def test_six_phpunit_files_are_heavy_and_a_filter_stays_light(self):
        self.assertEqual(self.kind('vendor/bin/phpunit ' + ' '.join(f'T{i}Test.php' for i in range(6))), 'tests')
        self.assertIsNone(self.kind('vendor/bin/phpunit --filter testFoo'))


class LoopTest(TempDirTest):
    def test_loop_over_batches(self):
        self.assertEqual(self.kind('for b in batch_*; do uv run pytest -q $(cat $b); done'), 'tests')

    def test_arithmetic_loop(self):
        self.assertEqual(self.kind('for ((i=0; i<n; i+=5)); do pytest $batch; done'), 'tests')

    def test_while_read(self):
        self.assertEqual(self.kind('while read f; do pytest "$f"; done < list.txt'), 'tests')

    def test_batchers(self):
        self.assertEqual(self.kind('ls tests/*.py | xargs -n 5 pytest'), 'tests')
        self.assertEqual(self.kind('find tests -name "test_*.py" -exec pytest {} +'), 'tests')
        self.assertEqual(self.kind('parallel -j4 pytest ::: a.py b.py'), 'tests')

    def test_small_literal_loops_stay_light(self):
        self.assertIsNone(self.kind('for f in a_test.py b_test.py; do pytest $f; done'))
        self.assertIsNone(self.kind('for g in REQ-1 REQ-2; do phpunit --group $g; done'))

    def test_a_single_run_after_a_loop_is_light(self):
        self.assertIsNone(self.kind('for x in 1 2; do echo $x; done; pytest tests/test_one.py'))

    def test_a_loop_word_inside_a_string_is_not_a_loop(self):
        self.assertIsNone(self.kind('echo "for x in y; do"; pytest tests/test_one.py'))


class ScriptTest(TempDirTest):
    def test_real_batch_scripts_are_heavy(self):
        for name, text in (('passes.sh', PASSES_SH), ('batches.sh', BATCHES_SH)):
            with self.subTest(script=name):
                path = self.write(name, text)
                result = C.classify_outside_semaphore(f'bash {path}', self.root)
                self.assertEqual(result[0], 'tests')
                self.assertIn(name, result[1])

    def test_detached_launch_through_a_line_variable(self):
        self.write('scratch/run.sh', BATCHES_SH)
        cmd = f'S={self.root}/scratch; nohup setsid $S/run.sh > /dev/null 2>&1 & echo started'
        result = C.classify_outside_semaphore(cmd, self.root)
        self.assertEqual(result[0], 'tests')
        self.assertIn('run.sh', result[1])

    def test_self_gated_script_is_light(self):
        path = self.write('self.sh', SELF_GATED_SH)
        self.assertIsNone(self.kind(path))

    def test_missing_large_or_foreign_script_is_judged_as_before(self):
        big = self.write('big.sh', '#!/bin/bash\npytest\n' + '#' * (C.SCRIPT_MAX_BYTES + 10))
        py = self.write('tool.py', '#!/usr/bin/env python3\nimport os\n')
        binary = self.write('bin.sh', '#!/bin/bash\n\0\0pytest\n')
        for cmd in (f'{self.root}/missing.sh', big, py, binary, 'nohup setsid $UNKNOWN_VAR/x.sh'):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.kind(cmd))

    def test_script_without_shebang_run_directly(self):
        path = self.write('plain.sh', 'cd x\nnpm ci\n')
        self.assertEqual(self.kind(path), 'install')

    def test_classify_process_resolves_against_the_process_cwd(self):
        self.write('run.sh', BATCHES_SH)
        self.assertEqual(C.classify_process(['/bin/bash', './run.sh'], self.root)[0], 'tests')


class RecipeTest(TempDirTest):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.root, 'repo', '.git'))
        self.write('repo/.claude/cloud-tests.json', json.dumps({'suites': {'gates': {
            'command': 'x', 'local_commands': ['make slow-check', 'FLAG=1 make all-check']}}}), 0o644)
        C._RECIPES.clear()

    def test_declared_target_is_heavy(self):
        result = C.classify_outside_semaphore(f'cd {self.root}/repo && make slow-check', self.root)
        self.assertEqual(result[0], 'gate')
        self.assertEqual(C.classify_outside_semaphore(f'cd {self.root}/repo/sub && make all-check', self.root)[0],
                         'gate')

    def test_undeclared_target_is_light(self):
        self.assertIsNone(C.classify_outside_semaphore(f'cd {self.root}/repo && make other-check', self.root))
        self.assertIsNone(C.classify_outside_semaphore('make slow-check', self.root))

    def test_broken_recipe_is_ignored(self):
        self.write('repo/.claude/cloud-tests.json', '{not json', 0o644)
        C._RECIPES.clear()
        self.assertIsNone(C.classify_outside_semaphore(f'cd {self.root}/repo && make slow-check', self.root))


class LightTestFilesTest(TempDirTest):
    def test_collects_the_files_of_light_runs_only(self):
        runs = C.light_test_files('pytest a.py b.py; pytest c.py::t', self.root)
        files = {p for _r, f in runs for p in f}
        self.assertEqual(files, {os.path.join(self.root, n) for n in ('a.py', 'b.py', 'c.py')})
        self.assertEqual(C.light_test_files('npm ci && pytest a.py', self.root), [])
        self.assertEqual(C.light_test_files('heavy-job run -- pytest a.py', self.root), [])
        self.assertEqual(C.light_test_files('pytest -k foo', self.root), [])


class SeriesGateTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix='heavy-job-series-state-')
        self.repo = tempfile.mkdtemp(prefix='heavy-job-series-repo-')
        self.addCleanup(shutil.rmtree, self.state, True)
        self.addCleanup(shutil.rmtree, self.repo, True)
        os.makedirs(os.path.join(self.repo, '.git'))

    def hook(self, command, session='s1', cwd=None, config=None):
        env = dict(os.environ, HOME=self.state, HEAVY_JOB_GATE_STATE=self.state, HEAVY_JOB_SCRIPT=SCRIPT,
                   CLAUDE_TOOLKIT_CONFIG_DIR=os.path.join(self.state, 'config'))
        if config:
            os.makedirs(os.path.join(self.state, 'config'), exist_ok=True)
            with open(os.path.join(self.state, 'config', 'heavy-job.json'), 'w') as handle:
                json.dump(config, handle)
        payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'session_id': session,
                   'cwd': cwd or self.repo}
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                             env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)['hookSpecificOutput']['permissionDecisionReason'] if out.stdout else None

    @staticmethod
    def batch(first, last):
        return 'pytest ' + ' '.join(f'tests/test_{i}.py' for i in range(first, last + 1))

    def test_third_batch_of_five_is_denied(self):
        self.assertIsNone(self.hook(self.batch(1, 5)))
        self.assertIsNone(self.hook(self.batch(6, 10)))
        reason = self.hook(self.batch(11, 15))
        self.assertIn('serie de lotes', reason)
        self.assertIn('heavy-job run', reason)
        # the denied batch was not recorded: a repeat of an earlier one still passes
        self.assertIsNone(self.hook(self.batch(1, 5)))

    def test_repeating_the_same_test_never_trips_it(self):
        for _ in range(20):
            self.assertIsNone(self.hook('pytest tests/test_a.py'))

    def test_other_session_or_checkout_is_another_series(self):
        other = tempfile.mkdtemp(prefix='heavy-job-series-other-')
        self.addCleanup(shutil.rmtree, other, True)
        self.assertIsNone(self.hook(self.batch(1, 5)))
        self.assertIsNone(self.hook(self.batch(6, 10)))
        self.assertIsNone(self.hook(self.batch(11, 15), session='s2'))
        self.assertIsNone(self.hook(self.batch(11, 15), cwd=other))

    def test_old_entries_leave_the_window(self):
        self.assertIsNone(self.hook(self.batch(1, 5)))
        self.assertIsNone(self.hook(self.batch(6, 10)))
        with open(os.path.join(self.state, 'series.json')) as handle:
            data = json.load(handle)
        for entries in data.values():
            for value in entries.values():
                value[0] -= 2 * 3600
        with open(os.path.join(self.state, 'series.json'), 'w') as handle:
            json.dump(data, handle)
        self.assertIsNone(self.hook(self.batch(11, 15)))

    def test_wrapped_runs_are_not_counted(self):
        for first in (1, 6, 11):
            self.assertIsNone(self.hook('heavy-job run --kind tests -- ' + self.batch(first, first + 4)))

    def test_threshold_from_the_config_piece(self):
        self.assertIsNone(self.hook(self.batch(1, 3), config={'default_slots': 4, 'series_max_files': 4}))
        self.assertIn('serie de lotes', self.hook(self.batch(4, 5), config={'default_slots': 4,
                                                                             'series_max_files': 4}))

    def test_corrupt_state_fails_open(self):
        with open(os.path.join(self.state, 'series.json'), 'w') as handle:
            handle.write('[1, 2')
        self.assertIsNone(self.hook(self.batch(1, 5)))


if __name__ == '__main__':
    unittest.main()
