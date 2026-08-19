---
name: repasa-spec
description: "OpenSpec full pipeline — sequential gaps → hydrate → apply → gaps. Auto-invoke on /repasa-spec, repasa la spec, pipeline openspec, full openspec pipeline, ejecuta el ciclo completo del change."
disable-model-invocation: true
---

# Repasa spec — OpenSpec sequential pipeline

> **Command:** `.claude/commands/repasa-spec.md`  
> **Rule (L2):** `.claude/skills/repasa-spec/SKILL.md`  
> **Orchestration:** `.claude/skills/multiagente/SKILL.md`

You are running **repasa-spec**: execute the **full OpenSpec review-and-apply cycle** for `openspec/changes/<slug>/` in **strict sequential order**. Each phase must **fully complete** (success, documented partial, or documented blocker) before the next phase starts. **Never run phases in parallel.**

## When to use (natural language)

Apply this skill when the user message matches **any** of:

| Intent (EN / ES) | Example prompts |
|------------------|-----------------|
| Slash / alias | `/repasa-spec background-permission`, `repasa-spec stats-net` |
| Repasa spec | `repasa la spec stats-net`, `repasa el change background-permission` |
| Full pipeline | `pipeline openspec stats-net`, `ejecuta el ciclo completo del change`, `full openspec pipeline stats-net` |
| Review + apply | `review and apply change stats-net`, `gaps hydrate apply gaps stats-net` |

**Do not run** when the user only wants **one** step (`/gaps-spec` alone, `/mejora-tarea` alone, `/aplica-tarea` alone) — use that skill instead.

## 1. Resolve `<slug>` (required)

| Step | Action |
|------|--------|
| Parse | First kebab-case token after `repasa-spec` (optional `/`, whitespace only — no `:` before slug) |
| Verify | `openspec/changes/<slug>/` exists **or** will be created in Phase 1 (Mode A only — slug required upfront) |
| Missing | Ask once: *"Indica el change-id (slug kebab-case bajo openspec/changes/)"* — stop |

Record `slug` for all four phases.

## 2. Orchestrator contract

The **main agent** is the pipeline orchestrator:

- **Does:** run phases 1→2→3→4 in order; delegate each phase to the canonical skill; verify phase exit criteria; accumulate phase reports; produce final `## Verification`.
- **Does not:** skip ahead; run phases in parallel; implement product code directly (Phase 3 subagents implement).
- **Overrides (pipeline only):** individual skills say "stop, tell user to run next command" — **ignore those stop boundaries** inside `repasa-spec`; continue to the next phase unless § Stop conditions apply.

Read before Phase 1:

- `.claude/skills/multiagente/SKILL.md`
- `.claude/skills/multiagente/SKILL.md`

## 3. Sequential phases (fixed order)

```text
Phase 1: gaps-spec (pre)  →  Phase 2: mejora-tarea  →  Phase 3: aplica-tarea  →  Phase 4: gaps-spec (post)
```

**Gate between phases:** do not start phase N+1 until phase N reports `phase_status: done | partial | blocked` with evidence (see per-phase exit criteria).

---

### Phase 1 — Pre-hydrate gap analysis

**Delegate:** `.claude/skills/openspec-gap-analysis/SKILL.md`  
**Equivalent:** `/gaps-spec <slug>` (Mode A — change-id required)

| Item | Detail |
|------|--------|
| Input | Existing or partial change folder |
| Output | `openspec/changes/<slug>/GAPS.md` updated |
| Mode | **Mode A only** (slug is mandatory for repasa-spec) |

**Exit criteria (proceed to Phase 2 when):**

- `GAPS.md` written or updated on disk.
- Orchestrator recorded: iteration count, FACT/INFERENCE/REJECTED counts (or "unchanged / no new FACT").
- Gap loop finished (≤5 iter or early stop per gap-analysis skill).

**On blocker:** folder missing and cannot scaffold → `phase_status: blocked` — **stop pipeline**, report.

---

### Phase 2 — Hydrate until READY TO APPLY

**Delegate:** `.claude/skills/mejora-tarea/SKILL.md`  
**Equivalent:** `/mejora-tarea <slug>`

| Item | Detail |
|------|--------|
| Input | Change folder + Phase 1 `GAPS.md` |
| Output | `proposal`, `design`, `specs`, `tasks` done; `READY-TO-APPLY.md`; `openspec validate <slug>` exit 0 |

**Steps (from mejora-tarea):**

