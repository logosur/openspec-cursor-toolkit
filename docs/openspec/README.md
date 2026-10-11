# OpenSpec — documentation index

This folder groups **human-authored** OpenSpec-related material. The **machine workflow** (changes, canonical specs, CLI config) lives at the repository root in **`openspec/`** in each **application** repo — do not move that tree; the `openspec` CLI and agents expect it there.

This **toolkit** repo ships commands/skills/rules (Cursor) and commands/skills (Claude Code) only; it does not include a product `openspec/` tree.

## Layout

| Path | Purpose |
|------|---------|
| **`openspec/`** (in app repos) | Active changes (`changes/<name>/`), archived changes, root `specs/`, `config.yaml`. |
| **`docs/openspec/prompts/`** | Reusable **prompts** (master explore→verify, refactor/SOLID). |
| **`docs/openspec/templates/`** | GAPS scaffolds and examples, `RUN-LOOP` state template. |
| **`docs/openspec/skills/`** | Long-form procedure notes. |
| **`.cursor/skills/`** | **Cursor Agent skills** (`SKILL.md`): task flow (`prepara-tarea`, …), `opsx-*`, verification, multiagent. |
| **`.claude/skills/`** | Same skills, native **Claude Code Agent Skills** (`SKILL.md`) — plus former Cursor-rule-only content folded in (e.g. `00-openspec-stack-agnostic`). |

## Stack-agnostic use

Each consuming project adds its own **stack rule** (local dev, tests, URLs). The toolkit references `00-openspec-stack-agnostic.mdc` (Cursor) / `.claude/skills/00-openspec-stack-agnostic/SKILL.md` (Claude Code) at runtime — see `app-residuos-oscar` (Symfony + Next.js) as a reference consumer.

## Quick links

- Master prompt: [`prompts/master-openspec-prompt.md`](prompts/master-openspec-prompt.md)
- Refactor / SOLID prompt: [`prompts/refactor-solid-master.md`](prompts/refactor-solid-master.md)
- Gap analysis notes: [`skills/gap-analysis.md`](skills/gap-analysis.md)
- Run loop state template: [`templates/RUN-LOOP-template.md`](templates/RUN-LOOP-template.md)

## Commands (Cursor and Claude Code)

| Invoke | Purpose |
|--------|---------|
| `/run-spec <slug>` + description | **Top layer** — unattended loop from idea to a published branch (prepara → repasa → gap-closure loop → confirm → tests → regression → commit + push), stopping at a **deploy-approval dialog** before the project's `/deploy`. State in `openspec/changes/<slug>/RUN-LOOP.md`; flags `--no-deploy`, `--max-iter N`. |
| `/openspec-list` | List recent OpenSpec changes (`bash .cursor/scripts/openspec-list.sh [count]` or `bash .claude/scripts/openspec-list.sh [count]`) |

Project skills under `.cursor/skills/` / `.claude/skills/` point at **`docs/openspec/prompts/master-openspec-prompt.md`** for the bootstrap flow. When using **`/prepara-tarea`**, copy the full `## Prompt` section **through `## Mandatory closing (after VERIFY)`**.

## Troubleshooting (`/` commands)

**Cursor:**

| Step | Action |
|------|--------|
| 1 | **Reload Window** — Command Palette → `Developer: Reload Window` |
| 2 | **Root folder** — Open the repository **root** in Cursor |
| 3 | **Frontmatter** — Each command file starts with `---` YAML |
| 4 | **Search** — Type part of the name (`tarea`, `prepara`, `opsx`) |

**Claude Code:**

| Step | Action |
|------|--------|
| 1 | **Restart** the `claude` session (or reopen the project) so it re-scans `.claude/commands/` |
| 2 | **Root folder** — Run `claude` from the repository **root** |
| 3 | **Frontmatter** — Each command file starts with `---` YAML (`description`, optional `argument-hint`) |
| 4 | **Search** — Type `/` then part of the name (`tarea`, `prepara`, `opsx`) |

## Conventions

- **English** in prompts and specs under `openspec/` (per project rules).
- After moving files under `docs/openspec/`, update references (grep for `docs/openspec/`).

## Budget and the lean mode (operator notes)

Measured over a week of real use with Claude Code on a C codebase (eleven
capabilities, the strongest model kept for judgment work); the full account is
[issue #2](https://github.com/logosur/openspec-cursor-toolkit/issues/2).

- Run as the skills used to describe, with parallel subagents fanned out by
  the orchestrator, phases 0 to 3 for two capabilities spent **65% of a weekly
  budget in one day**: parallel agents re-read the same files and re-explored
  the repository from scratch, agents waited on long suites by polling, and
  the supervisor re-ran every layer when a change touched one.
- The same phases run serially, **one agent at a time with a context packet**,
  cost **2 to 3% of the weekly counter per pass, regardless of the agent's
  token count** (agents of 115k, 197k, 232k and 321k tokens all read 2 to 3).
  By phase: inventory about 115k, gap analysis with live probes about 320k,
  scoped supervisor about 110k, full supervisor about 225k. One capability end
  to end: 12 to 15% instead of about 32%.

The lean mode, which the skills now recommend as the default:

1. **One agent at a time.** Before launching, write a `CONTEXT-<task>.md`
   packet: the exact files and line numbers, the commands to run, the contract
   to satisfy, the shape of the report. The agent reads the packet, not the
   repository.
2. **The orchestrator runs suites and the harness itself, in a background
   shell**, and waits for the notification. An agent waiting on a suite pays
   tokens for sleep. Never `pgrep -f` to wait on a process started from the
   same shell: it matches its own command line and never returns.
3. **Keep one persistent pre-change worktree** for RED proofs instead of
   letting each agent rebuild one.
4. **Scope the supervisor** to the layers the change touched; the full
   supervisor is for cross-cutting changes and for the close of a capability.
5. **The delegate never commits or pushes.** The orchestrator reads the diff
   line by line, runs the verification and commits. Expect to correct
   something in about one delegated change in three: in one week, a
   workaround that papered over a symptom, a test comparing against strings
   the program never prints, and a fixed delay where an event wait belonged.
6. **Count in passes, not in tokens, and read the counters after every
   pass.** There are three: a short session window, a weekly all-models
   counter, and a separate weekly counter for the strongest model. The
   per-model one binds, and the orchestrator session draws on it too.
7. **Parallel fan-out is an opt-in**, for tasks that share no files and when
   the budget has room. Say so in the plan when you choose it.

The one multi-agent step that earns its cost is the **fresh-context
supervisor** (`/harness-spec`, phase 4): in the same week it caught three
tests whose assertions could not fail, which the generating agent had reported
as passing. Keep that one; make everything else serial.
