# GAPS — mailbox-connector-call-shape (preparation pass)

> **Date:** 2026-11-27. **Mode:** A (change folder `openspec/changes/mailbox-connector-call-shape/`).
> **Real status:** preparation pass (P1) by one agent plus one advisor consultation; the gaps below were found while reading
> the code and the neighbouring specs and are closed in the documents. The independent review (`repasa-spec`) has not run.

| ID | Sev | Gap | Evidence (FACT) | Status | Where closed |
|----|-----|-----|-----------------|--------|--------------|
| G-01 | med | The permanent `mailbox-search-results` says "Connector accounts SHALL behave as before"; adding `view`, `paging` and `arguments` contradicts the letter | `openspec/specs/mailbox-search-results/spec.md` requirement "Existing output is unchanged…", scenario "Connector accounts do not change" | HYDRATED | `specs/mailbox-search-results/spec.md` (MODIFIED, whole block), proposal "Capabilities" |
| G-02 | med | `mailbox-access` ("One short routing skill") says the session goes straight to the connector tools; the skill now goes through `mailbox` first | `openspec/changes/external-access/specs/mailbox-access/spec.md` | HYDRATED (recorded as a divergence; that change is not edited here) | proposal "Capabilities", design D10 |
| G-03 | med | Item 1 (notice fields) and item 5 (pass verbatim, adding nothing) collide on `pageToken` | description of the change | HYDRATED | design D3: notice outside `arguments`; continuation is a second call that the document itself describes; the skill needs no extra words |
| G-04 | med | Three existing tests assert exact key sets or equality of connector documents and will fail on correct code | `test_mailbox.py` `test_the_document_names_the_tools_and_the_page_size` (exact `set(document)`), `test_whoami_prints_the_cheap_call_and_how_to_pass_the_answer_back` (exact dict), `test_reading_commands_on_a_connector_account_are_delegated_too` (reads only `tool`; kept) | HYDRATED | design D8 defines additive as "existing keys keep name, type and value"; task 1.2 updates the first two |
| G-05 | low | `folders` and `save` share `read_document` with `show`/`thread`; the change must say what they print | `global/scripts/mailbox` `cmd_folders`, `_id_command` | HYDRATED | design D7, spec "Commands without a connector read call keep their output" |
| G-06 | low | Exit codes of `show` and `thread` for a connector account: the description asks to check them | `_id_command` raises `SystemExit(DELEGATED)` (10); existing test asserts 10 for `show`, `thread`, `folders`, `save` | ALREADY (no code change; regression scenario and test only) | spec "Exit codes agree with search", task 1.3 |
| G-07 | med | Invalid configured values must not follow the silent fallback of the numeric `defaults` keys | `Config.__init__` falls back silently; account settings go through `_setting_problem` → `_error` → `pick_account` exits 2 | HYDRATED | design D6, spec "Connector settings are validated" and "An invalid connector setting makes the account unusable" |
| G-08 | low | `connector.page_size_max` must exclude booleans (`isinstance(True, int)`) | `_usable_number` already rejects bool; the new check must too | HYDRATED | spec scenario "Page-size maximum" (includes `true`) |
| G-09 | low | `--body-chars`, `--no-quote`, `--headers`, `--json` are accepted and ignored on a connector account; the change had to say what happens | `_id_command` takes no notice of them | HYDRATED (unchanged, stated) | design D5, spec scenario "Other options of show are accepted and change nothing" |
| G-10 | low | The new flag on an `imap`/`local` account | precedent: `--backend` on a connector account exits 2 | HYDRATED | spec scenario "The flag on another backend" |
| G-11 | low | `MINIMAL`: `show --headers` prints every header plus the body, so no existing option is a headers-only read | `cmd_show`, `render_message` | HYDRATED (left out as an option, design D5) | design D5 |
| G-12 | low | The per-account defaults live in two code places (`ACCOUNT_DEFAULTS` and `connector_settings`), not in the shipped config | `global/scripts/mailbox`, `mail_connector.connector_settings` | HYDRATED | design D6 (one set of constants in `mail_connector`, both read it), task 2.1 |
| G-13 | low | Requirement text longer than 500 characters fails `openspec validate --strict` | validator warning | HYDRATED (requirements split) | spec files |
| G-14 | — | What the connector returns for `messageFormat` `MINIMAL` and `METADATA_ONLY` on a read | not in the measured shapes | UNKNOWN (no flag, so nothing depends on it; the setting accepts them) | design D5 |
| G-15 | — | Whether a session passes `paging.continue_with` on correctly | needs a live session | UNKNOWN | task 10.1 (supervisor, after install) |

