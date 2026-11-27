# Spec Delta — llm-pool-console

## Purpose

Defines the desktop console: a local app window where the developer sees the pool, switches models on and off, and opens the history of what each model did.

## ADDED Requirements

### Requirement: A local app window with no external dependency
`llm-pool console` SHALL start an HTTP server bound to loopback, serve static files shipped with the module, and open the page in a browser app window. The page SHALL make no request to any other host and SHALL work without network access. The installer MAY add a desktop launcher.

#### Scenario: Opening the console offline
- **WHEN** the console is opened with the network down
- **THEN** the pool view renders completely, with the gateway shown as unreachable if it is

#### Scenario: Port in use
- **WHEN** the configured port is taken
- **THEN** the command exits with an error naming the port and does not pick another one by itself

### Requirement: The pool view lists every member
The first window SHALL show one card per member with: its name and provider; its state with a switch; its power level as a 1-to-5 indicator; its description of what kind of task it is good for; the task kinds it is assigned to, each with its mode; the data class it accepts; its billing; the quota left and when it resets; tokens used today and in the last 7 days; cost today and this month; main-model tokens avoided; and its success rate and median latency.

#### Scenario: A member that is not active
- **WHEN** a member is `exhausted`, `cooldown`, `probation` or `blocked`
- **THEN** its card says which, since when, why, and when or how it returns

#### Scenario: No members
- **WHEN** the registry is empty
- **THEN** the view explains in two sentences how to connect a provider in the gateway's dashboard and how to add a member, with a link to that dashboard

### Requirement: The header shows the whole picture
Above the cards the view SHALL show: the dial with its mode (manual or following usage), a stop button, the pool tokens spent and the cost for today and the month, the main-model tokens avoided raw and weighted, the leverage, the number of misses, the monthly free quota as a bar, and the gateway's health.

#### Scenario: Stop button
- **WHEN** the developer presses stop and confirms
- **THEN** the dial shows 0, every card shows that it receives no traffic, and the audit log holds the change with `console` as the actor

### Requirement: Switches act at once and through the same rules as the commands
A switch or an assignment change in the console SHALL call the same code as the matching command, apply the same refusals with their reason shown next to the control, and take effect for the next request.

#### Scenario: Switching on a member with stale terms
- **WHEN** the developer assigns a private task kind to a member whose provider terms are stale
- **THEN** the change is refused and the card shows the reason and the date the terms were read

### Requirement: A link opens the history in a second window
Each card and the header SHALL carry a link that opens a separate window with the history, already filtered by that member when opened from a card. The history SHALL be paginated, newest first, and filterable by member, project, session, task kind, outcome, judgement and date. Each row SHALL show when, where (project and session title), what for (task kind), which member, tokens, cost, outcome and judgement.

#### Scenario: Paging
- **WHEN** the history holds 1 240 rows and the page size is 50
- **THEN** the window shows 50 rows, the position "1–50 of 1 240" and controls for the next and previous page, and a page loads without loading the rest

#### Scenario: Row detail
- **WHEN** a row is opened
- **THEN** the detail shows what the model was asked and what it answered (redacted, or "no longer kept" after retention), what the caller did with it, and the routing explanation of that request

### Requirement: The console never shows a secret
No view SHALL show the gateway key, a provider key or an unmasked payload. Provider and key management SHALL be a link to the gateway's own dashboard.

#### Scenario: Payload with a masked secret
- **WHEN** a row whose payload had a secret masked is opened
- **THEN** the mask is shown, never the value

### Requirement: Writes are protected
Every request that changes something SHALL carry a token generated when the console starts, SHALL be accepted only from the console's own origin, and SHALL be audited. Requests without the token SHALL be refused.

#### Scenario: Another local page tries to switch a model on
- **WHEN** a page from another origin posts to the console's API
- **THEN** the request is refused and nothing changes

### Requirement: Readable on a laptop screen and by keyboard
The pool view SHALL fit a 1366×768 window without horizontal scrolling, SHALL follow the system's light or dark theme, SHALL be operable by keyboard, and SHALL never use colour as the only sign of a state.

#### Scenario: State without colour
- **WHEN** a card is viewed in greyscale
- **THEN** its state is still readable as text

### Requirement: Extended views
The console SHALL offer, each behind the switch of its extension: the routing matrix (task kinds against members, with modes), scorecards per pair, the timeline of audited changes, the what-if simulator's last report, replay of a stored request on another member, and quota forecasts with recommendations.

#### Scenario: Extension switched off
- **WHEN** the replay extension is off
- **THEN** no replay control appears in the row detail
