# Design — supervisor-exit-code-probes

Marks: **FACT** (read in the code or measured), **INFERENCE**, **HYPOTHESIS**, **UNKNOWN**. Paths are relative to the
repository root. Self-test checks are named by their exact `check()` label (stable), not by line number (lines move).

## D1. Where the probes run (sandbox)

FACT (`global/scripts/lib/supervisor/selftest.py`, `enter_sandbox` and `cmd_self_test`): `supervisor-lock self-test` without
`SUPERVISOR_SELFTEST_SANDBOX` re-runs itself in a child whose `HOME`, `TMPDIR`, `XDG_*` and toolkit config dir all point
inside a fresh `mkdtemp` root, after scrubbing `SUPERVISOR_*`, `ASK_GATE*`, `CLOUD_TESTS_*`, `GIT_*` and similar variables; the
child refuses to run when a path it would use lies outside that root (`SANDBOX REFUSED`, exit 2), and the root is removed at
the end. Inside, every command runs against `SUPERVISOR_LOCK_HOME`, `SUPERVISOR_SESSIONS_DIR` and the app glob under a second
temp dir, with fake notify, nudge, heavy-job and handoff helpers. New checks reuse the existing helpers (`run`, `crun`,
`urun`/`st_env`, `pf_beat`, `load`, `save`) and therefore inherit this sandbox. No new environment variable is needed.

## D2. Exit-site matrix (the source of truth for the probes and the mutations)

One row per exit **site** (a code can have several sites). "Existing check" is the exact label in `selftest.py` at the time
of writing; "—" marks a site with no check.

| Site | Code | Command and condition (FACT, where) | Existing check | Status |
|------|-----:|--------------------------------------|----------------|--------|
| S3a | 3 | `acquire`, lock held by another session and fresh → `report_held` (`lock.py` `cmd_acquire`) | `acquire: other session, fresh -> HELD, exit 3`; `ttl: paused lock 1 h old is still fresh (3)`; `concurrency: 12 acquires -> one exit 0, eleven exit 3` | probed; lock-unchanged not asserted |
| S3b | 3 | `reclaim --from X`, the lock's owner is not X → `report_held(always_held=True)`, 3 even when stale (`cmd_reclaim`) | `reclaim: wrong --from -> HELD, exit 3, untouched` | probed |
| S3c | 3 | `cloud`, provider absent → `cloud_rows` returns `UNAVAILABLE` → prints `CLOUD-UNAVAILABLE`, or `{"ok": false, "available": false}` with `--json` (`cloud.py` `cmd_cloud`) | — | **gap** |
| S3d | 3 | `cloud`, API unreadable → `CLOUD-UNKNOWN` (`cmd_cloud`) | `cloud: an unreadable API is CLOUD-UNKNOWN with exit 3, never «none»` | probed |
| S3e | 3 | `cloud-archive` / `cloud-send` by the owner, rows unreadable → `util.die(…, 3)` naming `CLOUD-UNAVAILABLE` or `CLOUD-UNKNOWN` (`cloud.py` `cloud_owned_target`) | — | **gap** |
| S4a | 4 | `acquire`, lock held by another session and stale → `report_held` (`cmd_acquire`) | `acquire: other session, stale -> STALE, exit 4`; `acquire: stale lock left untouched`; `ttl: paused lock 3 h old is stale (4)`; `ttl: running lock 1 h old is stale (4)` | probed |
| S6a | 6 | `open` with at least one open session (`lock.py` `cmd_open`) | `open: no lock -> nobody is excluded, exit 6 and the count line`; `open: owner and questions session are not counted, exit 6, …` | probed |
| S6b | 6 | `release` by the owner, a live busy session other than the owner and its questions session, no `--force-close` (`cmd_release`) | `release: other live session busy -> exit 6 with OPEN WORK, lock kept, nothing recorded`; `release: the questions session plus another busy session -> exit 6, …`; `workspace: release refuses (exit 6, OPEN WORK) while a session of the workspace is busy` | probed |
| S6c | 6 | `release` by the owner, a session still open (not archived), neither `--force-close` nor `--open-ok` (`cmd_release`) | `release: a session nobody opened (not archived) is still open -> exit 6, …`; `workspace: release refuses (exit 6, OPEN lines) while idle sessions of the workspace are still open` | probed |
| S7a | 7 | `backlog` with at least one change with unchecked tasks (`backlog.py` `cmd_backlog`) | `backlog: each change with unchecked tasks is WORK (done and archived ones are not), exit 7`; `backlog: a park is void once the open tasks of the change are not the ones it was written for` | probed |
| S7b | 7 | `beat --phase guardia…` and `backlog.guard_refusal` non-empty → heartbeat written, phase not changed (`lock.py` `cmd_beat`) | `beat --phase guardia: refused (7) while the project has documented work left; the phase does not change`; `beat --phase guardia: refused while the registry does not explain the guard`; `replay: \`beat --phase guardia\` is refused while the developer's message has no outcome` | probed |
| S8a | 8 | `beat --skill-seen`, skill file present, `lint.skill_load_proof` verdict `not-loaded` → `SKILL_NOT_LOADED` (`cmd_beat`) | `skill-seen proof: a beat with no Skill call in the transcript is refused (exit 8), skill_seen stays unset` and the other `refused(...)` checks of section 9b (seven more, among them `skill-seen proof: run by another session, the beat reads the owner's transcript, not the caller's`) | probed |
| S8b | 8 | the same beat also carries `--state paused` without `--third-party` while the account has usage → returns 8 (not 9), prints both refusals, the state stays (`cmd_beat`, the `if refused_pause` inside the skill branch) | — | **gap** |
| S9a | 9 | `beat --state paused` without `--third-party`, `account_has_usage()` true → `PAUSE_REFUSED`, state kept (`cmd_beat`) | `beat --state paused with usage and no --third-party: refused (exit 9), …, state kept`; `beat --state paused with usage on a limit pause: refused, …` | probed |

