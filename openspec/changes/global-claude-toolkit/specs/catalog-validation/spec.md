# Spec Delta — catalog-validation

## ADDED Requirements

### Requirement: Global tree consistency
The validator SHALL also check the global tree: every source listed in a module manifest exists; every file under `global/` belongs to exactly one module; every hook fragment command points to a destination some enabled module installs; every hook has a contract; every rule, script or skill cited by a global piece exists in the toolkit or is declared optional in its module.

#### Scenario: Orphan file
- **WHEN** a file under `global/` is not listed by any module
- **THEN** the validator reports an `ERROR` naming the file

#### Scenario: Dangling hook
- **WHEN** a hook fragment calls a script that no module installs
- **THEN** the validator reports an `ERROR` naming the fragment and the command

### Requirement: Parity scope
Parity between `.cursor/` and `.claude/` SHALL keep applying to the per-project catalog only; skills under `global/skills/` are outside parity.

#### Scenario: Global-only skill
- **WHEN** `global/skills/foo/` exists and no `.cursor/skills/foo/`
- **THEN** no parity error is reported
