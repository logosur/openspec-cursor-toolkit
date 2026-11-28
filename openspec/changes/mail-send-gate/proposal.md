# Proposal — mail-send-gate

> **Created by:** `/prepara-tarea mail-send-gate` — phase P1 of a `/run-spec` run, on branch
> `feature/mail-send-gate` @ `a04bf82`. Nothing is implemented in this phase.

## Why

Mail is read-only for agents: an agent may search and read mail and may draft text, but the developer is the one who
sends. Today nothing enforces that. A session that holds a mail connector can call its send, reply, forward, label,
trash or spam tools, and any session can send through Bash (`sendmail`, `msmtp`, `mail`, `swaks`, `curl smtp://…`, an
inline script with an SMTP library). A written rule alone is not followed deterministically; the toolkit already
enforces comparable limits with `PreToolUse` gates (`commit-authorship-gate`, `process-kill-gate`, `agent-model-gate`).

## Current behavior (FACT, read from the tree)

- No hook in `global/hooks/` looks at mail tools or mail commands (`grep -rli "smtp\|sendmail" global/hooks` is empty).
- `global/modules/access.yaml` says its own commands (`mailbox`, `stores`) only read; it does not cover a connector's
  write tools or other commands.
- `global/scripts/lib/access/mail_connector.py` never stores a connector's server identifier; it prints the tool the
  session should call. A gate must follow the same principle: no connector id in the repository.

## What Changes

- New hook `mail-send-gate` (module `core`, `PreToolUse`, matcher `Bash|Monitor|mcp__.*`) that denies, for every session:
  1. a mail connector tool that sends or modifies (send, reply, forward, create / edit / delete / send drafts, labels,
     trash, spam), matched by configurable name patterns on the tool's own name; read tools (search, read a message or
     thread, list, download an attachment) never match;
  2. a Bash command that sends mail: `sendmail`, `msmtp`, `mail` / `mailx`, `mutt -s`, `swaks`, `curl` to an
     `smtp://` or `smtps://` URL, and an inline interpreter that uses an SMTP library.
- Always allowed: the local test mailer (an explicit SMTP target `localhost`, `127.0.0.1`, `*.localhost`, `*.test`).
- Config piece `mail-send-gate` (generic defaults, real values in the private override): `exempt_paths` (project
  folders whose own send flow is authorised), `extra_commands` (a project's own send commands, denied too), `drafts`
  (default `false`; `true` allows only creating and editing drafts, never sending), and the tool-name pattern lists.
- Short generic rule `global/rules/correo-solo-lectura.md` (5 to 8 lines), one bullet in the global `CLAUDE.md` block,
  the `core` row of `README.md` and a note in `access.yaml`.
- Contract `global/contracts/mail-send-gate.yaml` and piece tests `scripts/toolkit/tests/pieces/test_mail_send_gate.py`
  with synthetic hook inputs only.

## Scope

**Included:** the hook, its config piece, contract, settings fragment entry, rule, module manifest and docs lines,
piece tests.

**Excluded:** product code of any project; rules of other repositories; the developer's private override (its values
are set by whoever installs); a dialog or an "ask" decision (the gate only denies); commands that send from inside a
script file, a container or a remote host (see design, «Known limits»).

## Source of truth

- The orchestrator's brief for this change (private, not quoted here): gate shape, command list, local mailer,
  config keys, rule length, «done when».
- Repository conventions: `CLAUDE.md` (invariants on `global/`, privacy, temporary `HOME`), `global/hooks/agent-model-gate`
  (config loading with `load_checked`, deny JSON, logs), `global/contracts/cross-project-message-gate.yaml` (a corrupt
  config never allows more), `scripts/toolkit/tests/pieces/test_agent_model_gate.py` (subprocess tests).

## Evidence map

| Claim | Evidence |
|---|---|
| Gates live in `core` and are registered in `hooks.core.json` | `global/modules/core.yaml`, `global/settings/hooks.core.json` |
| Config pieces load through `toolkit_config.load_checked`; wrong shapes keep the default | `global/scripts/lib/toolkit_config.py` |
| Every installed hook needs a contract with probes | `scripts/validate-toolkit.py` rule `global-contract` |
| `examples/override-full` already lists `core` | `examples/override-full/override.yaml` |
| `mcp__ccd_*` tools are the desktop app's own tools (session messaging uses `…__send_message`) | `global/settings/hooks.usage.json`, `global/hooks/cross-project-message-gate` |

## Impact

- Added: `global/hooks/mail-send-gate`, `global/config/mail-send-gate.json`, `global/contracts/mail-send-gate.yaml`,
  `global/rules/correo-solo-lectura.md`, `scripts/toolkit/tests/pieces/test_mail_send_gate.py`.
- Edited: `global/modules/core.yaml`, `global/settings/hooks.core.json`, `global/CLAUDE.md`, `README.md`,
  `global/modules/access.yaml`.
- Risk: a non-mail connector tool with a mail-like name (for example a chat connector's `send_message`) is denied.
  Mitigation: patterns are configurable, app tools (`mcp__ccd_*`) are ignored by default, the deny says how to proceed.
- Risk: a false deny on Bash text. Mitigation: command-position detection, not substring search; tests pin the
  look-alikes that must pass.
