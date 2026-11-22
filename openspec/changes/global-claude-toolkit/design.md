# Design — global-claude-toolkit

## Context

Facts that shape the design (measured 2026-11-22 on `develop` @ `3517c3b` and on a working `~/.claude`; the itemised inventory is kept outside the repository because it names private things):

| Fact | Evidence |
|---|---|
| Every script and hook resolves its home as `~/.claude` through `HOME` (`expanduser`, `Path.home()`); none reads `CLAUDE_CONFIG_DIR` | grep over 44 executables |
| So a temporary `HOME` reproduces paths faithfully, but **not** everything: `systemctl --user`, the desktop app's session registry under `~/.config/<app>/`, unix sockets and the real heavy-job state live outside `~/.claude` or are shared | audit §5; advisor review |
| A few executables carry a literal home path as a default (one of them is the default root for new git worktrees) | grep `/home/` |
| 22 OpenSpec skills exist both in `.claude/skills/` and globally; the repo copy is the newer, generalised one in each case; the only global skills with later evolution are written around private rules | `diff -rq` per skill, mtimes |
| The supervision scripts form one unit: the session supervisor (8 134 lines, ~500 KB, one file holding lock, census, watcher, end-of-turn hook, backlog, skill lint and self-test) loads the question queue, account switch, heavy-job, project pause and nudger as modules; the nudger and the handoff guard match **Spanish session titles and markers**; the supervisor lints the text of its own skill | call graph in the audit; `SKILL_ANCHORS`, title constants |
| The hook wiring in `settings.json` has 21 entries over 6 events; two point to personal pieces | `jq .hooks` |
| `settings.json` also holds model, theme, permissions, MCP servers, env and app flags: personal or machine state, none of it toolkit | audit of the non-hook keys |
| The authorship gate denies tool calls that write `settings.json` without keeping attribution empty, and its own rule and gate file | gate source |
| The exporter reads copies under an external bundle store, never this repo's `.claude/`; it has no delete logic | `toolkit-catalog-validation` design, Context |
| Public history of this repo already contained some personal references (now removed from the tree) | `scripts/privacy-check.py --range` over `develop` |

## Goals / Non-Goals

**Goals:**
- `./install.sh` turns a machine with Claude Code into one with the toolkit, safely and reversibly.
- The developer's own configuration is reproduced by toolkit + a private override, with every difference explained.
- Nothing personal is ever committed; the check is mechanical.
- Each piece has one responsibility, a small configuration and, when replaceable, a contract.

