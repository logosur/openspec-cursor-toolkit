# Tasks — agent-model-gate

## 1. Hook
- [x] 1.1 `global/hooks/agent-model-gate`: Agent/Task, start_session and advisor branches, fail open. Check: piece tests.
- [x] 1.2 Config piece `agent-model-gate` with generic defaults. Check: validator `global-*` rules.

## 2. Registration
- [x] 2.1 Core module manifest, `PreToolUse` fragment, contract with probes. Check: validator and installer tests.
- [x] 2.2 Rule `subagentes-con-modelo-explicito.md`, global `CLAUDE.md` bullet, README row.

## 3. Tests and evidence
- [x] 3.1 `test_agent_model_gate.py`: every branch (no model, sonnet, opus with and without mark, panel, fork,
  start_session, advisor below and above the cap, austerity, exempt folder, malformed input).
- [x] 3.1b Requirement change: the gate ships disabled (`enabled` false); a test pins that it allows everything and writes no state.
- [x] 3.2 `python3 scripts/validate-toolkit.py`, installer tests and `examples/override-full/try.sh` green.
- [ ] 3.3 CI `Validate toolkit` green on the branch.
