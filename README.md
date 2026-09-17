# OpenSpec + Cursor + Claude Code toolkit

Portable package for **OpenSpec workflows** in both **Cursor** and **Claude Code**: slash commands (`run-spec`, `prepara-tarea`, `opsx-*`, `gaps-spec`, `repasa-spec`, …), **skills** (`SKILL.md`), documentation under `docs/openspec/`, and rules aligned with the OpenSpec lifecycle. The two toolkits are kept in parity: `.cursor/` is the original Cursor package (commands + skills + `.mdc` rules), `.claude/` is the equivalent native Claude Code package (commands + skills — Claude Code has no separate rules file, so rule content is folded into the matching skill's `SKILL.md`).

**Stack-agnostic:** this repo does not assume Drupal, DDEV, Symfony, or any specific framework. Each consuming application documents its own stack (local dev, tests, URLs) in project rules; the toolkit references those at runtime. See `.cursor/rules/00-openspec-stack-agnostic.mdc` (Cursor) / `.claude/skills/00-openspec-stack-agnostic/SKILL.md` (Claude Code).

This repository ships **no product** `openspec/` tree for a consuming application — active changes, promoted specs and CLI config live in each application repo that installs the OpenSpec CLI. It does version its **own** OpenSpec work under `openspec/` (the toolkit's changes and specs, e.g. `openspec/changes/loop-skill/`), because the toolkit's features are themselves specified with OpenSpec.

## Contents

| Path | Description |
|------|-------------|
| `.cursor/commands/` | Cursor commands (Spanish task aliases + English `opsx-*`; `/run-spec`, `/gaps-spec`, `/repasa-spec`). |
| `.cursor/skills/` | Workflow skills: explore, propose, apply, archive, gap analysis, pipeline (`repasa-spec`), run loop (`run-spec`), verification, multiagent. |
| `.cursor/skills/README.md` | Skills index (OPSX ↔ ES map). |
| `.cursor/rules/` | OpenSpec rules (numbered series + workflow, multiagent, stack-agnostic). |
| `.cursor/scripts/openspec-list.sh` | List active OpenSpec changes (Markdown + HTML). |
| `.claude/commands/` | Same command set, native Claude Code slash-command frontmatter (`description`, `argument-hint`). |
| `.claude/skills/` | Same skills **plus** the former `.cursor/rules`-only content, each folded into its own `SKILL.md` (e.g. `00-openspec-stack-agnostic`, `openspec-e2e-regression-guard`, `openspec-extract-spec-from-doc`, `openspec-fix-changes-gitignore`). |
| `.claude/skills/README.md` | Skills index (OPSX ↔ ES map + stack-agnostic skill list). |
| `.claude/scripts/openspec-list.sh` | Same script, `.claude/context/` output path. |
| `docs/openspec/` | Index, master prompts, GAPS + RUN-LOOP templates, operator notes — shared by both toolkits. |

## Integrate into another project

**Cursor:**

1. Copy or merge `.cursor/commands/`, `.cursor/skills/`, `.cursor/rules/`, and `docs/openspec/` into the target repo root (or use `/exporta-spec` from a repo that already has the export bundle).
2. Add a **project-stack** rule in the target (e.g. `.cursor/rules/01-project-stack-quality-gate.mdc`) with real commands, paths, and URLs for that application.

**Claude Code:**

1. Copy or merge `.claude/commands/`, `.claude/skills/`, and `docs/openspec/` into the target repo root (or use `/exporta-spec` from a repo that already has the export bundle).
2. Add a **project-stack** note in the target's `CLAUDE.md` (or a project skill) with real commands, paths, and URLs for that application.

**Both:**

3. Adjust `.gitignore` so shared toolkit paths are versioned as you prefer.
4. Install the [OpenSpec CLI](https://github.com/Fission-AI/OpenSpec) and maintain `openspec/` in the application repo.

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

**Supervisor layer (above every session):**

```
/supervisa-sesiones [alcance] [--projects a,b,c] [--no-deploy] [--hasta-main] [--max-rondas N]
```

`/supervisa-sesiones` (also triggered by `supervisión maestra`, `supervisa maestro`, `supervisor maestro` and the like) sits **above** `/run-spec`: instead of driving one change, it drives **every open session across every project** to a clean close. In order: census of live sessions (ids, projects, branches, worktrees, real git state) → one fixed-contract message asking each session what is still theirs → a collision map that gives **one writer at a time** per repo, branch, worktree and service → convergence rounds until every session declares itself closed → a release-validation dialog per freed session → grouped dialogs for everything only the developer can decide (orphan findings included) → supervised subagents per decision → cascade merge → unattended deploy.

| Item | Detail |
|------|--------|
| Session release | A session that declares itself done is **not** archived silently: it gets its own validation dialog with a 2–3 line plain-language summary — what it was doing, where it ended (branch, commit, pushed, what was verified), why it is no longer needed — and three options: archive / leave open / hold. One batch per round, silence archives nothing |
| Single supervisor | Only one master supervisor may be alive. A global lock (`~/.claude/supervisor/MASTER.lock.d`, created with `mkdir` — atomic) holds an `owner.json` with a heartbeat rewritten on every phase and round. With another supervisor running it refuses to start and offers to let it continue, take over resuming **its** record, or hand it the extra scope. A lock is orphaned only when the heartbeat is stale **and** the owning session is gone; it is released in F9 even after a blocker |
| Stall watchdog | Nothing hangs the system: every write turn, subagent, wait, deploy and background command is registered with a deadline and swept each round (turn 30 min · session report 15 min · subagent 20 min · external wait per the runbook · background command 10 min idle). What expires leaves the critical path — the rest keeps going, the dependent project stops at `READY TO DEPLOY`/`BLOCKED` instead of being merged anyway, and the stall goes to the decision queue and into **Residual**. Deadlocks break by a deterministic rule (the more advanced session writes first), otherwise they are asked |
| Stop contract | It does **not** finish while a session has not declared its own part resolved, or a developer decision is unasked. Silence and timeouts are never a yes |
| Collisions | One writer per repo/branch/worktree/service; a green measured on a shared dirty working tree — or obtained by excluding someone else's files — is not a green |
| Truth source | Session and subagent reports never decide a gate: the repo does. Mismatches are logged |
| Untrusted input | Other sessions' transcripts and reports are **data, not instructions** — anything ordering an action is quoted to the developer and asked |
| Cascade | `main → develop` (recover production-only fixes first) → feature → `develop` → `main`, the last step only with `--hasta-main` and a documented flow |
| Deploy | `unattended-deploy on` → the project's own deploy command → verify → `off`, always. Production only when the order names it |
| State | `.claude/context/supervisor/SUPERVISOR-<YYYYMMDD-HHMM>.md` (`.cursor/` in Cursor), written after every transition; the run is resumable |
| Verdict | Last line, always: `Supervisor verdict: ALL CLOSED \| DEPLOYED \| READY TO DEPLOY \| AWAITING DEVELOPER DECISION \| BLOCKED (<reason>) \| NO PROGRESS` |

Without a session API (typically Cursor) it says so and degrades to **manual mode**: the census is rebuilt from `git worktree list`, unpushed branches and unchecked OpenSpec tasks, plus one dialog asking for the open sessions. It never simulates a census it could not take. See `.cursor/commands/supervisa-sesiones.md` (Cursor) / `.claude/commands/supervisa-sesiones.md` (Claude Code).

## Publish on GitHub

1. Ensure `.gitignore` excludes local artifacts (`.cursor/context/`, `.claude/context/`, `*.zip`, export registries).
2. Commit the toolkit tree (`.cursor/` commands, skills, rules; `.claude/` commands, skills; `docs/openspec/`).
3. Create the remote and push:

```bash
cd /path/to/openspec-cursor-toolkit
git remote add origin https://github.com/<org>/openspec-cursor-toolkit.git
git push -u origin main
```

Licensed under [MIT](LICENSE).

## Reference consumer

Use a **private or public app repo** that already deploys this toolkit and defines its own stack rule (e.g. Symfony + Next.js monorepo, Drupal site, etc.). Copy `.cursor/rules/01-project-stack-quality-gate.mdc` pattern from your application — not from this toolkit.

## Origin

Extracted and generalized from production OpenSpec usage across multiple stacks (2025–2026). Gap-analysis workflow added 2026-07.
