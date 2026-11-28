# VERIFY — mailbox-header-index (preparation, phase P1)

> Verifies the specification only. No product code was written or changed.

## Verdict

**READY TO APPLY.** To be reviewed by phase P2 (`repasa-spec`); its review is `GAPS.md`.

## Evidence map

| Claim | Source |
|-------|--------|
| The index keeps no header value; a header filter reads each candidate | `global/scripts/lib/access/mail_index.py` (`SCHEMA`, `select`, `header_filter`), `mail_local.py` (`LocalBackend.search`) |
| Cut and note live in the caller | `mail_local.py` (`LocalBackend.search`) |
| Incremental refresh, version check, delete statements | `mail_index.py` (`refresh`, `_scan`) |
| Row id reuse, trigger on an unqualified delete, `instr` with an empty needle and a NUL, unencodable and raising decodes | run in memory against the local SQLite and `mail_message.decode_words`, synthetic strings |
| A list setting would be discarded by the current loop | `global/scripts/mailbox` (`Config.__init__`, `_usable_number`) |
| Match semantics shared with `imap` | `mail_imap.py` (`_match`) |
| Constraints of existing tests on the new code | `scripts/toolkit/tests/pieces/test_mailbox.py` (`HeaderScanSetting`, `HeaderFilterBase`, `ReadOnlyByConstruction`) |

## Traceability

| Requirement | Design | Tasks |
|-------------|--------|-------|
| R-SCAN (modified) | D5, D7 | 3.1 |
| R-IDX | D2, D3, D5 | 3.1 |
| R-EQ | D5, D7, D9 | 1.2, 2.4, 3.2 |
| R-INC | D3, D4 | 2.1, 2.2, 2.5, 3.2 |
| R-OLD | D4, D5 | 2.3, 2.5, 3.1 |
| R-PROG | D6 | 4.1, 4.2 |
| R-CFG | D8 | 1.1, 5.1 |
| R-DEC | D10 | 2.0, 3.2 |
| R-CONC | D5, D11 | 2.5, 3.3 |

## Not verified

- No test of the change exists yet; every behaviour in the delta is to be proven by its task.
- Wall time of a completion or of a warm search (UNKNOWN; needs the installed copy; not a task of this change).
