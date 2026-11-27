# READY TO APPLY — external-access

> **Date:** 2026-11-27

## Verdict

**READY TO APPLY, and applied in this branch.** Two specs (22 requirements, 81 scenarios), design (D1 to D13) and tasks are complete; `openspec validate external-access --strict` passes. Every task that can be checked on a development machine is ticked with its evidence in `tasks.md`; four tasks stay open because they need the installed copy, a store key or the pushed branch, not code, and each carries `[prod-verify]`: 6.3 (cold agent through the skill), 7.3 (installed copies), 7.4 (real store services), 7.6 (full test discovery green in CI on the pushed branch; two local attempts were cut by the machine load without any failing test). `GAPS.md` ends at `Gaps pending (mejora + apply): 0`.

## What was applied

1. A shared access library (`global/scripts/lib/access/`), the `mailbox` and `stores` commands with their contracts and shipped config, the module `access` and the skill `cuentas-externas` (tasks 1 to 6).
2. Review round 1 (task group 8): privacy check at zero, bounded and fallback-safe `imap` thread lookup, doctor and robustness fixes.
3. Review round 2 (P3), from the first run against a live server: the server refused one search joining nine or more `OR` alternatives, so every `thread` fell back to `local` (gap G-13). Fixed with searches of at most four alternatives, a regression test, a spec scenario and design text.
4. Review round 3 (P4, confirm review in a fresh context): the section below was corrected (the full discovery was never run to completion locally); a request that carries credentials no longer follows a redirect, because `urllib` would forward the `Authorization` header to the new host (G-15); a mistyped account setting (`imap.port`, `local.folders`) is a one-line usage error instead of a traceback (G-16); the `folders` bound and the scan caps got scenarios and a test (G-17). Task group 9.

## Verified on this machine

Validator tests, validator, privacy tests and checks (staged files, commit message, pull-request text), the three piece test modules, `examples/override-full/try.sh`, and the real mailbox with both backends (same query through `imap` and `local`, a wrong account name, no secret in any output, a thread over `imap` on a server with more than 200 folders, the sent role). Details and numbers: tasks 6.1, 7.1, 7.2, 7.5.

## Not verified here (needs the installed copy or a key)

- 7.6: the full test discovery (`python3 -m unittest discover -s scripts/toolkit/tests -t .`) was **not** run to completion on this machine: two local attempts were cut by time on an overloaded machine without printing a failure, so they count as no evidence. The repository's rule makes it a CI gate on every push; it has to be green in CI on the pushed branch before integration.
- 6.3: an agent started elsewhere reaches an answer through the skill.
- 7.3: both `self-test` and both `doctor` from the installed copies.
- 7.4: `stores doctor --live` and one read per provider against the real services (the two providers are proven against simulated services only).

## Decisions locked (design.md)

One module with two pieces and one skill (D1) · entry scripts own the commands, a small package owns the backends (D2) · backend order and the connector as a printed call (D3, D7) · the local store is resolved, never configured (D4) · index and date-window rules (D5) · `imap` read-only with a cool-down after a refused login, bounded thread lookups with a local fallback (D6) · store authentication through `openssl`, no third-party library (D8) · what the store commands print with nothing connected (D9) · no token is lent (D10) · contract probes hold on any machine configuration (D12).

## Next step

Publication and install belong to the orchestrator and the supervisor: commit, push, install on one machine, then the three `[prod-verify]` tasks.
