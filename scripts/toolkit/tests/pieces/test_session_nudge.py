"""Tests for global/scripts/session-nudge (wake stopped desktop-app sessions through their unix socket).

Run:  python3 -m unittest scripts.toolkit.tests.pieces.test_session_nudge -v   (from the repository root)

The script is loaded as a module and every path it uses (registry, app records, transcripts, state, the toolkit
config) is pointed at a temp dir. Sessions are fake: a registry entry for this very process (so it counts as alive)
with its own key file and a unix socket served by a thread of the test, which records what a real session would
receive. No real session is ever contacted. SESSION_NUDGE_SCRIPT lets the suite run against another copy.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = os.environ.get('SESSION_NUDGE_SCRIPT') or str(REPO_ROOT / 'global/scripts/session-nudge')


def load_module():
    loader = importlib.machinery.SourceFileLoader('session_nudge_script', SCRIPT)
    spec = importlib.util.spec_from_loader('session_nudge_script', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


N = load_module()
PARIS = ZoneInfo('Europe/Paris')


def iso(epoch):
    return datetime.fromtimestamp(epoch, ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%S.000Z')


class FakeSocket:
    """A session inbox: accepts connections and keeps the json lines each one sent."""

    def __init__(self, path, echo_to=None):
        self.path = path
        self.echo_to = echo_to  # transcript the «session» writes each received message to (None: a recipient that holds it)
        self.received = []  # one list of decoded lines per connection
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(8)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            conn.settimeout(2)
            data = b''
            try:
                while data.count(b'\n') < 2:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            except OSError:
                pass
            conn.close()
            lines = [json.loads(line) for line in data.split(b'\n') if line.strip()]
            if self.echo_to and len(lines) > 1:  # a record type the detection ignores, so it never changes what is stuck
                try:
                    with open(self.echo_to, 'a') as fh:
                        fh.write(json.dumps({'type': 'queue-operation', 'content': lines[1]['message']['content']}) + '\n')
                except OSError:  # the test already removed its temp dir
                    pass
            self.received.append(lines)

    def close(self):
        self.server.close()


class NudgeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='sn-')  # short: unix socket paths are limited to 108 bytes
        self.dirs = {name: os.path.join(self.tmp, name) for name in ('sessions', 'projects', 'app', 'home')}
        for path in self.dirs.values():
            os.makedirs(path)
        self.saved = {k: os.environ.get(k) for k in (
            'SESSION_NUDGE_HOME', 'SESSION_NUDGE_SESSIONS_DIR', 'SESSION_NUDGE_APP_GLOB', 'SESSION_NUDGE_PROJECTS_DIR',
            'SESSION_NUDGE_HANDOFF_GUARD', 'SESSION_NUDGE_ASK_QUEUE', 'SESSION_NUDGE_VERIFY_S',
            'SESSION_NUDGE_ACCOUNT_SWITCH', 'PROJECT_PAUSE_BIN', 'CLAUDE_TOOLKIT_CONFIG_DIR')}
        os.environ['SESSION_NUDGE_HOME'] = self.dirs['home']
        os.environ['SESSION_NUDGE_SESSIONS_DIR'] = self.dirs['sessions']
        os.environ['SESSION_NUDGE_APP_GLOB'] = os.path.join(self.dirs['app'], '*', '*', 'local_*.json')
        os.environ['SESSION_NUDGE_PROJECTS_DIR'] = self.dirs['projects']
        os.environ['SESSION_NUDGE_HANDOFF_GUARD'] = os.path.join(self.tmp, 'no-handoff-guard')  # absent unless a test adds one
        os.environ['SESSION_NUDGE_ASK_QUEUE'] = os.path.join(self.tmp, 'no-ask-queue')
        os.environ['SESSION_NUDGE_VERIFY_S'] = '2'  # `stuck --send` verify window; tests of a held nudge shorten it
        # the real account-switch would ask the real account's usage: absent unless a test adds a fake one
        os.environ['SESSION_NUDGE_ACCOUNT_SWITCH'] = os.path.join(self.tmp, 'no-account-switch')
        # hermetic: neither the machine's paused projects nor its toolkit config count (a test writes its own config)
        os.environ['PROJECT_PAUSE_BIN'] = os.path.join(self.tmp, 'no-project-pause')
        self.config = os.path.join(self.tmp, 'toolkit-config')
        os.makedirs(self.config)
        os.environ['CLAUDE_TOOLKIT_CONFIG_DIR'] = self.config
        os.makedirs(os.path.join(self.dirs['app'], 'acct', 'org'))
        self.sockets = []
        self.count = 0

    def tearDown(self):
        for sock in self.sockets:
            sock.close()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, piece, data):
        with open(os.path.join(self.config, piece + '.json'), 'w') as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    # ------------------------------------------------------------ builders
    def session(self, status='waiting', records=(), name='Trabajo', bypass=True, archived=False,
                token='tok-1', key_proc='proc-1', with_socket=True, pid=None, echo=True):
        """Create one live fake session; records are (type, extra dict, content list, epoch) tuples."""
        self.count += 1
        cli = f'00000000-0000-0000-0000-{self.count:012d}'
        local = f'local_{cli}'
        pid = pid or os.getpid()
        base = os.path.join(self.dirs['sessions'], f'{pid}{self.count}')  # distinct file names, same live pid
        sock_path = os.path.join(self.tmp, f's{self.count}.sock')
        reg = {'pid': pid, 'sessionId': cli, 'cwd': '/work/proj', 'procStart': 'proc-1', 'entrypoint': 'claude-desktop',
               'hostSessionId': local, 'messagingSocketPath': sock_path, 'name': name, 'status': status}
        with open(base + '.json', 'w') as fh:
            json.dump(reg, fh)
        with open(f'{base}.abc.key', 'w') as fh:
            json.dump({'peerToken': token, 'procStart': key_proc}, fh)
        with open(os.path.join(self.dirs['app'], 'acct', 'org', local + '.json'), 'w') as fh:
            json.dump({'sessionId': local, 'cliSessionId': cli, 'isArchived': archived,
                       'permissionMode': 'bypassPermissions' if bypass else 'default', 'lastActivityAt': 1}, fh)
        proj = os.path.join(self.dirs['projects'], N.re.sub(r'[^A-Za-z0-9-]', '-', '/work/proj'))
        os.makedirs(proj, exist_ok=True)
        transcript = os.path.join(proj, cli + '.jsonl')
        with open(transcript, 'w') as fh:
            for kind, extra, content, epoch in records:
                rec = {'type': kind, 'timestamp': iso(epoch), 'message': {'role': kind, 'content': content}}
                rec.update(extra)
                fh.write(json.dumps(rec) + '\n')
        inbox = None
        if with_socket:
            inbox = FakeSocket(sock_path, transcript if echo else None)
            self.sockets.append(inbox)
        return {'cli': cli, 'local': local, 'inbox': inbox, 'reg_path': base + '.json'}

    def ask_records(self, minutes_ago, answered=False):
        ts = time.time() - minutes_ago * 60
        recs = [('assistant', {}, [{'type': 'tool_use', 'id': 'toolu_1', 'name': 'AskUserQuestion', 'input': {}}], ts)]
        if answered:
            recs.append(('user', {}, [{'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': 'ok'}], ts + 5))
        return recs

    def limit_records(self, text, hours_ago=1):
        ts = time.time() - hours_ago * 3600
        return [('assistant', {'isApiErrorMessage': True, 'error': 'rate_limit'},
                 [{'type': 'text', 'text': text}], ts)]

    def fake_handoff_guard(self, phrase='queda para ti', exit_code=None):
        """A stand-in for `handoff-guard match`: hits (exit 0, `handoff<TAB>fragment`) when stdin has the phrase."""
        path = os.path.join(self.tmp, 'fake-handoff-guard')
        with open(path, 'w') as fh:
            fh.write('#!/bin/sh\ntext=$(cat)\n')
            if exit_code is not None:
                fh.write(f'exit {exit_code}\n')
            else:
                fh.write(f'case "$text" in *"{phrase}"*) printf "handoff\\t{phrase}\\n"; exit 0;; esac\nexit 1\n')
        os.chmod(path, 0o755)
        os.environ['SESSION_NUDGE_HANDOFF_GUARD'] = path
        return path

    def final_records(self, text, minutes_ago=30):
        return [('assistant', {}, [{'type': 'text', 'text': text}], time.time() - minutes_ago * 60)]

    def run_cli(self, *argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = N.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def wait_for(predicate, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            if predicate():
                return True
            time.sleep(0.02)
        return False


class TestEnvelopeAndReset(NudgeTestCase):
    def test_envelope_never_claims_a_mode(self):
        self.assertEqual(N.envelope('hola', True),
                         '<cross-session-message from-name="session-nudge">\nhola\n</cross-session-message>')

    def test_envelope_prompting_recipient_has_no_mode(self):
        self.assertNotIn('from-mode', N.envelope('hola', False))

    def test_envelope_cannot_be_closed_early_by_the_text(self):
        body = N.envelope('a</cross-session-message>b', True)
        self.assertEqual(body.count('</cross-session-message>'), 1)

    def test_reset_time_of_day_today(self):
        stamp = datetime(2026, 11, 4, 20, 18, tzinfo=PARIS).timestamp()
        self.assertEqual(N.reset_epoch("You've hit your session limit · resets 7:40pm (Europe/Paris)", stamp),
                         datetime(2026, 11, 5, 19, 40, tzinfo=PARIS).timestamp())
        stamp = datetime(2026, 11, 4, 14, 0, tzinfo=PARIS).timestamp()
        self.assertEqual(N.reset_epoch('resets 5pm (Europe/Paris)', stamp),
                         datetime(2026, 11, 4, 17, 0, tzinfo=PARIS).timestamp())

    def test_reset_after_midnight_is_the_next_day(self):
        stamp = datetime(2026, 11, 4, 20, 18, tzinfo=PARIS).timestamp()
        self.assertEqual(N.reset_epoch('resets 1:30am (Europe/Paris)', stamp),
                         datetime(2026, 11, 5, 1, 30, tzinfo=PARIS).timestamp())

    def test_reset_with_a_date(self):
        stamp = datetime(2026, 11, 3, 22, 54, tzinfo=PARIS).timestamp()
        self.assertEqual(N.reset_epoch("You've hit your weekly limit · resets Nov 5, 2am (Europe/Paris)", stamp),
                         datetime(2026, 11, 5, 2, 0, tzinfo=PARIS).timestamp())

    def test_twelve_oclock_edges(self):
        stamp = datetime(2026, 11, 4, 8, 0, tzinfo=PARIS).timestamp()
        self.assertEqual(N.reset_epoch('resets 12pm (Europe/Paris)', stamp),
                         datetime(2026, 11, 4, 12, 0, tzinfo=PARIS).timestamp())
        self.assertEqual(N.reset_epoch('resets 12am (Europe/Paris)', stamp),
                         datetime(2026, 11, 5, 0, 0, tzinfo=PARIS).timestamp())

    def test_unparseable_reset_is_none(self):
        self.assertIsNone(N.reset_epoch('Something else happened', 0))
        self.assertIsNone(N.reset_epoch('resets 5pm (Nowhere/Land)', 0))
        self.assertIsNone(N.reset_epoch('resets Foo 5, 2am (Europe/Paris)', 0))


class TestSend(NudgeTestCase):
    def test_send_authenticates_and_delivers_to_a_bypass_session_without_a_mode(self):
        s = self.session(bypass=True)
        code, out, _ = self.run_cli('send', s['cli'], '--text', 'ping')
        self.assertEqual(code, 0)
        self.assertIn('SENT', out)
        self.assertTrue(self.wait_for(lambda: s['inbox'].received))
        auth, msg = s['inbox'].received[0]
        self.assertEqual(auth, {'type': 'auth', 'token': 'tok-1'})
        self.assertEqual(msg['type'], 'user')
        self.assertEqual(msg['priority'], 'next')
        self.assertTrue(msg['msg_id'].startswith('nudge-'))
        self.assertEqual(msg['message']['role'], 'user')
        self.assertEqual(msg['message']['content'], N.envelope('ping', True))

    def test_send_to_a_prompting_session_omits_the_mode(self):
        s = self.session(bypass=False)
        self.run_cli('send', s['cli'], '--text', 'ping')
        self.assertTrue(self.wait_for(lambda: s['inbox'].received))
        self.assertNotIn('from-mode', s['inbox'].received[0][1]['message']['content'])

    def test_target_can_be_the_local_id(self):
        s = self.session()
        code, out, _ = self.run_cli('send', s['local'], '--text', 'ping')
        self.assertEqual(code, 0)
        self.assertIn(s['cli'], out)

    def test_unknown_target_exits_2_and_connects_nowhere(self):
        s = self.session()
        code, _, err = self.run_cli('send', 'nope', '--text', 'ping')
        self.assertEqual(code, 2)
        self.assertIn('no live session', err)
        time.sleep(0.1)
        self.assertEqual(s['inbox'].received, [])

    def test_dead_process_is_not_a_target(self):
        s = self.session(pid=2 ** 22 + 12345)  # above pid_max: no such process
        code, _, _ = self.run_cli('send', s['cli'], '--text', 'ping')
        self.assertEqual(code, 2)

    def test_key_of_another_process_is_refused(self):
        s = self.session(key_proc='some-other-process')
        code, out, _ = self.run_cli('send', s['cli'], '--text', 'ping')
        self.assertEqual(code, 1)
        self.assertIn('NOT-SENT', out)
        self.assertIn('no peer token', out)
        time.sleep(0.1)
        self.assertEqual(s['inbox'].received, [])

    def test_missing_socket_is_reported_not_raised(self):
        s = self.session(with_socket=False)
        code, out, _ = self.run_cli('send', s['cli'], '--text', 'ping')
        self.assertEqual(code, 1)
        self.assertIn('no messaging socket', out)

    def test_dry_run_prints_the_envelope_without_connecting(self):
        s = self.session()
        code, out, _ = self.run_cli('send', s['cli'], '--text', 'ping', '--dry-run')
        self.assertEqual(code, 0)
        self.assertIn('DRY-RUN', out)
        self.assertNotIn('from-mode', out)
        time.sleep(0.1)
        self.assertEqual(s['inbox'].received, [])

    def test_verify_reports_a_message_seen_in_the_transcript(self):
        s = self.session()
        transcript = N.transcript_path({'sessionId': s['cli'], 'cwd': '/work/proj'})

        def echo():  # what the real session does: write the received message into its transcript
            self.wait_for(lambda: s['inbox'].received)
            content = s['inbox'].received[0][1]['message']['content']
            with open(transcript, 'a') as fh:
                fh.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': content}}) + '\n')
        threading.Thread(target=echo, daemon=True).start()
        code, out, _ = self.run_cli('send', s['cli'], '--text', 'ping', '--verify', '5')
        self.assertEqual(code, 0)
        self.assertIn('delivered (seen in the transcript)', out)

    def test_verify_without_an_echo_says_so(self):
        s = self.session(echo=False)
        code, out, _ = self.run_cli('send', s['cli'], '--text', 'ping', '--verify', '1')
        self.assertEqual(code, 0)
        self.assertIn('not seen in the transcript yet', out)


class TestStuckDetection(NudgeTestCase):
    def kinds(self, *extra):
        code, out, _ = self.run_cli('stuck', '--json', *extra)
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_old_unanswered_question_is_ready(self):
        s = self.session(records=self.ask_records(20))
        rows = self.kinds()
        self.assertEqual([(r['kind'], r['session'], r['ready']) for r in rows], [('QUESTION', s['cli'], True)])

    def test_recent_question_is_listed_but_not_ready(self):
        self.session(records=self.ask_records(5))
        self.assertFalse(self.kinds()[0]['ready'])

    def test_min_minutes_is_honoured(self):
        self.session(records=self.ask_records(5))
        self.assertTrue(self.kinds('--min-minutes', '3')[0]['ready'])

    def test_answered_question_is_not_stuck(self):
        self.session(records=self.ask_records(60, answered=True))
        self.assertEqual(self.kinds(), [])

    def test_question_needs_the_waiting_status(self):
        self.session(status='busy', records=self.ask_records(60))
        self.assertEqual(self.kinds(), [])

    def test_question_mailbox_is_skipped(self):
        self.session(records=self.ask_records(60), name='Preguntas de la supervisión de demo')
        self.assertEqual(self.kinds(), [])

    def test_archived_session_is_skipped(self):
        self.session(records=self.ask_records(60), archived=True)
        self.assertEqual(self.kinds(), [])

    def test_other_human_tools_are_not_questions(self):
        ts = time.time() - 3600
        self.session(records=[('assistant', {}, [{'type': 'tool_use', 'id': 't', 'name': 'mcp__claude-in-chrome__navigate',
                                                  'input': {}}], ts)])
        self.assertEqual(self.kinds(), [])

    def test_limit_stop_after_the_reset_is_ready(self):
        # stopped 3 h ago; a reset named 1 h ago is in the past whatever the clock says
        past = datetime.fromtimestamp(time.time() - 3600, PARIS)
        text = f"You've hit your session limit · resets {past.strftime('%-I:%M%p').lower()} (Europe/Paris)"
        s = self.session(status='idle', records=self.limit_records(text, hours_ago=3))
        rows = self.kinds()
        self.assertEqual([(r['kind'], r['session'], r['ready']) for r in rows], [('LIMIT', s['cli'], True)])

    def test_limit_stop_before_the_reset_waits(self):
        future = datetime.fromtimestamp(time.time() + 2 * 3600, PARIS)
        text = f"You've hit your session limit · resets {future.strftime('%-I:%M%p').lower()} (Europe/Paris)"
        self.session(status='idle', records=self.limit_records(text, hours_ago=0.1))
        self.assertFalse(self.kinds()[0]['ready'])

    def test_limit_with_unknown_reset_is_listed_but_never_ready(self):
        self.session(status='idle', records=self.limit_records("You've hit your limit", hours_ago=10))
        self.assertFalse(self.kinds()[0]['ready'])

    def test_limit_stop_older_than_three_days_is_not_nudged(self):
        self.session(status='idle', records=self.limit_records('resets 5pm (Europe/Paris)', hours_ago=24 * 4))
        self.assertFalse(self.kinds()[0]['ready'])

    def test_limit_only_counts_when_it_is_the_newest_record(self):
        ts = time.time() - 7200
        recs = self.limit_records('resets 5pm (Europe/Paris)', hours_ago=5) + [
            ('user', {}, 'reanuda', ts), ('assistant', {}, [{'type': 'text', 'text': 'vale'}], ts + 1)]
        self.session(status='idle', records=recs)
        self.assertEqual(self.kinds(), [])

    def test_plain_api_error_is_not_a_limit(self):
        # since T2 (2026-11-10) it is an APIERR retry candidate, but never a LIMIT
        ts = time.time() - 36000
        self.session(status='idle', records=[('assistant', {'isApiErrorMessage': True, 'error': 'unknown'},
                                              [{'type': 'text', 'text': 'API Error: Connection error.'}], ts)])
        self.assertEqual([r['kind'] for r in self.kinds()], ['APIERR'])

    def test_listing_never_sends(self):
        s = self.session(records=self.ask_records(60))
        self.run_cli('stuck')
        time.sleep(0.1)
        self.assertEqual(s['inbox'].received, [])
        self.assertFalse(os.path.exists(os.path.join(self.dirs['home'], 'state.json')))


class TestStuckSending(NudgeTestCase):
    def sent_count(self, s):
        time.sleep(0.15)
        return len(s['inbox'].received)

    def test_question_is_nudged_once_then_not_again_within_two_hours(self):
        s = self.session(records=self.ask_records(30))
        code, out, _ = self.run_cli('stuck', '--send')
        self.assertEqual(code, 0)
        self.assertIn('nudged 1 session(s)', out)
        self.assertEqual(self.sent_count(s), 1)
        content = s['inbox'].received[0][1]['message']['content']
        self.assertIn('30 min', content)
        self.assertIn('no autoriza commit, push, merge ni despliegue', content)
        _, out, _ = self.run_cli('stuck', '--send')
        self.assertIn('nudged 0 session(s)', out)
        self.assertEqual(self.sent_count(s), 1)

    def test_question_is_nudged_again_after_two_hours(self):
        s = self.session(records=self.ask_records(30))
        self.run_cli('stuck', '--send')
        state_path = os.path.join(self.dirs['home'], 'state.json')
        with open(state_path) as fh:
            state = json.load(fh)
        state = {k: v - N.QUESTION_EVERY - 1 for k, v in state.items()}
        with open(state_path, 'w') as fh:
            json.dump(state, fh)
        self.run_cli('stuck', '--send')
        self.assertEqual(self.sent_count(s), 2)

    def test_recent_question_is_not_nudged(self):
        s = self.session(records=self.ask_records(5))
        self.run_cli('stuck', '--send')
        self.assertEqual(self.sent_count(s), 0)

    def test_limit_nudge_goes_once_per_limit_event(self):
        past = datetime.fromtimestamp(time.time() - 3600, PARIS)
        text = f"You've hit your session limit · resets {past.strftime('%-I:%M%p').lower()} (Europe/Paris)"
        s = self.session(status='idle', records=self.limit_records(text, hours_ago=3))
        self.run_cli('stuck', '--send')
        self.assertEqual(self.sent_count(s), 1)
        self.assertIn('Se renovo el uso', s['inbox'].received[0][1]['message']['content'])
        state_path = os.path.join(self.dirs['home'], 'state.json')
        with open(state_path) as fh:
            state = json.load(fh)
        with open(state_path, 'w') as fh:  # even days later, the same limit event is never nudged twice
            json.dump({k: v - 5 * 86400 for k, v in state.items()}, fh)
        self.run_cli('stuck', '--send')
        self.assertEqual(self.sent_count(s), 1)

    def test_at_most_max_sessions_per_run(self):
        sessions = [self.session(records=self.ask_records(30)) for _ in range(8)]
        _, out, _ = self.run_cli('stuck', '--send')
        self.assertIn('nudged 6 session(s)', out)
        time.sleep(0.2)
        self.assertEqual(sum(len(s['inbox'].received) for s in sessions), 6)
        _, out, _ = self.run_cli('stuck', '--send')  # the next run takes the other two
        self.assertIn('nudged 2 session(s)', out)
        time.sleep(0.2)
        self.assertEqual(sum(len(s['inbox'].received) for s in sessions), 8)

    def test_failed_delivery_is_retried_next_run(self):
        s = self.session(records=self.ask_records(30), with_socket=False)
        _, out, _ = self.run_cli('stuck', '--send')
        self.assertIn('nudged 0 session(s)', out)
        self.assertFalse(os.path.exists(os.path.join(self.dirs['home'], 'state.json')))
        with open(s['reg_path']) as fh:
            sock_path = json.load(fh)['messagingSocketPath']
        s['inbox'] = FakeSocket(sock_path, N.transcript_path({'sessionId': s['cli'], 'cwd': '/work/proj'}))
        self.sockets.append(s['inbox'])
        self.run_cli('stuck', '--send')
        self.assertEqual(self.sent_count(s), 1)

    def test_log_records_each_attempt(self):
        self.session(records=self.ask_records(30))
        self.run_cli('stuck', '--send')
        with open(os.path.join(self.dirs['home'], 'nudges.log')) as fh:
            self.assertIn('SENT QUESTION', fh.read())

    # ---- delivery is verified in the recipient transcript: SENT, HELD (accepted, never shown) or FAILED
    def state(self):
        with open(os.path.join(self.dirs['home'], 'state.json')) as fh:
            return json.load(fh)

    def log_text(self):
        with open(os.path.join(self.dirs['home'], 'nudges.log')) as fh:
            return fh.read()

    def test_delivered_nudge_is_sent_and_recorded(self):
        s = self.session(records=self.ask_records(30))
        code, out, _ = self.run_cli('stuck', '--send')
        self.assertEqual(code, 0)
        self.assertIn('nudged 1 session(s), 0 held', out)
        self.assertTrue(out.startswith('SENT  QUESTION'), out)
        self.assertEqual(self.state().keys(), {f'q:{s["cli"]}'})
        self.assertIn('SENT QUESTION', self.log_text())
        self.assertNotIn('HELD', self.log_text())

    def test_accepted_but_not_in_the_transcript_is_held_and_recorded(self):
        os.environ['SESSION_NUDGE_VERIFY_S'] = '0.3'
        s = self.session(records=self.ask_records(30), echo=False)
        code, out, _ = self.run_cli('stuck', '--send')
        self.assertEqual(code, 0)
        self.assertEqual(self.sent_count(s), 1)  # the socket did take it
        self.assertIn('nudged 0 session(s), 1 held', out)
        self.assertTrue(out.startswith('HELD  QUESTION'), out)
        self.assertNotIn('SENT', out)
        self.assertEqual(self.state().keys(), {f'q:{s["cli"]}', f'H:q:{s["cli"]}'})
        log = self.log_text()
        self.assertIn(f'HELD QUESTION {s["cli"]} not seen in the transcript '
                      '(a bypass recipient holds it for the developer)', log)
        self.assertNotIn('SENT', log)

    def test_held_json_exposes_held_not_sent(self):
        os.environ['SESSION_NUDGE_VERIFY_S'] = '0.3'
        self.session(records=self.ask_records(30), echo=False)
        _, out, _ = self.run_cli('stuck', '--send', '--json')
        rows = json.loads(out)
        self.assertEqual([(r['sent'], r['held']) for r in rows], [(False, True)])

    def test_sent_json_has_held_false(self):
        self.session(records=self.ask_records(30))
        _, out, _ = self.run_cli('stuck', '--send', '--json')
        self.assertEqual([(r['sent'], r['held']) for r in json.loads(out)], [(True, False)])

    def test_a_held_key_is_not_resent_not_even_after_the_question_repeat_time(self):
        os.environ['SESSION_NUDGE_VERIFY_S'] = '0.3'
        s = self.session(records=self.ask_records(30), echo=False)
        self.run_cli('stuck', '--send')
        _, out, _ = self.run_cli('stuck', '--send')
        self.assertIn('nudged 0 session(s), 0 held', out)
        self.assertEqual(self.sent_count(s), 1)
        state_path = os.path.join(self.dirs['home'], 'state.json')
        aged = {k: v - 3 * 3600 for k, v in self.state().items()}  # 3 h later a sent question repeats (2 h)
        with open(state_path, 'w') as fh:
            json.dump(aged, fh)
        self.run_cli('stuck', '--send')
        self.assertEqual(self.sent_count(s), 1)

    def test_held_attempt_uses_the_max_budget(self):
        os.environ['SESSION_NUDGE_VERIFY_S'] = '0.2'
        sessions = [self.session(records=self.ask_records(30), echo=False) for _ in range(3)]
        _, out, _ = self.run_cli('stuck', '--send', '--max', '2')
        self.assertIn('nudged 0 session(s), 2 held', out)
        time.sleep(0.2)
        self.assertEqual(sum(len(x['inbox'].received) for x in sessions), 2)

    def test_scan_shows_a_held_key_as_wait(self):
        os.environ['SESSION_NUDGE_VERIFY_S'] = '0.3'
        self.session(records=self.ask_records(30), echo=False)
        self.run_cli('stuck', '--send')
        _, out, _ = self.run_cli('scan')
        self.assertIn('WAIT', out)
        self.assertIn('0 action(s)', out)


class TestHandoff(NudgeTestCase):
    def rows(self, *extra):
        code, out, _ = self.run_cli('stuck', '--json', *extra)
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_final_message_handing_work_back_is_a_ready_handoff(self):
        self.fake_handoff_guard()
        s = self.session(status='idle', records=self.final_records('Todo listo. La prueba queda para ti.'))
        rows = self.rows()
        self.assertEqual([(r['kind'], r['session'], r['ready']) for r in rows], [('HANDOFF', s['cli'], True)])

    def test_recent_handoff_is_listed_but_not_ready(self):
        self.fake_handoff_guard()
        self.session(status='idle', records=self.final_records('La prueba queda para ti.', minutes_ago=3))
        self.assertFalse(self.rows()[0]['ready'])

    def test_message_without_a_handoff_is_not_stuck(self):
        self.fake_handoff_guard()
        self.session(status='idle', records=self.final_records('Hecho y verificado en pre-produccion.'))
        self.assertEqual(self.rows(), [])

    def test_message_with_a_question_mark_is_not_a_handoff(self):
        self.fake_handoff_guard()
        self.session(status='idle', records=self.final_records('La prueba queda para ti. ¿Sigo?'))
        self.assertEqual(self.rows(), [])

    def test_handoff_needs_the_idle_status(self):
        self.fake_handoff_guard()
        self.session(status='busy', records=self.final_records('La prueba queda para ti.'))
        self.assertEqual(self.rows(), [])

    def test_handoff_only_counts_when_it_is_the_newest_record(self):
        self.fake_handoff_guard()
        ts = time.time() - 3600
        recs = self.final_records('La prueba queda para ti.', minutes_ago=90) + [('user', {}, 'hazla tu', ts)]
        self.session(status='idle', records=recs)
        self.assertEqual(self.rows(), [])

    def test_a_tool_call_in_the_last_message_is_not_a_handoff(self):
        self.fake_handoff_guard()
        recs = [('assistant', {}, [{'type': 'text', 'text': 'queda para ti'},
                                   {'type': 'tool_use', 'id': 't', 'name': 'Bash', 'input': {}}], time.time() - 3600)]
        self.session(status='idle', records=recs)
        self.assertEqual(self.rows(), [])

    def test_missing_or_failing_handoff_guard_means_no_match(self):
        self.session(status='idle', records=self.final_records('La prueba queda para ti.'))
        self.assertEqual(self.rows(), [])  # script absent
        self.fake_handoff_guard(exit_code=3)
        self.assertEqual(self.rows(), [])  # script fails

    def test_handoff_nudge_goes_once_per_final_message_and_says_what_to_do(self):
        self.fake_handoff_guard()
        s = self.session(status='idle', records=self.final_records('La prueba queda para ti.'))
        _, out, _ = self.run_cli('stuck', '--send')
        self.assertIn('nudged 1 session(s)', out)
        time.sleep(0.15)
        self.assertEqual(len(s['inbox'].received), 1)
        content = s['inbox'].received[0][1]['message']['content']
        for needle in ('hazlo tu', 'heavy-job', '~/.claude/rules/despliegue-y-limites-duros.md', 'ask-queue add',
                       'no autoriza commit, push, merge ni despliegue'):
            self.assertIn(needle, content)
        self.assertNotIn('from-mode', content)
        _, out, _ = self.run_cli('stuck', '--send')
        self.assertIn('nudged 0 session(s)', out)
        time.sleep(0.15)
        self.assertEqual(len(s['inbox'].received), 1)

    @unittest.skipUnless(os.path.isfile(os.path.expanduser('~/.claude/scripts/handoff-guard')),
                         'the optional handoff-guard is not installed')
    def test_works_with_the_real_handoff_guard(self):
        os.environ['SESSION_NUDGE_HANDOFF_GUARD'] = os.path.expanduser('~/.claude/scripts/handoff-guard')
        self.session(status='idle', records=self.final_records('Esto queda para ti.'))
        self.session(status='idle', records=self.final_records('Hecho: integrado y desplegado.'))
        rows = self.rows()
        self.assertEqual([r['kind'] for r in rows], ['HANDOFF'])


# What a real usage-limit stop looks like in a transcript (read 2026-11-10 from a real session, cut to the
# fields that matter): a synthetic assistant message, isApiErrorMessage true, error rate_limit, apiErrorStatus 429.
REAL_LIMIT_RECORD = {
    'type': 'assistant', 'timestamp': '2026-11-09T19:41:58.466Z', 'isApiErrorMessage': True, 'error': 'rate_limit',
    'apiError': 'usage_limit_reached', 'apiErrorStatus': 429,
    'apiErrorParams': {'rate_limit_info': {'status': 'rejected', 'resetsAt': 1794270600, 'rateLimitType': 'five_hour'}},
    'message': {'model': '<synthetic>', 'role': 'assistant', 'stop_reason': 'stop_sequence',
                'content': [{'type': 'text', 'text': "You've hit your session limit · resets 1:30am (Europe/Paris)"}]},
}


class TestLimitWithAccountUsage(NudgeTestCase):
    """A limit stop is woken before the reset it named once the app's account has usage again (2026-11-11: the
    five-hour window renewed at about 00:10 while three supervisors waited for the 01:50 their error named)."""

    def rows(self):
        code, out, _ = self.run_cli('stuck', '--json')
        self.assertEqual(code, 0)
        return json.loads(out)

    def fake_account(self, app_org='org-a', cli_org='org-a', usage=None, limited=False, crash=False):
        """A stand-in for account-switch with the helpers session-nudge loads: STATE, load, cli_org, usage and
        usage_limit."""
        usage = {'five_hour': {'utilization': 12.0}, 'seven_day': {'utilization': 2.0}} if usage is None else usage
        path = os.path.join(self.tmp, 'fake-account-switch')
        with open(path, 'w') as fh:
            fh.write(f"""STATE = '/nowhere/state.json'
