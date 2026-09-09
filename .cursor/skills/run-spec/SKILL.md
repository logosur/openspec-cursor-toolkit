---
name: run-spec
description: "Top-level OpenSpec run loop — unattended from idea to a published branch (prepara → repasa → gap-closure loop → confirm review → feature tests → regression → commit + push), then a mandatory deploy-approval dialog before the project deploy. Auto-invoke on /run-spec, build spec, construye la spec entera, de la idea al deploy, loop openspec completo."
disable-model-invocation: true
---

# Build spec — unattended OpenSpec run loop (idea → deploy)

> **Command:** `.cursor/commands/run-spec.md`
> **Rule (L2):** `.cursor/rules/run-spec-openspec-loop.mdc`
> **State file:** `openspec/changes/<slug>/RUN-LOOP.md` (template: `docs/openspec/templates/RUN-LOOP-template.md`)
> **Delegates to:** `prepara-tarea` · `repasa-spec` (gaps → mejora → aplica → gaps) · `ejecuta-tests-reporte` · project `/deploy`
> **Stack:** resolve every runtime command from the target project — `.cursor/rules/00-openspec-stack-agnostic.mdc`

You are running **run-spec**: drive one OpenSpec change from a plain description to a deployed feature **unattended**, stopping only on a real blocker, and closing with a machine-readable verdict.

This skill **orchestrates**. It does not re-implement gap analysis, hydration, apply, testing or deploy — each phase is delegated to the canonical skill/command that already owns it.

## Preconditions

| Requirement | Why |
|-------------|-----|
| The target project exposes the **OpenSpec CLI** (`openspec status`, `openspec validate`) | P1–P4 delegate to skills that call it; a missing binary stops the loop with `BLOCKED (openspec CLI unavailable)` rather than an opaque phase failure |
| The project documents its test / E2E / deploy commands (stack rule or `CLAUDE.md`) | P5, P6 and P8 resolve them from there; missing test commands downgrade the run to `READY TO DEPLOY` (§2), a missing deploy command blocks P8 |

## When to use

| Use `/run-spec` | Use the individual command instead |
|-------------------|------------------------------------|
| "build this feature end to end", "de la idea al deploy" | Only gaps → `/gaps-spec` |
| A new idea + you want it specified, implemented, tested and deployed | Only hydrate → `/mejora-tarea` |
| An existing change you want driven to completion (resume mode) | Only implement → `/aplica-tarea` |
| Paced execution across ticks → `/loop /run-spec <slug>` | Only the review cycle → `/repasa-spec` |

## Phase table (canonical order — never parallel)

| # | Phase | Delegate | Exit gate (read from disk) |
|---|-------|----------|----------------------------|
| **P0** | Parse + state | — | slug valid; `RUN-LOOP.md` created or resumed |
| **P1** | Bootstrap | `prepara-tarea` + description | `proposal.md` + `tasks.md` + `specs/**/spec.md` exist |
| **P2** | Review pipeline | `repasa-spec` | `GAPS.md` has the pending line; `READY-TO-APPLY.md` exists |
| **P3** | Gap-closure loop | `repasa-spec` × ≤ `max_iter` | gate `PASS` (§4) |
| **P4** | Confirm review | `repasa-spec` (fresh reviewer) | gate still `PASS` |
| **P5** | Feature tests | `ejecuta-tests-reporte` | exit 0 |
| **P6** | Regression | project full tests + E2E | exit 0 (or documented `skipped` → downgrade P7) |
| **P7** | Publish | `git commit` + `git push -u origin <branch>` | branch pushed (or nothing to publish) |
| **P8** | Deploy gate | **developer approval dialog** → project `/deploy` | approved and deploy succeeded → `DEPLOYED` |

Phases run **one after another**. A phase starts only when the previous one reached `done`, `skipped`, or a documented `blocked` that does not stop the loop.

---

## P0 — Parse input and open state

### Parse (first line + body)

