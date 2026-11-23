# supervisor-lock self-test: every path inside its sandbox (task 8.5)

`supervisor-lock self-test` never runs its checks in the caller's environment. It works in two steps.

The parent (`selftest.enter_sandbox`) creates a new sandbox `<tmp>/supervisor-lock-sandbox-*` and starts the self-test
again as a child. In the child, HOME, TMPDIR, `CLAUDE_TOOLKIT_CONFIG_DIR`, the XDG directories and `XDG_RUNTIME_DIR`
all point inside the sandbox. The parent removes every variable that could point elsewhere: `SUPERVISOR_*`,
`ASK_GATE*`, `ASK_QUEUE*`, `CLOUD_TESTS_*`, `ACCOUNT_SWITCH*`, `PROJECT_PAUSE*`, `CROSS_PROJECT_GATE_*`,
`CLAUDE_TOOLKIT_*`, `XDG_*`, `GIT_*`, `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_HOST_SESSION_ID`,
`DBUS_SESSION_BUS_ADDRESS`, `TMPDIR`/`TMP`/`TEMP` and `PYTHONPATH`. Only `SUPERVISOR_SKIP_INSTALLED_LINT` is kept.

The sandbox HOME holds what an installed `~/.claude` would:
- `scripts/supervisor-lock`, a link to the entry point under test;
- a copy of the `skills/` and `rules/` that ship next to it;
- an empty `toolkit/config`, so every config piece gives its defaults.

The parent removes the sandbox when the child exits.

Before its first check, the child resolves each path below (`selftest.sandbox_paths`). It compares both the absolute
path and the realpath against the sandbox. If any of them falls outside (or is unset), the child prints
`SANDBOX REFUSED <what>: <path>` and exits 2 without running a single check. The tests
`test_the_self_test_refuses_paths_outside_its_sandbox` and `test_a_sandboxed_child_refuses_a_state_path_set_outside`
cover this.

Exempt on purpose: the code under test, meaning the entry point and the package `scripts/lib/supervisor`, plus the
`ask-queue` next to it. The child runs them; it never writes to them.

## Paths checked before any check runs

| What | Default it resolves to (inside the sandbox HOME unless set) |
|---|---|
| HOME | sandbox `home/` |
| temp dir | sandbox `tmp/` (each check's `tmp` is a `mkdtemp` inside it) |
| toolkit config | sandbox `home/.claude/toolkit/config` (empty: defaults) |
| runtime dir (sockets) | sandbox `run/` |
| supervisor state | `~/.claude/supervisor` |
| CLI session registry | `~/.claude/sessions` |
| app session records | `~/.config/Claude/claude-code-sessions` (config `app_sessions_dir`) |
| transcripts | `~/.claude/projects` |
| skill | `~/.claude/skills/supervisa-sesiones/SKILL.md` (config `skill_file`) |
| skill lint roots | the skill's folder, `~/.claude/rules`, `~/.claude/commands/supervisa-sesiones.md`, config `skill_lint_roots` |
| ask gate state | `~/.claude/state/ask-gate` |
| cross-project decisions log | `~/.claude/state/cross-project-message-gate/decisions.log` |
| question queue | `~/.claude/state/ask-queue` |
| installed question queue CLI | `~/.claude/scripts/ask-queue` |
| optional pieces | `~/.claude/scripts/{account-switch,cloud-tests,project-pause,handoff-guard,heavy-job,routines,session-nudge}` (absent: the tool degrades) |

## Paths per test group

Every group runs its subprocesses with the suite's `env`. That `env` redirects all state into the group's `tmp`
(inside the sandbox): `SUPERVISOR_LOCK_HOME` (a folder `home` inside `tmp`, written `LOCK_HOME` below), `SUPERVISOR_SESSIONS_DIR=tmp/cli-sessions`,
`SUPERVISOR_APP_SESSIONS_GLOB=tmp/app/*/*/local_*.json`, `SUPERVISOR_PROJECTS_DIR=tmp/projects`,
`SUPERVISOR_SKILL_FILE=tmp/SKILL.md`, `ASK_GATE_DIR=tmp/ask-gate`, `ASK_QUEUE_DIR=tmp/ask-queue`,
`ASK_GATE_XPROJECT_LOG=tmp/xproject-decisions.log`, `GIT_CONFIG_GLOBAL=/dev/null`, and fakes in `tmp` for
heavy-job, notify, session-nudge and handoff-guard. In-process checks read the same paths through `os.environ`.

| Group | Paths it uses beyond the shared `env` |
|---|---|
| 0 memo | `tmp/memo/*.json` |
| 1 project, registry-dir | git repos `tmp/proj`, `tmp/proj-wt`, `tmp/other`, `tmp/plain`; `tmp/proj/.claude/context/supervisor/` |
| 2 lock lifecycle | `LOCK_HOME/locks/`, `LOCK_HOME/closed/` |
| 3, 3b sessions, transcripts | `tmp/cli-sessions/`, `tmp/app/a/b/`, `tmp/projects/<slug>/` |
| 4, 4b, 4c wait | the same, plus `tmp/heavy.txt`, the registry dir `tmp/registries/` |
| 5, 5b release, open | `LOCK_HOME/locks/`, app records in `tmp/app/` |
| 6, 6a, 6b, 6c, 6d watchdog, revive | `tmp/notify.log`, `tmp/nudge.log`, `tmp/nudge.out`, `LOCK_HOME/revive.json` and the alert fields of the locks in `LOCK_HOME/locks/` |
| 7, 7a, 7a2, 7a2b, 7a3 hook, closable | `LOCK_HOME/closable/`, `LOCK_HOME/holds/`, `LOCK_HOME/verdicts/`, `LOCK_HOME/answered/`, `LOCK_HOME/hook*.log`, `tmp/config-archive-authorised/` (a config piece of its own for the authorised wording), `tmp/dev-transcript.jsonl`; the stop gate next to the entry point, run with HOME = the sandbox HOME |
| account_has_usage | `tmp/fake-account-switch`, `tmp/fake-usage.json`, `LOCK_HOME/usage-cache.json` |
| 8 workspace mode | `tmp/ws/` and its nested repos, `tmp/ws-a-wt`, `tmp/ws-extra` |
| 9, 10, 12 mailbox, skill changes | `tmp/SKILL.md`, `LOCK_HOME/locks/` |
| 11, 11b, 11b-2..4 hook PreToolUse, ask gate | `tmp/ask-gate/`, `tmp/ask-queue/`, `tmp/xproject-decisions.log`, transcripts in `tmp/projects/`; the `ask-queue` next to the entry point (set as `ASK_QUEUE_BIN`, so the hook reads it too) |
| 30 cloud and machine queue | `tmp/cproj` (git, remote URL only, no network), `tmp/ct-state/`, `tmp/cloud-api.json`, `tmp/fake-cloud-tests` (stand-in for the optional provider), `tmp/fake-claude`, `tmp/claude-sent.log`, `tmp/heavy.json` |
| 31 backlog, guard, language, report, skill lint | `tmp/guard-home/`, `tmp/gproj` (git), `tmp/greg/`, `tmp/goon.jsonl`, `tmp/incident.jsonl`, `tmp/lint-skill/`; the installed-skill lint reads the sandbox copy of `skills/` and `rules/` |
