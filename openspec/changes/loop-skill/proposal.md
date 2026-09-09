# Proposal — loop-skill (`/run-spec`)

> **Created by:** `/prepara-tarea loop-skill` — 2026-09-08  
> **Status:** EXPLORE → PROPOSE → HYDRATE → VERIFY complete; **no implementation in this turn**.

## Why

The toolkit already ships every OpenSpec phase as a separate command: `/prepara-tarea` (bootstrap), `/repasa-spec` (gaps → hydrate → apply → gaps), `/ejecuta-tests-reporte` (scoped tests), `/verifica-tarea` (scenario matrix), `/finaliza-spec` (commit + archive). Consumer projects add their own `/deploy` (FACT: `vitalcigar.es/.claude/commands/deploy.md`, `app-residuos-oscar/.claude/commands/deploy.md`).

What is missing is the **top layer**: a single entry point that takes an idea (`slug` + description) and drives the whole lifecycle **unattended** until the feature is specified, implemented, gap-free, tested, regression-free and deployed — or until an honest, machine-readable blocker stops it. Today the developer has to:

- run `/prepara-tarea`, then `/repasa-spec`, then read `GAPS.md` by hand to see whether `Gaps pending (mejora + apply): N` reached `0`;
- re-run `/repasa-spec` manually while gaps or unchecked tasks remain;
- decide when a task is "pending only because it needs production" versus "pending because it is not done";
- run the feature tests and the regression suite as separate commands;
- invoke the project deploy command by hand.

Each of those steps is a context switch and a chance to skip a gate. The request (user text, verbatim intent) is a **loop**: prepare → review → *ask whether gaps remain and orchestrate until they are resolved* → final review → feature tests → no regressions → unattended deploy. It is the developer's own version of Claude Code **loops** (`/loop` skill + `ScheduleWakeup` self-pacing), so the design should reuse those primitives instead of a bespoke poll.

## What Changes

- New command **`/run-spec <slug> [--no-deploy] [--max-iter N]`** with the description on the following line(s), in both toolkits (`.claude/commands/run-spec.md`, `.cursor/commands/run-spec.md`).
- New skill **`run-spec`** (`.claude/skills/run-spec/SKILL.md`, `.cursor/skills/run-spec/SKILL.md`) plus the Cursor L2 rule `.cursor/rules/run-spec-openspec-loop.mdc` (Cursor keeps rules separate; Claude Code folds rule content into the skill, per repo parity convention).
- A **persistent loop state file** `openspec/changes/<slug>/RUN-LOOP.md` (template under `docs/openspec/templates/RUN-LOOP-template.md`) written after every phase transition, so the loop survives context compaction, session restarts and `/loop` ticks, and every phase is idempotent/resumable.
- A **machine-readable gap-closure gate**: the loop reads the canonical last line of `GAPS.md` (`Gaps pending (mejora + apply): N`) and counts unchecked `tasks.md` items **excluding** those tagged with a new literal marker **`[prod-verify]`** (tasks whose verification depends on production). Gate passes only when `N = 0` and no untagged `- [ ]` remains.
- A **bounded closure loop** (default 3 iterations, `--max-iter`) that re-runs `/repasa-spec <slug>` in a fresh-context subagent until the gate passes, with a **convergence guard** (no change in `(N, unchecked)` between two iterations → `NO PROGRESS` stop).
- **Final confirm review**, then **feature tests** (`/ejecuta-tests-reporte <slug>`), then **regression suite** (project test/E2E commands from the stack rule, failures classified per `openspec-e2e-regression-guard`), then **publish** (commit + push of the current branch), and finally a **deploy gate**: the loop stops and asks the developer whether to deploy unattended or stop there. `--no-deploy` skips the gate and ends at `READY TO DEPLOY`.
- **Loops integration**: optional paced mode `/loop /run-spec <slug>` where each tick runs at most one phase and yields with `ScheduleWakeup` semantics (`noop`, `stop`, delay matched to what is actually awaited). Cursor falls back to its `/loop` monitored-shell mechanism. Inline single-turn mode remains the default.
- **Token-efficiency contract** baked into the skill: skills read once, phase work delegated to fresh-context subagents that return short structured reports, gates re-verified by `grep` on files (never by trusting a subagent claim), phases skipped when their exit gate already holds, no analysis `.md` outside the change folder.
- Documentation: `README.md`, `.claude/skills/README.md`, `.cursor/skills/README.md`, `docs/openspec/README.md`, and a `/run-spec` cross-link row in `repasa-spec` command relation tables.

## Capabilities

### New Capabilities

- `run-spec-loop`: top-level unattended OpenSpec run loop — input parsing, persistent state, strict phase order, gap-closure gate + bounded loop, `[prod-verify]` task marker, confirm review, feature tests, regression gate, deploy delegation, terminal verdicts, paced (`/loop`) mode, token-efficiency and safety rules.

### Modified Capabilities

- None of the promoted specs (`comando-verificar`, `multiagent-apply-validation`) change requirements. `repasa-spec` gains only a documentation cross-link (no behavioural change). The `[prod-verify]` marker is **new** and is honoured by `run-spec` only; existing commands ignore it (an unchecked task stays unchecked for `/finaliza-spec` and `/archiva-tarea`, by design).

## Impact

- **Toolkit files (this repo):** `.claude/commands/`, `.claude/skills/`, `.cursor/commands/`, `.cursor/skills/`, `.cursor/rules/`, `docs/openspec/templates/`, four README files.
- **Consumer projects:** nothing required. `/run-spec` resolves the deploy command, test commands and E2E suite from the **target project** (`00-openspec-stack-agnostic`). Projects without a deploy command end with `BLOCKED (no deploy command)` — never an improvised push/FTP/SSH.
- **Git authorization model (global rules):** invoking `/run-spec` authorizes **one** git mutation — the P7 commit and push of the **current** branch — and nothing else. Merge, rebase, tag, force-push and pushes to other branches remain outside any standing authorization. The **deploy itself is never unattended**: P8 stops and opens an approval dialog; only an explicit *deploy now* answer releases the project's own `/deploy` flow, which keeps its internal decision dialogs. `--no-deploy` skips the gate (P7 still publishes).
- **Propagation (follow-up, out of this change):** copies under `~/.claude/commands|skills` and consumer repos via `/exporta-spec run-spec` once the toolkit version is verified.
