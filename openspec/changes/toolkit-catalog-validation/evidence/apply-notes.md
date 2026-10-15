# Apply notes — toolkit-catalog-validation (2026-10-15)

Facts recorded during `/aplica-tarea`, on `develop` @ `221d85a` plus this change's working tree.

## Deviations from the prepared plan

| Planned | Found | Resolution |
|---|---|---|
| `.cursor/commands` keys: `name`, `id`, `category`, `description` (measured on `583c12a`) | `221d85a`, committed while the design was being measured, added `argument-hint` to `.cursor/commands/cierra-sesion.md` | The requirement allows «only the keys its tree uses today», so `argument-hint` joins the allowed set for `.cursor/commands`. Spec delta and design table updated; `openspec validate --strict` passes. Without it the baseline would have reported one `keys` error for that file. |
| TF-IDF duplicates 0.66 / 0.57, next pair 0.29 (ad-hoc script) | With the validator's fixed stop-word list: 0.57 / 0.58 (`.claude`), 0.57 / 0.57 (`.cursor`); next pair `20-openspec-hydrate-spec`↔`30-openspec-anti-hallucination` 0.33 (`WARN`), driven by the shared suffix «numbered OpenSpec series» | Both duplicates stay above 0.50, so the thresholds hold. The 0.33 pair disappeared once the aliases left the corpus and both descriptions were rewritten (final top pair 0.25). |
| «8 stale inner frontmatter blocks» | 8 wrapper skills × 2 trees = 16 `WARN` lines (`aplica-tarea`, `archiva-tarea`, `mejora-tarea`, `opsx-apply`, `opsx-archive`, `opsx-explore`, `opsx-propose`, `prepara-tarea`) | Same 8 skills; the count in tasks.md is per tree. Left as `WARN` (design non-goal). |
| `CLAUDE.md` ≤ 59 + 10 lines | 62 lines | Within budget. |
| Task 3.4 «the Cursor equivalent» index rows | `.cursor/skills/README.md` had no row for either pair | The aliases and canonicals appear in its new «All skills» table, with `Deprecated alias` marked (task 5.1). |

## Test quality

Mutation check (scratch script, not committed): 17 mutants of `validate-toolkit.py` — each disables or loosens one rule (thresholds, README delimiters, alias checks, parity, missing reason, inner-block keys, routing scope, trigger phrases, length, name drift, unknown keys, dead exceptions, description parity, homonym rule, groups). All 17 make at least one test fail.

## Scope check (task 7.2)

- The 12 rewritten skills and their 10 updated homonym rules: 30 files changed, 30 lines added and 30 deleted. Every changed line is a `description:` line (`git diff -U0` filtered).
- Alias bodies: `20-hydrate-spec` and `openspec-anti-hallucination` in both skill trees, plus their two Cursor rules. No line of the canonical body survives in them.
- Docs: `README.md`, `CLAUDE.md`, `.claude/skills/README.md`, `.cursor/skills/README.md`. New files: `scripts/`, `.github/workflows/validate-toolkit.yml` and this change folder.
- **Not part of this change:** the working tree also has edits to the `exporta-spec` bundle (`.claude/commands/exporta-spec.md`, `.claude/skills/exporta-spec/SKILL.md`, `.cursor/commands/exporta-spec.md`, `.cursor/skills/exporta-spec/SKILL.md`, `.cursor/rules/comando-exporta-spec.mdc`). They add «exclusion list» and «drift» sections and were written at 17:32 by another session. This apply did not touch them. They change no `description`, and the final validator run (17:39) already includes them, still with 0 errors. Commit them separately from this change.
