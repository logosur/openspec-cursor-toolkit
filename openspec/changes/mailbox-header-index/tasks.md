# Tasks — mailbox-header-index

Requirement references: **R-SCAN** = header filter before the status pass and bounded (modified), **R-IDX** = answered from
the header index, **R-EQ** = same answer, **R-INC** = incremental, **R-OLD** = completed on demand, **R-PROG** = stderr,
**R-CFG** = the setting, **R-DEC** =
undecodable values, **R-CONC** = interrupted and concurrent runs (all in `specs/mailbox-search-results/spec.md`). Design decisions: `design.md` D0 to D9.
`--with-header` stays deferred: no task refers to it.

One implementer, in order. Every test runs in a temporary `HOME` with synthetic mailboxes (reserved domains only); no task
reads the real mail store, the real `HOME` or real configuration, and none writes under `~/.claude` or `~/.config`. Module
check after each task:
`python3 -m unittest scripts.toolkit.tests.pieces.test_mailbox scripts.toolkit.tests.pieces.test_access_helpers`.

## 1. Setting and reference tests

- [x] 1.1 `index_headers` in `DEFAULTS['defaults']` of `global/scripts/mailbox` and in `global/config/mailbox.json`, with its
  own validation in `Config.__init__` (D8; the numeric loop must not replace the list). Check: new tests for R-CFG "Shipped
  defaults agree", "Valid values", "Mistyped setting"; the existing shipped-defaults test passes.
- [x] 1.2 Before touching the index: a two-path test (D9) over the R-EQ "Two paths on the same fixtures" matrix and "Same
  cut", comparing `index_headers: []` with `["list-id"]`. Check: it passes now, when both configurations still scan; it
  stays unchanged afterwards. Record the module test count before and after.

## 2. The index

- [x] 2.0 `decode_words` never raises and returns storable text (D10). Check: R-DEC, unit tests with `idna`, `undefined`
  and `utf-7` surrogate words, and `FolderIndex.refresh` of a folder holding them as `Subject` and `List-ID`.
- [x] 2.1 Schema: `hdrs`, `hdr_cov`, their indexes and the delete trigger; `FolderIndex(..., headers=())` (D3, D4). Check:
  opening an index file that lacks them adds them with `stats.rebuilt` false; deleting a `msgs` row, and all rows, with raw
  SQL leaves no header row (R-INC, third scenario, trigger half).
- [x] 2.2 `_scan` writes header values and coverage with each message (`message_row` also returns the split headers). Check:
  rows after a first build (several occurrences, encoded words, case-folded), after appended mail (no rebuild), after a
  compaction.
- [x] 2.3 `refresh` purges names no longer configured and records `meta hdr_names`, also when the folder is unchanged (D4).
  Check: R-OLD "Configured names change" (purge half); the existing warm-run test still opens nothing.
- [x] 2.4 One module-level match predicate used by `header_filter`; new `header_lookup(rows, name, needle)` answering covered
  rows from the index and the rest from the file, storing nothing yet (D5). Check: unit tests that it returns the same
  `(matches, scanned)` as `header_filter` for covered, uncovered and mixed rows, an empty needle, and a failed read; zero
  file opens when all rows are covered.
- [x] 2.5 `header_lookup` stores what it read, in batches, guarded by the size/mtime and `rid` + `start` checks (D5). Check:
  R-OLD "Old index" (second call opens nothing), "Interrupted completion", "The file changed meanwhile"; R-INC "Rows deleted
  and added by a copy that does not know the index".

## 3. The search

- [x] 3.1 `LocalBackend` passes the names to `FolderIndex` and uses `header_lookup` for a configured name with an encodable
  needle, `header_filter` otherwise (D5, D7). Existing tests that observe the scan itself set `index_headers: []`, with their
  assertions unchanged. Check: R-IDX (three scenarios, counting `open_mbox` and spying `header_filter`), R-OLD "A search
  without a header reads nothing more", R-SCAN (existing tests on the scan path plus the cut and deleted-since-indexing on
  the index path).
- [x] 3.2 Two-path coverage of the states: extend the test of 1.2 with appended mail, compaction/rebuild, an index written
  before this change, a copy that does not know the tables, a name not configured, the undecodable values and a failed
  read. Check: R-EQ all scenarios and R-INC "Appended mail", "Compaction and rebuild", end to end through the command.
- [x] 3.3 Interrupted and concurrent runs (D11). Check: R-CONC four scenarios, plus two real processes searching the same
  old index at once.

- [x] 3.4 An index written before that cannot take the header tables (held, read only) is scanned instead of ending the
  search (D11). Check: R-CONC "An older index that cannot take the tables"; the test failed with `database is locked`
  before the fix.

## 4. Progress on stderr

- [x] 4.1 The progress callable and the header completion lines (D6). Check: R-PROG "Completion is announced" with
  `PROGRESS_EVERY` patched small (order: start line before the first read), stdout parses as one JSON document without those
  words, and nothing is printed for a covered search.
- [x] 4.2 The from-scratch build lines (D6). Check: R-PROG "A build from scratch is announced" and "Silent when nothing is
  built" (appended mail, empty file); the existing build-note tests pass unchanged.

## 5. Interface text and gates

- [x] 5.1 `--help` (D8), a contract probe for `index_headers`, one `mailbox self-test` check of a repeated header search,
  and the Purpose sentence of `openspec/specs/mailbox-search-results/spec.md`. Check: R-CFG "Help text", the `Contract` and
  `SelfTest` tests, `python3 scripts/validate-toolkit.py` with 0 errors.
- [x] 5.2 Gates on the final tree. Check, all exit 0 with counts recorded: the two piece test modules;
  `python3 -m unittest scripts/test_validate_toolkit.py scripts/test_privacy_check.py`;
  `python3 scripts/validate-toolkit.py`; `bash examples/override-full/try.sh` (throwaway `HOME`);
  `openspec validate mailbox-header-index --strict`; `python3 scripts/privacy-check.py --require-private`.

## Evidence (final tree)

- 1.2: the two piece modules had 272 tests before and 316 after. The two-path test passed before the index existed; it was
  later run in process (speed) and its cut test gained the state "index of the earlier code". Its comparisons are unchanged.
- Confirm review, after 3.4: the two piece modules (317 tests), `mailbox self-test`, `validate-toolkit.py`,
  `openspec validate --strict` and `privacy-check.py --require-private`, all exit 0.
- 5.2, all exit 0: the two piece modules (316 tests); `scripts/test_validate_toolkit.py` with `scripts/test_privacy_check.py`
  (81 tests); `validate-toolkit.py` (0 errors, 0 warnings); `try.sh` (every step passed); `mailbox self-test` in a temporary
  `HOME`; `openspec validate mailbox-header-index --strict`; `privacy-check.py --require-private` (0 findings).
- Mutation checks: removing the file-state guard, the same-message check or the single insert of coverage each fails a
  test of `HeaderIndexInterruptedAndConcurrent`.
