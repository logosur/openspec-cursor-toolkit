# Claude Code toolkit (global, with OpenSpec)

A general toolkit for **Claude Code**, installed once per machine into `~/.claude` and personalised
with a private **override** that lives outside this repository. It bundles:

- the **OpenSpec** workflow catalog: slash commands (`run-spec`, `prepara-tarea`, `opsx-*`,
  `gaps-spec`, `repasa-spec`, …), skills and the `docs/openspec/` templates;
- **guard rails for unattended agent work**: a commit-authorship gate, a gate that only lets a
  session kill its own processes, worktree placement, and a decision panel that replaces questions;
- **local development helpers**: one fixed block of ports per project and a private store of
  test users.

Claude Code is the default target. The original **Cursor** package (`.cursor/`) is still kept in
parity and exported per project, as a secondary target.

**Stack-agnostic:** nothing assumes Drupal, DDEV, Symfony or any framework. Each consuming project
documents its own stack (commands, tests, URLs) in its `CLAUDE.md`; the toolkit reads it at runtime.

## Install on a machine

Needs Linux, Python 3.10+, PyYAML and git.

```bash
git clone https://github.com/<org>/openspec-cursor-toolkit.git
cd openspec-cursor-toolkit
./install.sh install --dry-run     # what would change, nothing written
./install.sh install
```

| Command | What it does |
|---|---|
| `install [--modules a,b] [--override DIR] [--target DIR] [--dry-run] [-v]` | copies the modules' files, writes per-piece config, merges hook entries into `settings.json`; idempotent |
| `uninstall` | removes what the last install wrote (files you edited since are kept), restores the files it replaced, removes its hook entries and its block in `CLAUDE.md` |
| `status` | modules, files and hooks currently installed |
| `verify` | runs each installed piece's contract probes; only inside a sandbox `HOME` |
| `drift`, `pull`, `equivalence` | keep the live dir, the override and the toolkit in sync (see below) |

What the installer guarantees:

- **Only the `hooks` key of `settings.json` is touched**, and an entry that is already there (same
  event, matcher and command) is never duplicated. A `settings.json` that is not valid JSON stops the
  install with exit 2 and nothing written.
- **Every file it replaces is backed up** (`~/.claude/backups/toolkit-<stamp>/`) and recorded in
  `~/.claude/toolkit/installed.json` with its hash, so `uninstall` can put it back.
- Your own `~/.claude/CLAUDE.md` is kept: the toolkit's global rules go in a **managed block**
  between `<!-- claude-toolkit:begin … -->` and `<!-- claude-toolkit:end -->`.
- It never installs symlinks, never touches systemd or the desktop app, and never runs a piece outside
  a throwaway `HOME`. A missing required binary stops it with exit 2; a missing optional one is a
  warning.

## Modules

| Module | Contents |
|---|---|
| `openspec` | `.claude/commands/`, `.claude/skills/`, `openspec-list.sh` and `docs/openspec/` (the catalog below) |
| `core` | `commit-authorship-gate`, `process-kill-gate`, `worktree-location-gate` + `worktree-location`, the config helper, the rules that explain them, the `panel-de-decision` skill and the global `CLAUDE.md` block |
| `devtools` | `port-lease` (a fixed block of local ports per project) and `test-account` (private store of the test users sessions create), with their rules |

Manifests are in `global/modules/<name>.yaml`; the files they install are in `global/` (and, for
`openspec`, in `.claude/`). The rule texts of `core` and `devtools` are written in Spanish, like the
catalog's task aliases.

## Override layer

Your personal layer: by default `~/.config/claude-toolkit/`, or `CLAUDE_TOOLKIT_OVERRIDE`, or
`--override DIR` (`--override ''` installs the toolkit alone). See [`examples/override/`](examples/override/README.md)
for a complete example and how to version it in a private repository of your own.

Precedence, highest first:

- **files:** `override/files/<dest>` replaces the toolkit file → toolkit file + `override/append/<dest>`
  → toolkit file. `remove:` in `override.yaml` drops a toolkit file and the hooks that run it.
- **values:** `CLAUDE_TOOLKIT_CONFIG_DIR` (tests) → `override/config/<piece>.json` →
  `global/config/<piece>.json` → the defaults in the piece's code.

