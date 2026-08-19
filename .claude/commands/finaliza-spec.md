---
description: "Commit all pending work in the current window, then archive its OpenSpec change (/archiva-tarea) — only if the change is fully complete"
argument-hint: "[slug]"
---

# Finaliza spec (commit + archive)

You are running **finaliza-spec**. Invoking this command is the developer's **explicit authorization to `git commit`** the pending work of the current window and then archive the corresponding OpenSpec change. Three steps, in order: **(1) resolve slug, (2) verify the change is complete — refuse otherwise, (3) commit everything, (4) archive**.

> Scope of the authorization: this command authorizes **`git commit` only**. It does **not** authorize `git push`, `git merge`, `git rebase`, tags, or any remote operation. Never push.

## 1. Resolve `<slug>`

Parse the slug as the **first token after** `finaliza-spec` (optional leading `/`), separated by **whitespace only** — no colon required. Example: `/finaliza-spec add-property-management-and-scoping`.

If missing, infer it from the conversation context (the change just worked on). If still ambiguous, run `openspec list --json` and let the developer pick an **active** change with the AskUserQuestion tool — do **not** guess.

## 2. Completion gate — refuse if the change is not complete

**Hard gate. This runs before any `git add`, `git commit`, or archive.** If the change is not fully complete, **do nothing that mutates state**: no staging, no commit, no move. Report the incomplete items and stop.

Evaluate completion with the same definition the archive workflow uses:

1. **Artifact completion:**
   ```bash
   openspec status --change "<slug>" --json
   ```
   Any artifact reported as incomplete fails the gate.
2. **Task completion:** read the change's tasks file (typically `openspec/changes/<slug>/tasks.md`) and count checkboxes. Any task marked `- [ ]` (incomplete) fails the gate.
   - If **no** tasks file exists, treat that alone as non-blocking for the task check (an artifact-only change), but the artifact check above still governs.

**If the gate fails** (one or more incomplete artifacts and/or one or more `- [ ]` tasks):

- **Stop immediately.** Do not stage, commit, or archive anything.
- Report exactly what is incomplete: the list of incomplete artifacts and the count + titles of unchecked tasks.
- Tell the developer to finish the outstanding work (or, if the checkboxes are simply not updated, to update `tasks.md`) and re-run `/finaliza-spec`.
- Do **not** offer a "commit anyway" or "archive anyway" override — this command is complete-only by design. If the developer genuinely wants to archive an incomplete change, they can use `/archiva-tarea <slug>` directly, which has its own warning + confirmation flow.

Only when the gate passes (**all artifacts complete and every task `- [x]`**) continue to step 3.

## 3. Commit everything in the current window

1. Inspect the working tree so the commit message is accurate:
   ```bash
   git status -sb
   git diff --stat
   ```
2. Confirm the current branch is **not** `main` (production). If it is `main`, stop and ask the developer how to proceed — do not commit to `main`.
3. Stage **all** pending changes (tracked, untracked, deletions):
   ```bash
   git add -A
   ```
4. Commit with a **single, meaningful English message** in imperative mood that summarizes the window's work and references the change. First line ≤72 chars. End the message body with the trailer:
   ```
   Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
   ```
   Example first line: `Complete <slug> and archive OpenSpec change`.
5. Report the resulting commit hash and short subject. **Do not push.**

If `git status` shows a clean tree (nothing to commit), state that plainly and continue to step 4 — an already-committed window is not an error.

## 4. Archive the OpenSpec change

Delegate to the canonical archive workflow — same behavior as **`/archiva-tarea <slug>`** / **`/opsx-archive <slug>`**:

- Read and obey `.claude/commands/opsx-archive.md`.
- Check artifact and task completion; if incomplete, follow that file's warning + confirmation rules.
- Assess delta-spec sync state and, if delta specs exist, run the sync assessment before moving.
- Move `openspec/changes/<slug>/` to `openspec/changes/archive/YYYY-MM-DD-<slug>/` using the current date.

Do not archive unrelated changes.

## 5. Summary

Report, in this order:
- **Completion gate:** passed (all artifacts complete, all tasks checked). If it had failed, this section would list the blockers and no other step would have run.
- **Commit:** `<hash>` — `<subject>` (or "nothing to commit").
- **Archive:** final path `openspec/changes/archive/YYYY-MM-DD-<slug>/`, spec-sync status, and any warnings surfaced during archive.
- Reminder that nothing was pushed; the developer must push/open the PR to `develop` themselves.
