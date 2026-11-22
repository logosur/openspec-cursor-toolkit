# Description rewrite — toolkit-catalog-validation (tasks 4.1–4.4)

Contract: `specs/skill-routing/spec.md` → «Description carries a trigger clause», «Descriptions say what and when without inventing», «Rule descriptions follow homonym skills».
Every new description is identical in every tree where the skill exists. Quotes in the source column are from the file named, read on 2026-10-15.

## `00-openspec-master`

- **Files:** `.claude` + `.cursor` skills + `.cursor/rules` rule.
- **Old:** Master OpenSpec workflow for creating strong implementation specifications
- **New:** Full OpenSpec lifecycle for strong implementation specifications, ending in a verify verdict (READY TO APPLY, NEEDS HYDRATION, BLOCKED BY UNKNOWN or UNSAFE TO APPLY) before any code is written. Use when the user asks to create, improve, audit, hydrate or implement a feature, bugfix, refactor, test strategy, API, webhook or backend flow using OpenSpec, or asks for a spec fuerte.

| Phrase (trigger or claim) | Repo source |
|---|---|
| create, improve, audit, hydrate or implement a feature, bugfix, refactor, test strategy, API, webhook or backend flow using OpenSpec | `.claude/skills/00-openspec-master/SKILL.md` line 6 |
| READY TO APPLY / NEEDS HYDRATION / BLOCKED BY UNKNOWN / UNSAFE TO APPLY; before any code | `.claude/skills/00-openspec-master/SKILL.md` «VERIFY» and «Default behavior» |
| strong implementation specifications | previous description |
| spec fuerte | `CLAUDE.md` topic table, row «Spec fuerte / workflow» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ (names the verdict, not the six phases) · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (380).

## `00-openspec-orchestrator`

- **Files:** `.claude` + `.cursor` skills + `.cursor/rules` rule.
- **Old:** OpenSpec orchestration layer
- **New:** Default gate that sends change requests through OpenSpec instead of coding straight away; only a trivial direct change the user explicitly asks for skips it. Use when the user asks for a change, tests or TDD validation and has not asked to implement directly.

| Phrase (trigger or claim) | Repo source |
|---|---|
| sends change requests through OpenSpec | `.claude/skills/00-openspec-orchestrator/SKILL.md` line 6 «use the OpenSpec workflow» |
| a change, tests or TDD validation | `.claude/skills/00-openspec-orchestrator/SKILL.md` line 6 |
| trivial direct change the user explicitly asks for; has not asked to implement directly | `.claude/skills/00-openspec-orchestrator/SKILL.md` «Do not implement code immediately unless the user explicitly asks for a trivial direct change» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (259).

## `00-openspec-stack-agnostic`

- **Files:** `.claude` skill + `.cursor/rules` rule.
- **Old:** OpenSpec toolkit is stack-agnostic — resolve commands, paths, and URLs from the target project
- **New:** Keeps the OpenSpec toolkit stack-agnostic: base URL, auth helper, test, lint and build commands come from the target project's own docs (CLAUDE.md, README.md, Makefile, package.json, compose files), never from toolkit examples or another project. Use when a skill needs a runtime command, URL, path or E2E auth in a consuming project, or that project documents no local dev flow (nunca hardcodear host/puerto).

| Phrase (trigger or claim) | Repo source |
|---|---|
| base URL, auth helper, test, lint and build commands; CLAUDE.md, README.md, Makefile, package.json, compose files | `.claude/skills/00-openspec-stack-agnostic/SKILL.md` «Before runtime commands» |
| never from toolkit examples or another project | `.claude/skills/00-openspec-stack-agnostic/SKILL.md` «not from examples in this toolkit», «never hardcode host/port from another project» |
| runtime command, URL, path or E2E auth | `.claude/skills/00-openspec-stack-agnostic/SKILL.md` «Before runtime commands», «Path vocabulary», «URL and auth» (Multi-role / E2E auth) |
| documents no local dev flow | `.claude/skills/00-openspec-stack-agnostic/SKILL.md` «If the project has no documented local dev flow» |
| nunca hardcodear host/puerto | `CLAUDE.md` «Invariantes»: «Nunca hardcodear host/puerto/comandos ajenos» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (410).

## `10-openspec-refactor-solid`

