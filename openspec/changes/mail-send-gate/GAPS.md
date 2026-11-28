# GAPS — mail-send-gate (honest review of the spec, before and after apply)

> **Date:** 2026-11-28
> **Mode:** A (change folder), run as phase P2 of `run-spec` (`repasa-spec`: gaps → mejora → aplica → gaps).
> **Real status:** the pre-apply review (iterations 1–5) found nine FACT gaps; round 1 hydrated, applied and tested
> all of them. The post-apply review (iterations 6–7) found two more and closed them in the same round. The
> independent confirm review (P4, iterations 8–9) attacked the hook with 216 synthetic payloads: 40 sends got through
> (G-14 to G-20), all fixed with tests that fail against the previous hook; no false positive was found.

## Review objective

Settle in the spec, with scenarios and before any code: (1) Bash matching by command position, not substring, with
the look-alikes that must pass and the wrappers after which a send must still be denied; (2) how each command's SMTP
host is read and an anchored local-host match; (3) one table over connector tool-name suffixes (writes denied, reads
and non-mail look-alikes pass, `drafts: true` opens only create and update); (4) what a broken config does, decided by
what `process-kill-gate` and `commit-authorship-gate` actually do; (5) the deny text tells the session to hand the
text over in the chat or in a file.

## Methodology

| Iter | Focus | Honest result |
|------|-------|---------------|
| 1 | Spec scenario by scenario against the five points | Point 1 had four of the eleven must-pass look-alikes and none of the wrapper denies (`&&`, `;`, `|`, `env`, `xargs`); point 2 had no anchored-host scenario; point 3 had no non-mail look-alike; point 4 cited a gate the brief did not name |
| 2 | Design D5 rules re-read as code would run them | `command` is in the wrapper list, so `command -v msmtp` would be read as running `msmtp` (G-02); the interpreter row searches "the whole command text", so a heredoc that only writes a file next to an unrelated `python3 -m …` would be denied (G-03); `mutt` without `-s` and `php -r 'mail(…)'` send and pass (G-06, G-07) |
| 3 | Reference gates and the config loader | `process-kill-gate` and `commit-authorship-gate` read no config piece (`grep -l toolkit_config global/hooks/*` lists neither); their denies are built in. `toolkit_config.load` docstring: a missing or corrupt file falls back to the piece's defaults "so hooks fail open" (G-05) |
| 4 | Tasks against the standing rules of this phase | Task 6.2 needs the whole-tree test discovery, which P2 does not run; it belongs to the regression phase (G-08) |
| 5 | Stop check | No new FACT gap |
| 6 (P4, round 1, post-apply) | Hook probed in-process with everyday commands that hold `mail` or `smtp`, and with compound commands | Look-alikes (`npm run mail:test`, `docker compose logs mailpit`, `grep SMTP_HOST .env`, a Mailpit API `curl`, `pip install secure-smtplib`) pass; but `for …; do sendmail …; done`, `if …; then sendmail …; fi`, `{ sendmail …; }` and `! sendmail …` passed (G-12). Task 5.3 named a `verify --override` flag that does not exist (G-13). Both closed in this round |
| 7 | Stop check | No new FACT gap |
| 8 (P4 confirm, independent) | Adversarial probe of the hook as a subprocess, temporary `HOME`, synthetic payloads (see «Adversarial log») | 133 send attempts: 40 passed (G-14…G-20); 83 must-pass attempts: 0 false positives. All 40 fixed in the hook; 28 pinned in three new tests that fail against the previous hook (26 denied commands + 2 shell tools; checked by swapping the previous copy in and back) |
| 9 | Re-probe after the fix and stop check | 133/133 denied, 83/83 pass; one regression of the fix itself (`s-nail` missed by the cheap prefilter) found and fixed before the tests; no new FACT gap |

## Consolidated matrix

