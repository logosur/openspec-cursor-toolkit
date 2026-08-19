# OpenSpec — documentation index

This folder groups **human-authored** OpenSpec-related material. The **machine workflow** (changes, canonical specs, CLI config) lives at the repository root in **`openspec/`** in each **application** repo — do not move that tree; the `openspec` CLI and agents expect it there.

This **toolkit** repo ships commands/skills/rules (Cursor) and commands/skills (Claude Code) only; it does not include a product `openspec/` tree.

## Layout

| Path | Purpose |
|------|---------|
| **`openspec/`** (in app repos) | Active changes (`changes/<name>/`), archived changes, root `specs/`, `config.yaml`. |
| **`docs/openspec/prompts/`** | Reusable **prompts** (master explore→verify, refactor/SOLID). |
| **`docs/openspec/templates/`** | GAPS scaffolds and examples. |
| **`docs/openspec/skills/`** | Long-form procedure notes. |
| **`.cursor/skills/`** | **Cursor Agent skills** (`SKILL.md`): task flow (`prepara-tarea`, …), `opsx-*`, verification, multiagent. |
| **`.claude/skills/`** | Same skills, native **Claude Code Agent Skills** (`SKILL.md`) — plus former Cursor-rule-only content folded in (e.g. `00-openspec-stack-agnostic`). |

## Stack-agnostic use

Each consuming project adds its own **stack rule** (local dev, tests, URLs). The toolkit references `00-openspec-stack-agnostic.mdc` (Cursor) / `.claude/skills/00-openspec-stack-agnostic/SKILL.md` (Claude Code) at runtime — see `app-residuos-oscar` (Symfony + Next.js) as a reference consumer.

## Quick links

- Master prompt: [`prompts/master-openspec-prompt.md`](prompts/master-openspec-prompt.md)
- Refactor / SOLID prompt: [`prompts/refactor-solid-master.md`](prompts/refactor-solid-master.md)
- Gap analysis notes: [`skills/gap-analysis.md`](skills/gap-analysis.md)

## Commands (Cursor and Claude Code)

| Invoke | Purpose |
|--------|---------|
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