- **Files:** `.claude` + `.cursor` skills + `.cursor/rules` rule.
- **Old:** OpenSpec refactor workflow for SOLID, DI, and test-backed internal improvements (stack-agnostic)
- **New:** Plans SOLID and dependency-injection refactors of project-owned code as an OpenSpec change, keeping external behaviour unchanged and vendor/contrib code untouched. Use when the user asks to refactor custom code, improve architecture, apply SOLID, improve dependency injection, create interfaces or remove bad practices (refactor SOLID/DI).

| Phrase (trigger or claim) | Repo source |
|---|---|
| refactor custom code, improve architecture, apply SOLID, improve dependency injection, create interfaces, remove bad practices | `.claude/skills/10-openspec-refactor-solid/SKILL.md` line 6 |
| external behaviour unchanged, vendor/contrib untouched, project-owned code | `.claude/skills/10-openspec-refactor-solid/SKILL.md` «Refactor rules», «Scope by default» |
| refactor SOLID/DI | `CLAUDE.md` topic table, row «Refactor SOLID/DI» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (339).

## `20-openspec-hydrate-spec`

- **Files:** `.claude` + `.cursor` skills + `.cursor/rules` rule.
- **Old:** Hydrate weak OpenSpec proposals until testable (numbered OpenSpec series)
- **New:** Hydrates a weak OpenSpec proposal until every requirement can fail a test: measurable criteria, GIVEN/WHEN/THEN scenarios, edge and failure cases, source-of-truth references and small ordered tasks. Use when a proposal is vague, incomplete, risky or not testable, or the user asks to hidratar proposals.

| Phrase (trigger or claim) | Repo source |
|---|---|
| vague, incomplete, risky or not testable | `.claude/skills/20-openspec-hydrate-spec/SKILL.md` line 6 |
| every requirement can fail a test; measurable criteria | `.claude/skills/20-openspec-hydrate-spec/SKILL.md` «requirements that cannot fail a test», «without measurable criteria» |
| GIVEN/WHEN/THEN scenarios, edge and failure cases, source-of-truth references, small ordered tasks | `.claude/skills/20-openspec-hydrate-spec/SKILL.md` «Hydration means adding» |
| hidratar proposals | `CLAUDE.md` topic table, row «Hidratar proposals» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (303).

## `30-openspec-anti-hallucination`

- **Files:** `.claude` + `.cursor` skills + `.cursor/rules` rule.
- **Old:** Prevent invented implementation details during OpenSpec work (numbered OpenSpec series)
- **New:** Forbids inventing class names, services, endpoints, tables, statuses, response codes, config keys, test names or log fields in OpenSpec work: each one is verified in code, config, tests, docs or provided logs, or marked NOT VERIFIABLE, and claims are labelled FACT, INFERENCE, HYPOTHESIS or UNKNOWN. Use when a spec, design or task names a concrete implementation detail (anti-alucinación).

| Phrase (trigger or claim) | Repo source |
|---|---|
| class names, services, endpoints, tables, statuses, response codes, config keys, test names, log fields | `.claude/skills/30-openspec-anti-hallucination/SKILL.md` «must not invent» |
| verified in code, config, tests, docs or provided logs; NOT VERIFIABLE | `.claude/skills/30-openspec-anti-hallucination/SKILL.md` «verify them in» list and label |
| FACT, INFERENCE, HYPOTHESIS, UNKNOWN | `.claude/skills/30-openspec-anti-hallucination/SKILL.md` last block |
| a spec, design or task names a concrete implementation detail | `.claude/skills/30-openspec-anti-hallucination/SKILL.md` «Before using any of those elements, it must verify them» (paraphrase of when the check applies) |
| anti-alucinación | `CLAUDE.md` topic table, row «Anti-alucinación» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (390).

## `40-openspec-safe-apply`

- **Files:** `.claude` + `.cursor` skills (rule kept: it already differed).
- **Old:** Safe APPLY phase for OpenSpec — gates, scope control, and evidence-backed completion
- **New:** Keeps the APPLY step of an OpenSpec change inside its scope: it starts only after VERIFY returns READY TO APPLY, allows no drive-by refactors or weakened tests, stops when code contradicts the spec, and closes only with passing checks or recorded deferrals. Use when implementing an approved change or deciding whether an apply is complete (apply seguro, scope, evidencia).

