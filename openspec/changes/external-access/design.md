# Design — external-access

Marks: **FACT** (read or run), **INFERENCE**, **HYPOTHESIS** (to be proven by a task), **UNKNOWN**.

## D1 — One module, two pieces, one skill

`access` is one optional module with two independent pieces (`mailbox`, `stores`) and one skill.

- Two pieces because they share no behaviour, only output conventions; a machine may configure one and leave the other empty.
- One skill because every skill description is loaded in every session. A second description would cost tokens everywhere to save none.
- The skill names commands, never mechanisms. A new backend or provider changes a script and its help, not the skill (open for extension, closed for edits).

## D2 — Layout: entry scripts that own the commands, a small package that owns the backends

```
global/scripts/mailbox                 entry point: argument parsing, account configuration, the commands, backend order and fallback
global/scripts/stores                  entry point: argument parsing, configuration, the commands
global/scripts/lib/access/
  output.py        bounded text and JSON output, exit codes
  settings.py      config piece loading and validation (toolkit_config), account lookup
  mail_local.py    profile and store resolution of the desktop mail client, mbox reader
  mail_index.py    incremental SQLite index of one mbox
  mail_imap.py     live IMAP, read-only
  mail_connector.py  query translation and identity check for a connector account
  mail_message.py  header decoding, body extraction, attachments (shared by local and imap)
  store_auth.py    token signing through openssl, token exchange
  store_play.py    Google Play provider
  store_ios.py     App Store Connect provider
  http.py          one GET/POST helper over urllib with timeouts
```

Each backend and provider implements the same small interface (`search`, `fetch`, `thread`, `folders`, `status` for mail; `read_checks`, `live_checks`, the read commands, `public`, `console_url` for stores). What the entry scripts hold is the command logic (which backend answers, in what order, what is printed) and the configuration of accounts and apps; what the library holds is everything that knows how one backend or provider works. Adding a backend is a new file plus a line in `make_backend`; adding a provider is a new file plus a line in the provider table. The entry scripts are not "dispatch only": the command logic lives there on purpose, because it is the one place that sees all backends at once (fallback, the line that names the answering backend), and splitting it from the argument parser would only add a module that every command change has to touch as well.

## D3 — Mail backends and their order

An account lists its backends in order of preference. The first available one answers; the output always names which one answered and, if an earlier one was skipped, why.

| Backend | Needs | Freshness | Notes |
|---------|-------|-----------|-------|
| `imap` | host, user, a credentials file | live | read-only on the wire |
| `local` | a desktop mail client that keeps the account offline | the folder's modification time | no credentials, no network |
| `connector` | a mail connector in the session | live | the script cannot call it |

- `connector` never falls back to another backend and nothing falls back to it: where the owner wants an account read through the connector, that is the only route.
- **FACT (measured):** scanning a multi-gigabyte mbox cold takes about a minute; `local` is only usable with an index.

## D4 — Local store: resolve, never configure

The path of a local store is derived on every run from the mail client's own files:

1. Profile root: the first existing of the client's standard locations (overridable in config).
2. Profile: among the profiles that define the account, the installation's default if it is one of them, else the one whose preferences file changed last.
3. Account folder: from the preferences, matching the server's user name or an identity's address to the configured address, then that server's relative directory.
4. Role folders (`inbox`, `sent`, `drafts`): every non-empty file whose base name matches one of the role's known names, ignoring a numeric suffix, plus the folder the identity's preferences name for sent copies and drafts; most recently changed first. Config may pin a role to one name or a list. **FACT (one real account):** a role is not one folder. Sent mail was split between the server's own sent folder, written by webmail and phones, and the folder where the desktop client files its copies; a resolver that picked one of them hid most of the sent mail. Results are de-duplicated by `Message-ID` across the folders of a role.

Only the Thunderbird layout (mbox files, `.sbd` subfolders) is implemented. Another client is a new `local` resolver behind the same interface.

## D5 — Index

