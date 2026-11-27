# GAPS — mailbox-search-gaps (honest review)

> **Date:** 2026-11-27
> **Mode:** A (change folder `openspec/changes/mailbox-search-gaps/`)
> **Real status:** round 1 closed: the 4 FACT gaps of the pre-apply pass were hydrated, applied and re-checked; 2 more were
> found and fixed while applying and 3 more by the independent confirm review (P4); nothing is pending. Three `[prod-verify]` tasks stay open by design.

## Methodology

Single-agent passes (pre-apply and post-apply), because the reduced scope touches six product files and the evidence is a
direct read of them plus the tests that exercise them; a parallel search would not have found more. Each candidate was
checked against the code with a path and line, against the spec, design and tasks, and, for behaviour, by a test that fails
without the code.

| Iter | Focus | Honest result |
|------|-------|---------------|
| 1 | Spec requirements against `mail_local.search`, `mail_index.header_filter`, `Config`, `Item` | 3 FACT (G-01, G-02, G-03) |
| 2 | What the scenarios can observe; what the fixtures contain | 1 FACT (G-04), 1 INFERENCE (G-05) |
| 3 | Installed copy vs development checkout on one cache, existing indexes, other backends | 0 FACT: no schema change, so no index is touched (G-06 ALREADY) |
| 4 | Cross-check spec, design, tasks, proposal numbering and names | 0 new FACT |
| 5 | STOP check (pre-apply) | remaining candidates INFERENCE, UNKNOWN, ALREADY or REJECTED by the scope decision |
| 6 | Post-apply: spec ↔ code ↔ tests, on the final tree | 2 FACT found while applying and fixed in the same phase (G-08, G-09); 0 pending |
| 7 | P4, independent confirm review (fresh read of spec, code, tests and the claims of these documents) | 3 FACT (G-11, G-12, G-13) found, each fixed forward with a test that fails without the fix; the claims of `READY-TO-APPLY.md`, `GAPS.md` and `design.md` were checked against the code, the counts (25 scenarios, 182 to 233 tests) and a run of the tests against the product files of `HEAD`: the compatibility baseline holds (5 tests pass there), and one claim was false ("same matches", G-13) and is corrected; 0 pending |

## Consolidated matrix

