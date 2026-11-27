# Proposal — mailbox-search-gaps

> **Created by:** `/prepara-tarea mailbox-search-gaps` (phase P1 of `run-spec`), 2026-11-27. **Reduced in P2** after the
> orchestrator measured the installed command on the real local store (numbers in `design.md` D1).
> **Status:** PROPOSED. This file and the others of the change describe the reduced scope; the full first design is kept in
> `design.md`, section "Deferred", with the trigger that would bring it back.
> **Related:** `external-access` (adds the `mailbox` command and the library this change edits; merged and installed, not
> archived yet). Marks used below: **FACT** (read in the code or measured), **INFERENCE**, **HYPOTHESIS**, **UNKNOWN**.

## Why

The first project script migrated to `mailbox` lists the notification mails of one mailing list, found by their `List-ID`
header, and keeps a "seen" list. Two things it needed were missing or unusable. Numbers only; no mail content.

1. **Search results carry no message identifier.** FACT (`mail_message.Item.as_json`): a result item has `id`, `date`,
   `direction`, `party`, `subject`, `attachment` and `folder`. `id` is an opaque token of the backend (`l:…` / `i:…`), not
   the `Message-ID` header. A consumer that de-duplicates against its "seen" list can only tell a result is new by running
   one `mailbox show` per result, which it does for every result, new or not. Measured by the consumer on the live server:
   about half a minute for a few dozen results, with several IMAP sessions opened in a row. The consumer needs the body of each **new**
   message, so it keeps calling `show` for those; what it gains from an identifier in the results is skipping `show` for the
   results already in its "seen" list.
2. **A header filter on the `local` backend is slow, and its cut is silent.** FACT, measured by the orchestrator on the
   installed copy and the real local store (a few folders, the inbox holds about 15 000 live messages, the index files already
   existed; the machine was under load). Wall times are rounded to orders of magnitude; the exact figures are kept in the run's
   unpublished state file:

   | Run | Wall time | Result |
   |-----|----------:|--------|
   | (A) `search --backend local --folder inbox --limit 1`, no filter | several seconds | — |
   | (B) header filter with a date window, inbox | a few seconds | every match (the same results the live server returns) |
   | (C) the same header filter, no date window | about ten seconds | every match |
   | (D) every folder, header filter with a date window | about twenty seconds | every match |

   The consumer's "did not finish in two minutes" was seen once on a heavily loaded machine and is **not reproduced**. The path
   does not fail: it costs two file accesses per candidate message (below), so its time is proportional to the number of
   candidates and grows with machine load. It is correct at normal load (run C returns every match) and not
   bounded: nothing caps the first of the two passes, and the cap of the second one is silent.

### What the path costs (verified by reading the code; details and marks in `design.md` D1)

FACT, in three parts:

- **The index cannot answer a header filter.** `mail_index.py`: the index keeps summary columns (sender, recipients,
  subject, date, `Message-ID`, attachment guess, offsets) and no arbitrary header. `FolderIndex.select` ignores
  `Filters.header`, so a search whose only filter is a header selects **every live message of the folder**.
- **Two per-message file accesses, in the wrong order.** `mail_local.LocalBackend.search` runs `FolderIndex.live(select(f))`
  and then `FolderIndex.header_filter(rows, name, text)`. `live` reads the client's status line of **every** selected row
  (no cap), then `header_filter` reads and parses the header block of up to 50 000 rows. The status pass is spent on
  messages the header filter then drops.
- **The cut is silent.** `header_filter` returns `(rows, scanned)` and `search` discards `scanned`, and its `cap=50000` is a
  default argument, not a setting. A folder with more than 50 000 candidates is searched only in its newest 50 000 and the
  output does not say so. The caps of gap G-17 (`text_scan_max`, `imap_scan_max`) apply to `--text` and to the server
  candidates; neither is used by the header path.

## What Changes

- **`search` returns the message identifier on every backend** that `mailbox` reads itself (`imap`, `local`): an item gains
  `message_id` in `--json` (always; the normalised `Message-ID`, `null` when the message has none). The text line is
  unchanged. `thread --json` items share the serializer and gain the same field.
- **On `local`, a header filter runs before the status pass.** The newest candidates left by the other filters are read for
  the header first, and `live` runs only on the matches, so the status pass reads at most the number of matches instead of
  the whole folder. FACT of the order; the saving on the real store is **INFERENCE** until task 7.4 repeats runs (A) to (D).
