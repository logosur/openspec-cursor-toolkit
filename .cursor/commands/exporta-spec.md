---
name: /exporta-spec
id: exporta-spec
category: Tooling
description: "Export a command, skill, or rule bundle to all OpenSpec projects under the projects base directory"
---

# Exportar spec Cursor a todos los proyectos OpenSpec

When the developer invokes **`/exporta-spec`**, **`exporta spec`**, **`exporta el comando`**, **`export bundle`**, **`exporta todos`**, or **`propaga a los proyectos`**, export the indicated **command**, **skill**, **rule**, **bundle**, or **all bundles** from the **current repo** to every OpenSpec project under the projects base directory.

## Mandatory (this turn)

1. Read **`.cursor/skills/exporta-spec/SKILL.md`** in the same turn before executing.
2. Load **`.cursor/rules/comando-exporta-spec.mdc`** (L2).
3. Resolve artifact + `PROJECTS_BASE` → build bundle → run `exporta-spec.sh` → report counts **and full target directory list**.

## Mandatory reply block — target directories (always)

After every successful export (or dry-run), the agent **must** include in the chat message a section **`## Directorios exportados`** with:

1. `PROJECTS_BASE` used
2. `REGISTRY` path (local-only, gitignored)
3. `COUNT` from script (`TARGET_COUNT` / `discovered=N`)
4. **Complete numbered list** of every `TARGET:` path from the script block `## EXPORT_TARGETS` (copy verbatim from stdout — do not summarize as “29 proyectos” without the list)

Parse from script stdout:

```text
## EXPORT_TARGETS
PROJECTS_BASE=…
REGISTRY=…
SLUG=…
COUNT=…
TARGET:/absolute/path/to/project
…
```

**Prohibited:** closing export without pasting the full directory list when the script ran successfully.

## Scope parsing (human indicates target)

| Input pattern | Example | Meaning |
|---------------|---------|---------|
| Slug only | `/exporta-spec html` | Full bundle for slug `html` (command + skill + rule if present) |
| All bundles | `/exporta-spec all`, `/exporta-spec todos` | Deploy every bundle with `bundle.manifest` (includes `exporta-spec`, `repasa-spec`, …) |
| Type + name | `/exporta-spec command html` | Only `.cursor/commands/html.md` |
| Type + name | `/exporta-spec skill html` | Only `.cursor/skills/html/SKILL.md` (+ siblings in folder) |
| Type + name | `/exporta-spec rule comando-html` | Only `.cursor/rules/comando-html.mdc` |
| Bundle path | `/exporta-spec bundle templates/openspec-cursor/html` | Use existing bundle dir (sync only) |
| Base override | `PROJECTS_BASE=/other/path` on next line | Override projects base (else default below) |

**Type keywords:** `command`/`comando`, `skill`, `rule`/`regla`, `bundle`.

## Projects base (`PROJECTS_BASE`)

Default: **`$HOME/projects`** (parent directory — includes `htdocs/` and sibling repos).

Legacy alias: `HTDOCS_BASE` / `--htdocs-base` still accepted.

If that path **does not exist**, **ask the developer** (AskQuestion or explicit question in chat):

> ¿Cuál es la ruta base de tus proyectos? (ej. `$HOME/projects`)

Do **not** guess another path. Re-run with `PROJECTS_BASE=<answer>` or `--projects-base`.

## Projects registry (never commit)

The deploy script maintains a **local-only** registry of discovered OpenSpec projects:

| Location | Purpose |
|----------|---------|
| `<PROJECTS_BASE>/.cursor-local/export-spec/projects-registry.json` | Canonical cross-project registry |
| `<PROJECTS_BASE>/.cursor-local/export-spec/projects-registry.md` | Human-readable list |
| `<each-project>/.cursor/context/export-spec/projects-registry.json` | Gitignored mirror per repo |

**Never** commit registry files. Document the path in chat; do not add them to git.

## Smart update (default)

The deploy script **compares** each manifest file in every target project with the canonical bundle (`cmp -s`):

| Target state | Action |
|--------------|--------|
| File missing | **NEW** — copy from bundle |
| File exists, content differs | **UPDATE** — overwrite with bundle |
| File exists, identical content | **SKIP** — leave untouched |
| `--force` passed | **FORCE** — overwrite even when identical |

Per-project summary: `SKIP project (all files unchanged)` when every mapped file matches; `OK (touched)` when at least one file was new or updated.

Stdout includes `## EXPORT_STATS` with `FILES_NEW`, `FILES_UPDATED`, `FILES_UNCHANGED`, `PROJECTS_TOUCHED`, `PROJECTS_UNCHANGED`.

Use `--force` only when the developer explicitly wants a full re-copy (e.g. after line-ending normalization).

## Workflow (summary)

| Phase | Action |
|-------|--------|
| **0** | Lock slug (or `all`) + artifact files in **source repo** (`git rev-parse --show-toplevel`) |
| **1** | Resolve `ai-developer` + write `templates/openspec-cursor/<slug>/bundle.manifest` |
| **2** | Copy source files into bundle; add `README.md` if missing |
| **3** | `bash <ai-developer>/scripts/exporta-spec.sh --slug <slug> --projects-base "$PROJECTS_BASE"` or `--all` |
| **4** | Optional: patch `.cursor/skills/README.md` / `00-rules-priority-index.mdc` in source repo docs in bundle README |

Full detail: `.cursor/skills/exporta-spec/SKILL.md`.

## Script exit codes

| Code | Meaning | Agent action |
|------|---------|--------------|
| `0` | Deployed | Report `discovered=N` **and paste full `## EXPORT_TARGETS` list** + `REGISTRY` |
| `1` | Bundle/manifest error | Fix bundle, re-run |
| `2` | `ASK_PROJECTS_BASE` | Ask developer for base path; re-run with `--projects-base` |

## Prohibited

- Exporting without a **manifest** on disk in `ai-developer/templates/openspec-cursor/<slug>/`.
- Silently changing `PROJECTS_BASE` when default is missing.
- Committing registry files under `.cursor-local/` or `.cursor/context/export-spec/`.
- `git commit` / `git push` unless the developer explicitly asks.

## Related

| Item | Path |
|------|------|
| Skill | `.cursor/skills/exporta-spec/SKILL.md` |
| Rule | `.cursor/rules/comando-exporta-spec.mdc` |
| Deploy script | `ai-developer/scripts/exporta-spec.sh` |
| Discovery | `ai-developer/scripts/export-openspec-discover.sh` |
| Prior art | `export-html.sh`, `export-comando-verificar.sh` |
