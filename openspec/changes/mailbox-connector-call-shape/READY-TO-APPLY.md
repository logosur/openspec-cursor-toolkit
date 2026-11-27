# READY TO APPLY — mailbox-connector-call-shape

> **Date:** 2026-11-27 (phase P1 of `run-spec`, preparation only; nothing implemented, no product file edited).

## Update after the review and apply (repasa-spec, 2026-11-27)

Applied in this worktree: product code, tests and skill wording are done and checked (`tasks.md` has an evidence line per ticked task). Remaining unchecked: 9.6 (full discovery in CI) and 10.1 (live connector, after install), both tagged `[prod-verify]`. Review gaps G-16 to G-22 are closed (see `GAPS.md`).

## Verdict

**READY TO APPLY** pending the independent review (`repasa-spec`). The spec (two capabilities: `mailbox-connector-calls`, 12
requirements and 45 scenarios, all ADDED; `mailbox-search-results`, 1 MODIFIED requirement with its 3 scenarios), the design
(D1 to D11) and the tasks (groups 1 to 10) are complete, and `openspec validate mailbox-connector-call-shape --strict` passes.
`GAPS.md` ends at `Gaps pending (mejora + apply): 0`; two UNKNOWNs (what the connector returns for the `MINIMAL` and
`METADATA_ONLY` read formats; whether a live session continues with `pageToken`) are recorded, and neither blocks the code.

## Decisions taken in this phase (design)

1. New capability with ADDED requirements, because `mailbox-access` has no baseline; the one permanent requirement that says
   "Connector accounts SHALL behave as before" is restated (MODIFIED).
2. The cap notice is a top-level `paging` object, always present, never inside `arguments`.
3. `show` and `thread` exit 10 already; this change pins that with a test and edits no code for it.
4. Invalid connector settings make the account unusable (exit 2), they do not fall back silently.
5. `MINIMAL` is not offered as a flag; `show --headers` and `--body-chars` are not a headers-only read, and the connector's
   behaviour for `MINIMAL` and `METADATA_ONLY` on a read is unmeasured. Both values are accepted as a configured format.
6. `folders`, `save` and other connector kinds keep their documents.

## Not verified

Everything about product behaviour: no code was run. The skill's before and after character counts in design D10 were measured
on the current file and on the candidate text (1 862 to 1 861 for the body); task 7.1 recounts after the edit.

## Open tasks

Tasks 9.6 (full discovery green in CI on the pushed branch) and 10.1 (supervisor, after install, against the live connector) are
tagged `[prod-verify]` on their first line and stay unchecked here.
