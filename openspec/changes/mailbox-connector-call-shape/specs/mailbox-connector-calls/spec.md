# Spec Delta — mailbox-connector-calls

## Purpose

For a connector account (`kind: gmail`), `mailbox` does not read mail: it prints the call the assistant session has to make
to the mail connector. Until now that call was incomplete and unbounded: `search` printed a `pageSize` equal to `--limit`
(a value the connector refuses above 50) and no `view`, so the connector's default returned up to five messages per thread;
`show` and `thread` printed no `arguments` at all and dropped the id given on the command line; `whoami` printed no `view`.
These requirements make every printed call complete and token-bounded, so the session passes `tool` and `arguments` to the
connector verbatim and decides nothing. Related: `external-access` (capability `mailbox-access`, not archived yet, so it has
no baseline to modify: this capability only adds) and `mailbox-search-results` (its requirement "Existing output is unchanged
and costs nothing more" is modified in this change, see `specs/mailbox-search-results/spec.md`). Nothing here calls the
connector, writes to a mailbox or touches the `imap` and `local` backends.

Connector values named below (tool schema of the Gmail connector, shape measured by the orchestrator on 2026-11-27, no
content read): search `view` is one of `THREAD_VIEW_METADATA_ONLY`, `THREAD_VIEW_MINIMAL`, `THREAD_VIEW_IDS_ONLY`,
`THREAD_VIEW_SUMMARY`; `pageSize` defaults to 20 with a maximum of 50; `pageToken` continues a search; the read tool takes a
required `threadId` and a `messageFormat` that is one of `MINIMAL`, `FULL_CONTENT`, `METADATA_ONLY`, `PLAIN_TEXT` (default
`PLAIN_TEXT`).

## ADDED Requirements

### Requirement: The search call carries a bounded view
For a connector account of kind `gmail`, `mailbox search` SHALL print `arguments` with exactly the keys `query`, `pageSize`
and `view`. `view` SHALL be `THREAD_VIEW_SUMMARY` unless the account's `connector.search_view` names another of the four
known values, and the document SHALL keep its existing top-level keys (`delegate`, `kind`, `tool`, `arguments`, `read_tool`)
with their names, types and values, and exit 10.

#### Scenario: Default view
- **GIVEN** a connector account with no `connector.search_view`
- **WHEN** `mailbox search ACCOUNT --from user@example.org` runs
- **THEN** stdout is one JSON line whose `arguments.view` is `"THREAD_VIEW_SUMMARY"`, whose `arguments` keys are exactly
  `query`, `pageSize` and `view`, and the exit code is 10

#### Scenario: Per-account view
- **GIVEN** a connector account with `connector.search_view` set to `THREAD_VIEW_METADATA_ONLY`
- **WHEN** `mailbox search ACCOUNT` runs
- **THEN** `arguments.view` is `"THREAD_VIEW_METADATA_ONLY"`, and another connector account without the setting still prints
  `"THREAD_VIEW_SUMMARY"`

#### Scenario: Every known view is accepted
- **GIVEN** an account configured in turn with each of `THREAD_VIEW_METADATA_ONLY`, `THREAD_VIEW_MINIMAL`,
  `THREAD_VIEW_IDS_ONLY` and `THREAD_VIEW_SUMMARY`
- **WHEN** `mailbox search ACCOUNT` runs for each
- **THEN** each prints that value in `arguments.view` and exits 10

#### Scenario: Existing keys are untouched
- **WHEN** `mailbox search ACCOUNT --subject plan --since 2026-11-01` runs on a connector account with the default settings
- **THEN** `delegate` is `"connector"`, `kind` is `"gmail"`, `tool` is `"search_threads"`, `read_tool` is `"get_thread"`,
  `arguments.query` is `subject:plan after:2026/11/01` and `arguments.pageSize` is 20

### Requirement: The page size is capped at the connector maximum
`mailbox search` on a connector account SHALL print `arguments.pageSize` as the smaller of the requested limit (`--limit`, else
the configured default) and the page-size maximum: 50, or the account's `connector.page_size_max`. A limit below one SHALL be
cut to one, as on every backend.

#### Scenario: Within the maximum
- **WHEN** `mailbox search ACCOUNT --limit 20` runs, and when it runs with no `--limit`
- **THEN** `arguments.pageSize` is 20

#### Scenario: Exactly the maximum
- **WHEN** `mailbox search ACCOUNT --limit 50` runs
- **THEN** `arguments.pageSize` is 50

#### Scenario: Above the maximum
- **WHEN** `mailbox search ACCOUNT --limit 200` runs
- **THEN** `arguments.pageSize` is 50 and the exit code is 10

#### Scenario: Configured maximum
- **GIVEN** a connector account with `connector.page_size_max` set to 10
- **WHEN** `mailbox search ACCOUNT --limit 25` runs
- **THEN** `arguments.pageSize` is 10

#### Scenario: A limit below one
- **WHEN** `mailbox search ACCOUNT --limit 0` runs
- **THEN** `arguments.pageSize` is 1 and `paging.requested` is 1

### Requirement: A capped search says so outside the arguments
`mailbox search` on a connector account SHALL print a top-level `paging` object, never inside `arguments`, with `requested`,
`page_size` (the value in `arguments`) and `capped`. When the limit exceeds the maximum, `capped` SHALL be `true` and `paging`
SHALL also carry `continue_with` (`"pageToken"`) and `how` (one sentence: repeat the call adding the connector's `pageToken`).

#### Scenario: Not capped
- **WHEN** `mailbox search ACCOUNT --limit 20` runs, and `--limit 50`
- **THEN** `paging` is `{"requested": 20, "page_size": 20, "capped": false}` and `{"requested": 50, "page_size": 50,
  "capped": false}`, with no `continue_with` and no `how`

#### Scenario: Cap stated
- **WHEN** `mailbox search ACCOUNT --limit 200` runs
- **THEN** `paging` is `requested` 200, `page_size` 50, `capped` `true`, `continue_with` `"pageToken"` and a non-empty `how`

#### Scenario: Notice stays out of the connector's arguments
- **WHEN** `mailbox search ACCOUNT --limit 200` runs
- **THEN** `arguments` has exactly the keys `query`, `pageSize` and `view`: no `paging`, `requested`, `capped` or
  `continue_with` is inside it, so a verbatim pass sends the connector no parameter it does not know

#### Scenario: Configured maximum stated
- **GIVEN** a connector account with `connector.page_size_max` set to 10
- **WHEN** `mailbox search ACCOUNT --limit 25` runs
- **THEN** `paging` says `requested` 25, `page_size` 10, `capped` `true`

### Requirement: The read call carries the id and a message format
For a connector account of kind `gmail`, `mailbox show ACCOUNT ID` and `mailbox thread ACCOUNT ID` SHALL print one JSON
document with the keys `delegate`, `kind`, `tool` (the account's read tool), `arguments` and `note`, and exit 10.
`arguments` SHALL have exactly the keys `threadId` (the id as given, unchanged; an id that is empty or only whitespace is refused) and `messageFormat`, which is
`PLAIN_TEXT` unless the account's `connector.read_format` names another of the four known values.

#### Scenario: Default read call
- **GIVEN** a connector account with no `connector.read_format`
- **WHEN** `mailbox show ACCOUNT abc123` runs, and when `mailbox thread ACCOUNT abc123` runs
- **THEN** each prints one JSON line with `tool` equal to the account's read tool (`get_thread` by default), `arguments`
  exactly `{"threadId": "abc123", "messageFormat": "PLAIN_TEXT"}`, and exits 10

#### Scenario: The id is carried unchanged
- **WHEN** `mailbox show ACCOUNT 18f3A_c-9` runs
- **THEN** `arguments.threadId` is exactly `"18f3A_c-9"`: no case change, trimming or prefix

#### Scenario: An empty id is refused
- **WHEN** `mailbox show ACCOUNT ""` runs on a connector account, and when `mailbox thread ACCOUNT "   "` runs
- **THEN** it exits 2 with one line on stderr and nothing on stdout

#### Scenario: Per-account format
- **GIVEN** a connector account with `connector.read_format` set to `METADATA_ONLY`
- **WHEN** `mailbox show ACCOUNT abc123` runs
- **THEN** `arguments.messageFormat` is `"METADATA_ONLY"`

### Requirement: The HTML body is read only when asked for
`messageFormat` SHALL be `FULL_CONTENT` only when the account's `connector.read_format` says so or the command is given
`--full-content`, which wins over the setting. `--full-content` on an account that is not a connector account SHALL be a
usage error. No option SHALL select `MINIMAL` or `METADATA_ONLY`; they are reachable only through `connector.read_format`.

#### Scenario: Full content only on request
- **GIVEN** two connector accounts, one with `connector.read_format` set to `FULL_CONTENT` and one with no setting
- **WHEN** `mailbox show ACCOUNT abc123` runs on each, and `mailbox show ACCOUNT abc123 --full-content` runs on the second
- **THEN** the first prints `"FULL_CONTENT"`, the second prints `"PLAIN_TEXT"` without the flag and `"FULL_CONTENT"` with it,
  and no run of `show` or `thread` prints `FULL_CONTENT` for an account that has neither the setting nor the flag

#### Scenario: The flag wins over the setting
- **GIVEN** a connector account with `connector.read_format` set to `METADATA_ONLY`
- **WHEN** `mailbox thread ACCOUNT abc123 --full-content` runs
- **THEN** `arguments.messageFormat` is `"FULL_CONTENT"`

#### Scenario: The flag on another backend
- **GIVEN** an account whose backends are `imap` and `local`
- **WHEN** `mailbox show ACCOUNT ID --full-content` runs
- **THEN** it exits 2 with one line on stderr, nothing on stdout, and nothing is read

#### Scenario: No option for the cheap reads
- **WHEN** `mailbox show ACCOUNT abc123 --format MINIMAL` runs
- **THEN** it exits 2 (an unknown option) and prints no call

#### Scenario: Other options of show are accepted and change nothing
- **WHEN** `mailbox show ACCOUNT abc123 --body-chars 200 --no-quote --headers --json` runs on a connector account
- **THEN** the document and the exit code are identical to the run without those options

#### Scenario: Exit codes agree with search
- **WHEN** `mailbox search`, `mailbox show` and `mailbox thread` run on a connector account
- **THEN** all three print their document on stdout, nothing on stderr, and exit 10 (delegated to a connector)

### Requirement: Commands without a connector read call keep their output
`mailbox folders ACCOUNT` and `mailbox save ACCOUNT ID --out DIR` on a connector account SHALL print the same document as
before this change (`delegate`, `kind`, `tool`, `note`; no `arguments`) and exit 10. For a connector `kind` other than
`gmail`, `show`, `thread` and `whoami` SHALL print the document they printed before this change (no `arguments`, no `view`,
no `messageFormat`) and `search` SHALL keep refusing with exit 2.

#### Scenario: Folders and save
- **WHEN** `mailbox folders ACCOUNT` and `mailbox save ACCOUNT abc123 --out DIR` run on a connector account
- **THEN** each prints a document whose keys are `delegate`, `kind`, `tool` and `note`, and exits 10

#### Scenario: A connector kind other than gmail
- **GIVEN** a connector account with `kind` set to `other`
- **WHEN** `mailbox search ACCOUNT`, `mailbox show ACCOUNT abc123` (with and without `--full-content`) and
  `mailbox whoami ACCOUNT` run
- **THEN** `search` exits 2 with the existing "no query translation" line, `show` prints the legacy document (the same with
  and without the flag) and exits 10, and `whoami` prints the legacy call (`query`, `pageSize`, no `view`) and exits 0

### Requirement: The identity check asks for metadata only
`mailbox whoami ACCOUNT` on a connector account of kind `gmail` SHALL print as its first line the search tool and the
arguments `query` `in:sent`, `pageSize` 1 and `view` `THREAD_VIEW_METADATA_ONLY`, then its existing second line, and exit 0.
The view SHALL NOT depend on `connector.search_view`. `whoami ACCOUNT --sender ADDRESS` SHALL keep its behaviour.

#### Scenario: The check call
- **WHEN** `mailbox whoami ACCOUNT` runs on a connector account
- **THEN** the first line is `{"tool": "search_threads", "arguments": {"query": "in:sent", "pageSize": 1, "view":
  "THREAD_VIEW_METADATA_ONLY"}}`, the second line contains `mailbox whoami ACCOUNT --sender ADDRESS`, and the exit code is 0

#### Scenario: The view does not follow the search setting
- **GIVEN** a connector account with `connector.search_view` set to `THREAD_VIEW_IDS_ONLY` and `connector.page_size_max` 10
- **WHEN** `mailbox whoami ACCOUNT` runs
- **THEN** the call still has `view` `"THREAD_VIEW_METADATA_ONLY"` and `pageSize` 1

#### Scenario: The sender check is unchanged
- **WHEN** `mailbox whoami ACCOUNT --sender ADDRESS` runs with the account's address in another case, with an alias, and with
  an unrelated address
- **THEN** the first two exit 0 and the third exits 3 with a line saying the connector belongs to another mailbox

### Requirement: Connector settings are validated
When an account's backends include `connector` and its `kind` is `gmail`, a configured `connector.search_view` SHALL be one
of the four known view values, `connector.read_format` one of the four known message formats, and `connector.page_size_max`
an integer of at least 1 that is not a boolean. Matching SHALL be exact (case and spelling); nothing is normalised. An invalid value SHALL NOT fall
back silently to the default.

#### Scenario: Every valid value is accepted
- **GIVEN** `connector.read_format` set in turn to each of `MINIMAL`, `FULL_CONTENT`, `METADATA_ONLY` and `PLAIN_TEXT`
- **WHEN** `mailbox show ACCOUNT abc123` runs for each
- **THEN** each prints that value in `arguments.messageFormat` and exits 10

#### Scenario: Unknown view
- **GIVEN** a connector account with `connector.search_view` set to `THREAD_VIEW_FULL`
- **WHEN** `mailbox search ACCOUNT` runs
- **THEN** it exits 2, stdout is empty, and one stderr line names `connector.search_view` and lists the four known values

#### Scenario: Wrong case is not repaired
- **GIVEN** a connector account with `connector.read_format` set to `plain_text`
- **WHEN** `mailbox show ACCOUNT abc123` runs
- **THEN** it exits 2, stdout is empty, and the stderr line names `connector.read_format` and lists the four known formats

#### Scenario: Not a string
- **GIVEN** a connector account with `connector.search_view` set to the number 3, to an array or to the empty string
- **WHEN** `mailbox thread ACCOUNT abc123` runs
- **THEN** it exits 2 with stdout empty

#### Scenario: Absent or null is the default
- **GIVEN** connector accounts whose `connector.search_view`, `connector.read_format` and `connector.page_size_max` are absent,
  and one where each is `null`
- **WHEN** `mailbox search ACCOUNT` and `mailbox show ACCOUNT abc123` run on each
- **THEN** both exit 10 and print the defaults (`THREAD_VIEW_SUMMARY`, `PLAIN_TEXT`, a page-size maximum of 50)

#### Scenario: Page-size maximum
- **GIVEN** `connector.page_size_max` set in turn to `0`, `-5`, `2.5`, `50.0`, `true`, `"50"` and an array
- **WHEN** `mailbox search ACCOUNT` runs for each
- **THEN** each exits 2 with stdout empty and a line naming `connector.page_size_max`; the values `1` and `50` and `100` are
  accepted

### Requirement: An invalid connector setting makes the account unusable
An invalid connector setting SHALL be handled like any other mistyped account setting: the account carries an error line that
names the setting (and, for a view or a format, lists the known values); every command that picks the account (`search`,
`show`, `thread`, `folders`, `save`, `whoami`) SHALL print nothing on stdout and exit 2; `accounts` SHALL still exit 0 and
list the account as `UNUSABLE` with the reason.

#### Scenario: whoami on an unusable account
- **GIVEN** a connector account with an invalid `connector.search_view`
- **WHEN** `mailbox whoami ACCOUNT` runs
- **THEN** it exits 2 with stdout empty (the account is unusable, as for any other invalid setting)

#### Scenario: whoami with a sender on an unusable account
- **GIVEN** the same account
- **WHEN** `mailbox whoami ACCOUNT --sender ADDRESS` runs
- **THEN** it exits 2 with stdout empty (the account is picked first, as before this change for any invalid setting)

#### Scenario: accounts lists it
- **GIVEN** the same account
- **WHEN** `mailbox accounts` runs
- **THEN** it exits 0 and the account's line says `UNUSABLE` and names the setting

#### Scenario: The settings of another connector kind are not checked
- **GIVEN** a connector account with `kind` set to `other` and an invalid `connector.search_view`
- **WHEN** `mailbox accounts` and `mailbox show ACCOUNT abc123` run
- **THEN** the account is not listed as `UNUSABLE` and `show` prints the legacy document (exit 10)

#### Scenario: The settings of another backend are not checked
- **GIVEN** an account whose backends are `imap` only, with a `connector` object holding an invalid `search_view`
- **WHEN** `mailbox search ACCOUNT` runs
- **THEN** the setting is not reported (the connector is not one of its backends)

### Requirement: The connector's server identifier is never stored or printed
No document, line on stdout or stderr, configuration default, fixture or test output of the connector commands SHALL contain a
connector server identifier: only the short tool names from the configuration appear.

#### Scenario: No identifier in any output
- **WHEN** `search`, `show`, `thread`, `folders`, `save`, `whoami`, `accounts` and `doctor` run on a connector account, once
  with the default settings and once with every connector setting overridden
- **THEN** no output contains the text `mcp__` or a UUID-shaped string, and `--help` and the shipped config piece contain none

### Requirement: The offline self-test and the piece tests pin the shape
`mailbox self-test` and the piece tests SHALL fail when the printed call drifts from this capability: the default view and
format, the per-account override, the refusal of an invalid value, the page-size cap with its notice, the id carried into
`arguments`, the refusal of `--header`, and the absence of the connector's server identifier.

#### Scenario: Self-test passes
- **WHEN** `mailbox self-test` runs from the repository and from an installed copy
- **THEN** it exits 0 and prints `self-test: ok`

#### Scenario: Self-test notices a drift
- **GIVEN** the default view constant of the connector module is changed to another known value in the test process (the
  default is resolved when the call is built, not copied into the account defaults at import)
- **WHEN** the self-test runs
- **THEN** it exits 1 and names the failed check, because the self-test compares with the literal `THREAD_VIEW_SUMMARY`

#### Scenario: The header filter is still refused
- **WHEN** `mailbox search ACCOUNT --header 'X-Thing: 1'` runs on a connector account
- **THEN** it exits 2 with one line on stderr and nothing on stdout

### Requirement: The skill passes the printed call verbatim and does not grow
The skill `cuentas-externas`, for a connector account, SHALL tell the session to run `mailbox search`, `show` or `thread`
and pass the printed `tool` and `arguments` to the mail connector as printed, adding and removing nothing, keeping its
identity-check step. Its body SHALL be no longer than before this change (1 862 characters) and keep the words the existing
size test requires.

#### Scenario: Wording
- **WHEN** the skill file is read
- **THEN** its connector step names `search`, `show` and `thread`, says `tool` and `arguments` are passed as printed without
  adding or removing anything, and still mentions `whoami` and the `--sender` check

#### Scenario: Size
- **WHEN** the body of the skill (the text after the front matter) is counted in characters before and after the change
- **THEN** the after count is not greater than the before count (1 862), and the existing size and neutrality test passes
