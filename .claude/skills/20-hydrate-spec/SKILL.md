---
name: 20-hydrate-spec
description: Automatically hydrate weak OpenSpec proposals
---

When an OpenSpec proposal is vague, incomplete, risky, or not testable, hydrate it before implementation.

A spec is weak if it contains:

- vague verbs like "improve", "fix", "handle", "support" without measurable criteria
- missing acceptance criteria
- missing non-goals
- missing test strategy
- missing source of truth
- missing edge cases
- missing risk analysis
- tasks that are too large
- requirements that cannot fail a test

Hydration means adding:

- explicit requirements
- GIVEN/WHEN/THEN scenarios
- expected vs observed behavior
- source-of-truth references
- traceability tables
- edge cases
- failure cases
- test plan
- risk mitigation
- small ordered tasks

Never apply a weak spec.