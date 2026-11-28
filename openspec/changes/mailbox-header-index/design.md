# Design — mailbox-header-index

Marks: **FACT** (read in the code or run), **INFERENCE**, **HYPOTHESIS** (to be proven by a task), **UNKNOWN**.
Source of the first design: `openspec/changes/archive/2026-11-27-mailbox-search-gaps/design.md`, "Deferred 1".
Paths below are under `global/scripts/`.

## D0 — The trigger

"Deferred 1" was to return on a measured condition (more than 60 s at normal load, or more candidates than
`header_scan_max`). The developer has explicitly ordered the index; the condition no longer applies. Neither condition is
claimed. "Deferred 2" (`--with-header`) stays deferred and is not touched.

## D1 — The deferred design checked against the current code

| Deferred statement | Today (FACT unless marked) |
|--------------------|----------------------------|
| `CREATE TABLE IF NOT EXISTS` adds tables to an old index; `VERSION` stays `'3'` | Holds: `FolderIndex.__init__` runs `executescript(SCHEMA)`; `refresh` rebuilds only when the stored version differs, the file shrank or a signature fails (`lib/access/mail_index.py`) |
| Match = name lowercase, needle a substring of any occurrence's `decode_words(v).casefold()`, empty needle matches presence | Holds: `header_filter` and `ImapBackend._match`; the pair comes from `Filters.header_pair()` (name stripped and lowercased, text stripped and case-folded) |
| SQL `instr(value, ?) > 0` gives the same | Holds on the local SQLite (run): `instr(x, '')` is 1, and text after a NUL is found |
| Appended mail and a message cut short are covered by the same path | Holds: `refresh` deletes rows with `start >= last_start` and `_scan` inserts them again |
| An older copy sharing the cache only **appends** rows without header rows, so an upper bound `hdr_end` detects them | **Does not hold.** An older copy also deletes (`DELETE FROM msgs` on a rebuild, `DELETE ... WHERE start >= ?` incrementally) and leaves unknown tables alone. `msgs.rid` is `INTEGER PRIMARY KEY` without `AUTOINCREMENT`, so ids are reused (run): old header rows would attach to new messages, inside the trusted range |
| A new list setting needs its own check in `Config` | Holds, and more: the loop over `DEFAULTS['defaults']` accepts numbers only, so a list would **always** be replaced by the default (`mailbox`, `Config.__init__`) |
| "the cap" `cap=50000` / `header_scan_max` | `header_filter` has no cap; `LocalBackend.search` cuts `rows[:header_scan_max]` and writes the note |
| Any header name can be kept | **Does not hold** for `x-mozilla-*`: the client rewrites those lines in place without a size change (`live`, `_signature`), so a kept value would go stale |
| `decode_words` of a header value can be stored | **Not always** (run): a `utf-7` encoded word can decode to a lone surrogate, which SQLite cannot take; an `idna` one makes `decode_words` raise. Fixed at the source (D10) |
| `header_pairs` exists | Holds; it belongs to "Deferred 2" and is not used here |

## D2 — What is kept

The names of `index_headers` (default `["list-id"]`), one row per **occurrence**, `value = decode_words(v).casefold()`.
Storing every header was rejected in the deferred design (the index would copy a large part of the store) and stays
rejected. Consequence, stated: only a search on a configured name uses the index; any other name keeps today's scan.

## D3 — Schema (additive, `VERSION` unchanged)

```
hdrs(rid INTEGER, name TEXT, value TEXT)          index (name, rid), index (rid)
hdr_cov(rid INTEGER, name TEXT, PRIMARY KEY (name, rid))      index (rid)
TRIGGER msgs_headers_delete AFTER DELETE ON msgs: DELETE FROM hdrs and hdr_cov WHERE rid = old.rid
meta hdr_names: the configured names, sorted, joined by a comma
```

`hdr_cov(rid, name)` means "every occurrence of NAME in this message is in `hdrs`" (possibly none). The trigger is stored
in the index file, so it also runs for the delete statements of a copy of `mailbox` that does not know these tables
(**FACT**, run: it fires on a `DELETE` without `WHERE`); rows such a copy inserts have no coverage row and are detected.
The trigger body uses no Python function. Alternative rejected: the `hdr_floor`/`hdr_end` range of the deferred design (D1).

## D4 — Writing during `refresh`

- `FolderIndex(mbox, directory, headers=())`; `LocalBackend` passes the configured names, falling back to
  `('list-id',)` when its defaults carry no key (as `HEADER_SCAN_MAX` does).
