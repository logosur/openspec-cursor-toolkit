# READY TO APPLY — mailbox-search-gaps

> **Date:** 2026-11-27 (reduced scope, phase P2 of `run-spec`)

## Verdict

**READY TO APPLY, and applied in this branch.** The reduced spec (6 requirements, 25 scenarios), the design (D1 to D7 plus
the "Deferred" section) and the tasks are complete; `openspec validate mailbox-search-gaps --strict` passes. Every task
that can be checked on a development machine is ticked with its evidence in `tasks.md`; three stay open because they need
the installed copy, a live account or CI, not code, and each carries `[prod-verify]`: 7.4 (the timings (A) to (D) on the
real local store after the install), 7.5 (the consumer's seen list: results already seen need no `show`) and 7.6 (the full
test discovery green in CI on the pushed branch). `GAPS.md` ends at `Gaps pending (mejora + apply): 0`.

## What changed in scope (P2)

Measured by the orchestrator on the installed copy and the real local store, the header filter on `local` returns the right
answer in a few to about twenty seconds at normal load; the "did not finish in two minutes" was seen once on a heavily loaded machine and is not
reproduced. The first design (a header index with backfill and in-place upgrade, and `--with-header`) was therefore moved
to `design.md`, "Deferred", with a trigger for each, and removed from the spec and the tasks.

## What was applied

1. **Identifier:** `Item.message_id` (normalised `Message-ID`, `null` when absent) in every `search --json` item and every
   `thread --json` item, on `imap` and on `local`, with no extra command and no file read.
2. **Header filter on `local`:** the header is read before the status pass, on the newest `header_scan_max` candidates per
   folder (new setting, default 50 000, validated, in `--help`); `live` runs on the matches only; a cut is stated in a note
   (text and `--json` `notes`); `header_filter` has no cap of its own.
3. **Build announcement:** a first build or a rebuild after compaction adds a note with the message count.
4. `--help`, two contract probes (`message_id`, `header_scan_max`), the shipped config default, and one self-test check.

Gaps G-01 to G-04 (pre-apply) were hydrated; G-08 and G-09 were found and fixed while applying; G-11, G-12 and G-13 were
found and fixed by the independent confirm review (P4): a number a float cannot hold in the config raised `OverflowError`
(G-11, a traceback, also for the old numeric keys), the note counted a row whose read failed (G-12), and a message stored
twice in a folder with the header on the older copy only used to be hidden and is now listed, a stated difference (G-13,
design D6). See `GAPS.md`.

## Verified on this machine

- `python3 -m unittest scripts.toolkit.tests.pieces.test_mailbox scripts.toolkit.tests.pieces.test_access_helpers`: 233 tests
  OK (182 before the change).
- Compatibility: the existing output of `search` and `thread` on both backends is byte-identical (text) or identical after
  removing `message_id` (JSON), and the command stream sent to the fake IMAP server is the one recorded before the change; the
  baseline tests passed on the unmodified code before any product edit.
- The header-filter matches are the ones of the code before the change, with one stated exception (G-13, design D6): the
  semantics tests were run against the product files of `HEAD`; 9 of the 12 pass there and the 3 that fail are the ones for
  what this change adds (the cut note, `message_id`, and a message stored twice with the header on the older copy only).
- `python3 -m unittest scripts/test_validate_toolkit.py` 59 OK, `python3 scripts/validate-toolkit.py` 0 errors,
  `python3 -m unittest scripts/test_privacy_check.py` 22 OK, `bash examples/override-full/try.sh` every step passed,
  `openspec validate mailbox-search-gaps --strict` valid, `python3 scripts/privacy-check.py` and `--staged --require-private`
  0 findings.

## Not verified here

- 7.4: the real-store timings and whether the new order is faster there (design D1: the gain depends on whether the real
  folders carry client status lines, UNKNOWN). No claim of a gain is made.
- 7.5: the consumer's run with its seen list.
- 7.6: the full test discovery (`python3 -m unittest discover -s scripts/toolkit/tests -t .`) was not run in this phase by
  order; it is the CI gate on the pushed branch.

## Decisions locked (design.md)

Identifier form and nulls (D2) · header before the status pass, one stated cut, default never below 50 000, no
de-duplication before the cut (D3) · the build is announced, not bounded (D4) · one setting, `math.isfinite` for every numeric
default (D5) · the header index and `--with-header` deferred with triggers (Deferred 1 and 2).

## Next step

Publication and install belong to the orchestrator and the supervisor: commit, push, install on one machine, then the three
`[prod-verify]` tasks.