1. `openspec status --change "<slug>" --json`
2. Create pending artefacts in dependency order
3. Update `READY-TO-APPLY.md`
4. `openspec validate "<slug>"` — fix errors before exit

**Exit criteria (proceed to Phase 3 when):**

- `isComplete: true` in status JSON **or** orchestrator documents which artefacts remain and why (partial).
- `READY-TO-APPLY.md` exists with verdict.
- `openspec validate "<slug>"` exit 0.

**On partial:** if validation fails after fix attempts → `phase_status: partial` — **still attempt Phase 3** only if `tasks.md` exists with actionable items; otherwise `blocked` — stop pipeline.

**Scope:** artefacts only — no product code in this phase (same as mejora-tarea).

---

### Phase 3 — Apply (implement tasks)

**Delegate:** `.claude/skills/aplica-tarea/SKILL.md` + `.claude/skills/multiagente/SKILL.md`  
**Equivalent:** `/aplica-tarea <slug>`

| Item | Detail |
|------|--------|
| Input | Hydrated change + `tasks.md` |
| Output | Product code/config; `tasks.md` checkboxes updated; verification evidence |

**Steps (from aplica-tarea):**

1. `openspec status --change "<slug>" --json`
2. `openspec instructions apply --change "<slug>" --json` — read all `contextFiles`
3. Work `tasks.md` in order; `- [x]` only when implemented **and** verified per task
4. `openspec validate "<slug>"` when relevant
5. Project checks: project test/lint commands on touched paths (per stack rule)

**Exit criteria (proceed to Phase 4 when):**

- All applicable tasks marked done **or** remaining tasks listed with concrete blockers.
- `## Verification` evidence collected for implemented behavior (gate `00-verification-gate.mdc`).

**On blocker:** credentials, ambiguous product decision, or unfixable env → `phase_status: blocked` — **still run Phase 4** (post-apply gaps document residual FACT) unless Phase 3 never started (no `tasks.md`).

---

### Phase 4 — Post-apply gap analysis

**Delegate:** `.claude/skills/openspec-gap-analysis/SKILL.md`  
**Equivalent:** `/gaps-spec <slug>` (Mode A)

| Item | Detail |
|------|--------|
| Input | Post-apply codebase + updated spec/tasks |
| Output | `GAPS.md` refreshed — post-apply residual gaps |

**Exit criteria (pipeline complete when):**

- `GAPS.md` updated with post-apply section or iteration log.
- Residual FACT gaps listed for follow-up (`/mejora-tarea` or new change).

---

## 4. Phase tracking (orchestrator log)

Maintain an internal phase log (include in final chat):

```markdown
## Pipeline — <slug>

| Phase | Skill | Status | Evidence |
|-------|-------|--------|----------|
| 1 pre-gaps | openspec-gap-analysis | done/partial/blocked | GAPS.md path, FACT count |
| 2 hydrate | mejora-tarea | done/partial/blocked | isComplete, validate exit |
| 3 apply | aplica-tarea | done/partial/blocked | tasks x/y, verification |
| 4 post-gaps | openspec-gap-analysis | done/partial/blocked | new FACT count |
```

## 5. Stop conditions (whole pipeline)

| Condition | Action |
|-----------|--------|
| Missing slug | Ask once — stop |
| Phase 1 blocked (no change folder) | Stop — no Phase 2 |
| Phase 2 blocked (no tasks.md, validate fails) | Stop before Phase 3 — report |
| Phase 3 blocked mid-apply | Complete Phase 4 — report partial |
| User explicit interrupt | Stop — report progress table |
| git commit/push/merge/DB import | Never without explicit user auth (unchanged) |

## 6. Final response (mandatory sections)

1. **`## Pipeline — <slug>`** — phase table (above)
2. **`## Verification`** — evidence from Phase 3 apply; JS/console if UI touched; tests/lint commands + output
3. **Residual work** — unchecked `tasks.md` items; post-apply FACT gaps from Phase 4
4. **`## Resumen`** — locked to Verified facts only (VR-14)

## 7. Cross-links

| Step alone | Invoke |
|------------|--------|
| Gaps only | `/gaps-spec <slug>` |
| Hydrate only | `/mejora-tarea <slug>` |
| Apply only | `/aplica-tarea <slug>` |
| Verify after apply | `/verifica-tarea <slug>` |

**Do not** suggest running individual commands for phases already executed in this pipeline unless the user starts a **new** message.
