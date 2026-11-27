"""Tests of global/scripts/supervisor-lock: the thin entry point over the package global/scripts/lib/supervisor.

Every run uses a throwaway HOME, its own toolkit config and state paths inside a temp dir, with the variables that
could point at real state removed. None of the optional pieces (account-switch, cloud-tests, project-pause,
session-nudge, handoff-guard, routines) is present, so these tests also prove that the tool degrades without them.
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

from scripts.toolkit.paths import REPO_ROOT

ENTRY = str(REPO_ROOT / 'global/scripts/supervisor-lock')
SKILL = REPO_ROOT / 'global/skills/supervisa-sesiones/SKILL.md'
SUBCOMMANDS = ('project', 'registry-dir', 'acquire', 'reclaim', 'beat', 'release', 'open', 'closable', 'hold', 'cloud',
               'cloud-archive', 'cloud-send', 'status', 'backlog', 'skill-lint', 'wait-closer', 'mode', 'list',
               'sessions', 'wait', 'watchdog', 'titles', 'revive', 'hook', 'self-test')
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
                  'titles': list(s.QUESTIONS_TITLES), 'title': s.questions_title('p'), 'glob': s.APP_SESSIONS_GLOB,
                  'queued_min': s.QUEUED_REANNOUNCE_MIN, 'slotheld_min': s.SLOTHELD_REANNOUNCE_MIN,
                  'backoff_max_min': s.ALL_IDLE_BACKOFF_MAX_MIN,
                  'supervisor_title': s.supervisor_title('p'), 'closer_title': s.closer_title('p'),
                  'worker_title': s.worker_title('p', 'tarea'), 'suffix': s.REMOTE_PREVIOUS_SUFFIX,
                  'titles_sync': s.TITLES_SYNC}))
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
        self.assertEqual((got['queued_min'], got['slotheld_min'], got['backoff_max_min']), (120, 120, 120))
        self.assertEqual(got['anchors'][0], '## Prohibido')
        self.assertIn('## Motivo de la guardia', got['anchors'])

    def test_the_title_settings_default_and_can_be_overridden(self):
        got = self.settings()
        self.assertEqual((got['supervisor_title'], got['closer_title'], got['worker_title'], got['suffix'], got['titles_sync']),
                         ('Supervisora de p', 'Cierre de sesiones de p', 'p · tarea', ' (conexión anterior)', True))
        got = self.settings(json.dumps({'supervisor_session_title': 'Boss of {project}', 'worker_session_title': '{task} @ {project}',
                                        'remote_previous_suffix': ' (old)', 'titles_sync': False}))
        self.assertEqual((got['supervisor_title'], got['worker_title'], got['suffix'], got['titles_sync']),
                         ('Boss of p', 'tarea @ p', ' (old)', False))
        wrong = self.settings(json.dumps({'supervisor_session_title': '', 'closer_session_title': 3,
                                          'remote_previous_suffix': 7, 'titles_sync': 'no'}))
        self.assertEqual(wrong, self.settings('{}'))

    def test_the_default_titles_keep_the_role_recognisers_apart(self):
        out = self.python(LOADER + '''
import json
lock = load('supervisor_lock')
s, roles, util = lock._module('settings'), lock._module('session_roles'), lock._module('util')
questions = lambda t: any(util.fold_text(m) in util.fold_text(t) for m in roles.ASK_GATE_MAILBOX_TITLES)
closer = lambda t: any(c in util.fold_text(t) for c in s.CLOSER_TITLES)
titles = {'questions': s.questions_title('p'), 'closer': s.closer_title('p'),
          'supervisor': s.supervisor_title('p'), 'worker': s.worker_title('p', 'tarea')}
print(json.dumps({k: [questions(t), closer(t)] for k, t in titles.items()}))
''')
        self.assertEqual(json.loads(out), {'questions': [True, False], 'closer': [False, True],
                                           'supervisor': [False, False], 'worker': [False, False]})

    def test_a_corrupt_config_gives_the_defaults(self):
        self.assertEqual(self.settings('{not json'), self.settings('{}'))

    def test_mistyped_values_give_the_defaults_never_more_permission(self):
        got = self.settings(json.dumps({'deploy_preauthorised': 'yes', 'archive_preauthorised': 1,
                                        'presence_min': -5, 'fresh_min': 'x',
                                        'excluded_projects': 'p', 'skill_anchors': [1, 2]}))
        self.assertEqual(got, self.settings('{}'))

    def test_the_watcher_intervals_are_read_and_a_wrong_value_keeps_the_default(self):
        got = self.settings(json.dumps({'queued_reannounce_min': 10, 'slotheld_reannounce_min': 15.5,
                                        'all_idle_backoff_max_min': 45}))
        self.assertEqual((got['queued_min'], got['slotheld_min'], got['backoff_max_min']), (10, 15.5, 45))
        for bad in ('soon', -1, 0, True, None, [5], {'a': 1}):
            with self.subTest(bad=bad):
                got = self.settings(json.dumps({'queued_reannounce_min': bad, 'slotheld_reannounce_min': bad,
                                                'all_idle_backoff_max_min': bad}))
                self.assertEqual((got['queued_min'], got['slotheld_min'], got['backoff_max_min']), (120, 120, 120))
        got = self.settings('{"queued_reannounce_min": Infinity, "all_idle_backoff_max_min": NaN}')
        self.assertEqual((got['queued_min'], got['backoff_max_min']), (120, 120))

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


def rows_idle(*idles, status='idle'):
    """Census rows (only the fields the ALLIDLE rule reads) with these idle_s."""
    return [{'live': True, 'status': status, 'idle_s': i} for i in idles]


class AllIdleBackoffTest(Base):
    """watch.allidle_line: the quiet clock runs from the last activity, doubles while nothing moves, resets on
    activity and is recorded per project under <home>/announced."""

    def run_steps(self, steps, base=900, cap=7200, key='proj', blocked=False):
        """`steps`: [(now, idle_s list or None)]; the ALLIDLE line (or None) of each step, in one interpreter."""
        out = self.python(LOADER + f'''
import json
watch = load('supervisor_lock')._module('watch')
steps = {steps!r}
res = []
for now, idles in steps:
    rows = [{{'live': True, 'status': 'idle', 'idle_s': i}} for i in (idles or [])]
    res.append(watch.allidle_line({key!r}, rows, now, {base!r}, {cap!r}, 1000.0, (lambda: True) if {blocked!r} else None))
print(json.dumps(res))
''')
        return json.loads(out)

    def test_the_first_report_comes_at_the_threshold_and_the_next_ones_double_up_to_the_cap(self):
        # last activity at t=10000 (idle_s is `now - 10000` at every poll); the watcher first looks at that moment
        def at(quiet):
            return (10000 + quiet, [quiet])
        got = self.run_steps([at(0), at(899), at(900), at(901), at(1799), at(1800), at(3599), at(3600), at(7199),
                              at(7200), at(10800), at(14399), at(14400), at(21599), at(21600), at(28799), at(28800)])
        self.assertEqual(got, [None, None, 'ALLIDLE 900s', None, None, 'ALLIDLE 1800s', None, 'ALLIDLE 3600s', None,
                               'ALLIDLE 7200s', None, None, 'ALLIDLE 14400s', None, 'ALLIDLE 21600s', None,
                               'ALLIDLE 28800s'])

    def test_re_arming_does_not_restart_the_quiet_clock(self):
        # each call is a separate watcher process: the second one starts at 10901 and still needs only the
        # remaining 899 s of the doubled quiet time, not a fresh 900 or 1800 s from its own start
        first = self.run_steps([(10000, [0]), (10900, [900])])
        second = self.run_steps([(10901, [901]), (11800, [1800])])
        self.assertEqual((first, second), ([None, 'ALLIDLE 900s'], [None, 'ALLIDLE 1800s']))

    def test_re_arming_before_the_first_report_does_not_restart_the_clock_either(self):
        self.assertEqual(self.run_steps([(10000, [0]), (10500, [500])]), [None, None])
        self.assertEqual(self.run_steps([(10600, [600]), (10899, [899]), (10900, [900])]), [None, None, 'ALLIDLE 900s'])

    def test_any_activity_resets_the_back_off(self):
        # activity at t=10000: reports at 10900 and 11800 (900 s, then 1800 s). A session works at t=12000, so the
        # quiet time counts from there and the threshold is back to 900 s, then doubles again
        got = self.run_steps([(10000, [0]), (10900, [900]), (11800, [1800]), (12000, [0]), (12899, [899]),
                              (12900, [900]), (12901, [901]), (13799, [1799]), (13800, [1800])])
        self.assertEqual(got, [None, 'ALLIDLE 900s', 'ALLIDLE 1800s', None, None, 'ALLIDLE 900s', None, None,
                               'ALLIDLE 1800s'])

    def test_a_stretch_already_long_at_the_first_look_is_reported_after_the_threshold_and_does_not_repeat_at_once(self):
        # the project has been quiet since t=10000, but the watcher only looks at t=20000
        got = self.run_steps([(20000, [10000]), (20899, [10899]), (20900, [10900]), (20901, [10901]),
                              (21799, [11799]), (21800, [11800])])
        self.assertEqual(got, [None, None, 'ALLIDLE 10900s', None, None, 'ALLIDLE 11800s'])

    def test_the_cap_never_goes_below_the_base_threshold(self):
        got = self.run_steps([(10000, [0]), (10900, [900]), (10901, [901]), (11800, [1800]), (12700, [2700])],
                             base=900, cap=60)
        self.assertEqual(got, [None, 'ALLIDLE 900s', None, 'ALLIDLE 1800s', 'ALLIDLE 2700s'])

    def test_a_busy_session_or_a_zero_threshold_reports_nothing(self):
        out = self.python(LOADER + '''
import json
watch = load('supervisor_lock')._module('watch')
busy = [{'live': True, 'status': 'busy', 'idle_s': 5000}, {'live': True, 'status': 'idle', 'idle_s': 5000}]
dead_busy = lambda idle: [{'live': False, 'status': 'busy', 'idle_s': idle}]
idle = [{'live': True, 'status': 'idle', 'idle_s': 5000}]
print(json.dumps([watch.allidle_line('p', busy, 20000.0, 900, 7200, 0.0),
                  watch.allidle_line('p', idle, 20000.0, 0, 7200, 0.0),
                  watch.allidle_line('p', dead_busy(5000), 20000.0, 900, 7200, 0.0),
                  watch.allidle_line('p', dead_busy(5900), 20900.0, 900, 7200, 0.0)]))
''')
        self.assertEqual(json.loads(out), [None, None, None, 'ALLIDLE 5900s'])

    def test_a_blocked_report_is_not_recorded_so_it_fires_as_soon_as_it_is_unblocked(self):
        blocked = self.run_steps([(10000, [0]), (10900, [900]), (11800, [1800])], blocked=True)
        self.assertEqual(blocked, [None, None, None])
        with open(os.path.join(self.home, '.claude', 'supervisor', 'announced', 'proj.allidle.json')) as fh:
            self.assertEqual(json.load(fh)['count'], 0)
        self.assertEqual(self.run_steps([(11900, [1900])]), ['ALLIDLE 1900s'])

    def test_without_sessions_the_clock_runs_from_the_first_wait_and_survives_re_arming(self):
        # `started` is 1000: first report at 1900; the doubled threshold counts from the same start, so 2800
        got = self.run_steps([(1000, None), (1899, None), (1900, None), (1901, None), (2800, None), (2801, None)])
        self.assertEqual(got, [None, None, 'ALLIDLE 900s', None, 'ALLIDLE 1800s', None])

    def test_the_state_is_per_project_and_lives_under_announced(self):
        self.run_steps([(10000, [0]), (10900, [900])], key='one')
        self.assertEqual(self.run_steps([(10000, [0]), (10900, [900])], key='two'), [None, 'ALLIDLE 900s'])
        path = os.path.join(self.home, '.claude', 'supervisor', 'announced', 'one.allidle.json')
        with open(path) as fh:
            state = json.load(fh)
        self.assertEqual((state['activity'], state['count']), (10000.0, 1))

    def test_a_corrupt_state_file_starts_over(self):
        path = os.path.join(self.home, '.claude', 'supervisor', 'announced')
        os.makedirs(path)
        with open(os.path.join(path, 'proj.allidle.json'), 'w') as fh:
            fh.write('{not json')
        self.assertEqual(self.run_steps([(10000, [0]), (10900, [900])]), [None, 'ALLIDLE 900s'])


CLOUD_TESTS = str(REPO_ROOT / 'global/scripts/cloud-tests')


class TitlesBase(Base):
    """A project with a lock, app records in a folder of their own and the real cloud-tests script on a fake API."""

    def setUp(self):
        super().setUp()
        self.app = self.mkdir('app')
        self.api_file = os.path.join(self.tmp, 'api.json')
        self.cloud_env = {'SUPERVISOR_APP_SESSIONS_GLOB': os.path.join(self.app, '*', '*', 'local_*.json'),
                          'SUPERVISOR_CLOUD_TESTS': CLOUD_TESTS, 'CLOUD_TESTS_API_FAKE': self.api_file,
                          'CLOUD_TESTS_STATE': self.mkdir('ct-state'), 'SUPERVISOR_NUDGE': '', 'SUPERVISOR_NOTIFY': ''}
        self.env.update(self.cloud_env)
        self.repo_dir = self.repo('demo', 'https://github.com/t/demo.git')

    def record(self, local_id, title, cwd=None, bridges=(), account='acct', **extra):
        rec = {'sessionId': local_id, 'title': title, 'cwd': cwd or self.repo_dir, 'lastActivityAt': 5,
               'bridgeSessionIds': list(bridges), **extra}
        folder = self.mkdir(os.path.join('app', account, 'org'))
        path = os.path.join(folder, local_id + '.json')
        with open(path, 'w') as fh:
            json.dump(rec, fh)
        return path

    def bridge(self, cse_id, title, last='2026-11-27T10:00:00Z', kind='bridge', status='active'):
        return {'id': cse_id, 'title': title, 'status': status, 'environment_kind': kind, 'last_event_at': last,
                'worker_status': 'idle', 'status_bucket': 'completed',
                'config': {'sources': [{'url': 'https://github.com/t/demo'}]}}

    def api(self, *rows):
        with open(self.api_file, 'w') as fh:
            json.dump({'sessions': list(rows)}, fh)

    def api_state(self):
        with open(self.api_file) as fh:
            return json.load(fh)

    def take_lock(self, *extra):
        r = self.run_cli('acquire', '--dir', self.repo_dir, '--session', 'local_sup', *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_sup', '--mailbox', 'local_box',
                         '--closer', 'local_closer')
        self.assertEqual(r.returncode, 0, r.stderr)

    def lock_title(self):
        return json.loads(self.run_cli('status', '--dir', self.repo_dir, '--json').stdout)['title']


class LockTitleTest(TitlesBase):
    def test_acquire_without_a_title_uses_the_supervisor_title_of_the_project(self):
        self.take_lock()
        self.assertEqual(self.lock_title(), 'Supervisora de demo')

    def test_an_explicit_title_still_wins_and_a_resume_keeps_the_title_when_none_is_given(self):
        self.take_lock('--title', 'Mi supervisión')
        self.assertEqual(self.lock_title(), 'Mi supervisión')
        r = self.run_cli('acquire', '--dir', self.repo_dir, '--session', 'local_sup')
        self.assertIn('RESUMED', r.stdout)
        self.assertEqual(self.lock_title(), 'Mi supervisión')

    def test_a_title_that_looks_like_supervisor_lock_output_is_refused(self):
        self.take_lock()
        bad = ('HELD demo-1a2b session=local_x state=running', 'STALE k', '  MINE k', 'FREE k', 'ACQUIRED k', 'RESUMED k',
               'Algo session=local_abc', 'Algo heartbeat_age_s=3')
        for title in bad:
            with self.subTest(title=title):
                for args in (('acquire', '--session', 'local_new'),
                             ('reclaim', '--session', 'local_new', '--from', 'local_sup'),
                             ('beat', '--session', 'local_sup')):
                    r = self.run_cli(*args, '--dir', self.repo_dir, '--title', title)
                    self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))
                    self.assertIn('TITLE REFUSED', r.stderr)
        self.assertEqual(self.lock_title(), 'Supervisora de demo')
        for fine in ('Supervisora de demo', 'Helden de la guardia', 'FREEDOM'):
            r = self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_sup', '--title', fine)
            self.assertEqual(r.returncode, 0, (fine, r.stderr))
            self.assertEqual(self.lock_title(), fine)

    def test_beat_title_belongs_to_the_owner(self):
        self.take_lock()
        r = self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_other', '--title', 'Otra')
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.lock_title(), 'Supervisora de demo')


class RenameHintTest(TitlesBase):
    def test_beat_lists_the_sessions_that_carry_another_title(self):
        self.take_lock()
        self.record('local_sup', 'Supervisora de demo')
        self.record('local_box', 'Pregunta cualquiera')
        self.record('local_closer', 'Cierre')
        r = self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_sup', '--phase', 'F2')
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [ln for ln in r.stderr.splitlines() if ln.startswith('RENAME')]
        self.assertEqual(lines, [
            'RENAME local_box questions «Pregunta cualquiera» -> «Sesión de preguntas de demo»',
            'RENAME local_closer closer «Cierre» -> «Cierre de sesiones de demo»'])

    def test_no_line_when_the_titles_match_or_the_sessions_have_no_record(self):
        self.take_lock()
        r = self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_sup')
        self.assertEqual((r.returncode, r.stderr), (0, ''), r.stderr)
        self.record('local_sup', 'Supervisora de demo')
        self.record('local_box', 'Sesión de preguntas de demo')
        self.record('local_closer', 'Cierre de sesiones de demo')
        r = self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_sup')
        self.assertEqual((r.returncode, r.stderr), (0, ''))

    def test_titles_sync_off_silences_the_hint(self):
        with open(os.path.join(self.config, 'supervision.json'), 'w') as fh:
            json.dump({'titles_sync': False}, fh)
        self.take_lock()
        self.record('local_sup', 'Otro')
        r = self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_sup')
        self.assertEqual((r.returncode, r.stderr), (0, ''))


class TitlesCommandTest(TitlesBase):
    def titles(self, *args):
        r = self.run_cli('titles', *args)
        self.assertNotIn('Traceback', r.stderr)
        return r

    def test_it_lists_a_rename_per_role_and_never_edits_the_app_records(self):
        self.take_lock()
        paths = [self.record('local_sup', 'Vieja'), self.record('local_box', 'Vieja 2'),
                 self.record('local_closer', 'Cierre de sesiones de demo')]
        def read_all():
            data = []
            for path in paths:
                with open(path, 'rb') as fh:
                    data.append(fh.read())
            return data
        before = read_all()
        r = self.titles('--fix')
        self.assertEqual(r.returncode, 0, r.stderr)
        renames = [ln for ln in r.stdout.splitlines() if ln.startswith('RENAME')]
        self.assertEqual(renames, ['RENAME local_sup supervisor «Vieja» -> «Supervisora de demo»',
                                   'RENAME local_box questions «Vieja 2» -> «Sesión de preguntas de demo»'])
        self.assertEqual(read_all(), before)

    def test_fix_rewrites_only_the_lock_title(self):
        self.take_lock('--title', 'Supervisión 2026')
        self.record('local_sup', 'Supervisora de demo')
        r = self.titles()
        self.assertIn('LOCK demo', r.stdout)
        self.assertIn('«Supervisión 2026» -> «Supervisora de demo»', r.stdout)
        self.assertEqual(self.lock_title(), 'Supervisión 2026')
        self.titles('--fix')
        self.assertEqual(self.lock_title(), 'Supervisora de demo')
        self.assertNotIn('LOCK demo', self.titles().stdout)

    def test_a_corrupted_lock_title_is_repaired(self):
        self.take_lock()
        lock_dir = os.path.join(self.home, '.claude', 'supervisor', 'locks')
        path = os.path.join(lock_dir, os.listdir(lock_dir)[0])
        with open(path) as fh:
            lock = json.load(fh)
        lock['title'] = 'STALE demo session=local_sup state=running'
        with open(path, 'w') as fh:
            json.dump(lock, fh)
        self.titles('--fix')
        self.assertEqual(self.lock_title(), 'Supervisora de demo')

    def test_session_limits_the_output_to_that_project_and_an_unknown_one_is_an_error(self):
        other = self.repo('other', 'https://github.com/t/other.git')
        self.take_lock()
        r = self.run_cli('acquire', '--dir', other, '--session', 'local_osup')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.record('local_sup', 'Uno')
        self.record('local_osup', 'Dos', cwd=other)
        both = self.titles().stdout
        self.assertIn('local_sup', both)
        self.assertIn('local_osup', both)
        mine = self.titles('--session', 'local_box').stdout
        self.assertIn('RENAME local_sup', mine)
        self.assertNotIn('local_osup', mine)
        self.assertNotIn('«Dos»', mine)
        r = self.titles('--session', 'local_unknown')
        self.assertEqual(r.returncode, 2)

    def test_remote_control_copies_follow_the_local_title_and_older_ones_say_so(self):
        self.take_lock()
        self.record('local_work', 'demo · tarea', bridges=['session_NEW', 'session_OLD'])
        self.record('local_untitled', '', bridges=['session_BLANK'])
        self.api(self.bridge('cse_NEW', 'host-example-brave-otter', last='2026-11-27T11:00:00Z'),
                 self.bridge('cse_OLD', 'Título antiguo', last='2026-11-20T11:00:00Z'),
                 self.bridge('cse_BLANK', 'Se queda', last='2026-11-20T11:00:00Z'),
                 self.bridge('cse_STRANGER', 'Sin ficha local'),
                 self.bridge('cse_DONE', 'Archivada', status='archived'),
                 self.bridge('cse_CLOUD', 'Nube', kind='anthropic_cloud'))
        r = self.titles()
        self.assertEqual(r.returncode, 0, r.stderr)
        remote = [ln for ln in r.stdout.splitlines() if ln.startswith('REMOTE')]
        self.assertEqual(remote, ['REMOTE cse_NEW «host-example-brave-otter» -> «demo · tarea»',
                                  'REMOTE cse_OLD «Título antiguo» -> «demo · tarea (conexión anterior)»'])
        self.assertNotIn('renamed', self.api_state())
        self.titles('--fix')
        state = self.api_state()
        self.assertEqual(sorted(state['renamed']),
                         [['cse_NEW', 'demo · tarea'], ['cse_OLD', 'demo · tarea (conexión anterior)']])
        titles = {x['id']: x['title'] for x in state['sessions']}
        self.assertEqual((titles['cse_BLANK'], titles['cse_STRANGER'], titles['cse_CLOUD']),
                         ('Se queda', 'Sin ficha local', 'Nube'))
        # the shared cache already holds the new titles: the next run has nothing to rename and calls nothing
        again = self.titles('--fix')
        self.assertEqual([ln for ln in again.stdout.splitlines() if ln.startswith('REMOTE')], [])
        self.assertEqual(len(self.api_state()['renamed']), 2)

    def test_a_remote_copy_with_a_local_title_that_looks_like_lock_output_is_left_alone(self):
        self.record('local_bad', 'HELD demo session=local_x', bridges=['session_X'])
        self.api(self.bridge('cse_X', 'Nombre'))
        self.titles('--fix')
        self.assertNotIn('renamed', self.api_state())

    def adopt_lines(self, **kw):
        r = self.titles('--session', 'local_sup')
        self.assertEqual(r.returncode, 0, r.stderr)
        return [ln for ln in r.stdout.splitlines() if ln.startswith('ADOPT')]

    def test_adopt_lists_the_helpers_that_are_not_children_of_the_supervisor(self):
        self.take_lock()
        self.record('local_sup', 'Supervisora de demo')
        box = ('local_box', 'Sesión de preguntas de demo')
        closer = ('local_closer', 'Cierre de sesiones de demo')
        # children of the owner: nothing
        self.record(*box, spawnedFrom={'sessionId': 'local_sup'})
        self.record(*closer, spawnedFrom={'sessionId': 'local_sup'}, lineageDetached=False)
        self.assertEqual(self.adopt_lines(), [])
        # opened by another session (a previous supervisor): ADOPT, naming the parent
        self.record(*box, spawnedFrom={'sessionId': 'local_old'})
        self.assertEqual(self.adopt_lines(), ['ADOPT local_box questions (abierta por local_old)'])
        # moved to the top level: ADOPT, even when it was once the owner's child
        self.record(*closer, spawnedFrom={'sessionId': 'local_sup'}, lineageDetached=True)
        self.assertEqual(self.adopt_lines(), ['ADOPT local_box questions (abierta por local_old)',
                                              'ADOPT local_closer closer (abierta por local_sup)'])
        self.record(*closer, lineageDetached=True)
        self.assertEqual(self.adopt_lines()[1], 'ADOPT local_closer closer (abierta por -)')

    def test_adopt_prints_nothing_without_a_record_or_without_the_fields(self):
        self.take_lock()
        self.assertEqual(self.adopt_lines(), [])                      # no records at all
        self.record('local_sup', 'Supervisora de demo', spawnedFrom={'sessionId': 'local_elsewhere'}, lineageDetached=True)
        self.record('local_box', 'Sesión de preguntas de demo')       # neither field
        self.record('local_closer', 'Cierre de sesiones de demo', spawnedFrom={})
        self.assertEqual(self.adopt_lines(), [])                      # the supervisor itself is never adopted

    def test_beat_shows_the_adopt_lines_too(self):
        self.take_lock()
        self.record('local_sup', 'Supervisora de demo')
        self.record('local_box', 'Sesión de preguntas de demo', spawnedFrom={'sessionId': 'local_old'})
        self.record('local_closer', 'Cierre de sesiones de demo', lineageDetached=True)
        r = self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_sup')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([ln for ln in r.stderr.splitlines() if ln.startswith(('ADOPT', 'RENAME'))],
                         ['ADOPT local_box questions (abierta por local_old)', 'ADOPT local_closer closer (abierta por -)'])

    def test_one_unreadable_lock_does_not_stop_the_other_work(self):
        self.take_lock()
        self.record('local_sup', 'Vieja')
        lock_dir = os.path.join(self.home, '.claude', 'supervisor', 'locks')
        with open(os.path.join(lock_dir, 'broken.json'), 'w') as fh:
            json.dump({'session_id': 'local_broken', 'project': 'x'}, fh)   # no `key`
        r = self.titles('--fix')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('unreadable', r.stdout)
        self.assertIn('RENAME local_sup', r.stdout)
        self.assertEqual(self.lock_title(), 'Supervisora de demo')

    def test_without_the_provider_or_the_api_it_says_so_and_exits_zero(self):
        self.take_lock()
        self.record('local_sup', 'Vieja')
        self.env['SUPERVISOR_CLOUD_TESTS'] = os.path.join(self.tmp, 'missing')
        r = self.titles('--fix')
        self.assertEqual(r.returncode, 0)
        self.assertIn('REMOTE unavailable', r.stdout)
        self.assertEqual(self.lock_title(), 'Supervisora de demo')
        # the provider is present but the API refuses to answer
        self.env.update(SUPERVISOR_CLOUD_TESTS=CLOUD_TESTS, CLOUD_TESTS_API_FAKE='',
                        CLOUD_TESTS_CREDENTIALS=os.path.join(self.tmp, 'no-login.json'),
                        CLOUD_TESTS_API='http://127.0.0.1:9')
        r = self.titles('--fix')
        self.assertEqual(r.returncode, 0)
        self.assertIn('REMOTE unavailable', r.stdout)

    def test_http_403_and_404_are_skipped_and_counted_and_other_errors_reported(self):
        self.record('local_a', 'Uno', bridges=['session_A'])
        self.record('local_b', 'Dos', bridges=['session_B'])
        self.record('local_c', 'Tres', bridges=['session_C'])
        self.api(self.bridge('cse_A', 'x'), self.bridge('cse_B', 'x'), self.bridge('cse_C', 'x'))
        out = self.python(LOADER + '''
import json
lock = load('supervisor_lock')
titles, providers = lock._module('titles'), lock._module('providers')
ct = providers.cloud_tests_module()
codes = {'cse_A': 403, 'cse_B': 404, 'cse_C': 500}
listing = ct.api_call
ct.api_call = (lambda method, path, body=None: listing(method, path, body) if method == 'GET'
               else (codes[path.rsplit('/', 1)[1]], {}))
lines = []
counts = titles.sync_remote(titles.app_records(), True, lines.append)
print(json.dumps([counts, lines]))
''', env=self.cloud_env)
        counts, lines = json.loads(out)
        self.assertEqual(counts, {'fixed': 0, 'skipped': 2, 'failed': 1})
        self.assertIn('REMOTE cse_C HTTP 500', lines)
        self.assertTrue(any(ln.startswith('REMOTE skipped 2') for ln in lines), lines)
        self.assertFalse(any('unavailable' in ln for ln in lines), lines)


class WatchdogTitlesTest(TitlesBase):
    def setUp(self):
        super().setUp()
        self.take_lock('--title', 'Supervisión 2026')
        self.record('local_work', 'demo · tarea', bridges=['session_NEW'])
        self.api(self.bridge('cse_NEW', 'host-example-calm-fox'))

    def test_a_watchdog_run_renames_the_bridge_and_the_lock_without_adding_output(self):
        base = self.run_cli('watchdog', env={'SUPERVISOR_WATCHDOG_CLOUD': '0', 'CLOUD_TESTS_API_FAKE': ''})
        self.assertEqual(base.returncode, 0, base.stderr)
        self.assertEqual(self.lock_title(), 'Supervisora de demo')   # the lock title is repaired even with no cloud
        r = self.run_cli('watchdog')
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, base.stdout, ''))
        self.assertEqual(self.api_state()['renamed'], [['cse_NEW', 'demo · tarea']])

    def test_titles_sync_off_leaves_everything_as_it_was(self):
        with open(os.path.join(self.config, 'supervision.json'), 'w') as fh:
            json.dump({'titles_sync': False}, fh)
        r = self.run_cli('watchdog')
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertNotIn('renamed', self.api_state())
        self.assertEqual(self.lock_title(), 'Supervisión 2026')

    def test_a_failing_sync_is_one_line_and_never_changes_the_exit_code(self):
        out = self.python(LOADER + '''
import argparse, io, contextlib
lock = load('supervisor_lock')
watchdog, titles = lock._module('watchdog'), lock._module('titles')
def boom():
    raise RuntimeError('broken on purpose')
titles.watchdog_sync = boom
args = argparse.Namespace(notify=False, nudge=False, dead_after=600, stale_after=2700, realert_after=0)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = watchdog.cmd_watchdog_with_nudge(args)
print(code, repr(buf.getvalue()))
''', env=self.cloud_env)
        self.assertEqual(out.strip(), "0 'TITLES-FAILED broken on purpose\\n'")


class FakeHeavyJob(Base):
    """A fake `heavy-job` that prints a JSON status for `status --json`."""

    def fake_heavy(self, payload, name='fake-heavy'):
        path = os.path.join(self.tmp, name)
        with open(path + '.json', 'w') as fh:
            fh.write(payload if isinstance(payload, str) else json.dumps(payload))
        with open(path, 'w') as fh:
            fh.write(f'#!/bin/sh\ncat {path}.json\n')
        os.chmod(path, 0o755)
        return path


class QueuedJobSuppressesAllIdleTest(FakeHeavyJob):
    def waiting(self, repo, heavy, *extra):
        r = self.run_cli('wait', '--dir', repo, '--interval', '0.2', '--timeout', '3', '--all-idle-after', '1', *extra,
                         env={'SUPERVISOR_HEAVY_JOB': heavy}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def queue_of(self, pid, extra_jobs=()):
        return {'queue': [{'pid': pid, 'position': 1, 'label': 'suite', 'project': 'p',
                           'queued': '2026-11-26T10:00:00'}], 'jobs': list(extra_jobs), 'light': {'queue': [], 'jobs': []}}

    def test_a_job_of_the_project_waiting_in_the_machine_queue_holds_ALLIDLE_back(self):
        repo = self.repo('proj')
        sleeper = subprocess.Popen(['sleep', '60'], cwd=repo)
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.terminate)
        elsewhere = subprocess.Popen(['sleep', '60'], cwd=self.mkdir('elsewhere'))
        self.addCleanup(elsewhere.wait)
        self.addCleanup(elsewhere.terminate)
        queued = self.fake_heavy(self.queue_of(sleeper.pid), 'queued')
        self.assertEqual(self.waiting(repo, queued), ['TIMEOUT', '3s'])
        other = self.fake_heavy(self.queue_of(elsewhere.pid), 'other')
        got = self.waiting(repo, other)
        self.assertEqual(got[0], 'ALLIDLE', got)

    def test_without_a_readable_heavy_job_the_watcher_behaves_as_before(self):
        repo = self.repo('proj')
        for heavy in (os.path.join(self.tmp, 'missing'), self.fake_heavy('not json', 'garbage'),
                      self.fake_heavy('[1, 2]', 'listing'), self.fake_heavy({'queue': 'x', 'jobs': 5}, 'odd')):
            with self.subTest(heavy=os.path.basename(heavy)):
                got = self.waiting(repo, heavy)
                self.assertEqual(got[0], 'ALLIDLE', got)
                os.remove(os.path.join(self.home, '.claude', 'supervisor', 'announced',
                                       next(n for n in os.listdir(os.path.join(self.home, '.claude', 'supervisor', 'announced'))
                                            if n.endswith('.allidle.json'))))

    def test_project_job_queued_is_a_plain_yes_or_no(self):
        repo = self.repo('proj')
        out = self.python(LOADER + f'''
import json
lock = load('supervisor_lock')
mq, projects = lock._module('machine_queue'), lock._module('projects')
project = projects.resolve({repo!r})
mq.proc_cwd = lambda pid: {repo!r} if pid == 1 else '/nowhere'
q = lambda pid: {{'queue': [{{'pid': pid, 'queued': '2026-11-26T10:00:00'}}], 'jobs': [], 'light': {{'queue': [], 'jobs': []}}}}
light = {{'queue': [], 'jobs': [], 'light': {{'queue': [{{'pid': 1}}], 'jobs': []}}}}
print(json.dumps([mq.project_job_queued(project, q(1)), mq.project_job_queued(project, q(2)),
                  mq.project_job_queued(project, light), mq.project_job_queued(project, {{}}),
                  mq.project_job_queued(project, {{'queue': 'x'}}), mq.project_job_queued(project, [1])]))
''')
        self.assertEqual(json.loads(out), [True, False, True, False, False, False])


class ReannounceIntervalTest(Base):
    """QUEUED and SLOTHELD repeat an unchanged item after queued_reannounce_min / slotheld_reannounce_min (default 120)."""

    def announce(self, offsets_min, config=None):
        repo = self.repo('proj')
        if config is not None:
            with open(os.path.join(self.config, 'supervision.json'), 'w') as fh:
                json.dump(config, fh)
        out = self.python(LOADER + f'''
import json
lock = load('supervisor_lock')
mq, projects = lock._module('machine_queue'), lock._module('projects')
project = projects.resolve({repo!r})
mq.proc_cwd = lambda pid: {repo!r}
now = 1_800_000_000.0
def iso(ago):
    import time
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now - ago))
res = []
for minutes in {offsets_min!r}:
    t = now + minutes * 60
    # a job queued since 30 min before `now`, and a project job holding a slot since 3 h before `now` while it waits
    state = {{'queue': [{{'pid': 7, 'position': 1, 'label': 'mine', 'project': 'proj', 'queued': iso(1800)}}],
             'jobs': [{{'pid': 8, 'slots': [0], 'label': 'held', 'project': 'proj', 'cwd': {repo!r},
                        'started_ts': now - 3 * 3600}}], 'light': {{'queue': [], 'jobs': []}}}}
    lines = mq.heavy_events(project, state, t)
    res.append([l.split(' ', 1)[0] for l in lines])
print(json.dumps(res))
''')
        return json.loads(out)

    def test_an_unchanged_item_is_announced_first_and_again_after_the_default_two_hours(self):
        both = ['QUEUED', 'SLOTHELD']
        self.assertEqual(self.announce([0, 1, 30, 60, 119, 120, 121, 239, 240]),
                         [both, [], [], [], [], both, [], [], both])

    def test_the_configured_intervals_apply_to_each_kind(self):
        got = self.announce([0, 9, 10, 14, 15, 20, 25, 30],
                            {'queued_reannounce_min': 10, 'slotheld_reannounce_min': 15})
        self.assertEqual(got, [['QUEUED', 'SLOTHELD'], [], ['QUEUED'], [], ['SLOTHELD'], ['QUEUED'], [], ['QUEUED', 'SLOTHELD']])

    def test_a_wrong_interval_keeps_the_default(self):
        got = self.announce([0, 119, 120], {'queued_reannounce_min': 'soon', 'slotheld_reannounce_min': -3})
        self.assertEqual(got, [['QUEUED', 'SLOTHELD'], [], ['QUEUED', 'SLOTHELD']])


ASK_QUEUE = str(REPO_ROOT / 'global/scripts/ask-queue')


class AskDueTest(Base):
    """ASKDUE: ask-queue says when the project's partial batch of blocking questions may be sent; beat and the
    watcher tell the lock owner, once per set of due ids on the watcher, and say nothing when the queue is unreadable."""

    def setUp(self):
        super().setUp()
        self.env.update(ASK_QUEUE_BIN=ASK_QUEUE, SUPERVISOR_NUDGE='', SUPERVISOR_NOTIFY='',
                        SUPERVISOR_APP_SESSIONS_GLOB=os.path.join(self.mkdir('app'), '*', '*', 'local_*.json'))
        self.repo_dir = self.repo('proj')
        r = self.run_cli('acquire', '--dir', self.repo_dir, '--session', 'local_sup')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.beat().returncode, 0)

    def beat(self, env=None):
        return self.run_cli('beat', '--dir', self.repo_dir, '--session', 'local_sup', '--mailbox', 'local_box', env=env)

    def queue(self, *args):
        r = subprocess.run([sys.executable, ASK_QUEUE, *args], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def add(self, question, *extra, blocks='la tarea ordenada'):
        return self.queue('add', '--project', self.repo_dir, '--question', question, '--default', 'Esperar',
                          '--why', 'solo lo sabe el desarrollador', '--blocks', blocks, *extra)

    def test_beat_tells_the_owner_on_stderr_when_an_ordered_item_is_due(self):
        self.assertNotIn('ASKDUE', self.beat().stderr)
        qid = self.add('¿Qué cuenta uso?', '--order', 'hazlo primero')
        r = self.beat()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith('BEAT '))
        line = next(l for l in r.stderr.splitlines() if l.startswith('ASKDUE'))
        self.assertTrue(line.startswith(f'ASKDUE 1 {qid} '), line)
        for needle in ('tanda parcial', 'ask-queue list --due', 'ask-queue asked <ids> --to', self.repo_dir):
            self.assertIn(needle, line)
        self.queue('asked', qid, '--to', 'local_box')
        self.assertNotIn('ASKDUE', self.beat().stderr)

    def test_a_young_item_or_a_closed_window_says_nothing(self):
        self.add('¿Joven?')
        self.add('¿No bloquea?', blocks='nada')
        self.assertNotIn('ASKDUE', self.beat().stderr)
        old = self.add('¿Vieja?')
        presented = self.add('¿Presentada?')
        self.queue('asked', presented, '--to', 'local_box')
        with open(os.path.join(self.config, 'supervision.json'), 'w') as fh:
            json.dump({'ask_due_after_h': 0}, fh)  # every item that blocks work is due at once
        self.assertNotIn('ASKDUE', self.beat().stderr)  # ...but a batch was just presented: the window is closed
        with open(os.path.join(self.config, 'supervision.json'), 'w') as fh:
            json.dump({'ask_due_after_h': 0, 'ask_partial_batch_window_h': 0}, fh)
        line = next(l for l in self.beat().stderr.splitlines() if l.startswith('ASKDUE'))
        self.assertIn(old, line)

    def test_the_watcher_announces_a_set_once_and_a_set_with_a_new_id_at_once(self):
        first = self.add('¿Uno?', '--order', 'ya')
        code = LOADER + f'''
import json
lock = load('supervisor_lock')
askdue, projects = lock._module('askdue'), lock._module('projects')
project = projects.resolve({self.repo_dir!r})
print(json.dumps([askdue.askdue_events(project, now=1000.0), askdue.askdue_events(project, now=1000.0 + 3600)]))
'''
        once, again = json.loads(self.python(code))
        self.assertEqual(len(once), 1)
        self.assertTrue(once[0].startswith(f'ASKDUE 1 {first} '))
        self.assertEqual(again, [])
        second = self.add('¿Dos?', '--order', 'también')
        later, = json.loads(self.python(code))[:1]
        self.assertEqual(len(later), 1)
        self.assertTrue(later[0].startswith('ASKDUE 2 '))
        self.assertIn(second, later[0])

    def test_the_watcher_reports_it_also_on_guard(self):
        qid = self.add('¿Uno?', '--order', 'ya')
        for extra in ((), ('--guard',)):
            with self.subTest(extra=extra):
                r = self.run_cli('wait', '--dir', self.repo_dir, '--owner', 'local_sup', '--interval', '0.2',
                                 '--timeout', '5', '--all-idle-after', '0', *extra, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(r.stdout.startswith(f'ASKDUE 1 {qid} '), r.stdout)
                os.remove(os.path.join(self.home, '.claude', 'supervisor', 'announced',
                                       json.loads(self.run_cli('project', '--dir', self.repo_dir, '--json').stdout)['key']
                                       + '.askdue.json'))

    def test_without_a_readable_queue_beat_and_the_watcher_are_unchanged(self):
        self.add('¿Uno?', '--order', 'ya')
        missing = {'ASK_QUEUE_BIN': os.path.join(self.tmp, 'no-ask-queue')}
        r = self.beat(env=missing)
        self.assertEqual((r.returncode, 'ASKDUE' in r.stderr), (0, False))
        r = self.run_cli('wait', '--dir', self.repo_dir, '--owner', 'local_sup', '--interval', '0.2', '--timeout', '1',
                         '--all-idle-after', '0', env=missing, timeout=60)
        self.assertEqual(r.stdout.split(), ['TIMEOUT', '1s'])
        self.assertFalse(os.path.exists(os.path.join(self.home, '.claude', 'supervisor', 'askdue-errors.log')))


class AskDueTextsTest(Base):
    """The deny texts name the partial batch next to the radical path and teach --blocks and --order."""

    def test_deny_texts(self):
        out = self.python(LOADER + '''
import json
lock = load('supervisor_lock')
deny, roles = lock._module('deny'), lock._module('session_roles')
reason = lambda text: json.loads(text)['hookSpecificOutput']['permissionDecisionReason']
roles.mailbox_alive = lambda mailbox: True
owner = reason(deny.deny_question({'project': 'p', 'key': 'k', 'mailbox': 'local_box'}, 'local_me'))
print(json.dumps({'owner': owner, 'absent': reason(deny.deny_absent(20)),
                  'supervised': reason(deny.deny_supervised({'project': 'p', 'key': 'k'}, 20))}))
''')
        texts = json.loads(out)
        for needle in ('radical por unanimidad', '--radical --cost', 'tanda parcial', 'ask-queue list --due', 'ASKDUE'):
            self.assertIn(needle, texts['owner'])
        for name in ('absent', 'supervised'):
            with self.subTest(name=name):
                for needle in ('--order "<sus palabras>"', 'tanda parcial', '--blocks',
                               'sesión hija está archivada o aparcada con su decisión en ask-queue'):
                    self.assertIn(needle, texts[name])
        self.assertFalse(any('\n' in t for t in texts.values()))

    def test_askdue_is_a_guard_event_and_the_archive_template_blocks_nothing(self):
        out = self.python(LOADER + '''
lock = load('supervisor_lock')
print('ASKDUE' in lock._module('watch').GUARD_EVENTS)
''')
        self.assertEqual(out.strip(), 'True')
        source = (REPO_ROOT / 'global/scripts/lib/supervisor/closable.py').read_text(encoding='utf-8')
        self.assertIn('--blocks "nada: solo su archivado"', source)


class WakeJournalTest(Base):
    """wakes.py and `wait --owner`: every run of the watcher leaves one record of its wake beside the lock."""
    DAY = 86400

    def setUp(self):
        super().setUp()
        self.env.update(SUPERVISOR_NUDGE='', SUPERVISOR_NOTIFY='',
                        SUPERVISOR_APP_SESSIONS_GLOB=os.path.join(self.mkdir('app'), '*', '*', 'local_*.json'))
        self.sup_home = os.path.join(self.home, '.claude', 'supervisor')

    def wakes_py(self, body):
        """Run `body` with `wakes` loaded; its stdout."""
        return self.python(LOADER + "wakes = load('supervisor_lock')._module('wakes')\n" + body)

    def journal(self, key):
        return os.path.join(self.sup_home, 'wakes', key + '.jsonl')

    def locked_repo(self):
        repo = self.repo('proj')
        r = self.run_cli('acquire', '--dir', repo, '--session', 'local_sup')
        self.assertEqual(r.returncode, 0, r.stderr)
        key = json.loads(self.run_cli('project', '--dir', repo, '--json').stdout)['key']
        return repo, key

    def wait(self, repo, *extra):
        return self.run_cli('wait', '--dir', repo, *extra, '--interval', '0.2', '--timeout', '1',
                            '--all-idle-after', '0')

    def raw(self, key):
        with open(self.journal(key), 'rb') as fh:
            return fh.read()

    def lines(self, key):
        with open(self.journal(key), encoding='utf-8') as fh:
            return fh.read().splitlines()

    def test_a_record_reads_back_with_owner_utc_times_and_the_lines_in_order(self):
        got = json.loads(self.wakes_py('''
import json
wakes.record('proj', 'local_a', 1795766400.123, 1795766460.5, ['NEW local_b', 'TURN local_b 1->2'])
print(json.dumps(wakes.read('proj')))
'''))
        self.assertEqual(got, [{'owner': 'local_a', 'started': '2026-11-27T08:00:00.123Z',
                                'ended': '2026-11-27T08:01:00.500Z', 'events': ['NEW local_b', 'TURN local_b 1->2']}])
        self.assertEqual(self.wakes_py("print(wakes.read('other'))").strip(), '[]')

    def test_records_older_than_thirty_days_are_dropped_on_the_next_record(self):
        now = 1795766400.0
        old, young = now - 31 * self.DAY, now - 29 * self.DAY
        out = self.wakes_py(f'''
import json
wakes.record('proj', 'local_a', {old} - 5, {old}, ['OLD'], now={old})
wakes.record('proj', 'local_a', {young} - 5, {young}, ['YOUNG'], now={young})
wakes.record('proj', 'local_a', {now} - 5, {now}, ['NEW'], now={now})
print(json.dumps([r['events'] for r in wakes.read('proj')]))
''')
        self.assertEqual(json.loads(out), [['YOUNG'], ['NEW']])

    def test_an_append_with_nothing_old_keeps_the_earlier_lines_byte_for_byte(self):
        now = 1795766400.0
        self.wakes_py(f"wakes.record('proj', 'local_a', {now} - 9, {now} - 8, ['ONE'], now={now})")
        before = self.lines('proj')
        # an unparseable line that is not first survives an append: only a rewrite would drop it
        with open(self.journal('proj'), 'a', encoding='utf-8') as fh:
            fh.write('not json\n')
        raw = self.raw('proj')
        self.wakes_py(f"wakes.record('proj', 'local_a', {now} - 2, {now} - 1, ['TWO'], now={now})")
        after = self.raw('proj')
        self.assertTrue(after.startswith(raw))
        self.assertEqual(self.lines('proj')[0], before[0])
        self.assertEqual(len(self.lines('proj')), 3)

    def test_a_rewrite_drops_unparseable_lines_and_keeps_the_mode(self):
        now = 1795766400.0
        os.makedirs(os.path.dirname(self.journal('proj')), exist_ok=True)
        with open(self.journal('proj'), 'w', encoding='utf-8') as fh:
            fh.write('garbage\n')
        self.wakes_py(f"wakes.record('proj', 'local_a', {now} - 2, {now} - 1, ['TWO'], now={now})")
        self.assertEqual(len(self.lines('proj')), 1)
        self.assertEqual(os.stat(self.journal('proj')).st_mode & 0o777, 0o600)

    def test_the_journal_file_is_private(self):
        self.wakes_py("wakes.record('proj', 'local_a', 1.0, 2.0, ['X'], now=2.0)")
        self.assertEqual(os.stat(self.journal('proj')).st_mode & 0o777, 0o600)
        os.chmod(self.journal('proj'), 0o644)
        self.wakes_py("wakes.record('proj', 'local_a', 3.0, 4.0, ['Y'], now=4.0)")
        self.assertEqual(os.stat(self.journal('proj')).st_mode & 0o777, 0o600)

    def test_wait_journals_what_it_printed_and_prints_the_same_as_before(self):
        repo, key = self.locked_repo()
        r = self.wait(repo, '--owner', 'local_sup')
        self.assertEqual((r.returncode, r.stdout), (0, 'TIMEOUT 1s\n'), r.stderr)
        recs = [json.loads(l) for l in self.lines(key)]
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual((rec['owner'], rec['events']), ('local_sup', ['TIMEOUT 1s']))
        stamps = [datetime.strptime(rec[k], '%Y-%m-%dT%H:%M:%S.%fZ') for k in ('started', 'ended')]
        self.assertLessEqual(*stamps)

    def test_a_second_wait_appends_a_second_record(self):
        repo, key = self.locked_repo()
        for _ in range(2):
            self.assertEqual(self.wait(repo, '--owner', 'local_sup').returncode, 0)
        self.assertEqual(len(self.lines(key)), 2)

    def test_wait_without_an_owner_writes_no_journal(self):
        repo, key = self.locked_repo()
        r = self.wait(repo)
        self.assertEqual((r.returncode, r.stdout), (0, 'TIMEOUT 1s\n'), r.stderr)
        self.assertFalse(os.path.exists(self.journal(key)))

    def test_the_journal_changes_neither_list_nor_status_and_survives_release(self):
        repo, key = self.locked_repo()
        def shown():   # the heartbeat age ticks with the clock: masked
            return [re.sub(r'heartbeat_age_s=\d+', 'heartbeat_age_s=N', self.run_cli(*cmd).stdout)
                    for cmd in (('list',), ('status', '--dir', repo))]
        before = shown()
        self.assertEqual(self.wait(repo, '--owner', 'local_sup').returncode, 0)
        self.assertTrue(os.path.exists(self.journal(key)))
        after = shown()
        self.assertEqual(after, before)
        content = self.raw(key)
        r = self.run_cli('release', '--dir', repo, '--session', 'local_sup')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.raw(key), content)

    def test_a_journal_failure_does_not_change_how_wait_ends(self):
        repo, key = self.locked_repo()
        os.makedirs(self.journal(key))   # the journal path cannot be opened as a file
        r = self.wait(repo, '--owner', 'local_sup')
        self.assertEqual((r.returncode, r.stdout), (0, 'TIMEOUT 1s\n'), r.stderr)
        with open(os.path.join(self.sup_home, 'wait-errors.log'), encoding='utf-8') as fh:
            self.assertIn('wakes.py', fh.read())


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

    def test_a_supervisor_on_guard_is_stalled_only_when_its_turn_was_cut_by_the_limit(self):
        # the process of a cut supervisor stays alive and its heartbeat stays still, which on guard is normal: only the
        # limit's error as the newest record of its main transcript tells the two apart
        lock_home, projects = self.mkdir('sup-home'), self.mkdir('sup-projects')
        out = self.python(LOADER + '''
import datetime, json, os, time
lock = load('supervisor_lock')
revival = lock._module('revival')
home, projects = os.environ['SUPERVISOR_LOCK_HOME'], os.environ['SUPERVISOR_PROJECTS_DIR']
now = time.time()
iso = lambda ago: time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now - ago)) + '.000Z'
beat = lambda ago: datetime.datetime.fromtimestamp(now - ago).astimezone().isoformat(timespec='seconds')
text = {'role': 'assistant', 'content': [{'type': 'text', 'text': "You've hit your limit"}]}
fine = [{'type': 'assistant', 'timestamp': iso(4000), 'message': text}]
cut = fine + [{'type': 'assistant', 'timestamp': iso(3900), 'isApiErrorMessage': True, 'error': 'rate_limit',
               'message': text}]
os.makedirs(os.path.join(home, 'locks'))
live = {}
for key, phase, records in (('guard-cut', 'guardia', cut), ('guard-quiet', 'guardia', fine), ('work-cut', 'F3', cut),
                            ('work-quiet', 'F3', fine)):
    sid = 'local_' + key
    json.dump({'key': key, 'session_id': sid, 'state': 'running', 'phase': phase, 'project': 'demo',
               'checkout': home + '/none', 'heartbeat': beat(3600)},
              open(os.path.join(home, 'locks', key + '.json'), 'w'))
    path = os.path.join(projects, 'p', 'cli-' + key + '.jsonl')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w').write(''.join(json.dumps(r) + '\\n' for r in records))
    os.utime(path, (now - 3900, now - 3900))
    live[sid] = {'sessionId': 'cli-' + key, 'cwd': '/work/demo', 'status': 'idle'}
revival.live_hosts = lambda: live
print(json.dumps({k: v[0] for k, _, v in revival.stalled_supervisors(revival.STALLED_AFTER_S, now)}))
''', env={'SUPERVISOR_LOCK_HOME': lock_home, 'SUPERVISOR_PROJECTS_DIR': projects})
        got = json.loads(out)
        self.assertEqual(got.get('guard-cut'), 'limit')
        self.assertEqual(got.get('work-cut'), 'limit')
        self.assertNotIn('guard-quiet', got)      # quiet on guard is normal
        self.assertIn('work-quiet', got)          # quiet in a working phase is not

    def test_open_accepts_the_asking_session_like_status_does(self):
        # supervisors pass `--session <their id>` to `open` as they do to `status`; it is not a usage error and it
        # changes nothing: the owner, its questions session and its closing session are left out either way
        repo = self.repo('proj')
        self.assert_clean(self.run_cli('acquire', '--dir', repo, '--session', 'local_o', '--title', 't'))
        bare = self.run_cli('open', '--dir', repo)
        self.assert_clean(bare, (0, 6))
        for sid in ('local_o', 'local_other'):
            with self.subTest(session=sid):
                r = self.run_cli('open', '--dir', repo, '--session', sid)
                self.assert_clean(r, (bare.returncode,))
                self.assertEqual(r.stdout, bare.stdout)
                self.assertEqual(json.loads(self.run_cli('open', '--dir', repo, '--session', sid, '--json').stdout),
                                 json.loads(self.run_cli('open', '--dir', repo, '--json').stdout))

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
        self.assertGreaterEqual(checks, 564 if SKILL.is_file() else 563)
        self.assertTrue(r.stdout.rstrip().endswith('ok: 0 failed'))
        self.assertFalse(os.listdir(self.env['TMPDIR']), 'the self-test left files in the temp dir')


if __name__ == '__main__':
    unittest.main()
