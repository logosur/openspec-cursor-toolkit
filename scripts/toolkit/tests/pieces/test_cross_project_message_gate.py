"""Tests of global/hooks/cross-project-message-gate.

Every path is redirected into a temp dir (HOME included) and the projects are temp git repos, so the real registry,
state, locks, app records and switch event are never touched. The exception tests switch the exceptions on through a
temp config piece; DefaultsTest covers what a fresh install does.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from scripts.toolkit.paths import REPO_ROOT

HOOK = str(REPO_ROOT / 'global/hooks/cross-project-message-gate')
EVERY_EXCEPTION = ['account_switch', 'project_resume', 'skill_reload', 'supervisor_revive']


def gate_env(tmp, values=None, raw=None, **paths):
    """The hook's environment: a throwaway HOME, every path inside `tmp` and a config piece of its own."""
    config = os.path.join(tmp, 'toolkit-config')
    os.makedirs(config, exist_ok=True)
    with open(os.path.join(config, 'supervision.json'), 'w') as fh:
        fh.write(raw if raw is not None else
                 json.dumps({'message_exceptions': EVERY_EXCEPTION} if values is None else values))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CROSS_PROJECT_GATE_', 'ACCOUNT_SWITCH_', 'SUPERVISOR_LOCK_'))}
    env.update(HOME=os.path.join(tmp, 'home'), CLAUDE_TOOLKIT_CONFIG_DIR=config,
               PROJECT_PAUSE_BIN=os.path.join(tmp, 'none'))
    os.makedirs(env['HOME'], exist_ok=True)
    env.update(paths)
    return env
TOOL = 'mcp__ccd_session_mgmt__send_message'
MARKER = '[cambio de cuenta]'
RESUME = f'{MARKER} Sigue exactamente donde lo dejaste, sin repetir lo hecho.'
SENDER = 'cccccccc-1111-4111-8111-111111111111'
OTHER = 'dddddddd-2222-4222-8222-222222222222'
TARGET = 'eeeeeeee-3333-4333-8333-333333333333'
SIBLING = 'ffffffff-4444-4444-8444-444444444444'


class CrossProjectGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='cross-gate-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.mkdir('state')
        self.registry = self.mkdir('registry')
        self.app = self.mkdir('app')
        self.switch = self.mkdir('switch')
        self.projects = self.mkdir('projects')
        os.makedirs(os.path.join(self.projects, 'proj'))
        self.proj_a = self.repo('project-a')
        self.proj_b = self.repo('project-b')
        self.row('target', TARGET, self.proj_b)
        self.row('sibling', SIBLING, self.proj_a)

    def mkdir(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        return path

    def repo(self, name):
        path = self.mkdir(name)
        subprocess.run(['git', 'init', '-q', path], check=True)
        return os.path.realpath(path)

    def row(self, name, session_id, cwd):
        """A live row in the registry (this test process's pid, so /proc/<pid> exists)."""
        with open(os.path.join(self.registry, f'{name}.json'), 'w') as fh:
            json.dump({'pid': os.getpid(), 'sessionId': session_id, 'cwd': cwd, 'name': name}, fh)

    def event(self, listed=(TARGET, SIBLING), **extra):
        now = time.time()
        data = {'id': 't', 'at': now - 300, 'claimed_by': SENDER, 'claimed_at': now - 60, 'done': False,
                'sessions': [{'sessionId': f'local_{c}', 'cliSessionId': c, 'title': c, 'kind': 'hard'}
                             for c in listed]}
        data.update(extra)
        with open(os.path.join(self.switch, 'event.json'), 'w') as fh:
            json.dump(data, fh)

    def send(self, to=TARGET, text=RESUME, mode='default', sid=SENDER):
        payload = {'tool_name': TOOL, 'session_id': sid, 'cwd': self.proj_a, 'permission_mode': mode,
                   'tool_input': {'session_id': to, 'message': text}}
        env = gate_env(self.tmp, CROSS_PROJECT_GATE_STATE=self.state, CROSS_PROJECT_GATE_REGISTRY=self.registry,
                   CROSS_PROJECT_GATE_APP_SESSIONS=self.app, ACCOUNT_SWITCH_STATE=self.switch,
                   ACCOUNT_SWITCH_PROJECTS=self.projects)
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                             env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)['hookSpecificOutput'] if out.stdout.strip() else None

    def log(self):
        try:
            with open(os.path.join(self.state, 'decisions.log')) as fh:
                return fh.read()
        except OSError:
            return ''

    def assertAllowed(self, out):
        self.assertIsNone(out)
        self.assertIn('allow-account-switch', self.log())

    def assertStale(self, out):
        self.assertIsNotNone(out)
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('ya no es tuyo', out['permissionDecisionReason'])
        self.assertIn('deny-stale-account-switch', self.log())
        self.assertNotIn('allow-account-switch', self.log())

    def test_claimant_with_fresh_claim_may_send_to_a_listed_session_of_another_project(self):
        self.event()
        self.assertAllowed(self.send())

    def test_a_watcher_session_listed_by_the_event_may_receive_the_resume_with_its_extra_sentence(self):
        # a supervision session that lost its background watcher is listed with the kind "watcher" and gets the
        # resume text plus one sentence: the marker is what the gate looks at
        self.event(listed=(TARGET,))
        with open(os.path.join(self.switch, 'event.json')) as fh:
            data = json.load(fh)
        data['sessions'][0]['kind'] = 'watcher'
        with open(os.path.join(self.switch, 'event.json'), 'w') as fh:
            json.dump(data, fh)
        text = RESUME + ' Rearma tu vigilante (`supervisor-lock wait`) y sigue donde estabas.'
        self.assertAllowed(self.send(text=text))
        out = self.send(to=SIBLING, text=text)   # not listed: still refused
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('ya no está en la lista', out['permissionDecisionReason'])

    def test_scheduled_task_claim_counts_as_the_claimant(self):
        self.event(claimed_by='scheduled-task:' + SENDER)
        self.assertAllowed(self.send())

    def test_another_claimant_is_denied(self):
        self.event(claimed_by=OTHER)
        self.assertStale(self.send())

    def test_claim_older_than_the_window_is_denied(self):
        self.event(claimed_at=time.time() - 31 * 60)
        out = self.send()
        self.assertStale(out)
        self.assertIn('caducó a las', out['permissionDecisionReason'])

    def test_finished_event_is_denied(self):
        self.event(done=True)
        self.assertStale(self.send())

    def test_missing_event_is_denied(self):
        self.assertStale(self.send())

    def test_recipient_not_listed_is_denied(self):
        self.event(listed=(SIBLING,))
        self.assertStale(self.send())

    def test_stale_resume_to_a_session_of_the_senders_own_project_is_denied(self):
        self.event(claimed_by=OTHER)
        self.assertStale(self.send(to=SIBLING))

    def test_the_denial_is_never_an_ask_in_any_mode(self):
        self.event(claimed_by=OTHER)
        for mode in ('default', 'acceptEdits', 'bypassPermissions'):
            self.assertEqual(self.send(mode=mode)['permissionDecision'], 'deny', mode)

    def test_no_marker_to_another_project_is_gated_as_before(self):
        self.event()
        out = self.send(text='hola')
        self.assertEqual(out['permissionDecision'], 'ask')
        self.assertIn('otro proyecto', out['permissionDecisionReason'])
        out = self.send(text='hola', mode='bypassPermissions', sid=OTHER)
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('AskUserQuestion', out['permissionDecisionReason'])
        self.assertNotIn('stale', self.log())

    def test_the_bypass_denial_tells_supervised_sessions_not_to_open_the_dialog(self):
        self.event()
        out = self.send(text='hola', mode='bypassPermissions', sid=OTHER)
        reason = out['permissionDecisionReason']
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('desatendida, o una supervisada (o la propia supervisora) en la que el desarrollador no ha '
                      'escrito en los últimos 20 minutos', reason)
        self.assertIn('NO lo abre', reason)
        self.assertIn('solo vale para un envío que el desarrollador pidió en esta sesión', reason)
        self.assertIn('ask-queue add', reason)
        self.assertIn('No enviarlo', reason)
        self.assertIn('AskUserQuestion', reason)  # the dialog stays for an attended session
        self.assertNotIn('ask-queue', self.send(text='hola', sid=OTHER)['permissionDecisionReason'])

    # --- only an answered dialog lets the retried send through ----------------------------------------------------

    def sender_transcript(self, *entries):
        path = os.path.join(self.tmp, 'sender.jsonl')
        with open(path, 'w') as fh:
            for e in entries:
                fh.write(json.dumps(e, separators=(',', ':')) + '\n')
        return path

    def ask_use(self, tid='toolu_ask1', ago=5):
        return {'type': 'assistant', 'timestamp': self.stamp(ago),
                'message': {'role': 'assistant', 'content': [
                    {'type': 'tool_use', 'id': tid, 'name': 'AskUserQuestion', 'input': {'questions': []}}]}}

    def ask_result(self, tid='toolu_ask1', ago=4, error=False, text='The user answered: "Enviar"'):
        item = {'type': 'tool_result', 'tool_use_id': tid, 'content': text}
        if error:
            item['is_error'] = True
        return {'type': 'user', 'timestamp': self.stamp(ago), 'message': {'role': 'user', 'content': [item]}}

    def bypass_send(self, transcript):
        payload = {'tool_name': TOOL, 'session_id': OTHER, 'cwd': self.proj_a, 'permission_mode': 'bypassPermissions',
                   'transcript_path': transcript, 'tool_input': {'session_id': TARGET, 'message': 'hola'}}
        env = gate_env(self.tmp, CROSS_PROJECT_GATE_STATE=self.state, CROSS_PROJECT_GATE_REGISTRY=self.registry,
                   CROSS_PROJECT_GATE_APP_SESSIONS=self.app, ACCOUNT_SWITCH_STATE=self.switch,
                   ACCOUNT_SWITCH_PROJECTS=self.projects)
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                             env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)['hookSpecificOutput'] if out.stdout.strip() else None

    def deny_then_retry(self, *makers):
        """First send denied (it records the pending dialog), then the transcript grows by the entries the `makers`
        build (built only now, so their timestamps come after the denial), then the retry."""
        path = self.sender_transcript()
        first = self.bypass_send(path)
        self.assertEqual(first['permissionDecision'], 'deny')
        time.sleep(1.1)  # a whole second later, so the dialog's timestamp is past the denial
        with open(path, 'a') as fh:
            for make in makers:
                fh.write(json.dumps(make(), separators=(',', ':')) + '\n')
        return self.bypass_send(path)

    def test_an_answered_dialog_after_the_denial_lets_the_retry_through(self):
        self.assertIsNone(self.deny_then_retry(lambda: self.ask_use(ago=0), lambda: self.ask_result(ago=0)))
        self.assertIn('allow-after-dialog', self.log())

    def test_a_dialog_a_hook_denied_is_no_yes(self):
        out = self.deny_then_retry(lambda: self.ask_use(ago=0), lambda: self.ask_result(
            ago=0, error=True, text='PreToolUse:AskUserQuestion hook error: Esta sesión la supervisa'))
        self.assertIsNotNone(out, 'the retry passed on a denied dialog')
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertNotIn('allow-after-dialog', self.log())

    def test_a_dialog_without_an_answer_yet_is_no_yes(self):
        out = self.deny_then_retry(lambda: self.ask_use(ago=0))
        self.assertIsNotNone(out, 'the retry passed on an unanswered dialog')
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertNotIn('allow-after-dialog', self.log())

    def test_a_dismissed_dialog_is_no_yes(self):
        out = self.deny_then_retry(lambda: self.ask_use(ago=0), lambda: self.ask_result(
            ago=0, error=True, text="The user doesn't want to proceed"))
        self.assertIsNotNone(out, 'the retry passed on a dismissed dialog')
        self.assertEqual(out['permissionDecision'], 'deny')

    def test_an_answered_dialog_from_before_the_denial_is_no_yes(self):
        out = self.deny_then_retry(lambda: self.ask_use(ago=600), lambda: self.ask_result(ago=599))
        self.assertIsNotNone(out, 'the retry passed on a dialog older than the denial')
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertNotIn('allow-after-dialog', self.log())

    def test_no_marker_to_the_same_project_passes_silently(self):
        self.event(claimed_by=OTHER)
        self.assertIsNone(self.send(to=SIBLING, text='hola'))
        self.assertEqual(self.log(), '')

    # --- a listed session receives the resume at most once per event -------------------------------------------

    def transcript(self, cli_id, *entries):
        with open(os.path.join(self.projects, 'proj', f'{cli_id}.jsonl'), 'w') as fh:
            for e in entries:
                fh.write(json.dumps(e, separators=(',', ':')) + '\n')

    @staticmethod
    def stamp(ago=100):
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - ago)) + '.788Z'

    def peer(self, ago=100):  # idle recipient
        return {'type': 'user', 'isMeta': True, 'timestamp': self.stamp(ago),
                'origin': {'kind': 'peer', 'from': 'local_x', 'body': RESUME},
                'message': {'role': 'user', 'content': f'<cross-session-message from=local_x>\n{RESUME}'}}

    def queued(self, ago=100):  # busy recipient
        return {'type': 'queue-operation', 'operation': 'enqueue', 'timestamp': self.stamp(ago),
                'content': f'<cross-session-message from=local_x >\n{RESUME}'}

    def attached(self, ago=100):
        return {'timestamp': self.stamp(ago),
                'attachment': {'type': 'queued_command', 'prompt': f'<cross-session-message from=local_x>\n{RESUME}'}}

    def assertDuplicate(self, out):
        self.assertIsNotNone(out)
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('ya recibió el aviso de cambio de cuenta a las', out['permissionDecisionReason'])
        self.assertIn('deny-duplicate-account-switch', self.log())
        self.assertNotIn('allow-account-switch', self.log())

    def test_second_send_after_a_delivery_in_the_idle_shape_is_denied(self):
        self.event()
        self.transcript(TARGET, self.peer())
        self.assertDuplicate(self.send())

    def test_the_duplicate_denial_is_never_an_ask_in_any_mode_nor_in_the_same_project(self):
        self.event()
        self.transcript(TARGET, self.peer())
        self.transcript(SIBLING, self.peer())
        for mode in ('default', 'acceptEdits', 'bypassPermissions'):
            self.assertEqual(self.send(mode=mode)['permissionDecision'], 'deny', mode)
            self.assertEqual(self.send(to=SIBLING, mode=mode)['permissionDecision'], 'deny', mode)

    def test_a_queued_or_attached_delivery_is_a_duplicate_too(self):
        self.event()
        self.transcript(TARGET, self.queued())
        self.assertDuplicate(self.send())
        self.transcript(TARGET, self.attached())
        self.assertDuplicate(self.send())

    def test_a_delivery_from_a_previous_switch_does_not_count(self):
        self.event()  # the event began 300 s ago
        self.transcript(TARGET, self.peer(ago=3600))
        self.assertAllowed(self.send())

    def test_quoting_the_marker_in_a_tool_result_or_an_answer_is_not_a_delivery(self):
        self.event()
        quote = f'cat event: «{RESUME}»'
        self.transcript(
            TARGET,
            {'type': 'user', 'timestamp': self.stamp(),
             'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': quote}]}},
            {'type': 'assistant', 'timestamp': self.stamp(),
             'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': quote}]}},
            {'type': 'user', 'timestamp': self.stamp(), 'message': {'role': 'user', 'content': RESUME}})
        self.assertAllowed(self.send())

    def test_no_transcript_at_all_is_allowed(self):
        self.event()
        self.assertAllowed(self.send())

    def test_unparsable_lines_are_skipped(self):
        self.event()
        with open(os.path.join(self.projects, 'proj', f'{TARGET}.jsonl'), 'w') as fh:
            fh.write(f'{MARKER} not json\n')
        self.assertAllowed(self.send())

    def test_a_recipient_addressed_by_its_local_id_is_checked_in_its_cli_transcript(self):
        self.event()
        self.row('target-local', f'local_{TARGET}', self.proj_b)
        self.transcript(TARGET, self.peer())
        self.assertDuplicate(self.send(to=f'local_{TARGET}'))
        os.remove(os.path.join(self.projects, 'proj', f'{TARGET}.jsonl'))
        self.transcript(f'local_{TARGET}', self.peer())  # a file named after the local id is not the transcript
        self.assertAllowed(self.send(to=f'local_{TARGET}'))

    def test_a_stale_sender_to_an_already_resumed_session_gets_the_stale_reason(self):
        self.event(claimed_by=OTHER)
        self.transcript(TARGET, self.peer())
        self.assertStale(self.send())

    def test_the_stale_reason_says_not_to_run_account_switch_done(self):
        self.event(claimed_by=OTHER)
        self.assertIn('account-switch done', self.send()['permissionDecisionReason'])

    # --- the event ages from not_before when the new account had no usage at the switch ---------------------------

    def test_an_old_event_is_stale_without_not_before(self):
        self.event(at=time.time() - 7 * 3600)
        self.assertStale(self.send())

    def test_an_old_event_ages_from_not_before_when_the_usage_came_back_later(self):
        self.event(at=time.time() - 7 * 3600, not_before=time.time() - 600)
        self.assertAllowed(self.send())

    def test_an_event_whose_not_before_is_older_than_the_ttl_is_stale(self):
        self.event(at=time.time() - 9 * 3600, not_before=time.time() - 7 * 3600)
        self.assertStale(self.send())

    def test_a_not_before_still_ahead_does_not_make_the_event_stale(self):
        self.event(not_before=time.time() + 1800)
        self.assertAllowed(self.send())


