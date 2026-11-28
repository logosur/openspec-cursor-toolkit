# mailbox-search-results Specification

## Purpose

Closes two gaps a first consumer of `mailbox` found after `external-access` was installed: a search result did not carry the
message's identifier, and a header filter on the `local` backend did its status pass over a whole folder before looking at
the header, with a cut that was never reported. Related: `external-access` (capability `mailbox-access`, not archived yet).
These requirements only add behaviour: the existing JSON fields, exit codes, opaque ids and the default text line stay as
`mailbox-access` states them. A header filter on the `local` backend may be answered from a header index of the configured
names, with the same answer as reading the folder file. A per-result header option was designed and is deliberately not
part of this capability.

## Requirements

### Requirement: Search results carry the message identifier
`mailbox search --json` SHALL include in every item the key `message_id`: the first `Message-ID` of the message in
normalised form (lowercase, without angle brackets), or `null` when the message has none. It SHALL be the same string for
the same message on the `imap` and on the `local` backend and unique among the items of one result except for `null`.
`mailbox thread --json` items SHALL carry the same key.

#### Scenario: Identifier on the local backend
- **GIVEN** a synthetic local folder with a message whose header is `Message-ID: <Case.Mixed-1@example.test>`
- **WHEN** `mailbox search ACCOUNT --backend local --json` lists it
- **THEN** its item has `"message_id": "case.mixed-1@example.test"`

#### Scenario: Same string on both backends
- **GIVEN** the same message served by the fake IMAP server and by the synthetic local store
- **WHEN** it is listed with `--backend imap --json` and with `--backend local --json`
- **THEN** both items carry the same `message_id`

#### Scenario: Message without an identifier
- **GIVEN** a message with no `Message-ID` header
- **WHEN** it is listed with `--json` on `local`
- **THEN** its item has `"message_id": null` and a non-empty `id`

#### Scenario: Unique within a result
- **GIVEN** a message stored twice in one folder (the case the existing duplicate rule covers)
- **WHEN** `search --folder inbox --json` runs on either backend
- **THEN** it is one item, and no two items of the result share a non-null `message_id`

#### Scenario: Thread items
- **WHEN** `mailbox thread ACCOUNT ID --json` runs on either backend
- **THEN** each item has `message_id` with the same rules

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

### Requirement: A header filter on the local backend checks the header before the status pass and is bounded
For a `--header` filter the `local` backend SHALL read the header of at most `header_scan_max` candidates per folder (default
50 000, never lower), the newest left by the other filters, taking that cut before any read of the folder file for the
messages it leaves out. It SHALL run the deleted-message check only on the matches, SHALL state the cut in a note when it
left messages out, and SHALL match as before this change, except as "A message stored twice" states.

#### Scenario: Status pass reads only the matches
- **GIVEN** a folder of 200 messages, 3 of them matching, and a record of how many rows the deleted-message check receives
- **WHEN** `--header 'List-ID: x'` is the only filter
- **THEN** that check receives at most 3 rows

#### Scenario: Cap reached
- **GIVEN** `header_scan_max` is 2 and a folder with 5 candidate messages
- **WHEN** `--header 'List-ID: a'` runs on `local`
- **THEN** the output has a note `--header checked the newest 2 of 5 messages of FOLDER left by the other filters; narrow the
  search or raise header_scan_max` among its first lines and in the `notes` array of `--json`, no more than 2 headers are
  read, and the exit code is 0

#### Scenario: Cap not reached
- **GIVEN** `header_scan_max` is 1000 and a folder with 5 candidate messages
- **WHEN** the same search runs
- **THEN** all 5 are checked and no such note is printed

#### Scenario: The old silent cut is gone
- **WHEN** a header filter meets more candidates than `header_scan_max`
- **THEN** the cut is stated whatever the number of messages in the folder, and nothing in the code limits the scan to 50 000
  except that setting's default

#### Scenario: Same matches as before the change
- **GIVEN** a folder with messages whose `List-ID` is `<alpha.example.test>` or `<beta.example.test>`, one with the header
  twice with different values, and some without it
