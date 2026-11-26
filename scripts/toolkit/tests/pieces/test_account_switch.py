"""Tests for account-switch (transparent switch of the Claude account in the desktop app).

Run:  python3 -m unittest scripts.toolkit.tests.pieces.test_account_switch -v
      (ACCOUNT_SWITCH_SCRIPT=<path> tests another copy, e.g. the installed one, instead of the repo's)

The script runs as a subprocess with ACCOUNT_SWITCH_STATE and ACCOUNT_SWITCH_PROJECTS pointing to temp dirs, so
the real state and transcripts are never touched. `detect` is not run here: it starts `on-switch`, which talks to
the API and may open a terminal.
"""
import datetime
import email.message
import importlib.machinery
import io
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = os.environ.get('ACCOUNT_SWITCH_SCRIPT') or str(REPO_ROOT / 'global/scripts/account-switch')
LIMIT = "You've hit your weekly limit · resets Nov 5, 2am (Europe/Madrid)"


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def answer(text, error=False):
    entry = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if error:
        entry["isApiErrorMessage"] = True
    return entry


class AccountSwitchTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix='account-switch-state-')
        self.projects = tempfile.mkdtemp(prefix='account-switch-projects-')
        self.app = tempfile.mkdtemp(prefix='account-switch-app-')
        os.makedirs(os.path.join(self.projects, 'proj'))
        for d in (self.state, self.projects, self.app):
            self.addCleanup(shutil.rmtree, d, True)
        # the prompts of the app tasks that `arm` writes: on a machine without them installed, arm does nothing
        self.tasks = tempfile.mkdtemp(prefix='account-switch-tasks-')
        self.addCleanup(shutil.rmtree, self.tasks, True)
        for name in ('resume.md', 'revive.md'):
            with open(os.path.join(self.tasks, name), 'w') as fh:
                fh.write('prompt\n')

    def transcript(self, cli_id, entries, age=600):
        path = os.path.join(self.projects, 'proj', f'{cli_id}.jsonl')
        with open(path, 'w') as fh:
            for e in entries:
                fh.write(json.dumps(e, separators=(',', ':')) + '\n')  # compact, like Claude Code writes them
        os.utime(path, (time.time() - age, time.time() - age))

    def event(self, sessions, **extra):
        data = {"id": "t", "at": time.time(), "from": ["a", "b"], "to": ["c", "d"], "claimed_by": None,
                "claimed_at": None, "done": False,
                "sessions": [{"sessionId": f"local_{c}", "cliSessionId": c, "title": c, "cwd": "/tmp", "kind": k}
                             for c, k in sessions]}
        data.update(extra)
        with open(os.path.join(self.state, 'event.json'), 'w') as fh:
            json.dump(data, fh)

    def saved_event(self):
        with open(os.path.join(self.state, 'event.json')) as fh:
            return json.load(fh)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_SESSION_ID'}  # the real session's id
        env.update(ACCOUNT_SWITCH_STATE=self.state, ACCOUNT_SWITCH_PROJECTS=self.projects,
                   ACCOUNT_SWITCH_APP_SESSIONS=self.app,
                   ACCOUNT_SWITCH_CLI_CREDENTIALS=os.path.join(self.state, 'no-credentials.json'),   # no token: no network
                   ACCOUNT_SWITCH_TASK_FILE=os.path.join(self.tasks, 'resume.md'),
                   ACCOUNT_SWITCH_REVIVE_TASK_FILE=os.path.join(self.tasks, 'revive.md'))
        env.update(extra)
        return env

    def hook(self, sid='claimer', mode=None, entrypoint='claude-desktop'):
        payload = {"session_id": sid, "source": "resume"}
        if mode:
            payload["permission_mode"] = mode
        out = subprocess.run([sys.executable, SCRIPT, 'hook'], input=json.dumps(payload), capture_output=True,
                             text=True, env=self.env(CLAUDE_CODE_ENTRYPOINT=entrypoint), timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] if out.stdout.strip() else ""

    def run_rc(self, *args, sid=None):
        """(exit code, stdout) of a subcommand, as the session `sid` (none: no CLAUDE_CODE_SESSION_ID)."""
        extra = {'CLAUDE_CODE_SESSION_ID': sid} if sid else {}
        out = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=self.env(**extra),
                             timeout=60)
        return out.returncode, out.stdout

    @staticmethod
    def delivery(ago=10):
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - ago)) + '.123Z'
        return {"type": "user", "isMeta": True, "timestamp": stamp,
                "origin": {"kind": "peer", "from": "local_x", "body": "[cambio de cuenta] sigue"}}

    def run_cmd(self, *args):
        out = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=self.env(),
                             timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def app_folder(self, account, org, tasks=None):
        folder = os.path.join(self.app, account, org)
        os.makedirs(folder, exist_ok=True)
        if tasks is not None:
            with open(os.path.join(folder, 'scheduled-tasks.json'), 'w') as fh:
                json.dump({"scheduledTasks": tasks, "recordedSkips": {}}, fh)
        return folder

    def tasks_in(self, folder):
        with open(os.path.join(folder, 'scheduled-tasks.json')) as fh:
            return json.load(fh)["scheduledTasks"]

    def test_hands_stopped_sessions_to_one_desktop_session(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.transcript('soft1', [user('x'), answer('Se ha alcanzado tu límite de uso, así que paro aquí.')])
        self.event([('hard1', 'hard'), ('soft1', 'soft')])
        text = self.hook(mode='bypassPermissions')
        self.assertIn('[cambio de cuenta]', text)
        self.assertIn('local_hard1', text)
        self.assertIn('local_soft1', text)
        self.assertIn('Bypass permissions', text)
        self.assertEqual(self.saved_event()['claimed_by'], 'claimer')
        self.assertEqual(self.hook(sid='second', mode='bypassPermissions'), '',
                         'a second session must not get it while the claim is fresh')

    def test_archived_sessions_and_resume_task_runs_are_left_alone(self):
        # 2026-11-14: after an early lift a claim would have woken an archived (finished) session and the cut runs of
        # the resume task itself
        for cli in ('hard1', 'gone1', 'task1'):
            self.transcript(cli, [user('x'), answer(LIMIT, error=True)])
        folder = self.app_folder('c', 'd')
        for cli, extra in (('hard1', {}), ('gone1', {'isArchived': True}), ('task1', {'scheduledTaskId': 'account-switch-resume'})):
            with open(os.path.join(folder, f'local_{cli}.json'), 'w') as fh:
                json.dump(dict({'sessionId': f'local_{cli}', 'cliSessionId': cli, 'title': cli,
                                'lastActivityAt': time.time() * 1000}, **extra), fh)
        self.event([('hard1', 'hard'), ('gone1', 'hard'), ('task1', 'hard')])
        text = self.hook(mode='bypassPermissions')
        self.assertIn('local_hard1', text)
        self.assertNotIn('local_gone1', text)
        self.assertNotIn('local_task1', text)
        loader = importlib.machinery.SourceFileLoader('account_switch_leave_alone', SCRIPT)
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(mod)
        with mock.patch.object(mod, 'APP_SESSIONS', self.app), mock.patch.object(mod, 'PROJECTS', self.projects), \
                mock.patch.object(mod, 'paused_project', lambda cwd: False):
            self.assertEqual([s['sessionId'] for s in mod.stopped_sessions(folder)], ['local_hard1'])

    def test_fresh_event_is_left_to_the_task_unless_the_session_is_in_bypass(self):
        self.transcript('soft1', [user('x'), answer('Se ha alcanzado tu límite de uso, así que paro aquí.')])
        self.event([('soft1', 'soft')])
        self.assertEqual(self.hook(sid='no-mode'), '')
        self.assertEqual(self.hook(sid='auto-one', mode='auto'), '')
        self.assertIsNone(self.saved_event()['claimed_by'])

    def test_brief_claims_even_after_a_hook_and_prints_the_steps(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], claimed_by='someone', claimed_at=time.time())
        text = self.run_cmd('brief', '--wait', '0')
        self.assertIn('local_hard1', text)
        self.assertTrue(self.saved_event()['claimed_by'].startswith('scheduled-task:'))

    def test_brief_offers_the_missing_connectors_even_with_no_session_stopped(self):
        gmail = {"name": "Gmail", "url": "https://gmailmcp.googleapis.com/mcp/v1", "directory": "2701e52f-uuid"}
        self.event([], connectors_missing=[gmail])
        text = self.run_cmd('brief', '--wait', '0')
        self.assertIn('suggest_connectors', text)
        self.assertIn('2701e52f-uuid', text)
        self.assertIn('No conectes nada tú', text)

    def test_resume_steps_carry_the_connectors_step(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        gmail = {"name": "Gmail", "url": "https://gmailmcp.googleapis.com/mcp/v1", "directory": "2701e52f-uuid"}
        self.event([('hard1', 'hard')], connectors_missing=[gmail])
        text = self.hook(mode='bypassPermissions')
        self.assertIn('local_hard1', text)
        self.assertIn('2701e52f-uuid', text)

    def test_steps_carry_the_deadline_of_the_claim(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')])
        text = self.hook(mode='bypassPermissions')
        deadline = time.strftime('%H:%M', time.localtime(self.saved_event()['claimed_at'] + 30 * 60))
        self.assertIn(f'Vale hasta las {deadline}', text)
        self.assertIn('no envíes nada ni preguntes', text)
        self.assertLess(text.index('Vale hasta las'), text.index('\n1. Envía'))

    def test_brief_with_nothing_pending_says_so(self):
        self.assertIn('Nada que hacer', self.run_cmd('brief', '--wait', '0'))

    def test_arm_writes_the_task_everywhere_but_the_active_folder(self):
        other_task = {"id": "otra", "enabled": False, "filePath": "/x", "createdAt": 1}
        active = self.app_folder('acc-a', 'org-1', [other_task])
        same_account_other_org = self.app_folder('acc-a', 'org-2', [])
        old_run = dict(id='account-switch-resume', enabled=False, lastRunAt='2026-11-04T00:00:00Z',
                       filePath='/x', createdAt=1)
        other_account = self.app_folder('acc-b', 'org-3', [other_task, old_run])
        no_file_yet = self.app_folder('acc-c', 'org-4')
        with open(os.path.join(self.state, 'state.json'), 'w') as fh:
            json.dump({"account": "acc-a", "org": "org-1"}, fh)
        self.run_cmd('arm')
        self.assertEqual(self.tasks_in(active), [other_task], 'the active folder belongs to the app')
        for folder in (same_account_other_org, other_account, no_file_yet):
            task = [t for t in self.tasks_in(folder) if t['id'] == 'account-switch-resume']
            self.assertEqual(len(task), 1)
            t = task[0]
            self.assertTrue(t['enabled'])
            self.assertNotIn('lastRunAt', t)
            self.assertLessEqual(t['fireAt'], time.time() * 1000)
            self.assertEqual(t['permissionMode'], 'bypassPermissions')
        self.assertIn(other_task, self.tasks_in(other_account), 'other tasks of that account stay as they were')

    def test_arm_adds_the_revive_task_once_and_keeps_a_paused_one(self):
        # 2026-11-20: «reanimar-supervisoras» must exist in every account, or the next account switch loses it
        paused = dict(id='reanimar-supervisoras', enabled=False, cronExpression='*/15 * * * *', filePath='/x',
                      createdAt=1)
        active = self.app_folder('acc-a', 'org-1', [])
        fresh = self.app_folder('acc-b', 'org-2', [])
        kept = self.app_folder('acc-c', 'org-3', [paused])
        with open(os.path.join(self.state, 'state.json'), 'w') as fh:
            json.dump({"account": "acc-a", "org": "org-1"}, fh)
        self.run_cmd('arm')
        self.run_cmd('arm')
        self.assertEqual(self.tasks_in(active), [])
        revive = [t for t in self.tasks_in(fresh) if t['id'] == 'reanimar-supervisoras']
        self.assertEqual(len(revive), 1)
        self.assertEqual((revive[0]['cronExpression'], revive[0]['enabled'], revive[0]['permissionMode']),
                         ('*/15 * * * *', True, 'bypassPermissions'))
        self.assertTrue(revive[0]['cwd'].endswith('/.claude'))
        self.assertEqual([t for t in self.tasks_in(kept) if t['id'] == 'reanimar-supervisoras'], [paused])

    def test_arm_leaves_the_active_account_alone_when_its_org_is_unknown(self):
        a1 = self.app_folder('acc-a', 'org-1', [])
        a2 = self.app_folder('acc-a', 'org-2', [])
        with open(os.path.join(self.state, 'state.json'), 'w') as fh:
            json.dump({"account": "acc-a", "org": None}, fh)
        self.run_cmd('arm')
        self.assertEqual(self.tasks_in(a1), [])
        self.assertEqual(self.tasks_in(a2), [])

    def test_routine_or_terminal_never_claims(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')])
        self.assertEqual(self.hook(entrypoint='sdk-cli'), '')
        self.assertIsNone(self.saved_event()['claimed_by'])

    def test_a_listed_session_does_not_claim(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')])
        self.assertEqual(self.hook(sid='hard1', mode='bypassPermissions'), '')

    def test_resumed_sessions_drop_out_and_nothing_left_closes_the_event(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True), user('[cambio de cuenta] sigue'),
                                  answer('Sigo con lo mío.')])
        self.event([('hard1', 'hard')])
        self.assertEqual(self.hook(mode='bypassPermissions'), '')
        self.assertTrue(self.saved_event()['done'])

    def test_a_working_session_is_not_resumed_twice(self):
        self.transcript('busy', [user('x'), answer('Lanzo los tests.'), user('[tool_result]')], age=10)
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('busy', 'soft'), ('hard1', 'hard')])
        text = self.hook(mode='bypassPermissions')
        self.assertNotIn('local_busy', text)
        self.assertIn('local_hard1', text)

    def test_bypass_session_gets_first_minutes_when_some_were_cut_by_the_error(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')])
        self.assertEqual(self.hook(sid='auto-one', mode='auto'), '')
        self.assertIn('local_hard1', self.hook(sid='bypass-one', mode='bypassPermissions'))

    def test_after_the_wait_any_desktop_session_claims(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 600)
        self.assertIn('local_hard1', self.hook(sid='auto-one', mode='auto'))

    def test_stale_or_finished_event_is_ignored(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 7 * 3600)
        self.assertEqual(self.hook(), '')
        self.event([('hard1', 'hard')], done=True)
        self.assertEqual(self.hook(), '')


    # --- a listed session receives the resume at most once per event ----------------------------------------------

    def test_claim_drops_the_sessions_that_already_hold_the_resume(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.transcript('hard2', [user('x'), answer(LIMIT, error=True), self.delivery()])
        self.event([('hard1', 'hard'), ('hard2', 'hard')], at=time.time() - 300)
        text = self.hook(mode='bypassPermissions')
        self.assertIn('local_hard1', text)
        self.assertNotIn('local_hard2', text)
        self.assertEqual([s['cliSessionId'] for s in self.saved_event()['sessions']], ['hard1'])

    def test_a_delivery_from_before_the_event_does_not_count(self):
        self.transcript('hard1', [self.delivery(ago=3600), user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 300)
        self.assertIn('local_hard1', self.hook(mode='bypassPermissions'))

    def test_quoting_the_marker_is_not_a_delivery(self):
        quote = {"type": "assistant", "timestamp": self.delivery()["timestamp"],
                 "message": {"role": "assistant", "content": [{"type": "text", "text": "[cambio de cuenta] sigue"}]}}
        self.transcript('hard1', [quote, user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 300)
        self.assertIn('local_hard1', self.hook(mode='bypassPermissions'))

    # --- mine: is this still mine, and who is left? ---------------------------------------------------------------

    def claimed_event(self, sessions=(('hard1', 'hard'), ('hard2', 'hard')), **extra):
        data = dict(claimed_by='me', claimed_at=time.time() - 60, at=time.time() - 300)
        data.update(extra)
        self.event(list(sessions), **data)

    def test_mine_says_yes_to_the_fresh_claimant_and_lists_who_is_left(self):
        self.transcript('hard2', [self.delivery()])
        self.claimed_event()
        rc, out = self.run_rc('mine', sid='me')
        self.assertEqual(rc, 0, out)
        deadline = time.strftime('%H:%M', time.localtime(self.saved_event()['claimed_at'] + 30 * 60))
        self.assertIn(f'Sí: el aviso es tuyo hasta las {deadline}. Faltan:', out)
        self.assertIn('   - local_hard1 · hard1', out)
        self.assertNotIn('local_hard2', out)

    def test_mine_says_nothing_is_left_when_everyone_got_it(self):
        self.transcript('hard1', [self.delivery()])
        self.transcript('hard2', [self.delivery()])
        self.claimed_event()
        rc, out = self.run_rc('mine', sid='me')
        self.assertEqual(rc, 0, out)
        self.assertIn('No falta ninguna: ejecuta `~/.claude/scripts/account-switch done`.', out)
        self.assertNotIn('Faltan', out)

    def test_mine_counts_the_scheduled_task_claim_as_the_claimants(self):
        self.claimed_event(claimed_by='scheduled-task:me')
        self.assertEqual(self.run_rc('mine', sid='me')[0], 0)

    def test_mine_takes_the_session_from_the_argument_too(self):
        self.claimed_event()
        self.assertEqual(self.run_rc('mine', '--session', 'me')[0], 0)

    def test_mine_says_no_with_the_reason(self):
        tail = 'No envíes nada, no preguntes al desarrollador y sigue con tu tarea.'
        cases = [
            ('lo reclamó otra sesión', dict(claimed_by='other')),
            ('tu reclamación caducó a las', dict(claimed_at=time.time() - 31 * 60)),
            ('el cambio de cuenta ya terminó', dict(done=True)),
        ]
        for reason, extra in cases:
            self.claimed_event(**extra)
            rc, out = self.run_rc('mine', sid='me')
            self.assertEqual(rc, 1, reason)
            self.assertIn(f'No: {reason}', out)
            self.assertIn(tail, out)
        os.remove(os.path.join(self.state, 'event.json'))
        rc, out = self.run_rc('mine', sid='me')
        self.assertEqual(rc, 1)
        self.assertIn('No: no hay ningún cambio de cuenta pendiente', out)

    def test_mine_without_a_session_id_is_not_the_claimant(self):
        self.claimed_event()
        self.assertEqual(self.run_rc('mine')[0], 1)

    def test_mine_never_writes_the_event(self):
        self.claimed_event()
        path = os.path.join(self.state, 'event.json')

        def snapshot():
            with open(path) as fh:
                return fh.read(), os.stat(path).st_mtime_ns

        before = snapshot()
        for sid in ('me', 'other'):
            self.run_rc('mine', sid=sid)
        self.assertEqual(snapshot(), before)

    def test_steps_tell_the_claimant_to_run_mine_before_sending(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')])
        text = self.hook(mode='bypassPermissions')
        self.assertIn('account-switch mine', text)
        self.assertLess(text.index('account-switch mine'), text.index('«[cambio de cuenta]'))
        self.assertIn('\n1. Envía', text)
        self.assertIn('\n3. Al terminar', text)

    # --- done: only the claimant closes the event -------------------------------------------------------------

    def test_done_from_another_session_leaves_the_event_open(self):
        self.claimed_event()
        rc, out = self.run_rc('done', sid='stale')
        self.assertEqual(rc, 1)
        self.assertIn('No: este aviso de cambio de cuenta es de otra sesión; no hace falta que hagas nada. '
                      'Sigue con tu tarea.', out)
        self.assertFalse(self.saved_event()['done'])

    def test_done_from_the_claimant_closes_it(self):
        for claimed_by in ('me', 'scheduled-task:me'):
            self.claimed_event(claimed_by=claimed_by)
            self.assertEqual(self.run_rc('done', sid='me')[0], 0)
            self.assertTrue(self.saved_event()['done'], claimed_by)

    def test_done_with_no_session_id_or_with_force_closes_it(self):
        self.claimed_event()
        self.assertEqual(self.run_rc('done')[0], 0)
        self.assertTrue(self.saved_event()['done'])
        self.claimed_event()
        self.assertEqual(self.run_rc('done', '--force', sid='stale')[0], 0)
        self.assertTrue(self.saved_event()['done'])

    def test_done_on_an_unclaimed_event_closes_it(self):
        self.event([('hard1', 'hard')])
        self.assertEqual(self.run_rc('done', sid='anyone')[0], 0)
        self.assertTrue(self.saved_event()['done'])

    # --- not_before: a new account with no usage cannot take the resume yet ------------------------------------------

    def test_a_hook_session_gets_nothing_while_the_account_has_no_usage(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 600, not_before=time.time() + 3600)
        self.assertEqual(self.hook(sid='bypass-one', mode='bypassPermissions'), '')
        self.assertIsNone(self.saved_event()['claimed_by'])

    def test_a_hook_session_takes_it_once_not_before_has_passed(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 600, not_before=time.time() - 60)
        self.assertIn('local_hard1', self.hook(sid='auto-one', mode='auto'))

    def test_brief_ignores_not_before_because_the_account_is_answering(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], not_before=time.time() + 3600)
        self.assertIn('local_hard1', self.run_cmd('brief', '--wait', '0'))
        event = self.saved_event()
        self.assertTrue(event['claimed_by'].startswith('scheduled-task:'))
        self.assertIsNone(event['not_before'], 'the recorded limit is over once the task runs')

    def test_the_event_ages_from_not_before(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 8 * 3600, not_before=time.time() - 600)
        self.assertIn('local_hard1', self.hook(mode='bypassPermissions'))
        self.event([('hard1', 'hard')], at=time.time() - 8 * 3600, not_before=time.time() - 7 * 3600)
        self.assertEqual(self.hook(sid='other', mode='bypassPermissions'), '')

    def test_mine_counts_the_age_from_not_before(self):
        self.claimed_event(at=time.time() - 8 * 3600, not_before=time.time() - 600)
        self.assertEqual(self.run_rc('mine', sid='me')[0], 0)
        self.claimed_event(at=time.time() - 8 * 3600)
        self.assertEqual(self.run_rc('mine', sid='me')[0], 1)

    def test_brief_waits_for_a_stale_event_only_up_to_its_wait(self):
        self.event([], at=time.time() - 8 * 3600)
        self.assertIn('Nada que hacer', self.run_cmd('brief', '--wait', '0'))

    # --- release: the claimant gives the event back ---------------------------------------------------------------

    def test_release_by_the_claimant_frees_the_event_for_the_next_session(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        for claimed_by in ('me', 'scheduled-task:me'):
            self.claimed_event(sessions=(('hard1', 'hard'),), claimed_by=claimed_by)
            rc, out = self.run_rc('release', sid='me')
            self.assertEqual(rc, 0, out)
            event = self.saved_event()
            self.assertEqual((event['claimed_by'], event['claimed_at'], event['done']), (None, None, False))
            self.assertIn('hard1', self.hook(sid='next', mode='bypassPermissions'))
            self.assertEqual(self.saved_event()['claimed_by'], 'next')

    def test_release_takes_the_session_from_the_argument_too(self):
        self.claimed_event()
        self.assertEqual(self.run_rc('release', '--session', 'me')[0], 0)
        self.assertIsNone(self.saved_event()['claimed_by'])

    def test_release_from_anyone_else_changes_nothing(self):
        self.claimed_event()
        before = self.saved_event()
        for sid in ('stale', None):
            rc, out = self.run_rc('release', sid=sid)
            self.assertEqual(rc, 1)
            self.assertIn('No: este aviso de cambio de cuenta no es tuyo', out)
            self.assertEqual(self.saved_event(), before)

    def test_release_with_no_event_or_an_unclaimed_one_says_no(self):
        self.assertEqual(self.run_rc('release', sid='me')[0], 1)
        self.event([('hard1', 'hard')])
        self.assertEqual(self.run_rc('release', sid='me')[0], 1)

    def test_the_steps_say_it_is_theirs_and_how_to_hand_it_back(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')])
        text = self.hook(mode='bypassPermissions')
        self.assertIn('Esto es tuyo aunque esas sesiones sean de otros proyectos', text)
        self.assertIn('rules/cambio-de-cuenta.md', text)
        self.assertIn('account-switch release', text)
        self.assertLess(text.index('account-switch release'), text.index('\n1. Envía'))

    def test_status_shows_when_the_new_account_has_usage_again(self):
        until = time.time() + 3 * 3600
        self.event([('hard1', 'hard')], not_before=until, limit_what='five_hour')
        out = self.run_cmd('status')
        self.assertIn('sin uso hasta las ' + time.strftime('%H:%M', time.localtime(until)), out)
        self.assertIn('según lo anotado', out)   # the test CLI has no credentials: nothing to check it against
        self.event([('hard1', 'hard')], not_before=time.time() - 60)
        self.assertNotIn('sin uso', self.run_cmd('status'))
        self.event([('hard1', 'hard')])
        self.assertNotIn('sin uso', self.run_cmd('status'))

    def fake_account_script(self, org, usage_json):
        """A copy of account-switch whose cli_org()/usage() answer `org`/`usage_json` (None: no answer), run as a
        subprocess so `status` goes through its own command line."""
        path = os.path.join(self.state, 'account-switch-fake')
        with open(SCRIPT) as fh:
            src = fh.read()
        src = src.replace('\ndef cli_org():', '\ndef cli_org_real():', 1).replace(
            '\ndef usage():', '\ndef usage_real():', 1)
        src = src.replace('if __name__ == "__main__":', f'def cli_org():\n    return {org!r}\n\n\n'
                          f'def usage():\n    return {usage_json!r}\n\n\nif __name__ == "__main__":')
        with open(path, 'w') as fh:
            fh.write(src)
        return path

    def status_with(self, org, usage_json, **event_extra):
        until = time.time() + 3 * 3600
        self.event([('hard1', 'hard')], not_before=until, limit_what='five_hour', **event_extra)
        script = self.fake_account_script(org, usage_json)
        out = subprocess.run([sys.executable, script, 'status'], capture_output=True, text=True, env=self.env(),
                             timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout, until

    def test_status_says_the_limit_was_lifted_when_the_usage_endpoint_shows_room(self):
        out, _ = self.status_with('d', {"five_hour": {"utilization": 17, "resets_at": None}})
        self.assertIn('Cuenta nueva: el límite anotado ya no rige; el uso real de la cuenta tiene margen '
                      '(comprobado ahora)', out)
        self.assertNotIn('sin uso hasta', out)
        event = self.saved_event()
        self.assertIsNone(event['not_before'])
        self.assertIn('limit_lifted_at', event)

    def test_status_keeps_the_limit_line_when_the_usage_endpoint_confirms_it(self):
        resets = datetime.datetime.fromtimestamp(time.time() + 7200, datetime.timezone.utc).isoformat()
        out, until = self.status_with('d', {"five_hour": {"utilization": 100, "resets_at": resets}})
        self.assertIn('sin uso hasta las ' + time.strftime('%H:%M', time.localtime(time.time() + 7200)), out)
        self.assertIn('(límite de 5 horas) (comprobado ahora con el uso real)', out)
        self.assertGreater(self.saved_event()['not_before'], time.time())

    def test_status_says_it_could_not_check_when_the_cli_is_in_another_organization(self):
        out, until = self.status_with('other-org', {"five_hour": {"utilization": 17}})
        self.assertIn('sin uso hasta las ' + time.strftime('%H:%M', time.localtime(until)), out)
        self.assertIn('según lo anotado; sin comprobar: mira get_usage antes de darlo por vigente', out)
        self.assertEqual(self.saved_event()['not_before'], until)

    def test_a_hook_session_claims_after_the_limit_was_lifted_early(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], not_before=time.time() + 3 * 3600, limit_what='five_hour')
        script = self.fake_account_script('d', {"five_hour": {"utilization": 17}})
        out = subprocess.run([sys.executable, script, 'hook'], input=json.dumps({"session_id": 'claimer',
                             "permission_mode": 'bypassPermissions'}), capture_output=True, text=True,
                             env=self.env(CLAUDE_CODE_ENTRYPOINT='claude-desktop'), timeout=30)
        self.assertIn('local_hard1', out.stdout)
        self.assertEqual(self.saved_event()['claimed_by'], 'claimer')

    def test_mine_says_nobody_claimed_it_yet_when_there_is_no_claimant(self):
        self.event([('hard1', 'hard')])
        rc, out = self.run_rc('mine', sid='me')
        self.assertEqual(rc, 1)
        self.assertIn('No: nadie lo ha reclamado todavía', out)
        self.assertNotIn('lo reclamó otra sesión', out)

    def test_after_reset_through_the_command_line_ignores_an_unknown_event(self):
        self.event([('hard1', 'hard')])
        before = self.saved_event()
        self.assertEqual(self.run_rc('after-reset', '--event', 'nope')[0], 0)
        self.assertEqual(self.saved_event(), before)

    # -- the toolkit's version: machine values from config pieces, the routines engine optional

    def config_dir(self, **pieces):
        folder = tempfile.mkdtemp(prefix='account-switch-config-')
        self.addCleanup(shutil.rmtree, folder, True)
        for name, data in pieces.items():
            with open(os.path.join(folder, f'{name}.json'), 'w') as fh:
                fh.write(data if isinstance(data, str) else json.dumps(data))
        return folder

    def arm_cwd(self, config):
        self.app_folder('acc-a', 'org-1', [])
        other = self.app_folder('acc-b', 'org-2', [])
        with open(os.path.join(self.state, 'state.json'), 'w') as fh:
            json.dump({"account": "acc-a", "org": "org-1"}, fh)
        out = subprocess.run([sys.executable, SCRIPT, 'arm'], capture_output=True, text=True, timeout=60,
                             env=self.env(CLAUDE_TOOLKIT_CONFIG_DIR=config))
        self.assertEqual(out.returncode, 0, out.stderr)
        task = next(t for t in self.tasks_in(other) if t['id'] == 'account-switch-resume')
        self.last_task = task
        return task['cwd']

    def test_the_resume_task_runs_in_the_folder_of_the_config_piece(self):
        folder = tempfile.mkdtemp(prefix='account-switch-cwd-')
        self.addCleanup(shutil.rmtree, folder, True)
        config = self.config_dir(**{'account-switch': {'task_cwd': folder, 'task_name': 'Resume after a switch'}})
        self.assertEqual(self.arm_cwd(config), folder)
        self.assertEqual(self.last_task['displayName'], 'Resume after a switch')

    def test_without_the_config_piece_or_with_a_corrupt_one_the_task_runs_in_home(self):
        home = self.env()['HOME']
        self.assertEqual(self.arm_cwd(self.config_dir()), home)
        self.assertEqual(self.arm_cwd(self.config_dir(**{'account-switch': '{broken'})), home)
        self.assertEqual(self.arm_cwd(self.config_dir(**{'account-switch': {'task_cwd': ''}})), home)

    def test_the_marker_comes_from_the_supervision_piece_like_the_gate(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 600)
        config = self.config_dir(supervision={'account_switch_marker': '[account switch]'})
        out = subprocess.run([sys.executable, SCRIPT, 'brief', '--wait', '0'], capture_output=True, text=True,
                             timeout=60, env=self.env(CLAUDE_TOOLKIT_CONFIG_DIR=config))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('«[account switch] ', out.stdout)
        self.assertNotIn('[cambio de cuenta]', out.stdout)

    def test_an_empty_marker_in_the_config_keeps_the_default(self):
        self.transcript('hard1', [user('x'), answer(LIMIT, error=True)])
        self.event([('hard1', 'hard')], at=time.time() - 600)
        config = self.config_dir(supervision={'account_switch_marker': ''})
        out = subprocess.run([sys.executable, SCRIPT, 'brief', '--wait', '0'], capture_output=True, text=True,
                             timeout=60, env=self.env(CLAUDE_TOOLKIT_CONFIG_DIR=config))
        self.assertIn('«[cambio de cuenta] ', out.stdout)


class ModuleTest(unittest.TestCase):
    """The script loaded as a module, with the network, notifications, systemd and sleeps replaced."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='account-switch-mod-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.mkdir('state')
        self.projects = self.mkdir('projects')
        self.app = self.mkdir('app')
        os.makedirs(os.path.join(self.projects, 'proj'))
        self.credentials = os.path.join(self.tmp, 'credentials.json')
        env = dict(ACCOUNT_SWITCH_STATE=self.state, ACCOUNT_SWITCH_PROJECTS=self.projects,
                   ACCOUNT_SWITCH_APP_SESSIONS=self.app, ACCOUNT_SWITCH_CLI_CREDENTIALS=self.credentials)
        with mock.patch.dict(os.environ, env):
            loader = importlib.machinery.SourceFileLoader('account_switch_under_test', SCRIPT)
            spec = importlib.util.spec_from_loader(loader.name, loader)
            self.mod = importlib.util.module_from_spec(spec)
            loader.exec_module(self.mod)

    def mkdir(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        return path

    def write_credentials(self, token, expires_in):
        with open(self.credentials, 'w') as fh:
            json.dump({"claudeAiOauth": {"accessToken": token, "expiresAt": int((time.time() + expires_in) * 1000)}}, fh)

    def fake_claude(self):
        """A `claude` first on the PATH that writes a fresh token and leaves a mark, like `claude auth status`."""
        bindir = self.mkdir('bin')
        self.called = os.path.join(self.tmp, 'claude-called')
        script = os.path.join(bindir, 'claude')
        with open(script, 'w') as fh:
            fh.write('#!/bin/sh\necho "$@" >> "%s"\n'
                     'printf \'{"claudeAiOauth": {"accessToken": "fresh", "expiresAt": %d}}\' > "%s"\n'
                     % (self.called, (time.time() + 8 * 3600) * 1000, self.credentials))
        os.chmod(script, 0o755)
        self.mod.CLI_PATH = bindir

    # --- the toolkit's version -------------------------------------------------------------------------------------

    def test_the_helpers_other_pieces_import_are_there(self):
        # supervisor-lock, session-nudge and cloud-tests load this file as a module and call these
        for name in ('load', 'STATE', 'cli_org', 'usage', 'usage_limit', 'transcript_limit'):
            self.assertTrue(hasattr(self.mod, name), name)
        self.assertIsInstance(self.mod.load(os.path.join(self.tmp, 'missing.json'), {}), dict)

    def test_without_the_routines_engine_no_routines_login_is_asked(self):
        self.mod.ROUTINES = os.path.join(self.tmp, 'no-routines')
        self.mod.cli_org = lambda: 'org-new'
        self.mod.routines_org = lambda: self.fail('the routines token is not looked at without the engine')
        self.assertEqual(self.mod.needed_logins('org-new'), [])
        self.assertEqual(self.mod.needed_logins('org-other'), ['cli'])

    def test_with_the_routines_engine_its_token_is_checked(self):
        engine = os.path.join(self.tmp, 'routines')
        with open(engine, 'w') as fh:
            fh.write('#!/bin/sh\n')
        os.chmod(engine, 0o755)
        self.mod.ROUTINES = engine
        self.mod.cli_org = lambda: 'org-new'
        self.mod.routines_org = lambda: 'org-old'
        self.assertEqual(self.mod.needed_logins('org-new'), ['routines'])

    def test_login_without_the_routines_engine_does_not_run_it(self):
        self.mod.ROUTINES = os.path.join(self.tmp, 'no-routines')
        self.mod.cli_org = lambda: 'org-new'
        self.mod.plan_warning = lambda: ''
        self.mod.missing_connectors = lambda org: None
        ran = []
        with mock.patch.object(self.mod.subprocess, 'run', side_effect=lambda *a, **k: ran.append(a)), \
                mock.patch.object(self.mod.sys.stdin, 'isatty', return_value=False), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_login(mock.Mock(org='org-new')), 0)
        self.assertEqual(ran, [])

    # --- cli_token -------------------------------------------------------------------------------------------------

    def test_an_expired_cli_token_is_refreshed_by_the_cli(self):
        self.write_credentials('old', -60)
        self.fake_claude()
        self.assertEqual(self.mod.cli_token(), 'fresh')
        with open(self.called) as fh:
            self.assertEqual(fh.read().strip(), 'auth status --json')

    def test_a_token_about_to_expire_is_refreshed_too(self):
        self.write_credentials('old', 60)
        self.fake_claude()
        self.assertEqual(self.mod.cli_token(), 'fresh')

    def test_a_valid_cli_token_does_not_call_the_cli(self):
        self.write_credentials('good', 3600)
        self.fake_claude()
        self.assertEqual(self.mod.cli_token(), 'good')
        self.assertFalse(os.path.exists(self.called))

    def test_no_credentials_means_no_token_and_no_cli_call(self):
        self.fake_claude()
        self.assertIsNone(self.mod.cli_token())
        self.assertFalse(os.path.exists(self.called))

    def test_a_cli_that_fails_leaves_the_old_token(self):
        self.write_credentials('old', -60)
        bindir = self.mkdir('bin')
        with open(os.path.join(bindir, 'claude'), 'w') as fh:
            fh.write('#!/bin/sh\nexit 1\n')
        os.chmod(os.path.join(bindir, 'claude'), 0o755)
        self.mod.CLI_PATH = bindir
        self.assertEqual(self.mod.cli_token(), 'old')

    def test_the_profile_and_the_connectors_use_the_refreshed_token(self):
        self.write_credentials('old', -60)
        self.fake_claude()
        seen = []

        def fake_http(url, token, data=None, beta=None):
            seen.append(token)
            return {}, {"organization": {"uuid": "o"}, "account": {"email": "e"}, "data": []}

        self.mod.http_json = fake_http
        self.assertEqual(self.mod.cli_org(), 'o')
        self.write_credentials('old', -60)
        self.assertEqual(self.mod.account_connectors(), {})
        self.assertEqual(seen, ['fresh', 'fresh'])

    # --- usage: one cache shared by every caller, robust to 429 ------------------------------------------------------

    def fake_usage_endpoint(self, *answers):
        """http_json replaced by one that gives `answers` in turn (an exception is raised); returns the call list."""
        calls, queue = [], list(answers)

        def fake_http(url, token, data=None, beta=None):
            calls.append(url)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return {}, answer

        self.mod.http_json = fake_http
        return calls

    @staticmethod
    def too_many(retry_after='0'):
        headers = email.message.Message()
        if retry_after is not None:
            headers['retry-after'] = retry_after
        return urllib.error.HTTPError('https://api.anthropic.com/api/oauth/usage', 429, 'Too Many Requests', headers,
                                      None)

    def seed_usage_cache(self, data, age, token='tok', **extra):
        """A cache entry for `token` whose answer is `age` seconds old (as the script itself writes it)."""
        key = self.mod.hashlib.sha256(token.encode()).hexdigest()[:16]
        self.mod._save_usage_cache(dict({"key": key, "at": time.time() - age, "data": data}, **extra))

    def usage_cache(self):
        with open(self.mod.USAGE_CACHE) as fh:
            return json.load(fh)

    def test_the_usage_cache_lives_in_the_state_dir(self):
        self.assertEqual(os.path.dirname(self.mod.USAGE_CACHE), self.state)

    def test_a_200_refreshes_the_cache_without_storing_the_token(self):
        self.write_credentials('secret-token', 3600)
        self.seed_usage_cache({"five_hour": {"utilization": 5}}, age=120, token='secret-token')
        calls = self.fake_usage_endpoint({"five_hour": {"utilization": 42}})
        self.assertEqual(self.mod.usage(), {"five_hour": {"utilization": 42}})
        self.assertEqual(len(calls), 1)
        cache = self.usage_cache()
        self.assertEqual(cache["data"], {"five_hour": {"utilization": 42}})
        self.assertAlmostEqual(cache["at"], time.time(), delta=5)
        self.assertNotIn("not_before", cache)
        with open(self.mod.USAGE_CACHE) as fh:
            self.assertNotIn('secret-token', fh.read())

    def test_a_fresh_answer_is_served_without_the_network(self):
        self.write_credentials('tok', 3600)
        calls = self.fake_usage_endpoint({"five_hour": {"utilization": 42}})
        for _ in range(5):
            self.assertEqual(self.mod.usage(), {"five_hour": {"utilization": 42}})
        self.assertEqual(len(calls), 1)

    def test_a_429_serves_the_last_good_answer_and_sets_the_back_off(self):
        self.write_credentials('tok', 3600)
        self.seed_usage_cache({"five_hour": {"utilization": 7}}, age=5 * 60)
        calls = self.fake_usage_endpoint(self.too_many('0'))
        self.assertEqual(self.mod.usage(), {"five_hour": {"utilization": 7}})
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(self.usage_cache()["not_before"], time.time() + self.mod.USAGE_BACKOFF, delta=5)
        self.assertEqual(self.usage_cache()["data"], {"five_hour": {"utilization": 7}})   # the good answer is kept

    def test_a_longer_retry_after_wins_and_a_bad_one_falls_back_to_the_minimum(self):
        self.write_credentials('tok', 3600)
        self.fake_usage_endpoint(self.too_many('90'))
        self.assertIsNone(self.mod.usage())
        self.assertAlmostEqual(self.usage_cache()["not_before"], time.time() + 90, delta=5)
        os.unlink(self.mod.USAGE_CACHE)
        self.fake_usage_endpoint(self.too_many('Wed, 26 Nov 2026 04:31:00 GMT'))
        self.assertIsNone(self.mod.usage())
        self.assertAlmostEqual(self.usage_cache()["not_before"], time.time() + self.mod.USAGE_BACKOFF, delta=5)

    def test_during_the_back_off_nothing_asks_the_network(self):
        self.write_credentials('tok', 3600)
        self.seed_usage_cache({"five_hour": {"utilization": 7}}, age=5 * 60, not_before=time.time() + 30)
        calls = self.fake_usage_endpoint()
        self.assertEqual(self.mod.usage(), {"five_hour": {"utilization": 7}})
        self.seed_usage_cache(None, age=0, not_before=time.time() + 30)
        self.assertIsNone(self.mod.usage())
        self.assertEqual(calls, [])

    def test_a_429_with_no_recent_good_answer_is_none(self):
        self.write_credentials('tok', 3600)
        calls = self.fake_usage_endpoint(self.too_many(), self.too_many())
        self.assertIsNone(self.mod.usage())   # nothing cached
        self.seed_usage_cache({"five_hour": {"utilization": 7}}, age=self.mod.USAGE_STALE + 60)
        self.assertIsNone(self.mod.usage())   # cached, but too old
        self.assertEqual(len(calls), 2)

    def test_other_errors_fall_back_to_the_last_good_answer_without_a_back_off(self):
        self.write_credentials('tok', 3600)
        self.seed_usage_cache({"five_hour": {"utilization": 7}}, age=5 * 60)
        self.fake_usage_endpoint(urllib.error.URLError('down'))
        self.assertEqual(self.mod.usage(), {"five_hour": {"utilization": 7}})
        self.assertNotIn("not_before", self.usage_cache())

    def test_the_answer_of_another_account_is_never_served(self):
        self.write_credentials('new-account', 3600)
        self.seed_usage_cache({"five_hour": {"utilization": 100}}, age=10, token='old-account',
                              not_before=time.time() + 30)
        calls = self.fake_usage_endpoint({"five_hour": {"utilization": 3}}, self.too_many())
        self.assertEqual(self.mod.usage(), {"five_hour": {"utilization": 3}})
        self.assertEqual(len(calls), 1)
        self.seed_usage_cache({"five_hour": {"utilization": 100}}, age=120, token='old-account')
        self.assertIsNone(self.mod.usage())   # a 429 for the new account does not fall back to the old one

    def test_an_unwritable_cache_does_not_break_usage(self):
        self.write_credentials('tok', 3600)
        self.mod.USAGE_CACHE = os.path.join(self.tmp, 'no-such-dir', 'usage-cache.json')
        self.mod.STATE_DIR = os.path.join(self.tmp, 'file-not-dir')
        open(self.mod.STATE_DIR, 'w').close()
        self.fake_usage_endpoint({"five_hour": {"utilization": 42}})
        self.assertEqual(self.mod.usage(), {"five_hour": {"utilization": 42}})

    # --- account_limit ---------------------------------------------------------------------------------------------

    @staticmethod
    def iso(ahead):
        return datetime.datetime.fromtimestamp(time.time() + ahead, datetime.timezone.utc).isoformat()

    def usage_answer(self, five=0, week=0, five_in=3600, week_in=86400, extra=None):
        return {"five_hour": {"utilization": five, "resets_at": self.iso(five_in)},
                "seven_day": {"utilization": week, "resets_at": self.iso(week_in)},
                "seven_day_opus": None, "extra_usage": extra or {"is_enabled": False, "spend_limit_reached": False}}

    def use_usage(self, answer, org='o'):
        self.mod.cli_org = lambda: org
        self.mod.usage = lambda: answer

    def refused(self, cli_id, resets_in, entrypoint='claude-desktop', ago=0, kind='five_hour'):
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - ago)) + '.123Z'
        entry = {"type": "assistant", "timestamp": stamp, "isApiErrorMessage": True, "apiError": "usage_limit_reached",
                 "entrypoint": entrypoint, "apiErrorParams": {"rate_limit_info": {
                     "status": "rejected", "resetsAt": int(time.time() + resets_in), "rateLimitType": kind}}}
        with open(os.path.join(self.projects, 'proj', f'{cli_id}.jsonl'), 'w') as fh:
            fh.write(json.dumps(entry, separators=(',', ':')) + '\n')

    def test_usage_with_the_five_hour_window_full_is_a_limit_until_its_reset(self):
        self.use_usage(self.usage_answer(five=100, five_in=3600))
        limit = self.mod.account_limit('o', time.time() - 3600)
        self.assertEqual((limit['what'], limit['source']), ('five_hour', 'usage'))
        self.assertAlmostEqual(limit['until'], time.time() + 3600, delta=5)

    def test_the_latest_reset_of_the_exhausted_windows_wins(self):
        self.use_usage(self.usage_answer(five=100, week=100.0, five_in=3600, week_in=86400))
        limit = self.mod.account_limit('o', time.time() - 3600)
        self.assertEqual(limit['what'], 'seven_day')
        self.assertAlmostEqual(limit['until'], time.time() + 86400, delta=5)

    def test_usage_below_the_limit_is_not_limited_and_the_transcripts_are_not_asked(self):
        self.use_usage(self.usage_answer(five=81, week=48))
        self.refused('s1', 3600)
        self.assertIsNone(self.mod.account_limit('o', time.time() - 3600))

    def test_a_window_already_reset_is_not_a_limit(self):
        self.use_usage(self.usage_answer(five=100, five_in=-60))
        self.assertIsNone(self.mod.account_limit('o', time.time() - 3600))

    def test_extra_usage_on_keeps_the_account_working_until_its_spend_limit(self):
        self.use_usage(self.usage_answer(five=100, extra={"is_enabled": True, "spend_limit_reached": False}))
        self.assertIsNone(self.mod.account_limit('o', time.time() - 3600))
        self.use_usage(self.usage_answer(five=100, extra={"is_enabled": True, "spend_limit_reached": True}))
        self.assertEqual(self.mod.account_limit('o', time.time() - 3600)['what'], 'five_hour')

    def test_a_failed_usage_request_falls_back_to_the_transcripts(self):
        self.use_usage(None)
        self.refused('s1', 7200)
        limit = self.mod.account_limit('o', time.time() - 3600)
        self.assertEqual((limit['what'], limit['source']), ('five_hour', 'transcripts'))
        self.assertAlmostEqual(limit['until'], time.time() + 7200, delta=5)

    def test_another_account_than_the_cli_one_is_read_from_the_transcripts(self):
        self.use_usage(self.usage_answer(), org='other')
        self.mod.usage = mock.Mock(side_effect=AssertionError('must not ask the usage of another account'))
        self.refused('s1', 7200, kind='seven_day')
        limit = self.mod.account_limit('o', time.time() - 3600)
        self.assertEqual((limit['what'], limit['source']), ('seven_day', 'transcripts'))

    def test_transcripts_ignore_old_entries_other_entrypoints_and_past_resets(self):
        self.use_usage(None)
        self.refused('before', 7200, ago=7200)             # refused before the switch
        self.refused('cli', 7200, entrypoint='sdk-cli')    # not the desktop app
        self.refused('past', -60)                          # already reset
        self.assertIsNone(self.mod.account_limit('o', time.time() - 3600))

    def test_transcripts_not_touched_since_the_switch_are_not_read(self):
        self.use_usage(None)
        self.refused('s1', 7200)
        path = os.path.join(self.projects, 'proj', 's1.jsonl')
        os.utime(path, (time.time() - 7200, time.time() - 7200))
        self.assertIsNone(self.mod.account_limit('o', time.time() - 3600))

    def test_the_latest_reset_among_the_refused_turns_wins(self):
        self.use_usage(None)
        self.refused('a', 3600)
        self.refused('b', 9000, kind='seven_day')
        limit = self.mod.account_limit('o', time.time() - 3600)
        self.assertEqual(limit['what'], 'seven_day')
        self.assertAlmostEqual(limit['until'], time.time() + 9000, delta=5)

    # --- on-switch: a new account that is itself out of usage ------------------------------------------------------

    def write_event(self, **extra):
        data = {"id": "100", "at": time.time(), "from": ["a", "b"], "to": ["c", "d"], "claimed_by": None,
                "claimed_at": None, "done": False,
                "sessions": [{"sessionId": "local_h", "cliSessionId": "h", "title": "h", "cwd": "/tmp", "kind": "hard"}]}
        data.update(extra)
        with open(os.path.join(self.state, 'event.json'), 'w') as fh:
            json.dump(data, fh)

    def saved_event(self):
        with open(os.path.join(self.state, 'event.json')) as fh:
            return json.load(fh)

    def on_switch(self, limits, logins=()):
        """Run cmd_on_switch with `limits` as the successive answers of account_limit; (notifications, systemd-run
        argument lists)."""
        notes, scheduled = [], []
        self.mod.notify = lambda title, text, urgency="normal": notes.append((title, text, urgency))
        self.mod.needed_logins = lambda org: list(logins)
        self.mod.plan_warning = lambda: ""
        self.mod.missing_connectors = lambda org: None
        self.mod.account_limit = mock.Mock(side_effect=list(limits))
        self.mod.cmd_arm = lambda args: 0
        with mock.patch.object(self.mod.time, 'sleep'), mock.patch.object(self.mod.shutil, 'which', return_value=None), \
                mock.patch.object(self.mod.subprocess, 'run', side_effect=lambda cmd, **kw: scheduled.append(cmd)):
            self.assertEqual(self.mod.cmd_on_switch(mock.Mock()), 0)
        return notes, scheduled

    def test_on_switch_with_the_new_account_out_of_usage_says_so_first_and_schedules_the_check(self):
        until = time.time() + 3 * 3600
        self.write_event()
        notes, scheduled = self.on_switch([{"until": until, "what": "five_hour", "source": "usage"}, None])
        first, text, urgency = notes[0]
        self.assertEqual(urgency, 'critical')
        head = text.splitlines()[0]
        self.assertIn('La cuenta nueva también está sin uso', head)
        self.assertIn('límite de 5 horas', head)
        self.assertIn(time.strftime('%H:%M', time.localtime(until)), head)
        self.assertIn('ninguna sesión puede continuar hasta entonces', head)
        self.assertIn('cambiar a ella', head)
        self.assertNotIn('se reanudarán solas', text)
        event = self.saved_event()
        self.assertEqual((event['not_before'], event['limit_what']), (until, 'five_hour'))
        self.assertEqual(len(scheduled), 2)   # the at-reset timer and the first early check
        cmd = scheduled[0]
        self.assertEqual(cmd[0], 'systemd-run')
        self.assertIn('--on-calendar=' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(until + 60)), cmd)
        self.assertIn('--timer-property=AccuracySec=15s', cmd)
        self.assertTrue(any(c.startswith('--unit=account-switch-100-reset') for c in cmd))
        self.assertEqual(cmd[-3:], ['after-reset', '--event', '100'])
        self.assertTrue(any(c.startswith('--setenv=ACCOUNT_SWITCH_STATE=') for c in cmd))
        early = scheduled[1]
        self.assertIn('--on-active=300', early)
        self.assertTrue(any(c.startswith('--unit=account-switch-100-early-') for c in early))
        self.assertEqual(early[-4:], ['after-reset', '--event', '100', '--early'])
        self.assertEqual(len(notes), 1, 'the watchdog says nothing more while he waits for the reset')

    def test_the_limit_message_carries_the_date_when_it_is_not_today(self):
        until = time.time() + 30 * 3600
        self.write_event()
        notes, _ = self.on_switch([{"until": until, "what": "seven_day", "source": "usage"}])
        head = notes[0][1].splitlines()[0]
        self.assertIn('límite semanal', head)
        self.assertIn(time.strftime('el %d-%m a las %H:%M', time.localtime(until)), head)

    def test_on_switch_without_a_limit_keeps_the_old_text_and_schedules_nothing(self):
        self.write_event()
        notes, scheduled = self.on_switch([None, None])
        self.assertIn('se reanudarán solas', notes[0][1])
        self.assertEqual(scheduled, [])
        self.assertNotIn('not_before', self.saved_event())
        self.assertEqual(notes[-1][0], 'Claude: el cambio de cuenta no se ha completado solo')

    def test_on_switch_that_needs_a_login_does_not_ask_for_the_limit_yet(self):
        self.write_event()
        notes, _ = self.on_switch([None], logins=['cli'])
        self.assertIn('Se abre una terminal', notes[0][1])
        self.assertEqual(self.mod.account_limit.call_count, 1, 'only the watchdog asks')

    def test_the_watchdog_finds_the_limit_the_cut_task_left_in_the_transcripts(self):
        until = time.time() + 2 * 3600
        self.write_event()
        notes, scheduled = self.on_switch([None, {"until": until, "what": "five_hour", "source": "transcripts"}])
        self.assertEqual(len(notes), 2)
        title, text, urgency = notes[1]
        self.assertIn('se cortó', text)
        self.assertIn(time.strftime('%H:%M', time.localtime(until)), text)
        self.assertNotIn('no ha arrancado', text)
        self.assertEqual(self.saved_event()['not_before'], until)
        self.assertEqual(len(scheduled), 2)

    def test_the_watchdog_says_nothing_when_a_session_claimed_the_event(self):
        self.write_event(claimed_by='someone', claimed_at=time.time())
        notes, scheduled = self.on_switch([None])
        self.assertEqual(len(notes), 1)
        self.assertEqual(self.mod.account_limit.call_count, 1)

    def test_the_watchdog_asks_again_only_when_no_not_before_is_recorded(self):
        # a not_before already in the past (a short limit) still falls through to the generic notice
        self.write_event(not_before=time.time() - 10)
        notes, _ = self.on_switch([None])
        self.assertEqual(notes[-1][0], 'Claude: el cambio de cuenta no se ha completado solo')
        self.assertEqual(self.mod.account_limit.call_count, 1)

    # --- after-reset -----------------------------------------------------------------------------------------------

    def after_reset(self, limit=None, event_id='100', account=('c', 'd'), transcripts=()):
        """Run cmd_after_reset; (notifications, systemd-run argument lists)."""
        with open(os.path.join(self.state, 'state.json'), 'w') as fh:
            json.dump({"account": account[0], "org": account[1]}, fh)
        for cli_id, entries in transcripts:
            with open(os.path.join(self.projects, 'proj', f'{cli_id}.jsonl'), 'w') as fh:
                for e in entries:
                    fh.write(json.dumps(e, separators=(',', ':')) + '\n')
        notes, scheduled = [], []
        self.mod.notify = lambda title, text, urgency="normal": notes.append((title, text, urgency))
        self.mod.account_limit = mock.Mock(return_value=limit)
        with mock.patch.object(self.mod.subprocess, 'run', side_effect=lambda cmd, **kw: scheduled.append(cmd)):
            self.assertEqual(self.mod.cmd_after_reset(mock.Mock(event=event_id, early=False)), 0)
        return notes, scheduled

    def stopped_transcript(self):
        return ('h', [user('x'), answer(LIMIT, error=True)])

    def test_after_reset_with_sessions_still_stopped_tells_him_to_write_in_any_session(self):
        before = time.time() - 120
        self.write_event(not_before=before)
        notes, scheduled = self.after_reset(transcripts=[self.stopped_transcript()])
        self.assertEqual(len(notes), 1)
        title, text, urgency = notes[0]
        self.assertEqual(urgency, 'critical')
        self.assertIn('ha vuelto', text)
        self.assertIn(time.strftime('%H:%M', time.localtime(before)), text)
        self.assertIn('1 sesiones siguen paradas', text)
        self.assertIn('Abre una sesión nueva en la app (mejor en Bypass permissions)', text)
        self.assertIn('las reanuda ella sola', text)
        self.assertNotIn('en cualquier sesión', text)
        self.assertEqual(scheduled, [])
        self.assertFalse(self.saved_event()['done'])
        # the question to account_limit starts at the recorded not_before
        self.assertEqual(self.mod.account_limit.call_args[0], ('d', before))

    def test_after_reset_with_nothing_left_closes_the_event_quietly(self):
        self.write_event(not_before=time.time() - 120)
        notes, _ = self.after_reset(transcripts=[('h', [user('x'), answer(LIMIT, error=True),
                                                         user('[cambio de cuenta] sigue'), answer('Sigo.')])])
        self.assertEqual(notes, [])
        self.assertTrue(self.saved_event()['done'])

    def test_after_reset_limited_again_moves_not_before_reschedules_and_tells_him(self):
        old = time.time() - 120
        until = time.time() + 2 * 86400
        self.write_event(not_before=old)
        notes, scheduled = self.after_reset(limit={"until": until, "what": "seven_day", "source": "usage"},
                                            transcripts=[self.stopped_transcript()])
        event = self.saved_event()
        self.assertEqual((event['not_before'], event['limit_what']), (until, 'seven_day'))
        self.assertEqual(len(scheduled), 2)
        self.assertIn('--on-calendar=' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(until + 60)), scheduled[0])
        self.assertEqual(len(notes), 1)
        self.assertIn('límite semanal', notes[0][1])
        self.assertIn(time.strftime('el %d-%m a las %H:%M', time.localtime(until)), notes[0][1])
        self.assertFalse(event['done'])

    def test_after_reset_leaves_other_events_done_ones_and_fresh_claims_alone(self):
        for extra, kwargs in [(dict(), dict(event_id='999')),
                              (dict(done=True), {}),
                              (dict(claimed_by='s', claimed_at=time.time() - 60), {}),
                              (dict(), dict(account=('x', 'y')))]:
            self.write_event(not_before=time.time() - 120, **extra)
            before = self.saved_event()
            notes, scheduled = self.after_reset(transcripts=[self.stopped_transcript()], **kwargs)
            self.assertEqual((notes, scheduled), ([], []), (extra, kwargs))
            self.assertEqual(self.saved_event(), before)
        self.assertEqual(self.mod.account_limit.call_count, 0)

    def test_after_reset_takes_over_a_claim_that_expired(self):
        self.write_event(not_before=time.time() - 120, claimed_by='s', claimed_at=time.time() - 20 * 60)
        notes, _ = self.after_reset(transcripts=[self.stopped_transcript()])
        self.assertEqual(len(notes), 1)

    # --- recheck_limit ---------------------------------------------------------------------------------------------

    def recheck(self, org='d', usage=None, force=False, event_id='100', **event_extra):
        """recheck_limit with the CLI in `org` and the usage endpoint answering `usage`; (result, usage calls)."""
        event_extra.setdefault('not_before', time.time() + 3 * 3600)
        self.write_event(**event_extra)
        self.mod.cli_org = lambda: org
        self.mod.usage = mock.Mock(return_value=usage)
        return self.mod.recheck_limit(event_id, force=force), self.mod.usage.call_count

    def test_recheck_lifts_the_limit_when_the_usage_endpoint_shows_room(self):
        result, calls = self.recheck(usage={"five_hour": {"utilization": 17}})
        self.assertEqual((result, calls), ('lifted', 1))
        event = self.saved_event()
        self.assertIsNone(event['not_before'])
        self.assertAlmostEqual(event['limit_lifted_at'], time.time(), delta=5)
        self.assertAlmostEqual(event['limit_checked_at'], time.time(), delta=5)

    def test_recheck_moves_not_before_to_the_limit_that_holds_now(self):
        resets = time.time() + 5000
        iso = datetime.datetime.fromtimestamp(resets, datetime.timezone.utc).isoformat()
        result, _ = self.recheck(usage={"seven_day": {"utilization": 100, "resets_at": iso}}, limit_what='five_hour')
        self.assertEqual(result, 'limited')
        event = self.saved_event()
        self.assertAlmostEqual(event['not_before'], resets, delta=1)
        self.assertEqual(event['limit_what'], 'seven_day')
        self.assertIn('limit_checked_at', event)

    def test_recheck_is_unknown_for_another_organization_or_without_an_answer(self):
        before = time.time() + 3 * 3600
        for org, usage in [('other-org', {"five_hour": {"utilization": 17}}), ('d', None)]:
            result, calls = self.recheck(org=org, usage=usage, not_before=before)
            self.assertEqual(result, 'unknown', org)
            event = self.saved_event()
            self.assertEqual(event['not_before'], before)
            self.assertIn('limit_checked_at', event)
        self.assertEqual(self.mod.usage.call_count, 1, 'only the case in the right organization asks, and gets no answer')

    def test_recheck_is_none_without_a_future_not_before_or_for_another_event(self):
        for extra in (dict(not_before=None), dict(not_before=time.time() - 5)):
            result, calls = self.recheck(usage={"five_hour": {"utilization": 17}}, **extra)
            self.assertEqual((result, calls), ('none', 0), extra)
        self.assertEqual(self.recheck(usage={"five_hour": {"utilization": 17}}, event_id='999')[0], 'none')
        self.assertIn('not_before', self.saved_event())
        self.assertIsNotNone(self.saved_event()['not_before'])

    def test_recheck_is_throttled_to_once_a_minute_unless_forced(self):
        usage = {"five_hour": {"utilization": 100,
                               "resets_at": datetime.datetime.fromtimestamp(time.time() + 5000,
                                                                           datetime.timezone.utc).isoformat()}}
        result, calls = self.recheck(usage=usage, limit_checked_at=time.time() - 10)
        self.assertEqual((result, calls), ('unknown', 0))
        result, calls = self.recheck(usage=usage, limit_checked_at=time.time() - 10, force=True)
        self.assertEqual((result, calls), ('limited', 1))
        result, calls = self.recheck(usage=usage, limit_checked_at=time.time() - 61)
        self.assertEqual((result, calls), ('limited', 1))

    def test_recheck_does_not_write_the_event_when_another_one_replaced_it_meanwhile(self):
        self.write_event(not_before=time.time() + 3600)

        def swap():
            self.write_event(id='200', not_before=time.time() + 3600)
            return {"five_hour": {"utilization": 17}}

        self.mod.cli_org = lambda: 'd'
        self.mod.usage = swap
        self.assertEqual(self.mod.recheck_limit('100', force=True), 'none')
        self.assertEqual(self.saved_event()['id'], '200')
        self.assertIsNotNone(self.saved_event()['not_before'])

    def test_recheck_swallows_errors_from_the_network_calls(self):
        self.write_event(not_before=time.time() + 3600)
        self.mod.cli_org = mock.Mock(side_effect=RuntimeError('boom'))
        self.assertEqual(self.mod.recheck_limit('100', force=True), 'unknown')

    # --- after-reset --early ---------------------------------------------------------------------------------------

    def after_reset_early(self, outcome, **event_extra):
        """cmd_after_reset --early with recheck_limit answering `outcome` (and, for "lifted", clearing not_before like
        the real one); (notifications, systemd-run argument lists)."""
        self.write_event(**event_extra)

        def fake(event_id, force=False):
            if outcome == 'lifted':
                late = self.saved_event()
                late['not_before'] = None
                with open(os.path.join(self.state, 'event.json'), 'w') as fh:
                    json.dump(late, fh)
            return outcome

        with open(os.path.join(self.state, 'state.json'), 'w') as fh:
            json.dump({"account": 'c', "org": 'd'}, fh)
        with open(os.path.join(self.projects, 'proj', 'h.jsonl'), 'w') as fh:
            for e in self.stopped_transcript()[1]:
                fh.write(json.dumps(e, separators=(',', ':')) + '\n')
        notes, scheduled = [], []
        self.mod.notify = lambda title, text, urgency="normal": notes.append((title, text, urgency))
        self.mod.account_limit = mock.Mock(return_value=None)
        self.mod.recheck_limit = mock.Mock(side_effect=fake)
        with mock.patch.object(self.mod.subprocess, 'run', side_effect=lambda cmd, **kw: scheduled.append(cmd)):
            self.assertEqual(self.mod.cmd_after_reset(mock.Mock(event='100', early=True)), 0)
        self.assertEqual(self.mod.recheck_limit.call_args[1].get('force'), True)
        self.assertEqual(self.mod.account_limit.call_count, 0, 'the early check asks only the usage endpoint')
        return notes, scheduled

    def test_after_reset_early_with_the_limit_lifted_tells_him_the_sessions_wait(self):
        notes, scheduled = self.after_reset_early('lifted', not_before=time.time() + 3 * 3600)
        self.assertEqual(scheduled, [])
        self.assertEqual(len(notes), 1)
        title, text, urgency = notes[0]
        self.assertEqual((title, urgency), ('Claude: la cuenta ya tiene uso', 'critical'))
        self.assertIn('El límite de la cuenta nueva se levantó antes de tiempo (cambio de plan o renovación)', text)
        self.assertNotIn('se renovó a las', text)
        self.assertIn('1 sesiones siguen paradas', text)

    def test_after_reset_early_lifted_with_nothing_left_closes_the_event(self):
        self.write_event(not_before=time.time() + 3 * 3600)
        self.mod.recheck_limit = lambda event_id, force=False: 'lifted'
        with open(os.path.join(self.state, 'state.json'), 'w') as fh:
            json.dump({"account": 'c', "org": 'd'}, fh)
        notes = []
        self.mod.notify = lambda *a, **k: notes.append(a)
        with mock.patch.object(self.mod.subprocess, 'run') as run:
            self.assertEqual(self.mod.cmd_after_reset(mock.Mock(event='100', early=True)), 0)
        self.assertEqual((notes, run.call_count), ([], 0))
        self.assertTrue(self.saved_event()['done'])

    def test_after_reset_early_still_limited_schedules_another_check(self):
        notes, scheduled = self.after_reset_early('limited', not_before=time.time() + 3 * 3600)
        self.assertEqual(notes, [])
        self.assertEqual(len(scheduled), 1)
        self.assertIn('--on-active=300', scheduled[0])
        self.assertEqual(scheduled[0][-4:], ['after-reset', '--event', '100', '--early'])
        self.assertFalse(self.saved_event()['done'])

    def test_after_reset_early_stops_polling_when_the_reset_is_near(self):
        notes, scheduled = self.after_reset_early('unknown', not_before=time.time() + 4 * 60)
        self.assertEqual((notes, scheduled), ([], []))

    def test_after_reset_early_respects_the_usual_guards(self):
        self.write_event(not_before=time.time() + 3600, done=True)
        self.mod.recheck_limit = mock.Mock(return_value='lifted')
        self.assertEqual(self.mod.cmd_after_reset(mock.Mock(event='100', early=True)), 0)
        self.write_event(not_before=time.time() + 3600, claimed_by='s', claimed_at=time.time() - 60)
        self.assertEqual(self.mod.cmd_after_reset(mock.Mock(event='100', early=True)), 0)
        self.assertEqual(self.mod.recheck_limit.call_count, 0)

    def test_claim_problem_with_no_claimant_says_nobody_took_it_yet(self):
        self.write_event()
        event = self.saved_event()
        self.assertIn('nadie lo ha reclamado todavía', self.mod.claim_problem(event, 'me'))
        event['claimed_by'] = 'other'
        self.assertEqual(self.mod.claim_problem(event, 'me'), 'lo reclamó otra sesión')

    def test_after_reset_without_an_event_does_nothing(self):
        notes, scheduled = self.after_reset()
        self.assertEqual((notes, scheduled), ([], []))


if __name__ == '__main__':
    unittest.main()
