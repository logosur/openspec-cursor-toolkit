"""Tests for global/scripts/usage-watch (module `usage`): configuration, counting, attribution, the nine rules, the
findings store, the status line, the page, show and list, the timer and the write scope; and the sub-supervision role
(part B): the usage role in supervisor-lock, ask, decide, apply, measure, the ticket gate hook, the watcher and the
backlog hand-off.

Run from the repository root:  python3 -m unittest scripts.toolkit.tests.pieces.test_usage_watch

Every test works in a temporary HOME with CLAUDE_TOOLKIT_CONFIG_DIR, SUPERVISOR_LOCK_HOME, ASK_QUEUE_DIR and
CLAUDE_TOOLKIT_OVERRIDE inside it, synthetic transcripts (usage_watch.fixtures) and a simulated clock
(USAGE_WATCH_NOW). The real home is never read: the script runs as a subprocess with that environment, and in-process
checks run inside selftest.Sandbox, which points os.environ at the temporary HOME.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = str(REPO_ROOT / 'global/scripts/usage-watch')
LIB = str(REPO_ROOT / 'global/scripts/lib')
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from usage_watch import collect as collect_mod  # noqa: E402
from usage_watch import config as C  # noqa: E402
from usage_watch import flow, rules, scenarios, store  # noqa: E402
from usage_watch.data import Data  # noqa: E402
from usage_watch.selftest import NOW, Sandbox  # noqa: E402

H = 3600
ROLE_MODULES = {'role.py', 'flow.py', 'watcher.py', 'gate.py', 'selftest.py', 'cli.py'}
REAL_HOME = os.path.realpath(os.path.expanduser('~'))


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='usage-watch-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sandbox = Sandbox(self.tmp)
        self.home = self.sandbox.home

    def run_cli(self, *args, now=NOW, env=None):
        e = self.home.env(now=now)
        e.update(env or {})
        self.assertNotEqual(os.path.realpath(e['HOME']), REAL_HOME)
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=e, timeout=120)

    def in_home(self):
        return self.sandbox

    def detect(self, **overrides):
        with self.sandbox:
            if overrides:
                self.home.config(**overrides)
            cfg = C.load()
            collect_mod.collect(cfg, NOW)
            return rules.detect(cfg, NOW)

    def data(self, **overrides):
        with self.sandbox:
            if overrides:
                self.home.config(**overrides)
            cfg = C.load()
            collect_mod.collect(cfg, NOW)
            return Data(cfg, NOW), cfg

    def status(self, **overrides):
        if overrides:
            self.home.config(**overrides)
        self.assertEqual(self.run_cli('collect').returncode, 0)
        r = self.run_cli('status', '--json')
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)


# ---------------------------------------------------------------------------------------------------- 1. skeleton
class SkeletonTest(Base):
    def test_help_lists_every_subcommand(self):
        r = self.run_cli('--help')
        self.assertEqual(r.returncode, 0)
        for cmd in ('collect', 'detect', 'status', 'page', 'tick', 'show', 'list', 'timer', 'self-test', 'ask',
                    'decide', 'apply', 'measure', 'wait'):
            self.assertRegex(r.stdout, rf'\n\s+{re.escape(cmd)}\s')

    def test_role_commands_without_supervision(self):
        for args in (('ask', 'x'), ('decide', 'x'), ('wait', '--session', 'x')):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 6, args)
            self.assertIn('supervision module is needed', r.stderr)
        for args in (('apply', 'x'), ('measure', 'x')):
            self.assertEqual(self.run_cli(*args).returncode, 2, args)

    def test_shipped_config_equals_code_defaults(self):
        shipped = json.loads((REPO_ROOT / 'global/config/usage-watch.json').read_text())
        self.assertEqual(shipped, C.DEFAULTS)
        self.assertEqual(shipped['order_text'], '')
        self.assertEqual(shipped['weekly_budget_units'], 0)
        self.assertEqual(list(shipped['prices']), ['.'])

    def test_corrupt_config_gives_defaults(self):
        os.makedirs(self.home.config_dir, exist_ok=True)
        with open(os.path.join(self.home.config_dir, 'usage-watch.json'), 'w') as fh:
            fh.write('{not json')
        with self.sandbox:
            self.assertEqual(C.load()['advisor_max_per_day'], C.DEFAULTS['advisor_max_per_day'])
        r = self.run_cli('status')
        self.assertEqual(r.returncode, 0)
        self.assertIn('pace unknown', r.stdout)

    def test_wrong_shape_keeps_the_default(self):
        self.home.config(advisor_max_per_day='many', week_start_hour=30, panel_pattern='(', cheap_roles='usage',
                         proposals={'loop': {'proposal': 7}}, labels={'title': ''})
        with self.sandbox:
            cfg = C.load()
        self.assertEqual(cfg['advisor_max_per_day'], 4)
        self.assertEqual(cfg['week_start_hour'], 0)
        self.assertEqual(cfg['panel_pattern'], '^Panel')
        self.assertEqual(cfg['cheap_roles'], C.DEFAULTS['cheap_roles'])
        self.assertEqual(cfg['proposals']['loop'], C.DEFAULT_PROPOSALS['loop'])
        self.assertEqual(cfg['labels']['title'], C.DEFAULT_LABELS['title'])

    def test_wrong_shape_threshold_is_not_used_by_the_rule(self):
        # spec: advisor_max_per_day "many" -> the default cap (4): five advisor calls still fire
        tr = self.home.transcript('s-adv')
        tr.user(NOW - 2 * H, 'x')
        for i in range(5):
            scenarios._advisor(tr, NOW - 2 * H + i * 60, 1)
        found = [c for c in self.detect(advisor_max_per_day='many') if c['rule'] == 'advisor-excess']
        self.assertEqual(len(found), 1)

    def test_bad_price_entry(self):
        tr = self.home.transcript('s-price')
        tr.user(NOW - 100, 'x')
        tr.assistant(NOW - 90, model='alpha-1', inp=1000000)
        tr.assistant(NOW - 80, model='beta-1', inp=1000000)
        d, cfg = self.data(prices={'^beta': [1, 2, 3], '^alpha': [2, 0, 0, 0, 0]})
        self.assertEqual(list(cfg['prices']), ['^alpha'])
        self.assertIn('beta-1', d.unpriced)
        self.assertEqual({c['model']: c['units'] for c in d.calls}['alpha-1'], 2.0)

    def test_no_valid_price_entry_uses_the_default_table(self):
        with self.sandbox:
            self.home.config(prices={'(': [1, 1, 1, 1, 1]})
            self.assertEqual(list(C.load()['prices']), ['.'])


class FixtureSmokeTest(Base):
    def test_each_fixture_kind_builds_under_the_temporary_home(self):
        repo = self.home.git_repo('proj')
        tree = self.home.worktree(repo, 'proj-wt')
        paths = [self.home.transcript('s1', cwd=repo).user(NOW, 'x').path,
                 self.home.subagent('s1', 'a1', ts=NOW).path,
                 self.home.app_record('local_a', 's1', repo),
                 self.home.lock('proj', repo, 'local_a', mailbox='local_b'),
                 self.home.usage_role('local_u'), tree]
        for path in paths:
            self.assertTrue(os.path.exists(path), path)
            self.assertTrue(os.path.realpath(path).startswith(self.home.root), path)
        env = self.home.env()
        for key in ('HOME', 'CLAUDE_TOOLKIT_CONFIG_DIR', 'SUPERVISOR_LOCK_HOME', 'ASK_QUEUE_DIR', 'CLAUDE_TOOLKIT_OVERRIDE'):
            self.assertTrue(os.path.realpath(env[key]).startswith(self.home.root), key)
        with self.sandbox:
            self.assertEqual(os.path.realpath(os.path.expanduser('~')), self.home.root)
        self.assertEqual(os.path.realpath(os.path.expanduser('~')), REAL_HOME)


# ---------------------------------------------------------------------------------------------------- 2. counting
class CountingTest(Base):
    def test_main_and_subagent_usage_are_both_counted(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, inp=1, cw5=2, cw1h=3, cr=4, out=5)
        tr.assistant(NOW - 280, inp=10, cw5=20, cw1h=30, cr=40, out=50)
        self.home.subagent('s1', 'a1', ts=NOW - 200)   # one response: inp 10, out 20
        s = self.status()
        self.assertEqual(s['calls'], {'main': 2, 'subagent': 1, 'advisor': 0, 'total': 3})
        self.assertEqual(s['tokens'], {'in': 21, 'cw5': 22, 'cw1h': 33, 'cr': 44, 'out': 75})

    def test_synthetic_and_usage_less_lines_are_skipped(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, model='<synthetic>')
        tr.raw(json.dumps({'type': 'assistant', 'timestamp': C.iso(NOW - 280),
                           'message': {'id': 'm-nousage', 'model': 'model-small', 'content': []}}))
        s = self.status()
        self.assertEqual(s['calls']['total'], 0)
        self.assertEqual(s['skipped_lines'], 0)

    def test_cache_split_and_total_only(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, msg_id='split', cw5=50, cw1h=100)
        tr.assistant(NOW - 280, msg_id='total', cw5=80, split=False)
        d, _ = self.data()
        by = {c['id']: c for c in d.calls}
        self.assertEqual((by['split']['cw1h'], by['split']['cw5']), (100, 50))
        self.assertEqual((by['total']['cw5'], by['total']['cw1h']), (80, 0))

    def test_context_size(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, msg_id='c', inp=10, cw5=30, cw1h=20, cr=940)
        d, _ = self.data()
        self.assertEqual(d.calls[0]['ctx'], 1000)

    def test_advisor_iteration_is_a_separate_call(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, msg_id='m', model='model-main', iterations=[
            {'type': 'message', 'input_tokens': 7, 'output_tokens': 1},
            {'type': 'advisor_message', 'model': 'model-adv', 'input_tokens': 40, 'output_tokens': 4}])
        d, _ = self.data()
        kinds = {c['kind']: c for c in d.calls}
        self.assertEqual(set(kinds), {'main', 'advisor'})
        self.assertEqual((kinds['main']['in'], kinds['main']['model']), (7, 'model-main'))
        self.assertEqual((kinds['advisor']['in'], kinds['advisor']['model'], kinds['advisor']['session']),
                         (40, 'model-adv', 's1'))

    def test_only_advisor_iterations_main_uses_top_level_usage(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, msg_id='m', usage={'input_tokens': 3, 'output_tokens': 2, 'iterations': [
            {'type': 'advisor_message', 'input_tokens': 40, 'output_tokens': 4}]})
        d, _ = self.data()
        kinds = {c['kind']: c for c in d.calls}
        self.assertEqual((kinds['main']['in'], kinds['advisor']['in']), (3, 40))

    def test_broken_line_in_the_middle(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290)
        tr.raw('this is not json')
        tr.assistant(NOW - 280)
        s = self.status()
        self.assertEqual((s['calls']['total'], s['skipped_lines']), (2, 1))

    def test_wrong_types_and_missing_timestamp_are_skipped(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, usage={'input_tokens': 'many', 'output_tokens': 1})
        tr.raw(json.dumps({'type': 'assistant', 'message': {'id': 'nots', 'model': 'm', 'usage': {'input_tokens': 1}}}))
        r = self.run_cli('collect')
        self.assertEqual(r.returncode, 0)
        s = json.loads(self.run_cli('status', '--json').stdout)
        self.assertEqual((s['calls']['total'], s['skipped_lines']), (0, 2))

    def test_unreadable_file_is_skipped_and_counted(self):
        tr = self.home.transcript('s1').user(NOW - 300, 'go')
        os.chmod(tr.path, 0)
        self.addCleanup(os.chmod, tr.path, stat.S_IRUSR | stat.S_IWUSR)
        if os.access(tr.path, os.R_OK):
            self.skipTest('running as a user that can read any file')
        s = self.status()
        self.assertEqual(s['skipped_lines'], 1)

    def test_incremental_equals_full(self):
        def write(tr, lines):
            for kind, i in lines:
                if kind == 'u':
                    tr.user(NOW - 1000 + i, f'q{i}')
                else:
                    tr.assistant(NOW - 1000 + i, msg_id=f'm{i}', inp=i, out=2 * i)
        lines = [('u', 1), ('a', 2), ('a', 3), ('u', 4), ('a', 5), ('a', 6)]
        tr = self.home.transcript('s1')
        write(tr, lines[:3])
        self.assertEqual(self.run_cli('collect').returncode, 0)
        write(tr, lines[3:])
        incremental = self.status()
        full_home = Sandbox(os.path.join(self.tmp, 'full')).home
        write(full_home.transcript('s1'), lines)
        e = full_home.env(now=NOW)
        subprocess.run([sys.executable, SCRIPT, 'collect'], env=e, capture_output=True, check=True)
        full = json.loads(subprocess.run([sys.executable, SCRIPT, 'status', '--json'], env=e, capture_output=True,
                                         text=True, check=True).stdout)
        self.assertEqual((incremental['tokens'], incremental['calls']), (full['tokens'], full['calls']))

    def test_three_lines_of_one_response(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        for out in (1, 2, 3):
            tr.assistant(NOW - 290, msg_id='same', out=out)
        d, _ = self.data()
        self.assertEqual([(c['id'], c['out']) for c in d.calls], [('same', 3)])

    def test_tools_of_every_line_of_one_response_are_kept(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, msg_id='same', tools=[('Read', {'p': 1})])
        tr.assistant(NOW - 290, msg_id='same', text='done')
        d, _ = self.data()
        self.assertEqual(len(d.calls[0]['tools']), 1)
        self.assertIsNotNone(d.calls[0]['text'])

    def test_same_response_in_two_transcripts(self):
        self.home.transcript('s1').user(NOW - 300, 'go').assistant(NOW - 290, msg_id='shared')
        self.home.transcript('s1-resumed').user(NOW - 200, 'go').assistant(NOW - 290, msg_id='shared')
        d, _ = self.data()
        self.assertEqual(len([c for c in d.calls if c['id'] == 'shared']), 1)

    def test_replaced_or_truncated_file(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        for i in range(4):
            tr.assistant(NOW - 290 + i, msg_id=f'm{i}', out=10)
        self.assertEqual(self.run_cli('collect').returncode, 0)
        os.remove(tr.path)                      # replaced by a shorter file with another inode
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, msg_id='m0', out=10)
        tr.assistant(NOW - 280, msg_id='m9', out=10)
        s = self.status()
        self.assertEqual(s['calls']['total'], 5)   # m0..m3 from the first file, m9 new, m0 not duplicated
        self.assertEqual(s['tokens']['out'], 50)
        with open(tr.path, 'w') as fh:          # truncated in place (same inode)
            fh.write('')
        tr.user(NOW - 100, 'again').assistant(NOW - 90, msg_id='m10', out=10)
        s = self.status()
        self.assertEqual((s['calls']['total'], s['tokens']['out']), (6, 60))

    def test_records_after_now_are_ignored(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 300, 'go')
        tr.assistant(NOW - 290, msg_id='past')
        tr.assistant(NOW + 3600, msg_id='future')
        d, _ = self.data()
        self.assertEqual([c['id'] for c in d.calls], ['past'])


class TurnTest(Base):
    def origins(self):
        d, _ = self.data()
        return sorted(t['origin'] for t in d.turns.values()), d

    def test_one_origin_per_kind(self):
        tr = self.home.transcript('s1')
        for i, kind in enumerate(('task-notification', 'peer', 'child', 'app', 'unheard-of')):
            tr.user(NOW - 1000 + i, 'x', origin=kind)
        tr.user(NOW - 900, 'typed by the developer')
        tr.user(NOW - 890, 'summary', compact=True)
        tr.user(NOW - 880, '<task-notification> done')
        tr.tool_result(NOW - 870)
        tr.user(NOW - 860, 'meta', meta=True)
        origins, d = self.origins()
        self.assertEqual(origins, sorted(['task', 'peer', 'child', 'app', 'other', 'human', 'compact', 'task']))
        self.assertTrue(Data.is_automatic('task') and not Data.is_automatic('human')
                        and not Data.is_automatic('compact') and not Data.is_automatic('subagent'))

    def test_routine_from_the_app_record(self):
        self.home.app_record('local_r', 's-rout', self.home.root, scheduled='task-1')
        self.home.transcript('s-rout').user(NOW - 100, 'typed prompt').assistant(NOW - 90)
        d, _ = self.data()
        self.assertEqual([t['origin'] for t in d.turns.values()], ['routine'])
        self.assertEqual(d.calls[0]['origin'], 'routine')

    def test_each_main_call_belongs_to_its_turn(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 100, 'first', uuid='t1').assistant(NOW - 99).tool_result(NOW - 98).assistant(NOW - 97)
        tr.user(NOW - 50, 'second', origin='task-notification', uuid='t2').assistant(NOW - 49)
        d, _ = self.data()
        self.assertEqual([c['turn'] for c in d.calls], ['t1', 't1', 't2'])
        self.assertEqual([c['origin'] for c in d.calls], ['human', 'human', 'task'])


class WeightTest(Base):
    def test_configured_weights(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 100, 'x')
        tr.assistant(NOW - 90, model='model-w', inp=1000, cw5=2000, cw1h=3000, cr=4000, out=5000)
        d, _ = self.data(prices={'^model-w$': [1, 2, 3, 0.5, 10]})
        expected = (1000 * 1 + 2000 * 2 + 3000 * 3 + 4000 * 0.5 + 5000 * 10) / 1e6
        self.assertAlmostEqual(d.calls[0]['units'], expected)

    def test_unpriced_model(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 100, 'x')
        tr.assistant(NOW - 90, model='model-free', inp=7, out=3)
        s = self.status(prices={'^other$': [1, 1, 1, 1, 1]})
        self.assertEqual(s['unpriced_models'], {'model-free': 10})


class AttributionTest(Base):
    def test_worktree_of_a_project(self):
        repo = self.home.git_repo('main-repo')
        tree = self.home.worktree(repo, 'feature-tree')
        self.home.transcript('s-wt', cwd=tree).user(NOW - 100, 'x').assistant(NOW - 90)
        d, _ = self.data()
        self.assertEqual(d.session('s-wt')['project'], 'main-repo')

    def test_not_git_and_unknown(self):
        self.home.transcript('s-plain', cwd=os.path.join(self.home.root, 'gone', 'plain-dir')).user(NOW - 100, 'x')
        self.home.transcript('s-none').user(NOW - 100, 'x')
        d, _ = self.data()
        self.assertEqual((d.session('s-plain')['project'], d.session('s-none')['project']), ('plain-dir', 'unknown'))

    def test_questions_session_of_a_lock(self):
        repo = self.home.git_repo('proj')
        self.home.lock('proj', repo, 'local_sup', mailbox='local_box', closer='local_close')
        self.home.app_record('local_box', 'cli-box', repo)
        self.home.app_record('local_sup', 'cli-sup', repo)
        self.home.app_record('local_close', 'cli-close', repo)
        for cli in ('cli-box', 'cli-sup', 'cli-close', 'cli-other'):
            self.home.transcript(cli, cwd=repo).user(NOW - 100, 'x').assistant(NOW - 90)
        d, _ = self.data()
        self.assertEqual({k: d.session(k)['role'] for k in ('cli-box', 'cli-sup', 'cli-close', 'cli-other')},
                         {'cli-box': 'questions', 'cli-sup': 'supervisor', 'cli-close': 'closer', 'cli-other': 'worker'})
        self.assertEqual(d.session('cli-box')['app_id'], 'local_box')

    def test_usage_role_holder(self):
        self.home.app_record('local_u', 'cli-u', self.home.root)
        self.home.usage_role('local_u')
        self.home.transcript('cli-u').user(NOW - 100, 'x')
        d, _ = self.data()
        self.assertEqual(d.session('cli-u')['role'], 'usage')

    def test_released_lock(self):
        repo = self.home.git_repo('proj')
        self.home.lock('proj', repo, 'local_sup', mailbox='local_box', released=True)
        self.home.app_record('local_box', 'cli-box', repo)
        self.home.transcript('cli-box', cwd=repo).user(NOW - 100, 'x')
        d, _ = self.data()
        self.assertEqual(d.session('cli-box')['role'], 'worker')

    def test_without_supervision(self):
        self.home.app_record('local_r', 's-rout', self.home.root, scheduled='t')
        self.home.transcript('s-rout').user(NOW - 100, 'x').assistant(NOW - 90)
        self.home.transcript('s-w').user(NOW - 100, 'x').assistant(NOW - 90)
        self.home.subagent('s-w', 'p1', description='Panel member', ts=NOW - 50)
        self.assertFalse(os.path.exists(self.home.supervisor))
        self.assertEqual(self.run_cli('collect').returncode, 0)
        d, _ = self.data()
        self.assertLessEqual({d.session(s)['role'] for s in d.info}, {'routine', 'panel', 'subagent', 'worker'})

    def test_no_supervision_code_and_no_machine_names(self):
        pkg = REPO_ROOT / 'global/scripts/lib/usage_watch'
        text = ''.join(p.read_text() for p in sorted(pkg.glob('*.py')))
        # part B runs ask-queue and supervisor-lock as subprocesses from role.py only; nothing imports supervision code
        self.assertNotRegex(text, r'from \.\.supervisor|import supervisor|lib/supervisor')
        measuring = ''.join(p.read_text() for p in sorted(pkg.glob('*.py')) if p.name not in ROLE_MODULES)
        self.assertNotRegex(measuring, r'supervisor-lock|ask-queue')
        for name in ROLE_MODULES - {'role.py'}:
            self.assertNotRegex((pkg / name).read_text(), r"'~/\.claude/scripts/")
        defaults = (REPO_ROOT / 'global/config/usage-watch.json').read_text()
        for blob in (text, defaults, (REPO_ROOT / 'global/scripts/usage-watch').read_text()):
            self.assertNotRegex(blob, r'/home/|/Users/')


class RetentionTest(Base):
    def test_old_records_are_pruned_and_findings_stay(self):
        tr = self.home.transcript('s1')
        tr.user(NOW - 20 * 86400, 'old').assistant(NOW - 20 * 86400 + 1, msg_id='old')
        with self.sandbox:
            self.home.config(retention_days=30)
            cfg = C.load()
            collect_mod.collect(cfg, NOW)
            store.write(cfg, {'x-1': {'id': 'x-1', 'state': 'asked'}})
            before = read(store.store_path(cfg))
            self.home.config(retention_days=15)
            cfg = C.load()
            collect_mod.collect(cfg, NOW)
            self.assertEqual(Data(cfg, NOW).calls, [])
            self.assertEqual(read(store.store_path(cfg)), before)


# ---------------------------------------------------------------------------------------------------- 3. rules
class RuleCasesTest(Base):
    """The firing and the healthy case of every rule (the same cases as `self-test`)."""

    def check(self, rule, builder, overrides, fire):
        sub = Sandbox(os.path.join(self.tmp, f'{rule}-{fire}'))
        with sub as home:
            home.config(**overrides)
            builder(home, NOW)
            cfg = C.load()
            collect_mod.collect(cfg, NOW)
            found = [c for c in rules.detect(cfg, NOW) if c['rule'] == rule]
        if rule == 'pace':   # the burst is one session's, so its project fires too; the spec names the project
            found = [c for c in found if c['scope']['kind'] == 'project']
        self.assertEqual(len(found), 1 if fire else 0, f'{rule} fire={fire}: {found}')
        return found

    def test_every_rule(self):
        for rule, fire, healthy, overrides in scenarios.CASES:
            with self.subTest(rule=rule):
                found = self.check(rule, fire, overrides, True)
                self.check(rule, healthy, overrides, False)
                f = found[0]
                for key in ('id', 'rule', 'scope', 'evidence', 'saving_units_per_day', 'proposal', 'applier', 'undo'):
                    self.assertIn(key, f)
                self.assertRegex(f['id'], r'^[a-z-]+-[0-9a-f]{10}$')

    def test_pace_finding_is_for_the_project(self):
        with Sandbox(os.path.join(self.tmp, 'pace-scope')) as home:
            home.config(**scenarios.CASES[7][3])
            scenarios.pace_fire(home, NOW)
            cfg = C.load()
            collect_mod.collect(cfg, NOW)
            found = [c for c in rules.detect(cfg, NOW) if c['rule'] == 'pace']
        self.assertEqual(len([c for c in found if c['scope']['kind'] == 'project']), 1)

    def test_pace_no_history(self):
        self.home.transcript('s-new').user(NOW - 1800, 'x').assistant(NOW - 1700, inp=500)
        found = [c for c in self.detect(prices=scenarios.UNIT_PER_INPUT_TOKEN) if c['rule'] == 'pace']
        self.assertEqual(found, [])

    def test_pace_above_the_sustainable_pace(self):
        tr = self.home.transcript('s-sus', cwd=self.home.root)
        tr.user(NOW - 5 * H, 'x')
        for i in range(3):
            tr.assistant(NOW - 5 * H + i * H, inp=5)
        found = [c for c in self.detect(prices=scenarios.UNIT_PER_INPUT_TOKEN, weekly_budget_units=168,
                                        pace_sustainable_window_h=6, pace_sustainable_share=2, pace_min_units=1000)
                 if c['rule'] == 'pace' and c['scope']['kind'] == 'project']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['evidence']['limit'], 12)

    def test_role_model_proposes_a_session_model(self):
        f = self.check('role-model', scenarios.role_fire, {}, True)[0]
        self.assertEqual((f['proposal']['kind'], f['applier'], f['target_app_id']),
                         ('session-model', 'usage-role', 'local_box'))

    def test_expensive_automation_without_app_record_is_a_note(self):
        f = self.check('expensive-automation', scenarios.automation_fire, {'automation_min_share': 0.6}, True)[0]
        self.assertEqual((f['proposal']['kind'], f['applier']), ('note', 'project-supervisor'))

    def test_loop_same_tool_call(self):
        tr = self.home.transcript('s-call')
        tr.user(NOW - 3 * H, 'x')
        for i in range(7):
            tr.assistant(NOW - 3 * H + i * 120, tools=[('Bash', {'command': 'ls'})], text=f'try {i} {"abcdefg"[i]}')
        found = [c for c in self.detect() if c['rule'] == 'loop']
        self.assertEqual([f['evidence']['kind'] for f in found], ['same-call'])


class StoreTest(Base):
    def config_trigger_sessions(self, home, n=3):
        for s in range(n):
            home.transcript(f's{s}').turn(NOW - 3 * H)
            for i in range(3):
                home.subagent(f's{s}', f'a{s}{i}', description='Explore', ts=NOW - H + i, model=scenarios.EXPENSIVE)
            tr = home.transcript(f's{s}')
            for i in range(6):
                scenarios._advisor(tr, NOW - 2 * H + i * 60, 1)

    def test_detect_twice(self):
        scenarios.large_fire(self.home, NOW)
        self.assertEqual(self.run_cli('tick').returncode, 0)
        first = self.run_cli('list', '--json')
        r = self.run_cli('detect', now=NOW + 60)
        self.assertIn('0 new finding(s), 1 refreshed', r.stdout)
        findings = json.loads(self.run_cli('list', '--json').stdout)
        self.assertEqual(len(findings), 1)
        self.assertNotEqual(json.loads(first.stdout)[0]['last_seen'], findings[0]['last_seen'])

    def test_one_config_proposal_from_many_sessions(self):
        self.config_trigger_sessions(self.home)
        found = [c for c in self.detect() if c['proposal']['kind'] == 'config']
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual((f['scope']['kind'], f['proposal']['piece'], f['proposal']['key'], f['proposal']['value']),
                         ('machine', 'agent-model-gate', 'enabled', True))
        self.assertEqual(f['evidence']['sessions'], ['s0', 's1', 's2'])
        self.assertEqual(f['evidence']['rules'], ['expensive-subagents', 'advisor-excess'])
        self.assertTrue(f['id'].startswith('config-'))

    def test_value_already_in_effect(self):
        self.config_trigger_sessions(self.home, 1)
        self.home.piece('agent-model-gate', {'enabled': True})
        self.assertEqual([c for c in self.detect() if c['proposal']['kind'] == 'config'], [])

    def test_asked_and_rejected_are_untouched(self):
        scenarios.large_fire(self.home, NOW)
        scenarios.idle_fire(self.home, NOW)
        self.assertEqual(self.run_cli('tick').returncode, 0)
        with self.sandbox:
            cfg = C.load()
            findings = store.read(cfg)
            for f, state in zip(sorted(findings.values(), key=lambda f: f['rule']), ('asked', 'rejected')):
                f['state'] = state
            store.write(cfg, findings)
            before = json.dumps(store.read(cfg), sort_keys=True)
        self.assertEqual(self.run_cli('detect', now=NOW + 60).returncode, 0)
        with self.sandbox:
            self.assertEqual(json.dumps(store.read(C.load()), sort_keys=True), before)

    def test_corrupt_store_is_moved_aside(self):
        os.makedirs(self.home.state, exist_ok=True)
        with open(os.path.join(self.home.state, 'findings.json'), 'w') as fh:
            fh.write('{broken')
        scenarios.large_fire(self.home, NOW)
        r = self.run_cli('tick')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.home.state, 'findings.json.corrupt-1')))
        self.assertEqual(len(json.loads(self.run_cli('list', '--json').stdout)), 1)

    def test_id_is_stable_and_scoped(self):
        self.assertEqual(store.finding_id('loop', 'session', 's1', 'x'), store.finding_id('loop', 'session', 's1', 'x'))
        self.assertNotEqual(store.finding_id('loop', 'session', 's1', 'x'), store.finding_id('loop', 'session', 's2', 'x'))


# ---------------------------------------------------------------------------------------------------- 4. reporting
class StatusTest(Base):
    def test_red_pace(self):
        # NOW is a Thursday 12:00 UTC; a week starting Tuesday 18:00 is 42 of 168 hours in: a quarter of the week
        tr = self.home.transcript('s1')
        tr.user(NOW - H, 'x').assistant(NOW - 600, inp=40)
        s = self.status(prices=scenarios.UNIT_PER_INPUT_TOKEN, weekly_budget_units=100, week_start_weekday=1,
                        week_start_hour=18)
        self.assertEqual((s['week_elapsed_share'], s['pace']), (0.25, 'red'))

    def test_no_budget(self):
        self.home.transcript('s1').user(NOW - H, 'x').assistant(NOW - 600)
        s = self.status()
        self.assertEqual(s['pace'], 'unknown')
        self.assertIn('pace unknown', self.run_cli('status').stdout)

    def test_empty_home(self):
        s = self.status()
        self.assertEqual((s['calls']['total'], s['week_units'], s['pace']), (0, 0, 'unknown'))
        line = self.run_cli('status').stdout
        self.assertIn('pace unknown', line)
        self.assertIn('findings new 0, asked 0, authorized 0', line)

    def test_home_project_without_questions_session_warns(self):
        repo = self.home.git_repo('home-proj')
        self.home.usage_role('local_u', home_project=repo)
        self.assertIn('warning', self.run_cli('status').stdout)
        self.home.lock('home-proj', repo, 'local_sup', mailbox='local_box')
        self.assertNotIn('warning', self.run_cli('status').stdout)


class PageTest(Base):
    def test_page_content(self):
        scenarios.large_fire(self.home, NOW)
        self.assertEqual(self.run_cli('tick').returncode, 0)
        finding = json.loads(self.run_cli('list', '--json').stdout)[0]
        page = read(os.path.join(self.home.state, 'usage.html'))
        self.assertRegex(page, r'<meta http-equiv="refresh" content="300">')
        self.assertIn(finding['id'], page)
        self.assertIn('>new<', page)
        self.assertIn('prefers-color-scheme: dark', page)
        self.assertIn('name="viewport"', page)
        self.assertNotRegex(page, r'https?://')

    def test_labels_come_from_config(self):
        self.home.config(labels={'title': 'Consumo'})
        self.assertEqual(self.run_cli('page').returncode, 0)
        self.assertIn('<title>Consumo</title>', read(os.path.join(self.home.state, 'usage.html')))


class ShowListTest(Base):
    def test_show_and_list(self):
        scenarios.large_fire(self.home, NOW)
        self.assertEqual(self.run_cli('tick').returncode, 0)
        found = json.loads(self.run_cli('list', '--json').stdout)
        fid = found[0]['id']
        r = self.run_cli('show', fid)
        self.assertEqual(r.returncode, 0)
        self.assertIn('transcript locations:', r.stdout)
        self.assertRegex(r.stdout, r's-ctx\.jsonl:\d+')
        self.assertEqual(json.loads(self.run_cli('list', '--state', 'new', '--applier', 'project-supervisor',
                                                 '--json').stdout)[0]['id'], fid)
        self.assertEqual(json.loads(self.run_cli('list', '--state', 'asked', '--json').stdout), [])
        self.assertEqual(json.loads(self.run_cli('list', '--project', 'nope', '--json').stdout), [])
        self.assertIn(fid, self.run_cli('list').stdout)

    def test_unknown_id(self):
        r = self.run_cli('show', 'loop-0000000000')
        self.assertEqual((r.returncode, r.stdout), (2, ''))


# ---------------------------------------------------------------------------------------------------- 5. timer, scope
class TimerTest(Base):
    def snapshot(self):
        out = {}
        for root, _, files in os.walk(self.home.root):
            for name in files:
                path = os.path.join(root, name)
                with open(path, 'rb') as fh:
                    out[os.path.relpath(path, self.home.root)] = fh.read()
        return out

    def test_print_touches_nothing(self):
        self.home.config(timer_interval_min=7)
        before = self.snapshot()
        r = self.run_cli('timer', 'print')
        self.assertEqual(r.returncode, 0)
        self.assertIn('Type=oneshot', r.stdout)
        self.assertIn(f'{os.path.realpath(SCRIPT)} tick', r.stdout)
        self.assertIn('OnUnitActiveSec=7min', r.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_install_and_uninstall_with_a_fake_systemctl(self):
        bindir = os.path.join(self.tmp, 'fakebin')
        os.makedirs(bindir)
        log = os.path.join(self.tmp, 'systemctl.log')
        fake = os.path.join(bindir, 'systemctl')
        with open(fake, 'w') as fh:
            fh.write(f'#!/bin/sh\necho "$@" >> {log}\n')
        os.chmod(fake, 0o755)
        env = {'PATH': bindir + os.pathsep + os.environ.get('PATH', '')}
        self.assertEqual(self.run_cli('timer', 'install', env=env).returncode, 0)
        units = os.path.join(self.home.root, '.config', 'systemd', 'user')
        self.assertTrue(os.path.isfile(os.path.join(units, 'usage-watch.service')))
        self.assertTrue(os.path.isfile(os.path.join(units, 'usage-watch.timer')))
        self.assertIn('installed', self.run_cli('timer', 'status', env=env).stdout)
        calls = read(log)
        self.assertIn('--user daemon-reload', calls)
        self.assertIn('--user enable --now usage-watch.timer', calls)
        self.assertEqual(self.run_cli('timer', 'uninstall', env=env).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(units, 'usage-watch.timer')))
        self.assertIn('--user disable --now usage-watch.timer', read(log))


class WriteScopeTest(TimerTest):
    def test_a_full_tick_changes_only_the_state_dir_and_the_page(self):
        repo = self.home.git_repo('proj')
        self.home.lock('proj', repo, 'local_sup', mailbox='local_box')
        self.home.app_record('local_box', 'cli-box', repo)
        os.makedirs(os.path.join(self.home.queue), exist_ok=True)
        os.makedirs(os.path.join(self.home.override, 'config'), exist_ok=True)
        self.home.piece('agent-model-gate', {'enabled': False})
        for rule, fire, _, _ in scenarios.CASES:
            if rule not in ('role-model',):
                fire(self.home, NOW)
        before = self.snapshot()
        for cmd in (('tick',), ('status',), ('status', '--json'), ('list',), ('page',)):
            self.assertEqual(self.run_cli(*cmd).returncode, 0, cmd)
        after = self.snapshot()
        changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
        state = os.path.relpath(self.home.state, self.home.root)
        self.assertTrue(changed)
        self.assertEqual({p for p in changed if not p.startswith(state + os.sep)}, set())

    def test_self_test_writes_nothing_in_the_home(self):
        before = self.snapshot()
        r = self.run_cli('self-test')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('0 failure(s)', r.stdout)
        self.assertEqual(self.snapshot(), before)


class ContractTest(Base):
    def test_contract_probes_pass_in_a_temporary_home(self):
        from scripts.toolkit import contracts
        target = os.path.join(self.home.root, '.claude')
        os.makedirs(os.path.join(target, 'scripts', 'lib'), exist_ok=True)
        shutil.copy(SCRIPT, os.path.join(target, 'scripts', 'usage-watch'))
        shutil.copytree(os.path.join(LIB, 'usage_watch'), os.path.join(target, 'scripts', 'lib', 'usage_watch'),
                        ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy(os.path.join(LIB, 'toolkit_config.py'), os.path.join(target, 'scripts', 'lib'))
        keys = ('HOME', 'CLAUDE_TOOLKIT_CONFIG_DIR', 'USAGE_WATCH_NOW', 'SUPERVISOR_LOCK_HOME', 'ASK_QUEUE_DIR',
                'CLAUDE_TOOLKIT_OVERRIDE')
        old = {k: os.environ.get(k) for k in keys}
        for k in keys:
            os.environ.pop(k, None)
        os.environ['HOME'] = self.home.root
        try:
            ran, failures = contracts.run_probes(contracts.Path(target))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertGreaterEqual(ran, 7)
        self.assertEqual([f.render() for f in failures], [])


# ==================================================================================================== part B: the role
SUPERVISION_SCRIPTS = ('ask-queue', 'supervisor-lock')
DEV = 'local_dev'          # the questions session that records the developer's answers
ROLE_APP, ROLE_CLI = 'local_role', 'cli-role'
ROLE_ENV = {'CLAUDE_CODE_SESSION_ID': ROLE_CLI, 'CLAUDE_CODE_HOST_SESSION_ID': ROLE_APP}


class RoleBase(Base):
    """A temporary HOME with the supervision scripts installed (symlinks to the repository copies)."""

    def setUp(self):
        super().setUp()
        self.scripts = os.path.join(self.home.root, '.claude', 'scripts')
        os.makedirs(self.scripts, exist_ok=True)
        for name in SUPERVISION_SCRIPTS:
            os.symlink(str(REPO_ROOT / 'global/scripts' / name), os.path.join(self.scripts, name))
        self.home_repo = self.home.git_repo('home-proj')
        self.home.usage_role(ROLE_APP, ROLE_CLI, home_project=self.home_repo)

    def tool(self, name, *args, env=None, now=NOW):
        e = self.home.env(now=now)
        e.update(env or {})
        return subprocess.run([sys.executable, str(REPO_ROOT / 'global/scripts' / name), *args], capture_output=True,
                              text=True, env=e, timeout=120)

    def role(self, *args, now=NOW, env=None):
        return self.run_cli(*args, now=now, env=dict(ROLE_ENV, **(env or {})))

    def queue(self, project):
        r = self.tool('ask-queue', 'list', '--project', project, '--json')
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def answer(self, qid, text, by=DEV):
        env = {'CLAUDE_CODE_HOST_SESSION_ID': by} if by else {}
        r = self.tool('ask-queue', 'answer', qid, '--text', text, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def findings(self):
        with self.sandbox:
            return store.read(C.load())

    def finding(self, fid):
        return self.findings()[fid]

    def set_state(self, fid, state, **extra):
        with self.sandbox:
            cfg = C.load()
            found = store.read(cfg)
            found[fid].update(state=state, **extra)
            store.write(cfg, found)

    def tick(self, now=NOW):
        r = self.run_cli('tick', now=now)
        self.assertEqual(r.returncode, 0, r.stderr)

    def only(self, rule=None, kind=None):
        found = [f for f in self.findings().values() if (rule is None or f['rule'] == rule)
                 and (kind is None or f['proposal']['kind'] == kind)]
        self.assertEqual(len(found), 1, found)
        return found[0]['id']

    # -------------------------------------------------------------------- fixtures for each proposal kind
    def seed_model(self):
        """A session-model finding in a supervised project with a questions session (role-model on `cli-box`)."""
        scenarios.role_fire(self.home, NOW)
        self.tick()
        return self.only('role-model', 'session-model')

    def seed_note(self, cwd=None):
        tr = self.home.transcript('s-ctx', cwd=cwd)
        tr.user(NOW - 3 * H, 'go')
        for i in range(25):
            tr.assistant(NOW - 3 * H + i * 60, cr=200000)
        self.tick()
        return self.only('large-context', 'note')

    def seed_config(self):
        StoreTest.config_trigger_sessions(self, self.home)
        self.home.piece('agent-model-gate', {'enabled': False})
        self.tick()
        return self.only(kind='config')

    def ask(self, fid, question='Should this change be made?'):
        r = self.role('ask', fid, '--question', question)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.finding(fid)['queue']['id']

    def authorize(self, fid, text='Apply.'):
        qid = self.ask(fid)
        self.answer(qid, text)
        r = self.role('decide', fid)
        self.assertEqual(r.returncode, 0, r.stderr)
        return qid

    def tree(self, skip_state=True):
        out = {}
        state = os.path.relpath(self.home.state, self.home.root) + os.sep
        for root, _, files in os.walk(self.home.root):
            for name in files:
                path = os.path.join(root, name)
                rel = os.path.relpath(path, self.home.root)
                if skip_state and rel.startswith(state):
                    continue
                if os.path.islink(path):
                    continue
                with open(path, 'rb') as fh:
                    out[rel] = fh.read()
        return out

    def tickets(self):
        with self.sandbox:
            return flow.read_tickets(C.load())


# ---------------------------------------------------------------------------------------------------- 6. usage role
class UsageRoleTest(RoleBase):
    def lock(self, *args, env=None):
        return self.tool('supervisor-lock', *args, env=env)

    def record(self):
        return json.loads(read(os.path.join(self.home.supervisor, 'usage-role.json')))

    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.home.supervisor, 'usage-role.json'))

    def test_claim_resume_held_and_listing(self):
        r = self.lock('usage-role', '--claim', '--session', 'local_a', '--dir', self.home_repo,
                      env={'CLAUDE_CODE_SESSION_ID': 'cli-a'})
        self.assertEqual((r.returncode, r.stdout.split()[0]), (0, 'CLAIMED'), r.stderr)
        rec = self.record()
        self.assertEqual((rec['session_id'], rec['cli_session_id'], rec['home_project']),
                         ('local_a', 'cli-a', self.home_repo))
        self.assertEqual(self.lock('usage-role', '--claim', '--session', 'local_a').stdout.split()[0], 'RESUMED')
        r = self.lock('usage-role', '--claim', '--session', 'local_b')
        self.assertEqual((r.returncode, r.stdout.split()[0]), (3, 'HELD'))
        self.assertEqual(self.record()['session_id'], 'local_a')
        listed = json.loads(self.lock('list', '--json').stdout)['usage_role']
        self.assertEqual((listed['session_id'], listed['home_project'], listed['status']),
                         ('local_a', self.home_repo, 'HELD'))

    def test_stale_holder_and_takeover(self):
        self.lock('usage-role', '--claim', '--session', 'local_a', '--dir', self.home_repo)
        rec = self.record()
        rec['heartbeat'] = '2000-01-01T00:00:00+00:00'
        with open(os.path.join(self.home.supervisor, 'usage-role.json'), 'w') as fh:
            json.dump(rec, fh)
        r = self.lock('usage-role', '--claim', '--session', 'local_b')
        self.assertEqual((r.returncode, r.stdout.split()[0]), (4, 'STALE'))
        r = self.lock('usage-role', '--claim', '--session', 'local_b', '--from', 'local_a', '--dir', self.home_repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record()['session_id'], 'local_b')

    def test_beat_and_release_by_the_holder_only(self):
        self.lock('usage-role', '--claim', '--session', 'local_a', '--dir', self.home_repo)
        self.assertEqual(self.lock('usage-role', '--beat', '--session', 'local_b').returncode, 3)
        self.assertEqual(self.lock('usage-role', '--beat', '--session', 'local_a').returncode, 0)
        self.assertEqual(self.lock('usage-role', '--release', '--session', 'local_b').returncode, 3)
        self.assertEqual(self.record()['session_id'], 'local_a')
        self.assertEqual(self.lock('usage-role', '--release', '--session', 'local_a').returncode, 0)
        self.assertIsNone(json.loads(self.lock('list', '--json').stdout)['usage_role'])

    def test_the_holder_is_never_a_project_session(self):
        repo = self.home.git_repo('proj')
        self.lock('acquire', '--dir', repo, '--session', 'local_sup')
        for sid, cli in (('local_a', 'cli-a'), ('local_w', 'cli-w')):
            self.home.app_record(sid, cli, repo, title=sid)
        self.lock('usage-role', '--claim', '--session', 'local_a', '--dir', repo)
        listed = json.loads(self.lock('open', '--dir', repo, '--json').stdout)
        self.assertEqual([r['id'] for r in listed['open']], ['local_w'])
        closable = self.lock('closable', '--dir', repo).stdout
        self.assertNotIn('local_a', closable)


# ---------------------------------------------------------------------------------------------------- 7. ask, decide
class AskTest(RoleBase):
    def test_supervised_project_and_empty_order(self):
        fid = self.seed_model()
        repo = self.finding(fid)['project_root']
        self.assertTrue(repo.endswith('proj-q'))
        qid = self.ask(fid)
        items = self.queue(repo)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item['id'], item['key'], item['status'], item['default']),
                         (qid, f'usage-watch:{fid}', 'open', C.DEFAULTS['no_default']))
        self.assertTrue(item['question'].endswith(C.DEFAULTS['authorize_hint']))
        f = self.finding(fid)
        self.assertIn(f'session {f["target_app_id"]} model = {f["proposal"]["value"]}', item['question'])
        self.assertNotIn('order', item)
        self.assertEqual(item['blocks'], 'nothing')
        f = self.finding(fid)
        self.assertEqual((f['state'], f['queue']['id'], f['asked_by']), ('asked', qid,
                                                                         {'session': ROLE_CLI, 'host_session': ROLE_APP}))
        self.assertEqual(self.queue(self.home_repo), [])

    def test_asking_twice(self):
        fid = self.seed_model()
        self.ask(fid)
        r = self.role('ask', fid, '--question', 'again')
        self.assertEqual(r.returncode, 3)
        self.assertEqual(len(self.queue(self.finding(fid)['project_root'])), 1)

    def test_unsupervised_and_machine_wide_go_to_the_home_project(self):
        fid = self.seed_note(cwd=self.home.git_repo('lonely'))
        self.ask(fid)
        self.assertEqual([i['key'] for i in self.queue(self.home_repo)], [f'usage-watch:{fid}'])
        cid = self.seed_config()
        self.ask(cid)
        self.assertEqual(len(self.queue(self.home_repo)), 2)

    def test_order_text_from_config(self):
        self.home.config(order_text='as ordered')
        fid = self.seed_model()
        self.ask(fid)
        self.assertEqual(self.queue(self.finding(fid)['project_root'])[0]['order'], 'as ordered')

    def test_unknown_id(self):
        self.assertEqual(self.role('ask', 'loop-0000000000').returncode, 2)


class DecideTest(RoleBase):
    def setUp(self):
        super().setUp()
        self.fid = self.seed_model()
        self.qid = self.ask(self.fid)

    def decide(self):
        return self.role('decide', self.fid)

    def test_queue_item_still_open_or_asked(self):
        self.assertEqual(self.decide().returncode, 3)
        self.assertEqual(self.tool('ask-queue', 'asked', self.qid).returncode, 0)
        r = self.decide()
        self.assertEqual(r.returncode, 3)
        self.assertIn('not answered', r.stderr)
        self.assertEqual(self.finding(self.fid)['state'], 'asked')

    def test_authorising_answer_from_the_questions_session(self):
        self.answer(self.qid, ' Apply. ')
        self.assertEqual(self.decide().returncode, 0)
        f = self.finding(self.fid)
        self.assertEqual(f['state'], 'authorized')
        last = f['history'][-1]
        self.assertEqual((last['state'], last['answer'], last['answered_by']), ('authorized', ' Apply. ', DEV))

    def test_any_other_answer_rejects(self):
        self.answer(self.qid, C.DEFAULTS['no_default'])
        self.assertEqual(self.decide().returncode, 0)
        self.assertEqual(self.finding(self.fid)['state'], 'rejected')

    def test_closed_without_an_answer_rejects(self):
        self.assertEqual(self.tool('ask-queue', 'close', self.qid).returncode, 0)
        self.assertEqual(self.decide().returncode, 0)
        self.assertEqual(self.finding(self.fid)['state'], 'rejected')

    def untrusted(self, by):
        self.answer(self.qid, 'apply', by=by)
        r = self.decide()
        self.assertEqual(r.returncode, 3, by)
        self.assertIn('not trusted', r.stderr)
        self.assertEqual(self.finding(self.fid)['state'], 'asked')

    def test_the_role_holder_answering_is_not_trusted(self):
        self.untrusted(ROLE_APP)

    def test_the_asker_answering_is_not_trusted(self):
        self.untrusted(ROLE_CLI)

    def test_answer_recorded_by_nobody_is_not_trusted(self):
        self.answer(self.qid, 'apply', by=None)
        self.assertEqual(self.decide().returncode, 3)
        self.assertEqual(self.finding(self.fid)['state'], 'asked')


class NoSupervisionTest(Base):
    def test_measuring_works_and_role_commands_exit_6(self):
        scenarios.large_fire(self.home, NOW)
        self.assertEqual(self.run_cli('tick').returncode, 0)
        r = self.run_cli('wait', '--session', 'X')
        self.assertEqual(r.returncode, 6)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)


# ---------------------------------------------------------------------------------------------------- 8. apply
class ApplyRefusalTest(RoleBase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.home.override, 'config'), exist_ok=True)
        self.config_id = self.seed_config()

    def both(self):
        scenarios.role_fire(self.home, NOW)
        self.tick()
        return self.config_id, self.only('role-model', 'session-model')

    def assert_refused(self, fid, before):
        r = self.role('apply', fid)
        self.assertEqual(r.returncode, 3, (fid, r.stderr))
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.tickets(), [])

    def test_every_other_state_is_refused_for_both_kinds(self):
        for fid in self.both():
            for state in ('new', 'asked', 'rejected', 'applied', 'measured'):
                self.set_state(fid, state)
                self.assert_refused(fid, self.tree())

    def test_a_store_edited_by_hand(self):
        for fid in self.both():
            self.ask(fid)
            self.set_state(fid, 'authorized', answer={'text': 'apply', 'by': DEV})
            before = self.tree()
            self.assert_refused(fid, before)
        self.assertFalse(os.path.exists(os.path.join(self.home.override, 'config', 'agent-model-gate.json')))
        self.assertEqual(json.loads(read(os.path.join(self.home.config_dir, 'agent-model-gate.json'))),
                         {'enabled': False})

    def test_an_answer_changed_after_decide_is_refused(self):
        fid = self.config_id
        qid = self.authorize(fid)
        self.set_state(fid, 'authorized', answer={'text': 'something else', 'by': DEV})
        self.assert_refused(fid, self.tree())
        self.assertTrue(qid)

    def test_a_change_edited_after_the_answer_is_refused(self):
        """G-16: the answer authorises the change written in the question, not whatever the store holds later."""
        config_id, model_id = self.both()
        self.authorize(config_id)
        self.authorize(model_id)
        found = self.findings()
        self.set_state(config_id, 'authorized', proposal=dict(found[config_id]['proposal'], key='other_key'))
        self.set_state(model_id, 'authorized', target_app_id='local_someone_else')
        for fid in (config_id, model_id):
            self.assert_refused(fid, self.tree())
            self.assertEqual(self.finding(fid)['state'], 'authorized')
        self.assertFalse(os.path.exists(os.path.join(self.home.override, 'config', 'agent-model-gate.json')))

    def test_note_without_how(self):
        fid = self.seed_note()
        self.authorize(fid)
        r = self.role('apply', fid)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.finding(fid)['state'], 'authorized')
        r = self.role('apply', fid, '--how', 'compacted the session')
        self.assertEqual(r.returncode, 0, r.stderr)
        f = self.finding(fid)
        self.assertEqual((f['state'], f['applied']['how']), ('applied', 'compacted the session'))


class ConfigApplyTest(RoleBase):
    def install(self):
        os.makedirs(os.path.join(self.home.override, 'config'), exist_ok=True)
        with open(os.path.join(self.home.override, 'config', 'agent-model-gate.json'), 'w') as fh:
            json.dump({'advisor_max_per_day': 3}, fh)
        r = subprocess.run([sys.executable, '-m', 'scripts.toolkit', 'install', '--modules', 'core,usage',
                            '--override', self.home.override, '--target', os.path.join(self.home.root, '.claude')],
                           capture_output=True, text=True, env=self.home.env(), cwd=str(REPO_ROOT), timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])

    def drift(self):
        return subprocess.run([sys.executable, '-m', 'scripts.toolkit', 'drift', '--modules', 'core,usage',
                               '--override', self.home.override, '--target', os.path.join(self.home.root, '.claude')],
                              capture_output=True, text=True, env=self.home.env(), cwd=str(REPO_ROOT), timeout=300)

    def test_authorised_config_change_and_drift(self):
        self.install()
        piece = os.path.join(self.home.config_dir, 'agent-model-gate.json')
        installed_before = json.loads(read(piece))
        self.assertFalse(installed_before['enabled'])
        StoreTest.config_trigger_sessions(self, self.home)
        self.tick()
        fid = self.only(kind='config')
        self.authorize(fid)
        r = self.role('apply', fid)
        self.assertEqual(r.returncode, 0, r.stderr)
        override = json.loads(read(os.path.join(self.home.override, 'config', 'agent-model-gate.json')))
        self.assertEqual(override, {'advisor_max_per_day': 3, 'enabled': True})
        self.assertTrue(json.loads(read(piece))['enabled'])
        from scripts.toolkit import config as toolkit_config
        expected = toolkit_config.render(toolkit_config.resolve(['agent-model-gate'], {'agent-model-gate': override})
                                         ['agent-model-gate'])
        with open(piece, 'rb') as fh:
            self.assertEqual(fh.read(), expected)
        f = self.finding(fid)
        self.assertEqual(f['state'], 'applied')
        self.assertEqual(f['applied']['previous'], {'override': {'present': False, 'value': None},
                                                    'installed': {'present': True, 'value': False}})
        d = self.drift()
        self.assertNotIn('agent-model-gate.json', d.stdout, d.stdout)

    def test_no_override(self):
        fid = self.seed_config()
        self.authorize(fid)
        piece = os.path.join(self.home.config_dir, 'agent-model-gate.json')
        before = read(piece)
        r = self.role('apply', fid)
        self.assertEqual(r.returncode, 3)
        self.assertIn('no override', r.stderr)
        self.assertEqual(read(piece), before)
        self.assertEqual(self.finding(fid)['state'], 'authorized')


class TicketApplyTest(RoleBase):
    def test_session_model_ticket(self):
        fid = self.seed_model()
        self.authorize(fid)
        r = self.role('apply', fid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.finding(fid)['state'], 'applied')
        (ticket,) = self.tickets()
        self.assertEqual((ticket['session'], ticket['field'], ticket['value'], ticket['used']),
                         ('local_box', 'model', C.DEFAULTS['cheap_model'], False))
        self.assertEqual(ticket['expires_at'], NOW + C.DEFAULTS['ticket_ttl_s'])

    def test_no_target_id(self):
        fid = self.seed_model()
        self.authorize(fid)
        self.set_state(fid, 'authorized', target_app_id=None)
        self.assertEqual(self.role('apply', fid).returncode, 3)
        self.assertEqual(self.tickets(), [])


# ---------------------------------------------------------------------------------------------------- 8.4 the gate
HOOK = str(REPO_ROOT / 'global/hooks/usage-apply-gate')
SET_MODEL = 'mcp__ccd_session_mgmt__set_session_model'
SET_EFFORT = 'mcp__ccd_session_mgmt__set_session_effort'


class TicketGateTest(RoleBase):
    def hook(self, payload, now=NOW, raw=None):
        r = subprocess.run([sys.executable, HOOK], input=raw if raw is not None else json.dumps(payload),
                           capture_output=True, text=True, env=self.home.env(now=now), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def call(self, session='local_box', model='m-cheap', caller=ROLE_CLI, tool=SET_MODEL, now=NOW):
        field = 'model' if tool == SET_MODEL else 'effort'
        return self.hook({'hook_event_name': 'PreToolUse', 'tool_name': tool, 'session_id': caller,
                          'tool_input': {'session_id': session, field: model}}, now=now)

    def put_ticket(self, **extra):
        ticket = dict({'id': 't1', 'finding': 'f', 'session': 'local_box', 'field': 'model', 'value': 'm-cheap',
                       'issued_at': C.iso(NOW), 'expires_at': NOW + 900, 'used': False}, **extra)
        os.makedirs(self.home.state, exist_ok=True)
        with open(os.path.join(self.home.state, 'tickets.json'), 'w') as fh:
            json.dump({'tickets': [ticket]}, fh)

    def denied(self, out):
        return json.loads(out)['hookSpecificOutput']['permissionDecision'] == 'deny' if out.strip() else False

    def test_no_ticket(self):
        out = self.call()
        self.assertTrue(self.denied(out))
        self.assertIn('usage-watch apply', out)

    def test_one_ticket_one_call(self):
        self.put_ticket()
        self.assertEqual(self.call(), '')
        self.assertTrue(self.tickets()[0]['used'])
        self.assertTrue(self.denied(self.call()))

    def test_expired_or_mismatched(self):
        for extra, call in (({'expires_at': NOW - 1}, {}), ({}, {'session': 'local_other'}),
                            ({}, {'model': 'm-other'}), ({}, {'tool': SET_EFFORT})):
            self.put_ticket(**extra)
            self.assertTrue(self.denied(self.call(**call)), (extra, call))
            self.assertFalse(self.tickets()[0]['used'])

    def test_the_holder_by_its_app_id_from_the_environment(self):
        self.put_ticket()
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(
            {'tool_name': SET_MODEL, 'session_id': 'cli-unknown', 'tool_input': {'session_id': 'local_box', 'model': 'x'}}),
            capture_output=True, text=True, env=dict(self.home.env(now=NOW), CLAUDE_CODE_HOST_SESSION_ID=ROLE_APP))
        self.assertTrue(self.denied(r.stdout))

    def test_another_session_is_left_alone(self):
        before = self.tree(skip_state=False)
        self.assertEqual(self.call(caller='cli-other'), '')
        self.assertEqual(self.tree(skip_state=False), before)

    def test_no_role_record(self):
        os.remove(os.path.join(self.home.supervisor, 'usage-role.json'))
        self.assertEqual(self.call(), '')

    def test_unparseable_input(self):
        self.assertEqual(self.hook(None, raw='{not json'), '')

    def test_an_internal_error_fails_open_and_is_logged(self):
        os.makedirs(self.home.state, exist_ok=True)
        os.makedirs(os.path.join(self.home.state, 'tickets.json.lock'))   # the flock file cannot be opened
        self.assertEqual(self.call(), '')
        self.assertIn('Traceback', read(os.path.join(self.home.state, 'gate-errors.log')))

    def test_an_issued_ticket_opens_the_gate_once(self):
        fid = self.seed_model()
        self.authorize(fid)
        self.assertEqual(self.role('apply', fid).returncode, 0)
        cheap = C.DEFAULTS['cheap_model']
        self.assertEqual(self.call(model=cheap), '')
        self.assertTrue(self.denied(self.call(model=cheap)))

def snapshot(root):
    out = {}
    for base, _, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            with open(path, 'rb') as fh:
                out[os.path.relpath(path, root)] = fh.read()
    return out


class GateContractTest(Base):
    """The contract's safe probes in a temporary HOME with only the gate installed (no usage role record)."""

    def test_contract_probes(self):
        from scripts.toolkit import contracts
        target = os.path.join(self.home.root, '.claude')
        os.makedirs(os.path.join(target, 'hooks'), exist_ok=True)
        os.makedirs(os.path.join(target, 'scripts', 'lib'), exist_ok=True)
        shutil.copy(HOOK, os.path.join(target, 'hooks', 'usage-apply-gate'))
        shutil.copytree(os.path.join(LIB, 'usage_watch'), os.path.join(target, 'scripts', 'lib', 'usage_watch'),
                        ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy(os.path.join(LIB, 'toolkit_config.py'), os.path.join(target, 'scripts', 'lib'))
        keys = ('HOME', 'CLAUDE_TOOLKIT_CONFIG_DIR', 'USAGE_WATCH_NOW', 'SUPERVISOR_LOCK_HOME', 'ASK_QUEUE_DIR',
                'CLAUDE_TOOLKIT_OVERRIDE', 'CLAUDE_CODE_HOST_SESSION_ID')
        old = {k: os.environ.get(k) for k in keys}
        for k in keys:
            os.environ.pop(k, None)
        os.environ['HOME'] = self.home.root
        before = snapshot(self.home.root)
        try:
            ran, failures = contracts.run_probes(contracts.Path(target))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual([f.render() for f in failures], [])
        self.assertGreaterEqual(ran, 5)
        after = snapshot(self.home.root)
        self.assertEqual({k for k in set(after) ^ set(before) if '__pycache__' not in k}, set())


# ---------------------------------------------------------------------------------------------------- 8.5, 8.6
class MeasureTest(RoleBase):
    APPLIED = NOW - 25 * H

    def seed_applied(self):
        self.home.config(prices=scenarios.UNIT_PER_INPUT_TOKEN, measure_window_h=24)
        tr = self.home.transcript('s-m')
        tr.user(self.APPLIED - 23 * H, 'go')
        for i in range(10):
            tr.assistant(self.APPLIED - 20 * H + i * 60, inp=100)
        for i in range(5):
            tr.assistant(self.APPLIED + 2 * H + i * 60, inp=100)
        self.tick()
        fid = 'large-context-0000000001'
        with self.sandbox:
            cfg = C.load()
            found = store.read(cfg)
            found[fid] = {'id': fid, 'rule': 'large-context', 'scope': {'kind': 'session', 'id': 's-m'},
                          'state': 'applied', 'proposal': {'kind': 'note', 'text': 'x'}, 'applier': 'project-supervisor',
                          'applied': {'kind': 'note', 'how': 'x', 'ts': self.APPLIED, 'at': C.iso(self.APPLIED)},
                          'history': []}
            store.write(cfg, found)
        return fid

    def test_too_early(self):
        fid = self.seed_applied()
        r = self.run_cli('measure', fid, now=self.APPLIED + H)
        self.assertEqual(r.returncode, 4)
        self.assertEqual(self.finding(fid)['state'], 'applied')

    def test_measured(self):
        fid = self.seed_applied()
        r = self.run_cli('measure', fid, now=self.APPLIED + 24 * H)
        self.assertEqual(r.returncode, 0, r.stderr)
        f = self.finding(fid)
        self.assertEqual(f['state'], 'measured')
        self.assertEqual((f['measure']['before'], f['measure']['after']), (1000, 500))


class WalkTest(RoleBase):
    def test_walk_and_redetect(self):
        fid = self.seed_model()
        nid = self.seed_note()
        clock = [NOW]

        def step(*args):
            clock[0] += 60
            r = self.role(*args, now=clock[0])
            self.assertEqual(r.returncode, 0, (args, r.stderr))
            self.tick(now=clock[0])
            self.assertEqual(len([k for k in self.findings() if k == fid]), 1)

        self.ask(fid)
        self.tick()
        self.answer(self.finding(fid)['queue']['id'], 'apply')
        step('decide', fid)
        step('apply', fid)
        clock[0] = NOW + 25 * H
        step('measure', fid)
        self.ask(nid)
        self.answer(self.finding(nid)['queue']['id'], 'no')
        step('decide', nid)
        states = [h['state'] for h in self.finding(fid)['history']]
        self.assertEqual(states, ['new', 'asked', 'authorized', 'applied', 'measured'])
        self.assertEqual(self.finding(nid)['state'], 'rejected')
        keys = [i['key'] for p in (self.finding(fid)['project_root'], self.home_repo) for i in self.queue(p)]
        self.assertEqual(sorted(keys), sorted([f'usage-watch:{fid}', f'usage-watch:{nid}']))


# ---------------------------------------------------------------------------------------------------- 9. watcher
class WaitTest(RoleBase):
    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.home.supervisor, 'usage-role.json'))
        r = self.tool('supervisor-lock', 'usage-role', '--claim', '--session', ROLE_APP, '--dir', self.home_repo,
                      env={'CLAUDE_CODE_SESSION_ID': ROLE_CLI})
        self.assertEqual(r.returncode, 0, r.stderr)

    def wait(self, timeout='2'):
        return self.role('wait', '--session', ROLE_APP, '--timeout', timeout, '--interval', '0.2')

    def background(self):
        e = self.home.env(now=NOW)
        e.update(ROLE_ENV)
        return subprocess.Popen([sys.executable, SCRIPT, 'wait', '--session', ROLE_APP, '--timeout', '60',
                                 '--interval', '0.2'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)

    def test_nothing_new(self):
        r = self.wait()
        self.assertEqual((r.returncode, r.stdout), (0, 'TIMEOUT 2s\n'))

    def test_new_finding_once(self):
        proc = self.background()
        scenarios.large_fire(self.home, NOW)
        self.tick()
        out, _ = proc.communicate(timeout=90)
        self.assertEqual(proc.returncode, 0)
        fid = self.only('large-context')
        self.assertEqual(out, f'FINDING {fid} large-context session:s-ctx\n')
        self.assertEqual(self.wait().stdout, 'TIMEOUT 2s\n')

    def test_answer_once(self):
        fid = self.seed_note()
        self.wait()                       # announces the finding
        qid = self.ask(fid)
        self.assertEqual(self.wait().stdout, 'TIMEOUT 2s\n')
        proc = self.background()
        self.answer(qid, 'apply')
        out, _ = proc.communicate(timeout=90)
        self.assertEqual((proc.returncode, out), (0, f'ANSWER {fid}\n'))
        self.assertEqual(self.wait().stdout, 'TIMEOUT 2s\n')

    def test_not_the_holder(self):
        r = self.role('wait', '--session', 'local_other', '--timeout', '2')
        self.assertEqual(r.returncode, 5)
        self.assertIn('NOT HOLDER', r.stderr)


class BacklogTest(RoleBase):
    def backlog(self, repo):
        return self.tool('supervisor-lock', 'backlog', '--dir', repo)

    def test_script_missing_changes_nothing(self):
        repo = self.home.git_repo('proj')
        r = self.backlog(repo)
        self.assertEqual((r.returncode, r.stdout), (0, 'BACKLOG work=0 parked=0\n'))

    def test_backlog_line_until_applied(self):
        os.symlink(SCRIPT, os.path.join(self.scripts, 'usage-watch'))
        repo = self.home.git_repo('proj')
        self.home.lock('proj', repo, 'local_sup', mailbox='local_box')
        fid = self.seed_note(cwd=repo)
        self.assertEqual(self.backlog(repo).returncode, 0)
        self.authorize(fid)
        r = self.backlog(repo)
        self.assertEqual(r.returncode, 7)
        self.assertIn(f'USAGE {fid} large-context: ', r.stdout)
        self.assertEqual(self.role('apply', fid, '--how', 'compacted').returncode, 0)
        r = self.backlog(repo)
        self.assertEqual((r.returncode, r.stdout), (0, 'BACKLOG work=0 parked=0\n'))


class RoleSelfTestTest(RoleBase):
    def test_self_test_covers_the_role(self):
        r = self.run_cli('self-test')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for word in ('walk', 'untrusted', 'hand-edited', 'ticket gate', 'wait'):
            self.assertIn(word, r.stdout)


if __name__ == '__main__':
    unittest.main()
