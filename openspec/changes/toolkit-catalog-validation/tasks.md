# Tasks — toolkit-catalog-validation

Requirement references: **CV** = `specs/catalog-validation/spec.md`, **SR** = `specs/skill-routing/spec.md`. Design decisions: **D1**–**D9** in `design.md`.

## 1. Validator core: entry point, parity, frontmatter (CV)

- [x] 1.1 Create `scripts/validate-toolkit.py` (D1, D2) with the report format and exit-code contract (CV: Single validation entry point; Report every finding in one run); verify with tests for exit `0` on a clean fixture catalog, exit `1` with two findings reported in one run, and exit `0` with warnings only.
- [x] 1.2 Create `scripts/catalog-exceptions.yaml` (D3) declaring the 4 Claude-only skills, the `exporta-spec` command and skill description divergence, and the `openspec` skill group, each with a `reason`; verify the dead-exception and missing-reason tests fail on a fixture and pass on the real file (CV: No dead exceptions).
- [x] 1.3 Implement command-set and skill-set parity honouring exceptions (CV: Command set parity; Skill set parity); verify one passing and one failing test per rule.
- [x] 1.4 Implement cross-tree description parity (CV: Description parity across trees); verify a test where a declared divergence passes and an undeclared one fails showing both texts.
- [x] 1.5 Implement frontmatter presence/YAML validity and allowed/required keys per file kind (CV: Frontmatter validity; Allowed and required frontmatter keys); verify tests for unparseable YAML (unquoted `: `), unknown key `model`, and a rule missing `alwaysApply`.
- [x] 1.6 Implement name = folder, kebab-case names, and skill-folder/group handling (CV: Skill name matches its folder; Skill folders are real skills; D3 groups); verify tests for name drift, a stray folder, and a declared group whose nested skill is validated.
- [x] 1.7 Implement README coverage with token matching (CV: README coverage; D6); verify a test where `qa` appearing only inside another word does not count and `` `qa` `` does.
- [x] 1.8 Implement the two hygiene warnings (CV: Non-blocking hygiene warnings; D8 homonym resolution); verify a test where a stale inner `---` block yields `WARN` and exit `0`.
- [x] 1.9 Write `scripts/test_validate_toolkit.py` with `unittest` + temporary-directory catalogs covering every rule above (CV: The validator is tested); verify `python3 -m unittest scripts/test_validate_toolkit.py` passes locally.

## 2. Validator routing rules (SR)

- [x] 2.1 Implement routing scope: skip skills with `disable-model-invocation: true` for trigger and collision rules only (SR: Routing applies to model-invocable skills only); verify a test with an exempt wrapper and a non-exempt skill.
- [x] 2.2 Implement trigger-clause and 1024-character checks (SR: Description carries a trigger clause; Description length budget; D5); verify tests for a purpose-only description, each of the four accepted phrases, and a 1100-character description.
- [x] 2.3 Implement per-tree TF-IDF collision check with fixed stop-words and thresholds 0.50 / 0.30 as named constants (SR: No colliding descriptions; D4); verify tests for an error pair, a warn pair, and identical scores across two runs.
- [x] 2.4 Implement alias checks: `Deprecated alias of <name>` must be non-invocable, name an existing skill, and have ≤ 15 non-blank body lines (SR: Validator flags an alias that carries content); verify tests for each of the three failures.
- [x] 2.5 Baseline run on the unmodified catalog; save the output to `openspec/changes/toolkit-catalog-validation/evidence/baseline.txt`; verify it shows `ERROR`s for: trigger clause on the 14 non-compliant `.claude` skills and the 10 of them present in `.cursor`; collisions `20-hydrate-spec`↔`20-openspec-hydrate-spec` and `openspec-anti-hallucination`↔`30-openspec-anti-hallucination` in both trees; and the README gaps; and **no** parity, YAML, key or name errors. Any other error is a validator bug or an undeclared asymmetry to resolve before continuing.

## 3. Consolidate duplicate skills (SR)

