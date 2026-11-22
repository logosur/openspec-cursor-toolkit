# READY TO APPLY — toolkit-catalog-validation

> **Date:** 2026-10-15

## Verdict

**READY TO APPLY** — proposal, design, 2 specs (23 REQ / 36 scenarios) and tasks (29, none done); `openspec validate --strict` passes. See VERIFY.md for gates and the evidence map.

## Scope of the apply

1. Validator core + exceptions + tests (§1) → routing rules (§2) → baseline evidence that the rules bite (2.5).
2. Consolidate `20-hydrate-spec` → `20-openspec-hydrate-spec` and `openspec-anti-hallucination` → `30-openspec-anti-hallucination` as deprecated aliases (§3).
3. Rewrite 12 descriptions with traceable trigger vocabulary (§4), fill README coverage (§5).
4. CI workflow + `README.md` / `CLAUDE.md` docs (§6), final integration run (§7).

## Decisions locked (design.md)

D1 Python 3 + PyYAML, `unittest` · D2 root `scripts/` (not exported) · D3 YAML exceptions with reasons, dead entries fail · D4 TF-IDF cosine per tree, 0.50 error / 0.30 warn · D5 four trigger phrases · D6 README token matching + "All skills" index · D7 alias = pointer with `disable-model-invocation: true`, never delete · D8 homonym divergence is `WARN` · D9 GitHub Actions, read-only permissions.

## Out of scope (follow-ups)

Export pipeline (stored bundle copies, no `.claude/` export, no prune, `CLAUDE.md` path) · stale inner frontmatter in 8 wrappers · behavioural trigger evals.

## Next step

`/aplica-tarea toolkit-catalog-validation` in a new message. Commit, push and PR stay with the developer.