```text
/run-spec <slug> [--no-deploy] [--max-iter N]
<description line 1>
<description line 2…>
```

| Field | Rule |
|-------|------|
| `slug` | First whitespace-separated token after `run-spec` (optional leading `/`, no `:`). MUST be kebab-case. |
| `--no-deploy` | Optional flag anywhere on line 1. Sets `no_deploy = true`. |
| `--max-iter N` | Optional. `1 ≤ N ≤ 5`; `N > 5` clamps to 5 and is logged. Default **3**. |
| `description` | Everything after line 1, verbatim, newlines preserved. Flags are **never** part of the description. |

**Clarification rules (ask once, then stop):**

| Condition | Action |
|-----------|--------|
| Slug missing or not kebab-case | Ask once for a kebab-case slug — stop, create nothing |
| Description empty **and** `openspec/changes/<slug>/` does **not** exist | Ask once for the description — stop |
| Description empty **and** the folder exists | **Resume mode** — do not ask |

### Open or create the state file

`openspec/changes/<slug>/RUN-LOOP.md`, from `docs/openspec/templates/RUN-LOOP-template.md`.

- **New run:** create it with every phase `pending`, `iteration: 0`, verdict `RUNNING`.
- **Resume:** read it, keep `iteration`, and start at the **first phase whose status is not `done`/`skipped`**. Never re-run a `done` phase.
- **Crash-safe:** a phase left `running` is **not** trusted — re-read its exit gate from disk first; if the gate holds, mark it `done` and move on; if not, re-run it.

Write the file **after every phase transition** (start, end, blocker, gate reading). It is the loop's only memory: it must survive context compaction, a new session and paced ticks.

---

## §1 Delegation contract (every phase)

Each phase runs in a **fresh-context subagent** (`Task` tool, general subagent) so the orchestrator's context stays small and each phase re-derives its own facts.

**Exception — P7 (publish) and P8 (deploy gate) run in the main agent**, because they mutate git and open decision dialogs — the mandatory P8 approval dialog, plus the project deploy command's own prompts — that must reach the developer, not a subagent.

### Subagent prompt template

```text
Project root: <abs path>. Change slug: <slug>.
Read <skill path> and execute it for this slug exactly as if the user had run `<slash command> <slug>`.
Ignore any "stop here / run the next command in a new message" instruction inside that skill:
you are one phase of an orchestrated pipeline (`run-spec`), the orchestrator continues.
<phase-specific extra instructions>

Return ONLY this report, max 15 lines:
phase_status: done|partial|blocked
evidence: <paths and/or commands with exit codes>
gaps_pending: <int|n/a>
tasks_unchecked: <int|n/a>
tasks_prod_verify: <int|n/a>
blocker: <one line|none>
```

**Never** accept a subagent's claim as a gate result. The orchestrator always re-reads the gate from disk (§4). On mismatch, **the file wins** and the mismatch is logged in `RUN-LOOP.md`.

---

## §2 Phases

### P1 — Bootstrap (`prepara-tarea`)

- **Skip** with status `skipped (proposal exists)` when `openspec/changes/<slug>/proposal.md` is already on disk.
- Otherwise delegate to `.cursor/skills/prepara-tarea/SKILL.md` with the verbatim description.
- Its mandatory closing (`Do not implement yet.` / `No implementes todavía.`) is a **phase boundary, not a loop stop** — record `done` and continue.
- **Exit gate:** `proposal.md`, `tasks.md` and at least one `specs/**/spec.md` exist.

### P2 — Review pipeline (`repasa-spec`)

- Delegate to `.cursor/skills/repasa-spec/SKILL.md` (gaps → mejora → aplica → gaps, sequential).
- Extra instruction: *"When you hydrate or apply, tag any task that can only be verified in production with the literal token `[prod-verify]` (see §5)."*
- **Exit gate:** `GAPS.md` contains the canonical pending line; `READY-TO-APPLY.md` exists.
- **Blocked** (no change folder, no `tasks.md` after hydration) → stop the loop with `BLOCKED (<reason>)`.

