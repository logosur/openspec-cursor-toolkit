# Design — mailbox-search-gaps

Marks: **FACT** (read in the code or run), **INFERENCE**, **HYPOTHESIS** (to be proven by a task), **UNKNOWN**.
Builds on `external-access` (design D3, D5, D6, D11, D13); it does not restate them.

Scope (P2, decided by the orchestrator from the measurements of D1; source: the iteration log of `RUN-LOOP.md`): the
identifier, the header filter before the status pass with one bounded and stated scan, the build announcement, one new
setting. The header index and `--with-header` are **deferred** (section "Deferred", with triggers).

## D1 — Where the time goes on a header filter (FACT from the code; real-store numbers from the orchestrator)

Path of `mailbox search ACCOUNT --backend local --header 'Name: text'` **before** this change:

1. `global/scripts/mailbox` `cmd_search` → `answer` → `mail_local.LocalBackend.search`.
2. For each folder of the role: `self.index(name)` → `mail_index.FolderIndex.refresh` (it returns at once when size and
   mtime match; otherwise it parses from the last indexed message on, or the whole file after a compaction or a first
   build).
3. `index.select(f)`: SQL over `msgs` using `from_text`, `rcpt`, `subject`, `date`, `att`. **`Filters.header` is not read.**
   With a header as the only filter the `WHERE` is `1=1`: every indexed message of the folder.
4. `index.live(rows)`: for every row with a status offset (`st_off >= 0`) one `seek` + `read` of the client's status digits,
   to drop messages flagged deleted after indexing. No cap. One file access per selected row.
5. `index.header_filter(rows, name, text)`: for the first `cap=50000` rows (newest first), one `seek` + `read` of the header
   block, `split_headers`, and the match. `cap=50000` is an argument default, not a setting, and the returned `scanned` is
   dropped by the caller (`_rows, _scanned`), so a cut is not reported.
6. Only then, for `--text`, `text_scan_max` applies (to what is left).

What the index stores: `msgs(rid, start, hstart, hend, mend, idh, mid, date, from_text, from_addr, from_party, rcpt,
to_first, subject, att, st_off, st_len, has_status)` and `refs(rid, ref)`. `mid` (the normalised `Message-ID`) is already a
column, which is why need 1 costs nothing on `local`. No other header value is kept.

