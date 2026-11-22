# Spec Delta — global-install

## Purpose

Installs the toolkit into one machine's Claude Code configuration with one command, reversibly, without destroying what the user already has.

## ADDED Requirements

### Requirement: One command, modules, dry run
`./install.sh install` SHALL install the enabled modules into the target (`--target`, else `$CLAUDE_CONFIG_DIR`, else `~/.claude`). `--dry-run` SHALL print every planned action and write nothing.

#### Scenario: Dry run writes nothing
- **WHEN** `install --dry-run` runs on an empty target
- **THEN** it lists every file and hook it would add, exits `0`, and the target is still empty

#### Scenario: Fresh install
- **WHEN** `install` runs on an empty target with modules `core,openspec`
- **THEN** every file of both modules exists at its destination with the declared mode, and `toolkit/installed.json` lists each one with its sha256

### Requirement: Idempotence
A second `install` with the same inputs SHALL plan only unchanged actions and leave every file byte-identical.

#### Scenario: Re-run
- **WHEN** `install` runs twice in a row
- **THEN** the second plan has no create, update, backup or hook action

### Requirement: Backups before overwrite
A destination that exists with different content SHALL be copied to `backups/toolkit-<timestamp>/` before it is overwritten, and the manifest SHALL record the backup directory.

#### Scenario: Existing file
- **WHEN** the target already has `rules/x.md` with other content and the toolkit installs `rules/x.md`
- **THEN** the previous content is in the backup directory and the new file is installed

### Requirement: Uninstall removes only what was installed
`uninstall` SHALL remove every manifest file whose current hash equals the installed hash, keep and report files edited since, restore backups, remove the hook entries it added and delete the manifest.

#### Scenario: Round trip
- **WHEN** a target with user files gets `install` then `uninstall`
- **THEN** the target equals its state before `install`, user files included

#### Scenario: File edited after install
- **WHEN** an installed file is edited and `uninstall` runs
- **THEN** that file stays and the report names it

### Requirement: settings.json merge touches only hooks
The installer SHALL add each hook entry of the enabled fragments that is missing by `(event, matcher, command)`, SHALL preserve every other key and every existing entry, and SHALL abort without writing when `settings.json` does not parse.

#### Scenario: User keys survive
- **WHEN** `settings.json` has `model`, `permissions` and one user hook, and `install` runs
- **THEN** those keys and that hook are unchanged and the toolkit entries are present once

#### Scenario: Broken settings
- **WHEN** `settings.json` is not valid JSON
- **THEN** `install` exits `2` and writes no file

### Requirement: Dependencies are checked first
Required binaries of the enabled modules SHALL be checked before any write; a missing one SHALL make `install` exit `2` naming it. A missing optional binary SHALL produce a warning naming what will not work.

#### Scenario: Missing required binary
- **WHEN** a required binary is not on `PATH`
- **THEN** `install` exits `2`, names the binary and writes nothing

### Requirement: No system services
The installer SHALL NOT create, enable or start systemd units, cron entries or other services; module notes MAY print the command a user can run.

#### Scenario: Module with a timer note
- **WHEN** a module documents a timer
- **THEN** `install` prints the note and `systemctl` is never called
