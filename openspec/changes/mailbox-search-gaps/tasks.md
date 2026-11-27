# Tasks — mailbox-search-gaps

Requirement references: **R-ID** = identifier, **R-KEEP** = existing output unchanged, **R-SCAN** = header filter before the
status pass and bounded, **R-BUILD** = a build is announced, **R-CFG** = the setting and the help, **R-EXIT** = exit codes
(all in `specs/mailbox-search-results/spec.md`). Design decisions: `design.md` D1 to D7. The header index and `--with-header`
are deferred (`design.md`, "Deferred"): no task refers to them.

Each task ends with its own check. Every test runs in a temporary home with synthetic mailboxes; no task reads a real
mailbox except the last three tasks (the ones that need the installed side). Run the piece tests by module, not the whole discovery:
`python3 -m unittest scripts.toolkit.tests.pieces.test_mailbox scripts.toolkit.tests.pieces.test_access_helpers`
(the full discovery is task 7.6).

## 1. Baseline and fixtures

- [x] 1.1 Before any code change, capture on the synthetic fixture the current text output and the current `--json` output of
  `search` and `thread` (both backends) as the expected values of a compatibility test, with the local index already built
  (the second run of the same search, so no build note is involved). Check: the new test passes on the unmodified code
  (R-KEEP "Compatibility of existing output"). Evidence: `CompatibilityLocal` and `CompatibilityImap` (5 tests) passed on the
  unmodified code before any product edit; the expected values are the literal `BASELINE` in `test_mailbox.py`.
- [x] 1.2 Fixtures in `mail_selftest`: two messages with a `List-ID` (two lists), one with `List-ID` twice, one without
  `Message-ID`, one with a mixed-case `Message-ID`, and a 300-character subject, in the inbox (format B) and in the sent
  folder (format A, which carries status lines). They live in `list_messages()`, apart from `standard_messages()`, so no
  count of the standard fixture changes. Check: the whole `test_mailbox` module still passes and `mailbox self-test` exits 0.

## 2. The identifier (need 1)

- [x] 2.1 `Item` gains `message_id`; `LocalBackend._item` fills it from `row['mid']`, `ImapBackend._item` from `info['mid']`;
  `Item.as_json` emits `message_id` (`null` when empty); `thread` items share it (design D2). Check: tests for the R-ID
  scenarios "Identifier on the local backend", "Message without an identifier", "Unique within a result", "Thread items",
  "Same string on both backends", and the compatibility test of 1.1 (it must now differ only by the key).
- [x] 2.2 No extra work: the recorded IMAP command stream of a 25-result search has the same commands as before (one header
  fetch per batch, no fetch of a single message); on `local` a search of an already indexed folder without status lines opens the
  folder file zero times. Check: the R-KEEP scenario "No extra work per result".
- [x] 2.3 Connector accounts untouched. Check: R-KEEP scenario "Connector accounts do not change" (exit 10; `--header` exit 2,
  empty stdout).

## 3. The setting

- [x] 3.1 `header_scan_max` (default 50 000) in `DEFAULTS` of `global/scripts/mailbox` and in `global/config/mailbox.json`;
  `Config.__init__` accepts a number of at least 1 for it, anything else falls back to the default, and the backend uses
  `int(...)` of it; the value reaches
  `LocalBackend` through `cfg.defaults`. Check: R-CFG "Shipped defaults agree", "Default is not below the old cut",
  "Mistyped setting".

## 4. A header filter on `local`: before the status pass, bounded, stated (need 2)

