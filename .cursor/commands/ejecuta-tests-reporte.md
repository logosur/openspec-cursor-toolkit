---
name: /ejecuta-tests-reporte
id: ejecuta-tests-reporte
category: Workflow
description: "Run project tests relevant to an OpenSpec change and report failures honestly"
---

# Ejecuta tests reporte (OpenSpec)

You are running **ejecuta-tests-reporte**: test pass with honest reporting for `openspec/changes/<slug>/`.

Read `.cursor/rules/00-openspec-stack-agnostic.mdc` and the target project's stack rule for test commands.

## 1. Resolve `<slug>`

On the **first line**, parse the slug as the **first token after** `ejecuta-tests-reporte` (optional leading `/`), separated by **whitespace only** — do **not** require a colon. Example: `/ejecuta-tests-reporte task-commands`. If missing, ask once.

## 2. Derive scope

Read `openspec/changes/<slug>/tasks.md` and `openspec/changes/<slug>/specs/**/*.md`. Identify packages, modules, or test paths referenced. Prefer the **narrowest** project test command that still covers the change.

## 3. Execute

Run tests via the **project-documented** command (Makefile, `npm test`, `bin/phpunit`, Docker Compose exec, etc.) — not a stack assumed by this toolkit.

Examples (use only what the target project defines):

```bash
make test-phpunit FILTER=RelevantTest
npm run test --workspace @app/pkg
docker compose exec api bin/phpunit tests/Unit/RelevantTest.php
```

## 4. Report

- Exit code and exact command(s).
- On failure: failing suite names, first actionable stack traces or assertion messages, and suggested next steps.
- Do **not** relax assertions or skip tests to obtain green.

## 5. If scope is unclear

State **UNKNOWN**, list assumptions, and propose the smallest extra command to gain signal (e.g. one package's unit suite).
