"""Tests of global/scripts/cloud-tests: test suites sent to a cloud session instead of the local heavy-job slots.

Nothing here launches a cloud session or reaches the network. Every subprocess and every module load runs with a
throwaway HOME and these overrides:
  CLOUD_TESTS_CLAUDE        a fake `claude` that refuses everything (never the real CLI);
  CLOUD_TESTS_LIMIT=none    the account's usage is never asked (account-switch is never loaded);
  CLOUD_TESTS_API           an unroutable local URL, and CLOUD_TESTS_CREDENTIALS a missing file (no login, no API);
  CLOUD_TESTS_STATE         the ledger in a temp dir;
  CLOUD_TESTS_OWN_KEY=1     the project key without supervisor-lock (one test removes it on purpose);
  CLOUD_TESTS_NO_PUMP=1     no detached pump;
  HEAVY_JOB_BIN / HEAVY_JOB_DIR, PROJECT_PAUSE_BIN, CLAUDE_TOOLKIT_CONFIG_DIR, GIT_CONFIG_GLOBAL (a test identity for
  the throwaway repositories) and GIT_CONFIG_SYSTEM.
Remotes are local paths or GitHub URLs that no command here contacts (`check` and `local-guard` never fetch).
"""
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
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = os.environ.get('CLOUD_TESTS_SCRIPT') or str(REPO_ROOT / 'global/scripts/cloud-tests')
HEAVY_JOB = str(REPO_ROOT / 'global/scripts/heavy-job')
LIB = str(REPO_ROOT / 'global/scripts/lib')
SCRUB_PREFIXES = ('CLOUD_TESTS_', 'HEAVY_JOB_', 'SUPERVISOR_', 'ACCOUNT_SWITCH', 'PROJECT_PAUSE', 'CLAUDE_TOOLKIT_',
                  'FAKE_CLAUDE', 'GIT_')
REFUSING_CLAUDE = '#!/bin/sh\necho "fake claude: refused" >&2\nexit 1\n'


