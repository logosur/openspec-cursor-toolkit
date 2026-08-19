# OpenSpec — documentation index

This folder groups **human-authored** OpenSpec-related material. The **machine workflow** (changes, canonical specs, CLI config) lives at the repository root in **`openspec/`** in each **application** repo — do not move that tree; the `openspec` CLI and agents expect it there.

This **toolkit** repo ships commands/skills/rules only; it does not include a product `openspec/` tree.

## Layout

| Path | Purpose |
|------|---------|
| **`openspec/`** (in app repos) | Active changes (`changes/<name>/`), archived changes, root `specs/`, `config.yaml`. |
| **`docs/openspec/prompts/`** | Reusable **prompts** (master explore→verify, refactor/SOLID). |
| **`docs/openspec/templates/`** | GAPS scaffolds and examples. |
| **`docs/openspec/skills/`** | Long-form procedure notes. |
| **`.cursor/skills/`** | **Cursor Agent skills** (`SKILL.md`): task flow (`prepara-tarea`, …), `opsx-*`, verification, multiagent. |

## Stack-agnostic use

Each consuming project adds its own **stack rule** (local dev, tests, URLs). The toolkit references `00-openspec-stack-agnostic.mdc` at runtime — see `app-residuos-oscar` (Symfony + Next.js) as a reference consumer.

## Quick links

- Master prompt: [`prompts/master-openspec-prompt.md`](prompts/master-openspec-prompt.md)
- Refactor / SOLID prompt: [`prompts/refactor-solid-master.md`](prompts/refactor-solid-master.md)
- Gap analysis notes: [`skills/gap-analysis.md`](skills/gap-analysis.md)

## Cursor commands

| Invoke | Purpose |
|--------|---------|
| `/openspec-list` | List recent OpenSpec changes (`bash .cursor/scripts/openspec-list.sh [count]`) |

Project skills under `.cursor/skills/` point at **`docs/openspec/prompts/master-openspec-prompt.md`** for the bootstrap flow. When using **`/prepara-tarea`**, copy the full `## Prompt` section **through `## Mandatory closing (after VERIFY)`**.

## Troubleshooting (Cursor `/` commands)

| Step | Action |
|------|--------|
| 1 | **Reload Window** — Command Palette → `Developer: Reload Window` |
| 2 | **Root folder** — Open the repository **root** in Cursor |
| 3 | **Frontmatter** — Each command file starts with `---` YAML |
| 4 | **Search** — Type part of the name (`tarea`, `prepara`, `opsx`) |

## Conventions

- **English** in prompts and specs under `openspec/` (per project rules).
- After moving files under `docs/openspec/`, update references (grep for `docs/openspec/`).
