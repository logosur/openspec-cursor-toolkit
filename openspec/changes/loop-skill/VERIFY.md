# VERIFY — loop-skill (`/run-spec`)

> **Date:** 2026-09-08 (bootstrap) · updated 2026-09-09 after `/repasa-spec loop-skill` (gaps → hydrate → apply → gaps) and the developer's deploy-gate change.

## Gates

| Gate | Command / check | Result |
|------|-----------------|--------|
| Artefacts present | `ls openspec/changes/loop-skill/` | `proposal.md`, `design.md`, `specs/run-spec-loop/spec.md`, `tasks.md`, `VERIFY.md`, `READY-TO-APPLY.md` |
| `openspec validate loop-skill` | run in **sandbox copy** (`scratchpad/sandbox`, `openspec init --tools none`) because this toolkit repo has no `openspec init` (CLI: "No OpenSpec changes directory found") | `Change 'loop-skill' is valid` — exit 0; `--strict --json` → `passed: 1, failed: 0, issues: []` |
| `openspec status --change loop-skill --json` | same sandbox | `isComplete: true`; proposal/design/specs/tasks all `done`; schema `spec-driven` |
| Spec inventory | `grep -c '^### Requirement'` / `'^#### Scenario'` | 17 requirements · 51 scenarios |
| Tasks | `grep -c '^- \[x\]' tasks.md` | 35 tasks, **33 done**; the 2 open ones (5.6, 5.7) require running the loop in a real consumer project, and 5.7 is `[prod-verify]` |
| Marker novelty | `grep -rIl 'prod-verify\|production-only' .claude .cursor docs README.md openspec/specs` | 0 hits outside this change → `[prod-verify]` is new, no collision |
| Gate grep dry-run | fixture `GAPS.md` (`Gaps pending (mejora + apply): 0`) + `tasks.md` (one `[prod-verify]`, one untagged) with the REQ-RS-GATE-01 commands | `gaps_pending=0 tasks_unchecked=1 tasks_prod_verify=1` → `FAIL` as specified |

## Evidence map

| Claim | Class | Evidence |
|-------|-------|----------|
| Existing pipeline `/repasa-spec` = gaps → mejora → aplica → gaps, chat-only phase table, pipeline override of stop lines | FACT | `.claude/skills/repasa-spec/SKILL.md` §2–§4 |
| `/gaps-spec` canonical last line `Gaps pending (mejora + apply): N` in chat **and** `GAPS.md` `## Pending count` | FACT | `.claude/skills/openspec-gap-analysis/SKILL.md` §2 "Pending count — mandatory", §7 |
| `/ejecuta-tests-reporte`, `/verifica-tarea`, `openspec-e2e-regression-guard`, `/finaliza-spec` (commit only, never push) exist with the described roles | FACT | `.claude/commands/ejecuta-tests-reporte.md`, `.claude/commands/verifica-tarea.md`, `.claude/skills/openspec-e2e-regression-guard/SKILL.md`, `.claude/commands/finaliza-spec.md` |
| Consumer projects ship a `/deploy` command with own preflight + `AskUserQuestion` decision points and strict token budget | FACT | `/home/ivan/projects/htdocs/vitalcigar.es/.claude/commands/deploy.md`, `/home/ivan/projects/htdocs/app-residuos-oscar/.claude/commands/deploy.md` |
| Claude Code `/loop` skill exists ("omit the interval to let the model self-pace"); `ScheduleWakeup` tool with `delaySeconds` (60–3600), `noop`, `stop`, `prompt`, `reason` | FACT (this session) | Skill listing + tool schema available in this session |
| Cursor `/loop` uses monitored-shell sentinel + JSON prompt payload | FACT | `~/.cursor/skills-cursor/loop/SKILL.md` |
| Frontmatter parity conventions (Claude Code vs Cursor commands/skills/rules) | FACT | `.claude/commands/repasa-spec.md`, `.cursor/commands/repasa-spec.md`, `.cursor/rules/repasa-spec-openspec-pipeline.mdc`, both `repasa-spec/SKILL.md` |
| Toolkit repo has no `openspec init`; `openspec status/validate` fail here | FACT | CLI output: "No OpenSpec changes directory found. Run 'openspec init' first." |
| The invocation authorizes **only** the P7 commit + push of the current branch; the deploy is always gated by an explicit dialog | FACT (developer decision, 2026-09-09) | Superseded the earlier "invocation = deploy order" inference at the developer's request: publish is automatic, `AskUserQuestion` gates P8, new verdict `AWAITING DEPLOY APPROVAL`. See design D8. |
| Near-no-op cost of repasa-spec inner phases when nothing is pending | INFERENCE | mejora-tarea exits when `isComplete: true`; aplica-tarea has no unchecked tasks to work — not measured. |
| `ScheduleWakeup` available in every Claude Code surface / Cursor | UNKNOWN | Present in this session only; skill degrades to inline (REQ-RS-PACED-01). |
| Bundle store for `/exporta-spec` (`ai-developer/templates/openspec-claude/`) | UNKNOWN | Path not found under `/home/ivan/projects/htdocs/ai-developer/`; propagation kept out of this change. |
| Sub-agent primitive names (`Agent` in Claude Code, `Task` in Cursor) | FACT | This session's tool list; `.claude/skills/openspec-gap-analysis/SKILL.md` §3 uses `Task` naming for Cursor lineage |

