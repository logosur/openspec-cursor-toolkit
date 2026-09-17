# Cursor skills (OpenSpec toolkit)

**Stack-agnostic** Cursor Agent skills under this tree. Each skill is a folder containing **`SKILL.md`**. Resolve runtime commands (tests, URLs, auth) from the **target project's** stack rule — see `.cursor/rules/00-openspec-stack-agnostic.mdc`.

## OpenSpec workflow — mapa OPSX core → alias ES

| OPSX `core` command | ES alias (command) | Invoke | Purpose |
|---------------------|-------------------|--------|---------|
| `openspec propose` | `prepara-tarea` | `/prepara-tarea` | Bootstrap change: EXPLORE → PROPOSE → HYDRATE → VERIFY (no product code). |
| `openspec explore` | — / `opsx-explore` | `/opsx-explore` | Explore mode — thinking / investigation, no implementation. |
| `openspec apply` | `aplica-tarea` | `/aplica-tarea` | Implement tasks from `tasks.md`. |
| `openspec sync` | `mejora-tarea` | `/mejora-tarea` | Hydrate artefacts until READY TO APPLY. |
| — | `openspec-gap-analysis` | `/gaps-spec` **or NL** (`analiza gaps`, `casuísticas faltantes`, …) | Honest gap loop (≤5 iter) → `GAPS.md`; Mode A (change-id) or Mode B (ad-hoc objective); no implementation. |
| — | `repasa-spec` | `/repasa-spec <slug>` **or NL** (`repasa la spec`, `full openspec pipeline`, …) | Sequential pipeline: gaps → hydrate → apply → gaps (multiagent, slug mandatory). |
| — | `run-spec` | `/run-spec <slug>` + description | **Top layer** — unattended idea → published branch: prepara → repasa → gap-closure loop → confirm review → feature tests → regression → publish, then **stops at a deploy-approval dialog**. |
| — | `supervisa-sesiones` | `/supervisa-sesiones` **or NL** (`supervisión maestra`, `supervisa maestro`, `supervisor maestro`, `supervisa todas las sesiones`, `agente maestro supervisor`) | **Supervisor layer** — above every session and project: census → per-session reports → collision turns → convergence rounds → release-validation dialog per freed session → grouped developer dialogs → supervised subagents → cascade merge → unattended deploy. |
| `openspec archive` | `archiva-tarea` | `/archiva-tarea` | Archive a completed change. |

## OpenSpec CLI skills (`openspec/`)

Grouped under **`openspec/`**:

| Folder | Purpose |
|--------|---------|
| [`openspec/openspec-explore/`](openspec/openspec-explore/SKILL.md) | Explore mode — thinking / investigation, no implementation. |
| [`openspec/openspec-propose/`](openspec/openspec-propose/SKILL.md) | Propose a new change (`openspec new change`, artefacts in order). |
| [`openspec/openspec-apply-change/`](openspec/openspec-apply-change/SKILL.md) | Apply / implement from `tasks.md`. |
| [`openspec/openspec-archive-change/`](openspec/openspec-archive-change/SKILL.md) | Archive a completed change. |

## Gap analysis skill

| Folder | Invoke | Purpose |
|--------|--------|---------|
| [`openspec-gap-analysis/`](openspec-gap-analysis/SKILL.md) | `/gaps-spec` **or NL** | Honest multiagent gap analysis → `GAPS.md`. **Mode A:** change-id in message. **Mode B:** objective without slug → ad-hoc scaffold. No product code. |

Command entry point: [`.cursor/commands/gaps-spec.md`](../commands/gaps-spec.md).

## Full pipeline (`/repasa-spec`)

| Folder / command | Invoke | Purpose |
|------------------|--------|---------|
| [`repasa-spec/`](repasa-spec/SKILL.md) | `/repasa-spec <slug>` **or NL** | Run the full review-and-apply cycle **in strict order**: (1) `/gaps-spec`, (2) `/mejora-tarea`, (3) `/aplica-tarea`, (4) `/gaps-spec`. Unattended multiagent orchestration — **never parallel phases**. Slug required (Mode A only). |
| `repasa-spec` (command) | `/repasa-spec background-permission` | Shortcut for «repasa la spec» / «full openspec pipeline». |

