# Proposal: lean-mode

**Documentation only. No command changes its behaviour.** This change writes
down how to run the toolkit's multi-agent phases without spending a week's
model budget in a day, from a week of measured use.

## Why

Issue [#2](https://github.com/logosur/openspec-cursor-toolkit/issues/2). Run
as the skills describe, with the orchestrator fanning out parallel subagents,
phases 0 to 3 for two capabilities spent 65% of a weekly Claude Code budget by
the next morning. The causes were plain in the transcripts: parallel agents
re-read the same files and re-explored the repository from scratch, agents
waited on long test suites by polling, and the supervisor re-ran every layer
when a change touched one. Nothing in the skills or the operator notes
mentions budget, so nothing stopped the run before the counter did.

The same phases run serially, one agent at a time with a context packet, the
orchestrator running suites in a background shell and a supervisor scoped to
the layers a change touched, cost 2 to 3% of the weekly counter per pass
regardless of the agent's token count. One capability end to end went from
about 32% to 12 to 15%.

## What Changes

- `docs/openspec/README.md`: a section "Budget and the lean mode" with the
  measured costs, the three usage counters, and seven operating rules.
- `multiagente` (both toolkits): serial delegation with a context packet is
  the default; parallel fan-out is an explicit opt-in; the delegate never
  commits or pushes.
- `openspec-gap-analysis` (both toolkits): the mandatory multi-agent line
  becomes the lean form by default.
- `harness-spec` (both toolkits): the supervisor is scoped by default to the
  layers the change touched; two new prohibitions, a scenario counted as
  covered by a test never seen failing, and a delegate that commits.
- No `.cursor/rules` or command file changes.

## Capabilities

### New Capabilities

- `operator-budget`: what the toolkit tells an operator about cost and
  delegation before and during a run.

### Modified Capabilities

(none)

## Impact

Documentation under `docs/openspec/` and three `SKILL.md` files in each of
`.claude/skills/` and `.cursor/skills/`. Consumers who copied the toolkit
earlier see the change on their next sync.