### P3 — Gap-closure loop

Repeat, at most `max_iter` times:

1. Evaluate the gate (§4). If `PASS` → P3 `done`, go to P4.
2. Otherwise run one `repasa-spec` iteration in a fresh subagent, `iteration += 1`, persist.
3. Compare `(gaps_pending, tasks_unchecked)` with the previous iteration:
   - **identical** → stop, verdict **`NO PROGRESS`** (do not spend the remaining budget);
   - improved → loop again while budget remains.
4. Budget exhausted with gate still `FAIL` → verdict **`BLOCKED (max-iter reached)`**.

The `max_iter` budget is **shared** with the fix-forward passes of P5 and P6.

### P4 — Confirm review (independent)

One `repasa-spec` in a **fresh-context** subagent, with this extra line in its prompt:

> *"Do not assume any prior result. Re-derive gaps from the spec and the codebase as if you had never seen this change."*

Then re-evaluate the gate from disk:

- `PASS` → P4 `done`, go to P5.
- `FAIL` **and** budget remains → back to P3 (log the return in the iteration log).
- `FAIL` **and** no budget → verdict **`BLOCKED (confirm review found gaps)`**.

### P5 — Feature tests

- Delegate to `.cursor/commands/ejecuta-tests-reporte.md` — the **narrowest** project test command that covers the change (derived from `tasks.md` + `specs/**`).
- Exit 0 → `done` (record the exact command and exit code).
- Non-zero → classify per `.cursor/rules/openspec-e2e-regression-guard.mdc`:

| Classification | Action |
|----------------|--------|
| Application regression | Fix forward via `aplica-tarea` (consumes budget), re-run |
| Outdated test, spec agrees | Update the test to match the spec, re-run |
| Legitimate behaviour change | Update the **spec first**, then the test, re-run |
| Ambiguous | Verdict **`BLOCKED (ambiguous test failure)`** — do not guess |

- Project documents no test command → `skipped (no project test command)`.
- **Never** relax, skip or delete an assertion to obtain green.

### P6 — Regression

- Run the project's **full** test command and E2E suite as documented in its stack rule.
- Same classification and fix-forward rules as P5.
- No full test/E2E command documented → `skipped (no regression signal)` **and** P8 is downgraded: the run still publishes (P7) and ends with **`READY TO DEPLOY`** without offering to deploy.
- The loop **never** reaches P7 or P8 with P5 or P6 red.

### P7 — Publish (commit + push the current branch, main agent)

Runs when P5 and P6 are `done`. This is the loop's **only** git mutation.

1. Inspect the tree so the message is accurate: `git status -sb`, `git diff --stat`.
2. **Clean tree already in sync with its upstream** → `skipped (nothing to publish)`.
3. **Current branch is the project's production branch** (`main` by default, or whatever the project's stack rule names) → make **no** git mutation, record `blocked (on production branch)`, and carry that fact into the P8 dialog as its first line.
4. **Look at what you are about to stage** (`git status --porcelain`). Files that are not part of this change's declared Impact — unrelated edits, another session's work, build artefacts, caches, generated bundles — MUST NOT be swept in: if the project ignores them, fine; otherwise stage only the change's own paths (`git add <paths>`), and when the split is not obvious **ask** which files belong in the commit before staging anything.
5. Commit with one English imperative message (first line ≤ 72 chars) naming the change, then `git push -u origin <current-branch>`.
6. Record the staged file list as P7 evidence, so what was published is visible without re-running git.
7. Record the commit hash, subject and pushed branch as P7 evidence.

**Authorization:** invoking `/run-spec` authorizes exactly this commit and this push, and nothing else. **Never** merge, rebase, cherry-pick, tag, force-push, or push any branch other than the current one. P7 runs even with `--no-deploy` — publishing is independent of deploying.

