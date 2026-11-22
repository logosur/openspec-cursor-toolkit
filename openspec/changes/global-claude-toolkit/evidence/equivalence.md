# Equivalence evidence (task 7.3)

Run on 2026-11-22, read only against the live Claude dir of the reference machine, with its private
override (kept outside this repository):

```
./install.sh equivalence --live ~/.claude
```

The command installs the toolkit plus the override into a throwaway HOME and explains every difference
with the live dir. It exits 1 on any unexplained difference.

## Result

| Class | Files | Meaning |
|---|---:|---|
| identical | 7 | toolkit file, byte for byte the live one |
| override | 232 | supplied by the private override (`files/` or `append/`), byte for byte the live one |
| toolkit-newer | 6 | the live file is an earlier version of the toolkit file (a blob in this repository's history) |
| neutral-text | 3 | same Python AST, only docstrings and comments differ |
| declared | 2 | intended difference declared in `override.yaml` with its reason and proof |
| added | 22 | installed by the toolkit, not present live (new OpenSpec skills, docs, config pieces) |
| excluded | 6 | live files the toolkit never manages (third-party skills, symlinks into other trees, backups) |
| **unexplained** | **0** | |

Hooks: 21 identical (7 from the toolkit, 14 from the override's hook fragment), 0 unexplained.

Installed from the toolkit: 40 files; from the override: 232.

## The non-trivial classes, by piece

- toolkit-newer: `skills/00-openspec-master`, `skills/00-openspec-orchestrator`, `skills/20-hydrate-spec`,
  `skills/html`, `skills/openspec-anti-hallucination`, `skills/openspec-workflow`.
- neutral-text: `hooks/process-kill-gate`, `hooks/start-session-bypass-gate`, `hooks/worktree-location-gate`.
- declared (`config-injected`): `scripts/worktree-location` (worktree root) and `scripts/test-account`
  (forbidden notes folder) read from their config piece the value the live copy had as a literal.
  Proof: `OverrideLayer.test_replace_append_extra_and_config` and the `test-account` contract
  (its self-test, run from the installed copy).

## What this does not prove

- Only the managed scopes are compared (`CLAUDE.md`, rules, rules-detail, skills, commands, agents,
  scripts, hooks, scheduled-tasks, docs, toolkit config) plus the `hooks` key of `settings.json`. Runtime
  state (sessions, caches, logs, state folders) is out of scope by design.
- The live machine was not migrated to "toolkit + override"; that is the next step (design, Migration).
- 43 files the toolkit also provides differ from the live copy without being older versions of it. The
  override keeps the live copy for each of them, so an install changes nothing; reconciling them is
  done later, file by file, with `drift` and `pull`.
