# Evidence — supervisor-exit-code-probes

Phase P2 of `run-spec` (`repasa-spec`), 2026-11-27. Starting commit: `182c084`. Paths are relative to the repository root.

## How the runs were made

- **Local gate** (design D6): `python3 -m unittest -v scripts.toolkit.tests.pieces.test_supervisor_lock`, run in the worktree
  directly (`heavy-job classify`: light). It contains
  `SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home`, which runs the self-test in a temporary `HOME`.
- **Counted runs** (baseline, final, mutation batches): a copy of `global/` in the session's scratch directory, its
  `global/scripts/supervisor-lock self-test` run with the environment of the piece test (`Base` in
  `scripts/toolkit/tests/pieces/test_supervisor_lock.py`: throwaway `HOME`, own toolkit config and `TMPDIR`, the same
  scrubbed variable prefixes, `SUPERVISOR_USAGE=unknown`). Never against the real `HOME`. One run at a time.
- **Mutations** (design D5): three throw-away copies of the final `global/`, one per batch; the worktree was never mutated.
  The expected `FAIL` labels of every batch were written down before any batch result was read.

## Baseline and final

| Run | Tree | Exit | `ok` | `FAIL` | Last line | Wall time |
|-----|------|-----:|-----:|-------:|-----------|----------:|
| Orchestrator baseline (unittest, `SelfTestTest.test_the_whole_self_test_passes_in_a_temp_home`) | unmodified | 0 | — | 0 | — | about 408 s |
| Baseline count (copy, piece-test environment) | unmodified | 1 | 645 | 1 | `FAIL: 1 failed` | 243 s |
| Local gate (unittest module, 82 tests) | final | 0 | — | 0 | `OK` | 355 s |
| Final count (copy, piece-test environment) | final | 0 | 652 | 0 | `ok: 0 failed` | 243 s |
| Toolkit suite (`unittest discover -s scripts/toolkit/tests -t . -v`, 1221 tests, includes the gate) | final | 0 | — | 0 | `OK` | 1291 s |

Every label named in design D2 and D3 printed `ok` in the final run. Every D2 label printed `ok` in the baseline count run.
652 = 646 (645 `ok` + 1 `FAIL` of the baseline count run) + 6 new checks.

The one `FAIL` of the baseline count run is `watchdog --notify: idle text, unknown text (time from the heartbeat)`, a check
outside this change (no exit code, not touched) that compares an `HH:MM` clock text built at two different moments.
INFERENCE: an intermittent failure when a minute boundary falls between them. It printed `ok` in the other five runs of the
same check (the local gate, the final count and the three batches), and the orchestrator's baseline of the unmodified tree
was green. It is recorded, not fixed (out of scope: no existing check is changed).

## Mutation batches

| Batch | Sites | Exit | `ok` | `FAIL` | `ok + FAIL` | Unexpected `FAIL` |
|-------|-------|-----:|-----:|-------:|------------:|-------------------|
| 1 | S3a, S3c, S6a, S7a, S8a | 1 | 635 | 17 | 652 | none |
| 2 | S3b, S3d, S6b, S7b, S8b | 1 | 643 | 9 | 652 | none |
| 3 | S4a, S3e, S6c, S9a | 1 | 643 | 9 | 652 | none |

`ok + FAIL` equals the final count in every batch, so no run stopped half-way. Every `FAIL` was one of the labels expected for
its batch.

## Per site

| Site | Batch | Mutation (on the copy) | `FAIL` labels of the site | Result |
|------|------:|------------------------|---------------------------|--------|
| S3a | 1 | `lock.cmd_acquire`: a `HELD` owner prints the report and returns 0 | `acquire: other session, fresh -> HELD, exit 3`; `ttl: paused lock 1 h old is still fresh (3)`; `concurrency: 12 acquires -> one exit 0, eleven exit 3` | FAIL seen |
| S3b | 2 | `lock.cmd_reclaim`: the wrong `--from` prints the report and returns 0 | `reclaim: wrong --from -> HELD, exit 3, untouched` | FAIL seen |
| S3c | 1 | `cloud.cmd_cloud`: returns 0 when the provider is absent | `cloud: no cloud provider -> CLOUD-UNAVAILABLE, exit 3, never «none»`; `cloud --json: no cloud provider -> available false, exit 3` | FAIL seen |
| S3d | 2 | `cloud.cmd_cloud`: returns 0 when the API is unreadable | `cloud: an unreadable API is CLOUD-UNKNOWN with exit 3, never «none»` | FAIL seen |
| S3e | 3 | `cloud.cloud_owned_target`: `die(…, 3)` → `die(…, 2)` | `cloud-archive: unreadable cloud rows -> exit 3, nothing archived`; `cloud-send: unreadable cloud rows -> exit 3, nothing sent` | FAIL seen |
| S4a | 3 | `lock.report_held`: `else 4` → `else 3` | `acquire: other session, stale -> STALE, exit 4`; `ttl: paused lock 3 h old is stale (4)`; `ttl: running lock 1 h old is stale (4)` | FAIL seen |
| S6a | 1 | `lock.cmd_open`: `return 6 if rows else 0` → `return 0` | `open: no lock -> nobody is excluded, exit 6 and the count line`; `open: owner and questions session are not counted, exit 6, …` | FAIL seen |
| S6b | 2 | `lock.cmd_release`: the `return 6` after `OPEN WORK` → `return 0` | `release: other live session busy -> exit 6 …`; `release: the questions session plus another busy session -> exit 6, …`; `workspace: release refuses (exit 6, OPEN WORK) …` | FAIL seen |
| S6c | 3 | `lock.cmd_release`: the `return 6` after the still-open listing → `return 0` | `release: a session nobody opened (not archived) is still open -> exit 6, …`; `workspace: release refuses (exit 6, OPEN lines) …` | FAIL seen |
| S7a | 1 | `backlog.cmd_backlog`: `return 7 if work else 0` → `return 0` | `backlog: each change with unchecked tasks is WORK …, exit 7`; `backlog: a park is void once …` | FAIL seen |
| S7b | 2 | `lock.cmd_beat`: the `return 7` after `GUARD REFUSED` → `return 0` | `beat --phase guardia: refused (7) …`; `beat --phase guardia: refused while the registry does not explain the guard`; ``replay: `beat --phase guardia` is refused …`` | FAIL seen |
| S8a | 1 | `lock.cmd_beat`: `return SKILL_NOT_LOADED` → `0` when the pause was not refused | the eight `skill-seen proof: … refused` checks of section 9b | FAIL seen |
| S8b | 2 | `lock.cmd_beat`: `return SKILL_NOT_LOADED` → `PAUSE_REFUSED` when the pause was refused | `skill-seen proof: a beat refused for the skill and for the pause exits 8 with both reasons, state kept` | FAIL seen |
| S9a | 3 | `lock.cmd_beat`: the final `return PAUSE_REFUSED` → `return 0` | `beat --state paused with usage and no --third-party: refused (exit 9), …`; `beat --state paused with usage on a limit pause: refused, …` | FAIL seen |

Not covered by these mutations (they change exit codes only): the "state unchanged" assertions of N1, N3 and N4 stay `ok`
under them, as expected; they guard against a refusal that writes, which no D5 mutation introduces.

## Clean tree

The copies were discarded after the record. `git diff --stat 182c084 -- global/` lists only
`global/scripts/lib/supervisor/selftest.py`, and nothing under `global/skills/supervisa-sesiones/` changed: confirmed (32 lines added, none removed or changed in `selftest.py`).
