# Full example override: everything on

[`examples/override/`](../override/README.md) is the careful starting point: it installs the three default modules
and leaves every opt-in behaviour off. This folder is the other end: **every module and every option the toolkit can
use on its own**, so that someone who installs it from zero can try all of it. It holds only the values that differ
from the defaults in `global/config/`; every key it leaves out keeps its default.

## Try it without touching your own `~/.claude`

```bash
bash examples/override-full/try.sh
```

It installs the toolkit with this override into a throwaway `HOME` and runs every check the toolkit has:

1. `install --dry-run`, then `install` and `status`;
2. `verify`: the contract probes of every installed piece, with this override's values;
3. the pieces' own self-tests: `supervisor-lock self-test`, `test-account self-test` and, on a desktop session
   (it needs a running `gvfs` process), `process-kill-gate --self-test`;
4. `drift` (the install matches toolkit + override) and a second `install` that must change nothing;
5. `uninstall`, and a check that none of the files the install wrote is left, nor the bytecode Python made of
   them. The logs and state the pieces wrote while they ran stay: they are the user's, and `uninstall` keeps them
   on a real machine too.

Every variable that could point a piece at real state is dropped, the heavy-job semaphore gets its own folder
inside the throwaway `HOME`, and the folder is removed when every step passes. On a failure it is kept, with one
log per step. `TRY_KEEP=1` keeps it on success too, so you can look around. Pass another folder to try your own
override the same way: `bash examples/override-full/try.sh ~/.config/claude-toolkit`.

The CI runs the same script on every push, so this example cannot fall behind the toolkit.

## Install it for real

```bash
cp -r examples/override-full ~/.config/claude-toolkit      # or merge it into the override you already have
./install.sh install --dry-run
./install.sh install
```

Read what the opt-in modules change before you do: `sessions` makes the sessions you start from the desktop app
run without permission prompts, `supervision` lets one supervisor session per project order the others and
answers their questions with a decision panel, and `heavy-jobs` denies heavy commands (suites, builds, installs,
emulators) that are not launched through its semaphore. `accounts` installs the session sync between Claude
accounts and `account-switch`, which resumes the sessions a switch left stopped; they only run once you start
the sync's service. `routines` installs the machine's own routine engine, which runs nothing until you add
its timer. The [main README](../../README.md#modules) has the table.

## What each file turns on

| Path | Effect |
|---|---|
| `override.yaml` | all eight modules: `openspec`, `core`, `devtools`, `sessions`, `supervision`, `heavy-jobs`, `accounts`, `routines` |
| `config/supervision.json` | the four message exceptions (`account_switch`, `project_resume`, `skill_reload`, `supervisor_revive`), and `~/.claude` as the folder whose sessions may send a skill reload or a revive |
| `config/heavy-job.json` | two slots for compiling and tests; set what your machine can take |
| `config/worktree-location.json`, `config/test-account.json` | the worktree root and the notes folder test users must never be written to |
| `files/rules/my-team-conventions.md` | a rule of your own, added next to the toolkit's |
| `files/scripts/my-stop-notifier` + `hooks/personal.json` | a script of your own and the hook that runs it |
| `append/rules/worktrees-ubicacion.md` | text appended to a toolkit rule |

## Switches that grant authority stay off

`deploy_preauthorised`, `archive_preauthorised`, `excluded_projects` and `deploy_rule` in `config/supervision.json`
decide whether a supervisor may deploy, or archive finished sessions, without asking. An example never grants
that: they keep their defaults (off), so a supervisor leaves those decisions in `ask-queue` and goes on with the
rest. The supervisor-lock self-test checks what a supervisor does with deploying and archiving authorised and not
authorised, so `try.sh` covers both anyway. To grant them on your machine, add the keys to your own
`config/supervision.json`, naming the rule that authorises it:

```json
{"deploy_preauthorised": true, "deploy_rule": "my-deploy-rule.md", "excluded_projects": ["a-project-that-is-real-production"],
 "archive_preauthorised": true}
```

## Where "everything" ends

Some options act together with pieces of other modules, of the desktop app or of the machine (the module manifests
list them under `project_provided`). Without them those options are installed but do nothing, and the pieces say so
instead of failing:

| Option | Needs | Without it |
|---|---|---|
| `account_switch` message exception | the `accounts` module, with the `claude-sessions-sync` service started (it tells `account-switch` about each switch) | the marker is plain text |
| `project_resume` message exception, project pauses in heavy-job | `project-pause` (module `supervision`) | the marker is plain text; nothing is paused |
| `supervisor_revive` message exception | a scheduled task of the desktop app with the prompt `scheduled-tasks/reanimar-supervisoras/SKILL.md` (module `supervision`), which runs `supervisor-lock revive` and sends the texts it prints | run the plan by hand; the gate lets the marker through only for a supervisor the plan named |
| supervisor-lock `cloud` commands, heavy-job's cloud guard (exit 76) | `cloud-tests` (module `heavy-jobs`) and a project's `.claude/cloud-tests.json` | `CLOUD-UNAVAILABLE`; heavy-job runs everything locally |
| notifications and nudges of the supervisor watchdog, the second step of `supervisor-stop-gate` | `routines` (module `routines`), `session-nudge` and `handoff-guard` (module `supervision`) | skipped |
| the `sessions` gates | the Claude desktop app's session tools | they never fire |

`skill_reload` needs nothing more: a session started in `~/.claude` can tell every supervisor that has not read the
latest change of a skill or a rule to reload it.
