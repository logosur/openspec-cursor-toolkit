"""Tests for global/scripts/project-pause (pause every session of a project until the developer says otherwise).

Every test runs against a temporary PROJECT_PAUSE_HOME and a temporary HOME, so the real state, the real routines and
the real session census are never touched. supervisor-lock is the toolkit copy; routines is a fake that records its
calls. The optional pieces being absent is tested on purpose.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = os.environ.get('PROJECT_PAUSE_SCRIPT') or str(REPO_ROOT / 'global/scripts/project-pause')
LOCK = str(REPO_ROOT / 'global/scripts/supervisor-lock')
GIT_ENV = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@example.com'}

FAKE_ROUTINES = """#!/usr/bin/env python3
import os, sys
with open(os.environ['FAKE_ROUTINES_LOG'], 'a') as fh:
    fh.write(' '.join(sys.argv[1:]) + '\\n')
sys.exit(1 if os.environ.get('FAKE_ROUTINES_FAIL') else 0)
"""


def load_module(name='project_pause_under_test', env=None):
    with mock.patch.dict(os.environ, env or {}):
        loader = importlib.machinery.SourceFileLoader(name, SCRIPT)
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
    return module


class Sandbox(unittest.TestCase):
    """A temporary HOME, state dir, config dir and routines, with env for the script."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='project-pause-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, 'home')
        self.state = os.path.join(self.tmp, 'state')
        self.cfg = os.path.join(self.tmp, 'cfg')
        for d in (self.home, self.cfg):
            os.makedirs(d)
        self.routines_log = os.path.join(self.tmp, 'routines.log')
        self.routines_bin = os.path.join(self.tmp, 'fake-routines')
        with open(self.routines_bin, 'w') as fh:
            fh.write(FAKE_ROUTINES)
        os.chmod(self.routines_bin, 0o755)
        self.registry = os.path.join(self.tmp, 'registry.json')
        self.env = dict(os.environ, HOME=self.home, PROJECT_PAUSE_HOME=self.state, SUPERVISOR_LOCK_BIN=LOCK,
                        CLAUDE_TOOLKIT_CONFIG_DIR=self.cfg, ROUTINES_BIN=self.routines_bin,
                        ROUTINES_REGISTRY=self.registry, FAKE_ROUTINES_LOG=self.routines_log, **GIT_ENV)
        self.env.pop('FAKE_ROUTINES_FAIL', None)
        # in-process calls read the environment when they run: keep them inside the sandbox
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def repo(self, name='proj'):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        subprocess.run(['git', 'init', '-q', path], check=True, env=self.env)
        return os.path.realpath(path)

    def run_cli(self, *args, stdin='', env=None):
        return subprocess.run([sys.executable, SCRIPT, *args], input=stdin, capture_output=True, text=True,
                              env=env or self.env, timeout=60)

    def module(self):
        mod = load_module(env=self.env)
        assert mod.home() == self.state, 'the module must not see the real state'
        return mod

    def calls(self):
        try:
            with open(self.routines_log) as fh:
                return fh.read().split('\n')[:-1]
        except OSError:
            return []

    def write_config(self, data):
        with open(os.path.join(self.cfg, 'supervision.json'), 'w') as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))


