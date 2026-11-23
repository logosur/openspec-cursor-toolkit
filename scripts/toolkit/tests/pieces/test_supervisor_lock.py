"""Tests of global/scripts/supervisor-lock: the thin entry point over the package global/scripts/lib/supervisor.

Every run uses a throwaway HOME, its own toolkit config and state paths inside a temp dir, with the variables that
could point at real state removed. None of the optional pieces (account-switch, cloud-tests, project-pause,
session-nudge, handoff-guard, routines) is present, so these tests also prove that the tool degrades without them.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.toolkit.paths import REPO_ROOT

ENTRY = str(REPO_ROOT / 'global/scripts/supervisor-lock')
SKILL = REPO_ROOT / 'global/skills/supervisa-sesiones/SKILL.md'
SUBCOMMANDS = ('project', 'registry-dir', 'acquire', 'reclaim', 'beat', 'release', 'open', 'closable', 'hold', 'cloud',
               'cloud-archive', 'cloud-send', 'status', 'backlog', 'skill-lint', 'wait-closer', 'mode', 'list',
               'sessions', 'wait', 'watchdog', 'revive', 'hook', 'self-test')
EXPORTS = ('cli_dir', 'collect_sessions', 'pid_alive', 'read_json_files', 'read_locks', 'resolve', 'git', 'span',
           'ASK_GATE_MAILBOX_TITLES', 'NOT_HUMAN_PREFIXES', 'app_glob', 'fold_text', 'session_role',
           'title_names_project', 'session_files', 'last_human_input')
SCRUB_PREFIXES = ('SUPERVISOR_', 'ASK_GATE', 'ASK_QUEUE', 'CLOUD_TESTS_', 'ACCOUNT_SWITCH', 'PROJECT_PAUSE',
                  'CROSS_PROJECT_GATE_', 'CLAUDE_TOOLKIT_', 'CLAUDE_CODE_', 'CLAUDE_CONFIG_DIR', 'XDG_')


def load_entry(name):
    """The entry point loaded the way its callers load it (SourceFileLoader, any module name)."""
    loader = importlib.machinery.SourceFileLoader(name, ENTRY)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='supervisor-lock-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.mkdir('home')
        self.config = self.mkdir('toolkit-config')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(SCRUB_PREFIXES)}
        self.env.update(HOME=self.home, CLAUDE_TOOLKIT_CONFIG_DIR=self.config, TMPDIR=self.mkdir('tmp'),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, SUPERVISOR_USAGE='unknown')

    def mkdir(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path, exist_ok=True)
        return path

    def run_cli(self, *args, stdin='', env=None, timeout=120):
        return subprocess.run([sys.executable, ENTRY, *args], input=stdin, capture_output=True, text=True,
                              env=dict(self.env, **(env or {})), timeout=timeout, cwd=self.tmp)

    def python(self, code, env=None):
        """Run `code` in a fresh interpreter (sys.argv[1] is the entry point); its stdout."""
        r = subprocess.run([sys.executable, '-c', code, ENTRY], capture_output=True, text=True,
                           env=dict(self.env, **(env or {})), timeout=60, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def repo(self, name, remote=None):
        path = self.mkdir(name)
        subprocess.run(['git', 'init', '-q', path], check=True, env=self.env)
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'i'],
                       cwd=path, check=True, capture_output=True, env=self.env)
        if remote:
            subprocess.run(['git', 'remote', 'add', 'origin', remote], cwd=path, check=True, env=self.env)
        return path


LOADER = '''
import importlib.machinery, importlib.util, sys
def load(name):
    loader = importlib.machinery.SourceFileLoader(name, sys.argv[1])
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
'''


class EntryPointTest(Base):
    def test_help_lists_the_same_subcommands(self):
        r = self.run_cli('--help')
        self.assertEqual(r.returncode, 0, r.stderr)
        listed = r.stdout.split('{', 1)[1].split('}', 1)[0].split(',')
        self.assertEqual(tuple(listed), SUBCOMMANDS)

    def test_every_subcommand_has_help(self):
        for name in SUBCOMMANDS:
            r = self.run_cli(name, '--help')
            self.assertEqual(r.returncode, 0, (name, r.stderr))
            self.assertIn('usage', r.stdout)

    def test_reexported_names_survive_several_loads_under_different_names(self):
        out = self.python(LOADER + f'''
import json
a, b = load('supervisor_lock'), load('another_name')
names = {list(EXPORTS)!r}
print(json.dumps({{'missing': [n for n in names if not hasattr(a, n) or not hasattr(b, n)],
                   'same': all(getattr(a, n) is getattr(b, n) for n in names),
                   'callable': [n for n in names if not n.isupper() and not callable(getattr(a, n))],
                   'unknown': hasattr(a, 'no_such_name')}}))
''')
        got = json.loads(out)
        self.assertEqual(got, {'missing': [], 'same': True, 'callable': [], 'unknown': False})

    def test_reexports_read_the_owner_module_at_read_time(self):
        out = self.python(LOADER + '''
lock = load('supervisor_lock')
owner = lock._module('census')
real = owner.pid_alive
owner.pid_alive = lambda pid: 'patched'
print(lock.pid_alive(1))
owner.pid_alive = real
''')
        self.assertEqual(out.strip(), 'patched')

    def test_a_patch_of_the_owner_module_reaches_every_caller(self):
        out = self.python(LOADER + '''
import json
lock = load('supervisor_lock')
roles, deny, turns, gate = (lock._module(n) for n in ('session_roles', 'deny', 'human_turns', 'ask_gate'))
owner = {'project': 'p', 'mailbox': 'local_box', 'key': 'k'}
roles.mailbox_alive = lambda mailbox: True
alive = json.loads(deny.deny_question(owner, 'local_me'))['hookSpecificOutput']['permissionDecisionReason']
roles.mailbox_alive = lambda mailbox: False
dead = json.loads(deny.deny_question(owner, 'local_me'))['hookSpecificOutput']['permissionDecisionReason']
turns.last_human_input = lambda path, since, with_text=False: 4242.0
seen = gate.developer_present({'transcript_path': sys.argv[1]}, 'cli-x')
print(json.dumps([('local_box (SendMessage)' in alive), ('ya no existe' in dead), seen]))
''')
        self.assertEqual(json.loads(out), [True, True, 4242.0])

    def test_runtime_entry_is_the_realpath_of_the_entry_point(self):
        link = os.path.join(self.tmp, 'linked-lock')
        os.symlink(ENTRY, link)
        out = subprocess.run([sys.executable, '-c', LOADER + 'print(load("x")._module("runtime").ENTRY)', link],
                             capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(out.stdout.strip(), os.path.realpath(ENTRY), out.stderr)

    def test_the_hook_never_imports_the_self_test(self):
        out = self.python(LOADER + '''
import io, json
lock = load('supervisor_lock')
for payload in ({'hook_event_name': 'Stop', 'session_id': 's'},
                {'hook_event_name': 'PreToolUse', 'tool_name': 'AskUserQuestion', 'session_id': 's', 'tool_input': {}}):
    sys.stdin = io.StringIO(json.dumps(payload))
    lock._module('hook').cmd_hook(None)
print(sorted(m.rsplit('.', 1)[-1] for m in sys.modules if m.startswith(lock.PACKAGE + '.')))
''')
        self.assertNotIn("'selftest'", out)
        self.assertIn("'hook'", out)


class ConfigTest(Base):
    def settings(self, raw=None):
        if raw is not None:
            with open(os.path.join(self.config, 'supervision.json'), 'w') as fh:
                fh.write(raw)
        return json.loads(self.python(LOADER + '''
import json
s = load('supervisor_lock')._module('settings')
print(json.dumps({'presence': s.PRESENCE_MIN, 'fresh': s.FRESH_MIN, 'deploy': s.DEPLOY_PREAUTHORISED,
                  'archive': s.ARCHIVE_PREAUTHORISED, 'criterion': s.DECISION_CRITERION,
                  'excluded': list(s.EXCLUDED_PROJECTS), 'anchors': list(s.SKILL_ANCHORS), 'rule': s.DEPLOY_RULE,
                  'titles': list(s.QUESTIONS_TITLES), 'title': s.questions_title('p'), 'glob': s.APP_SESSIONS_GLOB}))
'''))

    def test_defaults_match_the_shipped_config_piece(self):
        with open(REPO_ROOT / 'global/config/supervision.json', encoding='utf-8') as fh:
            shipped = fh.read()
        self.assertEqual(self.settings(shipped), self.settings('{}'))

    def test_defaults_grant_nothing(self):
        got = self.settings()
        self.assertIs(got['deploy'], False)
        self.assertIs(got['archive'], False)
        self.assertNotIn('conservadora', got['criterion'])
        self.assertEqual(got['excluded'], [])
        self.assertEqual((got['presence'], got['fresh']), (20, 3))
        self.assertEqual(got['anchors'][0], '## Prohibido')
        self.assertIn('## Motivo de la guardia', got['anchors'])

    def test_a_corrupt_config_gives_the_defaults(self):
        self.assertEqual(self.settings('{not json'), self.settings('{}'))

    def test_mistyped_values_give_the_defaults_never_more_permission(self):
        got = self.settings(json.dumps({'deploy_preauthorised': 'yes', 'archive_preauthorised': 1,
                                        'presence_min': -5, 'fresh_min': 'x',
                                        'excluded_projects': 'p', 'skill_anchors': [1, 2]}))
        self.assertEqual(got, self.settings('{}'))

    def test_valid_values_are_read(self):
        got = self.settings(json.dumps({'deploy_preauthorised': True, 'excluded_projects': ['p1'], 'presence_min': 30,
                                        'questions_session_title': 'Questions of {project}',
                                        'deploy_rule': 'deploys.md'}))
        self.assertIs(got['deploy'], True)
        self.assertEqual((got['excluded'], got['presence'], got['title']), (['p1'], 30, 'Questions of p'))
        self.assertTrue(got['rule'].endswith('/rules/deploys.md'))

    def test_environment_overrides_keep_their_priority(self):
        out = self.python(LOADER + '''
lock = load('supervisor_lock')
print(lock._module('ask_gate').ask_gate_presence_minutes(), lock.app_glob())
''', env={'ASK_GATE_PRESENCE_MIN': '7', 'SUPERVISOR_APP_SESSIONS_GLOB': '/x/*.json'})
        self.assertEqual(out.split(), ['7.0', '/x/*.json'])


class DegradationTest(Base):
    """Without any optional piece every subcommand exits cleanly, with no traceback."""

    def assert_clean(self, r, codes=(0,)):
        self.assertNotIn('Traceback', r.stderr + r.stdout)
        self.assertIn(r.returncode, codes, r.stderr)

    def test_cloud_says_the_provider_is_unavailable(self):
        repo = self.repo('proj', 'https://github.com/t/proj.git')
        r = self.run_cli('cloud', '--dir', repo)
        self.assert_clean(r, (3,))
        self.assertIn('CLOUD-UNAVAILABLE', r.stdout + r.stderr)
        r = self.run_cli('cloud', '--dir', repo, '--json')
        self.assert_clean(r, (3,))
        self.assertIs(json.loads(r.stdout)['available'], False)

    def test_cloud_actions_say_the_provider_is_unavailable(self):
        repo = self.repo('proj', 'https://github.com/t/proj.git')
        self.assert_clean(self.run_cli('acquire', '--dir', repo, '--session', 'local_o', '--title', 't'))
        for args in (('cloud-archive', '--target', 'cse_x', '--reason', 'comprobado'), ('cloud-send', '--target', 'cse_x', '--text', 'hola')):
            r = self.run_cli(args[0], '--dir', repo, '--session', 'local_o', *args[1:])
            self.assertNotIn('Traceback', r.stderr)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('CLOUD-UNAVAILABLE', r.stdout + r.stderr)

    def test_the_other_subcommands_run_without_the_optional_pieces(self):
        repo = self.repo('proj')
        self.assert_clean(self.run_cli('acquire', '--dir', repo, '--session', 'local_o', '--title', 't'))
        for args, codes in ((('list', '--json'), (0,)), (('revive', '--json'), (0,)), (('watchdog', '--notify', '--nudge'), (0, 1)),
                            (('sessions', '--dir', repo, '--json'), (0,)), (('status', '--dir', repo), (0,)),
                            (('closable', '--dir', repo), (0, 1)),
                            (('backlog', '--dir', repo), (0,)), (('mode', '--dir', repo, '--get'), (0,)),
                            (('wait', '--dir', repo, '--owner', 'local_o', '--timeout', '1', '--interval', '0.2'), (0,)),
                            (('release', '--dir', repo, '--session', 'local_o', '--verdict', 'DONE'), (0,))):
            with self.subTest(args=args):
                r = self.run_cli(*args)
                self.assert_clean(r, codes)
        revive = self.run_cli('revive', '--json')
        self.assertEqual(set(json.loads(revive.stdout)), {'targets', 'notes'})

    def test_the_hook_never_fails_a_session(self):
        repo = self.repo('proj')
        self.assert_clean(self.run_cli('acquire', '--dir', repo, '--session', 'local_o', '--title', 't'))
        for payload in ({'hook_event_name': 'Stop', 'session_id': 's', 'cwd': repo},
                        {'hook_event_name': 'SessionStart', 'source': 'startup', 'session_id': 's', 'cwd': repo},
                        {'hook_event_name': 'PreToolUse', 'tool_name': 'AskUserQuestion', 'session_id': 's', 'cwd': repo,
                         'tool_input': {}}):
            r = self.run_cli('hook', stdin=json.dumps(payload))
            self.assert_clean(r)
        self.assert_clean(self.run_cli('hook', stdin='not json'))

    def test_the_stop_gate_works_without_handoff_guard(self):
        scripts = os.path.join(self.home, '.claude', 'scripts')
        os.makedirs(scripts)
        gate = str(REPO_ROOT / 'global/hooks/supervisor-stop-gate')
        for stdin in ('{"hook_event_name": "Stop", "session_id": "s"}', 'not json', ''):
            r = subprocess.run([gate], input=stdin, capture_output=True, text=True, env=self.env, timeout=30)
            self.assertEqual((r.returncode, r.stdout), (0, ''))
        os.symlink(ENTRY, os.path.join(scripts, 'supervisor-lock'))
        r = subprocess.run([gate], input='{"hook_event_name": "Stop", "session_id": "s"}', capture_output=True,
                           text=True, env=self.env, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ''))


class SelfTestTest(Base):
    def test_the_self_test_refuses_paths_outside_its_sandbox(self):
        sandbox = self.mkdir('sandbox')
        r = self.run_cli('self-test', env={'SUPERVISOR_SELFTEST_SANDBOX': sandbox})
        self.assertEqual(r.returncode, 2)
        self.assertIn('SANDBOX REFUSED HOME', r.stderr)
        self.assertNotIn('\nok ', '\n' + r.stdout)
        r = self.run_cli('self-test', env={'SUPERVISOR_SELFTEST_SANDBOX': os.path.join(self.tmp, 'missing')})
        self.assertEqual(r.returncode, 2)
        self.assertIn('is not a directory', r.stderr)

    def test_a_sandboxed_child_refuses_a_state_path_set_outside(self):
        sandbox = self.mkdir('sandbox2')
        inside = {'HOME': os.path.join(sandbox, 'h'), 'TMPDIR': sandbox, 'XDG_RUNTIME_DIR': sandbox,
                  'CLAUDE_TOOLKIT_CONFIG_DIR': sandbox, 'SUPERVISOR_SELFTEST_SANDBOX': sandbox,
                  'SUPERVISOR_LOCK_HOME': os.path.join(self.tmp, 'outside')}
        os.makedirs(inside['HOME'])
        r = self.run_cli('self-test', env=inside)
        self.assertEqual(r.returncode, 2)
        self.assertIn('SANDBOX REFUSED supervisor state', r.stderr)
        self.assertNotIn('SANDBOX REFUSED HOME', r.stderr)

    def test_the_whole_self_test_passes_in_a_temp_home(self):
        env = {}
        if not SKILL.is_file():
            # the supervision skill ships with its own piece; without it only the installed-skill lint is skipped
            env['SUPERVISOR_SKIP_INSTALLED_LINT'] = '1'
        r = self.run_cli('self-test', env=env, timeout=1500)
        failed = [line for line in r.stdout.splitlines() if line.startswith('FAIL')]
        self.assertEqual(failed, [], r.stdout[-3000:] + r.stderr[-2000:])
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        checks = sum(1 for line in r.stdout.splitlines() if line.startswith('ok '))
        self.assertGreaterEqual(checks, 558 if SKILL.is_file() else 557)
        self.assertTrue(r.stdout.rstrip().endswith('ok: 0 failed'))
        self.assertFalse(os.listdir(self.env['TMPDIR']), 'the self-test left files in the temp dir')


if __name__ == '__main__':
    unittest.main()