**Non-Goals:**
- Migrating the live `~/.claude` (described under Migration, done later with the developer's sessions idle).
- Publishing the supervision unit in this change (planned in tasks §8).
- Packaging for Windows or macOS; the toolkit is tested on Linux. Pieces that need Linux-only facilities (`/proc`, cgroups, `systemd --user`, `flock`) declare it in their module.
- Cursor global install (Cursor keeps the per-project export).

## Decisions

### D1. Two sources, no third copy
- `.claude/commands/`, `.claude/skills/`, `.claude/scripts/openspec-list.sh` stay the **only** source of the OpenSpec catalog. The `openspec` module installs them into `~/.claude/{commands,skills,scripts}`. `docs/openspec/` stays project documentation.
- `global/` holds everything else that is installed globally: `CLAUDE.md`, `rules/`, `skills/` (non-catalog), `scripts/`, `hooks/`, `config/` (defaults), `contracts/`, `modules/`.
- `.cursor/` stays the Cursor package, exported per project by `/exporta-spec` as today. Claude Code is the default IDE in every document; Cursor sections come second.
- *Alternative rejected:* moving `.claude/` into `global/` — breaks the paths the catalog documents and the exporter's provenance checks, and buys nothing.

### D2. Modules with a manifest each
`global/modules/<name>.yaml`:
```yaml
name: core
summary: …
requires: {binaries: [python3, git, flock], python: "3.10", os: linux}
optional: {binaries: [gh, jq, docker, node]}
files:            # src (repo-relative) -> dest (relative to the Claude dir)
  - {src: global/scripts/heavy-job, dest: scripts/heavy-job, mode: "0755"}
  - {src: global/rules/, dest: rules/}      # trailing slash = directory
hooks: global/settings/hooks.core.json      # fragment merged into settings.json
config: [heavy-job, worktree-location]      # pieces with a config file
depends: []                                 # other modules
```
Modules today: `openspec` (catalog from `.claude/`), `core` (general mechanics). Planned: `supervision`. A file belongs to exactly one module (validator).

### D3. Override directory and precedence
`$CLAUDE_TOOLKIT_OVERRIDE`, default `~/.config/claude-toolkit/`:
```
override.yaml          # schema: 1; modules: [core, openspec]; remove: [...]; excluded: [...]; equivalence: {...}
config/<piece>.json    # values for one piece
files/<dest>           # replaces the toolkit file at <dest>, or adds a new piece
append/<dest>          # appended to the toolkit file at <dest> (texts)
hooks/*.json           # extra hook fragments (same shape as settings "hooks")
privacy-denylist.txt   # private terms for the privacy guard
override.lock.json     # toolkit hash each replaced file was based on (written by tooling)
```
Precedence, highest first:
1. **Files:** `override/files/<dest>` > toolkit file + `override/append/<dest>` > toolkit file. `remove:` drops a toolkit destination (and its hooks).
2. **Values:** environment `CLAUDE_TOOLKIT_CONFIG_DIR` (tests only) > `override/config/<piece>.json` > `global/config/<piece>.json` > defaults in the code. Merge is a shallow key merge per piece.
3. **Hooks:** toolkit fragments of enabled modules + override fragments; an override fragment may also disable a toolkit entry with `"disabled": true` on the same (event, matcher, command).

The override never lives in this repository. Versioning it in a private repository is prepared (`examples/override/README.md`), not done: creating a remote repository on the developer's account is the developer's call.

### D4. Configuration per piece, read through one helper (DIP, ISP)
- The installer resolves each piece's configuration and writes it to `~/.claude/toolkit/config/<piece>.json`.
- Python pieces read it with `global/scripts/lib/toolkit_config.py` → `load(piece, defaults)`, which returns `defaults` overlaid with the file if present. Shell pieces call `toolkit_config.py get <piece> <key>`.
- Each piece reads **only its own file**; there is no global settings object.
- The code keeps generic defaults equal to `global/config/<piece>.json`, so a piece copied without the installer still behaves generically.
- *Alternative considered:* rendering placeholders into files at install time. It would make the developer's install byte-identical to the live tree, but scripts would not be runnable from the repo, a value change would need a reinstall, and a placeholder inside code is a dependency on the installer. Rejected in favour of runtime injection; the equivalence check explains the resulting differences (D9).

### D5. Contracts for replaceable pieces (LSP)
`global/contracts/<piece>.yaml` for every hook and every script another piece calls:
```yaml
piece: heavy-job-gate
kind: hook                    # hook | cli
event: PreToolUse
probes:
  - name: unrelated command passes
    stdin: {tool_name: Bash, tool_input: {command: "ls"}}
    exit: [0]
    stdout: empty-or-json
```
`toolkit verify` runs every probe against the installed file (toolkit or override) in a sandbox `HOME`. An override that replaces a piece must pass its probes; the installer refuses to finish (`install` exits 3) when a replacing piece fails, unless `--allow-contract-failures`.

### D6. Installer
`./install.sh [install|uninstall|status|verify|drift|equivalence] [--dry-run] [--target DIR] [--override DIR] [--modules a,b]` → `python3 -m scripts.toolkit …` (package `scripts/toolkit/`, one module per responsibility: `plan`, `apply`, `settings_merge`, `config`, `contracts`, `drift`, `equivalence`, `deps`).
- **Target:** `--target`, else `$CLAUDE_CONFIG_DIR`, else `~/.claude`.
- **Plan first:** every run computes the full list of actions (create, update, unchanged, backup, remove, hook add/remove); `--dry-run` prints it and exits 0.
- **Backups:** a destination that exists with different content is copied to `<target>/backups/toolkit-<timestamp>/<dest>` before being overwritten.
- **Manifest:** `<target>/toolkit/installed.json` (schema, version, modules, every file with source and sha256, every hook entry added, the backup dir).
- **Idempotent:** a second `install` with the same inputs plans only "unchanged".
- **Uninstall:** removes each manifest file whose hash still matches what was installed (a file edited since is kept and reported), restores the backups, removes the hook entries it added, deletes the manifest. User files never touched by the installer are never removed.
- **Dependencies:** checked before writing; missing required binary → exit 2 with the list; missing optional → warning naming what will not work.
- **No services:** the installer writes no systemd units or crontab entries. A piece that needs a timer documents the command in its module (`post_install` notes are printed, never executed).

### D7. settings.json merge
- Only the `hooks` key is merged. Every other key is preserved byte-for-byte in value (the file is re-serialised with 2-space indent).
- An entry's identity is `(event, matcher, command)`. Missing entries are appended to the event list; present ones are left alone. Added entries are recorded in the manifest; uninstall removes only those, and only if still present unchanged.
- Write is atomic (temp file + rename) after a backup. A `settings.json` that does not parse aborts the install (exit 2) without writing.

### D8. Privacy guard
Implemented first (commits `a260a29`, `6ddc3a5`, `c2df1a1`): `scripts/privacy-check.py`, `scripts/privacy-patterns.yaml` (generic), `scripts/privacy-allow.yaml` (declared exceptions with reasons), private denylist and private quotes read from the override. Scopes `--staged`, `--message`, `--range`. Private findings print only the entry number. CI runs the generic layer; contributors run `--require-private` before each commit. `toolkit pull --to toolkit` runs it and refuses on findings.

### D9. Sync, drift and equivalence
- **drift:** build the install plan for the live target (no writes) and compare with the live files: `in-sync`, `live-changed` (someone edited the installed file), `toolkit-changed` (a newer toolkit not yet installed), `override-base-changed` (the toolkit file under an override replacement changed since the override was made, per `override.lock.json`), `untracked` (live file no module or override owns, after `excluded:` globs).
- **pull `<dest>` `--to override|toolkit`:** copies a live file into `override/files/` (default; private) or into its toolkit source (only if the privacy guard passes on the new content). Updates `override.lock.json`.
- **equivalence `--live DIR`:** installs into a fresh temporary `HOME`, then compares the managed scopes (`CLAUDE.md`, `rules`, `rules-detail`, `skills`, `commands`, `agents`, `scripts`, `hooks`, `scheduled-tasks`, the `hooks` of `settings.json`) with the live tree. Each path gets exactly one class:
  - `identical`;
  - `override` (comes from `override/files`, so it equals the live file by construction);
  - `toolkit-newer` (OpenSpec catalog file whose repo version supersedes the live one);
  - `injected` (toolkit file whose live twin hard-codes values now read from config; proven by the piece's tests passing with the override's config);
  - `neutral-text` (toolkit text with personal narrative removed; the live literal is not needed at runtime);
  - `excluded` (declared in `override.yaml: excluded`: runtime state, backups, caches, third-party, app-managed);
  - `unexplained` → the check fails.
  The report gives counts per class and the share of managed files that come from the toolkit vs the override, so a check that passes only because the override copies everything is visible.

### D10. Scope of `core` in this change
A piece enters `core` only if (a) its general version passes the privacy guard, (b) its tests or self-test pass from the repo copy installed in a temporary `HOME`, and (c) it does not depend on the supervision unit at runtime (falling open is acceptable). Candidates from the audit: authorship gate, process-kill gate, heavy-job and its gate, worktree placement and its gate, port leases, test accounts, the question queue CLI, unattended-deploy and its gate, Docker Desktop restart gate, context gate and checker, `CLAUDE.md` bootstrapper, authorship history rewriter, design-check (without `node_modules`), the decision-panel skill, and neutral versions of the general rules. A candidate that fails a criterion stays in the private override and is listed in the final report.

### D11. Supervision unit: why it waits, and the plan
The unit (session supervisor, nudger, handoff guard, project pause, account switch, cloud tests, routines engine, question-queue prompt hook, cross-project gate, start-session gates, the supervision skills and the rules written around them) is published only as a whole, because its pieces load each other, match Spanish titles and markers as protocol, and the supervisor lints its own skill's text. Publishing a neutralised skill with unchanged matchers would break it silently. Tasks §8 carry the plan and acceptance criteria: protocol strings to config, split of the supervisor into modules behind the same CLI, neutral skill and rules, self-tests green from the repo copy, equivalence green.

### D12. What never enters the repo
Third-party skills and plugins (listed in README as optional), skills of client origin or uncertain authorship, personal pieces (routines, project-specific scripts and hooks, account and machine rules), runtime state (`state/`, `supervisor/`, `routines/`, `projects/`, `sessions/`…), credentials and tokens, backups and caches.

## Changes after the advisor review (before implementation)

- **Privacy guard:** the private layer can no longer be allowlisted; file names and symlink targets are checked; dated-order patterns cover the comma forms and day-first dates; literal texts are copied into the private override **before** any neutral text is written, so the private-quote layer is active while neutral versions are produced (task 7.4 runs before 5.2).
- **Sandbox:** a piece is executed (probes, self-tests) only when `HOME` is a temporary directory and the target is `$HOME/.claude`; `--target` alone never isolates, because pieces resolve `~/.claude` through `HOME`. `equivalence` compares files and never executes pieces.
- **Catalog layout:** the OpenSpec CLI skills grouped under `.claude/skills/openspec/<name>/` are installed flattened as `skills/<name>/`, as the live tree has them. `docs/openspec/` is installed as `docs/openspec/` in the Claude dir so the paths the skills cite exist; the validator's dependency closure covers those citations.
- **Equivalence classes need proof:** `toolkit-newer` only when the live file equals some historical version of its repo source (else it must be declared as a behaviour change on migration, with a reason); `neutral-text` for Python only when the AST without docstrings is equal; anything else is `injected` and must name the test that proves it.
- **Installer details:** hook identity normalises a leading interpreter (`python3 `) and `~`/`$HOME`; a second install keeps the first backup, so uninstall restores the original; a `CLAUDE.md` not written by the toolkit is not replaced: the toolkit text goes in a managed block between markers, unless the override replaces the whole file; symlinks are never installed (live symlinks are declared exclusions); a piece with a missing or corrupt config falls back to its defaults, and a probe checks it.
- **Scope of `core`:** evaluated piece by piece, not by excluding everything near supervision; the start-session gates, the duplicate-chip gate and the question-queue CLI are autonomous and tested, so they are candidates.
- **Order:** a vertical slice first (installer, override, hook merge, equivalence, with `openspec` and two or three autonomous pieces), then `core` grows.

## Changes during implementation

- **A third module, `devtools`** (port-lease, test-account and their rules), split from `core` so `core`
  stays the guard rails only (SRP); it depends on `core` for the config helper. Default modules:
  `openspec, core, devtools`, defined once in `scripts/toolkit/modules.py`.
- **A fourth module, `sessions`**: the two desktop-app session guards (born-in-bypass and duplicate
  proposal cards). Neither calls the supervisor's lock or question queue, so they meet D10 (a) and (c)
  and ship now, with contracts, instead of waiting for the supervision unit.
- **Override files the toolkit already provides** are kept in the override only when they differ from
  the toolkit and are not an earlier version of it; the rest moved to the override's `archive/`. An
  install therefore reproduces the live dir exactly (evidence/equivalence.md) and reconciling the 43
  differing files is left to `drift`/`pull`, file by file.
- **Probes take raw stdin** (`stdin_raw`), so a contract can test unparseable input. A probe found that
  the authorship gate exits 1 on valid JSON that is not an object; the gate is edited only by its
  owner by hand, so it is recorded (core-scope.md) and not changed.

## SOLID

| Principle | How the toolkit meets it | Where it is violated today (audit) and the fix |
|---|---|---|
| **Single responsibility** | One executable per job; the installer split into `plan`/`apply`/`settings_merge`/`config`/`contracts`/`drift`/`equivalence`/`deps`; module manifests only declare, the installer only executes; rules state a policy, scripts enforce it | The session supervisor is one ~500 KB file doing lock, census, watcher, end-of-turn hook, backlog, skill lint, cloud dispatch and self-test → split into a package (`lock`, `census`, `watch`, `hook`, `backlog`, `lint`, `cloud`, `selftest`) behind the same `supervisor-lock <subcommand>` entry point (tasks §8). `heavy-job` mixes classifier, queue and orphan scan → classifier extracted as a library the gate imports (it already loads it via `SourceFileLoader`; tasks §8) |
| **Open/closed** | New behaviour arrives as override files, appendices, extra hook fragments or new modules; no toolkit file is edited to personalise | Personal values and lists inside general scripts (excluded projects, profiles, hostnames) → per-piece config (D4) |
| **Liskov substitution** | A replacement must honour the piece's contract; `verify` probes it (D5) | Implicit contracts (session titles, markers, duplicated windows and lists across two files) → written down in `contracts/` and, for supervision, moved to one config (tasks §8) |
| **Interface segregation** | One small config file per piece; each piece reads only its own; contracts per piece | A single `settings.json` carries everything; the toolkit merges only `hooks` and never reads the rest. Shared constants duplicated in several files (app registry glob in six files, excluded-project list in three) → one config key per owning piece, others call the owner (tasks §8) |
| **Dependency inversion** | Pieces depend on `toolkit_config.load()` and on contracts of the scripts they call (path through config, e.g. `HEAVY_JOB_BIN`), never on a machine's paths, hosts, project names, models or thresholds | Literal home paths as defaults, a hostname-specific slot count, a hard-coded host and key name, literal model ids → config keys with generic defaults |

## Risks / Trade-offs

- **Runtime config means the developer's installed scripts differ from today's files.** Mitigation: equivalence class `injected` requires the piece's tests to pass with his config.
- **A temporary `HOME` does not isolate everything** (systemd, desktop-app files, sockets, real heavy-job state). Mitigation: no installer step touches systemd; self-tests that talk to the app or sockets are run only after checking they redirect every path, otherwise they are reported as not run; suites run through the real heavy-job outside the sandbox.
- **The authorship gate protects `settings.json`.** The merge preserves everything the gate protects: attribution keys stay untouched and the gate's own hook entry is never removed. The developer's real file is not written in this change.
- **Override drift:** replaced files freeze the toolkit version they came from. Mitigation: `override.lock.json` + `drift` state `override-base-changed`.
- **Spanish texts.** The toolkit's user-facing texts are Spanish where the source is; code, identifiers and docs are English. Translating is out of scope.
- **History.** Personal references already published in this repo's history stay there; rewriting public history is the developer's decision (queued).

## Migration Plan (next step, not in this change)

1. Stop or idle the sessions that use the live `~/.claude` (the supervisors).
2. `./install.sh install --dry-run` against the real target with the developer's override; review the plan (backups listed).
3. `./install.sh install`; `./install.sh verify`; `./install.sh drift` must report only `in-sync` and declared exclusions.
4. Keep the old tree's backup; roll back with `./install.sh uninstall` if anything misbehaves.

Consumers of the per-project catalog: nothing to do. A project with project-level copies of the OpenSpec skills may delete them after installing the global toolkit; project-level skills take precedence in that project, so stale copies would shadow the global ones.

## Follow-ups (not in this change)

- Tasks §8 (supervision unit).
- Optional: a `pre-commit` hook in this repo that runs the privacy guard (`core.hooksPath` changes are the developer's).
- Optional: translations of user-facing strings.
