# Tasks — global-claude-toolkit

Requirement references: **GI** = `specs/global-install`, **OL** = `specs/override-layer`, **PG** = `specs/privacy-guard`, **TS** = `specs/toolkit-sync`, **CV** = `specs/catalog-validation`. Design decisions **D1**–**D12**. Every task ends with its own check; the next one starts only after it passes. Heavy suites run through the machine's heavy-job semaphore.

## 1. Privacy guard first (PG, D8)

- [x] 1.1 `scripts/privacy-check.py` + `scripts/privacy-patterns.yaml` (generic only) + tests; verify `python3 -m unittest scripts/test_privacy_check.py` passes.
- [x] 1.2 Private denylist in the local override (never committed); verify `--require-private` exits `2` without it and finds the known personal references in the old tree.
- [x] 1.3 Remove personal references from the current tree in a commit of its own; verify `privacy-check.py --require-private` → 0 findings.
- [x] 1.4 CI runs the privacy tests and the generic layer; verify the workflow file lists both steps.
- [x] 1.5 Declared exceptions with reasons (`scripts/privacy-allow.yaml`); verify the test for a reason-less entry aborts.

## 2. Plan (this change)

- [x] 2.1 Audit `~/.claude` read-only; inventory kept outside the repo; counts in proposal.
- [x] 2.2 Proposal, design (with SOLID), specs and tasks; verify the privacy guard passes on them.
- [ ] 2.3 Advisor review before implementation; record changes made because of it in design.

## 3. Installer package (GI, D6, D7)

- [ ] 3.1 `scripts/toolkit/` package skeleton + `install.sh` entry; `status` with an empty target; verify `./install.sh status --target <tmp>` exits `0`.
- [ ] 3.2 Module manifests loader + validation of `files`, `hooks`, `config`, `requires`; verify tests for a missing source and a duplicate destination.
- [ ] 3.3 Plan builder (create/update/unchanged/backup, hooks) and `--dry-run`; verify the dry-run test writes nothing.
- [ ] 3.4 Apply with backups, modes and manifest; verify fresh-install, re-run (idempotent) and existing-file-backup tests.
- [ ] 3.5 settings.json merge (`hooks` only, identity triple, atomic write, parse error → exit 2); verify the user-keys-survive and broken-settings tests.
- [ ] 3.6 Uninstall (hash-matched removal, backup restore, hook removal); verify the round-trip and edited-file tests.
- [ ] 3.7 Dependency checks (required → exit 2, optional → warning); verify with a fake `PATH`.

## 4. Override layer and config (OL, D3, D4, D5)

- [ ] 4.1 Override resolution (`--override`, env, default) and `override.yaml` schema; verify the no-override test.
- [ ] 4.2 File precedence: replace, append, extra piece, remove (and hooks of removed pieces); verify one test per rule.
- [ ] 4.3 Config resolution per piece written to `toolkit/config/<piece>.json`; `global/scripts/lib/toolkit_config.py` with `load()` and `get` CLI; verify override-value and no-config tests.
- [ ] 4.4 Contracts + `verify` probes in a sandbox `HOME`; `install` exit `3` for a failing override piece; verify the faithful and broken replacement tests.
- [ ] 4.5 `examples/override/` with README (private versioning steps, no remote created); verify `install --override examples/override` works.

## 5. Modules content (D1, D2, D10)

- [ ] 5.1 `openspec` module pointing at `.claude/` (commands, skills, `openspec-list.sh`); verify install lists every catalog file once.
- [ ] 5.2 `core` scripts and hooks: neutral version + per-piece config for each candidate in D10; for each piece verify (a) privacy guard 0, (b) its tests/self-test pass from the repo copy installed in a temp `HOME`, (c) no runtime dependency on supervision. Pieces failing a criterion stay in the override and are listed in `evidence/core-scope.md`.
- [ ] 5.3 `core` rules and global `CLAUDE.md`: neutral texts (no quotes, dates of orders, projects, hosts); verify privacy guard 0 and that every rule cited by a core piece exists.
- [ ] 5.4 `core` skills (decision panel, neutral); verify validator routing rules pass for them.
- [ ] 5.5 Hook fragment `global/settings/hooks.core.json` and contracts for every core hook and called script; verify `verify` passes on a fresh install.

## 6. Validator (CV)

- [ ] 6.1 Global-tree checks: every manifest source exists, each file in `global/` belongs to exactly one module, hook fragments point to installed destinations, contracts exist for hooks, dependency closure of cited rules/scripts/skills; one passing and one failing test each.
- [ ] 6.2 Run `python3 -m unittest scripts/test_validate_toolkit.py && python3 scripts/validate-toolkit.py`; verify 0 errors.

## 7. Sync, drift, equivalence (TS, D9)

- [ ] 7.1 `drift` states incl. `override-base-changed`; verify tests per state.
- [ ] 7.2 `pull --to override|toolkit` with the privacy gate; verify private-by-default and refused-publication tests.
- [ ] 7.3 `equivalence` with classes and shares; verify all-explained and unexplained tests.
- [ ] 7.4 Developer override prepared in `~/.config/claude-toolkit/` from the live tree (personal pieces, literal rules, supervision unit, config values, exclusions); verify the private denylist covers every private name it introduces.
- [ ] 7.5 Run `equivalence --live ~/.claude` (read-only on the live tree); save the counts to `evidence/equivalence.md` (paths of private pieces summarised by class, never named); verify 0 `unexplained`.

## 8. Supervision unit (planned; acceptance criteria, not done in this change unless all hold)

- [ ] 8.1 Protocol strings (session titles, markers, watched rule names, skill anchors, app registry glob, claim windows, excluded-project list) moved to one config piece `supervision`; accept when every duplicate constant is read from it and the existing self-tests pass unchanged.
- [ ] 8.2 Split the session supervisor into a package (`lock`, `census`, `watch`, `hook`, `backlog`, `lint`, `cloud`, `selftest`) behind the same `supervisor-lock <subcommand>` CLI; accept when `supervisor-lock self-test` and every test that loads it pass from the repo copy, the CLI help lists the same subcommands, and equivalence stays green.
- [ ] 8.3 Extract heavy-job's command classifier into a library used by its gate; accept when both test files pass.
- [ ] 8.4 Neutral versions of the supervision skill, its references and the rules written around it (quotes and incidents stay in the override as appendices); accept when the privacy guard is 0, the supervisor's skill lint passes on the neutral text, and equivalence is green with the literal text in the override.
- [ ] 8.5 Self-tests that use the desktop app's files or sockets run only after checking every path is redirected into the sandbox; accept when that check is written down per test.
- [ ] 8.6 `supervision` module manifest + contracts; accept when `verify` passes on a fresh install with and without the override.

## 9. Docs and close

- [ ] 9.1 `README.md` (English): global toolkit, Claude Code default, install, override, privacy, sync, migration, Cursor as secondary, what is left out and why; verify the privacy guard and the validator's README coverage.
- [ ] 9.2 `CLAUDE.md` of the repo: new invariants (two sources, modules, override outside the repo, privacy guard before every commit, validator); verify privacy guard 0.
- [ ] 9.3 Final run: all tests, validator, privacy guard on tree and on the branch range; commits on the change branch only (integration and push wait for the developer's security audit).