### P8 — Deploy gate (developer decision, main agent)

**The loop is never unattended past this point.** Everything green is not approval.

| Situation | Action |
|-----------|--------|
| `no_deploy = true` | Skip the dialog → **`READY TO DEPLOY`** (P7 already published) |
| No project deploy command | **`BLOCKED (no deploy command)`** |
| No dialog channel (non-interactive, background, paced tick) | **`AWAITING DEPLOY APPROVAL`** + print the exact command to run |
| Otherwise | Ask (below) |

**Before asking**, gather what the developer needs to decide — cheaply, from what the run already produced:

- branch, commit hash and subject pushed by P7 (or why P7 was skipped/blocked);
- one line on what the change does;
- P5 and P6 results (commands + exit codes);
- residual `[prod-verify]` tasks, verbatim;
- what the project's deploy command will actually do — cascade merges, target host, migrations — read from **its own file**, not re-derived.

**Then open one `AskUserQuestion` dialog:**

| Option | Meaning |
|--------|---------|
| **Deploy now, unattended** (first option) | Run the project `/deploy` and do not ask anything else; its own internal dialogs still belong to it |
| **Stop here** | Verdict `READY TO DEPLOY`; nothing else runs |

Add **up to three** further questions in the same dialog **only** for genuine doubts about this deploy (target environment, whether residual `[prod-verify]` work should block the release, a migration that needs a window). Never ask what the project's deploy command already asks, and never ask for the sake of asking.

**Prohibited:** pre-answering the dialog; inferring approval from the `/run-spec` invocation; treating silence, a timeout or a non-answer as a yes; deploying to reach a nicer verdict.

**On approval:** invoke the project deploy command in the main agent exactly as a developer would, let it run its own preflight and prompts, and end with **`DEPLOYED`** on its success. The loop never runs FTP, SSH or a CI dispatch of its own.

---

## §3 State file schema (`RUN-LOOP.md`)

```markdown
# RUN LOOP — <slug>

| Key | Value |
|-----|-------|
| slug | <slug> |
| mode | inline \| paced |
| no_deploy | true \| false |
| max_iter | <N> |
| iteration | <n> |
| started | <ISO8601> |
| updated | <ISO8601> |
| verdict | RUNNING \| DEPLOYED \| READY TO DEPLOY \| AWAITING DEPLOY APPROVAL \| BLOCKED (<reason>) \| NO PROGRESS |

## Phases

| Phase | Delegate | Status | Evidence | Updated |
|-------|----------|--------|----------|---------|
| P0 parse+state | — | done | slug=<slug>, flags=… | … |
| P1 bootstrap | prepara-tarea | pending | | |
| P2 review | repasa-spec | pending | | |
| P3 gap-closure | repasa-spec ×N | pending | | |
| P4 confirm | repasa-spec (fresh) | pending | | |
| P5 feature tests | ejecuta-tests-reporte | pending | | |
| P6 regression | project tests + E2E | pending | | |
| P7 publish | git commit + push | pending | | |
| P8 deploy gate | dialog → project /deploy | pending | | |

## Gate (last reading)

| Metric | Value |
|--------|------:|
| gaps_pending | <int> |
| tasks_unchecked | <int> |
| tasks_prod_verify | <int> |
| result | PASS \| FAIL \| UNKNOWN |

## Iteration log

| Iter | Phase | gaps_pending | tasks_unchecked | Note |
|------|-------|-------------:|----------------:|------|

## Deploy gate

<!-- what was asked, what the developer answered, and when -->

## Residual (production)

<!-- verbatim [prod-verify] task lines -->
```

Status values: `pending` · `running` · `done` · `skipped` · `blocked`.

---

## §4 Gate — computed from files, never from prose