def load(path, default):
    return {{'org': {app_org!r}}}
def cli_org():
    if {crash!r}:
        raise RuntimeError('no token')
    return {cli_org!r}
def usage():
    return {usage!r}
def usage_limit(data):
    return {{'until': 1, 'what': 'five_hour'}} if {limited!r} else None
""")
        os.environ['SESSION_NUDGE_ACCOUNT_SWITCH'] = path

    def limit_stop(self, window='five_hour', minutes_ago=30, reset_in_hours=2):
        future = datetime.fromtimestamp(time.time() + reset_in_hours * 3600, PARIS)
        text = f"You've hit your session limit · resets {future.strftime('%-I:%M%p').lower()} (Europe/Paris)"
        info = {'status': 'rejected', 'resetsAt': int(time.time() + reset_in_hours * 3600)}
        if window:
            info['rateLimitType'] = window
        extra = {'isApiErrorMessage': True, 'error': 'rate_limit', 'apiErrorParams': {'rate_limit_info': info}}
        return self.session(status='idle', records=[('assistant', extra, [{'type': 'text', 'text': text}],
                                                     time.time() - minutes_ago * 60)])

    def test_account_with_usage_wakes_the_stop_before_the_named_reset(self):
        self.fake_account()
        s = self.limit_stop()
        rows = self.rows()
        self.assertEqual([(r['kind'], r['session'], r['ready'], r['early']) for r in rows],
                         [('LIMIT', s['cli'], True, True)])
        code, out, _ = self.run_cli('stuck')
        self.assertIn('the account already has usage again', out)

    def test_cli_in_another_organization_cannot_tell(self):
        self.fake_account(cli_org='org-b')
        self.limit_stop()
        self.assertFalse(self.rows()[0]['ready'])

    def test_account_still_limited_waits(self):
        self.fake_account(limited=True)
        self.limit_stop()
        self.assertFalse(self.rows()[0]['ready'])

    def test_the_window_that_stopped_it_still_full_waits(self):
        self.fake_account(usage={'five_hour': {'utilization': 10.0}, 'seven_day_opus': {'utilization': 100.0}})
        self.limit_stop(window='seven_day_opus')
        self.assertFalse(self.rows()[0]['ready'])

    def test_a_window_the_answer_does_not_list_waits(self):
        self.fake_account()
        self.limit_stop(window='seven_day_new_kind')
        self.assertFalse(self.rows()[0]['ready'])

    def test_a_stop_without_window_uses_the_five_hour_one(self):
        self.fake_account()
        self.limit_stop(window=None)
        self.assertTrue(self.rows()[0]['ready'])

    def test_a_stop_younger_than_the_grace_waits(self):
        self.fake_account()
        self.limit_stop(minutes_ago=0.2)
        self.assertFalse(self.rows()[0]['ready'])

    def test_a_failing_helper_only_means_cannot_tell(self):
        self.fake_account(crash=True)
        self.limit_stop()
        self.assertFalse(self.rows()[0]['ready'])

    def test_a_stop_older_than_three_days_is_not_woken_by_usage(self):
        self.fake_account()
        self.limit_stop(minutes_ago=4 * 24 * 60, reset_in_hours=-1)
        self.assertFalse(self.rows()[0]['ready'])

    def test_an_early_wake_goes_once_per_limit_event(self):
        self.fake_account()
        s = self.limit_stop()
        self.run_cli('stuck', '--send')
        time.sleep(0.15)
        self.run_cli('stuck', '--send')
        time.sleep(0.15)
        self.assertEqual(len(s['inbox'].received), 1)


class TestApiErrors(NudgeTestCase):
    def rows(self):
        code, out, _ = self.run_cli('stuck', '--json')
        self.assertEqual(code, 0)
        return json.loads(out)

    def api_error(self, minutes_ago, error='overloaded_error', text='API Error: 529 Overloaded'):
        return ('assistant', {'isApiErrorMessage': True, 'error': error}, [{'type': 'text', 'text': text}],
                time.time() - minutes_ago * 60)

    def test_real_limit_format_is_a_limit_with_the_reset_the_api_reports(self):
        path = os.path.join(self.tmp, 'real.jsonl')
        with open(path, 'w') as fh:
            fh.write(json.dumps(REAL_LIMIT_RECORD) + '\n')
        recs = N.tail_records(path)
        stamp, reset, text = N.limit_stop(recs)
        self.assertEqual(reset, 1794270600)  # resetsAt of the same record
        self.assertIsNone(N.api_error_stop(recs))
        self.assertIn('session limit', text)

    def test_real_limit_format_end_to_end(self):
        past = datetime.fromtimestamp(time.time() - 3600, PARIS)
        rec = dict(REAL_LIMIT_RECORD)
        rec['message'] = dict(rec['message'], content=[{'type': 'text', 'text':
                              f"You've hit your session limit · resets {past.strftime('%-I:%M%p').lower()} (Europe/Paris)"}])
        extra = {k: v for k, v in rec.items() if k not in ('type', 'timestamp', 'message')}
        s = self.session(status='idle', records=[('assistant', extra, rec['message']['content'], time.time() - 3 * 3600)])
        self.assertEqual([(r['kind'], r['session'], r['ready']) for r in self.rows()], [('LIMIT', s['cli'], True)])

    def test_other_api_error_is_a_retry_after_ten_minutes(self):
        s = self.session(status='idle', records=[self.api_error(11)])
        self.assertEqual([(r['kind'], r['session'], r['ready']) for r in self.rows()], [('APIERR', s['cli'], True)])

    def test_other_api_error_waits_out_the_cooldown(self):
        self.session(status='idle', records=[self.api_error(5)])
        self.assertFalse(self.rows()[0]['ready'])

    def test_api_error_needs_the_idle_status(self):
        self.session(status='busy', records=[self.api_error(60)])
        self.assertEqual(self.rows(), [])

    def test_api_error_nudge_text_and_once_per_error(self):
        s = self.session(status='idle', records=[self.api_error(20)])
        self.run_cli('stuck', '--send')
        time.sleep(0.15)
        self.assertEqual(len(s['inbox'].received), 1)
        content = s['inbox'].received[0][1]['message']['content']
        self.assertIn('continua donde lo dejaste', content)
        self.assertIn('no autoriza commit, push, merge ni despliegue', content)
        self.run_cli('stuck', '--send')
        time.sleep(0.15)
        self.assertEqual(len(s['inbox'].received), 1)

    def test_at_most_three_retries_in_a_row(self):
        s = self.session(status='idle', records=[self.api_error(300)])
        transcript = N.transcript_path({'sessionId': s['cli'], 'cwd': '/work/proj'})
        sent = 0
        for round_no in range(5):
            _, out, _ = self.run_cli('stuck', '--send')
            sent += 'nudged 1' in out
            # the retry failed again: a newer API error, no progress in between
            err = self.api_error(240 - 60 * round_no)
            with open(transcript, 'a') as fh:
                fh.write(json.dumps({'type': 'user', 'timestamp': iso(time.time() - (250 - 60 * round_no) * 60),
                                     'message': {'role': 'user', 'content': 'nudge'}}) + '\n')
                fh.write(json.dumps({'type': err[0], 'timestamp': iso(err[3]),
                                     'message': {'role': 'assistant', 'content': err[2]}, **err[1]}) + '\n')
            with open(os.path.join(self.dirs['home'], 'state.json')) as fh:  # age the nudge so it sits before the error
                st = json.load(fh)
            with open(os.path.join(self.dirs['home'], 'state.json'), 'w') as fh:
                json.dump({k: v - 3600 * 5 for k, v in st.items()}, fh)
        self.assertEqual(sent, 3)

    def test_progress_between_errors_resets_the_streak(self):
        s = self.session(status='idle', records=[self.api_error(600)])
        self.run_cli('stuck', '--send')
        with open(os.path.join(self.dirs['home'], 'state.json')) as fh:
            st = json.load(fh)
        key = next(iter(st))
        with open(os.path.join(self.dirs['home'], 'state.json'), 'w') as fh:
            json.dump({k: v - 9 * 3600 for k, v in st.items()}, fh)
        # nothing but errors since: streak 1
        recs = N.tail_records(N.transcript_path({'sessionId': s['cli'], 'cwd': '/work/proj'}))
        stamp = int(key.rsplit(':', 1)[1])
        self.assertEqual(N.apierr_streak({key: time.time() - 9 * 3600}, s['cli'], stamp + 1000, recs), 1)
        # a real assistant message after the nudge and before the new error breaks the chain
        recs.append({'type': 'assistant', '_ts': time.time() - 8 * 3600, 'message': {'content': []}})
        self.assertEqual(N.apierr_streak({key: time.time() - 9 * 3600}, s['cli'], stamp + 40000, recs), 0)

    def test_unclassified_cut_is_logged_once_with_send_only(self):
        self.session(status='idle', records=self.final_records('Usage limit reached, try later 429', minutes_ago=30))
        self.run_cli('stuck')
        self.assertFalse(os.path.exists(os.path.join(self.dirs['home'], 'unclassified.log')))
        self.run_cli('stuck', '--send')
        self.run_cli('stuck', '--send')
        with open(os.path.join(self.dirs['home'], 'unclassified.log')) as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn('00000000-0000-0000-0000-000000000001', lines[0])
        self.assertIn('Usage limit reached, try later 429', lines[0])

    def test_unclassified_text_is_cut_to_200_chars(self):
        self.session(status='idle', records=self.final_records('limit ' + 'x' * 250 + ' y', minutes_ago=30))
        self.run_cli('stuck', '--send')
        with open(os.path.join(self.dirs['home'], 'unclassified.log')) as fh:
            line = fh.read().strip()
        self.assertEqual(len(line.split(' ', 2)[2]), 200)

    def test_long_report_mentioning_limit_and_classified_cuts_are_not_unclassified(self):
        self.session(status='idle', records=self.final_records('limit ' + 'x' * 350, minutes_ago=30))
        self.session(status='idle', records=[self.api_error(30, text='x' * 120)])  # APIERR: classified
        self.run_cli('stuck', '--send')
        self.assertFalse(os.path.exists(os.path.join(self.dirs['home'], 'unclassified.log')))

    def test_limit_with_unreadable_reset_is_logged_as_a_new_format(self):
        text = "You've hit your limit, back whenever " + 'z' * 220
        self.session(status='idle', records=self.limit_records(text, hours_ago=2))
        self.run_cli('stuck', '--send')
        with open(os.path.join(self.dirs['home'], 'unclassified.log')) as fh:
            line = fh.read().strip()
        self.assertTrue(line.endswith('z' * 20))
        self.assertLessEqual(len(line.split(' ', 2)[2]), 200)

    def test_ordinary_final_message_is_not_logged(self):
        self.session(status='idle', records=self.final_records('Hecho. Todo integrado.'))
        self.run_cli('stuck', '--send')
        self.assertFalse(os.path.exists(os.path.join(self.dirs['home'], 'unclassified.log')))


class TestOpenDialog(NudgeTestCase):
    def fake_queue(self, exit_code=0):
        path = os.path.join(self.tmp, 'fake-ask-queue')
        self.queue_log = os.path.join(self.tmp, 'queue.jsonl')
        with open(path, 'w') as fh:
            fh.write('#!/usr/bin/env python3\nimport json,sys\n'
                     f'open({self.queue_log!r},"a").write(json.dumps(sys.argv[1:])+"\\n")\nsys.exit({exit_code})\n')
        os.chmod(path, 0o755)
        os.environ['SESSION_NUDGE_ASK_QUEUE'] = path

    def queued(self):
        if not os.path.exists(self.queue_log):
            return []
        with open(self.queue_log) as fh:
            return [json.loads(line) for line in fh]

    def dialog_records(self, minutes_ago, questions=None):
        questions = questions or [
            {'question': 'Que version uso?', 'header': 'v', 'options': [{'label': 'La 2', 'description': 'x'},
                                                                          {'label': 'La 3', 'description': 'y'}]},
            {'question': 'Y el nombre?', 'header': 'n', 'options': []}]
        ts = time.time() - minutes_ago * 60
        return [('assistant', {}, [{'type': 'tool_use', 'id': 'toolu_9', 'name': 'AskUserQuestion',
                                    'input': {'questions': questions}}], ts)]

    def test_dialog_open_over_fifteen_minutes_is_queued_once(self):
        self.fake_queue()
        s = self.session(records=self.dialog_records(20))
        _, out, _ = self.run_cli('stuck', '--send')
        calls = self.queued()
        self.assertEqual(len(calls), 2)
        first = dict(zip(calls[0][1::2], calls[0][2::2]))
        self.assertEqual(calls[0][0], 'add')
        self.assertEqual(first['--project'], '/work/proj')
        self.assertIn('Que version uso?', first['--question'])
        self.assertIn('La 2 | La 3', first['--question'])
        self.assertEqual(first['--default'], 'La 2')
        self.assertEqual(first['--why'], 'diálogo abierto sin respuesta')
        self.assertEqual(first['--blocks'], 'nada')
        self.assertEqual(first['--session'], s['cli'])
        self.assertEqual(dict(zip(calls[1][1::2], calls[1][2::2]))['--default'], 'No hacerlo')
        self.assertNotEqual(first['--key'], dict(zip(calls[1][1::2], calls[1][2::2]))['--key'])
        self.assertIn('nudged 1 session(s)', out)  # the QUESTION nudge still goes, the dialog is not counted
        self.run_cli('stuck', '--send')
        self.assertEqual(len(self.queued()), 2)
        with open(os.path.join(self.dirs['home'], 'nudges.log')) as fh:
            self.assertIn('QUEUED OPEN_DIALOG', fh.read())

    def test_dialog_younger_than_fifteen_minutes_is_not_queued(self):
        self.fake_queue()
        self.session(records=self.dialog_records(10))
        self.run_cli('stuck', '--send')
        self.assertEqual(self.queued(), [])

    def test_dialog_in_the_questions_session_is_never_queued(self):
        self.fake_queue()
        self.session(records=self.dialog_records(60), name='Preguntas de la supervisión de demo')
        self.run_cli('stuck', '--send')
        self.assertEqual(self.queued(), [])

    def test_answered_dialog_is_not_queued(self):
        self.fake_queue()
        recs = self.dialog_records(60)
        recs.append(('user', {}, [{'type': 'tool_result', 'tool_use_id': 'toolu_9', 'content': 'ok'}], time.time() - 3000))
        self.session(records=recs)
        self.run_cli('stuck', '--send')
        self.assertEqual(self.queued(), [])

    def test_failing_ask_queue_is_logged_and_retried_next_run(self):
        self.fake_queue(exit_code=1)
        s = self.session(records=self.dialog_records(30))
        _, out, _ = self.run_cli('stuck', '--send')
        self.assertIn('nudged 1 session(s)', out)  # the run goes on
        with open(os.path.join(self.dirs['home'], 'nudges.log')) as fh:
            self.assertIn(f'FAILED OPEN_DIALOG {s["cli"]}', fh.read())
        self.assertEqual(len(self.queued()), 1)  # stopped at the first failing question
        self.fake_queue(exit_code=0)
        self.run_cli('stuck', '--send')
        self.assertEqual(len(self.queued()), 3)  # 1 failed + both questions retried (ask-queue dedupes by --key)

    def test_missing_ask_queue_is_logged_not_raised(self):
        self.session(records=self.dialog_records(30))
        code, _, _ = self.run_cli('stuck', '--send')
        self.assertEqual(code, 0)
        with open(os.path.join(self.dirs['home'], 'nudges.log')) as fh:
            self.assertIn('ask-queue not found', fh.read())

    def test_the_dialog_is_never_answered(self):
        self.fake_queue()
        s = self.session(records=self.dialog_records(30))
        self.run_cli('stuck', '--send')
        time.sleep(0.15)
        for _, msg in [r for r in s['inbox'].received]:
            self.assertNotIn('tool_result', json.dumps(msg))
            self.assertIn('[session-nudge]', msg['message']['content'])


class TestConfig(NudgeTestCase):
    """What comes from the toolkit config pieces, and what each wrong or missing value falls back to."""

    def rows(self):
        code, out, _ = self.run_cli('stuck', '--json')
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_default_titles_skip_the_questions_session_with_or_without_accents(self):
        self.session(records=self.ask_records(60), name='Preguntas de la supervision de demo')
        self.session(records=self.ask_records(60), name='BUZÓN DE PREGUNTAS')
        self.session(records=self.ask_records(60), name='Sesión de preguntas de demo')
        self.assertEqual(self.rows(), [])

    def test_a_normal_session_is_not_skipped(self):
        self.session(records=self.ask_records(60), name='Cierre de sesiones de demo')
        self.assertEqual([r['kind'] for r in self.rows()], ['QUESTION'])

    def test_the_titles_come_from_the_supervision_config(self):
        self.write_config('supervision', {'questions_session_titles': ['mi buzon']})
        self.session(records=self.ask_records(60), name='Preguntas de la supervisión de demo')  # no longer a mailbox
        self.session(records=self.ask_records(60), name='Mi Buzón de demo')                     # now it is
        self.assertEqual([r['name'] for r in self.rows()], ['Preguntas de la supervisión de demo'])

    def test_a_broken_or_mistyped_config_keeps_the_default_titles(self):
        for bad in ('{not json', '[]', {'questions_session_titles': 'a string'}, {'questions_session_titles': ['']}):
            self.write_config('supervision', bad)
            self.assertTrue(N.is_questions_session('Preguntas de la supervisión de demo'), bad)

    def test_the_app_records_folder_comes_from_the_supervision_config(self):
        del os.environ['SESSION_NUDGE_APP_GLOB']
        self.assertTrue(N.app_glob().endswith('/.config/Claude/claude-code-sessions/*/*/local_*.json'))
        self.write_config('supervision', {'app_sessions_dir': self.dirs['app']})
        self.assertEqual(N.app_glob(), os.path.join(self.dirs['app'], '*', '*', 'local_*.json'))
        s = self.session(records=self.ask_records(60), archived=True)
        self.assertIn(s['local'], N.app_records())
        self.assertEqual(self.rows(), [])  # the archived flag was read through that folder

    def test_the_env_override_of_the_app_glob_wins_over_the_config(self):
        self.write_config('supervision', {'app_sessions_dir': '/nowhere'})
        self.assertEqual(N.app_glob(), os.environ['SESSION_NUDGE_APP_GLOB'])

    def test_the_default_handoff_text_names_the_configured_deploy_rule(self):
        text = N.handoff_text('la prueba')
        self.assertIn('(la prueba)', text)
        self.assertIn('(~/.claude/rules/despliegue-y-limites-duros.md)', text)
        self.assertNotIn('{', text)
        self.write_config('supervision', {'deploy_rule': 'my-rule.md'})
        self.assertIn('(~/.claude/rules/my-rule.md)', N.handoff_text('x'))

    def test_the_handoff_text_comes_from_its_own_config_piece(self):
        self.write_config('session-nudge', {'handoff_text': 'Hazlo ({what}) segun {rule} {otra}'})
        self.assertEqual(N.handoff_text('esto'),
                         'Hazlo (esto) segun ~/.claude/rules/despliegue-y-limites-duros.md {otra}')

    def test_a_wrong_handoff_text_keeps_the_default(self):
        default = N.handoff_text('x')
        for bad in ({'handoff_text': ''}, {'handoff_text': 7}, {'handoff_text': ['a']}, '{broken', '"text"'):
            self.write_config('session-nudge', bad)
            self.assertEqual(N.handoff_text('x'), default, bad)

    def test_the_configured_handoff_text_is_what_the_session_receives(self):
        self.write_config('session-nudge', {'handoff_text': '[session-nudge] Hazlo tu: {what}.'})
        self.fake_handoff_guard()
        s = self.session(status='idle', records=self.final_records('La prueba queda para ti.'))
        self.run_cli('stuck', '--send')
        time.sleep(0.15)
        self.assertEqual(s['inbox'].received[0][1]['message']['content'],
                         N.envelope('[session-nudge] Hazlo tu: queda para ti. [' + self.marker_of(s) + ']'))

    def marker_of(self, s):
        content = s['inbox'].received[0][1]['message']['content']
        return content.rsplit('[', 1)[1].split(']')[0]

    def test_the_other_texts_do_not_need_any_config(self):
        self.assertEqual(os.listdir(self.config), [])
        s = self.session(records=self.ask_records(30))
        self.run_cli('stuck', '--send')
        time.sleep(0.15)
        self.assertIn('30 min', s['inbox'].received[0][1]['message']['content'])


class TestOptionalPieces(NudgeTestCase):
    """handoff-guard, ask-queue, account-switch and project-pause are siblings of the toolkit that may be absent."""

    def test_everything_absent_still_lists_and_nudges_a_question(self):
        for var in ('SESSION_NUDGE_HANDOFF_GUARD', 'SESSION_NUDGE_ASK_QUEUE', 'SESSION_NUDGE_ACCOUNT_SWITCH',
                    'PROJECT_PAUSE_BIN'):
            self.assertFalse(os.path.exists(os.environ[var]), var)
        s = self.session(records=self.ask_records(30))
        self.session(status='idle', records=self.final_records('La prueba queda para ti.'))  # no handoff-guard: no match
        code, out, _ = self.run_cli('stuck', '--send')
        self.assertEqual(code, 0)
        self.assertIn('nudged 1 session(s)', out)
        time.sleep(0.15)
        self.assertEqual(len(s['inbox'].received), 1)

    def test_without_account_switch_a_limit_waits_for_its_reset(self):
        future = datetime.fromtimestamp(time.time() + 2 * 3600, PARIS)
        text = f"You've hit your session limit · resets {future.strftime('%-I:%M%p').lower()} (Europe/Paris)"
        self.session(status='idle', records=self.limit_records(text, hours_ago=0.5))
        self.assertIsNone(N.account_usage())
        _, out, _ = self.run_cli('stuck', '--json')
        self.assertFalse(json.loads(out)[0]['ready'])

    def fake_project_pause(self, paused):
        path = os.path.join(self.tmp, 'fake-project-pause')
        with open(path, 'w') as fh:
            fh.write(f'def paused_marker(path):\n    return {paused!r}\n')
        os.environ['PROJECT_PAUSE_BIN'] = path

    def test_a_paused_project_is_never_nudged(self):
        self.fake_project_pause({'since': 'x'})
        N._PAUSE.clear()
        self.session(records=self.ask_records(60))
        code, out, _ = self.run_cli('stuck', '--json')
        self.assertEqual(json.loads(out), [])
        N._PAUSE.clear()

    def test_a_project_that_is_not_paused_is_nudged(self):
        self.fake_project_pause(None)
        N._PAUSE.clear()
        self.session(records=self.ask_records(60))
        _, out, _ = self.run_cli('stuck', '--json')
        self.assertEqual([r['kind'] for r in json.loads(out)], ['QUESTION'])
        N._PAUSE.clear()

    def test_a_broken_project_pause_means_not_paused(self):
        path = os.path.join(self.tmp, 'broken-project-pause')
        with open(path, 'w') as fh:
            fh.write('raise RuntimeError("boom")\n')
        os.environ['PROJECT_PAUSE_BIN'] = path
        N._PAUSE.clear()
        self.assertFalse(N.paused_project('/work/proj'))


class TestCommandLine(unittest.TestCase):
    """The script run as a program, in a HOME that holds nothing: what `supervisor-lock watchdog --nudge` relies on."""

    def run_script(self, *args):
        with tempfile.TemporaryDirectory(prefix='sn-home-') as home:
            env = {k: v for k, v in os.environ.items() if not k.startswith(('SESSION_NUDGE_', 'PROJECT_PAUSE', 'CLAUDE_'))}
            env['HOME'] = home
            proc = subprocess.run([sys.executable, '-I', SCRIPT, *args], capture_output=True, text=True, timeout=60,
                                  env=env, cwd=home)
            left = sorted(os.listdir(home))
        return proc, left

    def test_help_lists_the_subcommands(self):
        proc, left = self.run_script('--help')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for word in ('send', 'stuck', 'scan'):
            self.assertIn(word, proc.stdout)
        self.assertEqual(left, [])

    def test_scan_with_no_sessions_writes_nothing(self):
        proc, left = self.run_script('scan')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('scan: 0 action(s), 0 unclassified; nothing sent or written', proc.stdout)
        self.assertEqual(left, [], 'scan wrote into HOME')

    def test_stuck_send_with_no_sessions_prints_the_summary_line_the_watchdog_reads(self):
        proc, _ = self.run_script('stuck', '--send', '--min-minutes', '15', '--max', '6')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'nudged 0 session(s), 0 held')

    def test_send_to_an_unknown_target_exits_2(self):
        proc, _ = self.run_script('send', 'nope', '--text', 'x')
        self.assertEqual(proc.returncode, 2)
        self.assertIn('no live session', proc.stderr)

    def test_a_corrupt_toolkit_config_does_not_crash(self):
        with tempfile.TemporaryDirectory(prefix='sn-cfg-') as cfg, tempfile.TemporaryDirectory(prefix='sn-home-') as home:
            for piece in ('supervision', 'session-nudge'):
                with open(os.path.join(cfg, piece + '.json'), 'w') as fh:
                    fh.write('{not json')
            env = {k: v for k, v in os.environ.items() if not k.startswith(('SESSION_NUDGE_', 'PROJECT_PAUSE', 'CLAUDE_'))}
            env.update(HOME=home, CLAUDE_TOOLKIT_CONFIG_DIR=cfg)
            proc = subprocess.run([sys.executable, '-I', SCRIPT, 'scan'], capture_output=True, text=True, timeout=60,
                                  env=env, cwd=home)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestScan(NudgeTestCase):
    def test_scan_lists_every_kind_and_writes_nothing(self):
        self.fake_handoff_guard()
        os.environ['SESSION_NUDGE_ASK_QUEUE'] = os.path.join(self.tmp, 'must-not-run')
        shutil.rmtree(self.dirs['home'])  # scan must not even create its state dir
        dlg = TestOpenDialog.dialog_records(self, 30)
        self.session(records=dlg)
        self.session(status='idle', records=self.final_records('La prueba queda para ti.'))
        self.session(status='idle', records=[('assistant', {'isApiErrorMessage': True, 'error': 'api_error'},
                                              [{'type': 'text', 'text': 'API Error: 500'}], time.time() - 1800)])
        self.session(status='idle', records=self.final_records('Usage limit 429', minutes_ago=30))
        code, out, _ = self.run_cli('scan')
        self.assertEqual(code, 0)
        for needle in ('WOULD-QUEUE', 'OPEN_DIALOG', 'WOULD-NUDGE', 'QUESTION', 'HANDOFF', 'APIERR',
                       'WOULD-LOG', 'nothing sent or written'):
            self.assertIn(needle, out)
        self.assertFalse(os.path.exists(self.dirs['home']))
        time.sleep(0.15)
        self.assertTrue(all(not sock.received for sock in self.sockets))

    def test_scan_json_and_max(self):
        for _ in range(3):
            self.session(records=self.ask_records(30))
        code, out, _ = self.run_cli('scan', '--json', '--max', '2')
        data = json.loads(out)
        self.assertEqual(sorted(c['would'] for c in data['candidates']), ['LATER', 'WOULD-NUDGE', 'WOULD-NUDGE'])

    def test_scan_marks_what_was_already_done_as_wait(self):
        self.session(records=self.ask_records(30))
        self.run_cli('stuck', '--send')
        _, out, _ = self.run_cli('scan')
        self.assertIn('WAIT', out)
        self.assertNotIn('WOULD-NUDGE', out)


if __name__ == '__main__':
    unittest.main()
