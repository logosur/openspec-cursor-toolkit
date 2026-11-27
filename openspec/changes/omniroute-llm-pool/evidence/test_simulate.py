"""Unit tests for simulate.py. Every transcript is invented and built in a temp dir.

Run from the repository root:
    python3 -m unittest openspec/changes/omniroute-llm-pool/evidence/test_simulate.py
"""
import calendar
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simulate  # noqa: E402

BASE = 1_795_000_000  # 2026-11-18, UTC; every figure below is relative to it
WEIGHTS = [1.0, 0.1, 1.25, 5.0]
UNIT_WEIGHTED = 1 * 1 + 10 * 0.1 + 100 * 1.25 + 1000 * 5.0  # weighted cost of one usage unit, see Builder.usage


def iso(epoch):
    return simulate._iso(epoch).replace('Z', '.000Z')


class Builder:
    """Writes one invented transcript. A usage 'unit' k means fresh k, cache read 10k, cache write 100k, output 1000k."""

    def __init__(self, path, tasks_dir, start):
        self.path, self.tasks_dir, self.t = path, tasks_dir, start
        self.records, self.n = [], 0
        self.owner = 'owner-demo'   # the --owner of every arming

    # -- low level
    def _emit(self, rec, sidechain=False):
        self.n += 1
        self.t += 1
        rec.update({'uuid': f'rec-{self.n}', 'sessionId': 'sess-invented', 'isSidechain': sidechain,
                    'timestamp': iso(self.t)})
        self.records.append(rec)

    def at(self, epoch):
        self.t = epoch

    @staticmethod
    def usage(units):
        return {'input_tokens': units, 'cache_read_input_tokens': 10 * units,
                'cache_creation_input_tokens': 100 * units, 'output_tokens': 1000 * units}

    def tool(self, name, **tool_input):
        self.n += 1
        return {'type': 'tool_use', 'id': f'toolu_{self.n}', 'name': name, 'input': tool_input}

    def arm(self, guard=False):
        cmd = (f'~/scripts/supervisor-lock wait --dir ~/work --owner {self.owner} --timeout 600'
               + (' --guard' if guard else ''))
        return self.tool('Bash', command=cmd, run_in_background=True)

    def assistant(self, blocks, units, mid=None, sidechain=False):
        """One record per block, all with the same message id and usage (as the real files repeat them)."""
        mid = mid or f'msg_{self.n + 1}'
        for block in blocks:
            self._emit({'type': 'assistant', 'message': {'id': mid, 'role': 'assistant', 'usage': self.usage(units),
                                                         'content': [block]}}, sidechain)

    def result(self, block, text, as_list=False):
        content = [{'type': 'text', 'text': text}] if as_list else text
        self._emit({'type': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': block['id'], 'content': content}]}})

    def human(self, text='please continue', meta=False):
        rec = {'type': 'user', 'message': {'role': 'user', 'content': text}}
        if meta:
            rec['isMeta'] = True
        self._emit(rec)

    def notification(self, arm, task, output_file=None, status='completed'):
        body = (f'<task-notification>\n<task-id>{task}</task-id>\n<tool-use-id>{arm["id"]}</tool-use-id>\n'
                f'<output-file>{output_file or os.path.join(self.tasks_dir, task + ".output")}</output-file>\n'
                f'<status>{status}</status>\n</task-notification>')
        self._emit({'type': 'user', 'origin': {'kind': 'task-notification'},
                    'message': {'role': 'user', 'content': body}})

    # -- turns
    def wake(self, arm, task, output, read_units=1, units=1, before=(), after=(), guard_next=False, read_as_list=False,
             compaction=False, write_output_file=None, status='completed'):
        """A wake turn: read the output (when `output` is not None), run `before`, re-arm, run `after`.

        Returns the new arming. The re-arm message carries `units`; the read message carries `read_units`.
        """
        path = os.path.join(self.tasks_dir, task + '.output')
        if write_output_file is not None:
            with open(path, 'w') as fh:
                fh.write(write_output_file)
        self.notification(arm, task, status=status)
        if output is not None:
            read = self.tool('Bash', command=f'cat {path}')
            self.assistant([read], read_units)
            self.result(read, output, as_list=read_as_list)
        if compaction:
            self._emit({'type': 'system', 'subtype': 'compact_boundary'})
        new_arm = self.arm(guard_next)
        blocks = list(before) + [new_arm] + list(after)
        self.assistant(blocks, units)
        for block in blocks:
            if block is not new_arm:
                self.result(block, 'ok')
        return new_arm

    def bare_wake(self, arm, task, write_output_file=None, status='completed', then_human=True):
        """A wake that starts no turn of its own: the notification, then straight away the next user record.

        With `then_human` that record is a real user message; without it the caller emits the next notification.
        """
        if write_output_file is not None:
            with open(os.path.join(self.tasks_dir, task + '.output'), 'w') as fh:
                fh.write(write_output_file)
        self.notification(arm, task, status=status)
        if then_human:
            self.human('next real message')

    def write(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w') as fh:
            for rec in self.records:
                fh.write(json.dumps(rec) + '\n')


IDLE = 'STATUS sess-a idle->busy\nSTATUS sess-b idle->busy\n[exited with code 0]'
ONE_IDLE = 'STATUS sess-c idle->busy'


class SeededCase(unittest.TestCase):
    """Two invented supervisor transcripts with known wakes, plus two files that must be ignored."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='simulate-test-')
        cls.tasks = os.path.join(cls.tmp, 'tasks')
        os.makedirs(cls.tasks)
        cls.projects = os.path.join(cls.tmp, 'projects')
        cls.build_a()
        cls.build_b()
        cls.build_ignored()
        for folder, _dirs, names in os.walk(cls.projects):   # the mtime filter must see the files as recent
            for name in names:
                os.utime(os.path.join(folder, name), (BASE + 10 ** 6, BASE + 10 ** 6))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def build_a(cls):
        b = Builder(os.path.join(cls.projects, 'slug-one', 'sess-a.jsonl'), cls.tasks, BASE)
        cls.a_first = b.t + 1
        b.human('start the round')
        arm = b.arm()
        b.assistant([arm], 1)                                                               # T0: 1 unit
        t = BASE + 600
        # W1: soft idle to busy, not needed. Lists sessions, reads two files, re-arms. A sidechain record that sends a
        # message and carries a huge usage must be ignored, and the duplicated message id counts once.
        b.at(t)
        side = b.tool('SendMessage', to='x')
        b.assistant([side], 900, sidechain=True)
        arm = b.wake(arm, 'tsk-1', IDLE, read_units=2, units=3,
                     before=[b.tool('Bash', command='~/scripts/supervisor-lock sessions --dir ~/work'),
                             b.tool('Read', file_path='~/work/notes-one.md'),
                             b.tool('Read', file_path='~/work/notes-two.md')])           # 5 units
        # W2: soft idle to busy, needed: a message to another session after the re-arm
        b.at(t + 600)
        arm = b.wake(arm, 'tsk-2', 'STATUS sess-d idle->busy', read_units=4, units=5,
                     after=[b.tool('SendMessage', to='sess-d', message='go')], read_as_list=True)   # 9 units
        # W3: soft timeout, not needed (a read-only git command and a git merge-base do not count)
        b.at(t + 1200)
        arm = b.wake(arm, 'tsk-3', 'TIMEOUT 600s', units=6, read_units=0,
                     before=[b.tool('Bash', command='git status && git merge-base HEAD main')])   # 6 units
        # W4: hard, a session finished its turn
        b.at(t + 1800)
        arm = b.wake(arm, 'tsk-4', 'STATUS sess-a busy->idle', read_units=3, units=4)        # 7 units
        # W5: a mixed batch: an idle-to-busy line plus a crash is hard
        b.at(t + 2400)
        arm = b.wake(arm, 'tsk-5', 'STATUS sess-a idle->busy\nCRASH sess-b 0->1', read_units=4, units=4,
                     guard_next=True)                                                        # 8 units
        # W6: the watcher was armed with --guard: hard even though its output is a plain TIMEOUT
        b.at(t + 3000)
        arm = b.wake(arm, 'tsk-6', 'TIMEOUT 600s', read_units=4, units=5)                    # 9 units
        # W7: no tool result reads the output and the output file does not exist: unclassified (no output)
        b.at(t + 3600)
        arm = b.wake(arm, 'tsk-7', None, units=10)                                           # 10 units
        # W7c: a compaction record sits inside the turn: unclassified
        b.at(t + 4200)
        arm = b.wake(arm, 'tsk-7c', ONE_IDLE, read_units=5, units=6, compaction=True)        # 11 units
        # W8: the output is only in the output file: soft idle to busy, not needed
        b.at(t + 4800)
        arm = b.wake(arm, 'tsk-8', None, units=12, write_output_file='STATUS sess-e idle->busy\n')
        # W9..W12: four more soft wakes; W9 also carries the advisory registry line. Rule B sleeps W8..W11 and
        # must wake at W12 (four sleeps in a row)
        for i, (task, out) in enumerate([('tsk-9', ONE_IDLE + '\nREGISTRY_BIG a-file 123 (advice)'), ('tsk-10', ONE_IDLE),
                                         ('tsk-11', ONE_IDLE), ('tsk-12', ONE_IDLE)]):
            b.at(t + 5400 + 600 * i)
            arm = b.wake(arm, task, out, read_units=0, units=1)                              # 1 unit each
        # W13: soft, needed by a deploy command; a grep for a deploy script is not a deploy
        b.at(t + 8400)
        arm = b.wake(arm, 'tsk-13', ONE_IDLE, read_units=1, units=1,
                     before=[b.tool('Bash', command='grep -n deploy ~/work/Makefile')],
                     after=[b.tool('Bash', command='flock -w 3600 ~/state/deploy-vps.lock make deploy')])   # 2 units
        # W14: soft, not needed
        b.at(t + 9000)
        arm = b.wake(arm, 'tsk-14', ONE_IDLE, read_units=1, units=2)                         # 3 units
        # W15: soft timeout, and the transcript ends inside the turn: unclassified (turn not ended)
        b.at(t + 9600)
        b.notification(arm, 'tsk-15')
        read = b.tool('Bash', command=f'cat {os.path.join(cls.tasks, "tsk-15.output")}')
        b.assistant([read], 4)
        b.result(read, 'TIMEOUT 600s')
        cls.a_last = b.t
        b.write()

    @classmethod
    def build_b(cls):
        b = Builder(os.path.join(cls.projects, 'slug-two', 'sess-b.jsonl'), cls.tasks, BASE + 100)
        cls.b_first = b.t + 1
        b.human('start')
        arm = b.arm()
        b.assistant([arm], 1)                                                               # T0: 1 unit
        t = BASE + 20000
        # Bw1 starts a stretch of sleeps; needed by starting a session
        b.at(t)
        arm = b.wake(arm, 'tsk-b1', ONE_IDLE, read_units=1, units=1,
                     after=[b.tool('mcp__ccd_session__start_session', title='x')])           # 2 units
        b.at(t + 3600)
        arm = b.wake(arm, 'tsk-b2', ONE_IDLE, read_units=0, units=1)                         # 1 unit
        b.at(t + 119 * 60)   # 1 h 59 min after the first sleep: still slept
        arm = b.wake(arm, 'tsk-b3', ONE_IDLE, read_units=0, units=1,
                     before=[b.tool('Bash', command='git log --oneline -3')])                # 1 unit
        b.at(t + 130 * 60)   # 2 h 10 min: the bound forces a wake; needed (git push)
        arm = b.wake(arm, 'tsk-b4', ONE_IDLE, read_units=1, units=2,
                     after=[b.tool('Bash', command='git -C ~/work push origin topic')])      # 3 units
        b.at(t + 140 * 60)   # a new stretch; needed (ask-queue add)
        arm = b.wake(arm, 'tsk-b5', ONE_IDLE, read_units=0, units=1,
                     after=[b.tool('Bash', command='~/scripts/ask-queue add --project ~/work --question "x"')])
        # a human message ends the stretch; its turn also re-arms the watcher
        b.at(t + 150 * 60)
        b.human('what is going on?')
        arm = b.arm()
        b.assistant([arm], 1)                                                               # 1 unit
        b.at(t + 160 * 60)   # needed (panel), slept: the stretch restarted after the human turn
        arm = b.wake(arm, 'tsk-b6', ONE_IDLE, read_units=0, units=2,
                     after=[b.tool('Skill', skill='panel-de-decision')])                    # 2 units
        b.at(t + 170 * 60)   # soft timeout, slept
        arm = b.wake(arm, 'tsk-b7', 'TIMEOUT 900s', read_units=0, units=1)                   # 1 unit
        # another background task finishes: an awake turn that is not a wake of the watcher
        b.at(t + 175 * 60)
        other = b.tool('Bash', command='sleep 5', run_in_background=True)
        b.assistant([other], 1)
        b.notification(other, 'tsk-other')
        b.assistant([b.tool('Bash', command='echo done')], 1)                               # the other task: 2 units
        b.at(t + 180 * 60)   # soft, slept: a new stretch
        arm = b.wake(arm, 'tsk-b8', ONE_IDLE, read_units=0, units=1)                         # 1 unit
        b.human('thanks')
        cls.b_last = b.t
        b.write()

    @classmethod
    def build_ignored(cls):
        # A transcript with the command but not in the background, and a plain one: not supervisors.
        b = Builder(os.path.join(cls.projects, 'slug-one', 'sess-c.jsonl'), cls.tasks, BASE)
        b.human('hello')
        b.assistant([b.tool('Bash', command='~/scripts/supervisor-lock wait --owner owner-demo')], 777)
        b.write()
        b = Builder(os.path.join(cls.projects, 'slug-three', 'sess-d.jsonl'), cls.tasks, BASE)
        b.human('hello')
        b.assistant([b.tool('Read', file_path='x')], 777)
        b.write()

    def run_analysis(self, **kw):
        return simulate.analyze(self.projects, **kw)

    # ------------------------------------------------------------------------------------------------ counts

    def test_counts_and_kinds(self):
        res = self.run_analysis()
        self.assertEqual(len(res['supervisors']), 2)
        self.assertEqual([s['label'] for s in res['supervisors']], ['S1', 'S2'])
        a, b = res['supervisors']
        self.assertEqual((a['wakes'], a['hard'], a['soft_idle'], a['soft_timeout'], a['unclassified']), (16, 3, 9, 1, 3))
        self.assertEqual((b['wakes'], b['hard'], b['soft_idle'], b['soft_timeout'], b['unclassified']), (8, 0, 7, 1, 0))
        self.assertEqual(res['wakes'], {'total': 24, 'hard': 3, 'soft_idle': 16, 'soft_timeout': 2, 'unclassified': 3,
                                        'hard_reasons': {'guard': 1, 'event': 2, 'watcher stopped': 0},
                                        'unclassified_reasons': {'compaction in turn': 1, 'no output': 1,
                                                                 'turn not ended': 1}})
        self.assertEqual(res['soft']['classified'], 18)
        self.assertEqual(res['soft']['needed'], 6)
        self.assertEqual(res['soft']['not_needed'], 12)
        self.assertEqual(res['soft']['criteria'], {'message': 1, 'session-control': 1, 'git-write': 1, 'deploy': 1,
                                                   'panel': 1, 'question': 1})

    def test_hours_observed(self):
        res = self.run_analysis()
        a, b = res['supervisors']
        self.assertAlmostEqual(a['hours'], (self.a_last - self.a_first) / 3600, delta=0.01)
        self.assertAlmostEqual(b['hours'], (self.b_last - self.b_first) / 3600, delta=0.01)
        self.assertAlmostEqual(res['hours_total'], a['hours'] + b['hours'], delta=0.01)

    def test_cost_flow_and_kinds_raw(self):
        res = self.run_analysis()
        flow = res['cost']['flow']
        # 91 units in the first transcript and 16 in the second; the sidechain (900) and the other files are ignored
        self.assertEqual(flow['fresh'], 107)
        self.assertEqual(flow['cache_read'], 1070)
        self.assertEqual(flow['cache_write'], 10700)
        self.assertEqual(flow['output'], 107000)
        self.assertEqual(flow['raw'], 107 * 1111)
        by = res['cost']['by_kind']
        self.assertEqual(by['hard']['fresh'], 7 + 8 + 9)
        self.assertEqual(by['unclassified']['fresh'], 10 + 11 + 4)
        self.assertEqual(by['soft_timeout']['fresh'], 6 + 2)   # the second one also holds the launch of another task
        self.assertEqual(by['soft_idle']['fresh'], 5 + 9 + 12 + 4 + 2 + 3 + (2 + 1 + 1 + 3 + 1 + 2 + 1))
        self.assertEqual(by['other']['fresh'], 1 + 1 + 1 + 1)
        total = sum(by[k]['fresh'] for k in by)
        self.assertEqual(total, flow['fresh'])

    # ------------------------------------------------------------------------------------------------- rule B

    def test_rule_b_known_saving_and_misses(self):
        res = self.run_analysis()
        rb = res['rule_b']
        # A sleeps W1 W2 W3 W8 W9 W10 W11 W13 W14 (W12 is the fifth in a row); B sleeps Bw1 2 3 5 6 7 8 (Bw4 is the
        # 2 h 10 min wake)
        self.assertEqual(rb['slept'], 9 + 7)
        self.assertEqual(rb['slept_soft_idle'], 8 + 6)
        self.assertEqual(rb['slept_soft_timeout'], 1 + 1)
        self.assertEqual(rb['saving']['fresh'], 40 + 10)
        self.assertEqual(rb['saving']['raw'], 50 * 1111)
        self.assertAlmostEqual(rb['saving_share_pct'], 100 * 50 / 107, places=2)
        # needed and slept: W2, W13 (A); Bw1, Bw5, Bw6 (B). Bw4 (git push) is needed but was not slept.
        self.assertEqual(rb['needed_slept'], 5)
        self.assertEqual(rb['needed_slept_criteria'], {'message': 1, 'session-control': 1, 'git-write': 0, 'deploy': 1,
                                                       'panel': 1, 'question': 1})
        self.assertTrue(rb['upper_bound'])

    def test_simulate_rule_b_bounds_directly(self):
        def turn(ts, cls='soft_idle', kind='wake'):
            return {'kind': kind, 'ts': ts, 'class': cls}
        five = [turn(i * 60) for i in range(5)]
        self.assertEqual(simulate.simulate_rule_b(five), [0, 1, 2, 3])
        # an awake turn in the middle restarts the count
        mixed = [turn(0), turn(60), turn(120, 'hard'), turn(180), turn(240), turn(300), turn(360), turn(420)]
        self.assertEqual(simulate.simulate_rule_b(mixed), [0, 1, 3, 4, 5, 6])
        # exactly two hours since the first sleep is not "less than"
        edge = [turn(0), turn(7199), turn(7200 + 0)]
        self.assertEqual(simulate.simulate_rule_b(edge), [0, 1])
        # a non-wake turn between two soft wakes ends the stretch; the preamble does not
        pre = [turn(None, None, 'preamble'), turn(0), turn(10, None, 'other'), turn(20), turn(30)]
        self.assertEqual(simulate.simulate_rule_b(pre), [1, 3, 4])

    # ------------------------------------------------------------------------------ weights and the warning

    def test_raw_report_warns_and_weighted_does_not(self):
        raw = simulate.render_markdown(self.run_analysis())
        self.assertTrue(raw.startswith('> WARNING: weights not set'))
        self.assertIn('weights not set', raw)
        self.assertIn('UPPER BOUNDS', raw)
        res = self.run_analysis(weights=WEIGHTS)
        text = simulate.render_markdown(res)
        self.assertNotIn('WARNING', text)
        self.assertNotIn('weights not set', text)
        flow = res['cost']['flow']
        self.assertAlmostEqual(flow['weighted'], 107 * UNIT_WEIGHTED)
        self.assertAlmostEqual(res['cost']['by_kind']['hard']['weighted'], 24 * UNIT_WEIGHTED)
        self.assertAlmostEqual(res['rule_b']['saving']['weighted'], 50 * UNIT_WEIGHTED)
        self.assertEqual(res['basis'], 'weighted')
        self.assertEqual(res['weights'], WEIGHTS)

    def test_no_weights_json_values_are_none(self):
        res = self.run_analysis()
        self.assertIsNone(res['cost']['flow']['weighted'])
        self.assertEqual(res['basis'], 'raw')

    # ------------------------------------------------------------------------------------------------ decision

    def test_decision_of_the_seeded_run(self):
        res = self.run_analysis()
        self.assertEqual(res['decision']['row'], 1)  # 18 classified soft wakes
        self.assertEqual(res['decision']['verdict'], 'open: too little data')

    def test_decision_rows(self):
        d = simulate.decide
        # row 1: fewer than 100 classified soft wakes (the spec's 40 wakes), or more than one in ten unclassified
        self.assertEqual(d(40, 0, 0, 12, 100)['row'], 1)
        self.assertEqual(d(100, 12, 0, 12, 100)['row'], 1)     # 12 of 112 > 10 %
        self.assertEqual(d(100, 11, 1, 12, 100)['row'], 3)     # 11 of 111 is not more than 10 %
        self.assertEqual(d(99, 0, 0, 12, 100)['row'], 1)
        # row 2: the rule saves under 5 % of the flow, whatever the needed rate
        self.assertEqual(d(300, 0, 0, 2, 100)['row'], 2)
        self.assertEqual(d(300, 0, 40, 2, 100)['row'], 2)
        self.assertEqual(d(300, 0, 40, 4.99, 100)['row'], 2)
        # row 3: at most one needed in 100 classified soft wakes
        self.assertEqual(d(300, 0, 1, 12, 100)['row'], 3)
        self.assertEqual(d(300, 0, 3, 5, 100)['row'], 3)
        self.assertEqual(d(300, 0, 4, 12, 100)['row'], 4)
        # row 4: the saving is worth it and the rule is unsafe
        self.assertEqual(d(100, 0, 9, 12, 100)['row'], 4)
        self.assertEqual(d(100, 0, 9, 12, 100)['verdict'], 'open: a model must be tested')
        self.assertEqual([d(40, 0, 0, 12, 100)['verdict'], d(300, 0, 0, 2, 100)['verdict'],
                          d(300, 0, 1, 12, 100)['verdict']],
                         ['open: too little data', 'no-go: too small', 'no-go: the rule is enough'])
        # an empty flow cannot show a saving
        self.assertEqual(d(300, 0, 0, 0, 0)['row'], 2)

    # ------------------------------------------------------------------------------------- window and privacy

    def test_since_drops_the_arming_before_the_window(self):
        # starting just after the first arming, the first wake cannot be recognised (its arming is out of the window)
        since = simulate._iso(BASE + 300)
        res = self.run_analysis(since=since)
        a = res['supervisors'][0]
        self.assertEqual(a['wakes'], 15)
        self.assertEqual(res['window']['since'], since[:19])
        self.assertEqual(len(res['supervisors']), 2)

    def test_until_and_a_window_with_no_wakes(self):
        res = self.run_analysis(until=simulate._iso(BASE + 60))
        self.assertEqual(res['wakes']['total'], 0)
        self.assertEqual(res['decision']['row'], 1)
        text = simulate.render_markdown(res)
        self.assertIn('Decision, row 1', text)

    def test_old_files_are_skipped_by_mtime(self):
        res = self.run_analysis(since='2999-01-01')
        self.assertEqual(res['supervisors'], [])

    def test_report_and_json_leak_nothing(self):
        out = os.path.join(self.tmp, 'figures.json')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = simulate.main(['--projects-dir', self.projects, '--journal-dir', os.path.join(self.tmp, 'no-journal'),
                                  '--weights', '1,0.1,1.25,5', '--json', out])
        self.assertEqual(code, 0)
        report = buf.getvalue()
        with open(out) as fh:
            raw_json = fh.read()
        figures = json.loads(raw_json)
        self.assertEqual(figures['wakes']['total'], 24)
        for text in (report, raw_json):
            for secret in (self.tmp, 'slug-one', 'slug-two', 'sess-invented', 'tsk-', 'toolu_', 'owner-demo', 'sess-a',
                           'notes-one', 'supervisor-lock', 'make deploy', 'panel-de-decision', 'git push'):
                self.assertNotIn(secret, text)
        self.assertIn('S1', report)
        self.assertIn('S2', report)
        self.assertIn('Decision, row 1', report)

    def test_calibration_lists_tool_names_only(self):
        res = self.run_analysis()
        tools = dict(res['tools_in_not_needed_soft_turns'])
        self.assertTrue(tools['Bash'] > 0)
        self.assertLessEqual(len(res['tools_in_not_needed_soft_turns']), 10)
        self.assertNotIn('SendMessage', tools)   # the only SendMessage in a soft turn sits in a needed wake
        self.assertNotIn('mcp__ccd_session__start_session', tools)

    def test_main_rejects_bad_weights(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            simulate.main(['--projects-dir', self.projects, '--weights', '1,2,3'])


class DetectionCase(unittest.TestCase):
    """The closed list of needed criteria, on single commands and tool names."""

    def crit(self, command):
        return simulate.bash_criteria(command)

    def test_git_writes(self):
        for cmd in ('git commit -m "x"', 'git -C ~/work push origin topic', 'cd ~/work && git merge feature',
                    'git rebase main', 'git cherry-pick abc', 'git revert abc', 'git tag v1', 'gh pr create --fill',
                    'gh pr merge 12', 'git -c user.x=y commit --amend'):
            self.assertEqual(self.crit(cmd), {'git-write'}, cmd)
        for cmd in ('git status', 'git log --oneline', 'git diff', 'git merge-base a b', 'git tag', 'git tag -l "v*"',
                    'gh pr view 12', 'gh pr list', 'echo git push', 'grep "git commit" notes.md', 'git branch -a'):
            self.assertEqual(self.crit(cmd), set(), cmd)

    def test_commit_message_in_a_heredoc_is_not_a_second_command(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nfix: it's done; git push later && deploy\nEOF\n)\""
        self.assertEqual(self.crit(cmd), {'git-write'})

    def test_deploys(self):
        for cmd in ('make deploy', './deploy.sh', 'bash scripts/deploy.sh --prod', 'flock -w 3600 ~/state/deploy-vps.lock '
                    'make deploy', 'DEPLOY_ENV=x make deploy-prod', 'npm run deploy', 'make test && make deploy'):
            self.assertEqual(self.crit(cmd), {'deploy'}, cmd)
        for cmd in ('grep -n deploy Makefile', 'cat scripts/deploy.sh', 'sed -n 1,20p scripts/deploy.sh',
                    'ls ~/state/deploy-vps.lock', 'rg "make deploy" docs', 'echo deploy', 'git log deploy',
                    'python3 -m pytest tests/test_deploy.py', 'supervisor-lock beat --state deploying',
                    'cd deploy && ls'):
            self.assertEqual(self.crit(cmd), set(), cmd)

    def test_questions(self):
        self.assertEqual(self.crit('~/.claude/scripts/ask-queue add --project . --question "x" --default "No"'),
                         {'question'})
        self.assertEqual(self.crit('ask-queue list'), set())
        self.assertEqual(self.crit('grep -n "ask-queue add" notes.md'), set())

    def test_tools(self):
        c = simulate.tool_criteria
        for name in ('SendMessage', 'CrossSessionMessage', 'mcp__ccd_session_mgmt__send_message'):
            self.assertEqual(c(name, {}), {'message'}, name)
        for name in ('mcp__ccd_session__start_session', 'mcp__ccd_session_mgmt__stop_session',
                     'mcp__ccd_session_mgmt__archive_session'):
            self.assertEqual(c(name, {}), {'session-control'}, name)
        self.assertEqual(c('Skill', {'skill': 'panel-de-decision'}), {'panel'})
        self.assertEqual(c('Skill', {'skill': 'cierra-sesion'}), set())
        self.assertEqual(c('AskUserQuestion', {}), {'question'})
        for name in ('Read', 'Grep', 'Edit', 'mcp__ccd_session_mgmt__get_session', 'mcp__ccd_session_mgmt__list_sessions'):
            self.assertEqual(c(name, {'file_path': 'x'}), set(), name)

    def test_event_lines(self):
        text = ('     1→STATUS a idle->busy\nsome other text\nSTATUS b idle->busy\n[exited with code 0]\n'
                'NEWS is not an event\nTIMEOUT 600s\nREGISTRY_BIG f 9 (x)')
        self.assertEqual(simulate.event_lines(text), ['STATUS a idle->busy', 'STATUS b idle->busy', 'TIMEOUT 600s',
                                                      'REGISTRY_BIG f 9 (x)'])

    def test_classify(self):
        def turn(events, **kw):
            base = {'guard': False, 'events': events, 'compacted': False, 'ended': True, 'criteria': set(),
                    'assistant_messages': 1}
            base.update(kw)
            return base
        c = simulate.classify_wake
        self.assertEqual(c(turn(['STATUS a idle->busy']))['kind'], 'soft_idle')
        self.assertEqual(c(turn(['STATUS a idle->busy', 'STATUS b idle->busy', 'REGISTRY_BIG f 1 (x)']))['kind'], 'soft_idle')
        self.assertEqual(c(turn(['TIMEOUT 600s', 'REGISTRY_BIG f 1 (x)']))['kind'], 'soft_timeout')
        self.assertEqual(c(turn(['TIMEOUT 600s', 'NEW x']))['kind'], 'hard')
        self.assertEqual(c(turn(simulate.event_lines('TIMEOUT 600s\nASKDUE 2 questions')))['kind'], 'hard')
        self.assertEqual(c(turn(['STATUS a busy->idle']))['kind'], 'hard')
        self.assertEqual(c(turn(['TURN a 3->4']))['kind'], 'hard')
        self.assertEqual(c(turn(['ALLIDLE 3600s']))['kind'], 'hard')
        self.assertEqual(c(turn(['STATUS a idle->busy'], guard=True))['kind'], 'hard')
        self.assertEqual(c(turn([], guard=True))['kind'], 'hard')
        self.assertEqual(c(turn([]))['reason'], 'no output')
        # a watcher whose notification status is not `completed` and printed nothing was stopped: hard, not unclassified
        stopped = c(turn([], status='stopped'))
        self.assertEqual((stopped['kind'], stopped['reason']), ('hard', 'watcher stopped'))
        for status in ('completed', None):
            plain = c(turn([], status=status))
            self.assertEqual((plain['kind'], plain['reason']), ('unclassified', 'no output'))
        self.assertEqual(c(turn(['STATUS a idle->busy'], status='stopped'))['kind'], 'soft_idle')
        guarded = c(turn([], guard=True, status='stopped'))
        self.assertEqual((guarded['kind'], guarded['reason']), ('hard', 'guard'))
        self.assertEqual(c(turn(['STATUS a idle->busy'], ended=False))['reason'], 'turn not ended')
        self.assertEqual(c(turn(['STATUS a idle->busy'], compacted=True))['reason'], 'compaction in turn')
        # a hard wake needs no end of turn
        self.assertEqual(c(turn(['CRASH a 0->1'], ended=False))['kind'], 'hard')
        done = c(turn(['TIMEOUT 5s'], criteria={'deploy'}))
        self.assertEqual((done['needed'], done['criteria']), (True, ['deploy']))

    def test_classify_no_turn_applies_to_soft_wakes_only(self):
        def turn(events, **kw):
            base = {'guard': False, 'events': events, 'compacted': False, 'ended': True, 'criteria': set(),
                    'assistant_messages': 0}
            base.update(kw)
            return base
        c = simulate.classify_wake

        def pair(result):
            return result['kind'], result['reason']
        # soft wakes with no message of their own
        self.assertEqual(pair(c(turn(['STATUS a idle->busy']))), ('unclassified', 'no turn'))
        self.assertEqual(pair(c(turn(['TIMEOUT 600s', 'REGISTRY_BIG f 1 (x)']))), ('unclassified', 'no turn'))
        self.assertIsNone(c(turn(['STATUS a idle->busy']))['needed'])
        # the rule comes before the compaction check; an unfinished turn comes first (it may still be answered)
        self.assertEqual(c(turn(['STATUS a idle->busy'], compacted=True))['reason'], 'no turn')
        self.assertEqual(c(turn(['STATUS a idle->busy'], ended=False))['reason'], 'turn not ended')
        # with a message of its own the same wake is classified
        self.assertEqual(c(turn(['STATUS a idle->busy'], assistant_messages=1))['kind'], 'soft_idle')
        # hard wakes keep their reasons whether or not they started a turn
        self.assertEqual(pair(c(turn(['NEW b']))), ('hard', 'event'))
        self.assertEqual(pair(c(turn(['TIMEOUT 600s', 'NEW b']))), ('hard', 'event'))
        self.assertEqual(pair(c(turn(['TIMEOUT 600s'], guard=True))), ('hard', 'guard'))
        self.assertEqual(pair(c(turn([], guard=True))), ('hard', 'guard'))
        # no event at all: no output (or watcher stopped) as before, never no turn
        self.assertEqual(pair(c(turn([]))), ('unclassified', 'no output'))
        self.assertEqual(pair(c(turn([], status='stopped'))), ('hard', 'watcher stopped'))
        self.assertEqual(pair(c(turn(['REGISTRY_BIG f 1 (x)']))), ('unclassified', 'no output'))

    def test_stopped_watcher_is_hard_and_not_slept(self):
        tmp = tempfile.mkdtemp(prefix='simulate-test-')
        try:
            b = Builder(os.path.join(tmp, 'p', 's.jsonl'), tmp, BASE)
            b.human('go')
            arm = b.arm()
            b.assistant([arm], 1)
            arm = b.wake(arm, 'tsk-1', ONE_IDLE)
            arm = b.wake(arm, 'tsk-2', None, status='stopped')   # stopped: no output is read, no output file exists
            arm = b.wake(arm, 'tsk-3', ONE_IDLE)
            b.human('next real message')
            b.write()
            parsed = simulate.parse_transcript(b.path)
            self.assertEqual([t['status'] for t in parsed['turns'] if t['kind'] == 'wake'],
                             ['completed', 'stopped', 'completed'])
            res = simulate.summarize([parsed], None)
            self.assertEqual((res['wakes']['hard'], res['wakes']['soft_idle'], res['wakes']['unclassified']), (1, 2, 0))
            self.assertEqual(res['wakes']['hard_reasons'], {'guard': 0, 'event': 0, 'watcher stopped': 1})
            self.assertEqual(res['wakes']['unclassified_reasons'], {})
            wakes = [t for t in parsed['turns'] if t['kind'] == 'wake']
            self.assertEqual([t['class'] for t in wakes], ['soft_idle', 'hard', 'soft_idle'])
            self.assertEqual(res['rule_b']['slept'], 2)   # the two soft wakes; the stopped one is never slept
            self.assertIn('Hard, by reason: guard 0, event 0, watcher stopped 1.', simulate.render_markdown(res))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_meta_user_record_does_not_end_a_turn(self):
        tmp = tempfile.mkdtemp(prefix='simulate-test-')
        try:
            b = Builder(os.path.join(tmp, 'p', 's.jsonl'), tmp, BASE)
            b.human('go')
            arm = b.arm()
            b.assistant([arm], 1)
            b.notification(arm, 'tsk-m')
            read = b.tool('Bash', command=f'cat {os.path.join(tmp, "tsk-m.output")}')
            b.assistant([read], 1)
            b.result(read, ONE_IDLE)
            skill = b.tool('Skill', skill='panel-de-decision')
            b.assistant([skill], 1)
            b.human('Base directory for this skill: x', meta=True)   # injected by the harness inside the turn
            b.assistant([b.tool('SendMessage', to='x')], 1)
            b.human('next real message')
            b.write()
            parsed = simulate.parse_transcript(b.path)
            wake = [t for t in parsed['turns'] if t['kind'] == 'wake'][0]
            self.assertTrue(wake['ended'])
            self.assertEqual(wake['criteria'], {'panel', 'message'})
            self.assertEqual(parsed['armings'], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


SLACK = simulate.JOURNAL_SLACK_S


def record(events, started, ended, owner='local_sup'):
    return {'events': events, 'started': started, 'ended': ended, 'owner': owner}


def write_journal(folder, records, name='project-key.jsonl'):
    """Append journal records (epoch times in `started`/`ended`) to one journal file; returns the folder."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), 'a', encoding='utf-8') as fh:
        for r in records:
            fh.write(json.dumps({'ended': iso(r['ended']), 'events': r['events'], 'owner': r['owner'],
                                 'started': iso(r['started'])}, sort_keys=True) + '\n')
    return folder


class JournalCase(unittest.TestCase):
    """The durable watcher journal as a third source of a wake's events, and the "no turn" rule."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='simulate-test-')
        self.tasks = os.path.join(self.tmp, 'tasks')
        os.makedirs(self.tasks)
        self.counter = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers
    def builder(self, guard=False, name='sess'):
        b = Builder(os.path.join(self.tmp, 'projects', 'slug', name + '.jsonl'), self.tasks, BASE)
        b.owner = 'local_sup'
        b.human('go')
        arm = b.arm(guard)
        b.assistant([arm], 1)
        return b, arm

    def send(self):
        self.counter += 1
        return {'type': 'tool_use', 'id': f'toolu_send{self.counter}', 'name': 'SendMessage', 'input': {'to': 'y'}}

    def task(self):
        self.counter += 1
        return f'tsk-{self.counter}'

    def one_wake(self, output=None, guard=False, after=(), bare=False, **kw):
        """One supervisor with one wake. Returns (arming time, notification time, transcript path)."""
        b, arm = self.builder(guard)
        arm_ts = b.t
        b.at(BASE + 600)
        notified = b.t + 1
        if bare:
            b.bare_wake(arm, self.task(), **kw)
        else:
            b.wake(arm, self.task(), output, after=after, **kw)
            b.human('next real message')
        b.write()
        return arm_ts, notified, b.path

    def journal(self, records=()):
        folder = tempfile.mkdtemp(dir=self.tmp, prefix='journal-')
        if records:
            write_journal(folder, records)
        return simulate.load_journal(folder)

    def wakes(self, path, records=()):
        """[(turn, classification)] of the wakes of a transcript parsed with a journal made of `records`."""
        parsed = simulate.parse_transcript(path, journal=self.journal(records))
        return [(t, simulate.classify_wake(t)) for t in parsed['turns'] if t['kind'] == 'wake']

    def classify(self, path, records=()):
        found = self.wakes(path, records)
        self.assertEqual(len(found), 1)
        return found[0]

    @staticmethod
    def shape(info):
        return info['kind'], info['reason'], info['needed']

    # -- (a) the journal is read
    def test_journal_gives_the_events_when_nothing_else_does(self):
        arm_ts, notified, path = self.one_wake(None)
        turn, info = self.classify(path, [record(['TIMEOUT 600s'], arm_ts + 2, notified - 2)])
        self.assertEqual(self.shape(info), ('soft_timeout', None, False))
        self.assertEqual(turn['events_source'], 'journal')
        self.assertEqual(turn['events'], ['TIMEOUT 600s'])
        # the turn decides whether it was needed
        arm_ts, notified, path = self.one_wake(None, after=[self.send()])
        turn, info = self.classify(path, [record(['TIMEOUT 600s'], arm_ts + 2, notified - 2)])
        self.assertEqual(self.shape(info), ('soft_timeout', None, True))
        self.assertEqual(info['criteria'], ['message'])

    def test_a_record_far_before_the_notification_still_matches(self):
        # the notification can arrive long after the watcher exited: never match on "ended close to the notification"
        arm_ts, notified, path = self.one_wake(None)
        turn, info = self.classify(path, [record(['TIMEOUT 600s'], arm_ts + 2, notified - 500)])
        self.assertEqual((info['kind'], turn['events_source']), ('soft_timeout', 'journal'))

    def test_the_slack_is_inclusive(self):
        arm_ts, notified, path = self.one_wake(None)
        self.assertEqual(SLACK, 5.0)
        turn, info = self.classify(path, [record(['TIMEOUT 600s'], arm_ts - SLACK, notified + SLACK)])
        self.assertEqual((info['kind'], turn['events_source']), ('soft_timeout', 'journal'))

    # -- (b) the class does not depend on the source
    def test_same_class_from_the_transcript_and_from_the_journal(self):
        cases = [
            (['STATUS local_a idle->busy', 'REGISTRY_BIG /x 30000 (advice)'], 'soft_idle'),
            (['STATUS local_a idle->busy', 'STATUS local_c idle->busy'], 'soft_idle'),
            (['TIMEOUT 600s'], 'soft_timeout'),
            (['NEW local_b'], 'hard'),
            (['TIMEOUT 600s', 'NEW local_b'], 'hard'),
        ]
        for events, kind in cases:
            for needed_after in (False, True):
                with self.subTest(events=events, needed=needed_after):
                    after = [self.send()] if needed_after else ()
                    _a, _n, from_transcript = self.one_wake('\n'.join(events) + '\n[exited with code 0]', after=after)
                    t_turn, t_info = self.classify(from_transcript)
                    arm_ts, notified, from_nothing = self.one_wake(None, after=after)
                    j_turn, j_info = self.classify(from_nothing, [record(events, arm_ts + 2, notified - 2)])
                    self.assertEqual((t_turn['events_source'], j_turn['events_source']), ('transcript', 'journal'))
                    self.assertEqual(self.shape(t_info), self.shape(j_info))
                    self.assertEqual(t_info['kind'], kind)
                    self.assertEqual(t_info['criteria'], j_info['criteria'])
        # a record that only carries the advisory line leaves the wake without events
        arm_ts, notified, path = self.one_wake(None)
        _turn, info = self.classify(path, [record(['REGISTRY_BIG /x 30000 (advice)'], arm_ts + 2, notified - 2)])
        self.assertEqual(self.shape(info), ('unclassified', 'no output', None))

    # -- (c) the transcript wins
    def test_transcript_and_output_file_win_over_the_journal(self):
        arm_ts, notified, path = self.one_wake('STATUS local_a idle->busy')
        other = [record(['NEW local_b'], arm_ts + 2, notified - 2)]
        turn, info = self.classify(path, other)
        self.assertEqual((info['kind'], turn['events_source']), ('soft_idle', 'transcript'))
        self.assertEqual(turn['events'], ['STATUS local_a idle->busy'])
        arm_ts, notified, path = self.one_wake(None, write_output_file='TIMEOUT 600s\n')
        turn, info = self.classify(path, [record(['NEW local_b'], arm_ts + 2, notified - 2)])
        self.assertEqual((info['kind'], turn['events_source']), ('soft_timeout', 'output file'))

    # -- (d) no match: unchanged
    def test_no_match_leaves_the_wake_without_output(self):
        arm_ts, notified, path = self.one_wake(None)
        ev = ['TIMEOUT 600s']
        cases = {
            'no record': [],
            'record of another owner': [record(ev, arm_ts + 2, notified - 2, owner='local_other')],
            'started before the arming': [record(ev, arm_ts - SLACK - 1, notified - 2)],
            'ended after the notification': [record(ev, arm_ts + 2, notified + SLACK + 1)],
            'two records of the owner': [record(ev, arm_ts + 2, arm_ts + 100), record(ev, arm_ts + 100, notified - 2)],
            'two identical records': [record(ev, arm_ts + 2, notified - 2)] * 2,
        }
        for name, records in cases.items():
            with self.subTest(name):
                turn, info = self.classify(path, records)
                self.assertEqual(self.shape(info), ('unclassified', 'no output', None))
                self.assertIsNone(turn['events_source'])
                self.assertEqual(turn['events'], [])

    def test_each_wake_gets_its_own_record(self):
        b, arm = self.builder()
        t0 = b.t
        b.at(t0 + 600)
        n1 = b.t + 1
        arm = b.wake(arm, self.task(), None)
        rearmed = n1 + 1            # the re-arm record of the first wake
        b.at(t0 + 1200)
        n2 = b.t + 1
        b.wake(arm, self.task(), None)
        b.human('next real message')
        b.write()
        records = [record(['TIMEOUT 600s'], t0 + 2, n1 - 100),
                   record(['STATUS local_a idle->busy'], rearmed + 2, n2 - 100)]
        found = self.wakes(b.path, records)
        self.assertEqual([i['kind'] for _t, i in found], ['soft_timeout', 'soft_idle'])
        self.assertEqual([t['events_source'] for t, _i in found], ['journal', 'journal'])

    def test_unknown_owner_or_arming_time_gives_no_events(self):
        j = {'local_sup': [{'started': 10.0, 'ended': 20.0, 'events': ['TIMEOUT 600s']}]}
        self.assertEqual(simulate._journal_events(j, 'local_sup', 10.0, 21.0), ['TIMEOUT 600s'])
        self.assertEqual(simulate._journal_events(j, None, 10.0, 21.0), [])
        self.assertEqual(simulate._journal_events(j, 'local_sup', None, 21.0), [])
        self.assertEqual(simulate._journal_events(j, 'local_sup', 10.0, None), [])
        self.assertEqual(simulate._journal_events(None, 'local_sup', 10.0, 21.0), [])
        self.assertEqual(simulate._journal_events({}, 'local_sup', 10.0, 21.0), [])

    def test_owner_of_an_arming_command(self):
        def owner(command):
            return simulate._arm_owner({'command': command})
        self.assertEqual(owner('supervisor-lock wait --dir d --owner local_x --timeout 9'), 'local_x')
        self.assertEqual(owner('supervisor-lock wait --owner=local_x --timeout 9'), 'local_x')
        self.assertEqual(owner('supervisor-lock wait --owner "local_x" --guard'), 'local_x')
        self.assertEqual(owner("supervisor-lock wait --owner 'local_x'"), 'local_x')
        self.assertIsNone(owner('supervisor-lock wait --owner "$OWNER"'))
        self.assertIsNone(owner('supervisor-lock wait --timeout 9'))

    # -- (e) a wake older than the file
    def test_a_wake_older_than_the_journal_stays_unclassified(self):
        arm_ts, notified, path = self.one_wake(None)
        later = [record(['TIMEOUT 600s'], notified + 1000, notified + 1100)]
        for records in ([], later):
            turn, info = self.classify(path, records)
            self.assertEqual(self.shape(info), ('unclassified', 'no output', None))
        folder = self.journal_dir_with_empty_file()
        parsed = simulate.parse_transcript(path, journal=simulate.load_journal(folder))
        self.assertEqual([simulate.classify_wake(t)['reason'] for t in parsed['turns'] if t['kind'] == 'wake'],
                         ['no output'])

    def journal_dir_with_empty_file(self):
        folder = tempfile.mkdtemp(dir=self.tmp, prefix='journal-')
        open(os.path.join(folder, 'old-project.jsonl'), 'w').close()
        return folder

    # -- (f) a soft wake that started no turn
    def test_a_soft_wake_without_a_turn_of_its_own_is_unclassified(self):
        # from the temporary output file (a transcript read needs a message of its own, so it cannot be bare)
        _a, _n, path = self.one_wake(bare=True, write_output_file='STATUS local_a idle->busy\n')
        turn, info = self.classify(path)
        self.assertEqual((turn['events_source'], turn['assistant_messages']), ('output file', 0))
        self.assertEqual(self.shape(info), ('unclassified', 'no turn', None))
        # from the journal
        arm_ts, notified, path = self.one_wake(bare=True)
        for events in (['TIMEOUT 600s'], ['STATUS local_a idle->busy', 'REGISTRY_BIG /x 30000 (advice)']):
            turn, info = self.classify(path, [record(events, arm_ts + 2, notified - 2)])
            self.assertEqual((turn['events_source'], turn['assistant_messages']), ('journal', 0))
            self.assertEqual(self.shape(info), ('unclassified', 'no turn', None))
            self.assertEqual(info['criteria'], [])

    def test_a_wake_with_a_read_of_its_own_is_not_no_turn(self):
        _a, _n, path = self.one_wake('STATUS local_a idle->busy')
        turn, info = self.classify(path)
        self.assertGreaterEqual(turn['assistant_messages'], 1)
        self.assertEqual(info['kind'], 'soft_idle')

    def test_hard_wakes_keep_their_reasons_without_a_turn(self):
        arm_ts, notified, path = self.one_wake(bare=True)
        turn, info = self.classify(path, [record(['NEW local_b'], arm_ts + 2, notified - 2)])
        self.assertEqual((turn['assistant_messages'], info['kind'], info['reason']), (0, 'hard', 'event'))
        _a, _n, path = self.one_wake(bare=True, write_output_file='TIMEOUT 600s\nNEW local_b\n')
        turn, info = self.classify(path)
        self.assertEqual((info['kind'], info['reason']), ('hard', 'event'))
        # a guard wake stays hard whatever it holds
        for output in ('TIMEOUT 600s\n', None):
            _a, _n, path = self.one_wake(guard=True, bare=True, write_output_file=output)
            turn, info = self.classify(path)
            self.assertEqual((turn['assistant_messages'], info['kind'], info['reason']), (0, 'hard', 'guard'))

    def test_no_events_and_no_turn_keeps_its_own_reason(self):
        _a, _n, path = self.one_wake(bare=True)
        self.assertEqual(self.shape(self.classify(path)[1]), ('unclassified', 'no output', None))
        _a, _n, path = self.one_wake(bare=True, status='stopped')
        info = self.classify(path)[1]
        self.assertEqual((info['kind'], info['reason']), ('hard', 'watcher stopped'))

    # -- (g) rule B and the counts
    def test_no_turn_wake_is_unclassified_in_the_counts_and_ends_a_stretch(self):
        b, arm = self.builder()
        send = b.tool('SendMessage', to='local_a')
        t = BASE + 600
        for i in (1, 2, 3):                                  # three soft wakes, the second one needed
            b.at(t + 600 * i)
            arm = b.wake(arm, self.task(), ONE_IDLE, after=[send] if i == 2 else ())
        b.at(t + 600 * 4)
        b.bare_wake(arm, self.task(), write_output_file=ONE_IDLE, then_human=False)   # soft, no turn of its own
        for i in (5, 6, 7):                                  # three more
            b.at(t + 600 * i)
            arm = b.wake(arm, self.task(), ONE_IDLE)
        b.human('thanks')
        b.write()
        parsed = simulate.parse_transcript(b.path)
        res = simulate.summarize([parsed], None)
        self.assertEqual(res['wakes']['total'], 7)
        self.assertEqual((res['wakes']['soft_idle'], res['wakes']['unclassified']), (6, 1))
        self.assertEqual(res['wakes']['unclassified_reasons'], {'no turn': 1})
        self.assertEqual((res['soft']['classified'], res['soft']['needed'], res['soft']['not_needed']), (6, 1, 5))
        self.assertAlmostEqual(res['rates']['unclassified_share_pct'], round(100 / 7, 2))
        # all six classified soft wakes are slept: the unclassified wake ended the first stretch (a run of six would
        # have been cut at four); the one in the middle is never slept
        self.assertEqual(res['rule_b']['slept'], 6)
        self.assertEqual(res['rule_b']['needed_slept'], 1)
        self.assertEqual(res['supervisors'][0]['unclassified'], 1)
        self.assertEqual(res['decision']['row'], 1)
        text = simulate.render_markdown(res)
        self.assertIn('Unclassified, by reason: no turn 1.', text)

    # -- (h) nothing from the journal is printed
    def test_report_and_json_hold_only_the_count_of_journal_wakes(self):
        arm_ts, notified, _path = self.one_wake(None)       # written under <tmp>/projects/slug
        marker = 'ASKDUE 1 q-secret-marker «text»'
        folder = write_journal(os.path.join(self.tmp, 'journal-seeded'), [record([marker], arm_ts + 2, notified - 2)])
        out = os.path.join(self.tmp, 'figures.json')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = simulate.main(['--projects-dir', os.path.join(self.tmp, 'projects'), '--journal-dir', folder,
                                  '--json', out])
        self.assertEqual(code, 0)
        report = buf.getvalue()
        with open(out, encoding='utf-8') as fh:
            raw_json = fh.read()
        for text in (report, raw_json):
            for secret in ('q-secret-marker', 'ASKDUE', 'text»', 'local_sup', 'project-key', folder):
                self.assertNotIn(secret, text)
        self.assertIn('Wakes whose events were read from the journal: 1.', report)
        figures = json.loads(raw_json)
        self.assertEqual((figures['wakes_from_journal'], figures['wakes']['hard']), (1, 1))

    def test_analyze_takes_a_directory_a_loaded_journal_or_none(self):
        arm_ts, notified, _path = self.one_wake(None)
        folder = write_journal(os.path.join(self.tmp, 'journal-seeded'),
                               [record(['TIMEOUT 600s'], arm_ts + 2, notified - 2)])
        projects = os.path.join(self.tmp, 'projects')
        by_dir = simulate.analyze(projects, journal=folder)
        by_dict = simulate.analyze(projects, journal=simulate.load_journal(folder))
        without = simulate.analyze(projects)
        self.assertEqual((by_dir['wakes_from_journal'], by_dir['wakes']['soft_timeout']), (1, 1))
        self.assertEqual(by_dir, by_dict)
        self.assertEqual((without['wakes_from_journal'], without['wakes']['unclassified']), (0, 1))
        self.assertEqual(without['wakes']['unclassified_reasons'], {'no output': 1})
        self.assertIn('Wakes whose events were read from the journal: 0.', simulate.render_markdown(without))

    def test_default_journal_folder_follows_the_supervisor_home(self):
        with mock.patch.dict(os.environ, {'SUPERVISOR_LOCK_HOME': '/some/home'}):
            self.assertEqual(simulate.default_journal_dir(), os.path.join('/some/home', 'wakes'))
        with mock.patch.dict(os.environ):
            os.environ.pop('SUPERVISOR_LOCK_HOME', None)
            self.assertEqual(simulate.default_journal_dir(),
                             os.path.join(os.path.expanduser('~/.claude/supervisor'), 'wakes'))

    # -- (i) reading the journal files
    def test_load_journal_skips_bad_lines_and_a_missing_folder_is_empty(self):
        self.assertEqual(simulate.load_journal(os.path.join(self.tmp, 'absent')), {})
        self.assertEqual(simulate.load_journal(None), {})
        folder = os.path.join(self.tmp, 'journal')
        os.makedirs(folder)
        good = {'ended': '2026-11-27T08:10:00.456Z', 'events': ['STATUS local_a idle->busy', 'REGISTRY_BIG /x 3 (y)'],
                'owner': 'local_sup', 'started': '2026-11-27T08:00:00.123Z'}
        lines = [
            json.dumps(good),
            'not json at all',
            '',
            '[1, 2]',
            '"text"',
            json.dumps({k: v for k, v in good.items() if k != 'owner'}),
            json.dumps({**good, 'owner': ''}),
            json.dumps({**good, 'owner': 5}),
            json.dumps({k: v for k, v in good.items() if k != 'ended'}),
            json.dumps({k: v for k, v in good.items() if k != 'started'}),
            json.dumps({**good, 'started': 'yesterday'}),
            json.dumps({**good, 'ended': 1795000000}),
            json.dumps({**good, 'events': 'STATUS local_a idle->busy'}),
            json.dumps({**good, 'events': ['TIMEOUT 600s', 7]}),
            json.dumps({k: v for k, v in good.items() if k != 'events'}),
            json.dumps({**good, 'events': []}),
        ]
        with open(os.path.join(folder, 'one.jsonl'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        with open(os.path.join(folder, 'two.jsonl'), 'w', encoding='utf-8') as fh:
            fh.write(json.dumps({**good, 'owner': 'local_other', 'events': ['NEW local_b']}) + '\n')
        with open(os.path.join(folder, 'ignored.json'), 'w', encoding='utf-8') as fh:   # not a journal file
            fh.write(json.dumps({**good, 'owner': 'local_ignored'}) + '\n')
        loaded = simulate.load_journal(folder)
        self.assertEqual(sorted(loaded), ['local_other', 'local_sup'])
        self.assertEqual(len(loaded['local_sup']), 2)       # the good record and the one with an empty event list
        first = loaded['local_sup'][0]
        self.assertEqual(first['events'], good['events'])
        self.assertAlmostEqual(first['started'], calendar.timegm((2026, 11, 27, 8, 0, 0)) + 0.123, places=3)
        self.assertAlmostEqual(first['ended'], calendar.timegm((2026, 11, 27, 8, 10, 0)) + 0.456, places=3)
        self.assertEqual(loaded['local_sup'][1]['events'], [])
        self.assertEqual(loaded['local_other'][0]['events'], ['NEW local_b'])


if __name__ == '__main__':
    unittest.main()
