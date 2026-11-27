# READY TO APPLY — supervisor-exit-code-probes

> **Date:** 2026-11-27 (phase P1 of `run-spec`, preparation only; nothing implemented, no product file edited).

## Verdict

**READY TO APPLY**, and applied in the independent review (`repasa-spec`, round 1; see «Applied» below). The proposal, the design (D1 to D6), the spec delta
(capability `supervisor-lock-exit-codes`: 4 ADDED requirements, 14 scenarios) and the tasks (groups 1 to 4) are complete;
`GAPS.md` ends at `Gaps pending (mejora + apply): 0`; `openspec validate supervisor-exit-code-probes --strict` exits 0.

## The premise was corrected

The request said exit codes 3, 4, 6, 7, 8 and 9 of `supervisor-lock` have no self-test probe. FACT: each of them already has
at least one check (design D2 names them). The change is re-scoped to what is actually missing:

1. three exit sites with no check: `cloud` with no cloud provider (3), `cloud-archive`/`cloud-send` with unreadable cloud rows
   (3), and a beat refused for both the skill and the pause (8);
2. one missing "state unchanged" assertion: the refused `acquire` on a fresh lock (3);
3. mutation evidence for all 14 exit sites, which does not exist for any of them today.

The "Done when" of the request still holds as written: the self-test has probes for those codes and passes, and each probe
is shown to fail when its code path changes (recorded in `evidence/mutations.md` during apply).

## Decisions taken in this phase

1. Probes and mutations are counted per exit **site**, not per code (design D2), because codes 3, 6, 7 and 8 have several.
2. Existing checks are kept and never loosened; new checks sit next to the existing ones for the same site (design D3, D4).
3. Mutations run preferably on a throw-away copy of `global/scripts/`, so the worktree is never left dirty (design D5).
4. The fast contract probes (`global/contracts/supervisor-lock.yaml`) are out of scope; the private text of the
   `supervisa-sesiones` skill is not touched (proposal Non-goals).

## Baseline (corrected in `repasa-spec`)

The preparation phase ran `supervisor-lock self-test` directly under the real `HOME` and saw 9 `FAIL`. That is not the gate.
FACT: run the way CI runs it, through the piece test in a temporary `HOME`, the unmodified tree is green (exit 0, about
408 s). Design D6 and tasks 1.1 and 4.1 now use that piece test as the local gate.

## Applied (`repasa-spec`, round 1)

The six checks of design D3 are in `selftest.py`, the piece-test floors are 564/563, and `evidence/mutations.md` records the
14 site mutations (all turned their checks red, none turned anything else red). The final tree passes the local gate (piece
test module, 82 tests) and its self-test prints 652 `ok` and `ok: 0 failed`. Nothing is committed.
