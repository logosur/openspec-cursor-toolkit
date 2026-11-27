# Tasks — external-access

Each task ends with its own check. A task is done when its check passes in a temporary home; nothing here reads the developer's real mailboxes or keys except 7.2 and 7.3.

## 1. Shared helpers (`global/scripts/lib/access/`)

- [x] 1.1 `output.py`: exit codes, single-line clipping, bounded list printing with a total, JSON mode, one-line failure. Check: unit tests.
- [x] 1.2 `settings.py`: load a config piece over its defaults without raising on a broken file, look up an account or app, check that a file is private, parse an env-style file, private cache directory. Check: unit tests, including a file readable by others.

## 2. `mailbox` — local backend

- [x] 2.1 Resolver: profile root, profile, account folder, role folders, folder listing. Check: tests with two profiles, a renamed inbox next to an empty old one, and an account absent from every profile.
- [x] 2.2 Index: header-only, incremental, rebuilt after compaction, both store formats, deleted flag skipped where present, duplicates listed once, modes 0700 and 0600. Check: tests that append, truncate, rewrite and flag in place a synthetic mbox of each format.
- [x] 2.3 Message reading: encoded headers, plain and HTML bodies, quote stripping, attachment listing and saving with safe names. Check: tests on synthetic multipart messages.
- [x] 2.4 Subcommands on the local backend: `accounts`, `folders`, `search`, `show`, `thread`, `save`, `where`, `doctor`. Check: command-level tests on the synthetic profile, including the default bounds and a message without a date.

## 3. `mailbox` — IMAP backend

- [x] 3.1 Read-only session, server-side search, header and body fetch, folder roles from the server's folder list. Check: a recording fake proves the read-only select, the peek fetch and the absence of every writing command.
- [x] 3.2 Credentials file checks and the 30-minute memory of an authentication failure. Check: tests for a file readable by others, a missing variable, a rejected login followed by a second run that does not connect.
- [x] 3.3 Ordered fallback and the line that names the answering backend. Check: test with `imap` unavailable and `local` present; test with `--backend`.

## 4. `mailbox` — connector accounts

- [x] 4.1 Filter translation to the connector's query language, delegated output with exit 10, `whoami` with and without `--sender`. Check: tests for each filter and for a mismatching sender.

## 5. `stores`

Order: 5.1, then what works without a key (5.4 and the `apps`, `url`, `doctor` parts of 5.2 and 5.3), then the API reads.

- [x] 5.1 `http.py` and `store_auth.py`: both signing algorithms through `openssl`, the DER-to-raw conversion of the elliptic-curve signature, token exchange, token lifetime. Check: signatures verify against the public key of a key pair generated in the test; the elliptic-curve signature segment is exactly 64 bytes.
- [x] 5.2 Google Play provider: `doctor`, `apps`, `tracks`, `reviews`, `listing`, `url`. Check: tests against a loopback server that records every request; the allow-list test of the read-only requirement.
- [x] 5.3 App Store Connect provider: `doctor`, `apps`, `versions`, `builds`, `review`, `url`. Check: same.
- [x] 5.4 `public` for both providers. Check: tests against the loopback server for 200, 404 and an empty lookup, with no key configured.

## 6. Module wiring and skill

- [x] 6.1 `global/modules/access.yaml`, shipped config defaults, contracts with `self-test` and corrupt-config probes, `README.md` module table, `CLAUDE.md` module list, `examples/override-full/` with the module on and example values on reserved domains. Check: `python3 scripts/validate-toolkit.py` and `bash examples/override-full/try.sh`. Evidence (2026-11-27, re-run in the P4 confirm review on the final tree): `python3 scripts/validate-toolkit.py` printed 0 error(s), 0 warning(s), exit 0; `bash examples/override-full/try.sh`: install dry run, install, status, contract probes (109 probes, 0 failures, `mailbox` and `stores` included), `test-account` and `process-kill-gate` self-tests, drift, a second install that changes nothing, uninstall and its leftovers check all PASS; the only FAIL is the `supervisor-lock` self-test of the `supervision` module (4 SessionStart re-arm-context checks and one timing check under machine load), a piece this change does not touch (`git diff` shows no file of it), see the note at the end of task 7.1.
- [x] 6.2 Skill `cuentas-externas`. Check: the size and neutrality test of the mailbox spec.
- [x] 6.3 Cold check: an agent started in an unrelated directory, given only a question about past correspondence, reaches the answer through the skill. Check: its transcript shows the skill and at most a handful of commands. [prod-verify] Evidence (2026-11-27, installed copies): a fresh agent started in an unrelated empty directory, given only a question about past correspondence, reached the answer through the skill with a handful of commands.

## 7. Verification

