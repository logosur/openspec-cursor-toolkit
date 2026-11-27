# Tasks — mailbox-connector-call-shape

Requirement references (all in `specs/mailbox-connector-calls/spec.md` unless noted): **R-VIEW** the search call carries a
bounded view, **R-PAGE** the page size is capped, **R-NOTICE** a capped search says so outside the arguments, **R-READ** the
read call carries the id and a message format, **R-HTML** the HTML body is read only when asked for, **R-LEGACY** commands
without a connector read call keep their output, **R-WHOAMI** the identity check asks for metadata only, **R-CFG** connector
settings are validated, **R-UNUSABLE** an invalid setting makes the account unusable, **R-ID** the server identifier is never
stored or printed, **R-TEST** the self-test and piece tests pin the shape, **R-SKILL** the skill passes the call verbatim and
does not grow; **R-KEEP** is the modified requirement of `specs/mailbox-search-results/spec.md`. Design decisions: `design.md`
D1 to D11.

Each task ends with its own check. Every test runs in a temporary home with synthetic accounts (reserved example addresses);
no task reads a real mailbox or calls the connector, except task 10.1. Run the piece tests by module, not the whole discovery:
`python3 -m unittest scripts.toolkit.tests.pieces.test_mailbox scripts.toolkit.tests.pieces.test_access_helpers` (the full
discovery is task 9.6 and runs in CI).

## 1. Baseline

- [x] 1.1 Before any product edit, capture the current connector documents on the synthetic account as literals of a
  compatibility test: `search` (no filter, with `--from`, with `--limit 5`), `show`, `thread`, `folders`, `save`, `whoami`, with
  their exit codes. Check: the new test passes on the unmodified code (R-KEEP "Connector accounts do not change", R-LEGACY).
  Evidence: `ConnectorCompatibility` (5 tests) passes on a copy of the unmodified HEAD tree (5 OK) and on the changed code.
- [x] 1.2 Update the two existing tests that assert an exact shape so they assert the new one once the code lands:
  `test_the_document_names_the_tools_and_the_page_size` (exact key set of the search document) and
  `test_whoami_prints_the_cheap_call_and_how_to_pass_the_answer_back` (whole-dictionary equality). Add a test that every old
  key of every document of 1.1 is still present with its old value (design D8). Check: the updated tests fail on the unmodified
  code for the right reason (missing `view`) and pass after groups 2 to 5; the old-key test passes before and after.
  Evidence: the two updated tests fail on the HEAD copy (missing `view`, `paging`) and pass now; `test_every_old_key_of_a_search_document_is_still_there` passes on both.
