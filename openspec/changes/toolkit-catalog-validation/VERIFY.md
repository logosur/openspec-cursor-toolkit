# VERIFY — toolkit-catalog-validation

> **Date:** 2026-10-15 · `develop` @ `583c12a` · bootstrap by `/prepara-tarea` (no implementation).

## Gates

| Gate | Command / check | Result |
|------|-----------------|--------|
| Artefacts present | `ls openspec/changes/toolkit-catalog-validation/` | `proposal.md`, `design.md`, `specs/catalog-validation/spec.md`, `specs/skill-routing/spec.md`, `tasks.md`, `VERIFY.md`, `READY-TO-APPLY.md` |
| `openspec validate toolkit-catalog-validation --strict` | run in this repo (OpenSpec CLI 1.14.1) | `Change 'toolkit-catalog-validation' is valid` |
| `openspec status --change toolkit-catalog-validation --json` | same | `isPlanningComplete: true`; proposal/specs/design/tasks `done` |
| Spec inventory | `grep -c '^### Requirement'` / `'^#### Scenario'` | catalog-validation 14 REQ / 21 scenarios · skill-routing 9 REQ / 15 scenarios |
| Requirement → task coverage | every `### Requirement:` title searched in `tasks.md` | 23 / 23 cited |
| Tasks | `grep -c '^- \[ \]' tasks.md` | 29 open, 0 done (nothing implemented) |
| Product files untouched | `git status --short` outside `openspec/changes/toolkit-catalog-validation/` | no changes |

## Evidence map

| Claim | Class | Evidence |
|-------|-------|----------|
| No validation script and no CI exist | FACT | `find . -name '*.sh'` → only `openspec-list.sh` ×2; no `.github/` |
| Command sets identical (24/24); skill sets differ only by `00-openspec-stack-agnostic`, `openspec-e2e-regression-guard`, `openspec-extract-spec-from-doc`, `openspec-fix-changes-gitignore` | FACT | `diff <(ls .cursor/commands) <(ls .claude/commands)`; same for `skills` |
| Frontmatter keys per file kind (see design Context) | FACT | inventory script over `.c*/skills/**/SKILL.md`, `.c*/commands/*.md`, `.cursor/rules/*.mdc` |
| All frontmatter parses as YAML; all skill names equal folder names | FACT | PyYAML `safe_load`; name/folder comparison |
| Only cross-tree description divergence: `exporta-spec` (command + skill) | FACT | description comparison script |
| 10 skills set `disable-model-invocation: true` (the ES/OPSX command wrappers + `repasa-spec`, `run-spec`) | FACT | same inventory |
| 8 wrappers carry a second `---` block in their body | FACT | regex over bodies |
| 14 of 24 model-invocable `.claude` skills lack a trigger clause | FACT | grep for `use when|auto-invoke|use on|triggers` on each description |
| `20-hydrate-spec` ≡ `20-openspec-hydrate-spec`, `openspec-anti-hallucination` ≡ `30-openspec-anti-hallucination` except name/description/trailing newline | FACT | `diff` → 6 lines each |
| Numbered names are the ones referenced by other skills/rules; unnumbered only in index tables | FACT | `grep -rnP '(?<![\w-])<name>(?![\w-])'` per name |
| TF-IDF cosine: duplicates 0.66 / 0.57, next pair 0.29; Jaccard: 0.60 / 0.50, next 0.23 | FACT | stdlib scripts over the 24 descriptions |
| READMEs omit 10 (`.claude`) / 19 (`.cursor`) skill folders | FACT (substring check; token check in task 1.7 may differ slightly) | per-folder search in each `skills/README.md` |
| The 4 Claude-only skills share their description with their Cursor rule | FACT | per-pair comparison |
| Homonym rule/skill descriptions differ today for `openspec-gap-analysis`, `40-openspec-safe-apply`, `rune-specs` | FACT | same |
| Exporter reads stored copies in `ai-developer/templates/openspec-cursor/`, exports no `.claude/` path, has no delete logic; 10 of 35 `openspec-core` copies differ from this repo | FACT | `exporta-spec.sh` lines 119–160; `grep '^\.claude'` over manifests → 0; `cmp` per entry |
| `CLAUDE.md` names `templates/openspec-claude/`, which does not exist | FACT | `ls ai-developer/templates/` → `agents-md`, `aula-intranet`, `openspec-cursor` |
| Python 3 + PyYAML 6.0.1 available locally; available on GitHub Ubuntu runners via `pip` | FACT (local) / INFERENCE (runner) | `python3 -c 'import yaml'`; runner image not inspected |
| A one-clause description change can move routing from 7/27 to 21/27 fires | FACT about agent-skills (claude-opus-5-5, their corpus) / INFERENCE for this toolkit | `agent-skills/evals/README.md` "Plugin evals" |
| Claude Code discovers skills nested in `skills/openspec/*/` | UNKNOWN | not tested; the validator treats `openspec/` as a declared group either way, so it does not block |
| Another session is editing `cierra-sesion` and exporting `repasa-spec` today | FACT (peer message, 2026-10-15) | this change touches neither; apply re-runs the validator after rebasing |

## Requirement → task coverage

| Requirement | Tasks |
|-------------|-------|
| CV Single validation entry point | 1.1, 7.1 |
| CV Report every finding in one run | 1.1 |
| CV Command set parity | 1.3 |
| CV Skill set parity | 1.2, 1.3 |
| CV Description parity across trees | 1.2, 1.4 |
| CV Frontmatter validity | 1.5 |
| CV Allowed and required frontmatter keys | 1.5 |
| CV Skill name matches its folder | 1.6 |
| CV Skill folders are real skills | 1.6 |
| CV README coverage | 1.7, 5.1 |
| CV No dead exceptions | 1.2 |
| CV Non-blocking hygiene warnings | 1.8 |
| CV The validator is tested | 1.9, 6.2 |
| CV CI runs the validator | 6.1 |
| SR Routing applies to model-invocable skills only | 2.1 |
| SR Description carries a trigger clause | 2.2, 4.1 |
| SR Description length budget | 2.2 |
| SR No colliding descriptions | 2.3, 3.5, 4.3 |
| SR Descriptions say what and when without inventing | 4.1, 4.4 |
| SR Rule descriptions follow homonym skills | 4.2 |
| SR Deprecated alias keeps the name and leaves the router | 3.1, 3.2, 3.3 |
| SR Canonical members of the duplicate pairs | 3.1, 3.4 |
| SR Validator flags an alias that carries content | 2.4 |

## Verification status

**READY TO APPLY** — every requirement is testable and mapped; no UNKNOWN changes the approach. Remote CI (task 6.1) can only be confirmed after a push the developer authorizes, and is outside this change's gate.