- [x] 7.1 Local gates: validator tests, validator, privacy tests and check (staged files, commit message, pull-request text), piece tests of this change. Evidence (2026-11-27; re-run in the P4 confirm review on the final tree, from the project root): `python3 -m unittest scripts/test_validate_toolkit.py` 59 tests OK, exit 0; `python3 scripts/validate-toolkit.py` 0 error(s), 0 warning(s), exit 0; `python3 -m unittest scripts/test_privacy_check.py` 22 tests OK, exit 0; `python3 -m unittest scripts.toolkit.tests.pieces.test_access_helpers scripts.toolkit.tests.pieces.test_mailbox scripts.toolkit.tests.pieces.test_stores` 262 tests OK, exit 0; `python3 scripts/privacy-check.py --staged --require-private` 0 findings, exit 0 (after the last `git add`). The checks of the commit text and of the pull-request text were run in the previous phase (0 findings) and not re-run here, because this phase has no commit text. Two earlier local attempts at the full discovery were cut by the machine's load (one by a 15 minute timeout, exit 124; one stopped by the orchestrator, exit 143), and neither printed a failing test; they are not counted as evidence, and the full discovery is task 7.6. SUPERVISOR-LOCK NOTE: `bash examples/override-full/try.sh` ends with exit 1 only because the `supervisor-lock` self-test (module `supervision`, untouched by this change) reports 5 failed checks; every step about `access` passes. BASE_NOTE_PLACEHOLDER
- [x] 7.2 From the branch, against one real configured mailbox: the same query through `local` and through `imap`, over a date window both cover, returns the same messages (differences are explained by the local copy's age or listed as defects); a deliberately wrong account name exits 2; no secret appears in any output. Evidence (2026-11-27, real mailbox with both backends, inbox, window 2026-11-24 to 2026-11-26, a limit above both counts): `imap` about two hundred messages, `local` about three hundred; compared message by message on date, other party, subject, attachment mark and direction (the two backends issue ids of different shape and a search result carries no Message-ID): the same set in both, none only in `imap`, a few dozen only in `local`. Those are mail the server no longer holds in the inbox: six other server folders (trash, junk, deleted items, archives, old inbox) searched over the same window held none of them, most of their sending domains never appear in the server's copy of the window, and the two busiest automated senders have a handful of messages on the server against some hundreds in the local copy since a month earlier. Read as deletion or move on the server since download, which the command's own note states. `--folder all` on `imap` adds a single sent message and no further difference. A wrong account name exits 2, so does an unknown `--backend`. Secret check: the password read in-process from the configured credentials file was found 0 times in the captured outputs of every run and in the cache directory.
- [x] 7.3 After installing on one machine: both `self-test` pass from the installed copies, `mailbox doctor` and `stores doctor` describe the machine truthfully. [prod-verify] Evidence (2026-11-27, installed copies): both `self-test` pass from the installed copies and both `doctor` commands describe the machine truthfully; re-checked after a later install the same day.
- [ ] 7.4 With a key granted on one machine: `stores doctor --live` and one read per provider against the real services return what the console shows (tasks 5.2 and 5.3 are proven against the simulated services only). [prod-verify] Not done: waits for a store API key that only the account owner can create.
- [x] 7.5 On the mailbox whose server holds more than 200 folders: `mailbox thread` on a message of a real thread returns from `imap` within the timeout or falls back to `local` on the first output line, and `search --folder sent` opens only sent folders near the top of the tree. Evidence (2026-11-27, same real mailbox, more than 200 folders on the server): the first `thread` of a real reply did NOT answer from `imap`; it fell back to `local` in under two seconds with the first line saying so, because the server refused the search joining nine or more alternatives (probes: 6 alternatives accepted, 9 and 18 refused) - gap G-13, fixed with short searches (`THREAD_OR`), a regression test, spec scenario and design text. After the fix: the same `thread` answered from `imap` (a handful of messages, no fallback) in about a minute on a cold server and a few seconds warm; a second real thread answered from `imap` in under half a minute cold and a couple of seconds warm; no fallback happened in any of these runs. `search --folder sent` on `imap` opened a couple of folders, both at the top level of the tree, listing a few thousand messages; on `local` it read one folder (also a few thousand messages).
- [x] 7.6 Full test discovery (`python3 -m unittest discover -s scripts/toolkit/tests -t .`) is green in CI on the pushed branch, checked before the branch is integrated. [prod-verify] Evidence (2026-11-27): CI run 45946679753 on `b5eb633`, green, checked before `develop` was fast-forwarded.

## 8. Review round 1 (gap analysis against the code of groups 1 to 5)

- [x] 8.1 Privacy check at zero without weakening it: reserved example domain, identifiers and key marker built at run time. Check: `python3 scripts/privacy-check.py --staged --require-private` reports 0.
- [x] 8.2 Bounded thread lookup on `imap` (and role folders by name only within two levels of the tree) and fallback to the `local` index by Message-ID after a failure, first output line says so. Check: tests with the fake server raising a timeout (with and without a `local` backend, and with a message the local copy lacks) and a server with 250 sent-named folders.
- [x] 8.3 Design D2 states what the entry scripts hold; D5 and `--help` state the date-filter semantics on both backends. Check: `openspec validate external-access --strict`.
- [x] 8.4 Robustness: `sqlite3.Error` in `main` is one line and exit 1; C1 control characters are removed from `show` output; the test base restores the time zone after the environment. Check: tests.
- [x] 8.5 `stores doctor` prints no check that depends on a missing key-file prerequisite. Check: doctor tests assert the absent lines.
- [x] 8.6 Contract probes of both pieces hold on any machine configuration and a test runs each contract's probes. Check: `Contract` tests of `test_mailbox` and `test_stores`.

## 9. Review round 2 (P4, confirm review in a fresh context)

- [x] 9.1 `READY-TO-APPLY.md` says what is true about the full test discovery (G-14): not run to completion locally, owned by task 7.6. Check: the section "Verified on this machine" no longer lists it and "Not verified here" names 7.6.
- [x] 9.2 A request that carries credentials never follows a redirect (G-15): the `Authorization` header would reach the new host. Check: `RedirectTest` in `test_stores` (the target server never sees the token; a public page without credentials still follows), spec scenario "A redirect never carries a token", design D8.
- [x] 9.3 A mistyped account setting is a one-line usage error, not a traceback (G-16). Check: `Accounts.test_a_mistyped_setting_is_a_one_line_usage_error_never_a_traceback`, spec scenario "Mistyped setting".
- [x] 9.4 The `folders` bound and the scan caps have scenarios, and the `local` text-scan cap has a test (G-17). Check: `LocalCommands.test_the_text_scan_of_the_local_backend_is_capped_and_says_so`, spec scenarios "Folder listing" and "Scan caps are stated".