def load_module(name='cloud_tests_under_test'):
    loader = importlib.machinery.SourceFileLoader(name, SCRIPT)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='cloud-tests-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.mkdir('home')
        self.config = self.mkdir('toolkit-config')
        self.state = os.path.join(self.tmp, 'state')
        claude = os.path.join(self.tmp, 'claude')
        with open(claude, 'w') as f:
            f.write(REFUSING_CLAUDE)
        os.chmod(claude, 0o755)
        gitconfig = os.path.join(self.tmp, 'gitconfig')
        with open(gitconfig, 'w') as f:
            f.write('[user]\n\tname = t\n\temail = t@t\n[init]\n\tdefaultBranch = main\n')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(SCRUB_PREFIXES)}
        self.env.update(
            HOME=self.home, TMPDIR=self.mkdir('tmp'), CLAUDE_TOOLKIT_CONFIG_DIR=self.config,
            GIT_CONFIG_GLOBAL=gitconfig, GIT_CONFIG_SYSTEM=os.devnull,
            CLOUD_TESTS_STATE=self.state, CLOUD_TESTS_CLAUDE=claude, CLOUD_TESTS_LIMIT='none',
            CLOUD_TESTS_API='http://127.0.0.1:9', CLOUD_TESTS_CREDENTIALS=os.path.join(self.tmp, 'no-login.json'),
            CLOUD_TESTS_OWN_KEY='1', CLOUD_TESTS_NO_PUMP='1',
            CLOUD_TESTS_ACCOUNT_SWITCH=os.path.join(self.tmp, 'no-account-switch'),
            HEAVY_JOB_BIN=HEAVY_JOB, HEAVY_JOB_DIR=self.mkdir('hj'), HEAVY_JOB_SLOTS='1', HEAVY_JOB_LIGHT_SLOTS='1',
            HEAVY_JOB_SCAN='0', HEAVY_JOB_SETTLE='0', HEAVY_JOB_MIN_AVAIL_GIB='0', HEAVY_JOB_POLL='0.2',
            HEAVY_JOB_INTERVENTIONS_LOG=os.path.join(self.tmp, 'interventions.log'),
            PROJECT_PAUSE_BIN=os.path.join(self.tmp, 'no-project-pause'), CLOUD_TESTS_BIN=SCRIPT)
        # In-process calls (Project._key, ledger, account_limit) read the environment at call time: sandbox it too.
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def mkdir(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path, exist_ok=True)
        return path

    def module(self, **env):
        with mock.patch.dict(os.environ, dict(self.env, **env), clear=True):
            return load_module()

    def cli(self, *args, cwd=None, env=None, timeout=60):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, timeout=timeout,
                              env=dict(self.env, **(env or {})), cwd=cwd or self.tmp)

    def git(self, *args, cwd):
        return subprocess.run(['git', *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def repo(self, name='proj', remote=None, files=None):
        path = self.mkdir(name)
        self.git('init', '-q', '-b', 'main', path, cwd=self.tmp)
        for rel, text in (files or {'a.txt': 'hi\n'}).items():
            full = os.path.join(path, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w') as f:
                f.write(text)
        self.git('add', '-A', cwd=path)
        self.git('commit', '-qm', 'init', cwd=path)
        if remote:
            self.git('remote', 'add', 'origin', remote, cwd=path)
        return path

    def write_config(self, data):
        with open(os.path.join(self.config, 'cloud-tests.json'), 'w') as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def write_ledger(self, repo, runs):
        """A ledger the way cloud-tests writes it: keyed by the git common dir of `repo`."""
        common = os.path.realpath(self.git('rev-parse', '--path-format=absolute', '--git-common-dir', cwd=repo))
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, 'proj-test.json'), 'w') as f:
            json.dump({'project': 'proj-test', 'repo': 'acme/proj', 'runner': {'session': 'session_R1'},
                       'runs': runs, 'common': common}, f)

    def assertHomeEmpty(self):
        self.assertEqual(os.listdir(self.home), [], 'the throwaway HOME was written to')


class TestSelfTest(Base):
    @unittest.skipUnless(shutil.which('script'), 'script(1) is needed by the self-test (util-linux)')
    def test_self_test_passes_offline(self):
        r = self.cli('self-test', timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        self.assertIn('\n0 failure(s)', r.stdout)
        self.assertNotIn('FAIL ', r.stdout)
        self.assertHomeEmpty()


class TestConfig(Base):
    def test_defaults_exclude_nothing(self):
        m = self.module()
        self.assertEqual((m.EXCLUDED_NAMES, m.EXCLUDED_OWNERS), (set(), set()))
        with open(REPO_ROOT / 'global/config/cloud-tests.json') as f:
            self.assertEqual(json.load(f), {'excluded_names': [], 'excluded_owners': [],
                                            'runner_session_title': 'Tests en la nube de {project}'})

    def test_configured_names_and_owners_are_excluded_case_blind(self):
        self.write_config({'excluded_names': ['Private-App'], 'excluded_owners': ['Team-Org']})
        m = self.module()
        self.assertEqual((m.EXCLUDED_NAMES, m.EXCLUDED_OWNERS), ({'private-app'}, {'team-org'}))

        class P:
            pass
        for name, slug, want in [('private-app', 'acme/x', True), ('checkout', 'acme/PRIVATE-APP', True),
                                 ('x', 'team-org/x', True), ('widgets', 'acme/widgets', False)]:
            p = P()
            p.name, p.slug = name, slug
            self.assertEqual(m.excluded(p), want, slug)

    def test_check_says_local_for_an_excluded_project(self):
        self.write_config({'excluded_owners': ['team-org']})
        repo = self.repo(remote='https://github.com/team-org/widgets.git')
        r = self.cli('check', cwd=repo)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith('LOCAL excluded project'), r.stdout)

    def test_wrong_shapes_and_a_broken_file_keep_the_defaults(self):
        self.write_config({'excluded_names': 'private-app', 'excluded_owners': ['', 'x']})
        m = self.module()
        self.assertEqual((m.EXCLUDED_NAMES, m.EXCLUDED_OWNERS), (set(), set()))
        self.write_config('{not json')
        m = self.module()
        self.assertEqual((m.EXCLUDED_NAMES, m.EXCLUDED_OWNERS), (set(), set()))
        r = self.cli('local-guard', '--', 'make', 'ci')
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))