- One SQLite file per mbox under the user's cache directory, in a `0700` directory, file mode `0600`. It holds addresses, subjects and offsets: it is the owner's correspondence metadata and never goes inside a repository or a notes folder.
- Header blocks only. Bodies are read at `show` time by seeking to the stored offset.
- Incremental: if the mbox grew and the last indexed message still starts where recorded, only the new bytes are parsed. If it shrank, or that check fails, the client compacted it and the index is rebuilt.
- The mbox is opened read-only, without any lock, so a running mail client is never blocked.
- **FACT (two real folders of one client, sampled):** the format is not uniform. One folder separates messages with `From - <date>` and a line feed, followed by `X-Mozilla-Status` and `X-Mozilla-Status2` lines; another, written by a newer version, uses carriage return plus line feed throughout and carries **no status lines at all**. The parser accepts both, and the test fixtures contain both.
- The date on the separator line is when the client stored the message, not when it was sent: dates come from the `Date` header, falling back to the newest `Received` header.
- **Date filters are one thing on every backend:** `--since` and `--until` compare that message date (the `Date` header, else the newest `Received`); a message with no date is outside any window. `imap` cannot ask the server for that date, only for the arrival date, so the server search is a pre-selection widened by one day before and two days after the window and every fetched message is then checked locally against its own date. Known limit: a message whose own date is in the window but that arrived more than that outside it (an import, a restored backup) is not found on `imap`; `local` finds it. `mailbox --help` says so.
- Deleted mail: where status lines exist, a message with the deleted flag is not indexed, and the flag is read again from the file when a result is about to be printed (the client changes it in place, without changing the file's size). Where they do not exist the file cannot tell, so the folder may still hold mail that was deleted or moved on the server since its last compaction. The `local` backend says so next to its freshness, and that is one reason `imap` goes first where both exist.
- The same message stored twice (same `Message-ID` in one folder) is listed once.

## D6 — IMAP: read-only and careful with the password

- `EXAMINE` (read-only select) and `BODY.PEEK` only. The module has no code path that issues `STORE`, `COPY`, `MOVE`, `APPEND`, `EXPUNGE`, `CREATE`, `DELETE` or `SUBSCRIBE`; a test asserts it on the command stream.
- The password comes from an env-style file named in config, read at run time. The file must not be readable by group or others, or the backend refuses it. The value is never printed, logged or put in an argument list.
- **Roles on a large server:** a folder is taken for the `sent` or `drafts` role by its name only within two levels of the tree (`Sent`, `INBOX.Sent`, `[Gmail]/Sent Mail`); the server's special-use flag always counts. An archive tree can hold hundreds of folders called `Sent`, and a role that opened each of them made every `search` and `thread` scan them all.
- **Thread lookups are bounded (FACT, from a real run):** on a server with more than 200 folders an unbounded thread lookup (every folder a role matched, three rounds, an `OR` over every identifier) ended in a timeout and "no backend available". `thread` therefore reads the message as headers only, opens at most four folders (its own, the inbox, two sent folders), runs at most two rounds of header searches over at most six identifiers each, and says when a long thread was cut. **A second real-run FACT:** the same server answered `BAD` ("Command Argument Error") to one search that joined nine header alternatives with `OR` (it accepted six), so every thread lookup fell back to `local` even though the server was healthy. The alternatives are therefore sent in searches of at most four (`THREAD_OR`) and their results are united. If the lookup still fails after the message was read, the `local` backend of the same account answers from the message's Message-ID and the first output line says it is a fallback; with no `local` backend, or none holding the message, the command exits 3 naming both reasons.
- An authentication failure is never retried and is remembered for 30 minutes: during that time the backend reports itself unavailable. **INFERENCE:** hosted mail services lock a mailbox after a few bad logins; a retry loop would lock the owner out.

## D7 — Connector accounts

The session, not the script, holds the connector. `mailbox search` on such an account prints the connector tool to call and its arguments as JSON (the filters translated to the connector's query language) and exits 10. `mailbox whoami ACCOUNT` prints the one cheap call that reveals the connector's address; `mailbox whoami ACCOUNT --sender ADDRESS` compares it with the configured one. Connectors belong to the assistant account that is signed in, so the check is per session. The connector's server identifier is never stored: the skill tells the session to use whichever tool of that name it has.

## D8 — Stores: authentication without a third-party library

- Google Play: service-account key file → signed assertion (RS256) → token endpoint → access token.
- App Store Connect: key id, issuer id and private key file → signed token (ES256), lifetime 15 minutes (**FACT:** the service refuses more than 20).
- Signing shells out to `openssl`; the standard library has no asymmetric signing. The key file never leaves disk and must be `0600`.
- `openssl` returns an elliptic-curve signature in DER form, and a token needs the raw form (r and s, 32 bytes each, concatenated). The conversion is tested on its own: a test that only asks `openssl` to verify what `openssl` signed would pass on a token the service rejects.
- **FACT:** the Play API cannot list the apps of a developer account, so apps are listed from config. **FACT:** reading tracks needs an edit; the provider opens one, reads and deletes it, and never commits.
- Endpoints are config values with the public defaults, so tests point them at a local server.
- A request that carries credentials never follows a redirect (`urllib` would forward the `Authorization` header to the new host, **FACT** probed with two loopback servers); the 3xx is returned and printed as an error. Only the unauthenticated public-page check follows redirects.

## D9 — What the store commands print when nothing is connected

`doctor` lists every prerequisite as `ok` or `missing`, with the one action that fixes each, and exits 3 if any is missing. A prerequisite that depends on an earlier missing one (the key file's existence, privacy and form after a missing path) is not printed: it would only say "fix the earlier one first". API commands exit 3 with one line that points to `doctor`. `apps` and `url` work without credentials, because the console address needs only ids.

Three levels of access exist per app, and the command is useful at each:

| Level | Needs | Gives |
|-------|-------|-------|
| none | ids in config | `apps`, `url` (console address for the browser), `public` (is the public page up) |
| key on disk | a private key file | `doctor --live` proves the key and names the missing grant |
| key granted | the account owner's grant in the console | every read |

A machine with no key file starts at level "none" for that provider. The API reads of tasks 5.2 and 5.3 are then proven against the simulated services only (**HYPOTHESIS** until they run once against the real service with a granted key).

The index of the signed-in user in a console address (`/u/N`) depends on the order in which accounts signed in to the browser and can change. It is a config value that `doctor` cannot verify; `url` prints it as given.

## D10 — No token is lent

No subcommand prints a token or hands one to another program. A store token is read-write, so lending it to an arbitrary command would be a write path; it is left for the change that adds writes.

## D11 — Output discipline

- Text by default, one line per item, at most 160 characters; `--json` for scripts.
- `search` returns 20 items unless told otherwise and always prints how many matched.
- `show` returns 1 500 body characters unless told otherwise, HTML reduced to text.
- Exit codes: 0 ok, 1 unexpected or remote error, 2 usage or unknown account, 3 not available or not connected, 4 not found, 10 delegated to a connector.

## D13 — Shared helpers: the contract both pieces code against

`mailbox` and `stores` are written independently; these two modules are their only shared code.

```python
# lib/access/output.py
OK, ERROR, USAGE, UNAVAILABLE, NOT_FOUND, DELEGATED = 0, 1, 2, 3, 4, 10
def clip(text: str, width: int = 160) -> str        # one line: whitespace collapsed, cut with an ellipsis
def print_items(lines: list[str], total: int, limit: int, header: str = "") -> None
                                                    # header, then at most `limit` clipped lines, then "N of TOTAL shown" when cut
def print_json(document: dict) -> None              # one compact JSON document, keys sorted, UTF-8 kept
def fail(piece: str, code: int, message: str) -> "NoReturn"   # "piece: message" on stderr, exit code

# lib/access/settings.py
def load(piece: str, defaults: dict) -> tuple[dict, str | None]
                                                    # config over defaults; on a broken file: (defaults, one-line problem)
def is_private(path) -> tuple[bool, str]            # regular file, owned by the user, no group/other bits; else the reason
def read_env_file(path) -> dict[str, str]           # KEY=VALUE lines, optional `export`, quotes stripped; never logs
def cache_dir(piece: str) -> "Path"                 # $XDG_CACHE_HOME or ~/.cache, /claude-toolkit/<piece>, created 0700
def expand(path: str) -> "Path"                     # ~ and environment variables
```

## D12 — Tests

- All tests build their own fixtures in a temporary home: a mail-client profile tree with small mbox files in both observed formats, a fake IMAP class that records every command, a local HTTP server that plays the two store APIs, and key pairs generated with `openssl` at test time.
- `self-test` in each script runs the offline subset; the contract probes call it. The probes must hold on any machine, whatever its override configures (accounts, apps), so they test `self-test`, a corrupt configuration (the `corrupt_config` probe), a usage error and that `accounts`, `apps` and `doctor` run; that the *shipped defaults* hold no account or app is proven by unit tests of the shipped config pieces, not by a probe.

## Unknowns

- **UNKNOWN:** whether a given IMAP server supports server-side `TEXT` search reliably. `--text` on `imap` is best effort and says so; `local` scans the candidate bodies itself.
- **UNKNOWN:** the store consoles' page paths beyond those already visited. `url` passes an unknown page through unchanged and the page table is a config value.
- **HYPOTHESIS:** one skill description is enough for sessions in unrelated projects to find the commands. Task 6.3 tests it with a cold agent.
