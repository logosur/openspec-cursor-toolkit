---
name: openspec-gap-analysis
description: "Honest OpenSpec gap analysis — multiagent loop (max 5 iter), evidence-backed GAPS.md; no implementation. Auto-invoke on NL: gap analysis, analiza gaps, revisar gaps, casuísticas faltantes, huecos en la spec, missing casuistics, GAPS.md, spec gaps, qué falta en la spec, gaps stats-net, gaps en polling rider."
---

# OpenSpec gap analysis

> **Rule:** `.cursor/rules/openspec-gap-analysis.mdc`  
> **Command alias:** `/gaps-spec` (`.cursor/commands/gaps-spec.md`)  
> **Reference:** `openspec/changes/archive/2026-06-24-inbound-external-orders/GAPS.md`

You are running **openspec-gap-analysis** (slash command **or natural language**): find **evidence-backed** spec gaps the user did not specify. **Gap discovery only** — no product code, no APPLY.

**MANDATORY:** operate under **`hazlo-en-modo-multiagente`** — orchestrator delegates via `Task`; subagents search/read only.

## When to use (natural language)

Apply this skill **without** requiring `/gaps-spec`, `@skill`, or `@openspec-gap-analysis` when the user message matches **any** of these intents:

| Intent (EN / ES) | Example prompts |
|------------------|-----------------|
| Gap analysis | "gap analysis stats-net", "run gap analysis on rider polling" |
| Analiza / revisar gaps | "analiza gaps stats-net", "revisar gaps en polling rider", "revisa los gaps del change" |
| Casuísticas / huecos | "qué casuísticas faltantes hay", "casuísticas faltantes en connection health", "huecos en la spec", "qué falta en la spec" |
| GAPS artefact | "genera GAPS.md", "actualiza GAPS.md", "GAPS.md para stats-net" |
| Missing coverage | "missing casuistics", "spec gaps", "what gaps are left before apply" |
| Pre-APPLY review | "gaps before apply", "gaps antes de aplica-tarea" |

If the message clearly asks for **implementation** (`/aplica-tarea`, "implementa", "aplica el change") → **do not** run this skill; use `aplica-tarea` instead.

## 1. Resolve input (Mode A or Mode B)

### Parsing rules (apply in order)

Works for **`/gaps-spec`**, **`gaps-spec`**, and **natural-language** messages (same logic).

| Condition | Mode | Action |
|-----------|------|--------|
| Message contains a **slug** (`stats-net`, `SWT1234`) or **path** (`openspec/changes/...`, ends in `.md`) as the change target | **A** | Derive `<slug>` from token or path |
| Slash command alone **or** NL message with review intent but **no** slug/path — objective text in same or following line(s) | **B** | Extract **review objective** verbatim (full user intent minus command keywords) |
| Neither slug nor objective text | — | Ask once: *"Indica change-id o escribe el objetivo de la revisión en la línea siguiente"* — stop |
| Objective clearly present (NL or next line after `/gaps-spec`) | **B** | Do **not** ask — proceed |

**Mode A examples:** `/gaps-spec stats-net`, `analiza gaps stats-net`, `/gaps-spec openspec/changes/stats-net/specs/stats-net/spec.md`

**Mode B examples:**

```
/gaps-spec
Revisar gaps en intervalos de polling y connection health para la app rider
```

```
revisar gaps en polling rider y connection health
```

```
qué casuísticas faltantes hay en intervalos de poll para la app rider
```

### Mode A — existing change folder

Verify folder exists: `openspec/changes/<slug>/`. If not, ask once and stop.

Read before iterating (if present):

- `proposal.md`, `design.md`, `specs/**/spec.md`, `tasks.md`, `OPERATOR.md`, `VERIFY.md`
- Existing `GAPS.md` (update in place; do not wipe verified rows without re-check)

### Mode B — ad-hoc / on-the-fly

1. **Review objective** = user text after command (multiline allowed); preserve verbatim for `GAPS.md`.
2. **Derive slug** for `openspec/changes/<slug>/`:
   - Prefer English kebab-case from objective keywords (max ~40 chars), e.g. `rider-polling-connection-health`.
   - If objective too vague → `adhoc-YYYY-MM-DD-<short-hash>` (hash from first 6 hex chars of objective text).
