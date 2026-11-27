# Spec Delta — mailbox-search-results

## Purpose

`mailbox-search-results` states that connector accounts behave as before. `mailbox-connector-calls` (this change) makes the
printed connector call complete: it adds `arguments.view` to the search document, a top-level `paging` key, and an `arguments`
object to the read document. The requirement below is restated whole with its last sentence and its connector scenario
changed; its two other scenarios are copied unchanged.

## MODIFIED Requirements

### Requirement: Existing output is unchanged and costs nothing more
No existing key of a `search` or `thread` document or item SHALL change its name, type or value, the text output of a search
SHALL be unchanged except for the notes this change adds, and obtaining `message_id` SHALL cost no additional server command
and no read of a message from a local folder file. Connector accounts SHALL keep the keys, exit codes and refusals of their
documents; what they gain is defined by `mailbox-connector-calls`.

#### Scenario: No extra work per result
- **GIVEN** the fake IMAP server records every command, and a local folder whose messages carry no client status line and
  whose index is already built
- **WHEN** a search listing 25 messages runs with `--json` on `imap`, and a search runs on that local folder
- **THEN** the server receives one header fetch for the 25 messages (a batch holds up to 200), no fetch of a whole message,
  and for the standard fixture exactly the command stream it received before this change; the local search opens the folder
  file zero times

#### Scenario: Compatibility of existing output
- **GIVEN** the output of `search --json` and of `search` (text) captured before this change on a fixed fixture, with the
  local index already built
- **WHEN** the same commands run after it
- **THEN** the text output is byte-identical, and the JSON document is identical after removing the key `message_id` from each
  item (top-level keys, item keys, values, order of items and exit code 0 unchanged)

#### Scenario: Connector accounts do not change
- **WHEN** `mailbox search` runs on a connector account
- **THEN** its document still has the keys `delegate`, `kind`, `tool`, `arguments` and `read_tool` with unchanged names, types
  and values (`arguments.query` and `arguments.pageSize` for a limit within the maximum included), it exits 10, and `--header`
  on it exits 2 with one line and nothing on stdout