Legend: **FACT** (pending hydrate) | **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN**

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-01 | high | Must-pass look-alikes and wrapper denies missing from the spec | Before: `spec.md` «Look-alikes pass» listed 4 commands and «Mail commands are denied» had no `&&`, `;`, `|`, `env X=1`, `xargs` form. Now both lists hold every command of the brief; tests `test_bash_sends_are_denied`, `test_bash_look_alikes_and_local_mailer_pass` | HYDRATED (applied) | Bash mail commands are found at command position |
| G-02 | high | `command -v X` would deny | Before: design D5 listed `command` among skipped prefixes. Now `command -v`/`-V`, `which`, `type`, `man` are queries (D5 «Command position»); test cases `command -v sendmail`, `which msmtp`, `type mailx` | HYDRATED (applied) | same |
| G-03 | high | Interpreter marker searched in the whole command text | Before: D5 "the whole command text holds `smtplib`". Now only the interpreter's own code counts (D5, hook `interpreter_code`); tests: heredoc to `cat`, `printf … > notes.txt && python3 -m pytest`, `python3 -m unittest tests.test_smtplib_helper` pass; piped `echo … | python3` denied | HYDRATED (applied) | Inline interpreters |
| G-04 | high | Host extraction not anchored or not specified per command | Before: no `smtp://localhost@evil.example`, `localhost.evil.example`, `x.test.evil.example`, `[::1]` scenario; no `::1` in D6; scheme-less `curl --mail-rcpt … smtp.example.com` passed. Now D5 table and D6; spec «Look-alike hosts are not local»; hook `is_local`, `url_host`; test `test_local_host_match_is_anchored` and the curl, swaks, msmtp cases | HYDRATED (applied) | Local test mailer; SMTP clients |
| G-05 | med | Broken-config behaviour cited the wrong precedent | Before: D9 cited `cross-project-message-gate`. Now D9 «Why, and from where»: code defaults that deny, read from the two named gates (no config, built-in denies) and the `toolkit_config.py` docstring; tests `test_corrupt_config_never_allows_more`, `test_an_internal_exception_fails_open`; contract probe «a corrupt config still denies a send» | HYDRATED (applied) | D9 |
| G-06 | med | `mutt` sends without `-s` | Before: D5 denied `mutt` only with `-s`. Now `-s`, `-a`, `-H` or a recipient; `mutt a@example.com < f` denied, `mutt` and `mutt -f ~/Mail` pass | HYDRATED (applied) | Bash mail commands |
| G-07 | med | PHP is an interpreter with no marker | Before: markers for Python, Perl, Ruby, Node only. Now `PHPMailer` and PHP `mail(`; `php -r 'mail(…)'` denied | HYDRATED (applied) | Inline interpreters |
| G-08 | low | Task 6.2 could not be ticked in this phase | `tasks.md` 6.2 now runs the installer test; the whole-tree discovery stays with the regression phase of `run-spec` | HYDRATED (applied) | task 6.2 |
| G-09 | low | One table over tool-name suffixes, with non-mail look-alikes | Spec «Every default write tool» (27 names) and «Non-mail look-alikes»; test `test_connector_table_over_tool_name_suffixes` (synthetic server names only) | HYDRATED (applied) | Connector write tools |
| G-12 | high | A send inside a compound command passed | In-process probe (iteration 6): the matcher returned no category for `for f in *; do sendmail -t < $f; done`, `if …; then …`, `{ …; }`; the reserved word was read as the command word. Now `do`, `then`, `else`, `elif`, `if`, `while`, `until`, `{`, `!` are skipped (D5); five cases in the denied list and in spec «Mail commands are denied» | HYDRATED (applied) | Bash mail commands; D5 |
| G-13 | low | Task 5.3 named a flag that does not exist | `./install.sh verify --override "" …` exits 2 (`unrecognized arguments`); `verify --help` shows only `--target`. Task corrected; `verify --target <tmp>/.claude` gives 25 probes, 0 failures | HYDRATED (applied) | task 5.3 |
| G-14 | high | Shell-running tools other than Bash were not checked | `Monitor` (`command`) is outside the matcher and `decide()`; `mcp__…__run_in_terminal` reached the connector branch and passed with `sendmail -t < m`. Now matcher `Bash\|Monitor\|mcp__.*`, `SHELL_TOOLS`, `SHELL_MCP_TOOL`; test `test_other_shell_tools_are_checked_like_bash`; contract probe «a send through Monitor is denied» | FIXED (P4) | Indirect routes (new); D2, D13 |
| G-15 | high | A shell reading commands on stdin was not scanned | `echo 'sendmail -t < m' \| bash`, `bash <<< '…'`, `bash <<'EOF' … EOF`, `sh -s <<EOF … EOF` passed. Now `check_shell`: no `-c` and no script file → stdin and piped arguments are scanned as commands | FIXED (P4) | same |
| G-16 | high | Wrapper option clusters and other wrappers | `sudo -iu root sendmail`, `sudo -nu root sendmail`, `doas`, `eval '…'`, `su -c '…'`, `su --command=`, `find -exec/-execdir … sendmail` passed. Now `cluster_takes_value`, `doas` wrapper, `eval`, `su`, `find` branches | FIXED (P4) | same |
| G-17 | high | Clustered interpreter code options | `python3 -Ic "…smtplib…"`, `python3 -uc`, `perl -le`/`-we`, `ruby -we`, `python3 /dev/stdin <<EOF` passed (code read as a script path). Now Python `-[flags]c\|m`, Perl `-…e`, Ruby `-…e`, `STDIN_FILES` | FIXED (P4) | Inline interpreters; D13 |
| G-18 | high | Inline host decoys (anchored-host trick in code) | `smtplib.SMTP('localhost'); smtplib.SMTP(h)` and `SMTP('localhost' + '.evil.example')` / implicit concatenation passed: one local literal was enough. Now one host per connection, a literal only when it is the whole argument; any non-literal denies | FIXED (P4) | Local test mailer; D13 |
| G-19 | med | curl rerouted away from a local URL | `--connect-to localhost:25:evil…`, `--resolve`, `-x`/`--proxy`/`-x<host>` with `smtp://localhost` passed. Now `CURL_REROUTE` makes it not local | FIXED (P4) | SMTP clients; D13 |
| G-20 | med | The same programs under other names | `ssmtp`, `esmtp`, `s-nail`, `mail.mailutils`, `neomutt -s`, `msmtpq`, `git send-email` (also `git -C x send-email`, `--smtp-server=/usr/sbin/sendmail`) passed. Now name families and `check_git` (a local `--smtp-server` passes) | FIXED (P4) | Indirect routes; D13 |
| G-10 | low | Deny text names chat and file | Spec «The deny says what to do»; every deny in the tests asserts `chat`, `file`, `correo-solo-lectura.md` | ALREADY | — |
| G-11 | low | An internal exception fails open, separate test | Task 4.2; test `test_an_internal_exception_fails_open` | ALREADY | — |