- **The header scan is bounded by one setting, `header_scan_max`, with a stated cut.** At most that many candidates per
  folder, newest first; when the bound leaves messages out, a note says how many were checked of how many, in the text
  output and in the `notes` of `--json`. The silent 50 000 is gone. **The default is 50 000, not lower**: the default is not below the
  old silent cut, because a real folder of about 15 000 messages is searched whole today and a smaller default would
  truncate a correct answer. The requirement is that a cut is stated, not that it is smaller.
- **A search that has to build an index says so.** A first build or a rebuild after compaction is unchanged work (a full
  parse of the folder file, inside the search that needs it) but is now announced in a note with the message count, so a
  slow first search is explained instead of silent.
- `--help`, the contract probes and the shipped config piece are updated with the identifier and the new setting.

## Deferred (designed, not implemented)

Two designs written in P1 are kept in `design.md` ("Deferred") with a written trigger each, and are **not** part of this
change: a header index (a table of kept headers, `index_headers`, a bounded backfill and in-place upgrade of an existing
index, `index_backfill_max`) and `--with-header NAME` (a header value per result). The measurements show a header filter
that finishes in seconds at normal load, and the only consumer needs the body of each new message, not a header value per
result. Triggers are in `design.md`.

## Known limit: the first build of an index is still unbounded

FACT: `FolderIndex.refresh` parses the whole folder file when no index exists or after a compaction, inside the search that
needs it, and nothing in this change bounds that work. The consumer's run did not include a build (the index files already
existed). This change only announces a build. If a first build proves to be the cost a consumer hits, the follow-up is
a resumable first build bounded like a scan, a change of its own.

## Capabilities

- New: `mailbox-search-results` (this delta, ADDED requirements only). **How the delta is expressed** (decision, verified):
  the capability `mailbox-access` of `external-access` is not under `openspec/specs/` yet, and `openspec validate` reports
  that an archive would refuse a `MODIFIED` or `RENAMED` delta for a capability with no baseline ("only ADDED requirements
  are allowed for new specs"; checked with `openspec validate --strict` on a scratch change). The precedent in this
  repository is `heavy-job-batch-and-orphan-gaps`: a new capability with its own ADDED requirements and a "Related" line.
  The requirements below are worded as additions and never restate or contradict a requirement of `mailbox-access` (its
  "Line content" and "Machine output" scenarios stay true: this change only adds a key and notes). If a later review wants
  the old requirements amended in place, that is done after `external-access` is archived.

## Impact

- Edited, all inside the module `access`: `global/scripts/mailbox` (setting and its validation, `--help`),
  `global/scripts/lib/access/mail_message.py` (`Item`), `mail_index.py` (`header_filter` loses its cap argument: the one cut is the caller's),
  `mail_local.py` (`search`, build note), `mail_imap.py` (item), `mail_selftest.py` (fixtures, and the self-test counts them),
  `global/config/mailbox.json`,
  `global/contracts/mailbox.yaml`, and the tests `scripts/toolkit/tests/pieces/test_mailbox.py` (and `test_access_helpers.py`
  only if a helper moves).
- Not edited: the `stores` command, `output.py` (the 160-character rule), the skill `cuentas-externas` (its body has a size
  budget and the settings are documented in `--help`), `README.md` and `examples/override-full/` (no module, config key of
  the example or user-facing table changes; the shipped config gains one default), the index schema (nothing is stored
  differently, so no existing index file is touched or upgraded).
- Cost: none on `imap` or on `local` for the identifier. A header filter on `local` does at most one header read per
  candidate (before: one status read per selected row plus one header read per candidate).
- Compatibility: see `design.md` D6. Existing JSON fields, exit codes and ids do not change; the text output is
  byte-identical unless a note applies (a header-filter cut, an index build).

## Out of scope (by design decision already taken)

- Regular expressions in filters; exposing message flags (deleted/seen); any write operation; any new dependency (standard
  library and `openssl` only); any change to the `stores` command.
- Connector accounts: they delegate the search to the session (exit 10) and the identifiers are the connector's own; nothing
  changes for them, and `--header` on them stays a usage error (exit 2).
- Bounding the status pass of `live` for searches that are not a header filter: run (A) (several seconds for an unfiltered
  `--limit 1` on about 15 000 messages) is the same class of cost and is **not** changed here; recorded in `design.md` as UNKNOWN.
- A new subcommand to build the index ahead of time.
