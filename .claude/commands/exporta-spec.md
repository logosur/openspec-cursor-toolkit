---
description: "Export a command or skill bundle to all OpenSpec projects under the projects base directory"
---

# Exportar spec a todos los proyectos OpenSpec

When the developer invokes **`/exporta-spec`**, **`exporta spec`**, **`exporta el comando`**, **`export bundle`**, **`exporta todos`**, or **`propaga a los proyectos`**, export the indicated **command**, **skill**, **bundle**, or **all bundles** from the **current repo** to every OpenSpec project under the projects base directory.

## Mandatory (this turn)

1. Read **`.claude/skills/exporta-spec/SKILL.md`** in the same turn before executing.
2. Resolve artifact + `PROJECTS_BASE` → build bundle → run `exporta-spec.sh` → report counts **and full target directory list**.

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
| Slug only | `/exporta-spec html` | Full bundle for slug `html` (command + skill) |
| All bundles | `/exporta-spec all`, `/exporta-spec todos` | Deploy every bundle with `bundle.manifest` (includes `exporta-spec`, `repasa-spec`, …) |
| Type + name | `/exporta-spec command html` | Only `.claude/commands/html.md` |
| Type + name | `/exporta-spec skill html` | Only `.claude/skills/html/SKILL.md` (+ siblings in folder) |
| Bundle path | `/exporta-spec bundle templates/openspec-cursor/html` | Use existing bundle dir (sync only) |
| Base override | `PROJECTS_BASE=/other/path` on next line | Override projects base (else default below) |

**Type keywords:** `command`/`comando`, `skill`, `bundle`.

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
| `<PROJECTS_BASE>/.claude-local/export-spec/projects-registry.json` | Canonical cross-project registry |
| `<PROJECTS_BASE>/.claude-local/export-spec/projects-registry.md` | Human-readable list |
| `<each-project>/.claude/context/export-spec/projects-registry.json` | Gitignored mirror per repo |

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

## Exclusion list — a project keeps its own version

A project may diverge **on purpose** (its own policy makes the generic bundle wrong there). Declare it instead of restoring files by hand after every run:

| Where | Scope |
|-------|-------|
| `<bundle>/bundle.exclude` | That bundle only — versioned next to the bundle, so the reason travels with it |
| `<ai-developer>/templates/openspec-cursor/exclude.global` | Every bundle |
| `--exclude PATTERN` (repeatable) | One run; absolute path, glob, or bare project directory name |
| `--exclude-file FILE` (repeatable) | One run, same syntax as `bundle.exclude` |

Syntax: one pattern per line, optional reason after `#`. Excluded projects are never written to and appear in `## EXPORT_EXCLUDED` with pattern, reason and the file that declared it.

**Prefer `bundle.exclude` over the flag** when the divergence is permanent: a flag is forgotten on the next run, a declared line is not. Real case: `job-offer-apply` keeps its own `cierra-sesion` because `master` is production there and each session publishes its own verified work without asking.

## Drift detection — the project edited its copy

Every deploy records the delivered `sha256` of each file under `<PROJECTS_BASE>/.cursor-local/export-spec/baselines/<project>/<slug>.sha256` (outside every repo — never inside a project, where a non-gitignored `.cursor/context/` would show it as a dirty file).

| Destination state | Action |
|-------------------|--------|
| Differs from bundle, matches the baseline | **UPDATE** — the bundle moved on; safe to overwrite |
| Differs from bundle **and** from the baseline | **DRIFT** — the project edited it; reported, **never overwritten** |
| No baseline yet, file has uncommitted local changes | **DRIFT** — treated as the project's own edit |
| No baseline yet, file clean | **UPDATE (no baseline)** — first run records one |

Drift makes the script exit **3** and list every case under `## EXPORT_DRIFT`. Three legitimate answers, never silence:

1. The project's edit is an improvement → port it to the source repo, rebuild the bundle, re-export (then it is no longer drift).
2. The divergence is intentional → add a line to `bundle.exclude` with the reason.
3. The edit is stale or wrong → re-run with `--accept-drift` (or `--force`), which discards it and says so per file.

`--check-drift` reports drift and writes nothing (implies `--dry-run`): use it before a wide export to see what you would overwrite.
`--check-drift` y `--dry-run` no escriben nada, y su informe lo dice: `Done (plan only, nothing written)`, `WRITES_PERFORMED=0` y contadores `WOULD_FILES_NEW` / `WOULD_FILES_UPDATED` / `WOULD_PROJECTS_TOUCH`. Nunca leer un log de auditoría como prueba de despliegue: solo una pasada real emite `FILES_NEW` / `FILES_UPDATED`.


## Locking — two sessions never interleave an export

Only one export of a given bundle runs at a time. A second run of the same bundle prints `WAIT: another export of '<slug>' holds the lock (…)` and continues on its own when the first finishes; different bundles may run in parallel. The shared projects registry has its own short lock.

- Locks live in `<PROJECTS_BASE>/.cursor-local/export-spec/locks/` (`<slug>.lock`, `registry.lock`), outside every repo.
- The kernel releases a lock when its holder exits or is killed, so a crashed run never leaves it stuck. The lock file records the last holder; the `WAIT` line says whether that process is still alive instead of trusting a stale record.
- `--lock-timeout SECONDS` (default 1800) bounds the wait; on timeout the script exits **4** without writing anything.
- Audits (`--check-drift`, `--dry-run`) take the lock too, so they never read a half-finished export.

Why it exists: on 2026-10-15 two sessions exported the same bundle a minute apart. Nothing broke only because the content matched; with different bundle versions one would have overwritten the other and the baselines would describe a delivery that no longer exists, which silently disables drift detection.

## Workflow (summary)

| Phase | Action |
|-------|--------|
| **0** | Lock slug (or `all`) + artifact files in **source repo** (`git rev-parse --show-toplevel`) |
| **1** | Resolve `ai-developer` + write `templates/openspec-cursor/<slug>/bundle.manifest` |
| **2** | Copy source files into bundle; add `README.md` if missing |
| **3** | `bash <ai-developer>/scripts/exporta-spec.sh --slug <slug> --projects-base "$PROJECTS_BASE"` or `--all` |
| **4** | Optional: patch `.claude/skills/README.md` in source repo docs in bundle README |

Full detail: `.claude/skills/exporta-spec/SKILL.md`.

## Script exit codes

| Code | Meaning | Agent action |
|------|---------|--------------|
| `0` | Deployed | Report `discovered=N` **and paste full `## EXPORT_TARGETS` list** + `REGISTRY` |
| `1` | Bundle/manifest error | Fix bundle, re-run |
| `2` | `ASK_PROJECTS_BASE` | Ask developer for base path; re-run with `--projects-base` |
| `4` | Timed out waiting for another export's lock | Nothing was written; the `WAIT` line says who holds it. Re-run later or raise `--lock-timeout` |
| `3` | Drift found, nothing overwritten | Read `## EXPORT_DRIFT`; port it upstream, declare it in `bundle.exclude`, or re-run with `--accept-drift` |

## Prohibited

- Exporting without a **manifest** on disk in `ai-developer/templates/openspec-cursor/<slug>/`.
- Silently changing `PROJECTS_BASE` when default is missing.
- Committing registry files under `.claude-local/` or `.claude/context/export-spec/`.
- `git commit` / `git push` unless the developer explicitly asks.

## Related

| Item | Path |
|------|------|
| Skill | `.claude/skills/exporta-spec/SKILL.md` |
| Deploy script | `ai-developer/scripts/exporta-spec.sh` |
| Discovery | `ai-developer/scripts/export-openspec-discover.sh` |
| Prior art | `export-html.sh`, `export-comando-verificar.sh` |