## Independent review and post-apply pass (repasa-spec, round 1)

> **Date:** 2026-11-27. Phase 1 (review of the spec and design against the code before applying) found G-16 to G-21; the
> hydration closed them in the documents, the apply closed them in code and tests, and the post-apply pass re-read the code
> and the documents against each other.

| ID | Sev | Gap | Evidence (FACT) | Status | Where closed |
|----|-----|-----|-----------------|--------|--------------|
| G-16 | med | The design had `ACCOUNT_DEFAULTS['connector']` read the new defaults: a value copied at import time freezes the default, so the "Self-test notices a drift" scenario (constant changed in the process) could not fail | `global/scripts/mailbox` builds `ACCOUNT_DEFAULTS` at import and `normalize_account` merges it into every account | CLOSED: defaults resolved inside `connector_settings` at call time; `ACCOUNT_DEFAULTS` keeps its 3 keys | design D6, task 2.1, `ConnectorSettings.test_the_defaults_are_the_literals_of_the_spec`, `ConnectorSelfTestDrift` (2 tests, exit 1) |
| G-17 | low | `--full-content` on a connector account of a kind other than gmail was not defined | design D7 | CLOSED: accepted and ignored (legacy document) | design D7, spec scenario "A connector kind other than gmail", `test_a_connector_kind_other_than_gmail_keeps_its_documents` |
| G-18 | low | `whoami ACCOUNT --sender ADDRESS` on an unusable account exits 2 (the account is picked first); only `whoami` without `--sender` was stated | `cmd_whoami` calls `pick_account` first | CLOSED (stated, existing precedence) | design D6, spec scenario "whoami with a sender on an unusable account", `test_an_invalid_setting_makes_every_command_that_picks_the_account_exit_2` |
| G-19 | low | `null`, the empty string, `0` and `false` as a setting value were undefined; the `or` idiom of the tool names would turn `""` into the default silently | `connector_settings` uses `or` for the tool names | CLOSED: absent or null is the default, anything else must be valid | design D6, spec scenario "Absent or null is the default", `test_absent_and_null_are_the_default` |
| G-20 | low | `page_size_max` 50.0 (a float with an integer value) was not in the invalid list | spec scenario "Page-size maximum" | CLOSED | spec, `test_the_page_size_maximum_is_a_whole_number_of_at_least_one` |
| G-21 | low | The self-test had to compare with literal values or a changed constant would pass it | `mail_selftest.run` | CLOSED | task 6.1, self-test checks |
| G-22 | low | Post-apply: the new `note` text of `show` and `thread` was not the one the design said | design D4 | CLOSED (design edited to the printed text) | design D4 |

Unchanged UNKNOWNs: G-14 (what the connector returns for `MINIMAL` and `METADATA_ONLY` reads) and G-15 (whether a live
session continues with `pageToken`); neither blocks the code, and G-15 is checked by task 10.1 after the install
(`[prod-verify]`). They need the installed side or the live connector, so they are not counted as pending for the cycle.

Post-apply check: every requirement and scenario of both spec files maps to a named test (task 6.2); the spec, design D6 and
`--help` carry the same names and values (task 9.5); `openspec validate --strict`, the repository validator, the privacy check,
271 module tests, the self-test and `examples/override-full/try.sh` pass. Not run here by order: the full discovery (task 9.6,
CI) and the live connector (task 10.1).

## Independent confirm review (P4, round 1)

