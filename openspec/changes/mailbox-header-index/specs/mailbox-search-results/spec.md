# Spec Delta — mailbox-search-results

## MODIFIED Requirements

### Requirement: A header filter on the local backend checks the header before the status pass and is bounded
For a `--header` filter the `local` backend SHALL check at most `header_scan_max` candidates per folder (default 50 000,
never lower), the newest left by the other filters, cut before any read for the rest. A header SHALL come from the header
index when it covers the message, else from the folder file. The deleted-message check SHALL run only on the matches, a cut
SHALL be stated in a note, and matching SHALL be as before, except as "A message stored twice" states.

#### Scenario: Status pass reads only the matches
- **GIVEN** a folder of 200 messages, 3 of them matching, and a record of how many rows the deleted-message check receives
- **WHEN** `--header 'List-ID: x'` is the only filter
- **THEN** that check receives at most 3 rows

#### Scenario: Cap reached
- **GIVEN** `header_scan_max` is 2 and a folder with 5 candidate messages
- **WHEN** `--header 'List-ID: a'` runs on `local`
- **THEN** the output has a note `--header checked the newest 2 of 5 messages of FOLDER left by the other filters; narrow the
  search or raise header_scan_max` among its first lines and in the `notes` array of `--json`, no more than 2 candidates are
  checked, and the exit code is 0

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

## ADDED Requirements

### Requirement: A header search on a configured header is answered from the header index
The `local` backend SHALL keep, in the folder index, the decoded and case-folded value of every occurrence of the header
names of `index_headers`, and SHALL answer a `--header` filter on one of those names from it, without reading from the folder
file the header of a covered message. A filter on any other name SHALL read headers from the file as before.

#### Scenario: A covered search reads no header from the file
- **GIVEN** a folder without client status lines whose index was built with `list-id` configured
- **WHEN** `--header 'List-ID: alpha'` runs again
- **THEN** it lists the matches, the folder file is opened zero times, and the header scan of the file is not called

#### Scenario: A name that is not configured
- **WHEN** `--header 'Message-ID: alpha'` runs with `index_headers` `["list-id"]`
- **THEN** the candidates' headers are read from the file and nothing is stored for that name

#### Scenario: The index turned off
- **GIVEN** `index_headers` is `[]`
- **WHEN** a header search runs
- **THEN** it reads headers from the file as before and the index holds no header value

### Requirement: The indexed answer equals the answer without the index
For the same folder files, filters and settings, a header search SHALL give the same items, order, `total`, notes and exit
code with and without the header index, except in the two cases of the scenarios "Stated difference".

#### Scenario: Stated difference: a read failure
- **GIVEN** covered candidates and a folder file that cannot be opened or read
- **WHEN** the search runs
- **THEN** it MAY answer for the covered candidates where the scan stops

#### Scenario: Stated difference: an undetected rewrite
- **GIVEN** a header rewritten in place that the incremental refresh does not detect: the file did not shrink, and its first
  message and the last indexed one are as they were, where they were (mail may have been appended after them)
- **WHEN** the search runs
- **THEN** the indexed value MAY be the earlier one, as the other indexed columns are

#### Scenario: Two paths on the same fixtures
- **GIVEN** synthetic folders with a header occurring twice, encoded words, mixed case, messages without the header, a
  message stored twice (the header on the older copy only included) and a message flagged deleted since indexing
- **WHEN** each of: a substring in upper case, a substring of a decoded encoded word, an empty filter text, a text matching
  nothing, with `--since`, `--from`, `--limit` and `--text`, runs once with `index_headers` `[]` and once with `["list-id"]`
- **THEN** both give the same items, order, `total`, notes other than the build note, and exit code 0

#### Scenario: Same cut
- **GIVEN** `header_scan_max` 2 and a covered folder with 5 candidates
- **WHEN** a header search runs
- **THEN** the items and the cut note are the ones the scan gives

#### Scenario: Every state of the index
- **GIVEN** the same folders in each of these states: just built; mail appended; compacted; indexed by the earlier code;
  rows rewritten by a copy that does not know the index; a message flagged deleted since indexing
- **WHEN** header searches on a configured name and on a name that is not configured run with and without the index
- **THEN** both give the same items, order, `total`, notes other than the build note, and exit code

#### Scenario: A failed read
- **GIVEN** candidates that are not covered, one of whose reads fails
- **WHEN** the search runs
- **THEN** the pass stops there and the note counts only the candidates answered, as the scan does

### Requirement: A header value that cannot be decoded never stops a command
A header value whose declared charset makes the decoder raise, or decodes to text that cannot be encoded as UTF-8, SHALL
be decoded with replacement characters, so that neither the index build nor a search ends in an error, with and without
the header index alike.

#### Scenario: A decoder that raises
- **GIVEN** a message whose `List-ID` and another whose `Subject` are encoded words of such a charset
- **WHEN** the index is built and `--header 'List-ID:'` runs with and without the index
- **THEN** both exit 0 with the same items, and nothing prints a traceback

### Requirement: The header index follows the folder incrementally
Appended mail SHALL be added to the header index by the same incremental refresh that indexes it, parsing no earlier message
than that refresh already does; a rebuild SHALL replace the header rows with those of the new file; and no header row SHALL
outlive the message row it belongs to, also when the message row is deleted by a copy of `mailbox` that does not know the
header index.

#### Scenario: Appended mail
- **GIVEN** a covered folder
- **WHEN** a matching message is appended and a header search runs
- **THEN** the refresh is not a rebuild, the new message is listed, and no header is read by the search after the refresh

