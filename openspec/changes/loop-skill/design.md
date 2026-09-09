# Design — loop-skill (`/run-spec`)

## Context

FACTs from EXPLORE (2026-09-08):

- Toolkit has parity trees: `.claude/{commands,skills}` and `.cursor/{commands,skills,rules}`; command frontmatter differs (Claude Code: `description`, `argument-hint`; Cursor: `name`, `id`, `category`, `description`). Skills use `name`, `description`, optional `disable-model-invocation: true`.
- `/repasa-spec` (`.claude/skills/repasa-spec/SKILL.md`) is the existing sequential pipeline gaps → mejora → aplica → gaps with a "pipeline override" that ignores inner stop lines. It records a `## Pipeline — <slug>` phase table in chat only (no on-disk state).
- `/gaps-spec` ends with the canonical line `Gaps pending (mejora + apply): <N>` both in chat and in `GAPS.md` `## Pending count` (`.claude/skills/openspec-gap-analysis/SKILL.md` §2, §7).
- `/ejecuta-tests-reporte <slug>` runs the narrowest project test command derived from `tasks.md` + `specs/**`. `/verifica-tarea` builds a 100 % scenario matrix. `openspec-e2e-regression-guard` defines failure classification (regression / legit change / outdated test / ambiguous → ask).
- `/finaliza-spec` authorizes **commit only** (never push). Project `/deploy` commands (vitalcigar.es, app-residuos-oscar) authorize commit + push + cascade merge + deploy with their own `AskUserQuestion` decision points and a strict token budget ("3–5 tool calls, do not re-read scripts").
- Claude Code loops: built-in `/loop` skill ("run a prompt or slash command on a recurring interval; omit the interval to let the model self-pace") and the `ScheduleWakeup` tool (dynamic mode: `delaySeconds` clamped 60–3600, `noop: true|false`, `stop: true`, `prompt` passed back verbatim, `reason` shown to the user; "do not poll harness-tracked work — schedule a long fallback instead"). Cursor `/loop` (`~/.cursor/skills-cursor/loop/SKILL.md`) uses a monitored shell sentinel (`AGENT_LOOP_WAKE_<purpose>`) with a JSON prompt payload.
- This toolkit repo has `openspec/specs/` but **no** `openspec/changes/` and no `openspec init` (CLI: "No OpenSpec changes directory found"). `openspec validate` for this change therefore runs in a sandbox copy (see VERIFY.md).
- No existing convention marks tasks as "verify in production only" (grep of toolkit for `prod-verify|production-only` → 0 hits). A marker must be introduced.

UNKNOWN: whether `ScheduleWakeup` is available in every Claude Code surface (present in this session; not guaranteed in Cursor or older CLI). The skill must degrade to inline mode.

## Goals / Non-Goals

**Goals**

- One command from idea to deploy, unattended, with honest terminal verdicts.
- Reuse existing skills verbatim as phases; add orchestration, gates, state and loop pacing only.
- Every gate machine-readable from files on disk (no trust in subagent prose).
- Bounded work: iteration cap + convergence guard; never an infinite loop.
- Minimal tokens: fresh-context subagents per phase, orchestrator holds only the state table.
- Safe git: mutation only inside the delegated project deploy flow, and only when the developer did not pass `--no-deploy`.

**Non-Goals**

- Re-implementing gaps/hydrate/apply/tests/deploy logic (delegated).
- Archiving the change after deploy (`/finaliza-spec` / `/archiva-tarea` stay manual; `[prod-verify]` tasks would block their gate anyway).
- Changing `openspec` CLI behaviour or the `GAPS.md` format.
- Auto-checking `[prod-verify]` tasks.

## Decisions

### D1 — Delegate, don't duplicate: phases are existing commands
`/run-spec` invokes `/prepara-tarea`, `/repasa-spec`, `/ejecuta-tests-reporte`, project test/E2E commands, and the project `/deploy`, each in a **fresh-context subagent** (`Agent` tool in Claude Code; Cursor `Task`) that must return a short structured report (`phase_status`, evidence paths, gate counts, blocker). The orchestrator never reads the whole `GAPS.md`/`tasks.md`; it `grep`s the gate lines. Alternative rejected: one long single-context run — hits compaction on real features and costs more tokens than isolated phases. **Exception discovered during apply:** P7 (deploy) runs in the **main agent**, not a subagent, because the project `/deploy` commands open `AskUserQuestion` dialogs (concurrent sessions, commit message, plan confirmation) that a subagent cannot surface to the developer; REQ-RS-PHASES-01 was amended accordingly.

