# backlog-integration-branch Specification

## Purpose

The supervisor's backlog lists the OpenSpec changes that the project's integration branch has, even when its main
checkout lags behind that branch.

## Requirements

### Requirement: Lagging checkout reads the integration branch
When the checkout's HEAD does not contain its integration branch (`origin/HEAD`, else local `main`, else `master`),
`backlog_items` SHALL read the changes and their tasks from that branch with local git only.

#### Scenario: Changes only on the integration branch
- **WHEN** `main` has a change with open tasks that the lagging checkout's working tree lacks
- **THEN** the backlog lists it as work

#### Scenario: Archived on the integration branch
- **WHEN** a change is still in the lagging working tree but `main` archived it
- **THEN** it is not listed

#### Scenario: Only in the working tree
- **WHEN** a change with open tasks exists only in the working tree and `main` neither has nor archived it
- **THEN** it is listed

### Requirement: Up-to-date checkouts are unchanged
When HEAD contains the integration branch, or there is no repository or integration branch, the backlog SHALL be read
from the working tree exactly as before.

#### Scenario: Checkout on main with local edits
- **WHEN** HEAD is the integration branch and a tasks file has uncommitted ticks
- **THEN** the backlog reflects the working tree
