# GAPS — mailbox-header-index (honest review)

> **Mode:** A
> **Real status:** gaps hydrated and implemented; post-apply review below.

## Methodology (early stop)

| Iter | Focus | Honest result |
|------|-------|---------------|
| 1 | `mail_index.py`, `mail_local.py`, `mail_message.decode_words` | G-01, G-02 |
| 2 | Concurrency and persistence of design D4/D5 | G-03, G-04, G-05, G-09 |
| 3 | "Same answer" under failures and states | G-06, G-07, G-08 |
| 4 | Spec, design, tasks against each other | G-10 |
| 5 | Stop check | no further candidate with evidence |

## Consolidated matrix

Legend: **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN** | **FACT** (pending)

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-01 | high | A charset whose decoder raises still ends a header search (and, in a summary column, every search) with a traceback; D4 only keeps the build alive for the header tables | run, synthetic: `decode_words` raises `UnicodeError` for `idna` and `undefined`; `FolderIndex.refresh` raises for such a Subject. `mail_message.decode_words` catches `LookupError` only, against its own docstring | HYDRATED | R-EQ, new R-DEC |
| G-02 | high | Text SQLite cannot take (lone surrogate) breaks `refresh` when it is a summary column; D4 handles header values only | run, synthetic: `utf-7` Subject makes `refresh` raise `UnicodeEncodeError` | HYDRATED | new R-DEC |
| G-03 | medium | D5 trusts a coverage row by `rid` + `start`; another process can rebuild between `select` and the lookup, and equal-length messages give the same pair to a different message | `rid` is reused (`SCHEMA`: no `AUTOINCREMENT`); `LocalBackend.search` selects outside any transaction | HYDRATED | R-INC / new R-CONC |
| G-04 | high | D5 compares size and mtime only at store time: a file rewritten in place after the read, then refreshed by another process, passes the check and stores a block of the old content under a new row | design D5, third bullet of "What was read is stored" | HYDRATED | new R-CONC |
| G-05 | medium | D5 says nothing about a store that fails (locked or full database): `main` turns any `sqlite3.Error` into exit 1, so a header search the scan would answer would fail | `global/scripts/mailbox` (`main`, `except sqlite3.Error`) | HYDRATED | R-OLD |
| G-06 | medium | Under a read failure that is not "cannot open and all covered", the indexed answer holds more than the scan's (covered rows need no read); the spec allows one narrower difference | `mail_index.header_filter` stops at the first failed read; D5 answers covered rows without reading | HYDRATED | R-EQ |
| G-07 | low | A header rewritten in place in the middle of a folder, same size, is not detected: the scan would read the new bytes, the index keeps the old value; the spec says "same folder files, same answer" without this | `mail_index.refresh`, same-size branch; proposal "Known limits" | HYDRATED | R-EQ |
| G-08 | medium | The two-path test of tasks 1.2/3.2 omits: a name not in `index_headers`, mail appended, a copy that does not know the tables, an old index | `tasks.md` 1.2 and 3.2 | HYDRATED | R-EQ |
| G-09 | medium | No scenario or task for two searches at once or for an interrupted from-scratch build | spec delta, no such scenario | HYDRATED | new R-CONC |
| G-10 | low | D5 matches in SQL and needs a special case for an unencodable needle; comparing the stored value in Python with the scan's own predicate removes both the case and any difference of semantics | design D5 point 2 | HYDRATED | design D5 |
| G-11 | info | `--json` stdout stays one document while progress goes to stderr | spec delta, "Completion is announced" | ALREADY | R-PROG |
| G-12 | low | A copy of the previous code sharing the cache is simulated by its SQL statements in the tests; running that code itself was not done (the permission system denied the command) | tests `reinsert_as_the_earlier_code`, trigger test | UNKNOWN | R-INC |
| G-13 | medium | An index without the header tables that is held by another run's write lock, or read only, ended the search (also on an unchanged folder, which the earlier code answered) | confirm review, run on synthetic fixtures: `database is locked`, `attempt to write a readonly database` from `FolderIndex.__init__`; the lock test of 3.3 recreated the tables first | HYDRATED | R-CONC, design D11, task 3.4 |
| G-14 | low | The stated difference "undetected rewrite" asked for an unchanged file size; the refresh also misses a middle header rewritten in place when mail was appended after it | confirm review, run: `rebuilt False`, index and scan differ | HYDRATED | R-EQ wording, design D5 |
| G-15 | low | A run still using a name another run has just removed from `index_headers` can store rows of it after the purge; they stay until the names change again. They are true of their message and follow it, so no answer changes | `_purge_headers`, `_store_headers` | INFERENCE | design D4 |

## Post-apply review

| Check | Result |
|-------|--------|
| Every requirement of the delta against code and tests | each scenario has a test; `tasks.md`, "Evidence" |
| G-01 to G-10 | implemented as hydrated; G-01 and G-02 fixed in `decode_words` for both paths and `imap` |
| New candidates | G-12, G-13 (G-13 reproduced and fixed by the confirm review) |

## Confirm review (independent, after apply)

Throwaway scripts outside the repository, synthetic mbox folders in temporary directories, index against scan.

| Run | Covered | Result |
|-----|---------|--------|
| Random operations | repeated, folded and encoded headers, odd charsets, mixed case, empty, absent and non-ASCII needles, small `header_scan_max`, append, compaction, rewrite, deleted flag, names added and removed, tables dropped, rows reinserted, a writer without the header tables (its statements) | 3 080 searches before and after the fix of G-13: no difference between index and scan |
| Kill before each SQL statement | first build, old index, appended mail, compaction, names removed | every point answers as the scan; no orphan or doubled row |
| Processes at once | 14 rounds of 5 processes with different `index_headers` while the folder changed | 210 answers equal to the scan |
| Folder changing while headers are read | 500 seeds | 1 difference from a fresh index, equal to the scan over the same rows: the existing change detection (same size, first and last message unchanged) |

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (spec OK; `/aplica-tarea` only) | 12 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 3 |

## Verification (this document)

- **Verified:** G-13 and G-14 by running them; the decoder and `refresh` behaviour of G-01 and G-02 (run on synthetic fixtures in a temporary directory);
  the other rows by reading the code and the artefacts.
- **Not verified (after apply):** G-12; wall time on a real store (design, "Unknowns"); nothing was installed.

Gaps pending (mejora + apply): 0