- `_scan` writes `hdrs` and `hdr_cov` with each inserted message, from the header block it already reads
  (`message_row`, used only by `_scan`, also returns the split headers). This covers the first build, appended mail and a
  rebuild, in the same transaction as the `msgs` rows: a message and its coverage are committed together or not at all.
- When the configured names differ from `meta hdr_names`, `refresh` deletes the rows of names no longer configured and
  stores the new list in **one** transaction, also on an unchanged folder (before the early return). An added name needs
  nothing: it simply has no coverage. A purge the database refuses (locked) is left for the next run: lingering rows are
  still true. The warm path stays free of any open of the folder file.

## D5 — A header search on a configured name

`LocalBackend.search`, per folder, header branch:

1. `rows = select(f)`; `candidates = len(rows)`; cut to `header_scan_max`. Unchanged.
2. If the name is configured: `FolderIndex.header_lookup(rows, name, needle)`; otherwise `header_filter` as today.
3. The cut note from `scanned < candidates`, `live` on the matches, de-duplication, `--text`: unchanged.

`header_lookup` returns `(matches, scanned)` with the meaning of `header_filter`:

- Coverage and values of the name are fetched by **one statement** (one snapshot), joined to `msgs`.
- A candidate is covered only when the covered message has its `rid`, `start`, `hstart`, `hend` **and** `idh`: a rebuild by
  another process between `select` and the lookup reuses ids, and equal-length messages reuse offsets.
- Walk the candidates in order. A covered one is answered from the index. Any other is read from the folder file. Both are
  tested with the **same functions** `header_filter` uses (one that decodes the values of a name, one substring test in
  Python; no SQL matching, so no difference of semantics). The file is opened only when the first such row appears.
- A failed read stops the pass, as in `header_filter`, and `scanned` counts what was answered.
- What was read is stored in batches of `BATCH`, each in one `BEGIN IMMEDIATE` transaction holding values **and**
  coverage, and only when the file's size and mtime at the time it was opened, the ones the index records at that moment
  and the ones the open file has now are all equal, and only for rows still present as read (same five columns). A block
  shorter than the row says is not stored. On a mismatch or a database error (locked, full) nothing more is stored in that
  run and the matches still stand: a search never fails because the index could not be completed.
- Coverage is inserted once (`INSERT OR IGNORE`); values are inserted only when that insert added the row, so two runs
  completing the same messages never double a value.
- A block that was read is stored for every configured name the message lacks.