| Phrase (trigger or claim) | Repo source |
|---|---|
| APPLY step; only after VERIFY returns READY TO APPLY | `.claude/skills/40-openspec-safe-apply/SKILL.md` line 6 and «Preconditions» |
| no drive-by refactors or weakened tests; stops when code contradicts the spec | `.claude/skills/40-openspec-safe-apply/SKILL.md` «Implementation rules» 2–4 |
| closes only with passing checks or recorded deferrals; deciding whether an apply is complete | `.claude/skills/40-openspec-safe-apply/SKILL.md` «Completion criteria» |
| apply seguro, scope, evidencia | `CLAUDE.md` topic table, row «Apply seguro, scope, evidencia» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ (states conditions (start, stop, close), not the task sequence) · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (373).

## `openspec-e2e-regression-guard`

- **Files:** `.claude` skill + `.cursor/rules` rule.
- **Old:** Use OpenSpec as the source of truth for E2E regression protection. Never weaken E2E assertions to make tests pass; surface conflicts instead of resolving them silently.
- **New:** Treats OpenSpec as the source of truth for E2E tests: assertions are never weakened, skipped or rewritten to get green, and code, tests and spec that disagree are surfaced to the user instead of being resolved silently. Use when an application change touches flows covered by E2E tests or an E2E test fails (E2E regresión).

| Phrase (trigger or claim) | Repo source |
|---|---|
| OpenSpec as the source of truth for E2E tests; never weakened, skipped or rewritten | `.claude/skills/openspec-e2e-regression-guard/SKILL.md` intro and «Strict rules» 1 |
| surfaced to the user instead of being resolved silently | `.claude/skills/openspec-e2e-regression-guard/SKILL.md` «Golden rule» |
| application change touches flows covered by E2E tests; an E2E test fails | `.claude/skills/openspec-e2e-regression-guard/SKILL.md` «Mandatory workflow when changing application code» 1, 3, 4 |
| E2E regresión | `CLAUDE.md` topic table, row «E2E regresión» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (323).

## `openspec-extract-spec-from-doc`

- **Files:** `.claude` skill + `.cursor/rules` rule.
- **Old:** How to convert a .doc/.docx/.odt ticket reference document (text + screenshots) into a precise OpenSpec spec/design/tasks/VERIFY
- **New:** Converts a .doc, .docx or .odt ticket reference document (text plus annotated screenshots, PDF as a last resort) into a precise OpenSpec proposal, design, spec, tasks and VERIFY, analysing every image and inferring nothing the document does not say. Use when the developer attaches or points to such a document as the source of truth for a ticket, for example with prepara-tarea or mejora-tarea (spec desde .doc/.docx).

| Phrase (trigger or claim) | Repo source |
|---|---|
| .doc, .docx or .odt ticket reference document, text plus annotated screenshots, PDF as a last resort | `.claude/skills/openspec-extract-spec-from-doc/SKILL.md` intro («o PDF como fallback», «.pdf como último recurso») |
| proposal, design, spec, tasks and VERIFY | `.claude/skills/openspec-extract-spec-from-doc/SKILL.md` intro (output list) |
| analysing every image; inferring nothing the document does not say | `.claude/skills/openspec-extract-spec-from-doc/SKILL.md` «Reglas duras» |
| attaches or points to such a document as the source of truth; prepara-tarea or mejora-tarea | `.claude/skills/openspec-extract-spec-from-doc/SKILL.md` «Cuándo usar esta regla» |
| spec desde .doc/.docx | `CLAUDE.md` topic table, row «Spec desde .doc/.docx» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (419).

## `openspec-fix-changes-gitignore`

- **Files:** `.claude` skill + `.cursor/rules` rule.
- **Old:** OpenSpec and E2E fix artifacts — gitignore by content (optional; adapt paths in your app repo)
- **New:** Decides from their content whether an OpenSpec change or E2E spec is ticket-scoped fix evidence (gitignored) or a product feature (versioned), and asks when it is mixed; optional, paths adapted per application repo. Use when about to git add an openspec/changes/<slug>/ folder or a ticket-scoped E2E spec (gitignore artefactos).

| Phrase (trigger or claim) | Repo source |
|---|---|
| decides from their content; fix evidence gitignored, feature versioned; asks when mixed | `.claude/skills/openspec-fix-changes-gitignore/SKILL.md` intro, «Classify as fix», «Classify as feature», «Agent obligation» |
| optional, paths adapted per application repo | `.claude/skills/openspec-fix-changes-gitignore/SKILL.md` «Optional skill… adapt E2E paths» |
| about to git add an openspec/changes/<slug>/ folder or a ticket-scoped E2E spec | `.claude/skills/openspec-fix-changes-gitignore/SKILL.md` «Before `git add` under classified paths» |
| gitignore artefactos | `CLAUDE.md` topic table, row «gitignore artefactos» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (328).

