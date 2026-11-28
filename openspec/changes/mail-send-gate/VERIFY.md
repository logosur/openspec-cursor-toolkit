# VERIFY — mail-send-gate

> Branch `feature/mail-send-gate` @ `a04bf82`, written by `/prepara-tarea` (phase P1 of `/run-spec`). This verifies the
> documents against the code as it is now; nothing is implemented.

## Gates

| Gate | Command / check | Result |
|------|-----------------|--------|
| Artefacts present | `ls openspec/changes/mail-send-gate/` | `proposal.md`, `design.md`, `specs/mail-send-gate/spec.md`, `tasks.md`, `VERIFY.md` |
| Strict validation | `openspec validate mail-send-gate --strict` | `Change 'mail-send-gate' is valid` (exit 0) |
| Status | `openspec status --change mail-send-gate` | proposal, specs, design, tasks complete |
| Spec inventory | `grep -c '^### Requirement'` / `'^#### Scenario'` | 12 requirements / 25 scenarios |
| Tasks | `grep -cE '^[[:space:]]*- \[ \]' tasks.md` | 21 open, 0 `[prod-verify]`; none needs a push to be ticked |
| Privacy | `python3 scripts/privacy-check.py --require-private` | 0 findings (exit 0) |
| Product files untouched | `git status --short` | only `openspec/changes/mail-send-gate/` is new |

## Requirement → code → planned test

| Requirement | Code today (FACT) | Task |
|---|---|---|
| Connector write tools denied | none | 2.1 |
| Read tools never match | none | 2.1 |
| Tools outside mail connectors pass | `mcp__ccd_*` are app tools (`hooks.usage.json`, `cross-project-message-gate`) | 2.1 |
| Drafts off by default | none | 1.1, 2.2 |
| Mail commands at command position | none; splitter precedent in `process-kill-gate` | 3.1 |
| SMTP clients need a local target | none | 3.2 |
| Inline interpreters | none | 3.3 |
| Local test mailer | none | 3.2, 3.3 |
| Exempt projects, extra commands | `exempt` helper precedent in `agent-model-gate` | 3.4 |
| Deny says what to do | deny JSON precedent in `agent-model-gate` | 4.1 |
| Fails open, never logs content | `load_checked` in `toolkit_config.py`; corrupt-config probe in `cross-project-message-gate.yaml` | 2.3, 4.1, 4.2 |
| Installed and documented by core | `core.yaml`, `hooks.core.json`, validator `global-*` rules | 5.1–5.5, 6.x |

## FACT / INFERENCE / UNKNOWN

- FACT: `examples/override-full/override.yaml` already lists `core`, so no example change is needed (installer test
  `test_installer.py` line ~345 requires every module there).
- FACT: the shipped Gmail-style connector tool names used in the defaults are generic names, not identifiers; the
  server segment is never stored (same principle as `global/scripts/lib/access/mail_connector.py`).
- INFERENCE: Claude Code passes `cwd` in every `PreToolUse` input (used by `agent-model-gate` `exempt`); exemption by
  folder relies on it.
- UNKNOWN: whether other mail connectors (non-Gmail) use the same tool names; the patterns are configurable for that.
- UNKNOWN: real connectors with non-mail tools named `send_message` outside `mcp__ccd_*`; risk documented in
  `proposal.md` with the override as mitigation.

## Verdict

**READY TO APPLY** — every requirement is testable with synthetic inputs and mapped to a task; no business rule was
invented beyond the brief (design D1 and D6 record the two choices made: owner `core`, no `enabled` key and a fixed
local-host list).