## Requirement → task coverage

| REQ | Tasks |
|-----|-------|
| REQ-RS-CMD-01 | 1.1, 1.2, 3.1, 3.2, 3.3, 5.1, 5.4 |
| REQ-RS-INPUT-01 | 1.1 |
| REQ-RS-STATE-01 | 1.4, 2.1, 5.3 |
| REQ-RS-PHASES-01 | 1.3 |
| REQ-RS-GATE-01 | 1.5, 5.2 |
| REQ-RS-LOOP-01 | 1.6 |
| REQ-RS-PRODTASK-01 | 1.7, 5.2 |
| REQ-RS-CONFIRM-01 | 1.8 |
| REQ-RS-TESTS-01 / REQ-RS-REGRESSION-01 | 1.9 |
| REQ-RS-PUBLISH-01 | 1.10, 5.7, 5.8 |
| REQ-RS-DEPLOY-01 | 1.15, 5.6, 5.7, 5.8 |
| REQ-RS-REPORT-01 | 1.11, 1.16, 5.6 |
| REQ-RS-PACED-01 | 1.12, 3.2 |
| REQ-RS-TOKEN-01 / REQ-RS-SAFETY-01 | 1.13, 5.6 |
| REQ-RS-DOCS-01 | 2.1, 2.2, 4.1–4.6, 5.1, 5.8 |
| VERIFY gate | 5.5 |

All 17 requirements have ≥ 1 task; all 35 tasks map to a requirement or the VERIFY gate.

## Not verified (honest)

- The implementation is on disk and structurally checked (files, frontmatter, grep of every gate rule, parity diff), but **no REQ-RS-* scenario has been observed at runtime** — the loop has never driven a real change end to end. Tasks 5.6 and 5.7 are exactly that verification.
- Paced-mode behaviour (`ScheduleWakeup` ticks) can only be observed in a live Claude Code run after apply (task 5.6 covers inline `--no-deploy`; paced observation is a manual follow-up).
- Task 5.7 (`[prod-verify]`) requires a consumer project deploy — outside this repo.

## Verdict

**APPLIED (33/35)** — artefacts complete and validated (sandbox: `openspec validate --strict` exit 0, `isComplete: true`); command, skills, Cursor rule, template and docs shipped in both toolkits. Remaining: 5.6 and 5.7, which require running `/run-spec` in a real consumer project.