## Out of v1 (does not block APPLY)

- Sends from inside a script file, a module, a container or a remote host, and commands built at run time (design
  «Known limits»).
- INFERENCE (P4, not fixed, documented in the hook docstring and design «Known limits»): project runners (`uv run`,
  `poetry run`, `npx`), `bash send.sh`, `source`, curl `-K` config files and curl proxy environment variables
  (`ALL_PROXY=… curl smtp://localhost`). They need a file's content or a runner's semantics; `extra_commands` covers a
  project's own scripts.

## Adversarial log (P4 confirm review)

Hook run as a subprocess, `HOME`, `CLAUDE_TOOLKIT_CONFIG_DIR` and `MAIL_SEND_GATE_STATE` in a temporary folder, one
synthetic `PreToolUse` payload per case. Previous hook = the copy installed by the apply phase's temporary-HOME check.

| Family | Tried (must deny) | Passed before the fix |
|---|---|---|
| Plain and separators | `sendmail`, `ls&&sendmail`, `ls;sendmail`, `cat m\|sendmail`, `(sendmail …)`, `time`, `nice -10` | 0 |
| Quoting and paths | `"sendmail"`, `s'end'mail`, `\sendmail`, `/usr/sbin/sendmail`, `/usr/lib/sendmail` | 0 |
| Substitutions | `"$(sendmail …)"`, backticks, `bash -c "echo \$(sendmail …)"` | 0 |
| Wrappers | `env X=1`, `env -i`, `sudo`, `sudo -E`, `sudo --`, `sudo -iu root`, `sudo -nu root`, `doas`, `doas -u`, `xargs -I{}`, `xargs -0`, `su -c`, `su --command=`, `find -exec`, `find -execdir`, `eval '…'`, `eval "…"` | 10 |
| Shells | `bash -c`, `sh -c`, `bash -lc`, `bash -o pipefail -c`, `echo … \| bash`, `bash <<<`, `bash <<EOF`, `sh -s <<EOF` | 4 |
| Programs | `mail`, `mailx`, `mutt -s`, `mutt -sx`, `mutt --`, `neomutt`, `s-nail`, `mail.mailutils`, `ssmtp`, `msmtpq`, `git send-email` ×3 | 8 |
| SMTP clients and hosts | msmtp/swaks/curl remote or missing; `smtp://localhost@evil.example`, `localhost.evil.example`, `x.test.evil.example`, `#@localhost`, upper-case scheme, two URLs, `--url`, `--connect-to`, `--resolve`, `-x`, `--proxy=`, `-x<host>` | 5 |
| Inline code | Python `-c`, `-c<code>`, `-Ic`, `-uc`, `-` heredoc, here-string, `/dev/stdin`, piped heredoc, decoy local literal, `+` and implicit concatenation, `SMTP()` + `.connect('evil')`, `host=` kwarg, `os.environ` host; Perl `-e`, `-le`, `-we`, `-M`; Ruby `-e`, `-we`; Node literal, variable host, look-alike host; PHP `mail(`, PHPMailer `Host`; `sudo python3 -c`, nested `bash -c "python3 -c …"` | 9 |
| Shell tools | `Monitor` (`sendmail`, `bash -c 'sendmail'`) and `mcp__…__run_in_terminal` (`sendmail`, `curl smtp://evil`) | 4 |
| Connector writes | send, reply, reply_all, forward, create/update/delete/send draft, label/unlabel message and thread, update_message_labels, apply_sensitive label, create/delete label, trash/untrash, mark/unmark spam, under `mailsrv`, an opaque id, `claude_ai_Gmail`, `plugin_gmail_gmail`, `gmail`, mixed case | 0 |
| **Total** | **133** | **40** |