SUPERVISOR_LOCAL = 'local_aaaaaaaa-5555-4555-8555-555555555555'
SUPERVISOR_CLI = 'aaaaaaaa-6666-4666-8666-666666666666'
RELOAD = '[recarga de skill] Recarga la skill /supervisa-sesiones: ha cambiado.'


class SkillReloadExceptionTest(unittest.TestCase):
    """The global-configuration session tells supervisors to reload the skill without the dialog."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='cross-gate-reload-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        mk = lambda n: (os.makedirs(os.path.join(self.tmp, n)), os.path.join(self.tmp, n))[1]
        self.state, self.registry, self.app = mk('state'), mk('registry'), mk('app')
        self.locks, self.config, self.skills = mk('locks'), mk('config'), mk('skills')
        self.scratch = mk('config/scratch-1')
        self.config_dirs = self.config  # the folders whose sessions count as configuration sessions
        self.updated_globs = os.path.join(self.skills, '*.md')  # the files whose change makes a reload due
        self.proj_a = os.path.realpath(mk('project-a'))
        self.proj_b = os.path.realpath(mk('project-b'))
        for p in (self.proj_a, self.proj_b):
            subprocess.run(['git', 'init', '-q', p], check=True)
        self.skill = os.path.join(self.skills, 'SKILL.md')
        open(self.skill, 'w').close()
        # the supervisor of project-b: a lock naming its local id, its app record and a live registry row
        with open(os.path.join(self.locks, 'project-b-1234.json'), 'w') as fh:
            json.dump({'session_id': SUPERVISOR_LOCAL, 'project': 'project-b', 'checkout': self.proj_b}, fh)
        os.makedirs(os.path.join(self.app, 'acc', 'org'))
        with open(os.path.join(self.app, 'acc', 'org', f'{SUPERVISOR_LOCAL}.json'), 'w') as fh:
            json.dump({'sessionId': SUPERVISOR_LOCAL, 'cliSessionId': SUPERVISOR_CLI, 'cwd': self.proj_b}, fh)
        with open(os.path.join(self.registry, 'sup.json'), 'w') as fh:
            json.dump({'pid': os.getpid(), 'sessionId': SUPERVISOR_CLI, 'cwd': self.proj_b, 'name': 'sup'}, fh)
        with open(os.path.join(self.registry, 'other.json'), 'w') as fh:
            json.dump({'pid': os.getpid(), 'sessionId': TARGET, 'cwd': self.proj_b, 'name': 'other'}, fh)

    def send(self, to=SUPERVISOR_LOCAL, text=RELOAD, cwd=None, mode='bypassPermissions'):
        payload = {'tool_name': TOOL, 'session_id': SENDER, 'cwd': cwd or self.scratch, 'permission_mode': mode,
                   'tool_input': {'session_id': to, 'message': text}}
        env = gate_env(self.tmp, CROSS_PROJECT_GATE_STATE=self.state, CROSS_PROJECT_GATE_REGISTRY=self.registry,
                   CROSS_PROJECT_GATE_APP_SESSIONS=self.app, ACCOUNT_SWITCH_STATE=os.path.join(self.tmp, 'none'),
                   ACCOUNT_SWITCH_PROJECTS=os.path.join(self.tmp, 'none'), CROSS_PROJECT_GATE_CONFIG_DIRS=self.config_dirs,
                   CROSS_PROJECT_GATE_LOCKS=self.locks,
                   CROSS_PROJECT_GATE_REVIVE=os.path.join(self.tmp, 'revive.json'),
                   CROSS_PROJECT_GATE_UPDATED_GLOBS=self.updated_globs,
                   )
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                             env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)['hookSpecificOutput'] if out.stdout.strip() else None

    def log(self):
        try:
            with open(os.path.join(self.state, 'decisions.log')) as fh:
                return fh.read()
        except OSError:
            return ''

    def assertGated(self, out, because):
        self.assertIsNotNone(out)
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('otro proyecto', out['permissionDecisionReason'])
        self.assertIn('no aplica: ' + because, out['permissionDecisionReason'])
        self.assertNotIn('allow-skill-reload', self.log())

    def test_config_session_reloads_a_supervisor_by_local_id_without_dialog(self):
        self.assertIsNone(self.send())
        self.assertIn('allow-skill-reload', self.log())
        self.assertIn('project-b', self.log())

    def test_the_supervisor_may_be_named_by_its_cli_session_id(self):
        self.assertIsNone(self.send(to=SUPERVISOR_CLI))
        self.assertIn('allow-skill-reload', self.log())

    def test_a_project_session_with_the_marker_is_gated_as_before(self):
        self.assertGated(self.send(cwd=self.proj_a), 'solo la manda una sesión de la configuración global')

    def test_the_refusal_names_the_configuration_folders_not_the_config_key(self):
        out = self.send(text=RELOAD, cwd=self.proj_a)
        self.assertGated(out, f'solo la manda una sesión de la configuración global, es decir, una que empezó o '
                              f'trabaja dentro de «{self.config}»')
        self.assertNotIn('config_session_dirs', out['permissionDecisionReason'])
        other = os.path.join(self.tmp, 'second-config')
        self.config_dirs = os.pathsep.join([self.config, other])
        out = self.send(text=RELOAD, cwd=self.proj_a)
        self.assertGated(out, f'solo la manda una sesión de la configuración global, es decir, una que empezó o '
                              f'trabaja dentro de alguna de estas carpetas: «{self.config}», «{other}»')
        self.assertNotIn('config_session_dirs', out['permissionDecisionReason'])

    def sender_record(self, origin, cwd):
        with open(os.path.join(self.app, 'acc', 'org', 'local_sender.json'), 'w') as fh:
            json.dump({'sessionId': 'local_sender', 'cliSessionId': SENDER, 'originCwd': origin, 'cwd': cwd}, fh)

    def test_config_session_working_in_another_folder_is_judged_by_where_it_started(self):
        # its current folder follows it when it works elsewhere, so the folder it started in counts too
        self.sender_record(self.scratch, self.proj_a)
        self.assertIsNone(self.send(cwd=self.proj_a))
        self.assertIn('allow-skill-reload', self.log())

    def test_a_project_session_that_started_in_its_project_stays_gated(self):
        self.sender_record(self.proj_a, self.proj_a)
        self.assertGated(self.send(cwd=self.proj_a), 'solo la manda una sesión de la configuración global')

    def test_a_recipient_without_a_supervisor_lock_is_gated_as_before(self):
        self.assertGated(self.send(to=TARGET), f'«{TARGET}» no es una supervisora')

    def lock(self, **extra):
        data = {'session_id': SUPERVISOR_LOCAL, 'project': 'project-b', 'checkout': self.proj_b}
        data.update(extra)
        with open(os.path.join(self.locks, 'project-b-1234.json'), 'w') as fh:
            json.dump(data, fh)

    def test_a_supervisor_that_already_read_the_latest_change_is_gated_as_before(self):
        self.lock(skill_seen=os.stat(self.skill).st_mtime)
        self.assertGated(self.send(), 'ya recargó la skill después del último cambio')

    def test_a_change_newer_than_the_version_she_read_passes_even_days_later(self):
        old = time.time() - 3 * 86400
        os.utime(self.skill, (old, old))
        self.lock(skill_seen=old - 3600)
        self.assertIsNone(self.send())
        self.assertIn('allow-skill-reload', self.log())

    def watched(self, name, mtime):
        path = os.path.join(self.skills, name)
        open(path, 'w').close()
        os.utime(path, (mtime, mtime))

    def test_a_change_older_than_the_reload_is_not_new_although_the_skill_is_older(self):
        # the skill file is older than another watched file (a rule, the supervisor-lock code), but she reloaded after
        # that change: `skill_seen` alone (the skill's mtime) would let a reload through after every reload
        now = time.time()
        os.utime(self.skill, (now - 7200, now - 7200))
        self.watched('rule.md', now - 600)
        self.lock(skill_seen=now - 7200, skill_seen_at=now - 60)
        self.assertGated(self.send(text=RELOAD), 'ya recargó la skill después del último cambio')

    def test_a_change_after_the_reload_passes(self):
        now = time.time()
        os.utime(self.skill, (now - 7200, now - 7200))
        self.watched('rule.md', now - 60)
        self.lock(skill_seen=now - 7200, skill_seen_at=now - 600)
        self.assertIsNone(self.send(text=RELOAD))
        self.assertIn('allow-skill-reload', self.log())

    def test_a_change_to_the_supervisor_lock_package_makes_a_reload_due(self):
        self.updated_globs = ''  # the hook's own list, under the throwaway HOME
        package = os.path.join(self.tmp, 'home', '.claude', 'scripts', 'lib', 'supervisor')
        os.makedirs(package, exist_ok=True)
        open(os.path.join(package, 'cli.py'), 'w').close()
        now = time.time()
        self.lock(skill_seen=now - 7200, skill_seen_at=now - 600)
        self.assertIsNone(self.send(text=RELOAD))
        self.assertIn('allow-skill-reload', self.log())

    def test_a_supervisor_that_never_read_the_skill_may_be_told_to(self):
        self.lock()  # no skill_seen
        self.assertIsNone(self.send())

    def test_without_the_marker_it_is_gated_as_before(self):
        out = self.send(text='Recarga la skill, por favor.')
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertNotIn('no aplica', out['permissionDecisionReason'])
        self.assertNotIn('allow-skill-reload', self.log())

    def test_outside_bypass_a_failed_marker_still_asks(self):
        out = self.send(cwd=self.proj_a, mode='default')
        self.assertEqual(out['permissionDecision'], 'ask')
        self.assertIn('no aplica', out['permissionDecisionReason'])


REVIVE = '[reanimar supervisora] Tu proceso murió hacia las 10:00 y nadie te despertó.'


class SupervisorReviveExceptionTest(SkillReloadExceptionTest):
    """A scheduled task wakes a supervisor whose process died, without the dialog, only
    for a target `supervisor-lock revive --plan` named in the last half hour."""

    def setUp(self):
        super().setUp()
        self.revive = os.path.join(self.tmp, 'revive.json')
        self.lock(skill_seen=os.stat(self.skill).st_mtime)  # no reload due: only the revive exception can pass

    def plan(self, key='project-b-1234', session=SUPERVISOR_LOCAL, ago=60):
        with open(self.revive, 'w') as fh:
            json.dump({key: {'session': session, 'incident': 'x', 'attempts': 1, 'planned_at': time.time() - ago}}, fh)

    def send(self, to=SUPERVISOR_LOCAL, text=REVIVE, cwd=None, mode='bypassPermissions'):
        return super().send(to=to, text=text, cwd=cwd, mode=mode)

    def assertRefused(self, out, because):
        self.assertIsNotNone(out)
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('no aplica: ' + because, out['permissionDecisionReason'])
        self.assertNotIn('allow-supervisor-revive', self.log())

    def test_a_target_the_plan_named_passes_without_dialog(self):
        self.plan()
        self.assertIsNone(self.send())
        self.assertIn('allow-supervisor-revive', self.log())

    def test_also_by_its_cli_session_id(self):
        self.plan()
        self.assertIsNone(self.send(to=SUPERVISOR_CLI))

    def test_without_a_plan_it_is_gated(self):
        self.assertRefused(self.send(), '`supervisor-lock revive` no la ha señalado')

    def test_a_plan_older_than_half_an_hour_is_gated(self):
        self.plan(ago=31 * 60)
        self.assertRefused(self.send(), '`supervisor-lock revive` no la ha señalado')

    def test_a_plan_for_another_owner_of_the_lock_is_gated(self):
        self.plan(session='local_00000000-0000-0000-0000-000000000000')
        self.assertRefused(self.send(), '`supervisor-lock revive` no la ha señalado')

    def test_a_project_session_cannot_use_the_marker(self):
        self.plan()
        self.assertRefused(self.send(cwd=self.proj_a), 'solo la manda la tarea «Reanimar supervisoras»')

    def test_a_session_without_a_lock_is_gated(self):
        self.plan()
        self.assertRefused(self.send(to=TARGET), f'«{TARGET}» no es una supervisora')

    # the inherited reload tests do not apply to this marker
    test_config_session_reloads_a_supervisor_by_local_id_without_dialog = None
    test_the_supervisor_may_be_named_by_its_cli_session_id = None
    test_a_project_session_with_the_marker_is_gated_as_before = None
    test_config_session_working_in_another_folder_is_judged_by_where_it_started = None
    test_a_project_session_that_started_in_its_project_stays_gated = None
    test_a_recipient_without_a_supervisor_lock_is_gated_as_before = None
    test_a_supervisor_that_already_read_the_latest_change_is_gated_as_before = None
    test_a_change_older_than_the_reload_is_not_new_although_the_skill_is_older = None
    test_a_change_after_the_reload_passes = None
    test_a_change_to_the_supervisor_lock_package_makes_a_reload_due = None
    test_a_change_newer_than_the_version_she_read_passes_even_days_later = None
    test_a_supervisor_that_never_read_the_skill_may_be_told_to = None
    test_without_the_marker_it_is_gated_as_before = None
    test_outside_bypass_a_failed_marker_still_asks = None


class DefaultsTest(unittest.TestCase):
    """What a fresh install, or a broken config, lets through: nothing to another project."""

    MARKERS = ('[cambio de cuenta]', '[reanudar proyecto]', '[recarga de skill]', '[reanimar supervisora]')

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='cross-gate-defaults-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, 'home')
        self.sender = os.path.join(self.home, '.claude')  # the folder a configuration session would work in
        self.other = os.path.join(self.tmp, 'project-b')
        registry = os.path.join(self.sender, 'sessions')
        for path in (registry, self.other):
            os.makedirs(path)
        with open(os.path.join(registry, 't.json'), 'w') as fh:
            json.dump({'pid': os.getpid(), 'sessionId': TARGET, 'cwd': self.other, 'name': 't'}, fh)
        # what would open each exception if it were on
        for rel, data in (('state/account-switch/event.json',
                           {'at': time.time(), 'claimed_by': SENDER, 'claimed_at': time.time(),
                            'sessions': [{'cliSessionId': TARGET}]}),
                          ('supervisor/locks/b.json', {'session_id': TARGET, 'project': 'project-b'}),
                          ('supervisor/revive.json', {'b': {'session': TARGET, 'planned_at': time.time()}})):
            path = os.path.join(self.sender, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as fh:
                json.dump(data, fh)

    def decide(self, text, payload=None, **config):
        payload = payload if payload is not None else {
            'tool_name': TOOL, 'session_id': SENDER, 'cwd': self.sender, 'permission_mode': 'bypassPermissions',
            'tool_input': {'session_id': TARGET, 'message': text}}
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                             env=gate_env(self.tmp, **config), timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)['hookSpecificOutput']['permissionDecision'] if out.stdout.strip() else None

    def test_shipped_defaults_allow_no_marker(self):
        shipped = json.loads((REPO_ROOT / 'global/config/supervision.json').read_text())
        self.assertEqual(shipped['message_exceptions'], [])
        self.assertEqual(shipped['config_session_dirs'], [])
        for marker in self.MARKERS:
            self.assertEqual(self.decide(f'{marker} go', values=shipped), 'deny', marker)

    def test_a_broken_or_mistyped_config_allows_no_marker(self):
        for raw in ('{broken', '[]', '{"message_exceptions": "account_switch"}', '{"message_exceptions": [1]}'):
            for marker in self.MARKERS:
                self.assertEqual(self.decide(f'{marker} go', raw=raw), 'deny', (raw, marker))

    def test_an_empty_marker_does_not_turn_every_message_into_an_exception(self):
        values = {'message_exceptions': ['account_switch'], 'account_switch_marker': ''}
        self.assertEqual(self.decide('hello', values=values), 'deny')

    def test_an_exception_switched_on_opens_only_itself(self):
        values = {'message_exceptions': ['account_switch']}
        self.assertEqual(self.decide('[reanimar supervisora] go', values=values), 'deny')
        self.assertIsNone(self.decide('[cambio de cuenta] go', values=values))

    def test_configuration_exceptions_also_need_their_folders(self):
        values = {'message_exceptions': ['supervisor_revive']}
        self.assertEqual(self.decide('[reanimar supervisora] go', values=values), 'deny')
        self.assertIsNone(self.decide('[reanimar supervisora] go',
                                      values=dict(values, config_session_dirs=['~/.claude'])))

    def test_with_no_configuration_folder_the_refusal_says_none_is_declared(self):
        payload = {'tool_name': TOOL, 'session_id': SENDER, 'cwd': self.sender, 'permission_mode': 'bypassPermissions',
                   'tool_input': {'session_id': TARGET, 'message': '[recarga de skill] go'}}
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                             env=gate_env(self.tmp, values={'message_exceptions': ['skill_reload']}), timeout=30)
        reason = json.loads(out.stdout)['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn('no aplica: solo la manda una sesión de la configuración global, y no hay ninguna carpeta '
                      'declarada para eso: la lista config_session_dirs de la configuración de supervisión está vacía',
                      reason)

    def test_a_payload_that_is_not_an_object_fails_open(self):
        self.assertIsNone(self.decide('', payload=['x']))


if __name__ == '__main__':
    unittest.main()
