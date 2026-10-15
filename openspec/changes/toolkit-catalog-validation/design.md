# Design — toolkit-catalog-validation

## Context

See proposal.md for motivation. Facts that shape the approach (measured 2026-10-15 on `develop` @ `583c12a`):

| Fact | Evidence |
|---|---|
| Command sets are identical (24 each); skill sets differ only by the 4 Claude-only skills `CLAUDE.md` documents | `diff <(ls .cursor/skills) <(ls .claude/skills)` |
| Frontmatter keys in use: skills `name`, `description`, `disable-model-invocation` (10), `license`/`compatibility`/`metadata` (4, the `openspec/` group); `.claude/commands` `description`, `argument-hint`; `.cursor/commands` `name`, `id`, `category`, `description` (plus `argument-hint` in `cierra-sesion` since `221d85a`, committed while this design was measured on `583c12a`); rules `description`, `alwaysApply`, `globs` | inventory script over all frontmatter |
| All frontmatter parses as YAML today; every skill `name` equals its folder | PyYAML `safe_load` over all files |
| Only description divergence across trees: `exporta-spec` (command and skill), because Claude has no rules | same script |
| `.claude/skills/openspec/` and `.cursor/skills/openspec/` are group folders with 4 nested skills and no `SKILL.md` | `find` |
| 8 command-wrapper skills repeat a `---` block (`name: /<cmd>`, `id`, `category`) at the top of their body | regex over bodies |
| READMEs omit 10 (`.claude`) / 19 (`.cursor`) skill folders | substring check per folder name |
| TF-IDF cosine over the 24 model-invocable `.claude` descriptions: duplicates 0.66 and 0.57; next pair 0.29; then ≤ 0.24 | ad-hoc stdlib script (same algorithm as Decision 4) |
| Local runtime: Python 3 with PyYAML 6.0.1, Node 24; no `yq` | `python3 -c 'import yaml'`, `node --version` |
| No `.github/workflows/`; remote is `github.com/logosur/openspec-cursor-toolkit` | `ls`, `git remote -v` |
| The exporter reads **copies** under `ai-developer/templates/openspec-cursor/<bundle>/`, never this repo; no manifest exports a `.claude/` path; in `openspec-core` 10 of 35 copies already differ from this repo; the script has no delete/prune logic | `exporta-spec.sh` lines 119–160, `cmp` per manifest entry |

## Goals / Non-Goals

**Goals:**
- One fast, dependency-light validator whose rules mirror the invariants `CLAUDE.md` already states, plus the routing contract.
- Zero false errors on the catalog after this change; every intentional asymmetry recorded once, with its reason.
- Catalog fixes limited to frontmatter, alias bodies and documentation.

**Non-Goals:**
- Behavioural (LLM-graded) evals or a prompt corpus for trigger ranking — that is idea 4 of the review, a later change.
- Fixing the export pipeline (bundle copies, missing `.claude/` export, no prune, `CLAUDE.md` naming `templates/openspec-claude/` which does not exist). Recorded under Risks as a follow-up.
- Removing the stale inner frontmatter of the 8 wrapper skills: reported as `WARN` only, cleaned in a follow-up so this change does not touch workflow bodies.
- Rewriting skill bodies, merging `00-openspec-master` / `00-openspec-orchestrator` / `openspec-workflow` (they overlap in purpose but score ≤ 0.12; distinct descriptions are enough here).
- Changing the skills in `~/.claude/skills/` or in consumer projects.

## Decisions

### 1. Python 3 + PyYAML, single file, stdlib `unittest`
Frontmatter must be validated as real YAML (Claude Code parses it; a hand-rolled `key: value` reader would accept invalid files). Python with PyYAML is installed locally and is one `pip install pyyaml` on GitHub's Ubuntu runners; tests need only `unittest`.
*Alternatives:* Node (as agent-skills does) — no YAML parser in the standard library, so it needs an npm dependency and a `package.json` in a repo that has none; Bash + `yq` — `yq` is not installed and Bash makes the similarity metric awkward.

### 2. Root `scripts/`, not `.claude/scripts` or `.cursor/scripts`
`.{claude,cursor}/scripts/` hold tooling that is exported to consumers (`openspec-list.sh`). The validator is contributor tooling for this repository only, so it lives in a new root `scripts/` that no bundle manifest references. Files: `scripts/validate-toolkit.py`, `scripts/test_validate_toolkit.py`, `scripts/catalog-exceptions.yaml`.

### 3. Declared exceptions in YAML, each with a reason, dead ones are errors
```yaml
claude_only_skills:
  - name: 00-openspec-stack-agnostic
    reason: Cursor ships it as an always-loaded rule (.cursor/rules/00-openspec-stack-agnostic.mdc)
  # … the other three
description_divergence:
  - kind: command   # or skill
    name: exporta-spec
    reason: Cursor exports rule bundles; Claude Code has no rules
skill_groups:
  - name: openspec
    reason: OpenSpec CLI skills grouped as installed by the CLI
```
Keeping exceptions in data, not code, means a reviewer sees every asymmetry in one diff. The "no dead exceptions" rule stops the file from becoming a graveyard.
*Alternative:* inline allow-lists in the script — invisible to reviewers of catalog changes.

