# Design — mail-send-gate

## D1. Owner module: `core`

FACT: `core.yaml` describes itself as the general mechanics for unattended agent work and already installs the two gates
this one is modelled on (`commit-authorship-gate`, `process-kill-gate`) plus `agent-model-gate`. FACT: `access.yaml` only
installs `mailbox` and `stores`, is opt-in, and a session can hold a mail connector without it. The limit applies to
every session whether or not `access` is installed, so the gate belongs to `core`. `access` depends on `core`, so its
manifest note may cite the gate (validator rule `global-citation`). `examples/override-full/override.yaml` already lists
`core`: no change there.

Consequence: `core` is a default module, so a fresh install denies mail sends. Anyone who does not want it removes the
hook in the override (`remove: [hooks/mail-send-gate]`, already supported and tested for `process-kill-gate` in
`test_installer.py`). No `enabled` key is added (the brief names none).

## D2. Registration

`global/settings/hooks.core.json` gains one `PreToolUse` entry, matcher `Bash|Monitor|mcp__.*` (Monitor and a terminal connector's `run_in_terminal` also run a shell
`command`; added by the confirm review), command
`python3 ~/.claude/hooks/mail-send-gate`, timeout 10. Any other tool name passes without work.

## D3. Config piece `mail-send-gate` (shipped defaults)

```json
{
  "exempt_paths": [],
  "extra_commands": [],
  "drafts": false,
  "send_tools": [
    "^(send_message|send_email|send_mail|send_draft)$",
    "^(reply|reply_all|forward)$",
    "^(create_draft|update_draft|delete_draft)$",
    "^(trash|untrash|delete)_(message|thread)$",
    "^(mark|unmark)_(message|thread)_spam$",
    "^(label|unlabel)_(message|thread)$",
    "^(update_message_labels|apply_sensitive_message_label|apply_sensitive_thread_label)$",
    "^(create|update|delete)_label$"
  ],
  "draft_tools": ["^(create_draft|update_draft)$"],
  "read_tools": ["^(search|get|list|read|download|fetch)_"],
  "ignore_servers": ["^ccd_"]
}
```

Loaded with `toolkit_config.load_checked('mail-send-gate', DEFAULTS)`: only known keys count and a value of the wrong
shape (not a bool, not a list of non-empty strings) keeps the code default. The hook's `DEFAULTS` equal this file.

## D4. Connector branch (`tool_name` starts with `mcp__`)

1. Split `mcp__<server>__<tool>` at the **last** `__`: `<server>` may contain single underscores
   (`ccd_session_mgmt`). A name without a second `__` is not a connector tool: allow.
2. `<server>` matches any `ignore_servers` regex (search, case-insensitive): allow. Default `^ccd_` keeps the desktop
   app's own tools (session messaging is `mcp__ccd_session_mgmt__send_message`) out of scope.
3. `<tool>` matches any `read_tools` regex: allow. Read patterns win over every other list.
4. `drafts` is true and `<tool>` matches any `draft_tools` regex: allow.
5. `<tool>` matches any `send_tools` regex: deny.
6. Otherwise allow.

The server segment is never compared with a stored identifier: a connector named by an opaque id is caught by its tool
names alone. A regex that does not compile is skipped and logged in `errors.log`; the others still apply.

## D5. Bash branch

**Tokenizing.** Heredoc bodies are cut out first, line by line (`<<WORD`, `<<-WORD`, `<<'WORD'`, `<<"WORD"`; the
delimiter must start with a letter or `_`) and kept in order. The rest goes through `shlex` in POSIX mode with
`punctuation_chars` `();<>|&` plus newline and `whitespace_split`, so quoted text stays one word (`git commit -m
"x; sendmail y"` is one argument). On a quoting error the text is split on whitespace and separators instead. Simple
commands are cut at `;`, `&&`, `||`, `|`, `|&`, `&`, newline, `(`, `)`; commands joined by `|` form one pipeline.
Redirections (`<`, `>`, `>>`, `<<`, `<<<`, `>&`, `&>`, …) and their target word leave the argument list; `<<` takes
the next heredoc body and `<<<` its word as the command's stdin text.

**Substitutions.** `$(…)` and backticks found outside single quotes are scanned again as commands of their own
(recursively), so `echo $(sendmail -t < m)` is denied while `git commit -m 'document $(sendmail)'` passes.