class TestStatuses(Base):
    def test_check_outside_a_repository_is_local(self):
        r = self.cli('check', cwd=self.mkdir('plain'))
        self.assertEqual((r.returncode, r.stdout.strip()), (3, 'LOCAL not a git repository'))

    def test_check_without_a_github_remote_is_local(self):
        repo = self.repo(remote=self.mkdir('origin.git'))
        r = self.cli('check', cwd=repo)
        self.assertEqual(r.returncode, 3)
        self.assertTrue(r.stdout.startswith('LOCAL no GitHub remote'), r.stdout)

    def test_check_without_a_recipe_is_local_and_with_one_eligible(self):
        repo = self.repo(remote='https://github.com/acme/widgets.git')
        r = self.cli('check', cwd=repo)
        self.assertEqual(r.returncode, 3)
        self.assertIn('no .claude/cloud-tests.json committed', r.stdout)
        if not shutil.which('script'):
            self.skipTest('script(1) missing: eligibility needs it')
        os.makedirs(os.path.join(repo, '.claude'))
        with open(os.path.join(repo, '.claude/cloud-tests.json'), 'w') as f:
            json.dump({'suites': {'ci': {'command': 'make ci'}}}, f)
        self.git('add', '-A', cwd=repo)
        self.git('commit', '-qm', 'recipe', cwd=repo)
        r = self.cli('check', cwd=repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(r.stdout.startswith('ELIGIBLE acme/widgets key=proj-'), r.stdout)

    def test_request_on_an_unpushed_branch_is_not_pushed(self):
        origin = self.mkdir('origin.git')
        self.git('init', '-q', '--bare', '-b', 'main', origin, cwd=self.tmp)
        repo = self.repo(remote=origin)
        r = self.cli('request', '--suite', 'ci', cwd=repo, env={'CLOUD_TESTS_ALLOW_ANY_REMOTE': '1'})
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith('NOT_PUSHED main'), r.stdout)
        self.assertFalse(os.path.exists(self.state) and os.listdir(self.state), 'nothing recorded')

    def test_help_lists_every_command(self):
        r = self.cli('--help')
        self.assertEqual(r.returncode, 0)
        for cmd in ('check', 'request', 'poll', 'wait', 'result', 'record-local', 'status', 'runner', 'local-guard',
                    'stop-local', 'brief', 'pump', 'sweep', 'self-test'):
            self.assertIn(cmd, r.stdout)


