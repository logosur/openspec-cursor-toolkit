# OpenSpec + Cursor toolkit

Portable package for **OpenSpec workflows in Cursor**: slash commands (`prepara-tarea`, `opsx-*`, `gaps-spec`, `repasa-spec`, …), **skills** (`SKILL.md`), documentation under `docs/openspec/`, and `.cursor/rules` aligned with the OpenSpec lifecycle.

**Stack-agnostic:** this repo does not assume Drupal, DDEV, Symfony, or any specific framework. Each consuming application documents its own stack (local dev, tests, URLs) in project rules; the toolkit references those at runtime. See `.cursor/rules/00-openspec-stack-agnostic.mdc`.

This repository **does not** include a product `openspec/` tree (active changes, promoted specs, CLI config). That lives in each application repo that installs the OpenSpec CLI.

## Contents

| Path | Description |
|------|-------------|
| `.cursor/commands/` | Cursor commands (Spanish task aliases + English `opsx-*`; `/gaps-spec`, `/repasa-spec`). |
| `.cursor/skills/` | Workflow skills: explore, propose, apply, archive, gap analysis, pipeline (`repasa-spec`), verification, multiagent. |
| `.cursor/skills/README.md` | Skills index (OPSX ↔ ES map). |
| `.cursor/rules/` | OpenSpec rules (numbered series + workflow, multiagent, stack-agnostic). |
| `docs/openspec/` | Index, master prompts, GAPS templates, operator notes. |
| `.cursor/scripts/openspec-list.sh` | List active OpenSpec changes (Markdown + HTML). |

## Integrate into another project

1. Copy or merge `.cursor/commands/`, `.cursor/skills/`, `.cursor/rules/`, and `docs/openspec/` into the target repo root (or use `/exporta-spec` from a repo that already has the export bundle).
2. Add a **project-stack** rule in the target (e.g. `.cursor/rules/01-project-stack-quality-gate.mdc`) with real commands, paths, and URLs for that application.
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

Runs phases **one after another** (never in parallel) for an existing change under `openspec/changes/<slug>/`. Requires the change slug — e.g. `/repasa-spec background-permission`. Also triggered by natural language (`repasa la spec`, `full openspec pipeline`, …). See `.cursor/commands/repasa-spec.md`.

`/gaps-spec` also accepts natural language (`analiza gaps`, `casuísticas faltantes`, `huecos en la spec`, …).

## Publish on GitHub

1. Ensure `.gitignore` excludes local artifacts (`.cursor/context/`, `*.zip`, export registries).
2. Commit the toolkit tree (commands, skills, rules, `docs/openspec/`).
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
