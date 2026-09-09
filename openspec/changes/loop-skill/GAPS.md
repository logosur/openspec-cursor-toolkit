# GAPS — loop-skill (honest review)

> **Date:** 2026-09-08
> **Mode:** A (change-id)
> **Real status:** post-apply review of the shipped `/run-spec` files

## Methodology

| Iter | Focus | Honest result |
|------|-------|---------------|
| **1** | Shipped files vs spec (`grep` on the five artefacts + 4 READMEs) | 3 FACT gaps (G-01…G-03), 1 out-of-v1, 1 already-covered |
| **2** | Post-apply: ran the shipped gate against this change's own `GAPS.md` | 1 FACT gap (G-06) — the gate regex missed the bold form the gap-analysis template writes |
| **3** | STOP — remaining candidates are documentation-only or already declared out of scope | early stop |

## Consolidated matrix

Legend: **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN**

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-01 | med | `README.md` states the repo does **not** include a product `openspec/` tree with active changes, but `openspec/changes/loop-skill/` now exists | `README.md:7`; `ls openspec/changes/loop-skill` → exists | HYDRATED | task 4.5 |
| G-02 | low | Versioning decision for the toolkit's own `openspec/changes/` is unstated; `.gitignore:28` keeps `# openspec/changes/` commented out (so it **is** versioned) by accident rather than by decision | `.gitignore:28` | HYDRATED | task 4.5 |
| G-03 | med | The loop's phases call `openspec status/validate` through the delegated skills, but nothing states the target project must have the OpenSpec CLI; a project without it fails P2 with an opaque error instead of a clear blocker | `grep -c 'openspec status\|openspec validate' .claude/skills/run-spec/SKILL.md` → 0 | HYDRATED | REQ-RS-SAFETY-01 (new scenario), task 1.14 |
| G-06 | **high** | The gate regex `^Gaps pending …$` did not match the **bold** form (`**Gaps pending (mejora + apply): 0**`) that the gap-analysis skill writes in `## Pending count`, so a real `GAPS.md` evaluated as `UNKNOWN` → `FAIL` forever | Ran the shipped gate on this change's own `GAPS.md`: `gaps_pending=<empty>` before the fix, `0` after | HYDRATED + FIXED | REQ-RS-GATE-01 (regex now tolerates `**`, new scenario) |
| G-04 | low | `/run-spec` is not registered in the `exporta-spec` bundle store, so it will not propagate to consumer projects yet | `grep run-spec .claude/commands/exporta-spec.md` → 0 hits | REJECTED (out of v1) | proposal § Impact declares propagation a follow-up |
| G-06 | med | `VERIFY.md` still claimed the invocation was a deploy order and reported the pre-change counts (16 REQ / 41 SC / 28 unchecked tasks) | `VERIFY.md:29`, `:12`, `:13` vs `grep -c` on the shipped spec (17 / 51 / 35) | HYDRATED | rewritten post-apply |
| G-07 | low | `READY-TO-APPLY.md` still read as pre-apply (verdict READY, next step `/aplica-tarea`, old D8 wording) | `READY-TO-APPLY.md:24`, `:20` | HYDRATED | rewritten post-apply |
| G-08 | low | `design.md` Open Questions still listed `"invocation = deploy order"` as a closed decision, contradicting the rewritten D8 | `design.md:106` | HYDRATED | rewritten post-apply |
| G-05 | — | New Cursor `.mdc` rule not registered in a rules index | `ls .cursor/rules/ \| grep index` → none in this repo | ALREADY | n/a — no rules index here |

## Out of v1 (does not block)

- Propagating `/run-spec` to consumer repos via `/exporta-spec` (G-04). Do it once the toolkit version is exercised in a real project (tasks 5.6 / 5.7).

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (spec OK; `/aplica-tarea` only) | 0 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 2 |

**Gaps pending (mejora + apply): 0**

## Verification (this document)

- **Verified:** every FACT row carries a file:line or a command output from this session. G-01…G-03 hydrated into `tasks.md` (1.14, 4.5) and implemented in this run. G-06 was found by executing the shipped gate against this very file, then fixed in both skills, the Cursor rule, the template and REQ-RS-GATE-01; re-run gives `gaps_pending=0`, and the unbolded form still matches.
- **Not verified:** behaviour of the loop in a live project (tasks 5.6 / 5.7 remain open). No REQ-RS-* scenario has been observed at runtime.