Legend: **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN** | **FACT** (pending hydrate)

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-01 | med | `Config` accepted any number of at least 0, floats included; the setting is a slice bound, a float raises `TypeError`, and `0` would silence every header search; the spec said neither that it is cut to an integer nor that `0` is refused | `global/scripts/mailbox:147` (rule before), `mail_local.py:509` (`int(...)` for `text_scan_max`) | HYDRATED (design D3 and D5, spec "Mistyped setting"; code: `MINIMUM`, `math.isfinite`, `int(...)`; tests `HeaderScanSetting`) | R-CFG |
| G-02 | low | Impact list omitted `mail_selftest.py` (fixtures, and the self-test counts them) | `tasks.md` 1.2; `mail_selftest.py:232` | HYDRATED (proposal Impact; fixtures in `list_messages()`, one self-test check added) | proposal |
| G-03 | med | `FolderIndex.header_filter` kept `cap=50000` as an argument default and sliced `rows[:cap]` itself, a second hidden bound under the stated one when `header_scan_max` is raised | `mail_index.py:272` (before) | HYDRATED (D3 step 3; the argument is removed; tests `test_the_old_cut_is_not_hidden_in_the_index_module`, `test_the_pass_has_no_bound_of_its_own_beyond_the_old_cut`) | R-SCAN |
| G-04 | low | The "deleted since indexing" scenario needs a folder with client status lines and `List-ID` fixtures in it | `mail_selftest.py` format A/B, `build_thunderbird` puts `Sent` in format A | HYDRATED (D7, task 1.2, test `test_a_message_flagged_deleted_since_indexing_stays_hidden`) | D7 |
| G-05 | low | `thread` and `show` build indexes too and print no build note | `mail_local.py:430` (`index()`), note emitted only in `search` | INFERENCE (decided: a search note, D4) | — |
| G-06 | — | Existing index files and a copy of `mailbox` from before the change writing the same cache | no schema or meta change in this scope | ALREADY | — |
| G-07 | — | The real gain of the new order is unknown (it depends on whether the real folders carry status lines) | D1 INFERENCE; task 7.4 measures | UNKNOWN | task 7.4 |
| G-08 | med | Found while applying: a de-duplication before the cut (first design of D3 step 2) would drop the second copy of a message stored twice when the first copy is flagged deleted, which `live` keeps today | `mail_index.py` `live()` (`flagged` rows are skipped before `seen` is updated) | HYDRATED (D3 step 2 states "no de-duplication before the cut"; code does none; test `test_a_message_stored_twice_is_listed_once`; the semantics tests also pass on the code before the change) | R-SCAN |
| G-09 | low | Found while applying: the build note counted "indexed messages" but a message stored twice is two rows, so the note said 6 for a folder that lists 5 | `BuildAnnouncement` test against the fixture inbox | HYDRATED (spec "A build is announced" and D4 say "the number of messages the index holds, a duplicate counts twice") | R-BUILD |
| G-10 | — | A header index, `index_headers`, backfill, `--with-header` | scope decision of P2 | REJECTED (deferred with triggers in `design.md`) | — |
| G-11 | med | Found in P4 (independent review): `math.isfinite(value)` raises `OverflowError` for an integer too large for a float (a JSON integer of 400 digits), so `Config()` died with a traceback for `header_scan_max` and, a regression, for every other numeric default (`limit`, `text_scan_max`, ...), which accepted such a value before the change | `Config.__init__` in `global/scripts/mailbox`; reproduced in-process with `defaults: {limit: 10**400}` | HYDRATED (spec "Mistyped setting" and design D5 say a number a float cannot hold is mistyped; code: `_usable_number`; test `test_a_number_beyond_the_range_of_a_float_is_mistyped_not_a_crash`, which raised `OverflowError` without the fix) | R-CFG |
| G-12 | low | Found in P4: `header_filter` counted a row as scanned before reading it, so when a read fails the note says `checked the newest K` with K one too high, and the design claim "the note stays true when the pass stops early" had no test | `mail_index.py` `header_filter` (`scanned += 1` before `fh.read`); no test stops the pass early | HYDRATED (design D3 step 4: a row counts after its header was read; code in `header_filter`; test `test_a_read_that_fails_stops_the_pass_and_the_note_counts_only_what_was_read`, which reported 3 instead of 2 without the fix) | R-SCAN |
| G-13 | med | Found in P4: the claim "the match is the one the backend gave before" was false for a message stored twice in one folder with the header on the older copy only: `live` used to de-duplicate (newest copy) before the header pass, so the message was hidden; now every copy is tested | `mail_index.py` `live()` (dedupe by `idh`, first row kept); reproduced by running `test_a_copy_with_the_header_is_listed_even_when_a_newer_copy_of_the_same_message_has_none` against `HEAD`'s product files: it fails there, passes now | HYDRATED (spec scenario "A message stored twice" and the stated difference in the requirement; design D6 second ordering difference; test as named) | R-SCAN |

## Useful casuistics (documentation, not new requirements)

- A header filter over a folder whose messages have no client status lines (the newer client format) has nothing for `live`
  to read; the saving of the new order is then only the in-memory part.
- A message stored twice uses two places of the cut, and a message flagged deleted since indexing uses one.
- A first search of a folder with no index is the expensive one; the note explains it and does not remove the cost.
- `thread --json` through the `imap` fallback to `local` goes through the same item builder, so it carries `message_id`.

## Out of v1 (does not block APPLY)

- Real-store timings (task 7.4), the consumer's seen-list run (7.5) and the full discovery in CI (7.6): `[prod-verify]`.
- Bounding the status pass for searches that are not a header filter (run A of the proposal).
- The deferred header index and `--with-header` (`design.md`, "Deferred", with their triggers).

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (spec OK; code and tests applied in this round) | 9 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 4 |

## Verification (this document)

See the "Verified" and "Not verified" lists in `READY-TO-APPLY.md`; the numbers there are from the final tree.

Gaps pending (mejora + apply): 0
