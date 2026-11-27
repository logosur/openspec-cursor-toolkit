# Spec Delta — llm-pool-console

## Purpose

Defines the desktop console: a local app window where the developer sees the pool, switches models on and off, and opens the history of what each model did.

## ADDED Requirements

### Requirement: A local app window with no external dependency
`llm-pool console` SHALL start an HTTP server bound to loopback only, serve static files shipped with the module, and open the page with the command the config key `console_opener` names. With the key empty, which is the default, it SHALL use the standard library's browser opener and, if that opens nothing, print the address. The page SHALL make no request to any other host and SHALL work without network access.

#### Scenario: Opening the console offline
- **WHEN** the console is opened with the network down
- **THEN** the pool view renders completely, with the gateway shown as unreachable if it is

#### Scenario: Nothing can open a page
- **WHEN** `console_opener` is empty and the machine has no browser the standard library can start
- **THEN** the command prints the address and keeps serving

### Requirement: The console server has a chosen port and a bounded life
The port SHALL be the config key `console_port`: 0, the default, means a free loopback port chosen at start. The server SHALL stop after 30 minutes without a request and with `llm-pool console --stop`.

#### Scenario: Fixed port in use
- **WHEN** the configured port is not 0 and is taken
- **THEN** the command exits with an error naming the port and does not pick another one by itself

#### Scenario: Left open overnight
- **WHEN** no request has reached the server for 30 minutes
- **THEN** the server has stopped and the page says so when it is next used

### Requirement: The launcher is installed by the piece, not by the installer
`llm-pool console --install-launcher` SHALL write a desktop entry in the user's applications directory that starts the console, and `--remove-launcher` SHALL delete it. The toolkit's installer SHALL NOT write it, and the module's notes SHALL say that uninstalling the toolkit does not remove it.

#### Scenario: Installing and removing the launcher
- **WHEN** `--install-launcher` and then `--remove-launcher` run in a temporary home
- **THEN** the entry exists after the first and is gone after the second, and nothing else outside the state directory was written

### Requirement: The pool view lists every member
The first window SHALL show one card per member with: its name and provider; its state with a switch; its power level as a 1-to-5 indicator; its description of what kind of task it is good for; the task kinds it is assigned to, each with its mode and one line saying what that task kind does; the data class it accepts; and its billing.

#### Scenario: A member that is not active
- **WHEN** a member is `paused`, `exhausted`, `cooldown` or `blocked`
- **THEN** its card says which, since when, why, and when or how it returns

#### Scenario: A pair on probation
- **WHEN** one of a member's pairs is in `probation`
- **THEN** the card shows it on that task kind, with the rows that caused it one click away

#### Scenario: No members
- **WHEN** the registry is empty
- **THEN** the view explains in two sentences how to connect a provider in the gateway's dashboard and how to add a member, with a link to that dashboard

### Requirement: Each card shows usage and cost
Each card SHALL also show: the quota left and when it resets; tokens used today and in the last 7 days; cost today and this month; main-model tokens avoided, labelled as an estimate; and the member's success rate and median latency.

#### Scenario: A member with no traffic yet
- **WHEN** a member has never served a request
- **THEN** its figures read zero and its success rate and latency read "no data", not zero

### Requirement: The header shows the whole picture
Above the cards the view SHALL show: the dial with its mode (manual or following usage) and the schedule window in force, a stop button, the pool tokens spent and the cost for today and the month, the main-model tokens avoided raw and weighted (or "not set"), the leverage, the number of false sleeps, the monthly free quota as a bar, and the gateway's health.

#### Scenario: Stop button
- **WHEN** the developer presses stop and confirms
- **THEN** the header shows the pool as stopped, every card shows that it receives no traffic, and the audit log holds the change with `console` as the actor