class TestLocalGuard(Base):
    """What heavy-job's cloud guard parses: exit 3 + a reason with [CLOUD_RUNNING <run>] / [CLOUD_DONE <run>]."""

    def setUp(self):
        super().setUp()
        self.proj = self.repo()
        self.tree = self.git('rev-parse', 'HEAD^{tree}', cwd=self.proj)
        self.sha = self.git('rev-parse', 'HEAD', cwd=self.proj)
        now = time.time()
        self.sent = {'run': 'r-sent', 'key': 'k1', 'suite': 'ci', 'command': 'X=1 make ci', 'sha': self.sha,
                     'tree': self.tree, 'state': 'sent', 'created': now, 'dispatched': now, 'deadline': now + 3600,
                     'local_match': ['make ci', 'ddev exec make ci']}

    def guard(self, *argv, cwd=None):
        return self.cli('local-guard', '--cwd', cwd or self.proj, '--', *argv)

    def test_no_ledger_lets_it_run(self):
        r = self.guard('make', 'ci')
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_a_suite_in_flight_for_this_tree_is_refused(self):
        self.write_ledger(self.proj, {'r-sent': self.sent})
        for argv in (['make', 'ci'], ['bash', '-c', 'XDEBUG_MODE=off make ci 2>&1 | tail -5'],
                     ['ddev', 'exec', 'make', 'ci']):
            r = self.guard(*argv)
            self.assertEqual(r.returncode, 3, argv)
            self.assertIn('[CLOUD_RUNNING r-sent]', r.stdout)

    def test_a_green_result_is_reused_and_a_red_one_is_not(self):
        done = dict(self.sent, run='r-done', state='done', finished=time.time(), result={'exit': 0})
        self.write_ledger(self.proj, {'r-done': done})
        r = self.guard('make', 'ci')
        self.assertEqual(r.returncode, 3)
        self.assertIn('[CLOUD_DONE r-done]', r.stdout)
        self.write_ledger(self.proj, {'r-done': dict(done, result={'exit': 1})})
        self.assertEqual(self.guard('make', 'ci').returncode, 0)

    def test_other_command_other_code_or_a_deploy_runs(self):
        self.write_ledger(self.proj, {'r-sent': self.sent})
        self.assertEqual(self.guard('make', 'unit').returncode, 0)
        self.assertEqual(self.guard('bash', '-c', 'make ci && ./deploy.sh').returncode, 0)
        with open(os.path.join(self.proj, 'new.txt'), 'w') as f:
            f.write('untracked\n')
        self.assertEqual(self.guard('make', 'ci').returncode, 0)

    def test_heavy_job_refuses_it_with_76(self):
        self.write_ledger(self.proj, {'r-sent': self.sent})
        r = subprocess.run([HEAVY_JOB, 'run', '--kind', 'gate', '--label', 'probe', '--', 'make', 'ci'],
                           cwd=self.proj, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 76, r.stdout + r.stderr)
        self.assertIn('CLOUD_RUNNING r-sent', r.stdout + r.stderr)