- [x] 1.3 Pin the exit codes: `search`, `show`, `thread`, `folders` and `save` on a connector account exit 10 with the document on
  stdout and nothing on stderr (FACT in design D1: already true). Check: a test passes on the unmodified code (R-READ "Exit codes
  agree with search").

## 2. Constants, settings and validation (`mail_connector.py`, `global/scripts/mailbox`)
  Evidence: `test_exit_codes_agree_for_search_show_and_thread` (search, show, thread, folders, save: 10, stderr empty) passes on the HEAD copy and now.

- [x] 2.1 `mail_connector.py` gains `SEARCH_VIEWS`, `DEFAULT_SEARCH_VIEW` (`THREAD_VIEW_SUMMARY`), `READ_FORMATS`,
  `DEFAULT_READ_FORMAT` (`PLAIN_TEXT`), `PAGE_SIZE_MAX` (50) and `WHOAMI_VIEW` (`THREAD_VIEW_METADATA_ONLY`);
  `connector_settings` returns `search_view`, `read_format` and `page_size_max`; the three new defaults are resolved inside
  `connector_settings` at call time (not copied into `ACCOUNT_DEFAULTS` at import: design D6). Check: a test that
  `connector_settings` of an account with no setting returns the literal values of the spec, and that the three settings set
  on the account are returned as given; an absent or `null` setting gives the default.
  Evidence: `ConnectorSettings.test_the_defaults_are_the_literals_of_the_spec` and `test_absent_and_null_are_the_default` pass; `ACCOUNT_DEFAULTS['connector']` keeps its 3 keys (asserted).
- [x] 2.2 `mail_connector` validation function, called from `_setting_problem` only when `connector` is among the backends and
  the kind is `gmail`: exact match against the known values; absent or `null` is the default; `page_size_max` an integer of at least 1,
  not a boolean (`50.0` refused); the error names the key and lists the values. Check: R-CFG scenarios "Unknown view", "Wrong case is not repaired", "Not a string",
  "Page-size maximum", "Every valid value is accepted", "The settings of another backend are not checked".
  Evidence: the tests of unknown view, wrong case, not-a-string, page-size maximum, every valid format and view, and the settings of another backend (`ConnectorSettings`, `ConnectorSearchCall`, `ConnectorReadCall`) pass.
- [x] 2.3 An invalid value makes the account unusable. Check: R-UNUSABLE scenarios "whoami on an unusable account" and
  "accounts lists it"; every command that picks the account exits 2 with stdout empty (`search`, `show`, `thread`, `folders`,
  `save`, `whoami`); `doctor ACCOUNT` exits 2 and `doctor` with no account prints `unusable:` and exits 3 (existing behaviour, asserted).

## 3. The search call and the identity check
  Evidence: `test_an_invalid_setting_makes_every_command_that_picks_the_account_exit_2` (7 commands exit 2 with stdout empty, `accounts` exit 0 with `UNUSABLE`, `doctor ACCOUNT` exit 2 as for any unusable account, `doctor` of all exit 3 with `unusable:`).

- [x] 3.1 `search_document` prints `arguments {query, pageSize, view}` with the configured or default view, `pageSize =
  min(limit, maximum)`, and the always-present top-level `paging` (`continue_with` and `how` only when capped). Check:
  R-VIEW "Default view", "Per-account view", "Every known view is accepted", "Existing keys are untouched"; R-PAGE "Within the
  maximum", "Exactly the maximum", "Above the maximum", "Configured maximum", "A limit below one"; R-NOTICE "Not capped",
  "Cap stated", "Notice stays out of the connector's arguments", "Configured maximum stated".
  Evidence: `ConnectorSearchCall` (7 tests) pass: default and per-account view, keys exactly `query,pageSize,view`, cap 20/50/200/0/-3, configured maximum, `paging` always present and outside `arguments`.
- [x] 3.2 `whoami_call` adds the fixed view. Check: R-WHOAMI "The check call", "The view does not follow the search setting",
  "The sender check is unchanged".

## 4. The read call
  Evidence: `ConnectorWhoami` (2 tests) pass; `whoami` of `kind: other` prints the legacy call (`ConnectorReadCall.test_a_connector_kind_other_than_gmail_keeps_its_documents`).

- [x] 4.1 New builder `read_call(account, thread_id, full_content)` printing `{delegate, kind, tool, arguments {threadId,
  messageFormat}, note}`; `_id_command` uses it for `show` and `thread` on a connector account of kind `gmail`, refuses an empty
  id with exit 2, keeps `read_document` for `folders`, `save` and other kinds, and still exits 10. Check: R-READ "Default read
  call", "The id is carried unchanged", "An empty id is refused", "Per-account format", "Other options of show are accepted and
  change nothing"; R-LEGACY "Folders and save", "A connector kind other than gmail".
  Evidence: `ConnectorReadCall` tests for the default call, the tool from the configuration, the id unchanged (case, spaces, quote, non-ASCII, JSON text), empty id exit 2, per-account format, other options of `show`, and the legacy documents of `folders`, `save` and another kind pass.
- [x] 4.2 `--full-content` on `show` and `thread` (store-true; wins over `connector.read_format`; a usage error on an account that
  is not a connector account, before any backend is touched). Check: R-HTML "Full content only on request", "The flag wins over
  the setting", "The flag on another backend", "No option for the cheap reads".

## 5. Interface text and contract
  Evidence: `test_full_content_only_on_request`, `test_the_flag_wins_over_the_setting`, `test_the_flag_on_another_backend_is_a_usage_error` (exit 2, nothing read, cache absent) and `test_no_option_selects_the_cheap_reads` pass.

- [x] 5.1 `--help` of `global/scripts/mailbox`: the section "Connector accounts" (the three settings and their values, defaults,
  the cap and `paging`, `--full-content`, the identity-check view, exit codes) and `[--full-content]` in the `show` and `thread`
  usage lines. `global/contracts/mailbox.yaml`: a probe that `--help` contains `page_size_max`. Check: the `Contract` test of
  `test_mailbox` runs every probe; `python3 scripts/validate-toolkit.py` 0 errors.

## 6. Self-test and tests
  Evidence: `--help` has the section and the usage lines; contract probe `help documents the connector page-size setting` added; `Contract.test_every_probe_passes` OK; `python3 scripts/validate-toolkit.py`: 0 error(s), 0 warning(s).

- [x] 6.1 `mail_selftest.py`: connector checks for the default view and format, the cap and its notice, the id in `arguments`,
  the whoami view, an invalid value refused with exit 2, the refusal of `--header`, and no `mcp__` or UUID shape in any
  connector output. The checks compare with literal values, not with the module constants, so a drifted constant fails them.
  Check: R-TEST "Self-test passes"; `python3 global/scripts/mailbox self-test` prints `self-test: ok`, exit 0.
  Evidence: `python3 global/scripts/mailbox self-test` prints the new connector checks and `self-test: ok` (exit 0); they compare with literals, not the constants.
- [x] 6.2 Piece tests for every scenario of the spec not already covered by tasks 2 to 4, including R-ID "No identifier in any
  output" (every connector command, default settings and all three settings overridden), R-TEST "The header filter is still
  refused", and the "Self-test notices a drift" scenario (the default view constant changed in the test process makes the
  self-test exit 1). Check: each scenario of both spec files maps to a named test; list the mapping in the evidence.
  Evidence (scenario to test): R-VIEW, R-PAGE, R-NOTICE -> `ConnectorSearchCall`; R-READ, R-HTML, R-LEGACY -> `ConnectorReadCall`, `ConnectorCompatibility`; R-WHOAMI -> `ConnectorWhoami`; R-CFG, R-UNUSABLE, R-ID -> `ConnectorSettings`; R-TEST drift -> `ConnectorSelfTestDrift` (default view or format changed in the process: self-test exit 1 naming the failed check); R-TEST header filter -> `ConnectorSearchCall.test_the_header_filter_is_still_refused`; R-KEEP -> `ConnectorCompatibility`, `CompatibilityLocal`, `CompatibilityImap`.
