# GAPS — questions-session-top-level (honest multiagent review)

> **Date:** 2026-11-27
> **Mode:** A
> **Real status:** pre-apply gaps verified and hydrated; post-apply reviews below (round 1 applied points a–e, round 2
> points f and g and the gates)

## Review objective

Phase P2 of a `/run-spec` run: review the whole change (points a–g), settle in the spec, before any code, the
additions the orchestrator listed (point g, re-baseline, the meaning of "once" in point b, one wake per answer in
point c, task 9.1 dropped), then apply points a–e only.

## Methodology — 5-iteration loop (early stop allowed)

| Iter | Focus | Honest result |
|------|-------|---------------|
| **1** | Change documents vs the orchestrator's brief (point g, task 9.1) | 2 FACT (G-01, G-08) |
| **2** | Re-baseline against the merged tree (self-test floor, skill lint, self-test line numbers) | 3 FACT (G-02, G-03, G-04) |
| **3** | Point b: the deny-once marker (where, reset, corrupt inputs, latency) | 2 FACT (G-05, G-06) |
| **4** | Point c: one wake per answer, also on guard; probes split by point | 2 FACT (G-07, G-09); 1 INFERENCE (G-12) |
| **5** | STOP check | no new FACT gap; early stop |
| **post-1** | Post-apply review of points a–e against the specs and the code | 1 FACT (G-13), fixed during apply; points f and g are hydrated and tracked by open tasks (5.x, 6.4, 6.6, 10.x), not spec gaps |
| **post-2** | Post-apply review of points f and g (stamp through the hook, probes under load, mutations) | 2 FACT (G-14, G-15), both fixed during apply; no gap left open |
| **P4 confirm** | Independent re-derivation of points a–g against the specs, the brief's «done when» and the code | no FACT gap; 1 integration note (G-16), 1 INFERENCE (G-17) |

## Consolidated matrix

