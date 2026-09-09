---
name: multiagente
description: Orchestrates unattended multi-agent execution for a specified task. Use when the user says /multiagente, modo multiagente, usa el modo multiagente, de forma desatendida, or no pares hasta terminarlo todo.
---

# Multiagente

Use this skill when the user asks to run a specified task in unattended multi-agent mode.

## Contract

Interpret the request as:

```text
usa el modo multiagente para [tarea especificada], de forma desatendida. No pares hasta terminarlo todo.
```

The goal is not to merely start work. The goal is to finish the task, verify it, and make any unfinished state impossible to miss.

## Roles

### Main agent

- Owns the task, acceptance criteria, orchestration, and final verdict.
- Splits work into small assignments for subagents when useful.
- Monitors real evidence: tests, logs, CLI output, HTTP responses, browser checks, build output, generated artifacts, or repository files.
- Interprets failures and sends subagents precise follow-up prompts containing the observed error and expected outcome.
- Does not accept subagent claims without checking the relevant evidence.

### Subagents

- Execute bounded tasks: explore code, implement a focused change, run a test group, inspect failures, review risks, or prepare evidence.
- Return files touched, commands run, results, and any blocker.
- Do not decide that the overall task is complete; only the main agent closes.

## Workflow

1. Restate the task internally as acceptance criteria.
2. Inspect the project before editing: stack, commands, relevant docs/rules, existing patterns, and current state.
3. Create a short task list for orchestration when the work has more than one meaningful step.
4. Launch subagents for independent or specialized work. Prefer parallel subagents for exploration/review/test investigation when possible.
5. Integrate results and apply or request additional focused work until the criteria are met.
6. Verify through the narrowest reliable checks first, then broaden only as risk requires.
7. If verification fails, treat the failure as the next task and continue.
8. Close only with a clear completion, verification, and residual-risk report.

## Stop Conditions

Do not stop for ordinary test failures, linter errors, missing imports, type errors, failing browser checks, or incomplete subtasks. Fix forward and verify again.

Stop only for:

- Missing credentials or human-only access.
- Ambiguous product requirements that cannot be inferred safely.
- Explicit user interruption.
- Git commit, push, merge, or rebase requiring explicit authorization.
- Destructive or high-risk operation requiring confirmation.

When stopped, report: current progress, exact blocker, evidence, and the smallest next user action.

## Verification Gate

Before final response, inventory every claim of completion. For each one, include matching evidence under a `## Verification` section. If a behavior was not verified, label it `Not verified` and do not use completion wording for that behavior.

For browser-observable work, verify in the browser when the project rules provide browser tooling. For backend-only work, run the relevant tests or framework commands. For docs/config/tooling, validate the consuming command or file shape where practical.

## OpenSpec Integration

When the task is OpenSpec apply or validation:

- Read the command/rule/skill instructions first: apply, verify, safe-apply, and this multiagente skill.
- Use `openspec status --change "<slug>" --json`, `openspec instructions apply --change "<slug>" --json`, and `openspec validate "<slug>"` when available.
- Read every `contextFiles` path returned by OpenSpec before implementation.
- Work pending `tasks.md` items in order unless the spec explicitly says otherwise.
- Mark a task complete only after implementation and matching verification for that task.
- If the session cannot complete all tasks, the final response must show the remaining unchecked tasks and why they remain.
- Never let an OpenSpec apply/verify turn end with hidden partial state.