- [x] 6.3 The existing `test_a_server_identifier_is_never_printed` and the reserved-address test of the files list stay green and
  cover the new output (the files list already names `mail_connector.py`, `mail_selftest.py`, `test_mailbox.py`). Check: both pass.

## 7. The skill
  Evidence: `Connector.test_a_server_identifier_is_never_printed` and `Neutrality.test_only_reserved_addresses_hosts_and_no_home_paths` pass (271 tests of the two modules OK).

- [x] 7.1 `global/skills/cuentas-externas/SKILL.md`, step 3: replace words, add no paragraph (design D10). Count the body before
  and after with the same regex as `test_the_skill_body_is_short_and_names_no_host_address_or_credential_path` and write both
  numbers in the evidence of this task (before: 1 862 characters, whole file 2 428; after must be at most 1 862). Check: the
  existing size and neutrality test passes; the connector step names `search`, `show`, `thread`, `tool`, `arguments`, `whoami`
  and `--sender`; R-SKILL "Wording" and "Size".

## 8. Compatibility of the whole module
  Evidence: body 1 862 characters before (file 2 428), 1 861 after (file 2 427), same regex as the test; `Neutrality.test_the_skill_body_is_short...` passes.

- [x] 8.1 R-KEEP: the `imap` and `local` compatibility tests of `mailbox-search-gaps` (`CompatibilityLocal`,
  `CompatibilityImap`) pass untouched. Check: the module tests of `test_mailbox` and `test_access_helpers` pass with the counts
  recorded (233 before this change; the count after is the evidence).

## 9. Verification
  Evidence: `python3 -m unittest scripts.toolkit.tests.pieces.test_mailbox scripts.toolkit.tests.pieces.test_access_helpers`: 271 tests OK (233 before this change, 38 added); `CompatibilityLocal` and `CompatibilityImap` untouched.

- [x] 9.1 Shapes against the connector's published schema, offline: a test that parses the documents printed for every
  combination of configured view, format and cap and asserts each value is in the tuples of design D6 and `arguments` has no
  other key. Check: passes. (No real connector call here; the live shape check is task 10.1.)
  Evidence: `ConnectorSettings.test_every_combination_prints_only_known_values_and_no_other_key` (4 views x 4 formats x 3 maxima) passes.
- [x] 9.2 `openspec validate mailbox-connector-call-shape --strict` valid; `python3 scripts/privacy-check.py` reports 0 findings
  on what is written (the script takes no path: it checks the tracked and staged files, so run it after the files are added,
  and `--staged --require-private` after the last `git add`, without staging the state file `RUN-LOOP.md`). Check: both exit 0.
  Evidence: `openspec validate mailbox-connector-call-shape --strict` valid; `python3 scripts/privacy-check.py` 0 findings; `--staged --require-private` 0 findings with the change files staged (RUN-LOOP.md not staged), unstaged afterwards.
- [x] 9.3 Local gates of the repository: `python3 -m unittest scripts/test_validate_toolkit.py`,
  `python3 scripts/validate-toolkit.py`, `python3 -m unittest scripts/test_privacy_check.py`, and the module tests of this piece.
  Check: all exit 0, counts recorded.
  Evidence: `python3 scripts/validate-toolkit.py` 0 errors; `python3 -m unittest scripts/test_validate_toolkit.py scripts/test_privacy_check.py` 81 tests OK; module tests 271 OK.
