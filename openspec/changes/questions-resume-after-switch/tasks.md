# Tasks — questions-resume-after-switch

One implementer, in order. Tests first in each task. All state is synthetic, in temporary folders with a temporary
`HOME`; never run `account-switch detect` and never read the real queue, locks or app records.
Piece tests: `python3 -m unittest scripts.toolkit.tests.pieces.test_account_switch -k <pattern>`; name the new tests
so that the pattern of their task matches them (a run of 0 tests is not a pass).

## 1. Selection

- [x] 1.1 In `test_account_switch.py`, make `env()` set a temporary `HOME`, `ASK_QUEUE_DIR` and `ASK_QUEUE_BIN` (the
      repository's `ask-queue`) and add a helper that creates items with `ask-queue add` + `asked --to`. Add to
      `global/scripts/account-switch` the queue reader of design D3 (`{id: item}`). Tests: items of every status;
      missing script, failing script and non-JSON output give `{}`; a non UTF-8 queue file of one project still gives
      the other project's items.
      Check: `-k asked_reader` passes and the whole file still passes.
- [x] 1.2 Add the mailbox reader (24-hour window) and the kind `questions` to `stopped_sessions` (design D2), with the
      scenarios of «A switch lists the questions session» and of «Existing exclusions and a missing queue». Check:
      `-k questions_selection` passes and the existing watcher tests still pass.

## 2. Pending and texts

- [x] 2.1 `pending_sessions` handles `questions` (design D4), with the scenarios of «A questions row stays pending»
      and «A watcher still drops after a turn».
      Check: `-k questions_pending` passes.
- [x] 2.2 `questions_text(ids)` (design D5), its block in `steps()` and its mark in `session_line`. Tests: both steps
      scenarios and «Supervisor, closer and questions session together»; the text starts with the configured marker and
      does not match `LIMIT_TEXT`.
      Check: `-k questions_steps` passes.
- [x] 2.3 `mine` prints the text under each pending questions row; `on-switch` adds its notice line; the module
      docstring describes the kind. Tests: the `mine` and notice scenarios. Check: `-k questions_notice` and
      `-k questions_mine` pass, and `python3 global/scripts/account-switch --help` mentions the questions session.

## 3. Gate

- [x] 3.1 In `test_cross_project_message_gate.py`, add the listed/unlisted scenario for a `questions` row, sending the
      text that `questions_text` of the repository's `account-switch` builds. Test only: the hook does not change. Check:
      `python3 -m unittest scripts.toolkit.tests.pieces.test_cross_project_message_gate -k questions` passes.

## 4. Documents

- [x] 4.1 `global/rules/cambio-de-cuenta.md`: one bullet for questions sessions.
      `global/scheduled-tasks/account-switch-resume/SKILL.md`, step 2: questions rows carry their own text.
      Check: `python3 scripts/validate-toolkit.py` exits 0.
- [x] 4.2 `global/modules/accounts.yaml`: add `scripts/ask-queue` to `project_provided` and a note that it is optional;
      `README.md`, `accounts` row: mention the questions session. Check: `python3 scripts/validate-toolkit.py` exits 0
      with no `global-citation` finding.
- [x] 4.3 `global/skills/supervisa-sesiones/reference/f5-decisiones.md`, «La sesión de preguntas»: after a switch,
      `account-switch` asks it to present the pending questions again; the supervisor resends only the ids that the
      session says it does not have. Check: `python3 scripts/validate-toolkit.py` exits 0 and
      `grep -n "account-switch" global/skills/supervisa-sesiones/reference/f5-decisiones.md` finds the sentence.

## 5. Verification

- [x] 5.1 Run, one at a time: the piece tests of `account-switch` and of the cross-project gate,
      `python3 scripts/validate-toolkit.py`, `python3 -m unittest scripts/test_validate_toolkit.py`,
      `bash examples/override-full/try.sh`, `openspec validate questions-resume-after-switch --strict` and
      `python3 scripts/privacy-check.py --require-private`; record the exit codes in `VERIFY.md`. No whole-tree
      `unittest discover`.
      Check: all exit 0.