class TestOptionalPieces(Base):
    def test_account_switch_absent_means_not_limited(self):
        m = self.module()
        self.assertIsNone(m._limit_from_account(time.time()))

    def test_account_switch_present_is_used_through_its_three_helpers(self):
        fake = os.path.join(self.tmp, 'account-switch')
        until = time.time() + 3600
        with open(fake, 'w') as f:
            f.write('import os\n'
                    'def usage():\n    return None if os.environ.get("FAKE_NO_USAGE") else {"five_hour": 100}\n'
                    f'def usage_limit(data):\n    return {{"until": {until}, "what": "five_hour"}}\n'
                    f'def transcript_limit(since):\n    return {{"until": {until}, "what": "weekly"}}\n')
        m = self.module(CLOUD_TESTS_ACCOUNT_SWITCH=fake)
        self.assertEqual(m._limit_from_account(time.time()), {'until': until, 'what': 'five_hour', 'source': 'usage'})
        with mock.patch.dict(os.environ, {'FAKE_NO_USAGE': '1'}):
            self.assertEqual(m._limit_from_account(time.time())['source'], 'refused-turns')

    def test_a_broken_account_switch_means_not_limited(self):
        fake = os.path.join(self.tmp, 'account-switch')
        with open(fake, 'w') as f:
            f.write('raise SystemExit(9)\n')
        m = self.module(CLOUD_TESTS_ACCOUNT_SWITCH=fake)
        self.assertIsNone(m._limit_from_account(time.time()))

    def test_supervisor_lock_absent_or_present_gives_the_project_key(self):
        repo = self.repo()
        env = {k: v for k, v in self.env.items() if k != 'CLOUD_TESTS_OWN_KEY'}
        with mock.patch.dict(os.environ, env, clear=True):
            m = load_module()
            self.assertRegex(m.Project(repo).key, r'^proj-[0-9a-f]{8}$')
            lock = os.path.join(self.home, '.claude/scripts/supervisor-lock')
            os.makedirs(os.path.dirname(lock))
            with open(lock, 'w') as f:
                f.write('#!/bin/sh\necho "key=shared-key"\n')
            os.chmod(lock, 0o755)
            self.assertEqual(m.Project(repo).key, 'shared-key')

    def test_heavy_job_absent_skips_the_preflight(self):
        repo = self.repo()
        tree = self.git('rev-parse', 'HEAD^{tree}', cwd=repo)
        m = self.module(HEAVY_JOB_BIN=os.path.join(self.tmp, 'no-heavy-job'))
        proj = m.Project(repo)
        with mock.patch('sys.stdout', new_callable=__import__('io').StringIO) as out:
            m.run_preflight(proj, {'preflight': ['exit 7']}, 'ci', {}, tree, False)
        self.assertEqual(out.getvalue().strip(), 'PREFLIGHT_SKIPPED ci (heavy-job is not installed)')

    def test_heavy_job_absent_stops_nothing(self):
        repo = self.repo()
        tree = self.git('rev-parse', 'HEAD^{tree}', cwd=repo)
        m = self.module(HEAVY_JOB_BIN=os.path.join(self.tmp, 'no-heavy-job'))
        proj = m.Project(repo)
        now = time.time()
        with m.ledger(proj) as data:
            data['runs']['r1'] = {'run': 'r1', 'state': 'sent', 'tree': tree, 'command': 'make ci', 'created': now,
                                  'deadline': now + 600, 'suite': 'ci', 'sha': 'x' * 40}
        with mock.patch('sys.stdout', new_callable=__import__('io').StringIO) as out:
            self.assertEqual(m.stop_redundant(proj), [])
        self.assertIn('WARN', out.getvalue())

    def test_sweep_without_a_login_skips_and_never_calls_the_api(self):
        r = self.cli('sweep', '--dry-run')
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith('SKIP no CLI login'), r.stdout)


