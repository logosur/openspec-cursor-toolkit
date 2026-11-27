# Proposal — supervisor-exit-code-probes

> **Created by:** `/prepara-tarea supervisor-exit-code-probes` (phase P1 of `run-spec`), 2026-11-27.
> **Status:** APPLIED in `repasa-spec` (round 1); not committed.
> **Marks used below:** **FACT** (read in the code or measured), **INFERENCE**, **HYPOTHESIS**, **UNKNOWN**.

## Why

`supervisor-lock` answers with documented exit codes beyond 0, 1, 2 and 5: 3 (lock held, or the cloud state cannot be
read), 4 (lock stale), 6 (sessions of the project still open), 7 (documented work left), 8 (`beat --skill-seen` without a
load of the skill) and 9 (`beat --state paused` refused while the account has usage). Supervisors and hooks branch on these
codes, so a silent change of one of them changes what a supervisor does without any test going red.

The request that opened this change said those six codes "have no probe at all" in `supervisor-lock self-test`.

**Corrected premise (FACT, read in `global/scripts/lib/supervisor/selftest.py` and confirmed in the baseline run of task
1.1):** every one of the six codes is already asserted by at least one self-test check. What is missing is narrower:

1. Three exit **sites** that produce code 3 or 8 have no check at all (design D2: sites S3c, S3e and S8b).
2. No exit site has evidence that its check would fail if the code changed: nobody has run a mutation against them, so the
   existing checks are trusted, not proven.
3. The refused `acquire` on a fresh lock (code 3) asserts the exit code and the first word, but not that the lock file was
   left as it was. The stale case (code 4, check `acquire: stale lock left untouched`) and the refused `reclaim` (code 3,
   check `reclaim: wrong --from -> HELD, exit 3, untouched`) already pin it.

## Current behaviour

FACT. The exit sites, by code (full matrix with the condition and the existing check in `design.md` D2):

- **3:** `acquire` on a fresh lock of another session; `reclaim --from` naming a session that does not hold the lock;
  `cloud` when the cloud provider is absent (`CLOUD-UNAVAILABLE`) or the API cannot be read (`CLOUD-UNKNOWN`);
  `cloud-archive` and `cloud-send` when the cloud rows cannot be read (`util.die(…, 3)` in `cloud.cloud_owned_target`).
- **4:** `acquire` on a stale lock of another session.
- **6:** `open` with at least one open session; `release` with a busy live session and no `--force-close`; `release` with a
  session still open (not archived) and neither `--force-close` nor `--open-ok`.
- **7:** `backlog` with at least one change with unchecked tasks; `beat --phase guardia` refused by `backlog.guard_refusal`
  (an unanswered developer message, documented work, or a registry without the guard section).
- **8:** `beat --skill-seen` when the session's transcript shows no load of the skill after its newest update
  (`lint.skill_load_proof` verdict `not-loaded`); this also wins when the same beat is a refused pause.
- **9:** `beat --state paused` without `--third-party` while `providers.account_has_usage()` is true; the state stays.

Checks exist today for every site except `cloud` → `CLOUD-UNAVAILABLE` (S3c), `cloud-archive`/`cloud-send` with unreadable
rows (S3e), and the beat that is refused for both the skill and the pause (S8b).

## Expected behaviour

- `supervisor-lock self-test` has one check per exit site of codes 3, 4, 6, 7, 8 and 9 (adding the three missing sites).
- Where it is cheap and the code promises it, a check also asserts that the refused command left its state unchanged: the
  lock file of a refused `acquire` on a fresh lock (3), no archive or send logged by a refused `cloud-archive`/`cloud-send` (3), the lock
  state and `skill_seen` of the doubly refused beat (8).
- For every exit site a mutation was run once (in batches, on throw-away copies, design D5): the exit path was altered and
  the site's self-test checks went `FAIL`, while the worktree was never mutated. The evidence is recorded in
  `evidence/mutations.md` of this change.
- `supervisor-lock self-test` passes in the piece test's temporary `HOME` (the local gate, design D6), ending `ok: 0 failed`.

## What Changes

- `global/scripts/lib/supervisor/selftest.py`: new checks only (design D3). No existing check is removed or loosened.
- `scripts/toolkit/tests/pieces/test_supervisor_lock.py`: the floor of the number of `ok` lines (today 558 with the skill
  shipped, 557 without) is raised by the number of checks added, so a later removal is noticed.
- `openspec/changes/supervisor-exit-code-probes/evidence/mutations.md`: the mutation record.

No product code changes: every other file under `global/scripts/` stays byte-identical at the end (task 4.3).

## Non-goals

- **The private text of the `supervisa-sesiones` skill is not touched**: no edit to `global/skills/supervisa-sesiones/**`, to
  the installed copy, or to any private override text. The self-test lints the skill as today and nothing more.
- No new subcommand, no new hook, no new flag, no new exit code, and no behaviour change in `supervisor-lock` or its modules.
- No change to `global/contracts/supervisor-lock.yaml` (its fast probes stay as they are; the full self-test is what the
  toolkit suite runs).
- Exit codes 0, 1, 2 and 5 are out of scope.
- Nothing is installed and nothing runs outside a temporary `HOME` (the self-test sandboxes itself, design D1).

## Capabilities

- New: `supervisor-lock-exit-codes` (ADDED requirements only). No permanent spec under `openspec/specs/` covers
  `supervisor-lock` today (FACT: `openspec/specs/` lists six capabilities, none of them about the supervisor lock).

## Impact

- One implementer, Python only, inside the module `supervision`.
- Risk is limited to the test code; the main risk is a new check that is flaky or depends on the order of the existing
  sections (design D4).
