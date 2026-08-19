# Gap analysis — procedure notes

Long-form notes for the **OpenSpec gap search** workflow. Executable steps live in:

**Cursor:**
- Skill: `.cursor/skills/openspec-gap-analysis/SKILL.md`
- Rule: `.cursor/rules/openspec-gap-analysis.mdc`
- Command: `.cursor/commands/gaps-spec.md`

**Claude Code:**
- Skill: `.claude/skills/openspec-gap-analysis/SKILL.md`
- Command: `.claude/commands/gaps-spec.md`

## Purpose

Find **evidence-backed** specification gaps the user did not specify — gaps that would change the APPLY contract if left unaddressed. This phase is **discovery only**: no product code, no spec hydration unless the user starts a new turn with `/mejora-tarea`.

## Position in the workflow

```
/prepara-tarea  →  EXPLORE / PROPOSE / HYDRATE / VERIFY
       ↓
/gaps-spec      →  GAPS.md (honest multiagent loop)
       ↓
/mejora-tarea   →  hydrate FACT gaps into REQ + READY-TO-APPLY
       ↓
/aplica-tarea   →  implement under safe-apply rules
       ↓
/archiva-tarea  →  promote / archive
```

Gap analysis is **recommended** after initial hydrate and **before** APPLY when the change touches async flows, integrations, ops tooling, or security boundaries.

## Input modes

| Mode | When | Output folder |
|------|------|---------------|
| **A** | Change slug or spec path provided | Existing `openspec/changes/<slug>/` |
| **B** | Review objective without slug | Derived slug + minimal `proposal.md` stub |

See skill §1 for parsing rules (slash, alias, and natural language).

## Multiagent loop (≤5 iterations)

| Iter | Focus |
|------|-------|
| 1 | Primary code paths from spec REQ or review objective |
| 2 | Adjacent integrations, stubs, ID mismatches |
| 3 | Ops, security, admin vs CLI coexistence |
| 4 | Cross-verify spec ↔ code ↔ prior GAPS.md (catch false HYDRATED) |
| 5 | STOP if no new FACT gaps |

Combine with `hazlo-en-modo-multiagente.mdc`: orchestrator writes `GAPS.md`; subagents are read-only.

## Taxonomy (every matrix row)

| Label | Use when |
|-------|----------|
| **FACT** | Path + line or command output proves the gap |
| **INFERENCE** | Useful note; not blocking |
| **REJECTED** | Invented, duplicate, policy-only, or unverifiable |
| **ALREADY** | Covered by existing REQ |
| **UNKNOWN** | Insufficient evidence (e.g. production runtime) |
| **HYDRATED** | FACT gap already in spec (cite REQ id) |

Align with `.cursor/rules/30-openspec-anti-hallucination.mdc` / `.claude/skills/30-openspec-anti-hallucination/SKILL.md`.

## Templates

| File | Role |
|------|------|
| [`templates/GAPS-template.md`](../templates/GAPS-template.md) | Empty scaffold for new reviews |
| [`templates/GAPS-example.md`](../templates/GAPS-example.md) | Real-world example (archived inbound-orders change) |

## After gap analysis

1. User reviews `GAPS.md` matrix.
2. Run `/mejora-tarea <slug>` to turn FACT gaps into formal requirements.
3. Re-run `/gaps-spec` only if spec or code changed materially.
4. Run `/aplica-tarea <slug>` only after READY-TO-APPLY.

## Natural language triggers

The skill auto-invokes on phrases such as:

- EN: `gap analysis`, `spec gaps`, `missing casuistics`, `update GAPS.md`
- ES: `analiza gaps`, `revisar gaps`, `casuísticas faltantes`, `huecos en la spec`, `gaps antes de aplica-tarea`

## Stack adaptation

Discover application source roots from the target repo (`src/`, `apps/`, `packages/`, etc.). Evidence commands in the skill use generic `rg`/`grep`; replace paths with project-specific roots. Readonly project CLI (Docker, npm, Make) is optional and must not mutate state.
