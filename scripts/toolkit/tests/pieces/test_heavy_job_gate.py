"""Tests for global/hooks/heavy-job-gate (PreToolUse(Bash) gate for the heavy-job semaphore).

The hook runs as a subprocess with the JSON on stdin and HEAVY_JOB_GATE_STATE pointing to a temp dir,
so the real ~/.claude/state/heavy-job-gate is never touched.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.toolkit.paths import REPO_ROOT

HOOK = str(REPO_ROOT / 'global/hooks/heavy-job-gate')
SCRIPT = str(REPO_ROOT / 'global/scripts/heavy-job')


class GateTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix='heavy-job-gate-test-')
        self.addCleanup(shutil.rmtree, self.state, True)

    def run_hook(self, stdin, extra_env=None):
        env = dict(os.environ, HOME=self.state, HEAVY_JOB_GATE_STATE=self.state, HEAVY_JOB_SCRIPT=SCRIPT,
                   CLAUDE_TOOLKIT_CONFIG_DIR=os.path.join(self.state, 'config'))
        env.update(extra_env or {})
        if not isinstance(stdin, str):
            stdin = json.dumps(stdin)
        return subprocess.run([sys.executable, HOOK], input=stdin, capture_output=True, text=True, env=env, timeout=30)

    def bash(self, command, **extra):
        payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'session_id': 'sess-1', 'cwd': '/tmp/proj'}
        payload.update(extra)
        return self.run_hook(payload)

    def read_log(self, name):
        try:
            with open(os.path.join(self.state, name)) as handle:
                return handle.read()
        except OSError:
            return ''

    def assert_allowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')

    def assert_denied(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(data['hookEventName'], 'PreToolUse')
        self.assertEqual(data['permissionDecision'], 'deny')
        self.assertIn('heavy-job run', data['permissionDecisionReason'])
        return data['permissionDecisionReason']

    def test_heavy_command_denied(self):
        reason = self.assert_denied(self.bash('npm ci'))
        self.assertIn('--kind install', reason)
        self.assertIn('trabajos-pesados.md', reason)
        self.assertRegex(reason, r'los \d+ huecos del resto')   # an install does not wait for the test queue

    def test_suite_denied_with_the_shared_cpu_slots(self):
        reason = self.assert_denied(self.bash('cd x && make ci'))
        self.assertIn('--kind gate', reason)
        self.assertRegex(reason, r'compilar apps y correr tests de todos los proyectos comparten \d+ huecos')

    def test_ml_command_denied_with_kind_ml(self):
        for command in ('whisper talk.mp3 --model large-v3', 'cd x && python3 -m faster_whisper talk.mp3',
                        'torchrun --nproc_per_node 2 train.py'):
            with self.subTest(command=command):
                reason = self.assert_denied(self.bash(command))
                self.assertIn('--kind ml', reason)
        self.assertIn('kind=ml', self.read_log('decisions.log'))

    def test_wrapped_ml_command_allowed(self):
        self.assert_allowed(self.bash('~/.claude/scripts/heavy-job run --kind ml -- whisper talk.mp3'))

    def test_light_command_allowed(self):
        self.assert_allowed(self.bash('git status && npm run lint'))

    def test_grep_mentioning_npm_ci_allowed(self):
        self.assert_allowed(self.bash('grep -n "npm ci" Makefile'))

    def test_already_wrapped_allowed(self):
        self.assert_allowed(self.bash('~/.claude/scripts/heavy-job run --kind install -- npm ci'))

    def test_mentioning_heavy_job_is_not_a_bypass(self):
        for command in ('make -C /tmp/heavy-job-probe ci',
                        'echo heavy-job; npm ci',
                        '~/.claude/scripts/heavy-job run -- npm ci && npm test',
                        'heavy-job status && ./gradlew assembleDebug'):
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

    def test_real_semaphore_use_allowed(self):
        for command in ('~/.claude/scripts/heavy-job run --kind gate -- make ci',
                        'cd /x && ~/.claude/scripts/heavy-job run --kind install --label deps -- npm ci',
                        'bash -c "~/.claude/scripts/heavy-job run -- npm ci"',
                        'nohup ~/.claude/scripts/heavy-job hold --kind emulator -- emulator -avd test_avd '
                        '-no-window > /tmp/e.log 2>&1 &',
                        'heavy-job status',
                        'grep -n heavy-job README.md'):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))

    def test_gradle_denied(self):
        self.assert_denied(self.bash('cd android && ./gradlew :app:assembleRelease'))

    def test_worktree_slot_make_ci_denied(self):
        self.assert_denied(self.bash('tools/worktree-slot.sh make ci'))

    def test_single_pytest_file_allowed(self):
        self.assert_allowed(self.bash('pytest tests/test_x.py -q'))

    def test_non_bash_tool_allowed(self):
        self.assert_allowed(self.run_hook({'tool_name': 'Write', 'tool_input': {'file_path': '/tmp/x', 'content': 'npm ci'}}))

    def test_missing_command_allowed(self):
        self.assert_allowed(self.run_hook({'tool_name': 'Bash', 'tool_input': {}}))

    def test_malformed_json_fails_open(self):
        self.assert_allowed(self.run_hook('{not json'))
        self.assertIn('errors.log', os.listdir(self.state))
        self.assertTrue(self.read_log('errors.log').strip())

    def test_missing_script_fails_open(self):
        result = self.run_hook({'tool_name': 'Bash', 'tool_input': {'command': 'npm ci'}},
                               {'HEAVY_JOB_SCRIPT': os.path.join(self.state, 'nope')})
        self.assert_allowed(result)
        self.assertTrue(self.read_log('errors.log').strip())
        self.assertEqual(self.read_log('decisions.log'), '')

    def test_classifier_crash_fails_open(self):
        broken = os.path.join(self.state, 'broken-heavy-job')
        os.makedirs(os.path.join(self.state, 'lib'))
        with open(os.path.join(self.state, 'lib', 'heavy_job_classifier.py'), 'w') as handle:
            handle.write('def classify_outside_semaphore(command, cwd=None):\n    raise RuntimeError("boom")\n')
        result = self.run_hook({'tool_name': 'Bash', 'tool_input': {'command': 'npm ci'}}, {'HEAVY_JOB_SCRIPT': broken})
        self.assert_allowed(result)
        self.assertIn('boom', self.read_log('errors.log'))

    def test_a_broken_script_never_blocks_what_the_classifier_would_deny(self):
        broken = os.path.join(self.state, 'broken-heavy-job')
        os.makedirs(os.path.join(self.state, 'lib'))
        shutil.copy(os.path.join(os.path.dirname(SCRIPT), 'lib', 'heavy_job_classifier.py'),
                    os.path.join(self.state, 'lib'))
        with open(broken, 'w') as handle:
            handle.write('raise RuntimeError("broken script")\n')
        result = self.run_hook({'tool_name': 'Bash', 'tool_input': {'command': 'npm ci'}}, {'HEAVY_JOB_SCRIPT': broken})
        self.assert_allowed(result)
        self.assertIn('broken script', self.read_log('errors.log'))

    def test_deny_writes_one_decision_line(self):
        self.assert_denied(self.bash('npm ci'))
        lines = self.read_log('decisions.log').splitlines()
        self.assertEqual(len(lines), 1)
        for fragment in ('sess-1', '/tmp/proj', 'kind=install', 'npm ci'):
            self.assertIn(fragment, lines[0])
        self.assertEqual(self.read_log('errors.log'), '')

    def test_allow_writes_no_log(self):
        self.assert_allowed(self.bash('git status'))
        self.assertEqual(os.listdir(self.state), [])

    def test_logged_command_truncated_to_200_chars(self):
        self.assert_denied(self.bash('npm ci # ' + 'x' * 500))
        line = self.read_log('decisions.log').splitlines()[0]
        self.assertLess(len(line), 400)
        self.assertNotIn('x' * 201, line)

    def test_decision_line_says_why(self):
        self.assert_denied(self.bash('vendor/bin/phpunit'))
        line = self.read_log('decisions.log').splitlines()[0]
        self.assertIn('why=phpunit sin filtro ni fichero (suite completa)', line)

    def test_explicit_targets_and_filters_pass_the_gate(self):
        for command in ('vendor/bin/phpunit --group REQ-1', 'for f in tests/*Test.php; do vendor/bin/phpunit $f; done',
                        'pytest --collect-only -q', 'npx playwright test e2e/a.spec.ts'):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))
        self.assertEqual(self.read_log('decisions.log'), '')

    def test_small_directory_is_judged_against_the_payload_cwd(self):
        project = tempfile.mkdtemp(prefix='heavy-job-gate-proj-')
        self.addCleanup(shutil.rmtree, project, True)
        small = os.path.join(project, 'tests', 'Unit', 'Small')
        big = os.path.join(project, 'tests', 'Unit', 'Big')
        for directory, count in ((small, 2), (big, 8)):
            os.makedirs(directory)
            for i in range(count):
                with open(os.path.join(directory, 'F%dTest.php' % i), 'w'):
                    pass
        self.assert_allowed(self.bash('vendor/bin/phpunit tests/Unit/Small', cwd=project))
        self.assert_denied(self.bash('vendor/bin/phpunit tests/Unit/Big', cwd=project))
        self.assert_denied(self.bash('vendor/bin/phpunit tests/Unit/Small', cwd='/tmp/proj'))
        self.assert_allowed(self.bash('cd %s && vendor/bin/phpunit tests/Unit/Small' % project, cwd='/tmp/proj'))
        self.assertEqual(len(self.read_log('decisions.log').splitlines()), 2)


if __name__ == '__main__':
    unittest.main()