class MarkerTests(Sandbox):
    def marker(self, mod, repo, key='proj-test', **extra):
        data = {'key': key, 'name': 'proj', 'checkout': repo, 'common_dir': mod.git_common_dir(repo),
                'paused_at': mod.now_iso(), 'sessions': [], 'supervisor': None, 'blocked': []}
        data.update(extra)
        mod.write_json(mod.marker_path(key), data)

    def test_nothing_paused_means_no_marker_and_no_git_call(self):
        mod = self.module()
        repo = self.repo()
        with mock.patch.object(mod, 'git_common_dir') as git:
            self.assertIsNone(mod.paused_marker(repo))
        git.assert_not_called()

    def test_the_checkout_a_subfolder_and_a_worktree_are_paused_another_repo_is_not(self):
        mod = self.module()
        repo, other = self.repo(), self.repo('other')
        sub = os.path.join(repo, 'src')
        os.makedirs(sub)
        subprocess.run(['git', '-C', repo, 'commit', '-q', '--allow-empty', '-m', 'x'], check=True, env=self.env)
        worktree = os.path.join(self.tmp, 'wt')
        subprocess.run(['git', '-C', repo, 'worktree', 'add', '-q', '--detach', worktree], check=True, env=self.env)
        self.marker(mod, repo)
        self.assertTrue(mod.paused_marker(repo))
        self.assertTrue(mod.paused_marker(sub))
        self.assertTrue(mod.paused_marker(worktree))
        self.assertIsNone(mod.paused_marker(other))
        self.assertIsNone(mod.paused_marker(''))

    def test_check_exit_codes_and_status(self):
        repo, other = self.repo(), self.repo('other')
        mod = self.module()
        self.marker(mod, repo)
        done = self.run_cli('check', repo)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, 'proj-test'))
        self.assertEqual(self.run_cli('check', other).returncode, 1)
        status = self.run_cli('status')
        self.assertIn('proj-test: en pausa desde', status.stdout)
        as_json = json.loads(self.run_cli('status', '--json').stdout)
        self.assertEqual(list(as_json), ['proj-test'])
        self.assertEqual(as_json['proj-test']['wake'], [])

    def test_status_with_nothing_paused(self):
        done = self.run_cli('status')
        self.assertEqual((done.returncode, done.stdout.strip()), (0, 'Ningún proyecto en pausa.'))

    def test_a_corrupt_marker_file_is_ignored(self):
        mod = self.module()
        os.makedirs(self.state)
        with open(os.path.join(self.state, 'broken.json'), 'w') as fh:
            fh.write('{not json')
        self.assertEqual(mod.markers(), {})
        self.assertEqual(self.run_cli('status').returncode, 0)


class HookTests(Sandbox):
    def paused(self, repo):
        mod = self.module()
        mod.write_json(mod.marker_path('proj-test'), {
            'key': 'proj-test', 'name': 'proj', 'checkout': repo, 'common_dir': mod.git_common_dir(repo),
            'paused_at': mod.now_iso(), 'sessions': [{'id': 'local_busy', 'live': True, 'status': 'busy'}],
            'supervisor': {'session': 'local_sup'}, 'blocked': []})
        return mod

    def payload(self, repo, prompt, **extra):
        return dict({'hook_event_name': 'UserPromptSubmit', 'cwd': repo, 'session_id': 'cli-x', 'prompt': prompt},
                    **extra)

    def test_an_automated_prompt_is_blocked_and_recorded(self):
        repo = self.repo()
        mod = self.paused(repo)
        out = json.loads(mod.hook_decide(self.payload(repo, '<task-notification>\n<task-id>abc</task-id>')))
        self.assertEqual(out['decision'], 'block')
        blocked = mod.read_json(mod.marker_path('proj-test'))['blocked']
        self.assertEqual([b['session'] for b in blocked], ['cli-x'])
        self.assertTrue(blocked[0]['head'].startswith('<task-notification>'))

    def test_the_developer_goes_through_with_a_note(self):
        repo = self.repo()
        mod = self.paused(repo)
        out = json.loads(mod.hook_decide(self.payload(repo, 'mira el log de ayer')))
        self.assertNotIn('decision', out)
        self.assertIn('en pausa', out['hookSpecificOutput']['additionalContext'])
        self.assertEqual(mod.read_json(mod.marker_path('proj-test'))['blocked'], [])

    def test_a_non_human_origin_is_blocked_even_with_plain_text(self):
        repo = self.repo()
        mod = self.paused(repo)
        out = json.loads(mod.hook_decide(self.payload(repo, 'hola', origin={'kind': 'task-notification'})))
        self.assertEqual(out['decision'], 'block')
        out = json.loads(mod.hook_decide(self.payload(repo, 'hola', origin={'kind': 'human'})))
        self.assertNotIn('decision', out)

    def test_another_project_and_a_project_not_paused_are_untouched(self):
        repo, other = self.repo(), self.repo('other')
        mod = self.paused(repo)
        self.assertEqual(mod.hook_decide(self.payload(other, '<task-notification>')), '')
        self.assertEqual(mod.hook_decide({'hook_event_name': 'Stop', 'cwd': repo}), '')

    def test_the_markers_come_from_the_supervision_config(self):
        repo = self.repo()
        self.write_config({'project_resume_marker': '[resume project]', 'account_switch_marker': '[account change]'})
        mod = self.paused(repo)
        self.assertEqual(mod.RESUME_MARKER, '[resume project]')
        self.assertFalse(mod.is_human({'prompt': '[resume project] go on'}))
        self.assertFalse(mod.is_human({'prompt': '[account change] go on'}))
        self.assertTrue(mod.is_human({'prompt': '[cambio de cuenta] go on'}))  # the default marker is not special now
        self.assertTrue(mod.is_human({'prompt': 'mira esto'}))

    def test_default_markers_without_config(self):
        mod = self.module()
        self.assertEqual(mod.RESUME_MARKER, '[reanudar proyecto]')
        self.assertFalse(mod.is_human({'prompt': '[reanudar proyecto] sigue'}))
        self.assertFalse(mod.is_human({'prompt': '[cambio de cuenta] sigue'}))

    def test_a_corrupt_or_mistyped_config_keeps_the_defaults(self):
        self.write_config('{not json')
        self.assertEqual(self.module().RESUME_MARKER, '[reanudar proyecto]')
        self.write_config({'project_resume_marker': '', 'account_switch_marker': 7})
        mod = self.module()
        self.assertEqual((mod.RESUME_MARKER, mod.CONFIG['account_switch_marker']),
                         ('[reanudar proyecto]', '[cambio de cuenta]'))

    def test_the_hook_process_never_fails_the_session(self):
        for raw in ('this is { not json', '', '[]', '{}'):
            done = self.run_cli('hook', stdin=raw)
            self.assertEqual((done.returncode, done.stdout), (0, ''), raw)

    def test_the_hook_works_without_supervisor_lock(self):
        repo = self.repo()
        self.paused(repo)
        env = dict(self.env, SUPERVISOR_LOCK_BIN=os.path.join(self.tmp, 'absent'))
        done = self.run_cli('hook', stdin=json.dumps(self.payload(repo, '<task-notification>')), env=env)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(done.stdout)['decision'], 'block')
        with open(os.path.join(self.state, 'proj-test.json')) as fh:
            blocked = json.load(fh)['blocked']
        self.assertEqual(blocked[0]['session'], 'cli-x')  # no registry to translate it: the CLI id stays