3. **Create minimal scaffold** if folder missing:

**`proposal.md`** (stub only):

```markdown
# Proposal — <slug>

> Created by `/gaps-spec` ad-hoc (on-the-fly gap review).

## Review objective

<verbatim user objective>

## Notes

No full spec yet. Gap review driven by objective + codebase evidence.
Run `/prepara-tarea` or `/mejora-tarea` later to hydrate formal requirements.
```

4. **Do not** require `spec.md`, `tasks.md`, or full proposal before starting the loop.
5. Gap search scope = **review objective** + relevant code paths discovered in iter 1.

## 2. Bootstrap or open GAPS.md

Target: `openspec/changes/<slug>/GAPS.md`

If file missing, create **structure only** (no invented gap rows):

```markdown
# GAPS — <slug> (honest multiagent review)

> **Date:** YYYY-MM-DD
> **Mode:** A | B (ad-hoc)
> **Real status:** gaps verified → (pending | hydrated REQ-…)

## Review objective

<!-- Mode B: quote user objective verbatim. Mode A: omit or cite from proposal if helpful. -->

## Methodology — 5-iteration loop (early stop allowed)

| Iter | Focus | Honest result |
|------|-------|---------------|
| **1** | … | … |
…

## Consolidated matrix

Legend: **HYDRATED** | **ALREADY** | **INFERENCE** | **REJECTED** | **UNKNOWN**

| ID | Sev | Gap | Evidence (FACT) | Status | Req |
|----|-----|-----|-----------------|--------|-----|

## Useful casuistics (documentation, not always new REQ)

## Out of v1 (does not block APPLY)

## Pending count

| Metric | Count |
|--------|------:|
| FACT pending hydrate (`/mejora-tarea`) | 0 |
| HYDRATED (spec OK; `/aplica-tarea` only) | 0 |
| Non-blocking (INFERENCE / REJECTED / ALREADY / UNKNOWN) | 0 |

**Gaps pending (mejora + apply): 0**

## Verification (this document)

- **Verified:** …
- **Not verified:** …
```

**Mode B:** `## Review objective` is **mandatory** with verbatim user text.

### Pending count — mandatory (GAPS.md + chat)

After updating the matrix, compute **`gaps_pending`** and write it in `## Pending count` **and** as the **last line** of the chat report (see §7).

**Counting rule (exact):**

| Include in `gaps_pending` | Exclude |
|---------------------------|---------|
| Matrix row with **Status** = `FACT`, `PENDING`, or empty/missing status **and** a non-empty Evidence (FACT) column | `HYDRATED`, `ALREADY`, `REJECTED`, `INFERENCE`, `UNKNOWN` |
| Rows in **Consolidated matrix** only (not "Useful casuistics" notes unless promoted to matrix) | Rows marked "Out of v1" / documentation-only |

**Formula:** `gaps_pending` = number of consolidated-matrix rows that still need **`/mejora-tarea`** before APPLY is honest.

When `gaps_pending = 0` and all in-scope FACT rows are **HYDRATED** → next step is **`/aplica-tarea <slug>`** only.

**Canonical last line (GAPS.md `## Pending count` and chat — verbatim format):**

```text
Gaps pending (mejora + apply): <N>
```

Replace `<N>` with the integer count. **No extra text on that line.** Chat body may have sections above; this line is **always last**.

## 3. Multiagent loop (max 5 iterations)

Orchestrator runs one focus per iteration. Spawn subagents when parallel code search helps.

### Iteration focus table

| Iter | Focus | Orchestrator actions | Subagent (`explore`) |
|------|-------|----------------------|----------------------|
| **1** | Primary code paths (spec REQ **or** objective keywords) | Map scope → modules/services/routes | Trace async, KV, DL, locks, webhooks |
| **2** | Adjacent integrations & edge cases | Compare assumptions vs grep hits | Find stubs, missing classes, ID field mismatches |
| **3** | Ops / security / tooling coexistence | Read `OPERATOR.md` if present; permissions, admin vs CLI | Search admin UIs, recovery paths, locks |
| **4** | Cross-verify spec/objective ↔ code ↔ GAPS.md | Mode A: `grep '^## Requirement'` on spec; Mode B: re-read objective vs findings | Confirm file existence (`Glob`, `Grep`) |
| **5** | STOP check | If no new FACT gaps → **STOP** early | N/A |