So the pass never reads more messages than the scan it replaces, needs no budget setting and converges after one search per
set of candidates. Rejected: a bounded backfill with partial answers (the answer would differ from the scan's); a bounded
backfill with the rest scanned (same reads, one more setting, no gain); filling the whole folder (a narrow date window
would pay for the whole folder once).

**Stated differences:** a covered message needs no read, so when the folder file cannot be opened or a read fails, the
indexed search may answer where the scan stops (and then lists more, or no cut note). And a header rewritten in place that
does not shrink the file and leaves its first and last indexed messages where they were
is not detected, also when mail was appended after them (the limit `refresh` already has for every column).

## D6 — Building is announced on stderr

- `FolderIndex` takes an optional progress callable; `LocalBackend` writes `mailbox: <text>` lines to `sys.stderr`
  (resolved at call time, flushed, folder name through `output.clip`).
- From-scratch build of a folder with a non-empty file (first build or rebuild, whatever the command): a start line
  `mailbox: building the index of FOLDER` before the parse, then `mailbox: index of FOLDER: N messages so far` every
  `PROGRESS_EVERY` messages (a module constant, equal to `BATCH`; the total is unknown while streaming).
- Completion of header rows (D5): `mailbox: building the header index of FOLDER: N messages to read` before the first read,
  then `mailbox: header index of FOLDER: K of N messages` every `PROGRESS_EVERY` reads.
- Nothing is printed for an incremental refresh (appended mail) or when nothing is missing.
- Only folder names and counts: never a header name's value or the filter text.
- The existing result note `the index of FOLDER was built from scratch (N messages)` is a published requirement and is kept
  as it is; the new lines add nothing to stdout or JSON.

## D7 — The cut is the same on both paths

`header_scan_max` bounds the candidates of an indexed search exactly as those of a scan, with the same note. A folder with
more candidates is not searched whole even when covered. Rejected for this change: lifting the cut for covered rows, which
makes the answer differ from the search without the index. A user raises the setting; covered candidates cost no file read.

## D8 — Setting and interface text

- `defaults.index_headers`: `DEFAULTS` of `mailbox` and `config/mailbox.json`, `["list-id"]`.
- Valid: a list whose every item is a string matching `[A-Za-z0-9-]+` (full match); names are lowercased and de-duplicated;
  names starting with `x-mozilla-` are dropped (D1); `[]` is valid and turns the header index off. Anything else falls back
  to the default silently, like the other keys.
- `--help`: the setting and default, which searches use the index, that the answer and the cut are the same, and the
  progress on stderr. The sentence saying a header filter "reads the header" is corrected.
- Contract: a probe that `--help` contains `index_headers`.
- `openspec/specs/mailbox-search-results/spec.md` Purpose: the sentence saying a header index is not part of it is updated.

## D9 — Tests

Synthetic mailboxes in a temporary `HOME` only (`mail_selftest` builders, reserved domains).

- **Two paths:** the same fixtures and filters with `index_headers: []` (scan) and `["list-id"]` (index); compare the whole
  JSON document except `freshness` age and the build note.
- **Encoded words** are put in a finished message by replacing the header line in the bytes (the email library re-encodes).
- **An index written before this change:** build one, then drop the two tables, the trigger and `meta hdr_names` with
  `sqlite3`; `msgs`, `refs` and the other meta keys are what the old code writes.
- **A copy that does not know the tables:** run its statements (`DELETE FROM msgs`, an `INSERT` into `msgs`) on the file.
- **"Uses the index":** count calls of `mail_local.open_mbox` (zero on a covered folder without status lines) and assert
  `header_filter` is not called.
- Existing tests that observe the scan itself (spies on `header_filter`, a failing read) select the scan path with
  `index_headers: []`; their assertions do not change.
- **FACT:** `test_the_old_cut_is_not_hidden_in_the_index_module` rejects the substring `cap` between `def header_filter`
  and `def raw`, and `ReadOnlyByConstruction` restricts `open(` calls in `mail_index.py` (use `mail_local.open_mbox`).
  `header_filter` is also called with a mock as `self`, so the shared predicate is a module-level function.

## D10 — A header value never raises and is always storable

`mail_message.decode_words`, the one decoder of both paths and of `imap`: any exception of a charset decoder (not only
`LookupError`) falls back to UTF-8 with replacement, and the joined result of encoded words has lone surrogates replaced.
This is what its docstring already promises. Effect, the same with and without the index: a header search over such a
value answers instead of ending in a traceback, and a folder holding such a `Subject` or sender can be indexed (**FACT**,
run: today `refresh` raises for both). Rejected: indexing such a message without the value (the search would still raise,
and `refresh` would still raise for a summary column).

## D11 — Concurrent and interrupted runs

Everything that makes an index "complete" is a `hdr_cov` row, written in the transaction of its values; `refresh` writes
rows, coverage and `meta` in one transaction as before. An interrupted run therefore leaves either whole committed batches
or nothing. Two runs on one cache serialise on SQLite's write lock; the checks of D5 cover what changed between a run's
reads and its writes. The order of `refresh`'s own decision (meta read before the lock) is not changed here.
The header tables are created apart from the older schema, the trigger last. When that is refused (an index written before, held by another run, read only or full) the run keeps no
header name and scans the file, as if `index_headers` were `[]`; it waits for the lock as long as any write does, then
answers.

## Compatibility

| Surface | After |
|---------|-------|
| stdout, JSON, exit codes, ids, order, notes | unchanged |
| stderr | new progress lines while an index is built |
| A header value with a charset that cannot be decoded | decoded with replacement instead of a traceback (D10) |
| Existing index file | gains tables and a trigger; no rebuild; completed on demand |
| Older copy of `mailbox` on the same cache | works; its writes are detected (D3) |
| `--header` on a name not configured, `imap`, connector | unchanged |

## Risks

- **A wrong persisted value** is the main new risk (it would outlast the run). Guards: coverage per row, the trigger, the
  five-column check, the three-way size/mtime check, and the two-path tests.
- **Longer write transactions** while completing: at most `BATCH` inserts; reads happen outside the transaction.
- **Mail arriving during a long completion** makes that run store nothing from then on; the next search reads again.

## Unknowns

- **UNKNOWN:** the real-store time of the completion and of a warm search. Not a task of this change (it needs the
  installed copy); the tests prove which reads happen, not wall time.
- **UNKNOWN:** whether a consumer filters on a header other than `list-id`; it would add it to `index_headers`.