Must pass (83 tried, 0 denied before or after): `global/scripts/mailbox …`, `mailbox search`, `python3 -m unittest
…test_mail_send_gate`, `grep -r sendmail .`, `grep -rn "mail -s" docs/`, `git commit -m "… sendmail …"`, `git log
--grep send-email`, `echo '{"command":"sendmail x"}' \| python3 …` and `\| jq .`, `which msmtp`, `which sendmail mail`,
`command -v mutt`, `type -a mailx`, `man mail`, `man 1 sendmail`, `whereis`, heredocs with `smtplib` written by `cat >`
and `tee`, `ls ~/mail`, `ls mail/`, `cd mail && ls`, `mkdir -p mail`, `cat mail.log`, `vim mail.txt`, `rg smtplib`,
`echo sendmail`, `printf … sendmail`, `git grep smtplib`, `python3 -m pytest … -k smtp`, `python3 scripts/send_report.py`,
`npm run mail:preview`, Mailpit logs and API, the local mailer through curl, swaks, msmtp, Python (`SMTP()` then
`.connect('localhost', 1025)`, `host=` kwarg), Node and PHPMailer, `git send-email --smtp-server localhost`, `find …
-exec grep`, `su -c 'ls /var/mail'`, `bash scripts/mail-report.sh`, `sudo -iu root ls /var/mail`, `eval "$(ssh-agent
-s)"`, `mutt -f`, `neomutt -f`, `pip show secure-smtplib`, `apt-cache show msmtp`, `journalctl … \| grep mail`; every
mail read tool (search_threads, get_message, get_thread, list_drafts, get_draft, list_labels,
download_gmail_attachment); non-mail look-alikes (`trash_file`, `create_file`, `share_file`, `delete_event`,
`create_event`, `update_event`, the app's `mcp__ccd_session_mgmt__send_message` and `start_session`, a docs
connector's `delete`, `delete_scheduled_task`); `Monitor tail -f mail.log`, `run_in_terminal npm run dev`.

Also confirmed by the piece tests: `drafts` defaults to false and `true` opens only `create_draft` and `update_draft`
(`send_draft`, `delete_draft`, `send_message` stay denied); an exempt folder lets Bash through and never a connector;
an exception inside the hook lets the call through (exit 0, no output, traceback logged); every deny names the chat,
a file and the rule; the rule is 7 lines (title, blank, 5 generic bullets); `privacy-check --require-private` finds
nothing in the changed files.

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (spec, design, code and tests applied in round 1) | 11 |
| FIXED in the P4 confirm review (spec D13, code, tests) | 7 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 3 |

Gaps pending (mejora + apply): 0
