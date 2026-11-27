# Proposal — agent-model-gate

## Why

A usage audit showed that subagents launched on the most expensive model, plus calls to the advisor, took more than half of
a weekly quota in one night. The written rule (implementation subagents on the cheap model) is not followed by itself:
a subagent that names no model inherits the caller's, and nothing stops a session from asking the advisor again and again.
A deterministic gate in front of those tools is the only control that does not depend on the agent remembering.

## What Changes

- New hook `agent-model-gate` (module `core`, `PreToolUse`) with its config piece, contract, rule and tests. It ships
  **disabled** (`enabled: false`): every optimisation is authorised by the developer before it applies, so the hook allows
  everything and writes no state until the private config sets `enabled: true`.
- `Agent` / `Task` calls need an explicit `model`, except a `fork`; Opus and Fable need a written reason or the decision panel.
- `start_session` calls that carry a `prompt` need an explicit `model`; Opus and Fable ids need the same written reason.
- `advisor` calls are capped per session in a rolling 24 hours.
- An `austerity` switch denies Opus and Fable even with a reason (panel excepted) and caps the advisor at 1.

## Impact

- Added: `global/hooks/agent-model-gate`, `global/config/agent-model-gate.json`, `global/contracts/agent-model-gate.yaml`,
  `global/rules/subagentes-con-modelo-explicito.md`, `scripts/toolkit/tests/pieces/test_agent_model_gate.py`.
- Edited: `global/modules/core.yaml`, `global/settings/hooks.core.json`, `global/CLAUDE.md`, `README.md`.
- Risk: a wrongly denied call. The gate fails open on any error and every deny names the exact way to send the call again.
- UNKNOWN: whether the host fires `PreToolUse` for `advisor`. In the transcripts inspected the advisor appears as a
  `server_tool_use` block and no hook record is tied to it, so it is probably a server-side tool the client does not announce.
  The matcher is registered anyway; if the host never fires it, the cap does nothing and the rule says so.
