"""Tests for global/scripts/routines (global scheduled routines): precheck, optional registry fields, overlap lock,
the config-driven permission profiles, the usage-limit pause, the once-per-12-hours failure alert, and the config
keys of the `routines` piece (defaults, wrong shapes, a corrupt file, what notify and login keep for their callers).

Run from the repository root:  python3 -m unittest scripts.toolkit.tests.pieces.test_routines

The script is loaded as a module with its config directory (and HOME) pointed at a temp dir, and every path it uses
(registry, state, runs, locks, prompts, vault, token) is pointed at another one, so the real registry, state and
config are never touched. The `claude` call is a stub that records the command line and the prompt; notifications and
auth alerts are mocks. ROUTINES_SCRIPT lets the suite run against a development copy.
"""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from datetime import timedelta
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = os.environ.get('ROUTINES_SCRIPT') or str(REPO_ROOT / 'global/scripts/routines')
SANDBOX = tempfile.mkdtemp(prefix='routines-home-')
REAL_RUN = subprocess.run

# What the `routines` config piece holds in these tests: a notes vault and two permission profiles, one of
# them able to commit and publish (so its denies, lifts and spelled-out allows are exercised).
MAIN = '/srv/app'
CONFIG = {
    'vault_dir': '~/notes-vault',
    'time_label': 'hora de prueba',
    'browser_opener': '~/bin/open-browser',
    'import_skip_ids': ['kept-in-app'],
    'profiles': {
        'observe': ["Bash(sqlite3 'file:data/app.db?mode=ro':*)", 'Bash(journalctl --user -u app-worker:*)'],
        'curl': ['Bash(curl:*)'],
        'publish': [
            'Edit(~/worktrees/app/**)', 'Bash(git add:*)', 'Bash(git commit:*)', 'Bash(git merge master)',
            f'Bash(git -C {MAIN} merge --ff-only:*)', f'Bash(git -C {MAIN} push origin master)',
            f'Bash(git -C {MAIN} status:*)', 'Bash(systemctl --user restart app-worker)',
            'Bash(systemctl --user is-active:*)', 'Bash(.venv/bin/pytest:*)',
        ],
    },
    'profile_deny': {
        'publish': [
            'Bash(git push --force:*)', 'Bash(git push -f:*)', 'Bash(git branch -D:*)', 'Bash(git switch:*)',
            *[f'Bash(git -C {MAIN} {verb}:*)' for verb in ('reset', 'rebase', 'checkout', 'switch', 'commit', 'add')],
            'Bash(git * push -*)', 'Bash(git * push * -*)', 'Bash(git * push *+*)', 'Bash(git * push *:**)',
        ],
    },
    'profile_lift': {'publish': ['Bash(git merge:*)']},
    'default_profiles': {'adopted': ['curl']},
}


