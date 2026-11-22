# Spec Delta — override-layer

## Purpose

Lets one machine and its projects personalise the toolkit without editing it: values, texts and extra pieces live in a private directory outside the repository, with a written precedence.

## ADDED Requirements

### Requirement: Override directory outside the repository
The override SHALL be read from `--override`, else `$CLAUDE_TOOLKIT_OVERRIDE`, else `~/.config/claude-toolkit/`. The toolkit SHALL work with no override.

#### Scenario: No override
- **WHEN** `install` runs and no override directory exists
- **THEN** the toolkit installs with its generic defaults

### Requirement: File precedence
For each destination, `override/files/<dest>` SHALL win over the toolkit file; otherwise the toolkit file followed by `override/append/<dest>` SHALL be installed; `remove:` in `override.yaml` SHALL drop a toolkit destination and the hooks that point to it. A file under `override/files/` with no toolkit counterpart SHALL be installed as an extra piece.

#### Scenario: Replacement
- **WHEN** the override has `files/rules/a.md`
- **THEN** the installed `rules/a.md` equals the override file

#### Scenario: Appendix
- **WHEN** the override has `append/rules/a.md`
- **THEN** the installed file is the toolkit text followed by the appendix

#### Scenario: Removal
- **WHEN** `override.yaml` lists `remove: [hooks/x-gate]`
- **THEN** `hooks/x-gate` is not installed and no `settings.json` entry points to it

### Requirement: Values per piece
Each configurable piece SHALL read only `toolkit/config/<piece>.json`, resolved at install time as defaults overlaid by `override/config/<piece>.json`; `CLAUDE_TOOLKIT_CONFIG_DIR` SHALL redirect the directory for tests. A piece without its config file SHALL fall back to the same generic defaults.

#### Scenario: Override value
- **WHEN** `override/config/worktree-location.json` sets `root`
- **THEN** the installed config has that `root` and the worktree script uses it

#### Scenario: No config file
- **WHEN** a piece runs with no config file present
- **THEN** it uses its generic defaults and does not fail

### Requirement: Contracts for replaceable pieces
Every hook and every script another piece calls SHALL have a contract in `global/contracts/`. `verify` SHALL run the contract probes against the installed piece, toolkit or override. `install` SHALL exit `3` when a piece provided by the override fails its contract, unless `--allow-contract-failures`.

#### Scenario: Faithful replacement
- **WHEN** the override replaces a hook with one that honours its probes
- **THEN** `verify` reports it as passing

#### Scenario: Broken replacement
- **WHEN** the override replaces a hook with one that exits `1` on a probe that allows only `0`
- **THEN** `install` exits `3` and names the piece and the probe

### Requirement: Override versioning is prepared, not performed
The repository SHALL ship `examples/override/` with the layout and instructions to keep an override in a private git repository; no tool SHALL create a remote repository.

#### Scenario: Template
- **WHEN** a user copies `examples/override/` to `~/.config/claude-toolkit/`
- **THEN** `install` accepts it and the README explains how to version it privately
