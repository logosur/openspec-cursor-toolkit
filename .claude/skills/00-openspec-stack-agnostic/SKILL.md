---
name: 00-openspec-stack-agnostic
description: OpenSpec toolkit is stack-agnostic — resolve commands, paths, and URLs from the target project
---

# OpenSpec — stack-agnostic toolkit

This repository is a **portable OpenSpec + Claude Code toolkit**. It MUST NOT assume Drupal, DDEV, Symfony, Next.js, or any single stack unless the **target application repo** documents that stack.

## Before runtime commands

1. Read the **target project's** stack rules when present — e.g. project `CLAUDE.md`, `README.md`, `Makefile`, `package.json` scripts, `docker-compose*.yaml`, `compose.*.yaml`.
2. Resolve **base URL**, **auth helper**, **test**, **lint**, and **build/cache** commands from those sources — not from examples in this toolkit.
3. If the project has no documented local dev flow, ask once or mark rows **BLOCKED (environment)** — do not invent DDEV/Drush/Make targets.

## Path vocabulary

| Concept | Generic rule |
|---------|----------------|
| OpenSpec artefacts | `openspec/changes/<slug>/` only during PROPOSE/HYDRATE/GAPS — no product implementation there |
| Application source | Any path **outside** `openspec/changes/<slug>/` that holds product code, config, assets, migrations — layout varies (`src/`, `apps/`, `packages/`, `web/modules/custom/`, …) |
| Third-party / vendor | Dependency trees (`vendor/`, `node_modules/`, contrib modules) — out of scope unless spec says otherwise |
| Verification artefacts | `.claude/context/verification/` — never product code |

## URL and auth

- Resolve base URL from project docs (Compose port mapping, `.env`, `APP_URL`, CI env, documented smoke script) — **never hardcode** host/port from another project.
- Multi-role / E2E auth: use the **project-documented** helper (Playwright storage state, test login script, seed user fixture) — one attempt per user per session; no retry loops on flood/lockout.

## Tests and quality gates

Use the **narrowest** command the project documents, for example:

| Need | Examples (pick what the project defines) |
|------|------------------------------------------|
| Unit / integration | `make test`, `npm test`, `bin/phpunit`, `pytest`, workspace filter |
| Lint / static analysis | `make lint`, `npm run lint`, `phpstan`, `eslint` |
| E2E / browser | Playwright/Cypress path from project rules |
| Cache / rebuild | Framework-specific when DI/routing/assets changed |
| Config / schema sync | Migrations, `config:import`, `prisma migrate`, etc. — only when spec touches config |

## Framework notes (when the target project uses them)

Examples in skills may mention Drupal forms, Symfony services, or React routes as **illustrations**. Apply the same verification discipline to the stack actually in the repo (REST handlers, CLI commands, background jobs, etc.).

## Integration

- Export/propagate this toolkit with `/exporta-spec` — each consumer keeps its own project-stack notes (in `CLAUDE.md` or a project skill).
- L1 truth/verification gates (equivalent to `00-verification-gate`, `00-honesty-no-manipulation` in the source rule set) still apply on every project.
