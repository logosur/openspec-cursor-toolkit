# Spec Delta — catalog-validation

## Purpose

Turns the toolkit's catalog invariants (tree parity, frontmatter, README coverage) into one executable check that contributors run locally and CI runs on every push, so a broken rule is caught before it is exported to consumer projects.

## ADDED Requirements

### Requirement: Single validation entry point
The toolkit SHALL provide one command, runnable from the repository root with no arguments, that validates the whole catalog and exits `0` when there are no errors and `1` when there is at least one error. Warnings SHALL NOT change the exit code.

#### Scenario: Clean catalog
- **WHEN** the validator runs on a catalog that breaks no rule
- **THEN** it exits `0` and prints a summary line with the number of errors (`0`) and warnings

#### Scenario: One broken rule
- **WHEN** the validator runs on a catalog where exactly one rule is broken
- **THEN** it exits `1` and the report names the offending file path and the rule

#### Scenario: Warnings only
- **WHEN** the only findings are warnings
- **THEN** the validator exits `0` and still lists every warning with its file path

### Requirement: Report every finding in one run
The validator SHALL evaluate every rule on every file and report all findings in a single run, each as one line with severity (`ERROR` or `WARN`), file path and a message naming the rule. It SHALL NOT stop at the first error.

#### Scenario: Several errors at once
- **WHEN** two different files each break a different rule
- **THEN** one run reports both findings and exits `1`

### Requirement: Command set parity
Every command file present in `.cursor/commands/` SHALL have a file with the same name in `.claude/commands/`, and vice versa, unless the asymmetry is declared in the exceptions file.

#### Scenario: Command only in one tree
- **WHEN** `.claude/commands/foo.md` exists and `.cursor/commands/foo.md` does not, with no exception declared
- **THEN** the validator reports an `ERROR` naming `foo.md` and the tree it is missing from

### Requirement: Skill set parity
Every skill folder in `.cursor/skills/` SHALL have a folder with the same name in `.claude/skills/`, and vice versa, unless declared in the exceptions file. The four skills that Cursor ships only as rules (`00-openspec-stack-agnostic`, `openspec-e2e-regression-guard`, `openspec-extract-spec-from-doc`, `openspec-fix-changes-gitignore`) SHALL be declared there, each with a reason.

#### Scenario: Declared Claude-only skill
- **WHEN** `.claude/skills/00-openspec-stack-agnostic/` exists, has no Cursor skill folder, and is declared as Claude-only
- **THEN** the validator reports no finding for it

#### Scenario: Undeclared skill asymmetry
- **WHEN** a skill folder exists in only one tree and is not declared
- **THEN** the validator reports an `ERROR` naming the skill and the missing tree

### Requirement: Description parity across trees
A command or skill present in both trees SHALL carry the same `description` in both, unless the divergence is declared in the exceptions file with a reason.

#### Scenario: Declared divergence
- **WHEN** `exporta-spec` describes rule bundles only in the Cursor tree and the divergence is declared
- **THEN** the validator reports no finding for it

#### Scenario: Undeclared divergence
- **WHEN** a skill's `description` differs between trees with no declared exception
- **THEN** the validator reports an `ERROR` showing both descriptions

### Requirement: Frontmatter validity
Every command file, skill `SKILL.md` and Cursor rule `.mdc` SHALL open with a frontmatter block that parses as YAML into a mapping. A file without frontmatter, or whose frontmatter does not parse, SHALL be an `ERROR`.

#### Scenario: Unparseable frontmatter
- **WHEN** a skill description contains an unquoted `: ` that makes the YAML invalid
- **THEN** the validator reports an `ERROR` with the file path and the parser message

### Requirement: Allowed and required frontmatter keys
Each file kind SHALL have only the keys its tree uses today and SHALL have the required ones:
- skills (both trees): required `name`, `description`; allowed `disable-model-invocation`, `license`, `compatibility`, `metadata`;
- `.claude/commands`: required `description`; allowed `argument-hint`;
- `.cursor/commands`: required `description`; allowed `name`, `id`, `category`, `argument-hint`;
- `.cursor/rules`: required `description`, `alwaysApply`; allowed `globs`.

#### Scenario: Unknown key
- **WHEN** a skill frontmatter contains `model: opus`
- **THEN** the validator reports an `ERROR` naming the key and the allowed set

#### Scenario: Missing required key
- **WHEN** a Cursor rule has no `alwaysApply`
- **THEN** the validator reports an `ERROR`

### Requirement: Skill name matches its folder
A skill's `name` SHALL equal its folder name, and every skill and command name SHALL be kebab-case (lowercase letters, digits and single hyphens).

#### Scenario: Name drift
- **WHEN** `.claude/skills/qa/SKILL.md` declares `name: qa-report`
- **THEN** the validator reports an `ERROR`

### Requirement: Skill folders are real skills
Every folder directly under `.claude/skills/` or `.cursor/skills/` SHALL contain a `SKILL.md`, except folders declared as skill groups in the exceptions file; the skills inside a declared group SHALL be validated like top-level skills.

#### Scenario: Declared group
- **WHEN** `openspec/` holds no `SKILL.md`, is declared as a group, and contains `openspec-explore/SKILL.md`
- **THEN** no finding is reported for `openspec/` and `openspec-explore` is validated

#### Scenario: Stray folder
- **WHEN** a folder under `skills/` has no `SKILL.md` and is not a declared group
- **THEN** the validator reports an `ERROR`

### Requirement: README coverage
Each tree's `skills/README.md` SHALL mention every skill folder of that tree by its folder name, including skills inside declared groups.

#### Scenario: Skill missing from README
- **WHEN** `.claude/skills/qa/` exists and `.claude/skills/README.md` never mentions `qa`
- **THEN** the validator reports an `ERROR` naming the skill and the README

### Requirement: No dead exceptions
Every entry in the exceptions file SHALL carry a non-empty `reason` and SHALL match at least one existing file or asymmetry. An entry that matches nothing SHALL be an `ERROR`.

#### Scenario: Exception outlives its cause
- **WHEN** the exceptions file declares `foo` as Claude-only but no `foo` skill exists in either tree
- **THEN** the validator reports an `ERROR` asking to remove the entry

#### Scenario: Exception without reason
- **WHEN** an exception entry has no `reason`
- **THEN** the validator reports an `ERROR`

### Requirement: Non-blocking hygiene warnings
The validator SHALL report as `WARN`, without failing: a second frontmatter-like block (`---` … `---` holding `name:` or `description:`) at the start of a skill body; and a Cursor rule whose `description` differs from its homonym skill's.

#### Scenario: Stale inner frontmatter
- **WHEN** `aplica-tarea/SKILL.md` repeats a `---` block with `name: /aplica-tarea` right after its frontmatter
- **THEN** the validator reports a `WARN` for that file and the exit code is unaffected

### Requirement: The validator is tested
The validator SHALL ship with automated tests that build throwaway catalogs and assert, for each rule, one passing case and one failing case, plus the exit code contract.

#### Scenario: Rule without a test
- **WHEN** a contributor adds a rule to the validator without a failing-case test
- **THEN** the review checklist in the validator's documentation flags it as incomplete

### Requirement: CI runs the validator
The repository SHALL run the validator and its tests on every push and pull request, and the run SHALL fail when either fails.

#### Scenario: Pull request breaks parity
- **WHEN** a pull request adds a command to `.claude/commands/` only
- **THEN** the CI check fails and its log shows the validator's `ERROR` line
