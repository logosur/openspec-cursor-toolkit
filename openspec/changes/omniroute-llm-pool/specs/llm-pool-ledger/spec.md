# Spec Delta — llm-pool-ledger

## Purpose

Defines the record of every pool call and the figures derived from it, so that the saving is measured and the developer can see where each model was used and what it did.

## ADDED Requirements

### Requirement: One row per request
Every `ask`, whatever its outcome, SHALL leave exactly one row with: an id, the time, the caller's session, its project, its role (supervisor or child), the task kind, the member (or none), the model the gateway says answered, the mode, the level in force, input and output tokens, latency, the cost and whether the gateway reported it or the module computed it, the outcome and the verdict when the task kind has one.

#### Scenario: Refused by the gate
- **WHEN** a request is refused by the privacy gate
- **THEN** a row exists with the outcome "refused by gate", no member, zero tokens and no payload

### Requirement: The row exists before the request leaves
The row SHALL be written before any request is sent, with the outcome `pending` and the budget it reserves, and completed when the answer or the failure is known. A `pending` row older than the request's time limit SHALL be closed as `lost` by the next command, and its reservation SHALL count as spent. Concurrent writers SHALL NOT lose or corrupt rows.

#### Scenario: The process is killed mid-request
- **WHEN** an `ask` is killed after sending and before the answer arrives
- **THEN** its row exists as `pending`, the next command marks it `lost`, and its reserved tokens count against the day's budget

#### Scenario: Ten callers at once
- **WHEN** ten `ask` commands run at the same moment
- **THEN** the ledger holds ten rows and the budget counts all ten

### Requirement: The payload is kept redacted and for a bounded time
The request and the answer SHALL be stored only after redaction and SHALL be deleted after the configured number of days (default 7). With the value 0, no payload SHALL be stored. Figures SHALL be kept for the configured number of days (default 400). The purge SHALL run at the start of a command, at most once a day, with no background process. The ledger file SHALL be readable by its owner only.

#### Scenario: Retention passed
- **WHEN** a row is 8 days old with the default retention and any command runs
- **THEN** its figures remain and its request and answer are gone

### Requirement: Avoided tokens are an estimate with a stated rule
Each row SHALL carry the main-model tokens it is estimated to have avoided and the rule used, labelled "estimate" wherever shown. For an honoured `sleep` judged `agreed` it SHALL be the median cost of that supervisor's last 20 soft wakes, read from the supervisor's transcript by the simulator's reader: with 5 to 19 it SHALL be marked "thin baseline", and with fewer than 5 "no baseline", counting as zero. A `sleep` judged `missed` or left `unknown` SHALL count as zero.

#### Scenario: No wake history
- **WHEN** a supervisor's transcript holds fewer than 5 soft wakes
- **THEN** the estimate for its honoured sleeps is marked "no baseline" and counts as zero in the totals

#### Scenario: A sleep nobody judged
- **WHEN** an honoured sleep is still `unknown`
- **THEN** it adds nothing to the avoided total

### Requirement: Digests, shadow rows and fallbacks have their own rule
For a digest read in `assist`, the avoided tokens SHALL be the size of the original minus the size of the digest, and zero when the caller reports that it read the original in full. For `shadow` rows and every outcome that fell back they SHALL be zero.

#### Scenario: Shadow row
- **WHEN** a request runs in `shadow`
- **THEN** its avoided tokens are zero

#### Scenario: The session read the original anyway
- **WHEN** a session receives a digest and reports that it then read the whole original
- **THEN** that row's avoided tokens are zero

### Requirement: Rows are judged by an explicit act
A row SHALL be judged only by a command. For `wake-triage` the supervisor's judging step records whether the supervisor was `needed` or `not-needed` for that event, and the row becomes `agreed` (a `sleep` when not needed, a `wake` when needed), `missed` (a `sleep` when needed) or `overwake` (a `wake` when not needed). For other task kinds a review records acceptable (`agreed`) or not acceptable (`missed`). A row nobody judges SHALL stay `unknown` and SHALL NOT count as agreement.

#### Scenario: The supervisor finds a slept event mattered
- **WHEN** a supervisor, on waking, records that it was needed for an event the pool slept
- **THEN** the row is `missed`, and the miss counts for demotion

#### Scenario: The tick ends without judging
- **WHEN** a supervisor's tick ends and it judged nothing
- **THEN** the slept rows stay `unknown`

### Requirement: Scorecards per pair
The module SHALL compute, per pair (task kind, member), from judged rows only: the number of samples; how many were cases where the supervisor was needed; the agreement, which is the `agreed` rows divided by the judged rows; the false sleeps, which are the `missed` rows; the median latency and the tokens per request. `llm-pool status --scorecards` SHALL print them.

#### Scenario: Mostly unjudged rows
- **WHEN** a pair has 200 shadow rows and 15 of them are judged
- **THEN** its scorecard says 15 samples

#### Scenario: A model that always wakes
- **WHEN** a pair has 50 judged rows, all with the verdict `wake`, and the supervisor was needed in 10 of them
- **THEN** its agreement is 20 %

### Requirement: Totals show spend, saving and leverage, raw and weighted
`llm-pool status` and the console SHALL show, for today, the last 7 days and the current month, per member and in total: pool tokens spent, cost, main-model tokens avoided, leverage (avoided ÷ spent), the number of requests by outcome, and the number of misses. Avoided tokens and leverage SHALL be shown raw and weighted with the configured weights of cache reads and cache writes. While no weights are configured the weighted figures SHALL read "not set", never a number.

#### Scenario: Weighted figure
- **WHEN** the configured weight of a cache-read token is 0.1 and a sleep avoided 1 000 000 tokens of which 980 000 were cache reads
- **THEN** the weighted saving shown for that row is 118 000 token units

#### Scenario: Weights not measured yet
- **WHEN** the config holds no cache weights
- **THEN** the weighted columns read "not set" and the raw columns are labelled raw

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
