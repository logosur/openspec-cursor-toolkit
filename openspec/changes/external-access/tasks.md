# Tasks — external-access

Each task ends with its own check. A task is done when its check passes in a temporary home; nothing here reads the developer's real mailboxes or keys except 7.2 and 7.3.

## 1. Shared helpers (`global/scripts/lib/access/`)

- [ ] 1.1 `output.py`: exit codes, single-line clipping, bounded list printing with a total, JSON mode, one-line failure. Check: unit tests.
- [ ] 1.2 `settings.py`: load a config piece over its defaults without raising on a broken file, look up an account or app, check that a file is private, parse an env-style file, private cache directory. Check: unit tests, including a file readable by others.

## 2. `mailbox` — local backend

- [ ] 2.1 Resolver: profile root, profile, account folder, role folders, folder listing. Check: tests with two profiles, a renamed inbox next to an empty old one, and an account absent from every profile.
- [ ] 2.2 Index: header-only, incremental, rebuilt after compaction, both store formats, deleted flag skipped where present, duplicates listed once, modes 0700 and 0600. Check: tests that append, truncate, rewrite and flag in place a synthetic mbox of each format.
- [ ] 2.3 Message reading: encoded headers, plain and HTML bodies, quote stripping, attachment listing and saving with safe names. Check: tests on synthetic multipart messages.
- [ ] 2.4 Subcommands on the local backend: `accounts`, `folders`, `search`, `show`, `thread`, `save`, `where`, `doctor`. Check: command-level tests on the synthetic profile, including the default bounds and a message without a date.

## 3. `mailbox` — IMAP backend

- [ ] 3.1 Read-only session, server-side search, header and body fetch, folder roles from the server's folder list. Check: a recording fake proves the read-only select, the peek fetch and the absence of every writing command.
- [ ] 3.2 Credentials file checks and the 30-minute memory of an authentication failure. Check: tests for a file readable by others, a missing variable, a rejected login followed by a second run that does not connect.
- [ ] 3.3 Ordered fallback and the line that names the answering backend. Check: test with `imap` unavailable and `local` present; test with `--backend`.

## 4. `mailbox` — connector accounts

- [ ] 4.1 Filter translation to the connector's query language, delegated output with exit 10, `whoami` with and without `--sender`. Check: tests for each filter and for a mismatching sender.

## 5. `stores`

Order: 5.1, then what works without a key (5.4 and the `apps`, `url`, `doctor` parts of 5.2 and 5.3), then the API reads.

- [ ] 5.1 `http.py` and `store_auth.py`: both signing algorithms through `openssl`, the DER-to-raw conversion of the elliptic-curve signature, token exchange, token lifetime. Check: signatures verify against the public key of a key pair generated in the test; the elliptic-curve signature segment is exactly 64 bytes.
- [ ] 5.2 Google Play provider: `doctor`, `apps`, `tracks`, `reviews`, `listing`, `url`. Check: tests against a loopback server that records every request; the allow-list test of the read-only requirement.
- [ ] 5.3 App Store Connect provider: `doctor`, `apps`, `versions`, `builds`, `review`, `url`. Check: same.
- [ ] 5.4 `public` for both providers. Check: tests against the loopback server for 200, 404 and an empty lookup, with no key configured.

## 6. Module wiring and skill

- [ ] 6.1 `global/modules/access.yaml`, shipped config defaults, contracts with `self-test` and corrupt-config probes, `README.md` module table, `CLAUDE.md` module list, `examples/override-full/` with the module on and example values on reserved domains. Check: `python3 scripts/validate-toolkit.py` and `bash examples/override-full/try.sh`.
- [ ] 6.2 Skill `cuentas-externas`. Check: the size and neutrality test of the mailbox spec.
- [ ] 6.3 Cold check: an agent started in an unrelated directory, given only a question about past correspondence, reaches the answer through the skill. Check: its transcript shows the skill and at most a handful of commands.

## 7. Verification

- [ ] 7.1 Gates: validator tests, validator, privacy tests and check (staged files, commit message, pull-request text), piece tests of this change, full test discovery in CI.
- [ ] 7.2 From the branch, against one real configured mailbox: the same query through `local` and through `imap`, over a date window both cover, returns the same messages (differences are explained by the local copy's age or listed as defects); a deliberately wrong account name exits 2; no secret appears in any output.
- [ ] 7.3 After installing on one machine: both `self-test` pass from the installed copies, `mailbox doctor` and `stores doctor` describe the machine truthfully.