**Early stop:** same criterion as archived GAPS iter 5 — remaining candidates are INFERENCE, REJECTED (policy), UNKNOWN, or ALREADY.

### When to spawn subagents

| Situation | Subagent type | Prompt must include |
|-----------|---------------|---------------------|
| Broad code search across application source | `explore`, thoroughness `medium` | Slug, objective or REQ ids, return path+line evidence only |
| Verify single hypothesis (file exists?) | `explore`, `quick` | Exact symbol; readonly |
| Readonly environment checks | `shell` | Project health check, `openspec validate <slug>` — no writes |

Subagents return: candidate gap, evidence quote, suggested taxonomy. Orchestrator **re-verifies** before writing FACT rows.

## 4. Evidence commands (readonly)

Run as orchestrator or delegate to `shell` subagent:

```bash
# Mode A: spec requirements inventory
grep -n '^## Requirement\|^### Requirement' openspec/changes/<slug>/specs/**/spec.md

# Symbol / class existence (adjust path to project layout)
rg -l 'ClassNameOrServiceId' src/ apps/ packages/

# Route / permission discovery (framework-specific patterns)
rg 'route|permission|Policy' --glob '*.yaml' --glob '*.php' --glob '*.ts'

# OpenSpec validation (read-only gate; Mode A only if change is formal)
openspec validate "<slug>"

# Optional readonly stack health (no writes — use project-documented command)
# e.g. docker compose ps, make status, framework console about
```

**Prohibited in gap phase:** destructive DB ops, editing product source trees, `git commit`.

## 5. Update matrix rows

For each candidate:

1. Assign taxonomy: **FACT** | **INFERENCE** | **REJECTED** | **ALREADY** | **UNKNOWN** | **HYDRATED**.
2. **FACT** only with `path:line` or command output in Evidence column.
3. Increment gap IDs (`G-01`, `G-02`, …) — do not reuse IDs for different gaps.
4. If FACT and missing from spec → note proposed REQ id in **Req** column as `(proposed REQ-XX-NN)` — **do not edit spec.md** in this skill unless user explicitly asks hydrate in same message.

Update the iteration table after each iter with **honest** outcome (including "0 FACT gaps").

After the loop (or on early stop), recompute **`gaps_pending`**, fill **`## Pending count`** in `GAPS.md`, and use that integer in the chat's mandatory last line (§7).

## 6. Optional spec deltas (proposal only)

After loop, you MAY list **proposed** REQ additions in chat or a short `## Proposed spec deltas` section in `GAPS.md` — bullet list mapping G-xx → draft REQ title. **Do not** implement or edit `spec.md` unless user runs `/mejora-tarea` in a **new** turn.

## 7. Close

Report (in chat, **before** the mandatory last line):

- **Mode** (A or B) and path to `GAPS.md`
- Derived slug (Mode B)
- Iterations run (and early STOP at iter N if applicable)
- Counts: FACT found | HYDRATED | INFERENCE | REJECTED | UNKNOWN
- Table snapshot from `## Pending count` in `GAPS.md`
- Next step: if `gaps_pending > 0` → **`/mejora-tarea <slug>`**; if `gaps_pending = 0` → **`/aplica-tarea <slug>`** (new message)

**Mandatory last line (chat — always last, no text after):**

```text
Gaps pending (mejora + apply): <N>
```

Use the same integer as in `GAPS.md` `## Pending count`. Prohibited to close without this line or with a different number than the file.

**Stop lines (before the mandatory last line, not after):**

Do not implement yet.

No implementes todavía.

Gap analysis complete. Run **`/mejora-tarea <slug>`** or **`/aplica-tarea <slug>`** in a **new** message when ready.

## Related

- `.cursor/rules/openspec-gap-analysis.mdc`
- `.cursor/rules/hazlo-en-modo-multiagente.mdc`
- `.cursor/skills/30-openspec-anti-hallucination/SKILL.md`
- `.cursor/skills/mejora-tarea/SKILL.md` — hydrate after gaps
- `.cursor/skills/aplica-tarea/SKILL.md` — implement after READY