> **Date:** 2026-11-27. Re-derived from the spec and the code with the old output of `HEAD` run from a temporary copy outside
> the repository (synthetic home, reserved addresses). Edge cases run by hand: `--limit` 49, 50, 51, 200, 0; a configured
> maximum of 10 and of 100; invalid view, format and maximum (`THREAD_VIEW_FULL`, empty string, `true`, `50.0`); an id with a
> quote, a backslash, a space and an accent; `--header`; `--format`; kind `other`; folders and save against the old output.
> Documents of a connector account are a superset of the old ones in every key; the only changed old value is the prose of
> `note` on `show` and `thread` (declared, design D4 and D8). The skill body went from 1 862 to 1 861 characters.

| ID | Sev | Gap | Evidence (FACT) | Status | Where closed |
|----|-----|-----|-----------------|--------|--------------|
| G-23 | low | Design D6 said `doctor ACCOUNT` prints `unusable:` and exits 3; it exits 2 (the account is picked first) and only `doctor` without an account prints `unusable:` and exits 3 | `cmd_doctor` calls `pick_account` when an account is named; the existing test asserts 2 and 3 | CLOSED (design edited to the real behaviour) | design D6 |
| G-24 | low | The spec and `--help` said any invalid connector setting makes the account unusable; the code (and design D6, D7) validates only a Gmail connector, so a connector of another kind with a nonsense `search_view` is not refused | `mail_connector.setting_problem` returns '' for a kind other than `gmail`; `test_a_connector_kind_other_than_gmail_keeps_its_documents` | CLOSED (spec requirement and scenario, `--help` sentence) | spec R-CFG, `global/scripts/mailbox` help |
| G-25 | low | The spec asked for an id "not empty"; the code and design D4 also refuse an id of only whitespace (exit 2), which the spec did not state | `read_call` refuses `not thread_id.strip()`; `test_an_empty_id_is_refused` includes `'   '` | CLOSED (spec requirement and scenario) | spec R-READ |
| G-26 | low | The proposal "Impact" still listed `ACCOUNT_DEFAULTS` and `cmd_search` as edited, which G-16 and the final code contradict | `git diff` of `global/scripts/mailbox` touches neither | CLOSED | proposal "Impact" |
| G-27 | med | R-SKILL ("passes the printed call verbatim", "does not grow") had no test that fails when the skill step loses its wording or the body grows past 1 862: the existing test only caps 2 000 | `grep` of `test_mailbox.py` for the skill: one test, cap 2 000 | CLOSED (new test `test_the_skill_passes_the_printed_connector_call_verbatim_and_did_not_grow`: body at most 1 862, the step names `search`, `show`, `thread`, `tool`, `arguments`, "tal cual", "sin añadir ni quitar", `whoami`, `--sender`) | `scripts/toolkit/tests/pieces/test_mailbox.py` |
| G-28 | low | False or stale sentences: tasks 2.3 (`doctor ACCOUNT` prints `unusable:`), READY-TO-APPLY (42 scenarios; there are 45), proposal Impact (three tests updated; two are, a third is kept), design D9 (a test that `ACCOUNT_DEFAULTS` and `connector_settings` agree, reversed by G-16), `--help` opening of "Connector accounts" (said every connector kind gets arguments) | read against the code and the test names | CLOSED (each sentence corrected; help scoped to a gmail connector) | tasks, READY-TO-APPLY, proposal, design, `--help` |

Superset check run with the old code from a temporary copy of `HEAD`: default gmail `search` (three filter sets), `show`, `thread`,
`folders`, `whoami` and `whoami --sender`, same exit codes; every old key is present with its old value except `note` on `show`
and `thread`, whose prose changed on purpose (design D4, D8; the spec requires the key, not its text).

Observation, not a gap: a configured `connector.page_size_max` above 50 (for example 100) prints `pageSize` up to that value,
which the connector refuses above its own maximum. This is the stated behaviour (spec R-PAGE, design D6: "the owner may know it
has changed") and a test pins it; the owner who sets it takes the risk.

Gaps pending (mejora + apply): 0
