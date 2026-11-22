# Proposal — toolkit-catalog-validation

> **Created by:** `/prepara-tarea toolkit-catalog-validation` — 2026-10-15
> **Origin:** ideas 1–3 from the review of [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) (v0.6.13): mechanical validation + CI, routing-grade skill descriptions, consolidation of duplicate skills.
> **Status:** EXPLORE → PROPOSE → HYDRATE → VERIFY; **no implementation in this turn**.

## Why

The toolkit's catalog rules live only as prose in `CLAUDE.md` ("Paridad `.cursor/` ↔ `.claude/`", "README al día", "Frontmatter: … skills `name` + `description` con triggers"), and nothing checks them: there is no validation script and no CI (FACT: no `.github/workflows/`, no script besides `openspec-list.sh`). Measured today:

- **Routing is weak.** 14 of the 24 model-invocable skills in `.claude/skills/` have a `description` with no trigger condition (e.g. `00-openspec-orchestrator`: "OpenSpec orchestration layer"). Agents pick skills by description; agent-skills measured that one trigger clause moved a skill from 7/27 to 21/27 fires with 0 false positives.
- **Two skills are copies of two others.** `20-hydrate-spec` ≡ `20-openspec-hydrate-spec` and `openspec-anti-hallucination` ≡ `30-openspec-anti-hallucination` differ only in `name`/`description` and a trailing newline (FACT: `diff` = 6 lines each). Both copies of each pair compete for the same requests and are both exported to consumers.
- **Prose invariants already drift.** The skills READMEs omit 10 (`.claude`) and 19 (`.cursor`) skill folders although `CLAUDE.md` says they are kept up to date; 8 command-wrapper skills carry a second, stale frontmatter block inside their body.

Each rule broken silently ships to every consumer project on the next `/exporta-spec`. Making the rules executable now, while the catalog still passes most of them, is cheap; later it is an archaeology job.

## What Changes

- **New contributor tool** `scripts/validate-toolkit.py` (Python 3 + PyYAML) with its own unit tests, that checks the catalog and exits non-zero on any error:
  - parity of the command set and skill set between `.cursor/` and `.claude/`, honouring a declared exception list (the 4 Claude-only skills, the `exporta-spec` description divergence);
  - frontmatter is valid YAML, has the required keys per file kind, `name` equals the folder name, kebab-case names;
  - every skill folder under `skills/` is listed in that tree's `README.md`;
  - routing contract for model-invocable skills (see below);
  - warnings (non-blocking) for a second frontmatter block inside a skill body and for homonym rule/skill description divergence.
- **New declared-exceptions file** `scripts/catalog-exceptions.yaml`, the single place where an intentional asymmetry is recorded with its reason. An exception that no longer matches anything is itself an error (no dead exceptions).
- **New CI workflow** `.github/workflows/validate-toolkit.yml` running the validator and its tests on push and pull request.
- **Routing contract for descriptions** (enforced by the validator, applied to every skill without `disable-model-invocation: true`): a trigger clause (`Use when` / `Use on` / `Auto-invoke on` / `Triggers on`), ≤ 1024 characters, and no pair of descriptions at or above the collision threshold (0.50 TF-IDF cosine; warning at 0.30).
- **Rewrite the 12 descriptions that fail the contract** after consolidation, in both trees, using vocabulary already present in the repo (READMEs, commands, `CLAUDE.md`), keeping homonym `.mdc` rule descriptions equal where they are equal today.
- **Consolidate the two duplicate pairs**: `20-openspec-hydrate-spec` and `30-openspec-anti-hallucination` stay canonical; `20-hydrate-spec` and `openspec-anti-hallucination` become **deprecated aliases** — a few-line pointer with `disable-model-invocation: true` (out of the router, name still resolves), in skills and in homonym Cursor rules. No folder is deleted.
- **Bring the two skills READMEs to full coverage** and document the validator in `README.md` and `CLAUDE.md` (replacing "mantener a mano" with "lo comprueba `scripts/validate-toolkit.py`").

## Capabilities

### New Capabilities

- `catalog-validation`: executable validation of the toolkit catalog — parity, frontmatter, README coverage, declared exceptions, exit codes, CI.
- `skill-routing`: the contract a model-invocable skill description must satisfy (trigger clause, length, no collisions) and the deprecated-alias policy that takes duplicates out of routing without breaking their names.

### Modified Capabilities

- None. The promoted specs `comando-verificar` and `multiagent-apply-validation` are untouched.

## Impact

- **Toolkit files:** new `scripts/` (validator, tests, exceptions), new `.github/workflows/validate-toolkit.yml`; frontmatter of ~12 skills × 2 trees and their homonym rules; bodies of 2 skills × 2 trees and 2 rules (alias pointers); `README.md`, `CLAUDE.md`, `.claude/skills/README.md`, `.cursor/skills/README.md`.
- **No behaviour change in any workflow body.** Only frontmatter descriptions, alias bodies and documentation change; every skill name that exists today still exists.
- **Consumers:** nothing to do. Deprecated aliases keep resolving in projects that already have them. Propagation of the new descriptions is a separate `/exporta-spec` step (out of scope; see design.md — the export bundles are copies that already diverge from this repo).
- **Dependencies:** Python 3 and PyYAML for contributors and CI only; nothing is exported to consumers.
- **Git:** this change does not authorize commit, push or PR; those stay with the developer.
