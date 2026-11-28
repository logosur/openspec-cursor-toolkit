# Proposal — mailbox-header-index

> **Created by:** `/prepara-tarea mailbox-header-index` (phase P1 of `run-spec`).
> **Status:** PROPOSED. Not implemented.
> **Starts from:** `openspec/changes/archive/2026-11-27-mailbox-search-gaps/`, `design.md` "Deferred 1 — A header index,
> backfill and in-place upgrade". Capability: `mailbox-search-results` (`openspec/specs/`).
> Marks: **FACT** (read in the code or run), **INFERENCE**, **HYPOTHESIS**, **UNKNOWN**.

## Why

A header filter on the `local` backend reads and parses the header block of every candidate message on every search.

- **FACT** (`mail_local.LocalBackend.search`, `mail_index.FolderIndex.header_filter`): the index keeps summary columns and
  offsets, no header value; `select` ignores `Filters.header`; each candidate (up to `header_scan_max` per folder) costs one
  seek, one read and one parse, and nothing is kept for the next search.
- **INFERENCE:** the time of such a search therefore grows with the number of candidates and with machine load, and a
  repeated search pays it again.

The index was designed and deferred with a trigger (a header search over 60 s at normal load, or a folder with more
candidates than `header_scan_max`). **The developer has now explicitly ordered the index, so that trigger condition no
longer applies.** No claim is made that either condition was met.

## What Changes

- The folder index keeps the decoded, case-folded values of a configured set of header names (new setting `index_headers`,
  default `["list-id"]`; `[]` turns it off). Additive tables in the existing index file; no version bump, no rebuild.
- A `--header` filter on a configured name is answered from the index. Candidates the index does not cover yet (an index
  written before this change, messages added by a copy of `mailbox` that does not know the tables, a newly configured name)
  are read in that same search, exactly as the scan reads them today, and kept for the next one.
- New mail, a compaction and a rebuild keep the index up to date through the existing incremental refresh.
- The answer is the one of the search without the index: same ids, `total`, order, notes and exit code, with the same
  `header_scan_max` cut.
- While an index is being built (a folder from scratch, or the header part of an existing one) the command says so on
  **stderr**, with progress. Nothing about it enters stdout or the JSON document.
- `--help`, one contract probe and the shipped config piece describe the setting.
- A header value whose charset makes the decoder raise, or yields text that cannot be stored, is decoded with replacement
  instead of ending the command in a traceback (**FACT**, run: today it does, also while indexing a `Subject`).

## Differences from the deferred design

Each one is explained in `design.md` (D1, D3, D5, D7).

| Deferred design | This change | Why |
|-----------------|-------------|-----|
| Coverage as an offset range (`hdr_floor`, `hdr_end`) | Coverage per message and name, plus a delete trigger | **FACT:** row ids are reused, and a copy that does not know the tables deletes `msgs` rows without them: a range would trust values of other messages |
| `index_backfill_max`; partial coverage answers from the covered part with a note | No such setting; the missing candidates are read in the same search | The answer must be identical to the search without the index |
| Coverage message in the results' notes | Progress on stderr only | Same requirement: never in stdout or JSON |
| Backfill at the end of every `refresh` | Only inside a header search on a configured name, only for its candidates | A search without a header never pays; a header search never reads more than the scan it replaces |
| (implied) no bound for a configured name | The `header_scan_max` cut and its note apply on both paths | Identical answer; the setting can be raised, and a covered candidate costs no file read |

## Out of scope

- **Returning extra headers in the listing** (`--with-header`, "Deferred 2"): stays deferred, untouched.
- Keeping every header of every message; headers not in `index_headers` use today's bounded scan.
- Lifting or changing `header_scan_max`; bounding the first build of a folder index; a subcommand that builds ahead of time.
- `imap` and connector accounts; any write to a mail store; any new dependency.

## Known limits

- The first header search on a copy indexed before this change still reads every candidate once (announced on stderr).
- Two copies of `mailbox` with different `index_headers` sharing one cache directory delete each other's extra names and
  read them again: answers stay correct, the saving is lost.
- The index trusts the existing change detection of `refresh` (size, mtime, first and last message signatures), as the
  other columns already do.

## Capabilities

- Modified: `mailbox-search-results` — one requirement modified (the header filter may check from the index), eight added.

## Impact

- Edited: `global/scripts/lib/access/mail_index.py`, `mail_local.py`, `mail_message.py`, `global/scripts/mailbox` (setting, validation,
  `--help`), `global/config/mailbox.json`, `global/contracts/mailbox.yaml`, `mail_selftest.py` (self-test check),
  `scripts/toolkit/tests/pieces/test_mailbox.py`, and the Purpose sentence of
  `openspec/specs/mailbox-search-results/spec.md`.
- Not edited: `mail_imap.py`, `mail_connector.py`, `output.py`, `stores`, the skill `cuentas-externas`, `README.md`.
- Disk: one coverage row per message and configured name, plus one row per occurrence, in the existing 0600 index file of
  the private cache directory.
