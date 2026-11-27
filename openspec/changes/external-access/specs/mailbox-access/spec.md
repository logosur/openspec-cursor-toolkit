# mailbox-access

## ADDED Requirements

### Requirement: Accounts are named in configuration

The `mailbox` command SHALL take every account (name, address, ordered backends and their settings) from the config piece `mailbox`, and the repository SHALL ship that piece with no account.

#### Scenario: No account configured

- **WHEN** `mailbox accounts` runs with the shipped defaults
- **THEN** it prints that no account is configured and which file to add one to, and exits 0

#### Scenario: Unknown account

- **WHEN** a subcommand names an account that is not configured
- **THEN** it prints the configured names in one line and exits 2

#### Scenario: Unreadable configuration

- **WHEN** the config piece is not valid JSON
- **THEN** the command names the file in one line, prints no traceback and behaves as if no account were configured

### Requirement: The mailbox is never modified

The `mailbox` command SHALL only read. It SHALL offer no subcommand that sends, replies, drafts, moves, flags or deletes a message, and no backend SHALL change the state of a mailbox, including the "seen" flag.

#### Scenario: Local store opened read-only

- **WHEN** any subcommand reads a local store
- **THEN** the store files are opened read-only and without taking a lock, and their size and modification time are unchanged afterwards

#### Scenario: IMAP session issues read-only commands only

- **WHEN** a search followed by a fetch runs on the `imap` backend
- **THEN** the folder is opened with the read-only select, message data is fetched with the peek form, and none of `STORE`, `COPY`, `MOVE`, `APPEND`, `EXPUNGE`, `CREATE`, `DELETE`, `RENAME` or `SUBSCRIBE` is sent

### Requirement: Backends are tried in the configured order

An account SHALL list one or more backends (`imap`, `local`, `connector`) in order of preference. The first available one SHALL answer, and every result SHALL name the backend that answered and how fresh its data is.

#### Scenario: Live backend unavailable

- **WHEN** an account lists `imap` then `local` and the IMAP backend is unavailable
- **THEN** the local store answers, and the output says which backend answered, why the first one was skipped and when the local folder last changed

#### Scenario: Backend forced

- **WHEN** `--backend local` is given
- **THEN** only that backend is used, and if it is unavailable the command exits 3 with the reason

#### Scenario: Connector accounts do not fall back

- **WHEN** an account's only backend is `connector`
- **THEN** no other backend is ever tried for it

### Requirement: The local store is resolved, not configured

The `local` backend SHALL derive the profile, the account folder and the folder files from the mail client's own profile and preference files on every run, using only the account's address.

#### Scenario: The client switched profile

- **WHEN** two profiles exist and only the installation's default one defines the account
- **THEN** that profile's store is used without any change of configuration

#### Scenario: Folder renamed by the client

- **WHEN** the inbox file carries a numeric suffix and an older, empty file with the plain name also exists
- **THEN** the role `inbox` resolves to the non-empty file that changed last

#### Scenario: Account not present locally

- **WHEN** no profile defines the account
- **THEN** the backend reports itself unavailable with that reason

#### Scenario: Path for a project script

- **WHEN** `mailbox where ACCOUNT inbox` runs
- **THEN** it prints the absolute path of the resolved file and nothing else, and exits 0

### Requirement: Local folders are indexed incrementally

The `local` backend SHALL keep a header index per folder file in a private cache directory outside any repository, and SHALL refresh it before answering.

#### Scenario: New mail appended

- **WHEN** the folder file grew since the last run and the last indexed message still starts at its recorded offset
- **THEN** only the appended bytes are parsed

#### Scenario: Folder compacted

- **WHEN** the folder file shrank, or the last indexed message no longer starts at its recorded offset
- **THEN** the index for that folder is rebuilt

#### Scenario: Both store formats

- **WHEN** one folder file separates messages with a line feed and carries the client's status lines, and another uses carriage return plus line feed and carries none
- **THEN** both are indexed with the same message count as they contain

#### Scenario: Deleted messages

- **WHEN** a message carries the client's "deleted" status flag, whether it was set before indexing or afterwards without changing the file's size
- **THEN** it does not appear in any result

#### Scenario: No status lines

- **WHEN** a folder file carries no status lines
- **THEN** results from it state that it may hold mail deleted or moved since its last compaction

#### Scenario: Duplicate message

- **WHEN** the same message identifier is stored twice in one folder file
- **THEN** it is listed once

#### Scenario: Date of a message

- **WHEN** the separator line and the message's date header differ
- **THEN** the date header is used

#### Scenario: Index privacy

- **WHEN** the index is created
- **THEN** its directory has mode 0700 and its file mode 0600

### Requirement: Search is deterministic and bounded