Legend: **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN**

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|
| G-01 | High | Point g (self-test probes that go red on a loaded machine; the three `< 0.3` s latency checks) is not in the change | Orchestrator brief, section «Añadido al cambio 3 … punto g» of the cycle's brief; `selftest.py` has no load-stability requirement | HYDRATED | `specs/supervisor-selftest-stability/spec.md` (new capability); design D7; tasks 10.x |
| G-02 | Med | The self-test floor is stated only as "rises"; the merged tree's floor is 564 (563 without the skill) | `scripts/toolkit/tests/pieces/test_supervisor_lock.py:1245` `assertGreaterEqual(checks, 564 if SKILL.is_file() else 563)` | HYDRATED | tasks 6.5 (a–c probes), 6.6 (f probes); VERIFY re-baseline |
| G-03 | Med | Task 7.4 and VERIFY compare the skill lint with `SKILL_LINT FAIL 2`; on the merged tree it is clean | `SUPERVISOR_SKILL_FILE=$PWD/global/skills/supervisa-sesiones/SKILL.md supervisor-lock skill-lint` (temp HOME) → `SKILL_LINT ok 0`, exit 0 | HYDRATED | task 7.4; VERIFY |
| G-04 | Low | Self-test line numbers moved; point g needs the current ones | `selftest.py:2127` (hook non-owner), `:2542-2543` (hook PreToolUse), `:3410` (hook Stop), `:1343-1346` (revive text, `hh(4000)` from `:1260`), `:2055` and `:2059` (Stop with no task / another owner's task), `:2140` (supervisor-stop-gate) | HYDRATED | design D7 (by label, line numbers only as of this baseline) |
| G-05 | Med | "Once" in point b: the marker's reset, a corrupt marker and a corrupt app record are not defined | design D3 says only "never removed"; `census.read_json_files` skips unreadable JSON (so a corrupt record reads as no record) | HYDRATED | design D3 (marker lifetime, pruning, corrupt inputs); spec «The ask gate never blocks the questions session twice» |
| G-06 | Low | The lineage lookup in the gate could slow every questions-session question if it parses all app records | `session_roles.is_mailbox_session` skips files whose text lacks the session id before parsing; the three latency checks are on non-mailbox paths (`selftest.py:2127`, `:2542`, `:3410`) | HYDRATED | design D1 (`app_record_of_cli` uses the same substring prefilter) |
| G-07 | Med | Point c: "each id at most once" has no scenario for consecutive polls and consecutive waits on guard; the turn state's write is not said to be under the store lock | `cloud.announce_once` runs under `lock_mod.Store()`; design D4 writes `questions-turns.json` without saying how | HYDRATED | spec «ANSWERED reports an answered queue item» (scenario «One wake per answer on guard»); design D4 |
| G-08 | Low | Task 9.1 (CI on the pushed branch) is the orchestrator's check, not a task of this change | Orchestrator brief, item 5 | HYDRATED | task 9.1 removed; VERIFY counts |
| G-09 | Med | Task 6.5 raises the floor for 6.1–6.4 at once, but 6.4 (stamp probes) belongs to point f, applied in a later phase | `tasks.md` 6.4/6.5 | HYDRATED | task 6.5 (a–c probes) and new 6.6 (f probes), each raising the floor by exactly its own count |
| G-13 | Med | (post-apply, round 1) A watcher left over from a former lock owner would record the `ANSWERED` announcements, so the current owner would miss them | `watch.py` `answered_events` read the lock's `mailbox` without checking `session_id`; fixed in apply: only while `--owner` holds the lock | HYDRATED | design D4 «Where»; test `test_a_watcher_of_another_owner_does_not_use_up_the_announcement` |
| G-14 | Med | (post-apply, round 2) The paused-limit revive probe compares `desde las HH:MM` with a `paused_at` written earlier: the same clock dependence as the revive probe of D7, but not in D7's table; it went red on a loaded pass | First done series under load, pass 3: `FAIL revive: the paused-limit text …`; `selftest.py` `pl_lock(… paused_at=hb_ago(7200))` and `hh(7200)` at check time | HYDRATED | fixed in apply with the same reference clock; D7 «As applied»; VERIFY mutation M5 |
| G-15 | Med | (post-apply, round 2) The no-watcher Stop probes depend on processes outside the sandbox: `wait_armed_in_proc` scans every process of the machine, so another self-test run's fake `wait --owner local_sup` arms this run's owner | `hook.py` `wait_armed_in_proc`; `selftest.py` starts such fake processes (sections 7 and the hook fallback checks) | HYDRATED | fixed in apply: inside the sandbox the scan counts only the same sandbox's processes; D7 «As applied»; probe in section 34; VERIFY mutation M4 |
| G-16 | Low | (P4, integration) The branch is behind `origin/main` (PRs #43–#46). `git diff origin/main -- …/selftest.py` therefore shows the usage-role checks (section 5c) as removed, although the branch never touched them: against the merge base no check is removed. A trial three-way merge (temp index, `git merge-tree`) auto-merges `selftest.py` keeping section 5c, and conflicts only on the self-test floor in `test_supervisor_lock.py` (branch 575/574, main 569/568) | `git merge-tree --write-tree <wip> origin/main` → `CONFLICT (content)` in `test_supervisor_lock.py` only; base `c38983e` has 0 `usage-role` lines, main 11 | INTEGRATION | at merge: floor = main's + this change's +11 → 580/579; rerun `SelfTestTest` after the merge |
| G-17 | Low | (P4) If the app flips the questions session's status off `busy` one poll before it raises `completedTurns`, the held answers fire alone and the turn fires on the next wait: two `ANSWERED` wakes for one batch | `questions_wake.answered_line`: `held` requires `busy`; the turn needs a higher count | INFERENCE | not reproducible without the real app's write order; each id and each turn is still announced once |
| G-12 | Low | A questions session whose cwd is outside the project is not in the census, so the turn trigger never sees it | `census.collect_sessions` keeps only rows whose cwd resolves to the project | INFERENCE | design «Edge cases» (queue trigger still works) |

## Useful casuistics (documentation, not always new REQ)

- A questions session denied once and then detached takes the `allow-mailbox` path from then on; its marker is never
  read again.
- The first wait after install may announce the answers of the last 24 h once (design «Risks»).

## Out of v1 (does not block APPLY)

- Whether a real, unattended questions session may call `detach_session` with `"self"` (task 9.4, UNKNOWN).

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (spec OK; `/aplica-tarea` only) | 12 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN / INTEGRATION) | 3 |

**Gaps pending (mejora + apply): 0**

## Verification (this document)

- **Verified:** every FACT row's evidence was read on this branch (file and line, or the command output quoted).
- **Verified (post-apply, round 1):** points a–e implemented with unit tests and self-test probes (see `VERIFY.md`,
  «Round 1 apply»).
- **Verified (post-apply, round 2):** point f through the `hook` command (unit tests and two self-test probes) and
  point g (reproduction, fixes, five mutation runs, three consecutive green passes under load and one across a minute
  boundary; see `VERIFY.md`).
- **Verified (P4 confirm review):** a) `titles.detach_lines`/`adopt_lines` (closer only) and their tests; b)
  `ask_gate.mailbox_lineage_decision` denies once, marker by local id, fail open on no/corrupt record, unwritable or
  corrupt marker; a hook-denied attempt is an error tool result, so the duplicate backstop does not catch the retry;
  c) `ANSWERED` in `GUARD_EVENTS`, computed from the unfiltered census rows, recorded under the store lock before it is
  printed; d) probes in sections 32–34 for a, b, c, f; e) no generic sentence keeps the questions session as a child
  (the older `cambios.md` entry is superseded by the new top one), override listed by file and heading only; f) the
  stamp is written right after `owner = locks[local]`, before the `stop_hook_active` test and the chain, the report
  block unchanged; g) best of three keeps `< 0.3` (3 `took < 0.3` lines, as on the base): legitimate, since the timed
  path has no in-process or on-disk cache that a second run would warm, a deterministic slowdown is slower in every
  run (M3), and runs that disagree fail the check; M1, M2, M4, M5 target deterministic outputs and stay caught; the
  three chained-block probes now assert the whole no-watcher reason (stricter). Gates:
  `python3 -m unittest scripts.toolkit.tests.pieces.test_supervisor_lock` 105 tests OK (exit 0);
  `python3 scripts/validate-toolkit.py` exit 0; `openspec validate questions-session-top-level --strict` exit 0;
  `python3 scripts/privacy-check.py --require-private` 0 findings, exit 0.
- **Not verified here:** the three loaded passes of the reproduction stayed green, so the original red was not
  reproduced on this machine; the fixes target what the code shows (clock, single-run timing, machine-wide process
  scan). Tasks 9.2–9.4 run after the branch (install, override phrases, a real self-detach).

Gaps pending (mejora + apply): 0
