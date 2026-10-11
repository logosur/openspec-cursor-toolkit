# Tasks: lean-mode

## 1. Documentation

- [x] 1.1 `docs/openspec/README.md`: section "Budget and the lean mode" (measured costs, three counters, seven rules, the supervisor as the one multi-agent step that earns its cost)
- [x] 1.2 `multiagente/SKILL.md`, step 4, both toolkits: serial by default with a context packet, parallel as opt-in, the delegate never commits
- [x] 1.3 `openspec-gap-analysis/SKILL.md`, both toolkits: lean delegation by default instead of the mandatory multi-agent line
- [x] 1.4 `harness-spec/SKILL.md`, both toolkits: scoped supervisor by default; prohibitions for a test never seen failing and for a delegate that commits

## 2. Verification

- [x] 2.1 `openspec validate lean-mode` clean
- [x] 2.2 `.claude` and `.cursor` copies carry the same additions (diff of the added passages)
- [ ] 2.3 One consumer project adopts the notes and reports its per-pass cost after a week (the number in the README is from one project; a second measurement either confirms it or corrects it)
