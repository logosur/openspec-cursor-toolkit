# OpenSpec + Cursor + Claude Code toolkit

Portable package for **OpenSpec workflows** in both **Cursor** and **Claude Code**: slash commands (`prepara-tarea`, `opsx-*`, `gaps-spec`, `repasa-spec`, …), **skills** (`SKILL.md`), documentation under `docs/openspec/`, and rules aligned with the OpenSpec lifecycle. The two toolkits are kept in parity: `.cursor/` is the original Cursor package (commands + skills + `.mdc` rules), `.claude/` is the equivalent native Claude Code package (commands + skills — Claude Code has no separate rules file, so rule content is folded into the matching skill's `SKILL.md`).

**Stack-agnostic:** this repo does not assume Drupal, DDEV, Symfony, or any specific framework. Each consuming application documents its own stack (local dev, tests, URLs) in project rules; the toolkit references those at runtime. See `.cursor/rules/00-openspec-stack-agnostic.mdc` (Cursor) / `.claude/skills/00-openspec-stack-agnostic/SKILL.md` (Claude Code).

This repository **does not** include a product `openspec/` tree (active changes, promoted specs, CLI config). That lives in each application repo that installs the OpenSpec CLI.

## Contents

| Path | Description |
|------|-------------|
| `.cursor/commands/` | Cursor commands (Spanish task aliases + English `opsx-*`; `/gaps-spec`, `/repasa-spec`). |
| `.cursor/skills/` | Workflow skills: explore, propose, apply, archive, gap analysis, pipeline (`repasa-spec`), verification, multiagent. |
| `.cursor/skills/README.md` | Skills index (OPSX ↔ ES map). |
| `.cursor/rules/` | OpenSpec rules (numbered series + workflow, multiagent, stack-agnostic). |
| `.cursor/scripts/openspec-list.sh` | List active OpenSpec changes (Markdown + HTML). |
| `.claude/commands/` | Same command set, native Claude Code slash-command frontmatter (`description`, `argument-hint`). |
| `.claude/skills/` | Same skills **plus** the former `.cursor/rules`-only content, each folded into its own `SKILL.md` (e.g. `00-openspec-stack-agnostic`, `openspec-e2e-regression-guard`, `openspec-extract-spec-from-doc`, `openspec-fix-changes-gitignore`). |
| `.claude/skills/README.md` | Skills index (OPSX ↔ ES map + stack-agnostic skill list). |
| `.claude/scripts/openspec-list.sh` | Same script, `.claude/context/` output path. |
| `docs/openspec/` | Index, master prompts, GAPS templates, operator notes — shared by both toolkits. |

## Integrate into another project

**Cursor:**

1. Copy or merge `.cursor/commands/`, `.cursor/skills/`, `.cursor/rules/`, and `docs/openspec/` into the target repo root (or use `/exporta-spec` from a repo that already has the export bundle).
2. Add a **project-stack** rule in the target (e.g. `.cursor/rules/01-project-stack-quality-gate.mdc`) with real commands, paths, and URLs for that application.

**Claude Code:**

1. Copy or merge `.claude/commands/`, `.claude/skills/`, and `docs/openspec/` into the target repo root (or use `/exporta-spec` from a repo that already has the export bundle).
2. Add a **project-stack** note in the target's `CLAUDE.md` (or a project skill) with real commands, paths, and URLs for that application.

**Both:**

3. Adjust `.gitignore` so shared toolkit paths are versioned as you prefer.
4. Install the [OpenSpec CLI](https://github.com/Fission-AI/OpenSpec) and maintain `openspec/` in the application repo.

## Recommended flow (including gap analysis)

**Manual (step by step):**

```
/prepara-tarea  →  EXPLORE / PROPOSE / HYDRATE / VERIFY
/gaps-spec      →  GAPS.md (honest multiagent loop, ≤5 iter)
/mejora-tarea   →  hydrate FACT gaps + READY TO APPLY
/aplica-tarea   →  implement tasks
/archiva-tarea  →  archive change
```

**Pipeline (unattended, sequential):**

```
/repasa-spec <slug>  →  gaps → mejora-tarea → aplica-tarea → gaps
```

Runs phases **one after another** (never in parallel) for an existing change under `openspec/changes/<slug>/`. Requires the change slug — e.g. `/repasa-spec background-permission`. Also triggered by natural language (`repasa la spec`, `full openspec pipeline`, …). See `.cursor/commands/repasa-spec.md` (Cursor) / `.claude/commands/repasa-spec.md` (Claude Code).

`/gaps-spec` also accepts natural language (`analiza gaps`, `casuísticas faltantes`, `huecos en la spec`, …).

## Publish on GitHub

1. Ensure `.gitignore` excludes local artifacts (`.cursor/context/`, `.claude/context/`, `*.zip`, export registries).
2. Commit the toolkit tree (`.cursor/` commands, skills, rules; `.claude/` commands, skills; `docs/openspec/`).
3. Create the remote and push:

```bash
cd /path/to/openspec-cursor-toolkit
git remote add origin https://github.com/<org>/openspec-cursor-toolkit.git
git push -u origin main
```

Licensed under [MIT](LICENSE).

## Reference consumer

Use a **private or public app repo** that already deploys this toolkit and defines its own stack rule (e.g. Symfony + Next.js monorepo, Drupal site, etc.). Copy `.cursor/rules/01-project-stack-quality-gate.mdc` pattern from your application — not from this toolkit.

## Origin

Extracted and generalized from production OpenSpec usage across multiple stacks (2025–2026). Gap-analysis workflow added 2026-07.