Each configurable piece reads only its own small file, `~/.claude/toolkit/config/<piece>.json`, through
`scripts/lib/toolkit_config.py`; a missing or corrupt file falls back to the defaults, so hooks fail
open. No piece hard-codes a path, host or project of a particular machine.

**Contracts.** A piece the override replaces must behave like the one it replaces (Liskov).
`global/contracts/<piece>.yaml` lists probes (input, expected exit code and output); `install` runs
them on the override's replacements in a throwaway `HOME` and refuses with exit 3 if one breaks
(`--allow-contract-failures` to force).

## Privacy

This repository is public; the override is not. `scripts/privacy-check.py` runs before every commit
and in CI:

- generic patterns in the repo (`scripts/privacy-patterns.yaml`): public IPs, e-mail addresses,
  account UUIDs, home paths, dated personal orders, API keys and private keys; exceptions only with a
  reason (`scripts/privacy-allow.yaml`);
- a private layer that is never published: terms from the override's `privacy-denylist.txt` and the
  literal quotes found in the override's files. Its findings never repeat the term, only its entry number.

```bash
python3 scripts/privacy-check.py --staged --require-private    # before a commit
python3 scripts/privacy-check.py --message .git/COMMIT_EDITMSG
python3 scripts/privacy-check.py --range origin/main..HEAD       # a branch's commits
```

## Keeping the live dir, the override and the toolkit in sync

- `./install.sh drift` lists files that are `missing`, `live-changed`, `toolkit-changed`,
  `override-base-changed` (the toolkit moved on since you replaced its file) or `untracked`.
- `./install.sh pull <dest>` copies a live file into the override (private, the default) and records
  the toolkit version it was based on; `--to toolkit` copies it into the repo only if the privacy check
  is clean.