FACT (task 1.2, repeated in apply): these are all the sites of codes 3, 4, 6, 7, 8 and 9 reachable from the CLI. A grep of
the package (without `selftest.py`) for `return [3-9]`, `else [3-9]`, `SKILL_NOT_LOADED`, `PAUSE_REFUSED`, `sys.exit(` and
`die(` finds only these rows; every other `die` uses code 2 (or the default 2), `closing.py` returns 5, and `cli.py` passes
the subcommand's code through. The "Existing check" column lists every check that asserts the site's code (a grep of
`selftest.py` for `returncode == <n>`, `refused(` and `PAUSE_REFUSED`); the mutation record expects the labels that assert
the code (a "left untouched" check, such as `acquire: stale lock left untouched`, stays `ok` under a mutation of the code).

## D3. The new checks

All new checks are appended **next to the existing checks of the same site**, so they run with the fixtures already in place.
Labels are fixed here so the mutation record can name them.

- **N1 (S3a, lock unchanged).** Around the existing `acquire: other session, fresh -> HELD, exit 3`: read the lock before
  the refused `acquire`, compare after. Label: `acquire: other session, fresh -> lock left untouched`.
- **N2 (S3c).** With `SUPERVISOR_CLOUD_TESTS` set to a path inside the test temp dir that does not exist (explicit, rather
  than relying on the sandbox `HOME` having no `cloud-tests`), placed after N3 in section 30 and run on the cloud project
  (whether it holds a lock does not matter: `cmd_cloud` does not read the lock): `cloud --dir <repo>` exits 3 and stdout starts with
  `CLOUD-UNAVAILABLE`; `cloud --dir <repo> --json` exits 3 and prints `"ok": false` and `"available": false`. Labels:
  `cloud: no cloud provider -> CLOUD-UNAVAILABLE, exit 3, never «none»` and `cloud --json: no cloud provider -> available
  false, exit 3`.
- **N3 (S3e).** Right after `cloud: an unreadable API is CLOUD-UNKNOWN with exit 3, never «none»` (the API fake has just been
  removed, so rows are unreadable), the owner of the cloud lock runs `cloud-archive --target <an id the earlier checks still
  list> --reason x` and `cloud-send --target <id> --text x`. Each exits 3 with `CLOUD-UNKNOWN` on stderr, prints no
  `ARCHIVED`/`SENT`, and the cloud actions log (`<lock home>/cloud-actions.log`) gets no new line. Labels:
  `cloud-archive: unreadable cloud rows -> exit 3, nothing archived` and `cloud-send: unreadable cloud rows -> exit 3, nothing
  sent`. FACT (read in section 30): nothing releases the cloud lock between its `acquire` and the `CLOUD-UNKNOWN` check, so
  its owner still holds it; the check asserts it (reading the lock file, guarded so a missing file is a `FAIL`, not a crash).
