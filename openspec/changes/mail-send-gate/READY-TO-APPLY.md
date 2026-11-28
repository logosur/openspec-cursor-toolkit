# READY TO APPLY — mail-send-gate

> Written by the hydrate phase of `repasa-spec` (P2 of `run-spec`), after `GAPS.md` iteration 1–5.

## Verdict

**READY TO APPLY.** The nine FACT gaps of `GAPS.md` are settled in `spec.md`, `design.md` and `tasks.md`:

- Bash matching by command position, quote-aware, with the must-pass look-alikes and the wrapper denies as scenarios
  (G-01, G-02, G-06).
- An interpreter's own code only (G-03), PHP covered (G-07).
- Per-command host reading and an anchored local-host match with `::1` (G-04).
- One connector table with non-mail look-alikes (G-09).
- Broken config: code defaults that deny, with the source read from `process-kill-gate`,
  `commit-authorship-gate` and `toolkit_config.py` (design D9, G-05).
- Task 6.2 runs only checks allowed in this phase (G-08).

## Checks

| Check | Result |
|---|---|
| `openspec validate mail-send-gate --strict` | valid, exit 0 |
| Tasks with `[prod-verify]` | 0 |