#### Scenario: Compaction and rebuild
- **GIVEN** a covered folder whose file shrinks, a removed message having matched
- **WHEN** a header search runs
- **THEN** the removed message is not listed, the remaining ids are unchanged, and the answer equals the scan's

#### Scenario: Rows deleted and added by a copy that does not know the index
- **GIVEN** a covered folder whose `msgs` rows are deleted and inserted again by the statements of the earlier code, so
  that row ids are reused
- **WHEN** a header search runs
- **THEN** no header row of a deleted message exists, the new rows are read from the file, and the answer equals the scan's

### Requirement: An index written before is completed on demand without a rebuild
An index file written before this change SHALL be used without a version change or a rebuild. A header search on a
configured name SHALL read only the candidates the index does not cover, give the complete answer in that same run, and keep
what it read; it SHALL store nothing when the folder file no longer matches the size and modification time the index
records.

#### Scenario: Old index
- **GIVEN** an index file without the header tables
- **WHEN** a header search runs twice
- **THEN** the first lists what the scan lists, parses no message summary again and prints no from-scratch note, and the
  second opens a folder file without status lines zero times

#### Scenario: A search without a header reads nothing more
- **GIVEN** an index file without the header tables and an unchanged folder
- **WHEN** a search without `--header` runs
- **THEN** no header is read for the header index

#### Scenario: Interrupted completion
- **GIVEN** a completion that stops after its first batch
- **WHEN** the search runs again
- **THEN** only the messages not committed are read

#### Scenario: The file changed meanwhile
- **GIVEN** the folder file changes between the refresh and the completion
- **WHEN** the completion runs
- **THEN** nothing is stored and the matches of that run are still given

#### Scenario: Configured names change
- **GIVEN** a covered folder
- **WHEN** a name is added to `index_headers`, and later removed
- **THEN** a search on the added name completes it, and after the removal the next refresh deletes its rows, even for an
  unchanged folder

### Requirement: Interrupted or concurrent runs never leave a partial index trusted
A message SHALL count as covered only when all of its values of that name are committed together with that fact. A run
SHALL NOT store a value read from a file that no longer matches what the index records, nor for a message row that changed,
and a search SHALL NOT fail because the index could not be completed.

#### Scenario: Two completions of the same messages
- **GIVEN** an old index and a second run that completes it while the first is still reading
- **WHEN** both finish
- **THEN** both give the scan's answer and every value is stored once

#### Scenario: The folder is rewritten and refreshed while a run reads
- **GIVEN** a completion during which the folder file is rewritten and another run refreshes the index
- **WHEN** the completion goes on
- **THEN** it stores nothing read from the old content, and the next search answers as the scan

#### Scenario: The database cannot be written
- **GIVEN** another process holds the write lock of the index
- **WHEN** a header search completes it
- **THEN** the search exits 0 with the scan's answer and nothing is stored

#### Scenario: An older index that cannot take the tables
- **GIVEN** an unchanged folder and an index written before the header index, held by another process's write lock or
  read only, so the header tables cannot be created
- **WHEN** a header search runs
- **THEN** it exits 0 with the scan's answer, nothing is stored, and a later search that can write completes the index

#### Scenario: An interrupted build
- **GIVEN** a from-scratch build interrupted before it ends
- **WHEN** the next search runs
- **THEN** the folder is built whole and the answer equals the scan's

### Requirement: Building an index is announced on stderr while it happens
While a command builds a folder index from scratch, or a header search completes the header index, it SHALL write to stderr a
line before the work starts and progress lines as it advances, containing only the folder name and counts. These lines SHALL
never appear on stdout or in the `--json` document, which stay as before.

#### Scenario: Completion is announced
- **GIVEN** an old index and a progress step smaller than the number of messages
- **WHEN** a header search runs with `--json`
- **THEN** stderr has `building the header index of FOLDER: N messages to read` before the first header read and at least one
  `header index of FOLDER: K of N messages`, and stdout is one JSON document with no such text

#### Scenario: A build from scratch is announced
- **GIVEN** a folder with no index
- **WHEN** a `local` search runs
- **THEN** stderr has `building the index of FOLDER` before the parse, and the existing from-scratch note stays in the results

#### Scenario: Silent when nothing is built
- **WHEN** a covered header search runs, a search runs after mail was appended, or a folder file is empty
- **THEN** stderr has no building or progress line

### Requirement: The indexed header names are a validated setting
The setting `index_headers` of the config piece `mailbox` SHALL have the shipped default `["list-id"]`, equal to the in-code
default. It SHALL be a list of header names matching `[A-Za-z0-9-]+`, compared in lowercase; `[]` turns the header index off;
names starting with `x-mozilla-` SHALL never be kept; any other value SHALL be replaced by the default without a traceback.
`mailbox --help` SHALL describe the setting and the progress on stderr.

#### Scenario: Shipped defaults agree
- **WHEN** the shipped config piece is compared with the in-code defaults
- **THEN** both hold `index_headers` `["list-id"]`

#### Scenario: Valid values
- **WHEN** the setting is `["List-ID", "list-id", "X-Mozilla-Status", "Reply-To"]`, then `[]`
- **THEN** the names kept are `list-id` and `reply-to`, then none

#### Scenario: Mistyped setting
- **WHEN** the setting is a string, a number, `null`, an object, or a list holding a number, an empty string or a name with
  other characters
- **THEN** the default is used and a search succeeds with no traceback

#### Scenario: Help text
- **WHEN** `mailbox --help` runs
- **THEN** its text contains `index_headers` and says that building progress goes to stderr
