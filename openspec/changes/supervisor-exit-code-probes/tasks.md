# Tasks — supervisor-exit-code-probes

Requirement references (all in `specs/supervisor-lock-exit-codes/spec.md`): **R-SITE** every exit site has a check,
**R-STATE** a refused command leaves its state as it was, **R-MUT** each probe is shown to fail when its site changes,
**R-ONLY** tests only and the self-test stays green. Design decisions: `design.md` D1 to D6; sites S3a … S9a are those of D2.

One implementer. Every run of `supervisor-lock self-test` sandboxes itself in a temporary `HOME` (design D1); nothing is
installed and nothing under the real home is written. Full runs go one at a time; `heavy-job classify` says they are light (D6).
Do not commit.

## 1. Baseline

- [x] 1.1 Record the starting commit (`git rev-parse HEAD`) and the baseline of the local gate (design D6) on the unmodified
  tree: `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock.SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home`
  (exit code, wall time), plus one run of the unmodified tree's self-test with the piece test's environment to count its `ok`
  lines. Record both in `evidence/mutations.md`. Check: the unittest exits 0 (R-ONLY); the count run gives the `ok` count,
  and any `FAIL` it prints is recorded and compared with the other runs of the same check.
- [x] 1.2 Re-derive the exit-site list: grep the package `global/scripts/lib/supervisor/` (excluding `selftest.py`) for
  `return [3-9]\b`, `SKILL_NOT_LOADED`, `PAUSE_REFUSED`, `sys.exit(` and `util.die(`, and confirm every hit with code 3, 4, 6, 7,
  8 or 9 is a row of design D2. Check: no unlisted site; if one appears, add it to D2, D3 and D5 before coding (R-SITE).
- [x] 1.3 Confirm that each existing check named in D2 is printed as `ok` in the baseline output of 1.1 (a check that exists
  but does not run would make its site a gap). Check: every D2 label of a "probed" row appears in the baseline as `ok`.

## 2. New checks (D3) — `global/scripts/lib/supervisor/selftest.py` only

- [x] 2.1 N1 (S3a): assert the lock is unchanged by the refused fresh `acquire`, label `acquire: other session, fresh -> lock
  left untouched`. Check: self-test green; the new label prints `ok` (R-STATE).
- [x] 2.2 N2 (S3c): `cloud` and `cloud --json` with `SUPERVISOR_CLOUD_TESTS` set to a missing file inside the test temp dir;
  labels as in D3. Check: self-test green; both labels `ok` (R-SITE).
- [x] 2.3 N3 (S3e): first confirm the cloud lock is still held by its owner where the `CLOUD-UNKNOWN` check runs (take it again
  with the existing `crun('acquire', …)` if not); then `cloud-archive` and `cloud-send` exit 3 with `CLOUD-UNKNOWN` on stderr,
  no `ARCHIVED`/`SENT` on stdout, and no new line in the cloud actions log; labels as in D3. Check: self-test green; both labels
  `ok`; the checks after it are unchanged in outcome (R-SITE, R-STATE).
- [x] 2.4 N4 (S8b): the doubly refused beat with forced usage exits 8 with both reasons; state `running`, no `pause_cause`,
  `skill_seen` unset; label as in D3. Check: self-test green; label `ok` (R-SITE, R-STATE).
- [x] 2.5 Raise both floors in `scripts/toolkit/tests/pieces/test_supervisor_lock.py` (`558`/`557`) by the number of checks
  added in 2.1–2.4 (6 if D3 is followed as written). Check: `python3 -m unittest
  scripts.toolkit.tests.pieces.test_supervisor_lock` passes (R-ONLY, scenario "Piece test floor follows the new checks").

## 3. Mutation checks (D5) — one per site, evidence in `evidence/mutations.md`

Each task: the site's D5 mutation is applied in its batch (design D5: three throw-away copies of `global/`, the expected
`FAIL` labels written before the run, one run per batch, one at a time). Check for each: the batch exits non-zero, at least one
`FAIL` label is an expected label of that site, no `FAIL` of the batch is unexpected, `ok + FAIL` of the batch equals the
final green count, and `git diff --stat <start> -- global/` lists only `selftest.py` afterwards (R-MUT).

- [x] 3.1 S3a — acquire on a fresh lock of another session.
- [x] 3.2 S3b — reclaim with a wrong `--from`.
- [x] 3.3 S3c — cloud with no provider.
- [x] 3.4 S3d — cloud with an unreadable API.
- [x] 3.5 S3e — cloud-archive / cloud-send with unreadable rows.
- [x] 3.6 S4a — acquire on a stale lock of another session.
- [x] 3.7 S6a — open with open sessions.
- [x] 3.8 S6b — release with a busy session.
- [x] 3.9 S6c — release with a session still open.
- [x] 3.10 S7a — backlog with work.
- [x] 3.11 S7b — beat to guard refused.
- [x] 3.12 S8a — skill-seen refused.
- [x] 3.13 S8b — skill-seen and pause refused together (8 wins).
- [x] 3.14 S9a — paused beat refused while the account has usage.
- [x] 3.15 Any site whose mutation showed no `FAIL`: strengthen its check (never weaken the mutation), rerun that mutation,
  and update the row. Check: every row of `evidence/mutations.md` ends in "FAIL seen" and "reverted clean" (R-MUT).

## 4. Final gates

- [x] 4.1 The local gate on the final tree (design D6):
  `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock.SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home`
  (inside the module run of 4.2), plus one run of the final tree's self-test with the piece test's environment to record the `ok` count.
  Check: exit 0, no `FAIL`, last line `ok: 0 failed`, every D2/D3 label `ok`, `ok` count = the baseline's check total (`ok` + `FAIL`) + 6 (R-ONLY).
- [x] 4.2 `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock`. Check: passes (R-ONLY).
- [x] 4.3 `git diff --stat <start commit> -- global/` lists only `global/scripts/lib/supervisor/selftest.py`, and nothing under
  `global/skills/supervisa-sesiones/` changed. Check: as stated (R-ONLY, proposal Non-goals).
- [x] 4.4 `python3 scripts/privacy-check.py` (whole tree, default mode) and `openspec validate supervisor-exit-code-probes
  --strict`. Check: both exit 0. The pre-commit form (`--staged --require-private`, and `--message <file>`) belongs to the
  publish phase, not to this task.
- [x] 4.5 Catalog gates the repo requires before closing (`python3 -m unittest scripts/test_validate_toolkit.py && python3
  scripts/validate-toolkit.py`). Check: both exit 0.
- [x] 4.6 The installer and `global/` suite the repo requires before closing a change of `global/` (`python3 -m unittest
  discover -s scripts/toolkit/tests -t . -v`), on the final tree (`heavy-job classify`: light). It contains the gate of 4.1
  and 4.2. Check: exit 0 (R-ONLY).
