# READY TO APPLY — loop-skill (`/run-spec`)

> **Date:** 2026-09-08 · updated 2026-09-09 (post-apply)

## Verdict

**APPLIED** — proposal, design, spec (17 REQ / 51 scenarios) and tasks (35, of which 33 done) are complete; `openspec validate --strict` and `openspec status` pass in a sandbox copy (this toolkit repo has no `openspec init`, see VERIFY.md).

## Gates

| Gate | Result |
|------|--------|
| `openspec validate loop-skill` (sandbox) | exit 0 — valid, strict mode 0 issues |
| `openspec status --change loop-skill --json` (sandbox) → `isComplete` | `true` |
| Artefacts | proposal ✅ · design ✅ · specs ✅ · tasks ✅ · VERIFY ✅ |
| `GAPS.md` | present — G-01…G-03 hydrated and fixed, G-06…G-08 fixed post-apply; `Gaps pending (mejora + apply): 0` |

## Scope of the next apply

Done: §1 → §4 plus verification 5.1–5.5, 5.8. Open: **5.6** (end-to-end dry-run with `--no-deploy` in a real consumer project) and **5.7** (`[prod-verify]` — approve the deploy gate on a real project).

## Decisions locked (design.md)

D1 delegate-not-duplicate · D2 `RUN-LOOP.md` state in change folder · D3 file-only gate · D4 `[prod-verify]` marker · D5 `max_iter` 3 + convergence guard · D6 fresh confirm reviewer · D7 tests/regression fix-forward, no weakening · D8 publish automatic on the current branch, deploy always gated by a dialog, `--no-deploy` skips the gate · D9 inline default, paced via `/loop` · D10 token contract · D11 verdict line (5 verdicts, incl. `AWAITING DEPLOY APPROVAL`).

## Next step

Exercise `/run-spec` on a real consumer project (tasks 5.6 then 5.7). Nothing is committed in this repo — `/finaliza-spec loop-skill` will refuse while 5.6/5.7 are unchecked.