- `./install.sh equivalence --live ~/.claude` installs toolkit + override into a temp `HOME` (the live
  dir is only read) and explains every difference: `identical`, `override`, `toolkit-newer` (the live
  file is an earlier version from this repo's history), `neutral-text` (same Python AST), `declared`
  (in `override.yaml` with reason and proof), `added`, `excluded`. Anything else is `unexplained` and
  makes it exit 1.

## Migrating a machine that already has its own `~/.claude`

1. Put your personal pieces in the override (`files/`, `append/`, `config/`, `hooks/`) and list what the
   toolkit must never manage under `excluded:`.
2. Run `./install.sh equivalence --live ~/.claude` until it reports 0 unexplained differences.
3. Only then run `./install.sh install` (it backs up everything it replaces; `uninstall` reverts it).

## What is not in the toolkit, and why

- **Session supervision** (the supervisor skill and its lock, census and question queue): it is
  personal today and lives in the developer's override. Making it general is planned, with acceptance
  criteria, in `openspec/changes/global-claude-toolkit/tasks.md` §8.
- Pieces that still carry machine values (the heavy-job semaphore, deploy gates, account switching,
  scheduled routines): listed one by one, with what each needs to enter, in
  `openspec/changes/global-claude-toolkit/evidence/core-scope.md`.
- **Third-party skills** are never redistributed; install them from their own source.

## Contents

| Path | Description |
|------|-------------|
| `install.sh`, `scripts/toolkit/` | Installer (Python package) and its tests (`scripts/toolkit/tests/`). |
| `global/` | Modules, the files they install, per-piece config defaults, hook fragments and contracts. |
| `examples/override/` | A complete example override. |
| `.claude/commands/`, `.claude/skills/` | The OpenSpec catalog for Claude Code (installed by the `openspec` module). Rule content is folded into each skill's `SKILL.md`. |
| `.claude/scripts/openspec-list.sh` | List active OpenSpec changes (Markdown + HTML). |
| `.cursor/commands/`, `.cursor/skills/`, `.cursor/rules/` | The same catalog as a Cursor package (secondary target), kept in parity, exported per project. |
| `docs/openspec/` | Index, master prompts, GAPS + RUN-LOOP templates, operator notes. |
| `scripts/` | Repo tooling, never installed: catalog validator, privacy check, their tests and declared exceptions. |
| `openspec/` | The toolkit's own OpenSpec changes (e.g. `openspec/changes/global-claude-toolkit/`). It ships no product `openspec/` tree for consuming applications. |

## Use the catalog in one project only (Cursor or Claude Code)

**Claude Code:** the global install already makes the catalog available in every project. To vendor it
into one repository instead, copy `.claude/commands/`, `.claude/skills/` and `docs/openspec/` (or use
`/exporta-spec`) and add a project-stack note to that project's `CLAUDE.md`.

**Cursor:** copy `.cursor/commands/`, `.cursor/skills/`, `.cursor/rules/` and `docs/openspec/` into the
target repo (or use `/exporta-spec`), and add a project-stack rule there (e.g.
`.cursor/rules/01-project-stack-quality-gate.mdc`).

In both cases install the [OpenSpec CLI](https://github.com/Fission-AI/OpenSpec) and keep `openspec/`
in the application repo.

## Recommended flow (including gap analysis)

**Manual (step by step):**

```
/prepara-tarea  →  EXPLORE / PROPOSE / HYDRATE / VERIFY
/gaps-spec      →  GAPS.md (honest multiagent loop, ≤5 iter)
/mejora-tarea   →  hydrate FACT gaps + READY TO APPLY
/aplica-tarea   →  implement tasks
/archiva-tarea  →  archive change
```

**Pipeline (unattended, sequential):**

```
/repasa-spec <slug>  →  gaps → mejora-tarea → aplica-tarea → gaps
```

Runs phases **one after another** (never in parallel) for an existing change under `openspec/changes/<slug>/`. Requires the change slug — e.g. `/repasa-spec background-permission`. Also triggered by natural language (`repasa la spec`, `full openspec pipeline`, …). See `.cursor/commands/repasa-spec.md` (Cursor) / `.claude/commands/repasa-spec.md` (Claude Code).

`/gaps-spec` also accepts natural language (`analiza gaps`, `casuísticas faltantes`, `huecos en la spec`, …).

**Top layer (unattended, idea → deploy):**

```
/run-spec <slug>
<descripción de la feature>
```

`/run-spec` is the layer **above** `/repasa-spec`. From a plain description it runs, in order: `/prepara-tarea` → `/repasa-spec` → a **gap-closure loop** → an independent **confirm review** → feature tests (`/ejecuta-tests-reporte`) → the project's **regression** suite → **publish** (commit + push of the current branch) → a **deploy gate** where it stops and asks you. Phases are delegated to fresh-context subagents; the orchestrator only keeps a state table.

| Item | Detail |
|------|--------|
| Flags | `--no-deploy` (skip the deploy gate; the branch is still published) · `--max-iter N` (gap-closure budget, 1–5, default 3) |
| Gate | Read from disk: `Gaps pending (mejora + apply): 0` in `GAPS.md` **and** no unchecked `tasks.md` item — an agent's claim never decides it |
| `[prod-verify]` | Literal token on a task line that can only be verified in production: never blocks the gate, never auto-checked, always listed in the final report |
| State | `openspec/changes/<slug>/RUN-LOOP.md` — written after every phase, so the loop resumes after a compaction, a new session or a `/loop` tick |
| Paced mode | `/loop /run-spec <slug>` runs one phase per tick (`ScheduleWakeup` in Claude Code, monitored-shell sentinel in Cursor) |
| Git | One authorized mutation: commit + `git push -u origin <current-branch>`. Never a merge, rebase, tag, force-push or another branch, and nothing at all on the production branch |
| Deploy gate | **Never unattended.** The loop stops and opens one dialog — *deploy now, unattended* / *stop here* — after showing the pushed commit, test and regression results, residual `[prod-verify]` work and what the project's deploy command will do. Approval is never inferred from the invocation |
| Verdict | Last line, always: `Run-spec verdict: DEPLOYED \| READY TO DEPLOY \| AWAITING DEPLOY APPROVAL \| BLOCKED (<reason>) \| NO PROGRESS` |

Once approved, the deploy is **delegated** to the consuming project's `/deploy` command, which keeps its own confirmation dialogs. A project without a deploy command ends at `BLOCKED (no deploy command)`, and a run with no dialog channel ends at `AWAITING DEPLOY APPROVAL` — the loop never improvises an FTP sync, an SSH release or a CI dispatch. See `.cursor/commands/run-spec.md` (Cursor) / `.claude/commands/run-spec.md` (Claude Code).

## Validate the catalog

`scripts/validate-toolkit.py` checks the catalog rules that used to be kept by hand, and CI (`.github/workflows/validate-toolkit.yml`) runs it with its tests on every push and pull request. It needs Python 3 and PyYAML (`pip install pyyaml`). Nothing in `scripts/` is exported to consumer projects.

```bash
python3 -m unittest scripts/test_validate_toolkit.py
python3 scripts/validate-toolkit.py
```

Each finding is one line — `ERROR` or `WARN`, the file, `[rule]` and a message — and the run ends with a summary line. Any `ERROR` makes it exit `1`; warnings never change the exit code.

| Rule | What it checks |
|------|----------------|
| `command-parity`, `skill-parity` | The same commands and skills exist in `.cursor/` and `.claude/`, except declared asymmetries |
| `description-parity` | A command or skill present in both trees has the same `description`, except declared divergences |
| `frontmatter`, `keys` | Frontmatter parses as YAML and has the required keys, and only the allowed ones, for its file kind |
| `name`, `skill-folder` | Skill `name` equals its folder; names are kebab-case; every folder under `skills/` has a `SKILL.md` or is a declared group |
| `readme-coverage` | Each `skills/README.md` names every skill folder of its tree (as `` `name` ``, `name/` or a link) |
| `trigger-clause`, `description-length`, `collision` | The routing contract below, for model-invocable skills |
| `alias` | A `Deprecated alias of <skill>` is not model-invocable, names an existing skill and stays a short pointer (≤ 15 lines) |
| `exceptions` | Every declared exception has a reason and still matches something |
| `inner-frontmatter`, `homonym-rule` (`WARN`) | A stale second frontmatter block at the top of a skill body; a Cursor rule whose description differs from its homonym skill |

**Declaring an intentional asymmetry.** Add an entry with a `reason` to `scripts/catalog-exceptions.yaml`, under `claude_only_skills`, `cursor_only_skills`, `claude_only_commands`, `cursor_only_commands`, `description_divergence` (with `kind: command` or `kind: skill`) or `skill_groups`. Remove it in the same change that removes its cause: an entry that matches nothing is an error.

**Routing contract.** A skill without `disable-model-invocation: true` is picked by its description, so the description must:

- say what the skill does and when to use it, with a trigger clause: `Use when`, `Use on`, `Auto-invoke on` or `Triggers on`;
- take its trigger phrases, Spanish ones included, from text already in the repo: this README, the skills READMEs, the command files, `CLAUDE.md` or the skill body;
- not list the skill's steps in order, and not name commands, files or behaviour the skill does not contain;
- stay within 1024 characters and below 0.50 TF-IDF cosine against every other model-invocable skill of its tree (0.30 or more is a warning: justify it or reword).

The validator checks the clause, the length and the collisions; the other points are checked in review.

**Retiring a duplicate skill.** Turn it into a deprecated alias instead of deleting it: keep the folder and `name`, set `disable-model-invocation: true`, start the description with `Deprecated alias of <canonical>`, and leave a body of a few lines that points to the canonical skill. Do the same with its homonym Cursor rule. The exporter cannot delete files, so a pointer is what brings consumer copies back in line.

**Changing the validator.** A new or changed rule ships with at least one passing and one failing case in `scripts/test_validate_toolkit.py`; a rule without a failing-case test is incomplete. The collision thresholds are named constants whose rationale is in the design of the OpenSpec change `toolkit-catalog-validation` (Decision 4). Changing them is a reviewed decision, never a way to turn CI green.


**The global tree.** When `global/` exists the validator also checks it:

| Rule | What it checks |
|------|----------------|
| `global-manifest` | Every module manifest parses; its sources, hook fragments, dependencies and config pieces exist |
| `global-orphan` | Every file in `global/` is installed by exactly one manifest entry; every fragment and config piece is used |
| `global-hooks` | A hook fragment only runs pieces its module (or a dependency) installs |
| `global-contract` | Every installed hook has a contract with probes, and every contract a piece |
| `global-citation` | A piece only cites `~/.claude/{rules,scripts,hooks,skills}/…` that its module closure installs |
| `global-skill` | A skill in `global/` follows the routing contract and does not duplicate or collide with the catalog |

The installer, contract, drift and equivalence tests run in throwaway `HOME`s:

```bash
python3 -m unittest discover -s scripts/toolkit/tests -t .
```

Licensed under [MIT](LICENSE).

## Origin

Extracted and generalized from production OpenSpec usage across multiple stacks (2025–2026). Gap-analysis
workflow added 2026-07; global install, override layer and privacy guard added 2026-11.
