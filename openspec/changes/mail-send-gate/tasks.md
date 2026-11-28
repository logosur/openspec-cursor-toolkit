# Tasks — mail-send-gate

One implementer, in order. Each task has one goal and its own check; the next one starts only when the check passes.
All tests use synthetic hook inputs in a temporary `HOME` (never a real mail send). `T` below means
`python3 -m unittest scripts.toolkit.tests.pieces.test_mail_send_gate -v`.

## 1. Config and skeleton
- [x] 1.1 `global/config/mail-send-gate.json` with exactly the defaults of design D3. Check:
  `python3 -c "import json;json.load(open('global/config/mail-send-gate.json'))"` exits 0.
- [x] 1.2 `global/hooks/mail-send-gate` (executable, docstring with what it denies, config keys, known limits, state dir,
  rule path): stdin parsing, `load_checked` with `DEFAULTS` equal to 1.1, deny helper, `errors.log` /
  `decisions.log` under `MAIL_SEND_GATE_STATE`, every call allowed for now. Check: `T` with the first tests — broken
  stdin, non-object payload and an unrelated tool pass with empty stdout; a test that the shipped JSON equals the
  hook's defaults (decisions identical with the shipped file and with no file over the whole test matrix).

## 2. Connector branch (requirements: connector write tools, read tools, outside connectors, drafts)
- [x] 2.1 Split at the last `__`, `ignore_servers`, `read_tools` first, then `send_tools` (design D4). Check: `T` —
  one table over tool-name suffixes: every write tool of the spec denied under `mcp__mailsrv__` and under an
  opaque-id server, every read tool of the spec passes, the non-mail look-alikes (`trash_file`, `create_file`,
  `share_file`, `delete_event`, `create_event`) pass; `mcp__ccd_session_mgmt__send_message`, `Read`, `Edit` pass; an override `send_tools` matching
  `get_message` still lets it pass.
- [x] 2.2 `drafts` (design D8) and the drafts-off sentence in the reason. Check: `T` — default denies `create_draft`
  with the drafts sentence; `drafts: true` allows `create_draft` and `update_draft` and denies `send_draft`,
  `delete_draft`, `send_message`.
- [x] 2.3 Bad config values: wrong shapes keep defaults; a pattern that does not compile is skipped and logged. Check:
  `T` — `send_tools: ["(", "^send_message$"]` still denies and `errors.log` names `(`; `drafts: "yes"` behaves as
  false; a corrupt config file denies `send_message`.

## 3. Bash branch (requirements: Bash commands, local mailer, exempt and extra)
- [x] 3.1 Quote-aware simple-command splitter, heredoc cut-out, substitutions, command position (assignments,
  wrappers with their options, `command -v` and other queries, basename, `sh|bash|zsh|dash -c`) with `sendmail`,
  `mail`, `mailx`, `mutt` (design D5). Check: `T` — every command of the spec's «Mail commands are denied» is denied
  and every command of «Look-alikes pass» passes.
- [x] 3.2 Host extraction for `msmtp --host`, `swaks --server|-s`, `curl smtp(s)://` and the local-host rule (design D6).
  Check: `T` — the spec's remote or missing targets and look-alike hosts denied, its local targets (`[::1]`,
  `a.localhost`, `b.test` included) pass, `curl https://example.com/smtp` passes.
- [x] 3.3 Inline interpreters: own code only (code option, module options, stdin heredoc, here-string or pipe when no
  script or module runs), markers (PHP included) and host literals (design D5). Check: `T` — every command of the
  spec's «Inline sends are denied» denied, every command of «Not an inline send» passes, a literal `.test` host
  passes, local plus remote literals denied.
- [x] 3.4 `exempt_paths` (by resolved `cwd`, Bash only) and `extra_commands` (design D7). Check: `T` — the three
  scenarios of the spec's «Exempt projects and extra commands» requirement, with `allow-exempt` in `decisions.log`.

## 4. Reason and logs (requirements: deny text, never logs content)
- [x] 4.1 Final reason text (design D11) and log lines without command text (design D10). Check: `T` — every deny
  carries `mail-send-gate:`, `chat`, `file`, `correo-solo-lectura.md`; after denying
  `echo secret-body | mail -s s a@example.com`, `decisions.log` has one line with neither `secret-body` nor
  `a@example.com`; plain allows write no file.
- [x] 4.2 An internal exception fails open. Check: `T` — load the hook in-process with `importlib` (SourceFileLoader),
  patch its decision function to raise, run its `main()` on a synthetic send input: exit 0, empty stdout, traceback
  in `errors.log`.

## 5. Registration and docs (requirement: installed and documented by core)
- [x] 5.1 `global/modules/core.yaml`: file entry (`mode: "0755"`), `mail-send-gate` in `config`, the gate named in
  `summary`. Check: `python3 scripts/validate-toolkit.py` exits 0.
- [x] 5.2 `global/settings/hooks.core.json`: `PreToolUse` entry, matcher `Bash|Monitor|mcp__.*` (design D2). Check: validator
  exits 0 and `python3 -m unittest scripts.toolkit.tests.test_installer` passes.
- [x] 5.3 `global/contracts/mail-send-gate.yaml` with probes: unrelated tool passes; connector send denied; connector
  read passes; `mcp__ccd_session_mgmt__send_message` passes; `sendmail` denied; `curl smtp://localhost:1025` passes;
  corrupt config still denies a send; unparseable stdin fails open. Check: validator exits 0 and
  with `HOME=<tmp>`, `./install.sh install --override "" --modules core --target <tmp>/.claude` then
  `./install.sh verify --target <tmp>/.claude` exit 0 (`verify` takes no `--override`) and the probe count includes
  the new ones (25 for `core` at apply; 26 after the confirm review added the Monitor probe).
- [x] 5.4 `global/rules/correo-solo-lectura.md` (Spanish, 5 to 8 lines including the title, design D12) and one
  bullet in `global/CLAUDE.md` «Autonomía y seguridad» citing it. Check: `wc -l` between 5 and 8; validator exits 0.
- [x] 5.5 `README.md` core row names `mail-send-gate`; `global/modules/access.yaml` gets a note that sending is denied
  for every session by core's `mail-send-gate`. Check: validator exits 0; `python3 scripts/privacy-check.py
  --require-private` exits 0.

## 6. Gates (all local, before any publication)
- [x] 6.1 `T` green (whole piece test file).
- [x] 6.2 `python3 -m unittest scripts.toolkit.tests.test_installer` green (the whole-tree discovery is the
  regression phase of `run-spec`, not this task).
- [x] 6.3 `python3 -m unittest scripts/test_validate_toolkit.py && python3 scripts/validate-toolkit.py` green.
- [x] 6.4 `bash examples/override-full/try.sh` green (installs `core`, runs the contract probes).
- [x] 6.5 `openspec validate mail-send-gate --strict` and `python3 scripts/privacy-check.py --require-private` exit 0.

## 7. Confirm-review fixes (P4, design D13)
- [x] 7.1 Indirect routes of design D13 (wrapper clusters, `doas`, `eval`, `su -c`, `find -exec`, shell stdin,
  clustered interpreter options, `/dev/stdin`, other program names, `git send-email`, rerouted curl, per-connection
  inline host literals) and the `Monitor` / `run_in_terminal` shell tools, with matcher `Bash|Monitor|mcp__.*`.
  Check: `T` — `test_confirm_review_bypasses_are_denied`, `test_confirm_review_look_alikes_pass` and
  `test_other_shell_tools_are_checked_like_bash` pass; the two deny tests fail against the hook before the fix.