- [x] 3.1 Replace `.claude/skills/20-hydrate-spec/SKILL.md` and `.cursor/skills/20-hydrate-spec/SKILL.md` with the alias format pointing to `20-openspec-hydrate-spec` (SR: Deprecated alias keeps the name and leaves the router; Canonical members of the duplicate pairs; D7); verify `diff` against the pre-change canonical body shows no workflow content left in the alias.
- [x] 3.2 Same for `openspec-anti-hallucination` → `30-openspec-anti-hallucination` in both trees; verify as in 3.1.
- [x] 3.3 Turn `.cursor/rules/20-hydrate-spec.mdc` and `.cursor/rules/openspec-anti-hallucination.mdc` into pointer rules to their canonical rules, `alwaysApply: false`, same alias description (SR: Deprecated alias…); verify the validator reports no homonym warning for them.
- [x] 3.4 Update the index rows that list both names (`CLAUDE.md` "Qué .mdc leer" table, `.claude/skills/README.md` lines listing `20-hydrate-spec` / `openspec-anti-hallucination`, and the Cursor equivalent) to name the canonical skill and mark the alias as deprecated (SR: Canonical members of the duplicate pairs — scenario "References point to canonical names"); verify `grep -rnP '(?<![\w-])(20-hydrate-spec|openspec-anti-hallucination)(?![\w-])'` outside `openspec/changes/` returns only alias files, index/deprecation notes and the exceptions file.
- [x] 3.5 Run the validator; verify the two collision errors are gone in both trees and no alias error is reported.

## 4. Rewrite routing descriptions (SR)

- [x] 4.1 Rewrite the description of the 12 remaining non-compliant skills — `00-openspec-master`, `00-openspec-orchestrator`, `00-openspec-stack-agnostic`, `10-openspec-refactor-solid`, `20-openspec-hydrate-spec`, `30-openspec-anti-hallucination`, `40-openspec-safe-apply`, `openspec-e2e-regression-guard`, `openspec-extract-spec-from-doc`, `openspec-fix-changes-gitignore`, `openspec-workflow`, `rune-specs` — in every tree where each exists, identical across trees (SR: Description carries a trigger clause; Descriptions say what and when without inventing); for each, record in `evidence/descriptions.md` the old text, the new text and the repo source of every trigger phrase; verify every phrase has a source.
- [x] 4.2 Copy each new description to the homonym `.cursor/rules/<name>.mdc` whose description was identical before (SR: Rule descriptions follow homonym skills); verify the set of homonyms with differing descriptions is still exactly `openspec-gap-analysis`, `40-openspec-safe-apply`, `rune-specs` (validator `WARN` lines).
- [x] 4.3 Run the validator; verify 0 trigger-clause errors, 0 collision errors, and record any new `WARN` pair (≥ 0.30) in `evidence/descriptions.md` with a one-line justification or a further rewrite.
- [x] 4.4 Review the 12 descriptions against the checklist (what + when, no step summary, no invented commands); verify the checklist result is recorded per skill in `evidence/descriptions.md`.

## 5. README coverage (CV)

- [x] 5.1 Add an "All skills" index table at the end of `.claude/skills/README.md` and `.cursor/skills/README.md` with one row per skill folder not mentioned yet (name, one-line purpose taken from its description, `deprecated alias` where applicable) (CV: README coverage; D6); verify the validator reports 0 README errors.

## 6. CI and documentation (CV)

- [x] 6.1 Add `.github/workflows/validate-toolkit.yml` per D9 (CV: CI runs the validator); verify with `python3 -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' .github/workflows/validate-toolkit.yml` and by running its two commands locally in the same order. Remote CI result is verified only after the developer pushes (not part of this change's gate).
- [x] 6.2 Document the validator in `README.md` (how to run, how to add an exception, the description checklist and the "new rule needs a failing-case test" rule) (CV: The validator is tested — review checklist); verify the documented commands run as written.
- [x] 6.3 Update `CLAUDE.md` "Invariantes" so parity, frontmatter and README coverage say they are checked by `scripts/validate-toolkit.py`, add the routing contract in one line, and mark `20-hydrate-spec` / `openspec-anti-hallucination` as deprecated aliases in the topic table; verify the file stays ≤ its current length + 10 lines (it loads in every session).

## 7. Integration check

- [x] 7.1 Run `python3 -m unittest scripts/test_validate_toolkit.py && python3 scripts/validate-toolkit.py` on the final tree; save the output to `evidence/final.txt`; verify exit `0`, 0 errors, and that the only warnings are the 8 stale inner frontmatter blocks, the 3 expected homonym divergences and any pair justified in 4.3.
- [x] 7.2 Confirm no workflow body changed outside the 2 alias skills × 2 trees and 2 alias rules: `git diff --stat` lists only frontmatter-only edits for the 12 skills/rules, the alias files, READMEs, `CLAUDE.md`, `README.md`, `scripts/`, `.github/` and this change folder; verify by `git diff -U0` on the 12 skills showing only `description:` lines.

## Workflow follow-up

- Developer decides commit, push and PR; CI result on GitHub is checked after the push.
- Propagate the new descriptions and aliases with `/exporta-spec` only after the export-pipeline follow-up (design.md → Follow-ups), since bundles are stored copies that already diverge.
- Archive with `/archiva-tarea toolkit-catalog-validation` once the review requirements are met.