```bash
C=openspec/changes/<slug>

gaps_pending=$(grep -E '^\*{0,2}Gaps pending \(mejora \+ apply\): [0-9]+\*{0,2}$' "$C/GAPS.md" 2>/dev/null | tail -1 | grep -oE '[0-9]+' | tail -1)
tasks_unchecked=$(grep -E '^[[:space:]]*- \[ \]' "$C/tasks.md" 2>/dev/null | grep -vc '\[prod-verify\]')
tasks_prod_verify=$(grep -E '^[[:space:]]*- \[ \]' "$C/tasks.md" 2>/dev/null | grep -c '\[prod-verify\]')
```

| Condition | Result |
|-----------|--------|
| `gaps_pending == 0` **and** `tasks_unchecked == 0` | **PASS** |
| Either is `> 0` | **FAIL** |
| `GAPS.md` missing, or the canonical line absent (`gaps_pending` empty) | **UNKNOWN** → treated as **FAIL**; the next `repasa-spec` iteration regenerates the line |

The phase subagent must end its report with the same canonical line. **The more pessimistic value wins:** take `max(file, report)`. A report claiming *fewer* gaps than `GAPS.md` never lowers the count — the file wins. A report claiming *more* (typically the P4 confirm reviewer finding something new) is authoritative: **write those findings into `GAPS.md` first**, then re-read the file, so the gate is never satisfied by discarding a real finding. Either way log `gate mismatch (report <a> / file <b>) → <resolution>` in the iteration log and do not advance until the file and the report agree.

---

## §5 `[prod-verify]` — production-dependent tasks

A task whose verification is only possible in production (PRO host smoke, real payment provider, real mail delivery, production data migration) carries the literal token **`[prod-verify]`** in its `tasks.md` line:

```markdown
- [ ] 8.1 Run the migration on the production database [prod-verify]
```

| Rule | |
|------|--|
| Excluded from `tasks_unchecked` | it never blocks the gate |
| Never auto-checked | only a human flips it |
| Listed verbatim | under **Residual (production)** in `RUN-LOOP.md` and in the final report |
| Applied sparingly | only when a production host, provider or dataset is genuinely required — not for "hard to test locally" |

Other commands ignore the marker: for `/finaliza-spec` and `/archiva-tarea` such a task is still an unchecked task, by design.

---

## §6 Loop budget and convergence

| Knob | Value |
|------|-------|
| `max_iter` | default **3**, `--max-iter N` with `1 ≤ N ≤ 5` (clamped, logged) |
| Consumers of the budget | P3 iterations, P4 → P3 returns, P5/P6 fix-forward passes |
| Convergence guard | `(gaps_pending, tasks_unchecked)` unchanged between two consecutive iterations → **`NO PROGRESS`** |
| Budget exhausted | **`BLOCKED (max-iter reached)`** with the remaining counts and items listed verbatim |

A stopped loop is **resumable**: running `/run-spec <slug>` again picks up from `RUN-LOOP.md` with a fresh budget.

---

## §7 Paced mode (`/loop`)

Default is **inline**: all phases in one turn.

**Paced** is the developer running `/loop /run-spec <slug>` (dynamic mode, no interval). Per tick:

1. Read `RUN-LOOP.md`.
2. Execute **at most one** phase (or one P3 iteration).
3. Persist state.
4. Arm the next wake-up with the Cursor `/loop` **monitored shell output** mechanism — a unique sentinel per loop and the prompt in the JSON payload:

```bash
sleep <seconds>
echo 'AGENT_LOOP_WAKE_build_spec_<slug> {"prompt":"/run-spec <slug>"}'
```

| Situation | Sentinel armed? | Delay |
|-----------|-----------------|-------|
| A phase advanced the state | yes | short (the next phase can start immediately) |
| Waiting on an external signal (deploy CI, remote queue) | yes | matched to that wait (e.g. ~480 s for an ~8 min CI) |
| Terminal verdict reached, **including `AWAITING DEPLOY APPROVAL`** (a tick cannot ask the developer) | **no** — stop, kill any watcher PID | — |