### D2 — Persistent state file `RUN-LOOP.md` inside the change folder
Path: `openspec/changes/<slug>/RUN-LOOP.md` (versioned with the change, like `GAPS.md`). Written **after every phase transition** (status `pending|running|done|skipped|blocked`, iteration counter, last gate reading `gaps_pending`, `tasks_unchecked`, `tasks_prod_verify`, timestamps, mode `inline|paced`, flags). On start, if the file exists the loop **resumes** from the first non-`done` phase. Alternative rejected: `.claude/context/` — gitignored and not visible to Cursor, and the user explicitly wants the loop to be their own version of loops (resumable across sessions).

### D3 — Gap-closure gate is a pure file read
`gaps_pending` = integer from the **last** line matching `^Gaps pending \(mejora \+ apply\): [0-9]+$` in `GAPS.md`. `tasks_unchecked` = number of lines matching `^\s*- \[ \]` in `tasks.md` **whose text does not contain `[prod-verify]`**. `tasks_prod_verify` = unchecked lines containing the marker. Gate **PASS** iff `gaps_pending == 0 && tasks_unchecked == 0`. Missing `GAPS.md` or missing line → gate `UNKNOWN` → treated as FAIL (one more `/repasa-spec` iteration, which regenerates the line). "Ask the AI whether gaps remain" is implemented as: the phase subagent must end its report with the same canonical line, **and** the orchestrator re-reads the file; on mismatch the file wins and the mismatch is logged.

### D4 — `[prod-verify]` literal marker for production-dependent tasks
Tasks whose verification is only possible in production (smoke on PRO host, real payment provider, real mail delivery, production data migration) carry the literal token `[prod-verify]` in the task line, e.g. `- [ ] 8.1 Run migration on PRO [prod-verify]`. They never block the gate, are never auto-checked, and are listed verbatim in the final report under *Residual (production)*. Chosen over a separate section heading because `grep` on a line token is cheaper and survives reordering. The marker is introduced by this change; `/mejora-tarea`/`/aplica-tarea` are not modified — `run-spec` instructs its subagents to tag such tasks when they hydrate/apply.

### D5 — Bounded closure loop with convergence guard
`max_iter` default **3** (`--max-iter N`, 1 ≤ N ≤ 5; values above 5 are clamped and logged). One iteration = one full `/repasa-spec <slug>` in a fresh subagent, then the gate read. If `(gaps_pending, tasks_unchecked)` is **identical** to the previous iteration → stop with `NO PROGRESS` (do not burn the remaining budget). The final confirm review (D6) and fix-forward passes in tests/regression consume the same budget so total work is bounded.

### D6 — Final confirm review by an independent (fresh) reviewer
After the gate passes, run one more `/repasa-spec <slug>` in a fresh-context subagent whose prompt states it must **not** assume prior results. When nothing is pending, repasa-spec's mejora/apply phases are near-no-ops, so the cost is dominated by the two gaps passes — accepted as the price of independence (same principle as `harness-spec`'s fresh supervisor). If the confirm review leaves `gaps_pending > 0` or new untagged unchecked tasks, control returns to D5 (budget permitting).

### D7 — Feature tests, then regression, both fix-forward but never test-weakening
P5 = `/ejecuta-tests-reporte <slug>` (narrowest command). P6 = the **project's full** test command and E2E suite as documented in its stack rule (`00-openspec-stack-agnostic`); if the project documents none, P6 records `SKIPPED (no project test command)` and the deploy gate is **downgraded**: P7 still publishes and the run ends at `READY TO DEPLOY` without offering to deploy (no deploy offer without a regression signal). Failures: `regression` or `outdated test with spec agreement` → `/aplica-tarea <slug>` fix-forward (counts toward `max_iter`); `legit behaviour change` → spec first, then tests; `ambiguous` → `BLOCKED (ambiguous test failure)`. Assertions are never relaxed (regression-guard rules).

### D8 — Publish is automatic on the current branch; **deploy is gated by the developer**
The loop's last two phases separate what is safe to automate from what is not.

- **P7 publish** (main agent): commit everything pending and `git push -u origin <current-branch>`. Invoking `/run-spec` authorizes exactly this and nothing else — no merge, no rebase, no tag, no force-push, no other branch. On the project's production branch P7 makes **no** git mutation and reports `blocked (on production branch)`.
- **P8 deploy gate** (main agent): the loop **stops** and opens one `AskUserQuestion` dialog — *deploy now, unattended* / *stop here*, plus up to three genuine doubts about this deploy. Approval is never inferred from the invocation and silence is never a yes. On approval the project's own `/deploy` runs untouched, keeping its internal dialogs. Without a dialog channel (non-interactive, background, paced tick) the verdict is `AWAITING DEPLOY APPROVAL`.

**Why the split.** Pushing a feature branch is cheap and reversible; a production deploy usually drags a cascade merge into `main` behind it, and the global git rules keep merge and production out of any standing authorization. Making the gate an explicit dialog also gives the developer one place to raise doubts (target host, migrations, residual `[prod-verify]` work) at the only moment when all the evidence — tests, regression, pushed commit — is already on the table. **Alternative rejected:** treating the invocation as a full deploy order (the earlier design). It made the riskiest step the only one nobody confirmed.