**Command position.** Leading `VAR=value` words and the reserved words that can stand before a command (`do`,
`then`, `else`, `elif`, `if`, `while`, `until`, `{`, `!`) are skipped, then wrappers with their options: `sudo` (`-u`, `-g`,
`-C`, `-D`, `-h`, `-p`, `-r`, `-t`, `-U` take a value), `env` (`-u`, `-C`, `-S` take a value; assignments skipped),
`xargs` (`-I`, `-n`, `-P`, `-L`, `-d`, `-E`, `-s`, `-a` take a value), `timeout` (options, then the duration),
`nice` (`-n`), `ionice` (`-c`, `-n`, `-p`), `stdbuf` (`-i`, `-o`, `-e`), `nohup`, `exec` (`-a` takes a value),
`time`, `setsid`. `command` is a wrapper only without `-v`/`-V`; with them, and for `which`, `type`, `man`, `whatis`,
`apropos`, `whereis`, the line only names a command and passes. The command word is compared by basename
(`/usr/sbin/sendmail` → `sendmail`). For `sh`, `bash`, `zsh`, `dash` with `-c` (alone or in a cluster such as `-lc`)
the next word is scanned as a full command.

| Command word | Denied when | Passes when |
|---|---|---|
| `sendmail`, `mail`, `mailx` | always (they carry no host) | — |
| `mutt` | it carries `-s`, `-a`, `-H` or a recipient (a word that is not an option or an option value) | no such word (`mutt`, `mutt -f ~/Mail`) |
| `msmtp` | `--host=H` / `--host H` absent or H not local | H local |
| `swaks` | `--server` / `--server=` / `-s` absent or not local (`host:port` keeps the host) | the server is local |
| `curl` | an argument, `--url` or `--url=` value starting with `smtp://` / `smtps://` whose host (`urlsplit().hostname`, so `user@` is dropped) is not local; or `--mail-rcpt` / `--mail-from` with no such URL | every such URL is local; no SMTP URL and no mail option |
| `python*`, `perl`, `ruby`, `node`, `nodejs`, `php` | its own code holds a marker and the host literals found are not all local, or none is found | no marker in its own code; every literal local |
| any, matching an `extra_commands` regex (searched in the whole command text) | always | — |

**An interpreter's own code** is the value of its code option (Python `-c`; Perl `-e`/`-E`; Ruby `-e`; Node `-e`,
`--eval`, `-p`, `--print`; PHP `-r`), its module options (Perl `-M…`/`-m…`; Ruby `-r…`/`-r X`; Node `-r X`,
`--require X`), and, only when it runs no script file and no module (no file argument, or `-`), its stdin text: the
heredoc body or here-string given to it and the text of the commands before it in the same pipeline. A script file
(`python3 send.py`) and a module run (`python3 -m pytest`) carry no inline code (known limit). Writing a heredoc to a
file with `cat` is not inline code, so `cat > f.py <<'EOF' … smtplib … EOF` passes.

**Markers:** `smtplib`, `Net::SMTP`, `net/smtp`, `nodemailer`, `PHPMailer`, and for `php` a `mail(` call
(`\bmail\s*\(`). **Host literals:** Python `SMTP(` / `SMTP_SSL(` / `LMTP(` first string argument or `host=`, and
`.connect(` first string argument; Perl `Net::SMTP…->new(` first string; Ruby `Net::SMTP.start(` / `.new(` first
string; Node and PHPMailer `host:` / `Host =` / `->Host =` string values. PHP `mail(` has no host, so it is always
denied.

## D6. Local test mailer

A host is local when, lowercased and without port, brackets or a trailing dot, it equals `localhost`, `127.0.0.1` or
`::1`, or ends in `.localhost` or `.test`. The comparison is on the whole host, so `localhost.evil.example` and
`x.test.evil.example` are not local, and a URL's `user@` part never counts as the host. Not configurable: the brief makes
it always allowed, and a configurable list could only widen. `::1` is added to the brief's list because it is the same
loopback as `127.0.0.1`.

## D7. Exempt projects