- The payload `prompt` is the same `/run-spec <slug>` text, verbatim, every tick.
- Use a unique sentinel per slug so unrelated loops do not collide; do not create duplicate sleepers.
- In **Claude Code** the equivalent contract uses `ScheduleWakeup` (`noop`, `stop`, `prompt`, `delaySeconds` clamped 60–3600) instead of a shell sentinel; never schedule short polls for harness-tracked subagents.
- If no wake-up primitive is available, **say so** and run inline.

---

## §8 Token budget (mandatory)

| Rule | |
|------|--|
| Read this skill **once** per run | do not re-read it per phase |
| Do **not** read the delegated skills | each subagent reads its own |
| Orchestrator context = the state table | never the full `GAPS.md`, `spec.md` or `tasks.md` |
| Gate checks are `grep`/`tail` | never a full-file read |
| Skip a phase whose exit gate already holds | on resume, and on a satisfied precondition |
| No `.md` outside `openspec/changes/<slug>/` | no analysis reports, no scratch docs |
| Subagent reports | ≤ 15 lines, the 6 fixed keys of §1, nothing else |
| Final chat | only the mandatory sections of §9 |

---

## §9 Final report (mandatory shape)

```markdown
## Run loop — <slug>
<phase table copied from RUN-LOOP.md>

## Verification
<commands, exit codes, evidence paths — one line each>

## Residual
<[prod-verify] tasks verbatim · residual gaps · blockers>

## Resumen
<verified facts only>
```

**Last line, verbatim format, nothing after it:**

```text
Run-spec verdict: <VERDICT>
```

`<VERDICT>` ∈ `DEPLOYED` | `READY TO DEPLOY` | `AWAITING DEPLOY APPROVAL` | `BLOCKED (<reason>)` | `NO PROGRESS`, identical to the verdict stored in `RUN-LOOP.md`.

---

## §10 Stop conditions

| Condition | Action |
|-----------|--------|
| Missing/invalid slug, or missing description on a new change | Ask once — stop |
| Missing credentials or human-only access | `BLOCKED (<reason>)` |
| OpenSpec CLI unavailable in the target project | `BLOCKED (openspec CLI unavailable)` — name the missing binary |
| Ambiguous product decision that cannot be inferred safely | `BLOCKED (ambiguous …)` |
| Ambiguous test failure (spec/code/test disagree) | `BLOCKED (ambiguous test failure)` |
| Destructive or high-risk operation needing confirmation | `BLOCKED` — ask, never assume |
| No deploy command in the project | `BLOCKED (no deploy command)` |
| Deploy approval dialog cannot be shown | `AWAITING DEPLOY APPROVAL` — never deploy instead |
| Explicit user interrupt | Stop, persist state, report progress |

Ordinary fixable failures (a red test, a lint error, a missing import, an unchecked task) are **not** stop conditions — fix forward within the budget.

Every blocker appears in **both** `RUN-LOOP.md` and the final report. Partial state is never hidden.

---

## §11 Related

| Path | Role |
|------|------|
| `.cursor/commands/run-spec.md` | Slash command entry point |
| `.cursor/skills/prepara-tarea/SKILL.md` | P1 |
| `.cursor/skills/repasa-spec/SKILL.md` | P2, P3, P4 |
| `.cursor/commands/ejecuta-tests-reporte.md` | P5 |
| `.cursor/rules/openspec-e2e-regression-guard.mdc` | P5/P6 failure classification |
| `.cursor/skills/multiagente/SKILL.md` | Unattended orchestration contract |
| `.cursor/rules/00-openspec-stack-agnostic.mdc` | Resolve project test/E2E/deploy commands |
| `docs/openspec/templates/RUN-LOOP-template.md` | State file template |
| `/verifica-tarea`, `/harness-spec` | Deeper verification — optional, **after** the loop |
| `/finaliza-spec`, `/archiva-tarea` | Commit + archive — manual, **after** the loop |
