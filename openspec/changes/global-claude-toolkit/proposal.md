# Proposal — global-claude-toolkit

> **Created:** 2026-11-22, from an audit (read-only) of a working personal Claude Code configuration (`~/.claude`) against this repository.
> **Status:** PROPOSE → DESIGN → TASKS written before any catalog change; implementation follows the tasks in micro-steps.

## Why

This repository was built as a **per-project catalog** (OpenSpec commands and skills copied into each application repo, Cursor first, Claude Code as a mirror). Real use has moved on:

- The skills, commands, rules, scripts and hooks that drive the work now live **once per machine**, in `~/.claude`, and apply to every project. Claude Code is the main IDE; Cursor is secondary.
- That global tree is not versioned, not installable on another machine and mixes three things: general mechanics (heavy-job semaphore, worktree placement, port leases, authorship gate, process-kill gate…), the same mechanics with one person's values baked in (paths, hosts, project names, model choices, thresholds), and pieces that only make sense for that person (their projects, clients, accounts, routines, incidents and literal quotes).
- The repository is **public**. Copying the global tree into it as is would publish personal data. Today's tree already carried some (project and client names, a home path, a client-derived example); they were removed before this change by its first commits, and a privacy check now runs before every commit and in CI.

Measured in the audit (counts only; the itemised inventory stays outside the repo because it names private things): 24 rules (2 general, 17 general with values, 5 personal) plus a detail file each (all personal: quotes and incidents); 67 skills (10 general, 27 general with values, 23 personal, 7 third-party); 26 commands (20 general, 6 personal); 58 scripts and hooks (31 general, 25 general with values, 4 personal); 21 hook entries in `settings.json`; 30 scheduled routines (all personal). No script honours `CLAUDE_CONFIG_DIR`; all of them resolve `~/.claude` through `HOME`, which makes a temporary `HOME` a faithful test bed. 22 OpenSpec skills exist both here and globally, and the copy in this repo is the newer, generalised one.

## What Changes

- **Global toolkit, Claude Code first.** New `global/` tree with the non-catalog pieces (rules, scripts, hooks, hook wiring, skills that are not part of the OpenSpec catalog, a global `CLAUDE.md`), organised in **modules** with a manifest each. The OpenSpec catalog keeps its single source in `.claude/` and is installed from there; `.cursor/` stays as the secondary Cursor package exported per project. No third copy of any file.
- **One-command installer** `./install.sh` (Python 3, stdlib + PyYAML): idempotent, `--dry-run`, backup of every file it would overwrite, `uninstall` that removes exactly what it installed and restores backups, merge of the `hooks` block of `settings.json` without touching any other key, declared and checked dependencies, a manifest of installed files with hashes.
- **Override layer** outside the repository (default `~/.config/claude-toolkit/`, or `$CLAUDE_TOOLKIT_OVERRIDE`): values per piece, file replacements, file appendices, extra pieces (skills, rules, hooks, routines), a removal list and a private privacy denylist. Written precedence. The toolkit is never edited to personalise it.
- **Values are injected, not hard-coded.** Pieces that carried one machine's values read a small per-piece configuration file through one helper; their defaults are generic.
- **Contracts for replaceable pieces.** A piece that an override may replace declares its contract (arguments, exit codes, output format); `verify` probes the installed piece, whoever provided it.
- **Privacy guard** (already landed at the start of this change): generic patterns in the repo and CI, private denylist and private quotes from the local override, run on the tree, the index, commit messages and commit ranges.
- **Sync and drift:** `drift` compares the live `~/.claude` with what an install would produce; `pull` brings a live improvement back to the override, or to the toolkit only through the privacy guard; overridden files remember the toolkit version they were based on.
- **Equivalence check:** install toolkit + override into a temporary `HOME` and compare with the live tree; every difference must fall in a declared class, and the report states how much of the tree comes from the toolkit and how much from the override.
- **SOLID applied as design criteria** (design §SOLID), including a planned split of the largest supervision script into modules behind a stable entry point.
- **Validator extended** for the global tree: manifests complete, every file belongs to one module, dependencies closed (each cited rule, script or hook exists or is declared optional), hook wiring points to installed files, contracts present for replaceable pieces.
- **Docs:** `README.md` and `CLAUDE.md` rewritten around "global toolkit, Claude Code by default, Cursor secondary": install, override, privacy, sync.

## Scope of this change

- **In:** the mechanism (installer, override layer, config helper, contracts, privacy guard, drift, equivalence), the `openspec` module (from `.claude/`), a `core` module with the general pieces that pass the privacy guard and their own tests, the developer's private override prepared outside the repo, and the equivalence measured on a temporary `HOME`.
- **Out, planned in tasks with acceptance criteria:** publishing the **supervision** unit (session supervisor, its watcher and hooks, question queue prompt, cross-project gate, account switch, cloud tests, project pause, routines engine, and the skills and rules written around them). Those pieces are coupled to each other, to a desktop app's internal formats and to Spanish string matchers, and carry many personal quotes; they ship to the developer through the private override until the split and neutral rewrite pass their self-tests and the equivalence check.
- **Out:** third-party skills and plugins (documented as optional dependencies), skills of client origin, runtime state, secrets, migrating the real `~/.claude` to "toolkit + override" (next step, described in design), creating a private remote repository for the override (needs the developer: queued as a decision).

## Capabilities

### New Capabilities

- `global-install`: modules, installer, uninstall, settings merge, dependency checks, manifest.
- `override-layer`: override directory, precedence, per-piece configuration, contracts for replaceable pieces.
- `privacy-guard`: generic and private layers, scopes, exit codes, CI.
- `toolkit-sync`: drift, pull, base-hash tracking, equivalence check.

### Modified Capabilities

- `catalog-validation` (change `toolkit-catalog-validation`): the validator also checks the global tree; parity still applies to the per-project catalog.

## Impact

- New: `install.sh`, `global/`, `scripts/toolkit/`, `scripts/privacy-*`, `examples/override/`, tests.
- Changed: `README.md`, `CLAUDE.md`, `scripts/validate-toolkit.py` and its tests, CI workflow.
- Unchanged: every command and skill under `.claude/` and `.cursor/` keeps its name and content (only privacy fixes); the external exporter and its bundles keep working; consumers need nothing. A project that already has project-level copies of the OpenSpec skills can keep them or delete them after installing the global toolkit (README → Migration).
- Git: commits on the change branch only; integration and push wait for the security audit the developer asked for.