- **N4 (S8b).** In the skill-seen section, with the `pf_beat` helper and an environment that forces usage
  (`st_env('yes')` or the same `SUPERVISOR_USAGE=yes` override it sets): a beat with a transcript that shows no load,
  `--state paused` and no `--third-party`. Expected: exit 8 (not 9), stderr has both `PAUSE REFUSED` and `SKILL SEEN REFUSED`,
  the lock's `state` is unchanged and has no `pause_cause`, and `skill_seen` stays unset. Label: `skill-seen proof: a beat
  refused for the skill and for the pause exits 8 with both reasons, state kept`.

Each new check asserts the exit code **and** one distinguishing token of the message, so a mutation that keeps the code but
changes the path (or the reverse) still fails.

## D4. Order and flakiness

- No new check sleeps or depends on wall-clock thresholds beyond what the reused fixtures already do.
- N3 runs where the API fake is already gone; it must not recreate it, or later checks that rely on its absence would change.
- N4 must restore what it changes (`forget()` already exists for `skill_seen`; the state is asserted unchanged, so nothing to
  restore).
- The piece test floor (`scripts/toolkit/tests/pieces/test_supervisor_lock.py`, `assertGreaterEqual(checks, 558 …/557)`) is
  raised by exactly the number of checks added (6 with D3 as written).

## D5. Mutation protocol (evidence that each check can fail)

For every site of D2 (14 sites), once, on the final code. FACT: the self-test cannot run a subset of its checks
(`cmd_self_test` is one function with no filter), and one full run takes about 7 minutes, so the mutations are **batched**:

1. Copy `global/` of the final tree into three throw-away directories in the session's scratch directory, one per batch.
   The worktree is never mutated, so it never needs a revert.
2. Apply the mutations of one batch (below) to its copy. Sites that share a check or the same statement go to different
   batches: S3a/S4a (`report_held`), S3c/S3d (`cmd_cloud`), S6b/S6c (`cmd_release`), S8a/S8b (the same `return`).
   - batch 1: S3a, S3c, S6a, S7a, S8a;
   - batch 2: S3b, S3d, S6b, S7b, S8b;
   - batch 3: S4a, S3e, S6c, S9a.
3. Before reading any result, write down the expected `FAIL` labels of each batch: the D2 "Existing check" labels and the
   D3 labels of its sites.
4. Run the copy's `supervisor-lock self-test` with the environment of the piece test (`test_supervisor_lock.py`, `Base`:
   throwaway `HOME`, own toolkit config and `TMPDIR`, scrubbed variables, `SUPERVISOR_USAGE=unknown`), one batch at a time,
   directly and in the background (`heavy-job classify` says these runs are light).
5. Pass criteria for a batch: exit non-zero; every site of the batch has at least one `FAIL` label among its expected ones;
   every `FAIL` label is an expected one (a `FAIL` outside the list is an unlisted check of the site, which is added to D2,
   or a cross-effect or flake, which reruns the batch); and `ok + FAIL` equals the `ok` count of the final green run, which
   proves the run did not abort half-way.
6. Discard the copies and confirm `git diff --stat <start> -- global/` lists only `selftest.py`.

Suggested mutations (the implementer may choose another one that changes only that site, and says so):

| Site | Mutation |
|------|----------|
| S3a | `cmd_acquire`: replace `return report_held(owner)` with `report_held(owner); return 0` for the HELD case only (`if status_word(owner) == 'HELD': …`) |
| S3b | `cmd_reclaim`: `return report_held(owner, always_held=True)` → return `0` |
| S3c | `cmd_cloud`: `return 3` → `return 0` only when `err == UNAVAILABLE` |
| S3d | `cmd_cloud`: `return 3` → `return 0` only when `err != UNAVAILABLE` |
| S3e | `cloud_owned_target`: `util.die(…, 3)` → `util.die(…, 2)` |
| S4a | `report_held`: `else 4` → `else 3` |
| S6a | `cmd_open`: `return 6 if rows else 0` → `return 0` |
| S6b | `cmd_release`: the `return 6` after `OPEN WORK` → `return 0` |
| S6c | `cmd_release`: the `return 6` after the still-open listing → `return 0` |
| S7a | `cmd_backlog`: `return 7 if work else 0` → `return 0` |
| S7b | `cmd_beat`: the `return 7` after `GUARD REFUSED` → `return 0` |
| S8a | `SKILL_NOT_LOADED = 8` → `SKILL_NOT_LOADED = 0` is too broad (it also hits S8b); use: in `cmd_beat`, `return SKILL_NOT_LOADED` → `return 0` when `not refused_pause` |
| S8b | in `cmd_beat`, inside the skill branch, `return SKILL_NOT_LOADED` → `return PAUSE_REFUSED` when `refused_pause` |
| S9a | `cmd_beat`: the final `return PAUSE_REFUSED` → `return 0` |

The record (`evidence/mutations.md`) has one row per site: batch, mutation applied, the batch's exit code, the `FAIL` labels
of the site, and the clean-tree check. A site whose mutation produces no `FAIL` is a finding: the check is strengthened (never the mutation
weakened) and the row is redone.

## D6. Runtime

FACT (orchestrator baseline on the unmodified tree): the local gate is the piece test, run the way CI runs it:
`python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock.SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home`
exits 0 in about 408 s. The whole module (`python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock`) is the
same gate plus the fast tests of the entry point. Running `global/scripts/supervisor-lock self-test` directly under the real
`HOME` is not the gate: it inherits the session's environment, and a preparation run done that way showed 9 `FAIL` lines that
the piece test does not show. The self-test is never run against the real `HOME`.

FACT: `heavy-job classify` says the piece test module, a run of the self-test and the toolkit suite are light, so the runs of
this change (baseline, mutation batches, final gate) run directly, one at a time, in the background. The piece test gives
the self-test a 1500 s timeout.