class ResumeGateTests(Sandbox):
    def event(self, mod, resumed_at=None, delivered=None):
        mod.write_json(os.path.join(mod.home(), 'resume-proj-test.json'), {
            'key': 'proj-test', 'name': 'proj', 'resumed_at': resumed_at or mod.now_iso(),
            'wake': [{'session': 'local_busy', 'delivered_at': delivered}]})

    def test_a_listed_session_gets_the_message_once(self):
        mod = self.module()
        self.event(mod)
        self.assertEqual(mod.resume_allowed('local_busy'), (True, 'proj'))
        self.assertFalse(mod.resume_allowed('local_other')[0])
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cmd_delivered(mock.Mock(session='local_busy'))
        allowed, why = mod.resume_allowed('local_busy')
        self.assertFalse(allowed)
        self.assertIn('ya recibió', why)

    def test_not_after_the_window(self):
        mod = self.module()
        late = datetime.fromtimestamp(time.time() - mod.RESUME_WINDOW_S - 60).astimezone().isoformat()
        self.event(mod, resumed_at=late)
        self.assertFalse(mod.resume_allowed('local_busy')[0])

    def test_delivered_of_an_unknown_session(self):
        done = self.run_cli('delivered', 'local_nobody')
        self.assertEqual((done.returncode, done.stdout.strip()), (1, 'UNKNOWN local_nobody'))