### 4. Collision metric: TF-IDF cosine per tree, thresholds 0.50 error / 0.30 warn
Tokens: lowercase `[a-z0-9áéíóúñ]+`, length > 2, minus a fixed English+Spanish stop-word list stored in the script; weight `tf × ln((1+N)/(1+df))` where `N` is the number of model-invocable skills in the tree. Thresholds come from the measured distribution: the two true duplicates sit at 0.57–0.66, every distinct pair at ≤ 0.29, so 0.50 separates them with margin and 0.30 flags drift early. These numbers are specific to this metric and corpus; agent-skills uses 0.75/0.50 on a different metric, which is why they are not copied.
*Alternatives:* embedding similarity — needs a model or network, not deterministic in CI; Jaccard on word sets — measured on the same corpus it separates about as well today (duplicates 0.50–0.60, next pair 0.23), but it weighs every shared word equally; once descriptions are rewritten, words that nearly every skill carries (`openspec`, `spec`, `change`) would inflate every pair, while IDF discounts them.

### 5. Trigger clause as a phrase list
`Use when` / `Use on` / `Auto-invoke on` / `Triggers on`, case-insensitive — the four forms already used by the descriptions that route well today (`exporta-spec`, `qa`, `cierra-sesion`, `openspec-gap-analysis`). A mechanical check cannot judge quality; the "what + when, no step summary, vocabulary from the repo" requirement is enforced at review with the checklist in the validator's documentation.

### 6. README coverage matches the folder name as a token
A skill counts as mentioned when its folder name appears delimited by backticks, a `/` or a link target (`` `qa` ``, `qa/`, `(qa/SKILL.md)`), not as a bare substring — so `qa` is not "found" inside another word. Missing entries are added as rows in an "All skills" index table at the end of each README, leaving the curated sections intact.

### 7. Alias format
```markdown
---
name: 20-hydrate-spec
description: Deprecated alias of 20-openspec-hydrate-spec. Kept so existing references and exported copies keep resolving; do not invoke.
disable-model-invocation: true
---

# 20-hydrate-spec (deprecated alias)

This skill was merged into `20-openspec-hydrate-spec`. Read and follow `.claude/skills/20-openspec-hydrate-spec/SKILL.md`.
```
(`.cursor/` variant points to `.cursor/skills/…`; the homonym `.mdc` rule keeps `alwaysApply: false` and points to `.cursor/rules/20-openspec-hydrate-spec.mdc`.) Deleting was rejected: the exporter cannot delete, so consumers would keep a full stale copy that still routes; a pointer that the next export overwrites converges them instead.

### 8. Homonym rule comparison
For `.cursor/rules/<x>.mdc`, the homonym skill is `.cursor/skills/<x>/` if it exists, otherwise `.claude/skills/<x>/` (the four Claude-only skills). Divergence is `WARN`, not `ERROR`, because three pairs legitimately differ today (`openspec-gap-analysis`, `40-openspec-safe-apply`, `rune-specs`).

### 9. CI
`.github/workflows/validate-toolkit.yml`: on `push` and `pull_request`; `ubuntu-latest`; `actions/setup-python` (3.12) → `pip install pyyaml` → `python -m unittest scripts/test_validate_toolkit.py` → `python scripts/validate-toolkit.py`. No secrets, no write permissions (`permissions: contents: read`).

## Risks / Trade-offs

- **Descriptions are rewritten here but consumers keep the old ones** → the change only fixes the source; propagation needs the export pipeline, which today copies from diverged bundles and never exports `.claude/`. Follow-up change (export from this repo, include `.claude/`, add prune) is recorded below; this change does not claim consumer impact.
- **Lexical similarity misses semantic collisions** (different words, same intent) → acceptable for a CI gate; idea 4 (behavioural trigger evals) is the semantic layer.
- **Thresholds tuned on today's corpus may misfire as the catalog grows** → they live as named constants with this design's rationale; raising or lowering them is a reviewed change, never a fix to make CI green.
- **Rewritten descriptions can shift routing in unwanted ways** → Spanish trigger phrases are taken from existing docs, and the collision check runs on the result; descriptions of `disable-model-invocation` wrappers are untouched.
- **CI on GitHub requires a push the developer authorizes** → until then the validator runs locally; the workflow file is inert in the working tree.
- **Another session is editing `cierra-sesion` and exporting `repasa-spec` concurrently (2026-10-15)** → this change touches neither skill's files; apply must re-run the validator after rebasing on whatever they commit.

## Migration Plan

1. Land validator + tests + exceptions with the current catalog: expected errors are exactly the routing errors and README gaps listed in tasks.md (proves the rules bite).
2. Consolidate duplicates, rewrite descriptions, fill READMEs until the validator reports 0 errors.
3. Add CI and documentation.
Rollback: revert the commit(s); no runtime, data or consumer state is involved.

## Follow-ups (not in this change)

- Export pipeline: build bundles from this repo instead of stored copies, export `.claude/` trees, add prune for removed files, fix `CLAUDE.md`'s reference to `templates/openspec-claude/`.
- Remove the stale inner frontmatter from the 8 command-wrapper skills (`WARN` today).
- Trigger evals with positive/negative prompts per skill (idea 4).
