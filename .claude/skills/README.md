# Claude Code skills (OpenSpec toolkit)

**Stack-agnostic** Claude Code Agent Skills under this tree. Each skill is a folder containing **`SKILL.md`**. Resolve runtime commands (tests, URLs, auth) from the **target project's** stack rule — see [`00-openspec-stack-agnostic/SKILL.md`](00-openspec-stack-agnostic/SKILL.md).

## OpenSpec workflow — mapa OPSX core → alias ES

| OPSX `core` command | ES alias (command) | Invoke | Purpose |
|---------------------|-------------------|--------|---------|
| `openspec propose` | `prepara-tarea` | `/prepara-tarea` | Bootstrap change: EXPLORE → PROPOSE → HYDRATE → VERIFY (no product code). |
| `openspec explore` | — / `opsx-explore` | `/opsx-explore` | Explore mode — thinking / investigation, no implementation. |
| `openspec apply` | `aplica-tarea` | `/aplica-tarea` | Implement tasks from `tasks.md`. |
| `openspec sync` | `mejora-tarea` | `/mejora-tarea` | Hydrate artefacts until READY TO APPLY. |
| — | `openspec-gap-analysis` | `/gaps-spec` **or NL** (`analiza gaps`, `casuísticas faltantes`, …) | Honest gap loop (≤5 iter) → `GAPS.md`; Mode A (change-id) or Mode B (ad-hoc objective); no implementation. |
| — | `repasa-spec` | `/repasa-spec <slug>` **or NL** (`repasa la spec`, `full openspec pipeline`, …) | Sequential pipeline: gaps → hydrate → apply → gaps (multiagent, slug mandatory). |
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

Command entry point: [`.claude/commands/gaps-spec.md`](../commands/gaps-spec.md).

## Full pipeline (`/repasa-spec`)

| Folder / command | Invoke | Purpose |
|------------------|--------|---------|
| [`repasa-spec/`](repasa-spec/SKILL.md) | `/repasa-spec <slug>` **or NL** | Run the full review-and-apply cycle **in strict order**: (1) `/gaps-spec`, (2) `/mejora-tarea`, (3) `/aplica-tarea`, (4) `/gaps-spec`. Unattended multiagent orchestration — **never parallel phases**. Slug required (Mode A only). |
| `repasa-spec` (command) | `/repasa-spec background-permission` | Shortcut for «repasa la spec» / «full openspec pipeline». |

Command entry point: [`.claude/commands/repasa-spec.md`](../commands/repasa-spec.md).

## Related documentation

| Path | Purpose |
|------|---------|
| [`docs/openspec/skills/gap-analysis.md`](../../docs/openspec/skills/gap-analysis.md) | Long-form gap analysis procedure |
| [`docs/openspec/templates/GAPS-template.md`](../../docs/openspec/templates/GAPS-template.md) | Empty `GAPS.md` scaffold |
| [`docs/openspec/templates/GAPS-example.md`](../../docs/openspec/templates/GAPS-example.md) | Real-world example output |
| [`docs/openspec/README.md`](../../docs/openspec/README.md) | Documentation index |

Invoke skills with **`/skill-name`** (explicit) or let Claude auto-invoke them based on the skill's `description` when the conversation matches.

## Open HTML in Chrome (`/html`)

| Folder / command | Invoke | Purpose |
|------------------|--------|---------|
| [`html/`](html/SKILL.md) | `/html` | Open requested artifact as HTML in system Chrome; generate twin from `.md` if missing. |
| `html` (command) | `/html` | Shortcut for «abreme lo que te he pedido en chrome html». |

## Cross-project / stack-agnostic skills

| Folder | Purpose |
|--------|---------|
| [`00-openspec-stack-agnostic/`](00-openspec-stack-agnostic/SKILL.md) | Resolve commands, paths, and URLs from the target project instead of assuming a stack. |
| [`00-openspec-master/`](00-openspec-master/SKILL.md) | Master EXPLORE → PROPOSE → HYDRATE → VERIFY → APPLY → ARCHIVE workflow. |
| [`00-openspec-orchestrator/`](00-openspec-orchestrator/SKILL.md) | OpenSpec orchestration layer (same lifecycle, orchestrator framing). |
| [`10-openspec-refactor-solid/`](10-openspec-refactor-solid/SKILL.md) | OpenSpec refactor workflow for SOLID / Drupal / Symfony / PSR. |
| [`20-hydrate-spec/`](20-hydrate-spec/SKILL.md) / [`20-openspec-hydrate-spec/`](20-openspec-hydrate-spec/SKILL.md) | Hydrate weak proposals until testable. |
| [`30-openspec-anti-hallucination/`](30-openspec-anti-hallucination/SKILL.md) / [`openspec-anti-hallucination/`](openspec-anti-hallucination/SKILL.md) | Prevent invented implementation details. |
| [`40-openspec-safe-apply/`](40-openspec-safe-apply/SKILL.md) | Safe APPLY phase — gates, scope control, evidence-backed completion. |
| [`openspec-e2e-regression-guard/`](openspec-e2e-regression-guard/SKILL.md) | OpenSpec as source of truth for E2E regression protection. |
| [`openspec-extract-spec-from-doc/`](openspec-extract-spec-from-doc/SKILL.md) | Convert a `.doc`/`.docx`/`.odt` ticket reference document into an OpenSpec spec/design/tasks/VERIFY. |
| [`openspec-fix-changes-gitignore/`](openspec-fix-changes-gitignore/SKILL.md) | Optional: decide version vs gitignore for fix-only OpenSpec/E2E artefacts. |
| [`rune-specs/`](rune-specs/SKILL.md) | Optional RUNE specs for business-logic services (PHP-oriented). |
