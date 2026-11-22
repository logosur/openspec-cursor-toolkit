# Spec Delta — toolkit-sync

## Purpose

Keeps the live configuration, the private override and the public toolkit aligned without manual copying, and proves that toolkit + override reproduce the live configuration.

## ADDED Requirements

### Requirement: Drift report
`drift` SHALL compare the live target with the install plan, without writing, and classify each managed path as `in-sync`, `live-changed`, `toolkit-changed`, `override-base-changed` or `untracked`, excluding the globs declared in `override.yaml: excluded`.

#### Scenario: Live edit
- **WHEN** an installed file is edited in the live target
- **THEN** `drift` reports it as `live-changed`

#### Scenario: Toolkit base moved under an override
- **WHEN** a toolkit file changes after the override copied it into `files/`
- **THEN** `drift` reports `override-base-changed` for it

### Requirement: Pull
`pull <dest>` SHALL copy the live file into `override/files/<dest>` and record the toolkit base hash; `pull <dest> --to toolkit` SHALL write it to its toolkit source only when the privacy guard passes on the new content.

#### Scenario: Private by default
- **WHEN** `pull rules/a.md` runs
- **THEN** the live file is in the override and the toolkit is unchanged

#### Scenario: Refused publication
- **WHEN** `pull rules/a.md --to toolkit` runs and the content has a denylist term
- **THEN** nothing is written and the command exits `1`

### Requirement: Equivalence check
`equivalence --live DIR` SHALL install toolkit + override into a new temporary `HOME`, compare the managed scopes with `DIR`, assign each path exactly one class (`identical`, `override`, `toolkit-newer`, `injected`, `neutral-text`, `excluded`, `unexplained`), print counts per class and the share of managed files from toolkit vs override, and exit `1` when any path is `unexplained`.

#### Scenario: All explained
- **WHEN** every differing path is covered by a class
- **THEN** the check exits `0` and prints the counts

#### Scenario: Unexplained difference
- **WHEN** a live file differs from the install and no class applies
- **THEN** the check exits `1` and lists the path with a short diff summary
