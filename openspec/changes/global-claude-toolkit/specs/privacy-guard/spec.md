# Spec Delta — privacy-guard

## Purpose

Keeps personal data out of a public repository: generic shapes are checked everywhere, private names and quotes are checked locally without being published.

## ADDED Requirements

### Requirement: Two layers
`scripts/privacy-check.py` SHALL apply the generic patterns of `scripts/privacy-patterns.yaml` and, when available, the private denylist and the private quotes (guillemet quotes of five words or more) of the override's text files. The public pattern file SHALL NOT contain names of real people, clients, projects, hosts or quotes.

#### Scenario: Generic finding
- **WHEN** a tracked file contains a public IPv4 address
- **THEN** the check exits `1` and names the file, line and pattern

#### Scenario: Private finding without echo
- **WHEN** a tracked file contains a denylist term
- **THEN** the check exits `1` and prints the denylist entry number, never the term

#### Scenario: Private quote
- **WHEN** a tracked file contains a quote that exists in the override's files
- **THEN** the check exits `1` with `private-quote`

### Requirement: Scopes
The check SHALL scan the working tree (tracked and untracked, not ignored) by default, the index with `--staged`, a commit message with `--message FILE`, and the messages and added lines of a commit range with `--range A..B`.

#### Scenario: Commit range
- **WHEN** a commit in the range adds a line with a public IP
- **THEN** the finding names the commit, file and new-file line

### Requirement: Declared exceptions
An exception SHALL live in `scripts/privacy-allow.yaml` with path, pattern and a reason; an entry without reason SHALL abort the check.

#### Scenario: Fixture
- **WHEN** a test fixture file is declared with a reason
- **THEN** its findings are not reported

### Requirement: Local strictness, CI generic
`--require-private` SHALL exit `2` when no denylist is found. CI SHALL run the tests and the generic layer on every push and pull request.

#### Scenario: Contributor without denylist
- **WHEN** `--require-private` runs on a machine without the override
- **THEN** it exits `2` and says where the denylist was expected