Command entry point: [`.cursor/commands/repasa-spec.md`](../commands/repasa-spec.md).

## Top layer (`/run-spec`)

| Folder / command | Invoke | Purpose |
|------------------|--------|---------|
| [`run-spec/`](run-spec/SKILL.md) | `/run-spec <slug>` + description | Drive **one** change from a plain description to a deployed feature, unattended: P1 `prepara-tarea` → P2 `repasa-spec` → P3 gap-closure loop (≤ `--max-iter`, default 3) → P4 independent confirm review → P5 feature tests → P6 regression → P7 publish (commit + push current branch) → P8 deploy gate (developer approval, then the project `/deploy`). |
| `run-spec` (command) | `/run-spec rider-eta --no-deploy` | Same loop, skipping the deploy gate; the branch is still committed and pushed. |

| Mechanism | Detail |
|-----------|--------|
| Gate | Read from disk — `Gaps pending (mejora + apply): 0` in `GAPS.md` **and** no unchecked `tasks.md` item. A subagent's claim never decides it; on mismatch the file wins. |
| `[prod-verify]` | Literal token on a task line verifiable only in production: excluded from the gate, never auto-checked, listed verbatim in the final report. |
| State | `openspec/changes/<slug>/RUN-LOOP.md` (template: [`RUN-LOOP-template.md`](../../docs/openspec/templates/RUN-LOOP-template.md)) — written after every phase, so the loop resumes across compaction, sessions and `/loop` ticks. |
| Budget | `--max-iter N` (1–5, default 3), shared with test fix-forward passes; identical counts twice in a row → `NO PROGRESS`. |
| Paced mode | `/loop /run-spec <slug>` — one phase per tick. |
| Git | One authorized mutation: commit + push of the **current** branch. No merge, rebase, tag, force-push or other branch; nothing at all on the production branch. |
| Deploy gate | **Never unattended** — one `AskUserQuestion` (*deploy now* / *stop here*, plus genuine doubts) after the evidence is on the table. Approval is never inferred from the invocation. |
| Verdict | Last line: `Run-spec verdict: DEPLOYED \| READY TO DEPLOY \| AWAITING DEPLOY APPROVAL \| BLOCKED (<reason>) \| NO PROGRESS`. |

Command entry point: [`.cursor/commands/run-spec.md`](../commands/run-spec.md). Rule: [`.cursor/rules/repasa-spec-openspec-pipeline.mdc`](../rules/repasa-spec-openspec-pipeline.mdc).

## Related documentation

| Path | Purpose |
|------|---------|
| [`docs/openspec/skills/gap-analysis.md`](../../docs/openspec/skills/gap-analysis.md) | Long-form gap analysis procedure |
| [`docs/openspec/templates/GAPS-template.md`](../../docs/openspec/templates/GAPS-template.md) | Empty `GAPS.md` scaffold |
| [`docs/openspec/templates/GAPS-example.md`](../../docs/openspec/templates/GAPS-example.md) | Real-world example output |
| [`docs/openspec/README.md`](../../docs/openspec/README.md) | Documentation index |

Invoke skills with **`/`** or **`@`** attach per Cursor behaviour.

## Open HTML in Chrome (`/html`)

| Folder / command | Invoke | Purpose |
|------------------|--------|---------|
| [`html/`](html/SKILL.md) | `/html` | Open requested artifact as HTML in system Chrome; generate twin from `.md` if missing. |
| `html` (command) | `/html` | Shortcut for «abreme lo que te he pedido en chrome html». |

## Supervisor layer (`/supervisa-sesiones`)

| Folder / command | Invoke | Purpose |
|------------------|--------|---------|
| [`supervisa-sesiones/`](supervisa-sesiones/SKILL.md) | `/supervisa-sesiones [alcance] [flags]` **or NL** (`supervisa todas las sesiones`, `agente maestro supervisor`, `merge en cascada y deploy de todo`) | **Above every session, and only one of it at a time.** Takes a global single-supervisor lock, then census of open sessions and projects → ask each one what is still theirs → collision map with one writer per repo/branch/service → convergence rounds until every session declares itself closed → a release-validation dialog for each freed session (plain-language why, then archive it) → grouped developer dialogs for everything only they can decide → supervised subagents per decision → cascade merge → unattended deploy. |

