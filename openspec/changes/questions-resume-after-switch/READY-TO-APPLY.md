# READY TO APPLY — questions-resume-after-switch

> Written by the hydrate phase of `repasa-spec` (P2 of `run-spec`).

## Verdict

**READY TO APPLY.** The eight FACT gaps of `GAPS.md` are settled in `spec.md`, `design.md` and `tasks.md`:

- Corrupt or unreadable queue: an id that is not listed is unknown, and one corrupt project does not hide the others
  (G-01, G-02).
- Scenarios for several projects, one row per session, answered or dismissed items (G-03, G-04, G-05).
- A requirement that supervisor and closing rows do not change (G-06).
- The gate test sends the real text (G-07).
- Task 5.1 runs only the checks allowed in this run (G-09).

## Checks

| Check | Result |
|---|---|
| `openspec validate questions-resume-after-switch --strict` | valid, exit 0 |
| Tasks with `[prod-verify]` | 0 |
