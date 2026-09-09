---
description: "Top layer — drive one OpenSpec change from idea to a published branch unattended (prepara → repasa → gap-closure loop → confirm → tests → regression → commit + push), then stop at a deploy-approval dialog"
argument-hint: "[slug] [--no-deploy] [--max-iter N]"
---

# Build spec (OpenSpec top-level loop)

You are running **run-spec**: take a plain description and drive it to a deployed feature **unattended**, stopping only on a real blocker.

## Mandatory (this turn)

1. Read **`.claude/skills/run-spec/SKILL.md`** in the same turn **before** executing any phase.
2. Create or resume the state file **`openspec/changes/<slug>/RUN-LOOP.md`**.
3. Execute phases P0 → P8 in order, one at a time, each delegated to its canonical skill in a fresh-context subagent (publish and the deploy gate run in the main agent).
4. Close with the mandatory report and the canonical last line `Run-spec verdict: <VERDICT>`.

## Invocation

```text
/run-spec [slug]
[descripción del problema o de la feature]
```

Examples:

```text
/run-spec rider-eta
Mostrar el ETA en vivo en la tarjeta del rider, recalculado en cada poll.
```

```text
/run-spec rider-eta --no-deploy --max-iter 2
Mostrar el ETA en vivo en la tarjeta del rider.
```

```text
/run-spec rider-eta
```

The third form is **resume mode**: the change already exists, so no description is required and the loop continues from `RUN-LOOP.md`.

## Parsing

| Field | Rule |
|-------|------|
| `slug` | First whitespace-separated token after `run-spec` (optional leading `/`, no `:`). MUST be kebab-case. |
| `--no-deploy` | Skip the deploy gate and end at `READY TO DEPLOY`. P7 still commits and pushes the current branch. |
| `--max-iter N` | Gap-closure budget, `1 ≤ N ≤ 5` (above 5 clamps to 5 and is logged). Default **3**. |
| description | All lines after line 1, verbatim. Flags are never part of it. |

Ask **once** and stop when: the slug is missing or not kebab-case; or the description is empty **and** `openspec/changes/<slug>/` does not exist.

## Phases

| # | Phase | Delegate | Exit gate |
|---|-------|----------|-----------|
| P0 | Parse + state | — | slug valid; `RUN-LOOP.md` created or resumed |
| P1 | Bootstrap | `/prepara-tarea <slug>` + description | proposal + tasks + specs on disk (skipped if `proposal.md` exists) |
| P2 | Review pipeline | `/repasa-spec <slug>` | `GAPS.md` pending line + `READY-TO-APPLY.md` |
| P3 | Gap-closure loop | `/repasa-spec <slug>` × ≤ `max_iter` | `gaps_pending = 0` **and** 0 unchecked tasks without `[prod-verify]` |
| P4 | Confirm review | `/repasa-spec <slug>` (fresh reviewer) | gate still passes |
| P5 | Feature tests | `/ejecuta-tests-reporte <slug>` | exit 0 |
| P6 | Regression | project full tests + E2E | exit 0 (none documented → downgrades P7) |
| P7 | Publish | `git commit` + `git push -u origin <branch>` | branch pushed (or nothing to publish) |
| P8 | Deploy gate | **approval dialog** → project `/deploy` | approved and deploy succeeded → `DEPLOYED` |

Inner "stop here, run the next command in a new message" lines of the delegated skills are **overridden** inside this loop — same pipeline override as `/repasa-spec`.

## Gate and `[prod-verify]`

The gap-closure gate is read from disk, never from an agent's prose:

- `gaps_pending` — the last `Gaps pending (mejora + apply): N` line in `GAPS.md`.
- `tasks_unchecked` — unchecked `tasks.md` lines **without** the literal token `[prod-verify]`.
- `tasks_prod_verify` — unchecked lines **with** it: never blocking, never auto-checked, always listed verbatim in the final report.

## Git and deploy

**Publish (P7) is automatic; deploy (P8) is not.**

Invoking `/run-spec` authorizes exactly **one** git mutation: committing the pending work and pushing the **current** branch (`git push -u origin <branch>`). The loop never merges, rebases, tags, force-pushes, or pushes another branch, and it makes no git mutation at all on the project's production branch.

The deploy is then **gated**: the loop stops and opens one `AskUserQuestion` dialog — *deploy now, unattended* / *stop here* — after laying out the pushed commit, the test and regression results, the residual `[prod-verify]` work and what the project's deploy command will actually do. It may add up to three genuine doubts about this deploy. Approval is never inferred from the invocation and silence is never a yes. On approval the project's own `/deploy` runs untouched, keeping its internal dialogs.

| Situation | Verdict |
|-----------|---------|
| Developer approves and the deploy succeeds | `DEPLOYED` |
| Developer stops at the gate, or `--no-deploy` | `READY TO DEPLOY` |
| No dialog channel (non-interactive, background, paced tick) | `AWAITING DEPLOY APPROVAL` |
| No project deploy command | `BLOCKED (no deploy command)` |

## Paced mode

`/loop /run-spec <slug>` runs **one phase per tick** and yields with `ScheduleWakeup` semantics (`noop`, `stop`, `prompt`, `delaySeconds` matched to what is actually awaited). Cursor uses its own `/loop` monitored-shell mechanism. Without a wake-up primitive the loop says so and runs inline.

## Output

`## Run loop — <slug>` (phase table) → `## Verification` → `## Residual` → `## Resumen`, and the last line, verbatim:

```text
Run-spec verdict: DEPLOYED | READY TO DEPLOY | AWAITING DEPLOY APPROVAL | BLOCKED (<reason>) | NO PROGRESS
```

## Relation

| Command | Role |
|---------|------|
| `/run-spec <slug>` | **Top layer** — idea → published branch, unattended, stopping at the deploy gate |
| `/repasa-spec <slug>` | Layer below — one review-and-apply cycle (P2/P3/P4 here) |
| `/prepara-tarea`, `/gaps-spec`, `/mejora-tarea`, `/aplica-tarea` | Individual phases — do not chain them by hand while `run-spec` is running |
| `/ejecuta-tests-reporte`, `/verifica-tarea`, `/harness-spec` | Tests and deeper verification |
| `/finaliza-spec`, `/archiva-tarea` | Commit + archive — manual, after the loop |
