# Spec Delta — llm-pool-ledger

## Purpose

Defines the record of every pool call and the figures derived from it, so that the saving is measured and the developer can see where each model was used and what it did.

## ADDED Requirements

### Requirement: One row per request
Every `ask`, whatever its outcome, SHALL write one row with: an id, the time, the caller's session, its project, its role (supervisor or child), the task kind, the member (or none), the mode, the dial level, input and output tokens, latency, the cost the gateway reports (zero when it reports none), the outcome and the verdict when the task kind has one.

#### Scenario: Refused by the gate
- **WHEN** a request is refused by the privacy gate
- **THEN** a row exists with the outcome "refused by gate", no member, zero tokens and no payload

### Requirement: The payload is kept redacted and for a bounded time
The request and the answer SHALL be stored only after redaction and SHALL be deleted after the configured number of days (default 7). With the value 0, no payload SHALL be stored. The ledger file SHALL be readable by its owner only.

#### Scenario: Retention passed
- **WHEN** a row is 8 days old with the default retention
- **THEN** its figures remain and its request and answer are gone

### Requirement: Avoided tokens are an estimate with a stated rule
Each row SHALL carry the main-model tokens it is estimated to have avoided, and the rule used: for an honoured `sleep`, the median cost of that supervisor's last 20 wakes; for a digest read in `assist`, the size of the text the main model did not read minus the size of the digest; for `shadow` rows and for every outcome that fell back, zero.

#### Scenario: Shadow row
- **WHEN** a request runs in `shadow`
- **THEN** its avoided tokens are zero

#### Scenario: No wake history
- **WHEN** a supervisor has fewer than 5 recorded wakes
- **THEN** the estimate for its honoured sleeps is marked "no baseline" and counts as zero in the totals

### Requirement: Rows are judged afterwards
A row SHALL be marked `agreed`, `missed` or `unknown` once what really happened is known: for `wake-triage`, by the supervisor at its next wake; for other task kinds, by the main model that read the answer or by a canary check. A command SHALL record the judgement by ledger id.

#### Scenario: The supervisor finds a slept event mattered
- **WHEN** a supervisor, on waking, sees that an event slept by the pool needed action earlier
- **THEN** it records `missed` for that row with one command, and the miss counts for demotion

### Requirement: Totals show spend, saving and leverage
`llm-pool status` and the console SHALL show, for today, the last 7 days and the current month, per member and in total: pool tokens spent, cost, main-model tokens avoided (raw and weighted with the configured weights for cache reads and cache writes), leverage (avoided ÷ spent), the number of requests by outcome, and the number of misses.

#### Scenario: Weighted figure
- **WHEN** the configured weight of a cache-read token is 0.1 and a sleep avoided 1 000 000 tokens of which 980 000 were cache reads
- **THEN** the weighted saving shown for that row is 118 000 token units

### Requirement: Usage is reconciled with the gateway
When the gateway exposes usage per key or per request, a command SHALL compare the ledger's tokens and cost with it for a period and report the difference. When it does not, the ledger SHALL say that its figures are its own count.

#### Scenario: Gateway reports more than the ledger
- **WHEN** the gateway's usage for the module's key exceeds the ledger's by more than 5 % in a day
- **THEN** `llm-pool doctor` reports it as a finding

### Requirement: History is paginated and filterable
`llm-pool history` SHALL return rows newest first, in pages of a given size, filtered by member, project, session, task kind, outcome, judgement and date range, with a stable cursor so that new rows do not shift a page being read.

#### Scenario: Second page while requests arrive
- **WHEN** page 2 is requested with the cursor of page 1 and ten new rows were written in between
- **THEN** page 2 continues exactly after the last row of page 1
