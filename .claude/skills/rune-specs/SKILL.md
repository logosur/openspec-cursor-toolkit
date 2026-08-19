---
name: rune-specs
description: RUNE specs — create formal specifications for business logic services before implementing (optional; PHP-oriented)
---

# RUNE Specs for Business Logic

For **new business logic services** (validators, guards, mappers, calculators), consider a RUNE spec before implementing. This ensures consistent AI-generated code and explicit contracts.

**Optional:** use only when the target project adopts RUNE; skip for stacks that use OpenSpec scenarios alone.

## When to use RUNE specs

| Use RUNE | Skip RUNE |
|----------|-----------|
| **Services with business logic** — guards, calculators, validators | Thin controllers, route handlers, UI components |
| **Value Objects** — constructors, validation | Integrations with external APIs |
| **Domain validation** — payload rules, invariants | Orchestration-only glue code |

## Location

Place specs where the project documents them — e.g. `<package>/specs/*.rune` or co-located with the service. Adjust path to project layout.

## Workflow

1. **New service**: Define RUNE spec (SIGNATURE, INTENT, BEHAVIOR, TESTS) before or in parallel with the interface.
2. **Existing service**: Document the contract and detect drift from code.
3. **Refactor**: Update spec → implement → generate tests from spec.

## Required fields

- **SIGNATURE**: Exact method syntax for the project's language
- **INTENT**: 1–3 sentences (docstring-ready)
- **BEHAVIOR**: WHEN/THEN rules
- **TESTS**: Minimum 3 (happy path, boundary, error)

## Meta example (PHP)

```yaml
meta:
  name: methodName
  language: php
  class: App\\Domain\\Service\\ServiceClass
  tags: [category, tags]
```

## Editor: .rune as YAML

```json
{
  "files.associations": {
    "*.rune": "yaml"
  }
}
```

## References

- [Rune-stone](https://github.com/vict00r99/Rune-stone) — specification pattern
