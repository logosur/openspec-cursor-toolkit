---
name: 10-openspec-refactor-solid
description: OpenSpec refactor workflow for SOLID, DI, and test-backed internal improvements (stack-agnostic)
---

When the user asks to refactor custom code, improve architecture, apply SOLID, improve dependency injection, create interfaces, improve tests, or remove bad practices, use an OpenSpec change before implementation.

Read `.cursor/rules/00-openspec-stack-agnostic.mdc` and the target project's stack rule for **source path layout** (e.g. `src/`, `apps/api/`, `packages/`, `web/modules/custom/`).

## Scope by default

- Application-owned source trees documented in the project (exclude `vendor/`, `node_modules/`, and third-party/contrib packages unless the spec says otherwise).
- Themes or front-end packages only when they contain injectable business logic or shared domain code worth refactoring.

## Out of scope by default

- Third-party / vendor / contrib dependencies.
- Functional behavior changes not explicitly requested.
- Database or schema changes unless explicitly justified.
- Cosmetic-only refactors.

## Required analysis

- Business-logic units without project-owned interfaces (services, use cases, handlers).
- Consumers depending on concrete implementations where an interface exists or should exist.
- Test doubles bound to concrete classes when an interface exists.
- Static service locators, global facades, or container lookups that bypass constructor injection (framework-specific: `\Drupal::`, `App::`, service locators in legacy code).
- God classes and units with too many responsibilities.
- Logic mixed into controllers, forms, CLI commands, hooks, event subscribers, or route handlers that should live in domain/application services.
- Duplicated business rules.
- Weak or missing tests before refactor.

## Refactor rules

- Do not change external behavior.
- Do not modify third-party/contrib code.
- Do not create unnecessary interfaces or fat interfaces.
- Do not introduce abstractions without a concrete reason.
- Project-owned business code should depend on project-owned interfaces where appropriate.
- Consumers should type-hint interfaces, not concrete implementations, when an interface exists.
- Tests should mock dependencies through interfaces when an interface exists.
- Entry points (controllers, forms, commands, plugins) should use constructor injection where viable.
- Avoid static service location in new code except documented edge cases.

## Before implementation

- Create or update an OpenSpec proposal.
- Add tests or characterization tests when coverage is insufficient.
- Define acceptance criteria and rollback strategy.
- Verify the spec status.

Never apply a SOLID refactor unless the spec is **READY TO APPLY**.