class TestRunnerTitles(Base):
    """The runners of a project carry «Tests en la nube de <project>»: set when the runner is launched and by `sweep`."""

    def setUp(self):
        super().setUp()
        self.api = os.path.join(self.tmp, 'api.json')
        self.iso = lambda age_s: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - age_s))

    def write_api(self, *rows):
        with open(self.api, 'w') as f:
            json.dump({'sessions': list(rows)}, f)

    def api_state(self):
        with open(self.api) as f:
            return json.load(f)

    def session(self, sid, **kw):
        return dict({'id': sid, 'status': 'active', 'worker_status': 'idle', 'status_bucket': 'completed',
                     'environment_kind': 'anthropic_cloud', 'last_event_at': self.iso(5 * 3600), 'title': 'Cloud runner',
                     'config': {'sources': [{'url': 'https://github.com/acme/proj'}]}}, **kw)

    def test_the_title_comes_from_the_config_piece(self):
        self.assertEqual(self.module().runner_title('demo'), 'Tests en la nube de demo')
        self.write_config({'runner_session_title': 'Runner of {project}'})
        self.assertEqual(self.module().runner_title('demo'), 'Runner of demo')
        self.write_config({'runner_session_title': ''})
        self.assertEqual(self.module().runner_title('demo'), 'Tests en la nube de demo')

    def test_rename_session_puts_the_title_on_the_cse_id_and_reports_the_status(self):
        m = self.module(CLOUD_TESTS_API_FAKE=self.api)
        self.write_api(self.session('cse_ABC'))
        self.assertEqual(m.rename_session('session_ABC', 'Nuevo'), 200)
        self.assertEqual(self.api_state()['renamed'], [['cse_ABC', 'Nuevo']])
        self.assertEqual(self.api_state()['sessions'][0]['title'], 'Nuevo')
        self.assertEqual(m.rename_session('session_NOPE', 'x'), 404)

    def test_rename_session_never_raises(self):
        m = self.module()   # no fake and no CLI login
        self.assertIsNone(m.rename_session('session_ABC', 'x'))
        m.api_call = mock.Mock(side_effect=RuntimeError('boom'))
        self.assertIsNone(m.rename_session('session_ABC', 'x'))

    def queued(self, m):
        data = {'runs': {'r1': {'run': 'r1', 'state': 'queued', 'sha': 'a' * 40, 'tree': 'b' * 40, 'suite': 'ci',
                                'command': 'make ci', 'timeout_min': 30, 'created': time.time()}}, 'runner': None}
        return data

    def test_a_new_runner_is_renamed_as_soon_as_its_session_id_is_known(self):
        m = self.module(CLOUD_TESTS_API_FAKE=self.api)
        self.write_api(self.session('cse_NEWRUN'))
        m.launch_runner = lambda proj, line: ('session_NEWRUN', None)
        proj = mock.Mock()
        proj.name = 'demo'
        data = self.queued(m)
        self.assertEqual(m.dispatch(proj, data, time.time()), 'r1')
        self.assertEqual(self.api_state()['renamed'], [['cse_NEWRUN', 'Tests en la nube de demo']])
        self.assertEqual(data['runner']['session'], 'session_NEWRUN')

    def test_a_failed_rename_never_fails_the_launch(self):
        m = self.module()
        m.launch_runner = lambda proj, line: ('session_NEWRUN', None)
        for failure in (m.ApiUnavailable('network down'), RuntimeError('boom')):
            m.api_call = mock.Mock(side_effect=failure)
            proj = mock.Mock()
            proj.name = 'demo'
            data = self.queued(m)
            self.assertEqual(m.dispatch(proj, data, time.time()), 'r1')
            self.assertEqual((data['runs']['r1']['state'], data['runs']['r1']['session']), ('sent', 'session_NEWRUN'))
        m.api_call = mock.Mock(return_value=(500, {}))
        data = self.queued(m)
        self.assertEqual(m.dispatch(mock.Mock(), data, time.time()), 'r1')

    def write_ledger_named(self, key, name, runner='session_CUR'):
        os.makedirs(self.state, exist_ok=True)
        data = {'project': key, 'repo': 'acme/proj', 'runner': {'session': runner, 'created': time.time() - 600, 'runs': 1},
                'retired': [{'session': 'session_RET'}], 'results_seen': None,
                'runs': {'a': {'state': 'sent', 'session': 'session_BUSY'}, 'b': {'state': 'done', 'session': 'session_DONE'},
                         'c': {'state': 'done', 'session': 'session_OTHER'}}}
        if name:
            data['name'] = name
        with open(os.path.join(self.state, key + '.json'), 'w') as f:
            json.dump(data, f)

    def sweep(self, *args):
        r = self.cli('sweep', *args, env={'CLOUD_TESTS_API_FAKE': self.api})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def sessions_for_sweep(self):
        want = 'Tests en la nube de demo'
        return [self.session('cse_CUR', last_event_at=self.iso(60)),                       # usable runner: kept, renamed
                self.session('cse_BUSY', worker_status='running'),                        # working: kept, renamed
                self.session('cse_RET'),                                                  # retired, quiet: archived only
                self.session('cse_DONE', title=want, last_event_at=self.iso(60)),         # right title already
                self.session('cse_OTHER', config={'sources': [{'url': 'https://github.com/acme/elsewhere'}]}),
                self.session('cse_STRANGER'),                                             # not in the ledger
                self.session('cse_BRIDGE', environment_kind='bridge')]

    def test_sweep_renames_the_runners_the_ledger_proves_and_nothing_else(self):
        self.write_ledger_named('proj-test', 'demo')
        self.write_api(*self.sessions_for_sweep())
        out = self.sweep()
        state = self.api_state()
        self.assertEqual(sorted(state['renamed']), [['cse_BUSY', 'Tests en la nube de demo'],
                                                   ['cse_CUR', 'Tests en la nube de demo']], out)
        self.assertEqual(state['archived'], ['cse_RET'])
        titles = {x['id']: x['title'] for x in state['sessions']}
        self.assertEqual((titles['cse_RET'], titles['cse_OTHER'], titles['cse_STRANGER'], titles['cse_BRIDGE']),
                         ('Cloud runner',) * 4)
        self.assertIn('RENAMED proj-test cse_CUR', out)
        again = self.sweep()
        self.assertNotIn('RENAMED', again)
        self.assertEqual(len(self.api_state()['renamed']), 2)

    def test_sweep_dry_run_changes_nothing_and_a_ledger_without_a_name_is_never_guessed(self):
        self.write_ledger_named('proj-test', 'demo')
        self.write_api(*self.sessions_for_sweep())
        out = self.sweep('--dry-run')
        self.assertIn('WOULD_RENAME proj-test cse_CUR', out)
        self.assertNotIn('renamed', self.api_state())
        self.write_ledger_named('proj-test', None)
        self.assertNotIn('RENAME', self.sweep())
        self.assertNotIn('renamed', self.api_state())

    def test_an_old_ledger_takes_the_name_from_its_git_common_dir(self):
        self.write_ledger_named('proj-test', None)
        path = os.path.join(self.state, 'proj-test.json')
        with open(path) as f:
            data = json.load(f)
        data['common'] = '/somewhere/old-name/.git'
        with open(path, 'w') as f:
            json.dump(data, f)
        self.write_api(*self.sessions_for_sweep())
        self.assertIn('RENAMED proj-test cse_CUR «Cloud runner» -> «Tests en la nube de old-name»', self.sweep())
        data['common'] = '/somewhere/bare.git'
        with open(path, 'w') as f:
            json.dump(data, f)
        self.assertNotIn('RENAME', self.sweep())

    def test_the_ledger_records_the_project_name(self):
        repo = self.repo('demo-checkout', remote='https://github.com/acme/proj.git')
        m = self.module()
        with mock.patch.dict(os.environ, self.env, clear=True):
            proj = m.Project(repo)
            with m.ledger(proj) as data:
                pass
            self.assertEqual(data['name'], 'demo-checkout')
            with open(os.path.join(self.state, proj.key + '.json')) as f:
                self.assertEqual(json.load(f)['name'], 'demo-checkout')


