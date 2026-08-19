# Refactor / SOLID — Master OpenSpec Prompt

Use this prompt for **internal refactors**: SOLID alignment, extracting **business service interfaces**, reducing **service locator** usage, normalizing **constructor DI**, splitting **god services**, tightening test doubles, style enforcement, **orchestration vs domain** separation, **duplicated rules** removal, and **test coverage before refactors**.

## Prompt

OpenSpec mode — refactor / SOLID.
Spec name: [spec-name]
User request:
[PASTE REQUEST HERE]

Follow the project OpenSpec architecture:

- EXPLORE (use the checklist in this prompt; align with `.cursor/rules/10-openspec-refactor-solid.mdc` and `.cursor/rules/tdd-spec-driven-tests.mdc`)
- PROPOSE (same artefact layout as `docs/openspec/prompts/master-openspec-prompt.md`: `proposal.md`, `specs/`, `design.md` when needed, `tasks.md`)
- HYDRATE
- VERIFY
- APPLY only when VERIFY = READY TO APPLY (use `.cursor/rules/40-openspec-safe-apply.mdc`)

Do not implement until VERIFY passes.

Explore the codebase for **evidence**:

- existing interfaces vs concrete services
- DI configuration (container, modules, providers)
- static service location or global facades in application code
- duplicated domain rules across classes
- tests: what is already covered; where characterization tests are needed (see `.cursor/rules/tdd-spec-driven-tests.mdc`)

The result must include:

- behavior preservation statement (unless explicit intentional change)
- current vs expected at integration boundaries
- risks (workflows, third-party boundaries, cache, events)
- **testing strategy**: characterization / existing tests first
- tasks.md with small, reviewable steps

Rules:

- Do not invent class names, service IDs, routes, config keys, or workflows; verify in repo or mark NOT VERIFIABLE.
- Do not weaken tests to pass.
- Prefer dependency inversion: **interfaces for domain/business services**, mocks from interfaces in tests.
- Keep framework types at boundaries where appropriate; do not introduce redundant wrappers.

Verification status must be one of:

- READY TO APPLY
- NEEDS HYDRATION
- BLOCKED BY UNKNOWN
- UNSAFE TO APPLY