### D9 — Loops integration: inline by default, paced via `/loop`
- **Inline mode** (default): all phases in one turn, sequential.
- **Paced mode**: the developer runs `/loop /run-spec <slug>` (Claude Code). Each tick: read `RUN-LOOP.md`, execute **at most one** phase or one loop iteration, persist, then yield using `ScheduleWakeup` semantics: `noop: false` when state advanced, `noop: true` when waiting on an external signal (e.g. deploy CI), `stop: true` on a terminal verdict, `prompt` = the same `/run-spec <slug>` text. Delay: 60 s (the minimum) when the next phase can start immediately; matched to the external wait (e.g. a ~8 min CI → one ~480 s check) when waiting; never a short poll for harness-tracked subagents. Cursor: same one-phase-per-tick contract using the Cursor `/loop` monitored-shell sentinel. If no wake-up primitive is available, the skill states so and runs inline.

### D10 — Token budget contract (explicit in the skill)
Orchestrator: read `run-spec/SKILL.md` once; do **not** re-read delegated skills (subagents read their own); hold only the state table; gate checks via `grep -c`/`tail`; skip a phase when its exit gate already holds on resume; no `.md` reports outside `openspec/changes/<slug>/`; final chat ≤ the mandatory sections. Subagent reports: ≤ 15 lines, fixed keys.

### D11 — Terminal verdicts and mandatory last line
`DEPLOYED` | `READY TO DEPLOY` | `AWAITING DEPLOY APPROVAL` | `BLOCKED (<reason>)` | `NO PROGRESS`. Last chat line, verbatim format: `Run-spec verdict: <VERDICT>` — mirrors the `Gaps pending …` convention so the next layer (or a human) can parse it.

## Phase table (canonical order)

| # | Phase | Delegate | Exit gate (file-readable) |
|---|-------|----------|---------------------------|
| P0 | Parse + state | — | slug kebab-case; `RUN-LOOP.md` created or resumed |
| P1 | Bootstrap | `/prepara-tarea <slug>` + description | `proposal.md`, `tasks.md`, `specs/**/spec.md` exist; skipped on resume if present |
| P2 | Review pipeline | `/repasa-spec <slug>` | `GAPS.md` has pending line; `READY-TO-APPLY.md` exists |
| P3 | Gap-closure loop | `/repasa-spec <slug>` × ≤ `max_iter` | `gaps_pending == 0 && tasks_unchecked == 0`; else `NO PROGRESS`/budget stop |
| P4 | Confirm review | `/repasa-spec <slug>` (fresh reviewer) | gate still PASS |
| P5 | Feature tests | `/ejecuta-tests-reporte <slug>` (+ fix-forward) | exit 0 |
| P6 | Regression | project full tests + E2E (+ classify/fix-forward) | exit 0, or documented `SKIPPED` (downgrades P7) |
| P7 | Publish | `git commit` + `git push -u origin <current-branch>` | branch pushed, or `skipped`/`blocked (on production branch)` |
| P8 | Deploy gate | approval dialog → project `/deploy` | approved and deploy succeeded → `DEPLOYED`; declined → `READY TO DEPLOY` |

## Risks / Trade-offs

- **Cost of the confirm review** (D6): one extra `/repasa-spec` when everything is already green. Mitigated by fresh-context isolation and near-no-op inner phases; accepted for independence.
- **Marker misuse**: a developer/agent could tag an ordinary task `[prod-verify]` to pass the gate. Mitigation: the final report lists every tagged task verbatim; `/finaliza-spec` still refuses to archive with unchecked tasks.
- **The loop is unattended up to the gate, not past it**: P8 always stops for a human, and the project `/deploy` may then open its own dialogs. This is intentional — a production release is not a step to automate behind a single slash command. A developer who wants one uninterrupted run answers the gate once, and everything after it is the project's own flow.
- **P7 pushes without asking**: the branch is published even when the developer later declines the deploy. Accepted — the work is already committed locally either way, and a pushed feature branch is recoverable; the alternative (asking twice) makes the loop chatty at the exact moment it should be gathering evidence.
- **Paced mode availability** (UNKNOWN): documented degradation to inline.
- **Loop budget shared** across closure, tests and regression fix-forward: keeps total bounded but may stop a slow-converging feature at `NO PROGRESS`; the state file makes a manual re-run (`/run-spec <slug>` again) resume where it stopped.

## Migration

None. New files only; one cross-link row added to `repasa-spec` command relation tables in both toolkits. No consumer project changes are required.

## Open Questions

- None blocking. Marker spelling (`[prod-verify]`), default `max_iter = 3` and the publish/deploy split (the invocation authorizes the P7 push only; the P8 deploy is always gated by a dialog) are decided above (D4, D5, D8); the developer can override by passing `--no-deploy` / `--max-iter`.