class CycleTests(Sandbox):
    """pause -> a blocked prompt -> resume -> delivered, through the real commands and the toolkit supervisor-lock."""

    def write_registry(self, repo):
        with open(self.registry, 'w') as fh:
            json.dump({'routines': [{'id': 'nightly', 'enabled': True, 'cwd': repo},
                                    {'id': 'elsewhere', 'enabled': True, 'cwd': self.tmp},
                                    {'id': 'already-off', 'enabled': False, 'cwd': repo}]}, fh)

    def test_the_whole_cycle(self):
        repo = self.repo()
        self.write_registry(repo)
        done = self.run_cli('pause', repo, '--order', 'test order', '--by', 'local_me')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('routines_disabled=1', done.stdout)
        self.assertEqual(self.calls(), ['disable nightly'])
        again = self.run_cli('pause', repo, '--order', 'again')
        self.assertIn('ALREADY', again.stdout)
        self.assertEqual(self.calls(), ['disable nightly'])  # idempotent
        self.assertEqual(self.run_cli('check', repo).returncode, 0)

        hook = self.run_cli('hook', stdin=json.dumps({'hook_event_name': 'UserPromptSubmit', 'cwd': repo,
                                                      'session_id': 'local_woken', 'prompt': '<task-notification> x'}))
        self.assertEqual(json.loads(hook.stdout)['decision'], 'block')
        status = json.loads(self.run_cli('status', '--json').stdout)
        (key, data), = status.items()
        self.assertEqual((data['order'], data['by'], data['routines_disabled']), ('test order', 'local_me', ['nightly']))
        self.assertEqual(data['wake'], ['local_woken'])

        done = self.run_cli('resume', repo, '--by', 'local_me')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('ROUTINE-ON nightly', done.stdout)
        self.assertIn('WAKE local_woken', done.stdout)
        self.assertEqual(self.calls(), ['disable nightly', 'enable nightly'])
        self.assertEqual(self.run_cli('check', repo).returncode, 1)
        self.assertEqual(self.run_cli('resume', repo).returncode, 1)
        self.assertTrue(any(n.startswith(key) for n in os.listdir(os.path.join(self.state, 'history'))))
        with open(os.path.join(self.state, f'resume-{key}.json')) as fh:
            event = json.load(fh)
        text = event['wake'][0]['text']
        self.assertTrue(text.startswith('[reanudar proyecto]'))
        self.assertIn('task-notification', text)
        mod = self.module()
        self.assertTrue(mod.resume_allowed('local_woken')[0])
        self.assertEqual(self.run_cli('delivered', 'local_woken').returncode, 0)
        self.assertFalse(mod.resume_allowed('local_woken')[0])

    def test_a_failing_routines_command_is_reported_and_the_pause_still_happens(self):
        repo = self.repo()
        self.write_registry(repo)
        done = self.run_cli('pause', repo, '--order', 'o', env=dict(self.env, FAKE_ROUTINES_FAIL='1'))
        self.assertEqual(done.returncode, 1)
        self.assertIn('ROUTINE-FAILED nightly', done.stdout)
        self.assertEqual(self.run_cli('check', repo).returncode, 0)

    def test_without_routines_installed_the_pause_works_and_says_so(self):
        repo = self.repo()
        self.write_registry(repo)
        env = dict(self.env, ROUTINES_BIN=os.path.join(self.tmp, 'absent'))
        done = self.run_cli('pause', repo, '--order', 'o', env=env)
        self.assertIn('routines is not installed', done.stdout)
        self.assertNotIn('Traceback', done.stderr)
        self.assertEqual(self.run_cli('check', repo).returncode, 0)

    def test_without_a_routines_registry_nothing_is_disabled(self):
        repo = self.repo()
        done = self.run_cli('pause', repo, '--order', 'o')
        self.assertEqual(done.returncode, 0)
        self.assertIn('routines_disabled=0', done.stdout)
        self.assertEqual(self.calls(), [])

    def test_pause_without_supervisor_lock_fails_with_a_message(self):
        repo = self.repo()
        env = dict(self.env, SUPERVISOR_LOCK_BIN=os.path.join(self.tmp, 'absent'))
        done = self.run_cli('pause', repo, '--order', 'o', env=env)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('supervisor-lock is not installed', done.stderr)
        self.assertNotIn('Traceback', done.stderr)
        self.assertEqual(self.run_cli('free', env=env).returncode, 1)

    def test_a_directory_that_is_not_a_project_is_refused(self):
        done = self.run_cli('pause', os.path.join(self.tmp, 'nowhere'), '--order', 'o')
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('neither a git repository nor a workspace', done.stderr)

    def test_free_with_nothing_paused(self):
        done = self.run_cli('free', '--dry-run')
        self.assertEqual(done.returncode, 0)
        self.assertIn('Ningún proyecto en pausa.', done.stdout)
        self.assertIn('freed ~0 MB', done.stdout)


class SelfTestTests(Sandbox):
    def test_the_builtin_self_test_passes(self):
        done = self.run_cli('self-test')
        self.assertEqual(done.returncode, 0, done.stdout[-500:])
        self.assertIn('all passed', done.stdout)

    def test_the_builtin_self_test_skips_the_cycle_without_supervisor_lock(self):
        done = self.run_cli('self-test', env=dict(self.env, SUPERVISOR_LOCK_BIN=os.path.join(self.tmp, 'absent')))
        self.assertEqual(done.returncode, 0, done.stdout[-500:])
        self.assertIn('skip cycle', done.stdout)


if __name__ == '__main__':
    unittest.main()