| Mechanism | Detail |
|-----------|--------|
| Flags | `--projects a,b,c` · `--no-deploy` · `--hasta-main` (without it the cascade stops at `develop`) · `--max-rondas N` (1–10, default 5) |
| Single supervisor | A global lock — `~/.claude/supervisor/MASTER.lock.d`, taken with `mkdir` (atomic) — with an `owner.json` heartbeat rewritten every phase and round. With another supervisor alive it does **not** start: `BLOCKED (supervisor duplicado)` plus a dialog (let it continue / take over and resume **its** record / hand it the new scope). Orphan only when the heartbeat is > 30 min old **and** the owning session no longer exists. Released in F9, always. Without a session API the liveness check falls back to the heartbeat plus asking you — never a forced reclaim |
| Stall watchdog (§W) | Every launched unit — write turn, subagent, wait, deploy, background command — is registered with `inicio`, `deadline` and `última señal`, and swept at the start of each round. Defaults: turn 30 min · session report 15 min · subagent 20 min · external wait per the project runbook (else 30 min) · background command 10 min without new output. Whatever expires leaves the critical path: the rest keeps going, the dependent project stops at `READY TO DEPLOY`/`BLOCKED`, and the stall goes to the decision queue and verbatim into **Residual** |
| Session channel | Claude Code: `mcp__ccd_session_mgmt__*` or `ListAgents`/`SendMessage`. Cursor usually has none → **manual mode** (census from `git worktree list`, unpushed branches and unchecked OpenSpec tasks, stated up front). Unreachable and unattended sessions are marked `NO CONTACTABLE` and become a developer question, never an assumed close |
| Gate | Always re-read from the repo (git, tests, `tasks.md`). A session's or a subagent's report never decides a gate — on mismatch the repo wins |
| Dialogs | AskQuestion (or an explicit chat question), batched up to 4 questions, options explained in plain language. Silence or a timeout is never a yes → `AWAITING DEVELOPER DECISION` |
| Session release | A session that finishes its own part is **not** archived silently: F4b opens a dialog (in Cursor, where there is no archive API, it names the session you can close and why) with a 2–3 line plain-language summary (what it was doing, where it ended — branch, commit, pushed, what was verified — and why it is no longer needed) and three options: archive / leave open / hold. One batch per round, up to 4 sessions per dialog; silence archives nothing |
| Orphan findings | Anything a session spotted that belongs to no session goes to the developer: fix now / new session / backlog / drop |
| State | `.cursor/context/supervisor/SUPERVISOR-<YYYYMMDD-HHMM>.md` — written after every transition, so the run resumes across compaction, sessions and `/loop` ticks |
| Git | Cascade `main → develop` (recover first) → feature → `develop` → `main` (only with `--hasta-main` **and** a documented flow). Never `push --force`, history rewrite or branch deletion |
| Deploy | `~/.claude/scripts/unattended-deploy on` → the project's own deploy command → verify → `off`, always. Production only when the order names it: **merging is not deploying** |
| Verdict | Last line, always: `Supervisor verdict: ALL CLOSED \| DEPLOYED \| READY TO DEPLOY \| AWAITING DEVELOPER DECISION \| BLOCKED (<reason>) \| NO PROGRESS` |

Command entry point: [`.cursor/commands/supervisa-sesiones.md`](../commands/supervisa-sesiones.md), rule [`supervisa-sesiones-multisesion.mdc`](../rules/supervisa-sesiones-multisesion.mdc).

## Session close (`/cierra-sesion`)

| Folder / command | Invoke | Purpose |
|------------------|--------|---------|
| [`cierra-sesion/`](cierra-sesion/SKILL.md) | `/cierra-sesion [detalle]` **or NL** (`¿queda algo pendiente?`, `¿puedo cerrar la sesión?`) | Read-only close check: verdict in one line + up to 5 plain-language bullets with what is still pending. Never fixes, commits or pushes anything. |

Command entry point: [`.cursor/commands/cierra-sesion.md`](../commands/cierra-sesion.md), rule [`cierra-sesion-check.mdc`](../rules/cierra-sesion-check.mdc).