## `openspec-workflow`

- **Files:** `.claude` + `.cursor` skills + `.cursor/rules` rule.
- **Old:** OpenSpec workflow rules for safe AI-assisted development
- **New:** Guardrails for AI-assisted OpenSpec work: no implementation before the source of truth is identified, a clear split between what the code guarantees, what tests verify, what logs show and what remains unproven, and tests that are never relaxed just to pass. Use when the user asks to work with OpenSpec proposals or specs, tests, TDD, Postman, PHPUnit, webhooks or state transitions.

| Phrase (trigger or claim) | Repo source |
|---|---|
| OpenSpec proposals or specs, tests, TDD, Postman, PHPUnit, webhooks or state transitions | `.claude/skills/openspec-workflow/SKILL.md` line 6 |
| no implementation before the source of truth is identified | `.claude/skills/openspec-workflow/SKILL.md` items 1–3 |
| code guarantees / tests verify / logs show / remains unproven | `.claude/skills/openspec-workflow/SKILL.md` item 6 |
| tests never relaxed just to pass | `.claude/skills/openspec-workflow/SKILL.md` items 10–11 |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (383).

## `rune-specs`

- **Files:** `.claude` + `.cursor` skills (rule kept: it already differed).
- **Old:** RUNE specs — create formal specifications for business logic services before implementing (optional; PHP-oriented)
- **New:** Writes RUNE specifications (SIGNATURE, INTENT, BEHAVIOR, TESTS) for business-logic services such as validators, guards, mappers and calculators before they are implemented; optional and PHP-oriented, only for projects that adopt RUNE. Use when creating, documenting or refactoring such a service in a RUNE project, or when the user mentions RUNE specs or .rune files.

| Phrase (trigger or claim) | Repo source |
|---|---|
| SIGNATURE, INTENT, BEHAVIOR, TESTS; validators, guards, mappers, calculators; before implementing | `.claude/skills/rune-specs/SKILL.md` intro and «Required fields» |
| optional, PHP-oriented, only for projects that adopt RUNE | `.claude/skills/rune-specs/SKILL.md` «Optional:» note and previous description |
| creating, documenting or refactoring such a service | `.claude/skills/rune-specs/SKILL.md` «Workflow» (new service / existing service / refactor) |
| RUNE specs, .rune files | `.claude/skills/rune-specs/SKILL.md` title and «Editor: .rune as YAML»; `CLAUDE.md` row «RUNE specs» |

- **Checklist (4.4):** what ✔ · when (trigger clause) ✔ · no step summary ✔ · no invented command, file or behaviour ✔ · ≤ 1024 chars ✔ (367).

## Homonym rules (task 4.2)

Updated with the new text because they were identical to the skill before: `00-openspec-master`, `00-openspec-orchestrator`, `00-openspec-stack-agnostic`, `10-openspec-refactor-solid`, `20-openspec-hydrate-spec`, `30-openspec-anti-hallucination`, `openspec-e2e-regression-guard`, `openspec-extract-spec-from-doc`, `openspec-fix-changes-gitignore`, `openspec-workflow`.
Kept, because they already differed: `40-openspec-safe-apply`, `rune-specs` (and `openspec-gap-analysis`, not rewritten). The validator's `homonym-rule` WARN lines after the rewrite are exactly these three.

## Collision check (task 4.3)

Validator run after the rewrite: 0 `trigger-clause` errors, 0 `collision` errors and **no `collision` WARN** (no pair ≥ 0.30), so no pair needs a justification.
Highest pairs measured with `description_similarities()` on the final descriptions: `.claude` — `comando-verificar`↔`verifica-tarea` 0.25 (neither rewritten), `openspec-e2e-regression-guard`↔`openspec-fix-changes-gitignore` 0.18; `.cursor` — `comando-verificar`↔`verifica-tarea` 0.24, `00-openspec-master`↔`10-openspec-refactor-solid` 0.16.
The three skills of the «Spec fuerte / workflow» row (`00-openspec-master`, `00-openspec-orchestrator`, `openspec-workflow`) keep distinct vocabulary on purpose: «spec fuerte» is only in `00-openspec-master`.
