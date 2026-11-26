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
                  'titles': list(s.QUESTIONS_TITLES), 'title': s.questions_title('p'), 'glob': s.APP_SESSIONS_GLOB,
                  'queued_min': s.QUEUED_REANNOUNCE_MIN, 'slotheld_min': s.SLOTHELD_REANNOUNCE_MIN,
                  'backoff_max_min': s.ALL_IDLE_BACKOFF_MAX_MIN}))
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
        self.assertGreaterEqual(checks, 558 if SKILL.is_file() else 557)
        self.assertTrue(r.stdout.rstrip().endswith('ok: 0 failed'))
        self.assertFalse(os.listdir(self.env['TMPDIR']), 'the self-test left files in the temp dir')


if __name__ == '__main__':
    unittest.main()