### Requirement: Switches act at once and through the same rules as the commands
A switch or an assignment change in the console SHALL call the same code as the matching command, apply the same refusals with their reason shown next to the control, and take effect for the next request. What the commands cannot change (caps, prices, data classes, provider terms, schedules) SHALL be shown read-only with the name of the override key that holds it.

#### Scenario: Switching on a member with stale terms
- **WHEN** the developer assigns a private task kind to a member whose provider terms are stale
- **THEN** the assignment is stored, and the card says that the member accepts `public` only, with the date its terms were read, so the pair receives nothing

### Requirement: A link opens the history in a second window
Each card and the header SHALL carry a link that opens a separate window with the history, already filtered by that member when opened from a card. The history SHALL be paginated, newest first, and filterable by member, project, session, task kind, outcome, judgement and date. Each row SHALL show when, where (project and session), what for (task kind), which member, tokens, cost, outcome and judgement.

#### Scenario: Paging
- **WHEN** the history holds 1 240 rows and the page size is 50
- **THEN** the window shows 50 rows, the position "1–50 of 1 240" and controls for the next and previous page, and a page loads without loading the rest

#### Scenario: Row detail
- **WHEN** a row is opened
- **THEN** the detail shows what the model was asked and what it answered (redacted, or "no longer kept" after retention), what the caller did with it, and the routing explanation of that request

### Requirement: Shadow answers can be reviewed
The console SHALL offer a review view that shows, for a pair of a task kind whose highest mode is `assist`, its unjudged shadow rows one at a time with the request and the answer (redacted), and records "acceptable" or "not acceptable" for each, stored in the ledger as `agreed` or `missed`. It is how the assist-only task kinds earn a promotion.

#### Scenario: Reviewing twenty digests
- **WHEN** the developer judges 20 shadow rows of a pair and 19 are acceptable
- **THEN** the pair's scorecard shows 20 samples at 95 % and the promotion control is no longer refused for lack of samples

### Requirement: The console never shows a secret
No view SHALL show the gateway key, a provider key or an unmasked payload. Provider and key management SHALL be a link to the gateway's own dashboard.

#### Scenario: Payload with a masked secret
- **WHEN** a row whose payload had a secret masked is opened
- **THEN** the mask is shown, never the value

### Requirement: Every request to the console is protected
The server SHALL generate a token when it starts and pass it to the page in the address fragment. Every API request, reads included, SHALL carry the token; a request SHALL be accepted only when its `Host` header is the loopback address with the server's own port and, when it carries an origin, that origin is the console's own. Requests that change something SHALL be audited. Anything else SHALL be refused.

#### Scenario: Another local page tries to switch a model on
- **WHEN** a page from another origin posts to the console's API
- **THEN** the request is refused and nothing changes

#### Scenario: Reading the history without the token
- **WHEN** a local process requests the history without the token
- **THEN** the request is refused and no row is returned

#### Scenario: A request through another host name
- **WHEN** a request reaches the server with a `Host` header that is not the loopback address and its port
- **THEN** it is refused

### Requirement: Readable on a laptop screen and by keyboard
The pool view SHALL fit a 1366×768 window without horizontal scrolling, SHALL follow the system's light or dark theme, SHALL be operable by keyboard, and SHALL never use colour as the only sign of a state.

#### Scenario: State without colour
- **WHEN** a card is viewed in greyscale
- **THEN** its state is still readable as text

### Requirement: Extended views appear only when their extension is on
When an extension is named in the config key `extensions`, the console SHALL offer its view: the routing matrix (task kinds against members, with modes), scorecards per pair, the timeline of audited changes, the simulator's last report, replay of a stored request on another member, and quota forecasts with recommendations. When it is off, no control of that view SHALL appear.

#### Scenario: Extension switched off
- **WHEN** the replay extension is off
- **THEN** no replay control appears in the row detail

#### Scenario: Routing matrix switched on
- **WHEN** the routing-matrix extension is on
- **THEN** a view shows every task kind against every member with the mode of each pair