def load_module(config=CONFIG, raw_config=None):
    """The script loaded with a config dir holding `config` (or the raw text), and HOME inside the sandbox."""
    cfg_dir = tempfile.mkdtemp(prefix='cfg-', dir=SANDBOX)
    if raw_config is not None:
        with open(os.path.join(cfg_dir, 'routines.json'), 'w') as fh:
            fh.write(raw_config)
    elif config is not None:
        with open(os.path.join(cfg_dir, 'routines.json'), 'w') as fh:
            json.dump(config, fh)
    env = {'HOME': SANDBOX, 'CLAUDE_TOOLKIT_CONFIG_DIR': cfg_dir}
    with mock.patch.dict(os.environ, env):
        loader = importlib.machinery.SourceFileLoader('routines_script', SCRIPT)
        spec = importlib.util.spec_from_loader('routines_script', loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
    return module


R = load_module()
REAL_NOTIFY = R.notify   # RoutinesTestCase replaces R.notify with a mock
SCHEDULED = '2026-11-04T10:00:00+01:00'

# The script works in the machine's local time, and the times these tests expect are written in UTC+1. While this
# module runs, the process zone is pinned to a fixed UTC+1 (a POSIX rule, so no tz database is needed), so the
# results are the same on any machine, CI runners in UTC included; tearDownModule puts the original zone back.
_SAVED_TZ = os.environ.get('TZ')


def setUpModule():
    os.environ['TZ'] = 'CET-1'
    time.tzset()


def tearDownModule():
    if _SAVED_TZ is None:
        os.environ.pop('TZ', None)
    else:
        os.environ['TZ'] = _SAVED_TZ
    time.tzset()


class RoutinesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='routines-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, 'routines')
        self.cwd = os.path.join(self.tmp, 'proj')
        os.makedirs(self.cwd)
        os.makedirs(self.root)
        paths = {'ROOT': self.root, 'REGISTRY': os.path.join(self.root, 'registry.json'),
                 'STATE_DIR': os.path.join(self.root, 'state'), 'RUNS_DIR': os.path.join(self.root, 'runs'),
                 'LOCK_DIR': os.path.join(self.root, 'locks'), 'NOTIFY_LOG': os.path.join(self.root, 'n.log'),
                 'PROMPTS': os.path.join(self.tmp, 'prompts'), 'VAULT': os.path.join(self.tmp, 'vault'),
                 'VAULT_RAW': '~/notes-vault',
                 'TOKEN_FILE': os.path.join(self.root, 'oauth-token.json')}
        for name, value in paths.items():
            patcher = mock.patch.object(R, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.notify = self.patch('notify')
        self.alert = self.patch('alert_auth')
        self.claude_calls = []
        self.started = []
        self.claude_result = (0, 'all done', '')
        patcher = mock.patch.object(R.subprocess, 'run', side_effect=self.fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.makedirs(os.path.join(self.tmp, 'prompts', 'demo'))
        with open(os.path.join(self.tmp, 'prompts', 'demo', 'SKILL.md'), 'w') as fh:
            fh.write('Do the demo task.\n')

    def patch(self, name):
        patcher = mock.patch.object(R, name)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def fake_run(self, cmd, *args, **kwargs):
        if cmd and cmd[0] == 'claude':
            self.claude_calls.append({'cmd': cmd, 'input': kwargs.get('input'), 'env': kwargs.get('env')})
            code, out, err = self.claude_result
            return subprocess.CompletedProcess(cmd, code, out, err)
        if cmd and cmd[0] == 'systemd-run':   # the tick must never start a real unit from a test
            self.started.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, '', '')
        return REAL_RUN(cmd, *args, **kwargs)

    def routine(self, **extra):
        r = {'id': 'demo', 'enabled': True, 'cwd': self.cwd, 'cron': '0 * * * *', 'profiles': []}
        r.update(extra)
        R.save_registry({'routines': [r]})
        return r

    def run_routine(self, test=False, scheduled=SCHEDULED):
        return R.cmd_run(Namespace(id='demo', test=test, scheduled_for=scheduled))

    def state(self):
        return R.load_state('demo')

    def flag_value(self, flag):
        cmd = self.claude_calls[-1]['cmd']
        return cmd[cmd.index(flag) + 1]


class PrecheckTest(RoutinesTestCase):
    def test_exit_0_appends_stdout_under_marker_and_runs_claude(self):
        self.routine(precheck='echo "pending: abc"; echo "id=$ROUTINE_ID at=$ROUTINE_SCHEDULED_FOR"')
        self.assertEqual(self.run_routine(), 0)
        self.assertEqual(len(self.claude_calls), 1)
        prompt = self.claude_calls[0]['input']
        self.assertIn('Do the demo task.', prompt)
        head, _, tail = prompt.partition('\n\n=== PRECHECK ===\n')
        self.assertTrue(tail.startswith('pending: abc\n'))
        self.assertIn(f'id=demo at={SCHEDULED}', tail)
        self.assertEqual(self.state()['last_exit'], 0)
        self.assertNotIn('last_result', self.state())

    def test_exit_0_without_output_adds_no_marker(self):
        self.routine(precheck='true')
        self.run_routine()
        self.assertNotIn('=== PRECHECK ===', self.claude_calls[0]['input'])

    def test_exit_0_runs_in_the_routine_cwd(self):
        self.routine(precheck='pwd')
        self.run_routine()
        self.assertIn(os.path.realpath(self.cwd), self.claude_calls[0]['input'].split('=== PRECHECK ===')[1])

    def test_long_stdout_is_cut_and_says_so(self):
        self.routine(precheck='python3 -c "print(\'x\' * 30000)"')
        self.run_routine()
        block = self.claude_calls[0]['input'].split('=== PRECHECK ===\n')[1]
        self.assertIn('[precheck output truncated at 20000 characters]', block)
        self.assertLess(len(block), 20200)

    def test_exit_1_skips_without_claude_or_notification_and_records_it(self):
        self.routine(precheck='echo scanning; echo "nothing missing"; exit 1')
        self.assertEqual(self.run_routine(), 0)
        self.assertEqual(self.claude_calls, [])
        self.notify.assert_not_called()
        self.alert.assert_not_called()
        st = self.state()
        self.assertEqual(st['last_exit'], 0)
        self.assertEqual(st['last_result'], 'skipped: precheck found nothing to do (nothing missing)')
        self.assertTrue(st['last_run_at'])
        with open(os.path.join(self.root, 'runs', 'demo', 'skips.log')) as fh:
            self.assertIn('nothing missing', fh.read())
        self.assertFalse(os.path.exists(os.path.join(self.root, 'runs', 'demo', 'latest.md')))

    def test_skipped_occurrence_is_not_due_again(self):
        # tick marks last_scheduled_for before it starts the run; a skip must leave that mark alone.
        self.routine(precheck='exit 1')
        occ = R.parse_iso(SCHEDULED)
        R.save_state('demo', {'last_scheduled_for': R.iso(occ), 'previous_scheduled_for': None})
        self.run_routine()
        self.assertEqual(self.state()['last_scheduled_for'], R.iso(occ))
        self.assertIsNone(R.due_occurrence(R.find(R.load_registry(), 'demo'), self.state(), occ + timedelta(minutes=5)))

    def test_exit_other_fails_the_run_with_stderr_tail(self):
        self.routine(precheck='echo boom >&2; exit 2')
        self.assertEqual(self.run_routine(), 125)
        self.assertEqual(self.claude_calls, [])
        self.notify.assert_called_once()
        title, text = self.notify.call_args[0][:2]
        self.assertIn('falló', title)
        self.assertIn('precheck exit 2: boom', text)
        self.assertEqual(self.state()['last_exit'], 125)
        with open(os.path.join(self.root, 'runs', 'demo', 'latest.md')) as fh:
            self.assertIn('precheck exit 2: boom', fh.read())

    def test_timeout_fails_the_run(self):
        self.routine(precheck='sleep 10')
        with mock.patch.object(R, 'PRECHECK_TIMEOUT', 1):
            self.assertEqual(self.run_routine(), 125)
        self.assertEqual(self.claude_calls, [])
        self.assertIn('timed out', self.notify.call_args[0][1])

    def test_precheck_stderr_is_not_read_as_an_auth_or_network_problem(self):
        self.routine(precheck='echo "Invalid API key ECONNREFUSED" >&2; exit 3')
        self.run_routine()
        self.alert.assert_not_called()
        self.notify.assert_called_once()
        self.assertNotIn('waiting_network', self.state())

    def test_test_mode_sets_routine_test_and_writes_no_state(self):
        self.routine(precheck='echo "test=${ROUTINE_TEST:-unset}"')
        self.run_routine(test=True)
        self.assertIn('test=1', self.claude_calls[0]['input'])
        self.assertEqual(self.state(), {})
        self.claude_calls.clear()
        self.run_routine()
        self.assertIn('test=unset', self.claude_calls[0]['input'])

    def test_test_mode_skip_writes_nothing(self):
        self.routine(precheck='exit 1')
        self.assertEqual(self.run_routine(test=True), 0)
        self.assertEqual(self.claude_calls, [])
        self.assertEqual(self.state(), {})
        self.assertFalse(os.path.exists(os.path.join(self.root, 'runs', 'demo', 'skips.log')))

    def test_manual_run_gets_a_scheduled_for(self):
        self.routine(precheck='echo "at=$ROUTINE_SCHEDULED_FOR"')
        self.run_routine(scheduled=None)
        self.assertRegex(self.claude_calls[0]['input'], r'at=20\d\d-\d\d-\d\dT')

    def test_list_shows_a_skipped_run(self):
        self.routine(precheck='exit 1')
        self.run_routine()
        with mock.patch.object(R, 'auth_ok', return_value=True), mock.patch('builtins.print') as out:
            R.cmd_list(Namespace())
        self.assertIn('omitida', '\n'.join(str(c.args[0]) for c in out.call_args_list if c.args))


class CommandLineTest(RoutinesTestCase):
    def test_new_flags_appear_only_when_set(self):
        self.routine()
        self.run_routine()
        cmd = self.claude_calls[0]['cmd']
        for flag in ('--model', '--effort', '--add-dir', '--chrome'):
            self.assertNotIn(flag, cmd)

    def test_routine_without_new_fields_builds_the_same_command_as_before(self):
        r = self.routine(chrome=True, profiles=['curl'])
        allow, deny = R.permissions_for(r)
        expected = ['claude', '-p', '--permission-mode', 'dontAsk', '--output-format', 'text',
                    '--allowedTools', ','.join(allow), '--disallowedTools', ','.join(deny), '--chrome']
        self.assertEqual(R.claude_command(r, allow, deny), expected)

    def test_model_effort_and_add_dirs(self):
        self.routine(model='sonnet', effort='high', add_dirs=['~/a', '/b/c'])
        self.run_routine()
        self.assertEqual(self.flag_value('--model'), 'sonnet')
        self.assertEqual(self.flag_value('--effort'), 'high')
        cmd = self.claude_calls[0]['cmd']
        dirs = [cmd[i + 1] for i, c in enumerate(cmd) if c == '--add-dir']
        self.assertEqual(dirs, [os.path.expanduser('~/a'), '/b/c'])

    def test_timeout_min_is_used(self):
        self.routine(timeout_min=7)
        seen = {}

        def fake(cmd, *args, **kwargs):
            seen['timeout'] = kwargs.get('timeout')
            return subprocess.CompletedProcess(cmd, 0, 'ok', '')
        with mock.patch.object(R.subprocess, 'run', side_effect=fake):
            self.run_routine()
        self.assertEqual(seen['timeout'], 420)

    def test_bash_timeout_min_sets_the_cli_bash_cap(self):
        self.routine(bash_timeout_min=45)
        self.run_routine()
        self.assertEqual(self.claude_calls[0]['env']['BASH_MAX_TIMEOUT_MS'], '2700000')

    def test_no_bash_timeout_leaves_the_cli_default(self):
        self.routine()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('BASH_MAX_TIMEOUT_MS', None)
            self.run_routine()
        self.assertNotIn('BASH_MAX_TIMEOUT_MS', self.claude_calls[0]['env'])


class AddTest(RoutinesTestCase):
    def add(self, **kwargs):
        prompt = os.path.join(self.tmp, 'p.md')
        with open(prompt, 'w') as fh:
            fh.write('task\n')
        args = dict(id='new', cron='0 * * * *', at=None, cwd=self.cwd, prompt_file=prompt, chrome=False,
                    profile=None, disabled=False, model=None, effort=None, timeout_min=None, precheck=None,
                    add_dir=None, bash_timeout_min=None)
        args.update(kwargs)
        R.cmd_add(Namespace(**args))
        return R.find(R.load_registry(), 'new')

    def test_fields_are_stored_only_when_given(self):
        r = self.add()
        for key in ('model', 'effort', 'timeout_min', 'precheck', 'add_dirs', 'bash_timeout_min'):
            self.assertNotIn(key, r)

    def test_fields_are_stored_when_given(self):
        r = self.add(model='sonnet', effort='medium', timeout_min=90, precheck='scripts/check.sh',
                     add_dir=['/x', '/y'], bash_timeout_min=60)
        self.assertEqual((r['model'], r['effort'], r['timeout_min'], r['precheck'], r['add_dirs'],
                          r['bash_timeout_min']),
                         ('sonnet', 'medium', 90, 'scripts/check.sh', ['/x', '/y'], 60))


class LockTest(RoutinesTestCase):
    def test_second_concurrent_run_skips_quietly(self):
        self.routine(precheck='echo hi')
        os.makedirs(R.LOCK_DIR)
        with open(os.path.join(R.LOCK_DIR, 'demo.lock'), 'w') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_routine(), 0)
        self.assertEqual(self.claude_calls, [])
        self.notify.assert_not_called()
        self.assertEqual(self.state(), {})

    def test_lock_is_free_again_after_a_run(self):
        self.routine()
        self.run_routine()
        gc_check = open(os.path.join(R.LOCK_DIR, 'demo.lock'), 'w')
        self.addCleanup(gc_check.close)
        fcntl.flock(gc_check, fcntl.LOCK_EX | fcntl.LOCK_NB)


class PublishProfileTest(RoutinesTestCase):
    MAIN = MAIN

    def perms(self, profiles):
        return R.permissions_for(self.routine(profiles=profiles))

    def test_commit_add_and_merge_are_lifted_only_for_the_profile(self):
        allow, deny = self.perms(['observe', 'publish'])
        for lifted in ('Bash(git commit:*)', 'Bash(git add:*)', 'Bash(git merge:*)'):
            self.assertNotIn(lifted, deny)
        self.assertIn('Bash(git commit:*)', allow)
        self.assertIn('Bash(git merge master)', allow)
        allow, deny = self.perms(['observe'])
        for denied in ('Bash(git commit:*)', 'Bash(git add:*)', 'Bash(git merge:*)'):
            self.assertIn(denied, deny)

    def test_reset_rebase_checkout_push_and_make_stay_denied(self):
        _, deny = self.perms(['publish'])
        for denied in ('Bash(git reset:*)', 'Bash(git rebase:*)', 'Bash(git checkout:*)', 'Bash(git push:*)',
                       'Bash(make:*)', 'Bash(npm:*)', 'Bash(sudo:*)', 'Bash(rm -rf:*)'):
            self.assertIn(denied, deny)

    def test_extra_denies_of_the_profile(self):
        allow, deny = self.perms(['publish'])
        wanted = ['Bash(git push --force:*)', 'Bash(git push -f:*)', 'Bash(git branch -D:*)', 'Bash(git switch:*)']
        wanted += [f'Bash(git -C {self.MAIN} {verb}:*)' for verb in ('reset', 'rebase', 'checkout', 'switch')]
        for denied in wanted:
            self.assertIn(denied, deny)
        _, plain = self.perms(['observe'])
        self.assertNotIn('Bash(git push --force:*)', plain)
        self.assertNotIn(f'Bash(git -C {self.MAIN} reset:*)', plain)

    def test_no_deny_overlaps_a_specific_allow(self):
        # deny beats allow, so a deny that is a prefix of an allowed command would make that allow dead.
        allow, deny = self.perms(['publish'])
        for rule in allow:
            if not rule.startswith('Bash('):
                continue
            command = rule[5:-1]
            for d in deny:
                prefix = d[5:-3] if d.endswith(':*)') else d[5:-1]
                if d.startswith('Bash(') and command.startswith(prefix):
                    self.fail(f'{d} shadows {rule}')

    def test_main_checkout_git_is_spelled_out_never_bare(self):
        allow, _ = self.perms(['publish'])
        self.assertNotIn('Bash(git -C:*)', allow)
        self.assertIn(f'Bash(git -C {self.MAIN} push origin master)', allow)
        self.assertNotIn(f'Bash(git -C {self.MAIN} push origin master:*)', allow)
        self.assertNotIn(f'Bash(git -C {self.MAIN} push:*)', allow)
        self.assertIn(f'Bash(git -C {self.MAIN} merge --ff-only:*)', allow)

    def test_edit_rules_and_tools(self):
        allow, _ = self.perms(['publish'])
        for rule in ('Edit(~/worktrees/app/**)', 'Bash(.venv/bin/pytest:*)',
                     'Bash(systemctl --user restart app-worker)', 'Bash(systemctl --user is-active:*)'):
            self.assertIn(rule, allow)
        self.assertNotIn('Bash(systemctl --user restart:*)', allow)

    def test_every_profile_in_the_deny_and_lift_tables_exists(self):
        for table in (R.PROFILE_DENY, R.PROFILE_LIFT):
            self.assertLessEqual(set(table), set(R.PROFILES))
        for lifted in sum(R.PROFILE_LIFT.values(), []):
            self.assertIn(lifted, R.COMMON_DENY)

    def test_routines_without_a_deny_table_get_the_common_denies(self):
        allow, deny = self.perms(['curl', 'observe'])
        expected_deny = [d for d in R.COMMON_DENY if d not in allow]
        self.assertEqual(deny, expected_deny)

    def test_project_notes_edit_follows_the_vault_key(self):
        allow, _ = self.perms([])
        self.assertIn('Edit(~/notes-vault/10-Projects/proj/Estado.md)', allow)


LIMIT_OUT = "You've hit your 5-hour rolling limit, resets 6:30am (Europe/Madrid)"
PREVIOUS = '2026-11-04T09:00:00+01:00'


class ClockTestCase(RoutinesTestCase):
    """A routine whose tick already marked SCHEDULED, with now_local() fixed at self.now."""
    def setUp(self):
        super().setUp()
        self.now = R.parse_iso('2026-11-04T10:02:00+01:00')
        patcher = mock.patch.object(R, 'now_local', side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.routine()
        self.mark_started()

    def mark_started(self, scheduled=SCHEDULED):
        st = self.state()
        st.update({'previous_scheduled_for': st.get('last_scheduled_for', PREVIOUS), 'last_scheduled_for': scheduled})
        R.save_state('demo', st)

    def latest_report(self):
        with open(os.path.join(self.root, 'runs', 'demo', 'latest.md')) as fh:
            return fh.read()

    def titles(self):
        return [c.args[0] for c in self.notify.call_args_list]


class UsageLimitTest(ClockTestCase):
    def setUp(self):
        super().setUp()
        self.claude_result = (1, LIMIT_OUT, '')

    def test_limited_run_is_given_back_and_told_once_as_a_pause_not_a_failure(self):
        self.assertEqual(self.run_routine(), 1)
        st = self.state()
        self.assertEqual(st['last_scheduled_for'], PREVIOUS)
        self.assertEqual(st['waiting_usage'], SCHEDULED)
        self.assertNotIn('waiting_network', st)
        self.assertNotIn('failure_notified_at', st)
        self.assertEqual(self.titles(), ['Rutinas en pausa por el límite de uso'])
        self.assertNotIn('critical', self.notify.call_args.args)
        self.assertIn('vuelve a las 06:30', self.notify.call_args.args[1])
        self.alert.assert_not_called()
        pause = R.load_usage_pause()
        self.assertEqual(pause['resets'], '2026-11-05T06:30:00+01:00')   # 6:30am already passed today
        self.assertEqual(pause['not_before'], '2026-11-04T11:02:00+01:00')   # an hour at most: another account may have usage
        self.assertIn("hit your 5-hour rolling limit", pause['line'])
        report = self.latest_report()
        self.assertIn('Límite de uso de la cuenta (vuelve a las 06:30): no se avisa como fallo; no cuenta como hecha', report)

    def test_limit_close_to_its_reset_pauses_until_the_reset(self):
        self.now = R.parse_iso('2026-11-05T06:02:00+01:00')
        self.run_routine()
        self.assertEqual(R.load_usage_pause()['not_before'], '2026-11-05T06:30:00+01:00')

    def test_session_limit_wording_is_a_limit_too(self):
        self.claude_result = (1, "You've hit your session limit · resets 1:30am (Europe/Madrid)", '')
        self.run_routine()
        self.assertEqual(self.titles(), ['Rutinas en pausa por el límite de uso'])
        self.assertEqual(self.state()['waiting_usage'], SCHEDULED)

    def test_more_limited_runs_in_the_same_period_tell_nothing(self):
        self.run_routine()
        for minutes in (15, 75, 135):   # the same tick, then probes after each pause, all still limited
            self.now += timedelta(minutes=minutes - (self.now - R.parse_iso('2026-11-04T10:02:00+01:00')).seconds // 60)
            self.mark_started()
            self.run_routine()
        self.assertEqual(self.titles(), ['Rutinas en pausa por el límite de uso'])
        self.assertEqual(R.load_usage_pause()['since'], '2026-11-04T10:02:00+01:00')

    def test_stamp_left_by_an_old_period_starts_a_new_one(self):
        self.run_routine()
        self.now += timedelta(hours=8)   # not_before + 7 h, and no successful run closed the period
        self.mark_started()
        self.run_routine()
        self.assertEqual(len(self.titles()), 2)

    def test_successful_run_ends_the_period(self):
        self.run_routine()
        self.claude_result = (0, 'all done', '')
        self.mark_started()
        self.assertEqual(self.run_routine(), 0)
        self.assertIsNone(R.load_usage_pause())
        self.assertNotIn('waiting_usage', self.state())
        self.claude_result = (1, LIMIT_OUT, '')
        self.mark_started()
        self.run_routine()
        self.assertEqual(len(self.titles()), 2)

    def test_new_routine_token_ends_the_pause(self):
        self.run_routine()
        R.save_routine_token('tok-test-value')
        self.assertIsNone(R.load_usage_pause())

    def test_manual_run_is_not_given_back(self):
        R.save_state('demo', {})
        self.run_routine(scheduled=None)
        self.assertNotIn('waiting_usage', self.state())
        self.assertNotIn('no cuenta como hecha', self.latest_report())
        self.assertEqual(self.titles(), ['Rutinas en pausa por el límite de uso'])

    def test_long_output_that_mentions_a_limit_is_a_real_failure(self):
        self.claude_result = (1, 'x' * 700 + '\n' + LIMIT_OUT, '')
        self.run_routine()
        self.assertEqual(self.titles(), ['Rutina demo falló'])
        self.assertIsNone(R.load_usage_pause())

    def test_list_says_sin_uso_and_until_when(self):
        self.run_routine()
        with mock.patch.object(R, 'auth_ok', return_value=True), mock.patch('builtins.print') as out:
            R.cmd_list(Namespace())
        text = '\n'.join(str(c.args[0]) for c in out.call_args_list if c.args)
        self.assertIn('Límite de uso: rutinas en pausa hasta las 11:02.', text)
        self.assertIn('sin uso', text)


class UsagePauseTickTest(ClockTestCase):
    def tick(self):
        with mock.patch.object(R, 'api_reachable', return_value=True), \
                mock.patch.object(R, 'auth_ok', return_value=True), mock.patch('builtins.print'):
            return R.cmd_tick(Namespace())

    def test_tick_starts_nothing_until_the_pause_ends(self):
        R.save_state('demo', {})
        R.pause_for_usage(None, "You've hit your 5-hour rolling limit", self.now)
        self.assertEqual(self.tick(), 0)
        self.assertEqual(self.started, [])
        self.assertEqual(self.state(), {})   # the occurrence stays due
        self.now += timedelta(minutes=61)
        self.tick()
        self.assertEqual(len(self.started), 1)
        self.assertIn('--scheduled-for', self.started[0])

    def test_unreadable_stamp_does_not_stop_the_tick(self):
        R.save_state('demo', {})
        with open(R.usage_pause_path(), 'w') as fh:
            fh.write('{not json')
        self.tick()
        self.assertEqual(len(self.started), 1)


class UsageResetsAtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.NOW = R.parse_iso('2026-11-05T05:00:00+01:00')   # after setUpModule pinned the zone

    def at(self, text):
        found = R.usage_resets_at(text, self.NOW)
        return R.iso(found) if found else None

    def test_times_of_day(self):
        self.assertEqual(self.at('resets 6:30am (Europe/Madrid)'), '2026-11-05T06:30:00+01:00')
        self.assertEqual(self.at('resets 5pm'), '2026-11-05T17:00:00+01:00')
        self.assertEqual(self.at('resets 12pm'), '2026-11-05T12:00:00+01:00')
        self.assertEqual(self.at('resets 1:30am'), '2026-11-06T01:30:00+01:00')   # already past: tomorrow
        self.assertEqual(self.at('resets 12am'), '2026-11-06T00:00:00+01:00')
        self.assertEqual(self.at('Resets at 11:15 PM'), '2026-11-05T23:15:00+01:00')

    def test_dates(self):
        self.assertEqual(self.at('resets Nov 7, 3pm (Europe/Madrid)'), '2026-11-07T15:00:00+01:00')
        self.assertEqual(self.at('resets Jan 2 at 9am'), '2027-01-02T09:00:00+01:00')

    def test_no_time_or_impossible_date(self):
        self.assertIsNone(self.at("You've hit your limit"))
        self.assertIsNone(self.at('resets Feb 30, 3pm'))
        self.assertIsNone(self.at(''))

    def test_limit_wordings(self):
        for text in ("You've hit your 5-hour rolling limit, resets 6:30am", "You've hit your session limit",
                     "You've hit your weekly limit", "Claude AI usage limit reached|1762318800"):
            self.assertTrue(R.usage_limited(1, text, ''), text)
        self.assertFalse(R.usage_limited(0, "You've hit your 5-hour rolling limit", ''))
        self.assertFalse(R.usage_limited(1, 'Traceback: boom', ''))


class FailureAlertOnceTest(ClockTestCase):
    def setUp(self):
        super().setUp()
        self.claude_result = (1, 'boom', '')

    def again(self, minutes):
        self.now += timedelta(minutes=minutes)
        self.mark_started()
        return self.run_routine()

    def test_first_failure_alerts_critical(self):
        self.assertEqual(self.run_routine(), 1)
        self.assertEqual(self.titles(), ['Rutina demo falló'])
        self.assertIn('critical', self.notify.call_args.args)
        self.assertEqual(self.state()['failure_notified_at'], '2026-11-04T10:02:00+01:00')

    def test_repeated_failure_is_written_in_the_report_not_alerted(self):
        self.run_routine()
        self.again(15)
        self.again(15)
        self.assertEqual(len(self.titles()), 1)
        self.assertIn('Aviso no repetido: ya se avisó de un fallo de esta rutina el 04-11 a las 10:02', self.latest_report())
        self.assertEqual(self.state()['last_exit'], 1)

    def test_alert_again_after_twelve_hours_of_failures(self):
        self.run_routine()
        self.again(11 * 60 + 59)
        self.assertEqual(len(self.titles()), 1)
        self.again(1)
        self.assertEqual(len(self.titles()), 2)

    def test_successful_run_ends_the_run_of_failures(self):
        self.run_routine()
        self.claude_result = (0, 'all done', '')
        self.again(15)
        self.assertNotIn('failure_notified_at', self.state())
        self.claude_result = (1, 'boom', '')
        self.again(15)
        self.assertEqual(len(self.titles()), 2)

    def test_precheck_with_nothing_to_do_ends_the_run_of_failures(self):
        self.run_routine()
        self.routine(precheck='exit 1')
        self.again(15)
        self.assertNotIn('failure_notified_at', self.state())

    def test_failing_precheck_is_alerted_once_too(self):
        self.routine(precheck='echo boom >&2; exit 2')
        self.run_routine()
        self.again(15)
        self.assertEqual(len(self.titles()), 1)
        self.assertIn('El precheck falló', self.notify.call_args.args[1])

    def test_limited_and_offline_runs_neither_alert_nor_reset_the_run(self):
        self.run_routine()
        self.claude_result = (1, LIMIT_OUT, '')
        self.again(15)
        self.assertEqual(self.state()['failure_notified_at'], '2026-11-04T10:02:00+01:00')
        self.assertEqual(self.titles(), ['Rutina demo falló', 'Rutinas en pausa por el límite de uso'])


class ConfigTest(unittest.TestCase):
    """The keys of the `routines` config piece and what happens without them."""

    def write_prompt(self):
        tmp = tempfile.mkdtemp(prefix='cfg-prompt-', dir=SANDBOX)
        path = os.path.join(tmp, 'p.md')
        with open(path, 'w') as fh:
            fh.write('Do the demo task.\n')
        return path

    def prompt(self, module, test=False):
        r = {'id': 'demo', 'cwd': '/srv/proj', 'prompt_file': self.write_prompt()}
        return module.build_prompt(r, SCHEDULED, test).replace(module.SELF, 'SELF')

    def test_defaults_without_a_config_file_are_neutral(self):
        m = load_module(config=None)
        self.assertEqual((m.VAULT, m.VAULT_RAW, m.CHROME_OPENER), ('', '', ''))
        self.assertEqual((m.PROFILES, m.PROFILE_DENY, m.PROFILE_LIFT, m.DEFAULT_PROFILES), ({}, {}, {}, {}))
        self.assertEqual(m.CONFIG['import_skip_ids'], [])
        self.assertEqual(m.CONFIG['time_label'], 'hora local')
        self.assertEqual(m.APP_SESSIONS, os.path.join(SANDBOX, '.config', 'Claude', 'claude-code-sessions'))
        allow, deny = m.permissions_for({'cwd': '/srv/proj', 'profiles': []})
        self.assertEqual(allow, m.COMMON_ALLOW)
        self.assertEqual(deny, m.COMMON_DENY)

    def test_prompt_without_a_vault_has_no_notes_step(self):
        text = self.prompt(load_module(config=None))
        self.assertIn('hora local', text)
        self.assertIn('1. Lee el contexto del proyecto: sus CLAUDE.md', text)
        self.assertIn('\n3. Termina con un resumen', text)
        self.assertNotIn('Estado.md', text)
        self.assertNotIn('vault', text)
        self.assertNotIn('vault', self.prompt(load_module(config=None), test=True))
        self.assertIn('MODO PRUEBA: ejecuta solo lectura. No envíes notificaciones', self.prompt(load_module(config=None), test=True))

    def test_prompt_with_a_vault_has_the_notes_step_and_the_time_label(self):
        m = load_module()
        text = self.prompt(m)
        self.assertIn('prevista ' + SCHEDULED + ', hora de prueba)', text)
        self.assertIn(f'{SANDBOX}/notes-vault/10-Projects/proj/Estado.md', text)
        self.assertIn('\n4. Termina con un resumen', text)
        self.assertIn('No escribas en el vault, no envíes', self.prompt(m, test=True))

    def test_profile_tables_come_from_the_config(self):
        self.assertEqual(set(R.PROFILES), {'observe', 'curl', 'publish'})
        self.assertEqual(R.DEFAULT_PROFILES, {'adopted': ['curl']})
        self.assertEqual(R.PROFILE_LIFT, {'publish': ['Bash(git merge:*)']})

    def test_values_of_the_wrong_shape_keep_the_defaults(self):
        m = load_module({'vault_dir': 5, 'time_label': '  ', 'browser_opener': ['x'], 'import_skip_ids': [1, 2],
                         'profiles': 'nope', 'profile_deny': ['x'], 'default_profiles': 3})
        self.assertEqual((m.VAULT, m.CHROME_OPENER, m.CONFIG['time_label']), ('', '', 'hora local'))
        self.assertEqual(m.CONFIG['import_skip_ids'], [])
        self.assertEqual((m.PROFILES, m.PROFILE_DENY, m.DEFAULT_PROFILES), ({}, {}, {}))

    def test_rule_tables_drop_entries_of_the_wrong_shape(self):
        m = load_module({'profiles': {'a': ['Bash(x)', 5, '', ' '], 'b': 'nope', 'c': []}})
        self.assertEqual(m.PROFILES, {'a': ['Bash(x)'], 'c': []})

    def test_a_corrupt_config_file_keeps_the_defaults(self):
        for raw in ('{not json', '[]', ''):
            m = load_module(raw_config=raw)
            self.assertEqual((m.VAULT, m.PROFILES), ('', {}), raw)

    def test_browser_opener_is_expanded(self):
        self.assertEqual(R.CHROME_OPENER, os.path.join(SANDBOX, 'bin', 'open-browser'))

    def test_app_sessions_dir_is_the_supervision_key(self):
        cfg_dir = tempfile.mkdtemp(prefix='cfg-', dir=SANDBOX)
        with open(os.path.join(cfg_dir, 'supervision.json'), 'w') as fh:
            json.dump({'app_sessions_dir': '~/elsewhere/sessions'}, fh)
        with mock.patch.dict(os.environ, {'HOME': SANDBOX, 'CLAUDE_TOOLKIT_CONFIG_DIR': cfg_dir}):
            loader = importlib.machinery.SourceFileLoader('routines_script', SCRIPT)
            spec = importlib.util.spec_from_loader('routines_script', loader)
            m = importlib.util.module_from_spec(spec)
            loader.exec_module(m)
        self.assertEqual(m.APP_SESSIONS, os.path.join(SANDBOX, 'elsewhere', 'sessions'))

    def test_callers_keep_their_interfaces(self):
        # account-switch reads the routines' token here and supervisor-lock calls `notify`.
        m = load_module()
        self.assertEqual(m.TOKEN_FILE, os.path.join(SANDBOX, '.claude', 'routines', 'oauth-token.json'))
        self.assertEqual(m.NOTIFY_LOG, os.path.join(SANDBOX, '.claude', 'routines', 'notifications.log'))
        self.assertIn('Read(~/.claude/routines/oauth-token*)', m.COMMON_DENY)
        self.assertIn(f'Bash({m.SELF} notify:*)', m.COMMON_ALLOW)


class UnknownProfileTest(RoutinesTestCase):
    def test_a_profile_the_config_does_not_define_adds_nothing(self):
        r = self.routine(profiles=['ghost'])
        self.assertEqual(R.permissions_for(r), R.permissions_for(dict(r, profiles=[])))
        self.assertEqual(R.unknown_profiles(r), ['ghost'])

    def test_the_run_reports_it_and_still_runs(self):
        self.routine(profiles=['ghost', 'curl'])
        self.assertEqual(self.run_routine(), 0)
        self.assertIn('Perfil de permisos desconocido, no se aplica: ghost', self.latest_report())
        self.assertIn('Bash(curl:*)', self.flag_value('--allowedTools'))

    def test_perms_warns_on_stderr(self):
        self.routine(profiles=['ghost'])
        with mock.patch('builtins.print') as out, mock.patch('sys.stdout'):
            R.cmd_perms(Namespace(id='demo'))
        self.assertTrue(any('ghost' in str(c.args[0]) and c.kwargs.get('file') is sys.stderr
                            for c in out.call_args_list if c.args))

    def latest_report(self):
        with open(os.path.join(self.root, 'runs', 'demo', 'latest.md')) as fh:
            return fh.read()


class CommandsTest(RoutinesTestCase):
    def main(self, *argv):
        with mock.patch.object(sys, 'argv', ['routines', *argv]):
            return R.main()

    def test_add_accepts_a_configured_profile_and_rejects_another(self):
        prompt = os.path.join(self.tmp, 'p.md')
        with open(prompt, 'w') as fh:
            fh.write('task\n')
        base = ['add', '--id', 'new', '--cron', '0 * * * *', '--cwd', self.cwd, '--prompt-file', prompt]
        with mock.patch('sys.stderr'), self.assertRaises(SystemExit) as raised:
            self.main(*base, '--profile', 'ghost')
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(self.main(*base, '--profile', 'observe', '--profile', 'curl'), 0)
        self.assertEqual(R.find(R.load_registry(), 'new')['profiles'], ['observe', 'curl'])

    def test_import_adopts_app_tasks_except_the_configured_ones(self):
        app = os.path.join(self.tmp, 'app', 'acct-1234567890', 'org')
        os.makedirs(app)
        tasks = []
        for tid in ('kept-in-app', 'adopted', 'other'):
            path = os.path.join(self.tmp, tid + '.md')
            with open(path, 'w') as fh:
                fh.write('task\n')
            tasks.append({'id': tid, 'enabled': True, 'cwd': self.cwd, 'filePath': path, 'cronExpression': '0 * * * *'})
        with open(os.path.join(app, 'scheduled-tasks.json'), 'w') as fh:
            json.dump({'scheduledTasks': tasks}, fh)
        with mock.patch.object(R, 'APP_SESSIONS', os.path.join(self.tmp, 'app')), mock.patch('builtins.print'):
            self.assertEqual(R.cmd_import(Namespace()), 0)
        found = {r['id']: r for r in R.load_registry()['routines']}
        self.assertEqual(set(found), {'adopted', 'other'})
        self.assertEqual(found['adopted']['profiles'], ['curl'])
        self.assertEqual(found['other']['profiles'], [])

    def test_notify_logs_and_sends_a_desktop_notification(self):
        with mock.patch.object(R.shutil, 'which', return_value='/usr/bin/notify-send'):
            REAL_NOTIFY('Title', 'Text one line')
        sent = [c for c in self.fake_calls if c and c[0] == 'notify-send']
        self.assertEqual(sent, [['notify-send', '-u', 'normal', '-a', 'routines', 'Title', 'Text one line']])
        with open(R.NOTIFY_LOG) as fh:
            self.assertTrue(fh.read().rstrip().endswith('\tTitle\tText one line'))

    def test_notify_without_notify_send_only_logs(self):
        with mock.patch.object(R.shutil, 'which', return_value=None):
            REAL_NOTIFY('Title', 'Text')
        self.assertEqual([c for c in self.fake_calls if c and c[0] == 'notify-send'], [])
        self.assertTrue(os.path.exists(R.NOTIFY_LOG))

    def test_the_notify_subcommand_is_wired_to_notify(self):
        self.assertEqual(self.main('notify', 'T', 'X'), 0)
        self.notify.assert_called_once_with('T', 'X')

    def test_tick_with_no_routines_does_nothing_and_does_not_touch_the_network(self):
        with mock.patch.object(R, 'api_reachable', side_effect=AssertionError('network')):
            self.assertEqual(R.cmd_tick(Namespace()), 0)
        self.assertEqual(self.started, [])

    def setUp(self):
        super().setUp()
        self.fake_calls = []
        inner = R.subprocess.run.side_effect
        def spy(cmd, *a, **k):
            self.fake_calls.append(cmd)
            if cmd and cmd[0] == 'notify-send':
                return subprocess.CompletedProcess(cmd, 0, '', '')
            return inner(cmd, *a, **k)
        patcher = mock.patch.object(R.subprocess, 'run', side_effect=spy)
        patcher.start()
        self.addCleanup(patcher.stop)


if __name__ == '__main__':
    unittest.main()
