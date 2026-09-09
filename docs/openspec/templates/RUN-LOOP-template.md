# RUN LOOP — <slug>

> State file for **`/run-spec <slug>`**. Written after **every** phase transition; it is the loop's only memory across context compaction, new sessions and paced (`/loop`) ticks.
> Location: `openspec/changes/<slug>/RUN-LOOP.md` (versioned with the change, like `GAPS.md`).

| Key | Value |
|-----|-------|
| slug | `<slug>` |
| mode | `inline` \| `paced` |
| no_deploy | `true` \| `false` |
| max_iter | `<N>` (default 3, range 1–5) |
| iteration | `<n>` |
| started | `<YYYY-MM-DDTHH:MM:SS>` |
| updated | `<YYYY-MM-DDTHH:MM:SS>` |
| verdict | `RUNNING` \| `DEPLOYED` \| `READY TO DEPLOY` \| `AWAITING DEPLOY APPROVAL` \| `BLOCKED (<reason>)` \| `NO PROGRESS` |

## Phases

Status ∈ `pending` · `running` · `done` · `skipped` · `blocked`.

| Phase | Delegate | Status | Evidence | Updated |
|-------|----------|--------|----------|---------|
| P0 parse+state | — | pending | | |
| P1 bootstrap | `prepara-tarea` | pending | | |
| P2 review | `repasa-spec` | pending | | |
| P3 gap-closure | `repasa-spec` ×N | pending | | |
| P4 confirm | `repasa-spec` (fresh) | pending | | |
| P5 feature tests | `ejecuta-tests-reporte` | pending | | |
| P6 regression | project tests + E2E | pending | | |
| P7 publish | `git commit` + `git push` | pending | | |
| P8 deploy gate | dialog → project `/deploy` | pending | | |

## Gate (last reading)

| Metric | Value |
|--------|------:|
| gaps_pending | |
| tasks_unchecked | |
| tasks_prod_verify | |
| result | `PASS` \| `FAIL` \| `UNKNOWN` |

Computed from disk only:

```bash
C=openspec/changes/<slug>
gaps_pending=$(grep -E '^\*{0,2}Gaps pending \(mejora \+ apply\): [0-9]+\*{0,2}$' "$C/GAPS.md" | tail -1 | grep -oE '[0-9]+' | tail -1)
tasks_unchecked=$(grep -E '^[[:space:]]*- \[ \]' "$C/tasks.md" | grep -vc '\[prod-verify\]')
tasks_prod_verify=$(grep -E '^[[:space:]]*- \[ \]' "$C/tasks.md" | grep -c '\[prod-verify\]')
```

`PASS` iff `gaps_pending = 0` **and** `tasks_unchecked = 0`. A missing file or missing line is `UNKNOWN`, treated as `FAIL`.

## Iteration log

| Iter | Phase | gaps_pending | tasks_unchecked | Note |
|------|-------|-------------:|----------------:|------|

Notes worth logging: `gate mismatch (report N / file M)`, `no progress — same counts as previous iteration`, `confirm review returned to P3`, `max-iter clamped 7 → 5`, `fix-forward after failing test`.

## Deploy gate

| Item | Value |
|------|-------|
| Published | `<branch>` @ `<commit>` — `<subject>` (or `skipped` / `blocked (on production branch)`) |
| Asked | `<YYYY-MM-DDTHH:MM:SS>` (or `not asked — <reason>`) |
| Questions | `<the doubts raised, if any>` |
| Developer answer | `deploy now` \| `stop here` \| `<other>` |
| Deploy command | `<the project command invoked, if approved>` |

The deploy is **never** unattended: without an explicit *deploy now* answer the run ends at `READY TO DEPLOY` or `AWAITING DEPLOY APPROVAL`.

## Residual (production)

Verbatim `tasks.md` lines still unchecked that carry the literal token `[prod-verify]` — tasks verifiable only against a production host, provider or dataset. They never block the gate and are never auto-checked.

<!-- - [ ] 8.1 Run the migration on the production database [prod-verify] -->

## Blockers

| Phase | Blocker | Smallest next action |
|-------|---------|----------------------|