**Real-store measurements** (orchestrator, installed copy, rounded to orders of magnitude; the machine was under load; a few
folders; the inbox has about 15 000 live messages; the index files already existed, so no first build is in these numbers;
the exact figures are kept in the run's unpublished state file):

| Run | Wall | Result |
|-----|-----:|--------|
| (A) `search --backend local --folder inbox --limit 1` | several seconds | the cost of selecting the folder and running `live` over every row |
| (B) the consumer's header filter, with a date window, inbox | a few seconds | every match, identical to the live server's results |
| (C) the same header filter, no date window, inbox | about ten seconds | every match |
| (D) every folder, header filter with a date window | about twenty seconds | every match |

- **FACT:** the path returns the right answer at normal load. "Did not finish in two minutes" was seen once on a heavily
  loaded machine and is **not reproduced**. Need 2 is a path that makes two file accesses per candidate message (`live` over
  everything `select` returns, then one header read per candidate) and is sensitive to machine load, not a path that fails.
- **FACT:** the header-only search (C) and the unfiltered one (A) both pay `live` over the whole folder; with a date window
  (B) `select` narrows the candidates first and the cost falls with them.
- **INFERENCE:** moving the header read before `live` removes the status pass over messages the header filter drops: on
  run (C) the rows handed to `live` go from about 15 000 to a few dozen. A status read happens only for a message that carries a
  client status line (`st_off >= 0`; the newer client format has none), so how much wall time that saves depends on the
  folder: **UNKNOWN** for the real inbox. The header reads stay (one per candidate). The gain is therefore at most the
  size of the status pass, about half of the two per-candidate passes, and may be small; it is not an order of magnitude.
  Task 7.4 repeats (A) to (D) after the install and compares them with the table above; it does not assume a figure.
- **Synthetic measurement** (a scratch mbox of 20 000 messages, 71 MB, 15 headers each, one folder, on a heavily
  loaded machine; not a statement about the real store): `live` over all rows 0.14 s of CPU and 1.2 s to 16.9 s of wall
  time; `header_filter` over all rows 1.25 s of CPU (62 µs per message) and 22 s to 106 s of wall time. The two per-row
  passes cost about the same, and their wall time is dominated by waiting for the file, which is why load moves it by a
  factor of five or more.
- **UNKNOWN:** the split of a first build of an index (`external-access` D3: on the order of a minute to scan separators in a
  multi-gigabyte folder). Not in the consumer's run, not bounded here (proposal, "Known limit").
- **UNKNOWN:** whether run (A)'s several seconds, an unfiltered search, matters to any consumer. Out of scope.

## D2 — The message identifier (need 1)

- **Which header:** `Message-ID`. **Form:** the normalised form the command already uses internally
  (`mail_message.summarize()['mid']`): the first identifier of the header, lowercase, without angle brackets. This is the
  form stored in the index (`msgs.mid`), used for threads and for the duplicate rule, and it is the same string for the same
  message on `imap` and on `local`. It is **not** the raw header that `show --json` prints (`<…>`, original case). A consumer
  compares `message_id` values with each other, never with `show` output; the help says so.
- **Absent or unparsable `Message-ID`:** `null` in JSON (never an empty string, never a generated value: the opaque `id` of
  the same item is the stable handle for such a message on one backend).
- **Uniqueness:** both backends already list a message once per `Message-ID` (`local`: duplicate rule on the hash of `mid`;
  `imap`: `entry[0]['mid']`), so `message_id` is unique among the items of one result except for `null`. A message that
  exists in two folders is one item (the first folder in the existing order).
- **Always in JSON, never in the default text line.** JSON consumers ignore unknown keys; text consumers parse positions, and
  the text line already spends its 160 characters on the id, date, party and subject.
- **Which items:** `Item.as_json` is shared by `search` and `thread`; `thread --json` items gain `message_id` too. This is
  a decision, not an accident: the thread lookup already holds the identifier and a consumer that follows threads has the
  same de-duplication need.
- **Cost:** none. `local`: `row['mid']` is read from the index. `imap`: `HEADER_FIELDS` already fetches `MESSAGE-ID` and
  `_fetch_headers` already returns `summarize(...)['mid']`. No command is added to either backend, and no read of the
  folder file on `local`.
- **What the consumer gains (INFERENCE from its description, measured by task 7.5):** it keeps calling `show` for each new
  message (it needs the body), and skips `show` for the results whose `message_id` is already in its "seen" list.

## D3 — A header filter on `local`: before the status pass, bounded, stated

Order of the passes in `LocalBackend.search` for a header filter, per folder:

1. `select(f)` for the other filters (SQL). Unchanged.
2. **Candidates:** the rows of step 1 (newest first), cut to the newest `header_scan_max`. The cut is taken **before** any
   read of the folder file for the messages it leaves out. No de-duplication is done here on purpose: `live` keeps the
   second copy of a message stored twice when the first was flagged deleted, and a de-duplication before it would drop that
   copy; so a message stored twice uses two places of the cut.
3. **Header pass:** `FolderIndex.header_filter(candidates, name, needle)` reads the header block of each candidate and
   keeps the matches. It has **no cap of its own** (the old `cap=50000` argument default is removed): the bound is the
   one cut of step 2, so a raised `header_scan_max` is not cut a second time in silence. Match semantics are the existing ones and do not change: the header name compared lowercase, the
   needle (case-folded) a **substring** of the decoded value of **any** occurrence of that header; an empty needle matches
   every message that has the header at least once.
4. **Note when the bound cut the scan:** if fewer candidates were checked than the other filters left (the cap, or a read
   error that stopped the pass), one note per folder: `--header checked the newest K of N messages of FOLDER left by the
   other filters; narrow the search or raise header_scan_max`. `K` is what `header_filter` reports it scanned, not the cap, so
   the note stays true when the pass stops early; a row counts as scanned only after its header block was read, so a read
   that fails is not counted (G-12, found in P4).
5. **`live(...)` on the matches only**: the status pass reads at most the number of matches, never the whole folder. A
   message flagged deleted since indexing is still dropped (it is counted among the candidates, which the note's "of N"
   includes; one more reason the number is the count left by the other filters, not a promise about live messages).
6. De-duplication by `idh` across folders, sorting, then the existing `--text` cap on what is left. Unchanged.

`total` counts the matches found in what was checked, as for the existing `--text` scan; the note tells the reader it may be
incomplete. No search ends in an error because of the cap: exit code 0, as for `--text`.

**Setting:** `header_scan_max`, a key of `defaults` in the piece `mailbox`. **Default 50 000.** The constraint is the one the
orchestrator wrote down: the default must not be below the old silent cut, because a real folder of about 15 000 messages is
searched whole today and a smaller default would truncate a correct answer. The decision is to state the cut, not to make it smaller;
a consumer that wants a tighter bound sets a lower value in its override. `Config.__init__` accepts a number of at least 1
(a bound of 0 would turn every header search into an empty answer with a note); anything else falls back to the default
silently, as the other numeric keys do. The generic rule of `Config` also accepts floats and `0`, so this key gets its own
minimum, and the backend cuts the value to an integer (`int(...)`) before it is used as a slice bound, as it already does
for `text_scan_max`.

**Unchanged on purpose:** the filters other than a header (a `--from` that matches 100 000 messages still goes through the
whole status pass), and `refresh`.

## D4 — A build is announced, not bounded

When `FolderIndex.refresh` reports `rebuilt` (first build, or a rebuild after compaction) and the folder holds messages, the
search adds one note per folder: `the index of FOLDER was built from scratch (N messages)`, in the text output and in the
`notes` of `--json`. `N` is the number of messages the index holds after the build (a message stored twice in the file is two rows and counts
twice). The work itself is the existing full parse and is
not bounded here (proposal, "Known limit"); the note makes a slow first search explicable. It is a note of `search` only
(`thread` and `show` do not carry it) and a later search of the unchanged folder prints nothing. A first build of an empty
folder says nothing (nothing slow to explain).

`LocalBackend.index()` is where the build happens; it records `{folder: N}` for the builds it made and `search` turns them
into notes before the existing no-status note.

## D5 — Settings and interface text

- `DEFAULTS['defaults']['header_scan_max'] = 50000` in `global/scripts/mailbox`, the same key and value in the shipped
  `global/config/mailbox.json`; a test compares the two.
- `Config.__init__`: the minimum of 1 for this key (D3). Decision: the rule "a finite number" (`math.isfinite`) now applies to
  **every** numeric default, not only this one, because a JSON `Infinity` would otherwise reach `int()` and raise; such a
  value falls back to the default like any other mistyped one. The check itself must not raise: `math.isfinite` raises
  `OverflowError` for an integer of 400 digits, so the test is wrapped and that value is treated as mistyped too (G-11,
  found in P4; before it, `Config()` died with a traceback for any numeric default).
- `--help` (the docstring of `global/scripts/mailbox`): `message_id` and its form (normalised, not the raw header that `show`
  prints; compare it with itself); that a header filter on `local` checks at most `header_scan_max` messages per folder,
  newest first, says so when it cuts, and runs before the deleted-message check; that a search which builds an index says
  so. The settings paragraph names `header_scan_max` with its default.
- Contract `global/contracts/mailbox.yaml`: a probe that `--help` mentions `message_id` and one that it mentions
  `header_scan_max`; both hold on any machine configuration (D12 of `external-access`).

## D6 — Compatibility: what a consumer written against today's output sees

| Surface | Before | After |
|---------|--------|-------|
| `search --json`: top-level keys (`account`, `backend`, `freshness`, `total`, `shown`, `skipped`, `notes`, `items`) | as is | unchanged |
| `search --json` item keys (`id`, `date`, `direction`, `party`, `subject`, `attachment`, `folder`) | as is | unchanged, values unchanged; **one new key `message_id`** |
| `thread --json` items | as is | gain `message_id` |
| Text output of a search | as is | byte-identical, except a note where the old output was silently cut (header filter over `header_scan_max`) or silent about a build (D4) |
| Exit codes | 0, 1, 2, 3, 4, 10 | the same |
| Opaque `id`, ordering, `total` for a complete answer | as is | unchanged |
| `--header` on `local`, up to `header_scan_max` candidates (default 50 000) | complete answer | the same set |
| `--header` on `local`, more than `header_scan_max` candidates | silent cut at 50 000, or no answer in time | cut at `header_scan_max` with a note |
| `--header` combined with a date window | as is | the same set, fewer status reads |
| `--header`, one message stored twice in a folder, the header on the older copy only | not listed | listed once (second ordering difference below) |
| A search that builds or rebuilds a folder index | no output about it | a note with the message count (the work is unchanged) |
| An existing index file | works | works, untouched (no schema change) |

- **INFERENCE:** a JSON consumer that reads item keys by name is unaffected. One that compares whole item objects for
  equality, or validates items against a closed schema, sees an extra key; the document names it so it can be allowed.
- **FACT (stated, not changed):** a consumer that de-duplicates on `message_id` must treat `null` as "no identifier" and use
  the item `id` for those messages.
- **One ordering difference, stated:** before, the status pass ran before the header filter, so a message flagged deleted
  could never occupy a place in the 50 000 scanned; now the cap is taken before the status pass, so such a message uses one
  of the places. It cannot be listed, and it matters only for a folder over `header_scan_max` candidates.
- **A second ordering difference, stated (G-13, found in P4):** before, the de-duplication by `Message-ID` ran inside `live`,
  before the header pass, and kept the first row in the order of the selection (the newest copy). Two copies of one message
  in one folder, with the header on the older copy only, were hidden by a header filter. Now every copy is header-tested
  first and the message is listed when any copy matches, which is what `imap` and the cross-folder rule already did. This
  is a decision: it is the same message, and hiding it depended on which copy the client wrote last. A de-duplication
  before the header pass is not restored (it would also bring back G-08). The test pins it.

## D7 — Tests

Only synthetic mailboxes in a temporary home (`mail_selftest` fixtures: `message(..., extra=[('List-ID', …)])` exists).
Fixtures to add: messages with a `List-ID` (two lists), a header occurring twice, one without `Message-ID`, one with a
mixed-case `Message-ID`, and a 300-character subject (checked against the 160-character line rule with a message id present); the `List-ID` messages go in the inbox (format B, no client status
line) and in the sent folder (format A, status lines), because the deleted-since-indexing scenario flips the status flag in
place and needs a status line to flip. The caps are config values, so no large fixture is needed: a cap of
2 or 3 on a folder of 5 to 10 messages. Instrumentation, in-process: a wrapper around `FolderIndex.live` records how many
rows it was given; a counter around `mail_local.open_mbox` counts file opens. The recorded IMAP command stream of the fake
server compares an old-shape search with the new one.

## Unknowns

- **UNKNOWN:** the real gain of the new order (D1 INFERENCE); task 7.4.
- **UNKNOWN:** whether any consumer needs a first build bounded (proposal, "Known limit").
- **UNKNOWN:** consumers outside this repository that validate `search --json` items against a closed schema.
- **HYPOTHESIS:** `live` alone, for a `--from` that matches a very large part of a folder, is the same kind of cost as run
  (A). Out of scope and not measured here.

---

## Deferred (designed in P1, not implemented; not deleted)

Both designs below were written before the real-store measurements of D1. They are kept as written so that a later change
starts from them. **None of it is implemented by `mailbox-search-gaps`; no requirement or task refers to it.**

### Deferred 1 — A header index, backfill and in-place upgrade (was R-IDX, R-UP; tasks 5.1, 5.2, 5.4, 5.5)

**Trigger to bring it back:** a header-only search on the local backend of the real store takes **more than 60 s at normal
load** (a load average below the machine's core count), measured by task 7.4's runs repeated, **or** a folder holds more
candidates than `header_scan_max` so that the stated cut starts to hide mail a consumer needs. Until then the bounded scan
of D3 is enough: run (C), about 15 000 candidates, takes about ten seconds.

**Decision then: the index keeps the decoded values of a configured set of header names.** Alternatives, rejected:

| Alternative | Why not |
|-------------|---------|
| Store every header of every message | Header blocks are a large part of a notification mailbox (several KB each); the index would be a copy of a large part of the store it indexes. |
| Time-bounded scan of the file | Not deterministic: in the synthetic measurement the wall time of the same pass varied 5x to 14x between two runs and was 17 to 85 times its CPU time. A test can only fail it with an injected clock. |
| Count-bounded scan only | Deterministic and testable (and what D3 implements), but it cannot answer the query completely on a folder larger than the bound. |
| Refuse a header filter on `local` | The fallback would stay unusable for the consumer's whole use case. |

**Settings:** `index_headers` (default `["list-id"]`; header names, lowercase, `[A-Za-z0-9-]+`; an empty list keeps none),
`index_backfill_max` (default `20000`: messages per folder and per run whose header values are added to an existing index).
`Config.__init__` would need its own check for the list key. The numbers came from the synthetic cost model (one file access
about 62 µs of CPU, 1 to 5 ms of wall time under extreme load) and would be confirmed on the real store.

**Schema (additive, version unchanged):** `hdrs(rid INTEGER, name TEXT, value TEXT)` with an index on `(name, rid)`, one row
per **occurrence** of a kept header in a message, `value = decode_words(v).casefold()`. Meta keys `hdr_names` (the names kept
when the rows were written, sorted, joined by a comma) and `hdr_floor`. `CREATE TABLE IF NOT EXISTS` adds the table to an old
index file; `VERSION` stays `'3'`, because the `msgs` row layout does not change and a version bump would make `refresh`
rebuild the whole folder inside the first search. A copy of `mailbox` from before such a change can still write the same
cache directory (the installed copy and a development checkout both run against the real mailbox), appending `msgs` rows
without `hdrs` rows, so the coverage would have an upper bound, `hdr_end` (the file size when the last writer that knows
about `hdrs` finished), so those rows are detected, not trusted.

**Match semantics (must equal `ImapBackend._match` and the scan of D3):** name lowercase; value the decoded text, case-folded;
the filter text (case-folded) a substring of any occurrence; empty text matches every message that has the header. In SQL:
`EXISTS (SELECT 1 FROM hdrs WHERE hdrs.rid = msgs.rid AND name = ? AND instr(value, ?) > 0)`. A test would run the same
fixture through the indexed path and the scan path and compare the sets of ids.

**Coverage invariant:** every message whose `start` is at or above `hdr_floor` and below `hdr_end` has its `hdrs` rows for all
names in `hdr_names`. First build or rebuild writes the rows with the message (`hdr_floor = 0`, `hdr_end = size`); appended
mail is covered by the same path (`hdr_floor = min(hdr_floor, begin)`); an index written before has nothing covered
(`hdr_floor = hdr_end = size` at the first refresh); a **backfill step** at the end of `refresh` takes the rows with
`start < hdr_floor`, highest `start` first, at most `index_backfill_max`, reads each header block by the stored
`hstart`/`hend`, writes its rows, commits in batches and lowers `hdr_floor` (to `0` when none are left), so an interrupted
run keeps what it committed. Rows appended by an older copy are filled first, counted in the same budget. Names added to the
configuration reset `hdr_floor` (one floor serves all names); names removed are deleted from `hdrs`.

**What a search would see while coverage is partial:** the header filter on a kept name runs on the covered part only, with
one note per folder, `the header index of FOLDER covers K of N messages so far; search again to extend it`, also in the
`notes` of `--json`; a repetition converges in `ceil(N / index_backfill_max)` searches. A header filter on a name the index
does not keep would use the bounded scan of D3.

**Cost model (HYPOTHESIS until measured):** one backfilled message costs one random header read (about 60 µs of CPU, no
summary parse, no separator scan), so one step of 20 000 is about 1.2 s of CPU plus the file access that dominates under load;
a rebuild would cost the full parse (260 µs per message) plus the separator scan. A refresh that finds the index unchanged
(size and mtime equal, names equal, `hdr_floor = 0`, `hdr_end = size`) still returns at once.

The old requirements, to be rewritten when it returns: indexed answer equals the scan answer; semantics; a header-only
filter does not read the whole folder; messages deleted since indexing stay hidden; combined filters; upgrade without
rebuild; step bound and convergence; older matching message appears once covered; appended mail covered at once; rebuild after
compaction; names changed in configuration; rows added by an older copy; unchanged folder still free; read-only.

### Deferred 2 — `--with-header NAME` (was R-WH; tasks 3.x)

**Trigger to bring it back:** a consumer that needs the value of a header **per result without reading the body** (for
example to group or filter results by a header it did not search on). The only consumer today needs the body of each new
message and calls `show` for it, so a header value in the listing saves it nothing.

- **Why opt-in and generic:** the need would be "any other header" (D2 covers the identifier); `List-ID`,
  `List-Unsubscribe`, `Reply-To`, `X-…` are the likely asks. A fixed extra set always returned would grow every JSON
  document for every consumer and still miss the next header.
- **Syntax:** `--with-header NAME`, repeatable, at most three distinct names (case-insensitive), each `[A-Za-z0-9-]+`;
  anything else exit 2 with one line; accepted only on `search`.
- **Value:** the first occurrence, unfolded, RFC 2047 words decoded (`decode_words`), cut at 1 000 characters; `null` when
  absent; the header as written (`<…>` kept), unlike `message_id`.
- **JSON:** each item gains `headers`, an object whose keys are the requested names in lowercase, in request order; absent
  when the option is not used.
- **Text:** `ID WHEN DIR+MARK PARTY | name=value name=value | SUBJECT`, the segment **before** the subject so the 160-character
  clip cuts the subject first; with the option, the party is cut at 24 characters (48 by default) and each value at 20 with
  an ellipsis; an absent header prints `name=-`. Without the option the line is byte-identical to today's.
- **`local`:** after sorting and limiting, the header block of each **listed** message is read by offset
  (`FolderIndex.header_pairs`). **`imap`:** `_fetch_headers` takes a list of extra names added to the same `HEADER.FIELDS`
  fetch; no extra command.
- **Connector accounts:** untranslatable like `--header`: `mail_connector.Unsupported`, exit 2, one line, nothing on stdout.