- [x] 4.1 `LocalBackend.search` for a header filter: select, cap at `header_scan_max` before any file
  access, header pass, note when the scan checked fewer than N, `live` on the matches only; `FolderIndex.header_filter` loses
  its `cap=50000` argument altogether (the one cut is the caller's) and reports what it scanned. Check: R-SCAN "Status pass reads only the matches", "Cap reached",
  "Cap not reached", "The old silent cut is gone" (all with the cap set to 2 or 3, so no large fixture).
- [x] 4.2 Semantics and combinations unchanged. Check: R-SCAN "Same matches as before the change" (a header occurring twice, a
  case-insensitive substring, an empty needle that matches every message having the header), "Combined with other filters"
  (date window and `--from`, then `--text` with its own cap), "Messages deleted since indexing stay hidden", and "Read-only" (a header search leaves the store files byte-identical).
  Evidence: `HeaderFilterSemantics` (12 tests) was also run against the product files of `HEAD` (everything but the
  fixtures in `mail_selftest.py`): the 9 tests of match semantics, deleted-since-indexing, limit, exit codes and read-only
  pass there; the 3 that fail there are the ones for what this change adds (the note, `message_id` in the long-subject test,
  and the second ordering difference of D6: a message stored twice with the header on the older copy only, G-13). So the
  matches are the ones the backend gave before, except that one stated case.
- [x] 4.3 Exit codes. Check: R-EXIT (a capped search exits 0; no backend 3; stale id 4; a malformed `--header` 2).

## 5. A build is announced

- [x] 5.1 `LocalBackend.index()` records a build or rebuild (`stats.rebuilt` with messages), `search` adds the note with the
  message count (design D4). Check: R-BUILD "A build is announced" (text and `--json` notes; none on the second run of an
  unchanged folder; one after a compaction; none for an empty folder).

## 6. Interface text and contract

- [x] 6.1 `--help` (the docstring of `global/scripts/mailbox`): the identifier and its form, the bound of a header filter on
  `local` and its note, the setting, the build note. `global/contracts/mailbox.yaml`: a probe that `--help` contains
  `message_id` and one that it contains `header_scan_max`; both must hold on any machine configuration (D12 of
  `external-access`). Check: R-CFG "Help text"; the `Contract` test of `test_mailbox` runs every probe;
  `python3 scripts/validate-toolkit.py` 0 errors.

## 7. Verification

- [x] 7.1 `openspec validate mailbox-search-gaps --strict` valid; `python3 scripts/privacy-check.py` reports 0 findings on
  the change folder and `--staged --require-private` after the last `git add`. Check: both exit 0. Evidence: `openspec validate mailbox-search-gaps
  --strict` valid; the privacy check 0 findings on the change folder and, after staging the files of this change (not the
  state file `RUN-LOOP.md`), `--staged --require-private` 0 findings (private denylist: 61 terms, 169 quotes).
- [x] 7.2 Local gates of the repository: `python3 -m unittest scripts/test_validate_toolkit.py`,
  `python3 scripts/validate-toolkit.py`, `python3 -m unittest scripts/test_privacy_check.py`, and the module tests of this
  piece (`test_mailbox`, `test_access_helpers`). Check: all exit 0, counts recorded. Evidence: validator tests 59 OK; `validate-toolkit.py` 0 errors, 0 warnings; privacy
  tests 22 OK; `test_mailbox` + `test_access_helpers` 233 tests OK (182 before this change).
- [x] 7.3 `bash examples/override-full/try.sh` with the module on: the `mailbox` probes (including the two new ones) and the
  self-test pass. Check: every `access` step passes (steps of other modules are not this change's). Evidence: exit 0, every step passed
  (install, status, contract probes of every installed piece, the supervisor-lock, test-account and process-kill-gate
  self-tests, drift, second install, uninstall).
- [ ] 7.4 [prod-verify] Real-store timings on the installed copy, after the install (needs the supervisor's install): repeat the four runs
  of `design.md` D1 on the real local store, (A) `search --backend local --folder inbox --limit 1`, (B) the consumer's header
  filter with a date window on the inbox, (C) the same without a date window, (D) every folder with a date window, and compare
  the wall time and the result count of each with the figures recorded in the run's state file, noting the machine load. Check:
  the results are the same sets as before, and the times are recorded next to the old ones; no claim of a gain beyond the numbers.
- [ ] 7.5 [prod-verify] With a live account and the consumer's "seen" list: the consumer's query with `search --json` returns `message_id`
  for all its results in one session, and results whose `message_id` is already in its seen list need no `show`. Check: the
  consumer's query needs `show` only for the new messages.
- [ ] 7.6 [prod-verify] Full test discovery (`python3 -m unittest discover -s scripts/toolkit/tests -t .`) is green in CI on the pushed
  branch, checked before the branch is integrated (as task 7.6 of `external-access`).
