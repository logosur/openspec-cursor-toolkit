# Example override

Your own layer on top of the toolkit. It lives **outside** this repository, by default in
`~/.config/claude-toolkit/` (or wherever `CLAUDE_TOOLKIT_OVERRIDE` or `--override` points), and it is
never published. Copy this folder there and edit it:

```bash
cp -r examples/override ~/.config/claude-toolkit
./install.sh install --dry-run      # see what would change
./install.sh install
```

| Path | Effect |
|---|---|
| `override.yaml` | modules to install, files to `remove`, live files `excluded` from management, declared `equivalence` differences |
| `config/<piece>.json` | values for one piece (for example the worktree root); they win over `global/config/` |
| `files/<dest>` | replaces the toolkit file at `<dest>` (relative to `~/.claude`), or adds a new one |
| `append/<dest>` | text appended to the toolkit file at `<dest>` |
| `hooks/*.json` | extra hook entries, merged into the `hooks` key of `settings.json` |
| `privacy-denylist.txt` | private terms (one per line) the privacy check must never let into the toolkit repo |
| `override.lock.json` | written by `pull`: the toolkit version each replaced file was based on |
| `archive/` | literal copies kept only for reference; never installed |

A replacement must keep the contract of the piece it replaces (`global/contracts/`): `install` runs
the probes in a throwaway HOME and refuses (exit 3) a replacement that breaks them.

## Keeping it under version control, privately

The override holds personal data, so it gets its own **private** repository; never a fork of this one.

1. `cd ~/.config/claude-toolkit && git init`
2. Add a `.gitignore` with anything that must not leave the machine at all (tokens, `*.env`).
3. Commit, then create a private repository on your Git host yourself and push to it.

Nothing in the toolkit creates that repository or pushes it for you.

## Moving changes between the live dir, the override and the toolkit

```bash
./install.sh drift                                  # what changed since the last install
./install.sh pull rules/my-rule.md                  # live file -> override (private, the default)
./install.sh pull rules/x.md --to toolkit           # live file -> toolkit, only if the privacy check is clean
./install.sh equivalence --live ~/.claude           # every difference explained, or exit 1
```
