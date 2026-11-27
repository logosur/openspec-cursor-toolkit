# Tasks — blocking-questions-partial-batch

Requirement references: **QB** = `specs/developer-question-batches/spec.md`. Design decisions: **D1**–**D9** in `design.md`.

## 1. ask-queue

- [x] 1.1 `blocks_work`, `due_items`, `partial_batch_state` and the two thresholds from the `supervision` piece (QB: blocking-due; one partial batch per window; thresholds are configuration; D1–D3).
- [x] 1.2 `add --order` (blank refused with 2, kept on a plain duplicate) and `list --due [--json]` with `age_h`, `due_reason` and one batch line per project (QB: order flag; D4, D5).
- [x] 1.3 Keys `ask_due_after_h` and `ask_partial_batch_window_h` in `global/config/supervision.json`; a `list --due` probe in `global/contracts/ask-queue.yaml`.
- [x] 1.4 Unit tests in `scripts/toolkit/tests/pieces/test_ask_queue.py` for every scenario of the four ask-queue requirements.

## 2. supervisor-lock

- [x] 2.1 `askdue.py` (state, line, announced events; fail silent) (QB: the supervisor is told; D6).
- [x] 2.2 Watcher: `ASKDUE` in `machine_events` every 300 s and in `GUARD_EVENTS`; `beat`: the line on stderr (D6).
- [x] 2.3 Deny texts extended (`deny_question`, `deny_absent`, `deny_supervised`) without rewording asserted fragments; archive template with `--blocks "nada: solo su archivado"` (QB: texts; D7, D8).
- [x] 2.4 Self-test checks next to the deny-text checks (section 11c). Compiled and name-checked only; they run in CI (`SelfTestTest`), not on this machine.
- [x] 2.5 Unit tests in `scripts/toolkit/tests/pieces/test_supervisor_lock.py`: beat line, window closed, announce once, guard event, no queue, deny texts.

## 3. Skill and rules

- [x] 3.1 `SKILL.md` point 5; `reference/f5-decisiones.md`, `vigilancia.md`, `anti-patrones.md`, `registro-y-cierre.md`; top entry in `reference/cambios.md` (QB: texts; no report blames an unasked question; D9).
- [x] 3.2 Rules `despliegue-y-limites-duros.md`, `desatencion-sin-preguntas.md`, `supervisor-decide-lo-documentado.md`; skill `panel-de-decision`.
- [x] 3.3 `skill-lint` on the repo copy passes (`SKILL_LINT ok 0`; core 12 538 characters).

## 4. Gates on this machine

- [x] 4.1 `openspec validate blocking-questions-partial-batch --strict`.
- [x] 4.2 The touched unit test classes, by id: `test_ask_queue` (whole module) and `test_supervisor_lock` `ConfigTest`, `EntryPointTest`, `DegradationTest`, `ReannounceIntervalTest`, `AllIdleBackoffTest`, `QueuedJobSuppressesAllIdleTest`, `RenameHintTest` (121 tests, OK), then `AskDueTest` and `AskDueTextsTest` (7 tests, OK).
- [x] 4.3 `python3 -m unittest scripts/test_validate_toolkit.py`, `python3 scripts/validate-toolkit.py`.
- [x] 4.4 Privacy check on the staged files (`--staged --require-private`: 0 findings) and on the commit message.
- [ ] 4.5 `privacy-check.py --range origin/main..HEAD` once the commit exists (run after committing; result in the hand-off report).

## 5. After this branch (not done here)

- [ ] 5.1 CI green: full unit discovery, `supervisor-lock self-test` (inside `SelfTestTest`) and `examples/override-full/try.sh`.
- [ ] 5.2 Install, then reload the skill in each live supervisor (`reference/cambios.md` entry).
- [ ] 5.3 The developer's private override copies of the three rules get the same wording (the override is not in this repo).
- [ ] 5.4 Archive the change once 5.1–5.3 are done.