When the hook input's `cwd`, resolved, equals or is below an `exempt_paths` entry (`~` expanded), the Bash branch
allows everything, `extra_commands` included (that folder's own send flow is authorised). Connector tools are not
exempted: the connector is the developer's account, not a project's flow.

## D8. Drafts

`drafts: false` (default) denies creating and editing drafts. `drafts: true` allows only the tools matched by
`draft_tools`; `send_draft`, `delete_draft` and every other send tool stay denied.

## D9. Failure handling

- Unparseable stdin, a payload that is not an object, or a missing `tool_name`: exit 0, no output.
- Any exception inside the decision: exit 0, no output, traceback in `errors.log` (a deny is never the result of a
  crash). Same as `process-kill-gate` `main()`, which catches every exception, logs it and lets the command run.
- Missing or corrupt config file: the code defaults, which deny (gate active, `drafts` false, no exemptions).

**Why, and from where (brief point 4).** The two gates the brief names were read, not assumed:
`process-kill-gate` and `commit-authorship-gate` read no config piece at all (`grep -l toolkit_config
global/hooks/*` lists neither). Their deny rules are built into the code, so no state of any config file can turn
them off; what "fails open" covers in them is broken input (`commit-authorship-gate` exits 0 on unparseable stdin,
probe «unparseable stdin fails open» in its contract) and internal errors (`process-kill-gate`). The repository
invariant «Un hook con la config rota falla abierto» is defined by `global/scripts/lib/toolkit_config.py`, whose
docstring says a missing or corrupt file makes `load()` fall back to the defaults the piece passes in, "so hooks fail
open": the hook never breaks, it runs on its defaults. This gate follows both: a broken config never crashes it and
never removes a deny that its code defaults make, exactly like the two reference gates whose denies do not depend on a
config. `cross-project-message-gate` (probe «a corrupt config never allows more») is consistent with this, not the
source. A separate test patches the decision to raise and proves the call goes through (task 4.2).

## D10. Logs and state

State dir `~/.cache/claude-toolkit/mail-send-gate` (override: `MAIL_SEND_GATE_STATE`). `decisions.log` gets one
tab-separated line per deny and per exempt allow: time, session id, tool, decision, category (for example
`deny-connector`, `deny-bash-sendmail`, `allow-exempt`). The command text, recipients and message bodies are never
written. Plain allows write nothing.

## D11. Deny reason

`mail-send-gate: agents do not send or change mail; <what was denied>. Write the text in the chat or in a file and
the developer sends it. Reading mail is never blocked.` plus, for a connector draft tool with drafts off, a line
saying drafts are off in this machine's config. The rule path `~/.claude/rules/correo-solo-lectura.md` closes it.

## D12. Rule text (Spanish, like the other global rules; 5 to 8 lines)

Content points: mail is read-only for agents; they draft, the developer sends; reading, searching and downloading are
never blocked; the gate denies connector write tools and Bash send commands; the local test mailer is allowed; on a
deny, hand over the text in the chat or a file; exceptions and drafts live in the config piece, real values in the
override.

## D13. Indirect routes (confirm review, P4)

The adversarial review found sends that reached the shell without a listed command at command position. The Bash
rules now also cover: the `command` of `Monitor` and of a connector tool named `run_in_terminal`; short-option
clusters of wrappers (`sudo -iu root`: the last letter takes the next word); `doas`; `eval` (its words are scanned as
a command); `su -c|--command`; `find -exec|-execdir|-ok|-okdir … ;|+`; a shell with no `-c` and no script file reads
its stdin, so its heredoc, here-string and the arguments of the commands piped into it are scanned as commands;
clustered interpreter code options (Python `-[flags]c`, `-[flags]m` is a module; Perl `-…e|E`; Ruby `-…e`) and
`/dev/stdin` as the script; the same programs under other names (`ssmtp`, `esmtp` like `sendmail`; `nail`, `s-nail`,
`bsd-mailx`, `heirloom-mailx`, `mail.mailutils` like `mailx`; `neomutt` like `mutt`; `msmtpq` like `msmtp`);
`git send-email` unless every `--smtp-server` is local; curl with `--connect-to`, `--resolve`, `-x`, `--proxy`,
`--preproxy` or `--socks*` is never local. Inline host literals are read per connection: every `SMTP(`/`SMTP_SSL(`/
`LMTP(`/`.connect(`/`Net::SMTP…new(`/`Net::SMTP.start(` call with arguments and every `host:`/`Host =` setting must
name a plain string literal (followed by `,`, `)`, `;`, `}` or the end), and all of them must be local; a call with no
argument names no remote host.

## Known limits (documented in the hook docstring)

- A send made inside a script file (`python3 send.py`, `bash send.sh`, `bin/notify`), a module (`python3 -m
  mymailer`), a project runner (`uv run`, `poetry run`, `npx`), a container (`ddev exec`, `docker exec`) or a remote
  host (`ssh host sendmail`) is not seen; curl's proxy environment variables are not read; `extra_commands` covers a project's
  known scripts.
- Detection is textual: inline interpreter code that only mentions an SMTP library is denied.
- Commands built at run time (`$CMD -t`, `eval "$x"`) are not seen.
- A non-mail connector with a tool named like a mail write (`send_message`) is denied unless its server matches
  `ignore_servers` in the override.

## Testing strategy

Subprocess tests in `scripts/toolkit/tests/pieces/test_mail_send_gate.py`, modelled on `test_agent_model_gate.py`:
`HOME`, `CLAUDE_TOOLKIT_CONFIG_DIR` and `MAIL_SEND_GATE_STATE` point into a temp dir; inputs are synthetic JSON; no
network, no mail binary is ever executed (the hook only reads text). Contract probes cover the installed copy.