- [x] 9.4 `bash examples/override-full/try.sh` with the module on: the `mailbox` probes (including the new one) and the
  self-test pass. Check: every `access` step passes (steps of other modules are not this change's).
- [x] 9.5 The documents are consistent with the code: `--help`, spec, design D6 and the shipped defaults name the same values.
  Check: a grep of the five names (`THREAD_VIEW_SUMMARY`, `PLAIN_TEXT`, `page_size_max`, `search_view`, `read_format`) shows the
  same set in spec, design and `--help`.
  Evidence: grep of the five names: present in spec, design D6, `--help` and `mail_connector.py`; the value lists in `--help` and the spec agree.
  Evidence: `bash examples/override-full/try.sh` exit 0: every step passed, including `contract probes of every installed piece (verify)` (the new `page_size_max` probe) and the self-tests.
- [x] 9.6 [prod-verify] Full test discovery (`python3 -m unittest discover -s scripts/toolkit/tests -t .`) is green in CI on the
  pushed branch, checked before the branch is integrated (as task 7.6 of `external-access`).
  Evidence: Done: the `Validate toolkit` workflow, which runs the full discovery, was green on the pushed branch head `16001b3` and again on the pull request to `main`.

## 10. The installed side

- [x] 10.1 [prod-verify] Supervisor, after install: with the installed `mailbox`, run `mailbox search`, `show`, `thread` and `whoami` on a
  configured connector account, pass each printed `tool` and `arguments` verbatim to the live mail connector of the session
  (the `paging` key is not part of `arguments`), and record only shapes and counts (no sender, subject or body): that the
  connector accepts each call, the number of messages per thread returned with the default view, with `--limit 200` that one
  page of at most 50 threads returns and what the response offers to continue (a page token if it carries one), the keys of the
  `messageFormat` `PLAIN_TEXT` read, and that `whoami`'s result still carries each message's sender. Check: the connector accepts
  every printed call without an argument error, and the recorded shapes match the proposal's "Why".
  Evidence (the build checked was the one merged to `main` as `067b968`; shapes and counts only):
  - `search` with a text filter and `--limit 3`: call accepted; 3 threads, one message per thread; thread keys `id`,
    `messageCount`, `messages`; message keys `id`, `sender`, `subject`, `threadId`, `toRecipients` (no snippet, no date in the
    summary view); top-level keys `resultCountEstimate`, `threads`.
  - `search` with a date filter and `--limit 200`: the printed call asked for `pageSize` 50; accepted; exactly 50 threads
    returned, one message each; `resultCountEstimate` far above the page size; the response carried no page token key at all.
    Two extra diagnostic calls with `pageSize` 1 (`THREAD_VIEW_IDS_ONLY`, and the connector's default view) carried none either.
  - `show` and `thread` with a real thread id: the printed `get_thread` call (`messageFormat` `PLAIN_TEXT`) was accepted; thread
    keys `id`, `messageCount`, `messages`, `viewUrl`; message keys `addressDisplayNames`, `date`, `historyId`, `id`,
    `internalDate`, `labelIds`, `plaintextBody`, `sender`, `sizeEstimate`, `snippet`, `subject`, `threadId`, `toRecipients`,
    `viewUrl`; no `htmlBody`.
  - `whoami`: the printed call was accepted; one thread with one message carrying `sender`; `mailbox whoami <account> --sender
    <address>` then confirmed the account (exit 0).
  - The missing page token was registered as gap G-29 and fixed in this iteration (group 11).

## 11. Paging hint after the live check (gap G-29)

- [x] 11.1 `paging.how` true with and without a page token: `mail_connector.search_document` prints one compact sentence (a
  page token: repeat the call adding it as `pageToken`; none: narrow the search with a shorter `--since`/`--until` range or
  another filter and run `mailbox search` again; `resultCountEstimate` estimates how many results match). Additive: every key stays,
  `continue_with` stays `"pageToken"`, exit codes unchanged. Spec R-NOTICE, design D3, proposal, `--help` and the self-test
  say the same; the skill is untouched (its size test still holds). Check: R-NOTICE "Cap stated" and "The hint holds with and
  without a page token".
- [x] 11.2 A test pins that the capped `how` mentions the page token case and the narrowing case (`pageToken`, `narrow the
  search`, `--since`, `resultCountEstimate`), is shorter than 300 characters, and that a search within the maximum has no `how`
  (`ConnectorSearchCall.test_the_notice_is_outside_the_arguments_and_always_present`). Check: the module tests pass.