class TestSupervisorLockProvider(Base):
    """supervisor-lock loads this script as its optional cloud provider and uses a few names and the ledger."""

    def test_provider_loads_it_and_reads_its_ledger(self):
        os.makedirs(self.state)
        with open(os.path.join(self.state, 'k.json'), 'w') as f:
            json.dump({'runner': {'session': 'session_CUR'}, 'retired': [{'session': 'session_OLD'}],
                       'runs': {'a': {'state': 'sent', 'session': 'session_BUSY'}}}, f)
        code = (
            'import sys; sys.path.insert(0, sys.argv[1])\n'
            'from supervisor import providers, cloud\n'
            'ct = providers.cloud_tests_module()\n'
            'names = ("github_slug", "sid_key", "iso_epoch", "active_cloud_sessions", "api_call", "send_followup",'
            ' "STATE_DIR")\n'
            'print([n for n in names if not hasattr(ct, n)])\n'
            'print(ct.github_slug("git@github-work:acme/widgets.git"), ct.sid_key("cse_X") == ct.sid_key("session_X"))\n'
            'ids, busy = cloud.cloud_runner_ids("k")\n'
            'print(sorted(ids), sorted(busy))\n')
        env = dict(self.env, SUPERVISOR_CLOUD_TESTS=SCRIPT)
        r = subprocess.run([sys.executable, '-c', code, LIB], capture_output=True, text=True, env=env, timeout=60,
                           cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ['[]', 'acme/widgets True', "['BUSY', 'CUR', 'OLD'] ['BUSY']"])


if __name__ == '__main__':
    unittest.main()
