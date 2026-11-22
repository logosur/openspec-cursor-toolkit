---
name: 30-openspec-anti-hallucination
description: "Forbids inventing class names, services, endpoints, tables, statuses, response codes, config keys, test names or log fields in OpenSpec work: each one is verified in code, config, tests, docs or provided logs, or marked NOT VERIFIABLE, and claims are labelled FACT, INFERENCE, HYPOTHESIS or UNKNOWN. Use when a spec, design or task names a concrete implementation detail (anti-alucinación)."
---

The assistant must not invent:

- class names
- services
- endpoints
- database tables
- statuses
- webhook labels
- response codes
- configuration keys
- test names
- log fields

Before using any of those elements, it must verify them in:

1. source code
2. configuration
3. existing tests
4. existing documentation
5. logs provided by the user

If the assistant cannot verify something, it must label it as:

NOT VERIFIABLE

The assistant must distinguish between:

- FACT: directly supported by evidence
- INFERENCE: likely but not directly proven
- HYPOTHESIS: possible explanation
- UNKNOWN: not enough evidence