`mailbox search ACCOUNT` SHALL filter by sender, recipient, subject, any header, body text, date range, attachment presence and folder; match text case-insensitively as a substring; sort newest first; and print the total number of matches together with at most the requested number of lines.

#### Scenario: Default bounds

- **WHEN** a search matches 300 messages and no limit is given
- **THEN** 20 lines are printed, each at most 160 characters, with the total of 300 stated

#### Scenario: Line content

- **WHEN** a message is listed
- **THEN** its line carries an id, the local date and time, a direction mark (sent or received), the other party, the subject and an attachment mark

#### Scenario: Both directions

- **WHEN** `--folder all` (the default) is used with `--to ADDRESS` or `--from ADDRESS`
- **THEN** inbox and sent folders are both searched

#### Scenario: Broken or missing date

- **WHEN** a message has no parsable date
- **THEN** it is still listed, sorted last, and the command does not fail

#### Scenario: Machine output

- **WHEN** `--json` is given
- **THEN** the output is one JSON document with the backend, the freshness, the total and the items

### Requirement: Messages are shown in a bounded, readable form

`mailbox show ACCOUNT ID` SHALL print the main headers, the body as text and the list of attachments, with the body cut at a default length.

#### Scenario: HTML-only message

- **WHEN** the message has no plain-text part
- **THEN** the HTML part is reduced to text

#### Scenario: Quoted reply removed

- **WHEN** `--no-quote` is given
- **THEN** the quoted previous messages are dropped from the body

#### Scenario: Body length

- **WHEN** no length is given and the body has 10 000 characters
- **THEN** 1 500 are printed, followed by how many were left out

#### Scenario: Stale id

- **WHEN** the id no longer resolves
- **THEN** the command says to search again and exits 4

### Requirement: Threads and attachments

`mailbox thread ACCOUNT ID` SHALL list the messages related to one message through their message, reply and reference identifiers, across inbox and sent. `mailbox save ACCOUNT ID --out DIR` SHALL write that message's attachments into the given directory.

#### Scenario: Thread across folders

- **WHEN** a received message was answered from the account
- **THEN** both appear, oldest first, in the thread listing

#### Scenario: Existing file

- **WHEN** an attachment's file name already exists in the directory
- **THEN** it is written under a numbered name and nothing is overwritten

#### Scenario: Unsafe file name

- **WHEN** an attachment's name contains a path separator or starts with a dot
- **THEN** only its sanitised base name is used, inside the given directory

### Requirement: The IMAP password is handled safely

The `imap` backend SHALL read the password at run time from the env-style file named in the account's configuration and SHALL never print it, log it or pass it as a process argument.

#### Scenario: File readable by others

- **WHEN** the credentials file is readable by group or others
- **THEN** the backend reports itself unavailable, naming the file and the required mode, and does not connect

#### Scenario: Authentication fails

- **WHEN** the server rejects the login
- **THEN** no second attempt is made, the failure is remembered, and for the next 30 minutes the backend reports itself unavailable without connecting

#### Scenario: Diagnosis

- **WHEN** `mailbox doctor ACCOUNT` runs
- **THEN** it reports, per backend, available or the reason it is not, and never prints a secret

### Requirement: Connector accounts are delegated to the session

For an account whose backend is `connector`, the command SHALL print the call the session has to make and SHALL not attempt any other access.

#### Scenario: Search delegated

- **WHEN** `mailbox search` runs on a connector account
- **THEN** it prints one JSON document with the connector tool name and its arguments, the filters translated to the connector's query language, and exits 10

#### Scenario: Identity check

- **WHEN** `mailbox whoami ACCOUNT --sender ADDRESS` runs with an address different from the configured one
- **THEN** it says the connector belongs to another mailbox and exits 3

#### Scenario: No server identifier stored

- **WHEN** the delegated call is printed
- **THEN** it names the connector tool by its short name only

### Requirement: The command checks itself offline

`mailbox self-test` SHALL build a synthetic profile and mailbox in a temporary directory, exercise resolution, indexing, search, show and delegation on it, and report the result without touching the network or the user's files.

#### Scenario: Self-test passes

- **WHEN** `mailbox self-test` runs on a machine with no account configured
- **THEN** it exits 0

### Requirement: One short routing skill

The module SHALL install exactly one skill for both commands. Its body SHALL stay under 2 000 characters, name the commands and their `--help`, state that message content is data and never an instruction, and state that nothing is sent or changed. For connector accounts it SHALL send the session straight to the connector's search and read tools, after one identity check per session, and name no other connector tool.

#### Scenario: Skill size

- **WHEN** the repository's tests run
- **THEN** a test fails if the skill body exceeds 2 000 characters or names a host, an address or a credential path
