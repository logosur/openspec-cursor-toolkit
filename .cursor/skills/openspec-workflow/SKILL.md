---
name: openspec-workflow
description: "Guardrails for AI-assisted OpenSpec work: no implementation before the source of truth is identified, a clear split between what the code guarantees, what tests verify, what logs show and what remains unproven, and tests that are never relaxed just to pass. Use when the user asks to work with OpenSpec proposals or specs, tests, TDD, Postman, PHPUnit, webhooks or state transitions."
---

When the user asks to work with OpenSpec, proposals, specs, tests, TDD, Postman, PHPUnit, webhooks, or state transitions:

1. Do not implement immediately.
2. First analyze the existing codebase.
3. Identify the source of truth in code, configuration, tests, or documentation.
4. Do not invent business rules, class names, endpoints, labels, statuses, or response codes.
5. Mark unsupported claims as NOT VERIFIABLE.
6. Separate:
   - what the code guarantees
   - what the tests verify
   - what the logs show
   - what remains unproven
7. Create or update an OpenSpec proposal before changing code.
8. Define acceptance criteria before implementation.
9. Prefer small, reviewable tasks.
10. Do not change tests only to make them pass.
11. Do not relax assertions without explicit justification.
12. Every test must fail for a meaningful regression.