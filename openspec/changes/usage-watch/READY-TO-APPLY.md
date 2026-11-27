# READY TO APPLY — usage-watch (`/run-spec`, phase P2)

> **Date:** 2026-11-27

## Verdict

**READY TO APPLY** — the twelve gaps of `GAPS.md` are hydrated into `design.md`, both spec deltas and `tasks.md`; `openspec validate usage-watch --strict` exits 0.

## Gates

| Gate | Result |
|------|--------|
| `openspec validate usage-watch --strict` | exit 0 |
| Artefacts | proposal · design · specs (2) · tasks · GAPS · VERIFY (preparation) |
| `GAPS.md` | G-01 … G-12 hydrated |

## Decisions locked in this phase

- **Authorised state (G-01, D7):** only the queue decides. `decide` takes no outcome argument; an answer whose `answered_by` is empty, the asker or the usage role holder is untrusted; `apply` re-reads the queue verdict before acting, so a hand-edited store is refused.
- **Both kinds gated mechanically (G-02, D7, D14):** a `config` change is written only by an authorised `apply`; a session's model or effort is changed by the app's tool, which the `usage-apply-gate` hook lets the role use only against a one-use ticket that an authorised `apply` writes.
- **Module direction (G-03, D1):** `depends` stays `usage → core`. Part A reads supervision's data files as JSON and cites nothing outside `core`; Part B's script calls are declared in `project_provided` on both sides; the gate hook belongs to `usage` and has a contract. Checked with the validator in a scratch copy before any file landed.

## Scope of the next apply

Part A (tasks 1 to 5) in this phase, stopping at its gate 5.4. Part B (6 to 11) in the next phase.