- **WHEN** `--header 'List-ID: ALPHA'`, then `--header 'List-ID: beta'`, then `--header 'List-ID:'` run
- **THEN** the first lists every message with `alpha` anywhere in any occurrence of the header, case-insensitively, the second
  the same for `beta`, and the third every message that has the header at least once and no message without it

#### Scenario: A message stored twice
- **GIVEN** one folder with two copies of the same `Message-ID`, and only the copy that comes first in the file has a `List-ID`
- **WHEN** `--header 'List-ID: alpha'` runs
- **THEN** the message is listed once, with `total` 1 (the copy without the header does not hide the one that has it, as on
  the `imap` backend and across folders)

#### Scenario: Combined with other filters
- **WHEN** `--header 'List-ID: alpha' --since DATE --from TEXT` runs
- **THEN** only messages satisfying all three are listed, the date window and `--from` are applied before the header pass, and
  a body filter `--text` applies after them with its own cap

#### Scenario: Messages deleted since indexing stay hidden
- **GIVEN** a matching message whose client status flag is set to deleted without changing the file's size
- **WHEN** the search runs
- **THEN** it is not listed, as for any other filter

### Requirement: A build of an index is announced
A `local` search that builds a folder index from scratch (no index yet, or the folder file was compacted) SHALL say so in a
note with the number of messages the index holds, in the text output and in the `notes` of `--json`; a later search of the
unchanged folder SHALL print no such note. The work done SHALL not change.

#### Scenario: A build is announced
- **GIVEN** a folder with no index
- **WHEN** a `local` search runs, then the same search runs again
- **THEN** the first output has a note `the index of FOLDER was built from scratch (N messages)` with N the number of messages
  the index holds (a message stored twice counts twice), also in the `notes` of `--json`, and the second has no such note

#### Scenario: Rebuild after compaction
- **GIVEN** an indexed folder whose file shrinks (the client compacted it)
- **WHEN** a `local` search runs
- **THEN** it carries the build note, and the ids of the messages that remain are the same as before

#### Scenario: An empty folder says nothing
- **GIVEN** a folder file with no messages
- **WHEN** a `local` search of that folder runs
- **THEN** no build note is printed

### Requirement: The new setting is validated and documented
The setting `header_scan_max` of the config piece `mailbox` SHALL have the shipped default `50000`, equal to the in-code
default and never lower than 50 000. A value that is not a number of at least 1 SHALL be replaced by the default without a
traceback, and `mailbox --help` SHALL describe `message_id`, `header_scan_max`, the bound and note of a header filter on
`local`, and the build note.

#### Scenario: Shipped defaults agree
- **WHEN** the tests compare `global/config/mailbox.json` with the defaults in `global/scripts/mailbox`
- **THEN** `header_scan_max` is present in both with the same value

#### Scenario: Default is not below the old cut
- **WHEN** the shipped default of `header_scan_max` is read
- **THEN** it is at least 50 000

#### Scenario: Mistyped setting
- **WHEN** `header_scan_max` is a string, `0`, negative, a boolean, `null`, or a number a float cannot hold (an integer of
  400 digits)
  (a decimal such as `2.0` is a number and is cut to an integer, not refused)
- **THEN** the command uses the default for that key, prints no traceback, and behaves as with the shipped config (no cut note
  on a small folder)

#### Scenario: Help text
- **WHEN** `mailbox --help` runs
- **THEN** its text contains `message_id` and `header_scan_max`

### Requirement: Existing exit codes and read-only behaviour are unchanged
No new outcome of `mailbox search` SHALL use an exit code other than the existing ones (0, 1, 2, 3, 4, 10), and nothing in
this change SHALL write to a mailbox, a mail store, or any place other than the index in the private cache directory.

#### Scenario: Exit codes
- **WHEN** a search runs with a valid header filter that meets the cap, with a malformed `--header`, with no backend
  available, and with an id that no longer resolves
- **THEN** the exit codes are 0, 2, 3 and 4 respectively

#### Scenario: Read-only
- **WHEN** a header search runs
- **THEN** the store files are opened read-only without a lock, and their size and modification time are unchanged
