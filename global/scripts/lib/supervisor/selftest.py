"""The self-test, imported only by the self-test subcommand."""
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from datetime import timezone

from . import (
    backlog, census, cloud, deny, developer, guard_report,
    hook as hook_mod, human_turns, language, lint, lock as lock_mod, projects,
    providers, revival, runtime, session_roles, settings, transcripts,
    unattended, util, watch, watchdog,
)


# ---------------------------------------------------------------- self-test sandbox
# The self-test never touches the developer's real state. `self-test` re-runs itself as a child whose HOME, temp dir,
# toolkit config and every state path live in a new sandbox, with the variables that could point elsewhere removed;
# the child checks every path it is about to use (sandbox_paths) and refuses to run if one resolves outside.
SANDBOX_ENV = 'SUPERVISOR_SELFTEST_SANDBOX'
INSTALLED_CONFIG_ENV = 'SUPERVISOR_SELFTEST_INSTALLED_CONFIG'   # set by the sandbox, never by hand
SANDBOX_SCRUB_PREFIXES = ('SUPERVISOR_', 'ASK_GATE', 'ASK_QUEUE', 'CLOUD_TESTS_', 'ACCOUNT_SWITCH', 'PROJECT_PAUSE',
                          'CROSS_PROJECT_GATE_', 'CLAUDE_TOOLKIT_', 'XDG_', 'GIT_')
SANDBOX_SCRUB_NAMES = ('CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_HOST_SESSION_ID',
                       'DBUS_SESSION_BUS_ADDRESS', 'FAKE_USAGE', 'TMPDIR', 'TMP', 'TEMP', 'PYTHONPATH')
SANDBOX_KEEP = ('SUPERVISOR_SKIP_INSTALLED_LINT',)


def enter_sandbox():
    """Run the self-test in a child confined to a new sandbox; its exit code. The pieces that ship next to the entry
    point (the skill and the rules) are copied in, as an installed ~/.claude would hold them; the entry point itself is
    linked, so the child runs the code under test."""
    root = os.path.realpath(tempfile.mkdtemp(prefix='supervisor-lock-sandbox-'))
    home = os.path.join(root, 'home')
    claude = os.path.join(home, '.claude')
    for d in (os.path.join(claude, 'scripts'), os.path.join(claude, 'toolkit', 'config'), os.path.join(root, 'tmp'),
              os.path.join(home, '.config'), os.path.join(home, '.local', 'state'), os.path.join(home, '.cache'),
              os.path.join(home, '.local', 'share'), os.path.join(root, 'run')):
        os.makedirs(d)
    os.chmod(os.path.join(root, 'run'), 0o700)
    entry = os.path.realpath(runtime.ENTRY)
    os.symlink(entry, os.path.join(claude, 'scripts', 'supervisor-lock'))
    shipped = os.path.dirname(os.path.dirname(entry))
    for name in ('skills', 'rules'):
        if os.path.isdir(os.path.join(shipped, name)):
            shutil.copytree(os.path.join(shipped, name), os.path.join(claude, name), symlinks=False)
    # The installed skill is linted with the installed config: a machine whose skill has its own anchors sets them
    # there. Every other check runs with the defaults.
    installed_cfg = os.path.join(shipped, 'toolkit', 'config')
    installed_copy = os.path.join(root, 'installed-config')
    if os.path.isdir(installed_cfg):
        shutil.copytree(installed_cfg, installed_copy, symlinks=False)
    env = {k: v for k, v in os.environ.items()
           if k in SANDBOX_KEEP or not (k.startswith(SANDBOX_SCRUB_PREFIXES) or k in SANDBOX_SCRUB_NAMES)}
    env.update({'HOME': home, 'TMPDIR': os.path.join(root, 'tmp'),
                'CLAUDE_TOOLKIT_CONFIG_DIR': os.path.join(claude, 'toolkit', 'config'),
                'XDG_CONFIG_HOME': os.path.join(home, '.config'), 'XDG_STATE_HOME': os.path.join(home, '.local', 'state'),
                'XDG_CACHE_HOME': os.path.join(home, '.cache'), 'XDG_DATA_HOME': os.path.join(home, '.local', 'share'),
                'XDG_RUNTIME_DIR': os.path.join(root, 'run'), SANDBOX_ENV: root})
    if os.path.isdir(installed_copy):
        env[INSTALLED_CONFIG_ENV] = installed_copy
    try:
        return subprocess.run([sys.executable, entry, 'self-test'], env=env, cwd=root).returncode
    finally:
        shutil.rmtree(root, ignore_errors=True)


def first_word(cmd):
    import shlex
    try:
        parts = shlex.split(cmd)
    except ValueError:
        parts = [cmd]
    return os.path.expanduser(parts[0]) if parts else ''


def sandbox_paths():
    """{what: path} of every path the self-test reads or writes by default: app records, CLI registry, sockets, state,
    transcripts, skill, queue, config, temp dir and the optional pieces it may call."""
    from . import ask_gate
    paths = {
        'HOME': os.path.expanduser('~'),
        'temp dir': tempfile.gettempdir(),
        'toolkit config': os.environ.get('CLAUDE_TOOLKIT_CONFIG_DIR', ''),
        'runtime dir (sockets)': os.environ.get('XDG_RUNTIME_DIR', ''),
        'supervisor state': util.home(),
        'CLI session registry': census.cli_dir(),
        'app session records': os.path.dirname(os.path.dirname(os.path.dirname(census.app_glob()))),
        'transcripts': transcripts.projects_dir(),
        'skill': lint.skill_file(),
        'ask gate state': ask_gate.ask_gate_dir(),
        'cross-project decisions log': ask_gate.ask_gate_xproject_log(),
        'question queue': os.path.expanduser(os.environ.get('ASK_QUEUE_DIR', '~/.claude/state/ask-queue')),
        'question queue CLI (installed)': os.path.expanduser(os.environ.get('ASK_QUEUE_BIN', '~/.claude/scripts/ask-queue')),
        'account switch': os.path.expanduser(os.environ.get('SUPERVISOR_ACCOUNT_SWITCH', '~/.claude/scripts/account-switch')),
        'cloud provider': os.path.expanduser(os.environ.get('SUPERVISOR_CLOUD_TESTS', providers.CLOUD_TESTS_BIN)),
        'project pause': os.path.expanduser(os.environ.get('PROJECT_PAUSE_BIN', '~/.claude/scripts/project-pause')),
        'handoff guard': os.path.expanduser(os.environ.get('SUPERVISOR_HANDOFF_GUARD', '~/.claude/scripts/handoff-guard')),
        'machine queue': first_word(os.environ.get('SUPERVISOR_HEAVY_JOB', '~/.claude/scripts/heavy-job')),
        'notifier': first_word(os.environ.get('SUPERVISOR_NOTIFY', '~/.claude/scripts/routines notify')),
        'nudger': first_word(os.environ.get('SUPERVISOR_NUDGE', '~/.claude/scripts/session-nudge')),
    }
    paths.update({f'lint root {i}': p for i, p in enumerate(lint.lint_roots())})
    return paths


def sandbox_refusals(root):
    """[(what, path)] of the paths that are not inside `root` (by absolute path and by resolved path)."""
    root = os.path.realpath(root)
    bad = []
    for what, path in sandbox_paths().items():
        if not path:
            bad.append((what, '(unset)'))
            continue
        for p in (os.path.abspath(path), os.path.realpath(path)):
            if not (p == root or p.startswith(root + os.sep)):
                bad.append((what, path))
                break
    return bad


FAKE_CLOUD_PROVIDER = r'''"""Sandbox stand-in for the optional cloud provider: sessions from $CLOUD_TESTS_API_FAKE."""
import json
import os
import re
import subprocess
from datetime import datetime


def __getattr__(name):
    if name == 'STATE_DIR':
        return os.environ.get('CLOUD_TESTS_STATE', '')
    raise AttributeError(name)


def github_slug(url):
    m = re.search(r'github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?$', url or '')
    return m.group(1) if m else ''


def sid_key(sid):
    sid = str(sid or '')
    for prefix in ('cse_', 'session_'):
        if sid.startswith(prefix):
            return sid[len(prefix):]
    return sid


def iso_epoch(text):
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _api():
    with open(os.environ['CLOUD_TESTS_API_FAKE']) as fh:
        return json.load(fh)


def active_cloud_sessions():
    data = _api()
    gone = {sid_key(x) for x in data.get('archived', [])}
    return [s for s in data.get('sessions', []) if sid_key(s.get('id')) not in gone]


def api_call(method, path, body=None):
    renamed = re.fullmatch(r'/v1/code/sessions/([^/]+)', path)
    if method == 'PUT' and renamed:
        data = _api()
        data.setdefault('renamed', []).append([renamed.group(1), (body or {}).get('title')])
        for row in data.get('sessions', []):
            if row.get('id') == renamed.group(1):
                row['title'] = (body or {}).get('title')
        with open(os.environ['CLOUD_TESTS_API_FAKE'], 'w') as fh:
            json.dump(data, fh)
        return 200, {}
    m = re.fullmatch(r'/v1/code/sessions/([^/]+)/archive', path)
    if method != 'POST' or not m:
        return 404, {}
    data = _api()
    data.setdefault('archived', []).append(m.group(1))
    with open(os.environ['CLOUD_TESTS_API_FAKE'], 'w') as fh:
        json.dump(data, fh)
    return 200, {}


def send_followup(project, session_id, text):
    r = subprocess.run([os.environ['CLOUD_TESTS_CLAUDE'], '--resume', session_id, '-p', text],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout or r.stderr).strip()
'''


def cmd_self_test(args):
    root = os.environ.get(SANDBOX_ENV)
    if not root:
        return enter_sandbox()
    refused = sandbox_refusals(root) if os.path.isdir(root) else [('sandbox', root)]
    if refused:
        for what, path in refused:
            where = 'is not a directory' if what == 'sandbox' else f'is outside {root}'
            print(f'SANDBOX REFUSED {what}: {path} {where}', file=sys.stderr)
        return 2
    os.environ['SUPERVISOR_SELFTEST_NO_REPORT'] = '1'  # report_block has its own checks below
    tmp = tempfile.mkdtemp(prefix='supervisor-lock-test-')
    lock_home = os.path.join(tmp, 'home')
    sessions_dir = os.path.join(tmp, 'cli-sessions')
    app_dir = os.path.join(tmp, 'app', 'a', 'b')
    for d in (sessions_dir, app_dir):
        os.makedirs(d)
    projects_t = os.path.join(tmp, 'projects')
    notify_log, heavy_txt = os.path.join(tmp, 'notify.log'), os.path.join(tmp, 'heavy.txt')
    nudge_log, nudge_out = os.path.join(tmp, 'nudge.log'), os.path.join(tmp, 'nudge.out')
    os.makedirs(projects_t)
    for name, body in (('fake-notify', f'printf \'%s|%s\\n\' "$1" "$2" >> {notify_log}'), ('fake-heavy', f'cat {heavy_txt}'),
                       ('fake-nudge', f'echo "$*" >> {nudge_log}; cat {nudge_out}; exit $(cat {nudge_out}.rc 2>/dev/null || echo 0)'),
                       # handoff-guard match: a hit only for «me confirmes»
                       ('fake-handoff', 'grep -q "me confirmes" && printf "handoff\\tCuando me confirmes\\n" && exit 0; exit 1')):
        with open(os.path.join(tmp, name), 'w') as fh:
            fh.write(f'#!/bin/sh\n{body}\n')
        os.chmod(os.path.join(tmp, name), 0o755)
    open(notify_log, 'w').close()
    open(heavy_txt, 'w').close()
    skill = os.path.join(tmp, 'SKILL.md')
    open(skill, 'w').write('skill v1\n')
    env = dict(os.environ, SUPERVISOR_SKILL_FILE=skill, SUPERVISOR_LOCK_HOME=lock_home, SUPERVISOR_SESSIONS_DIR=sessions_dir,
               SUPERVISOR_APP_SESSIONS_GLOB=os.path.join(tmp, 'app', '*', '*', 'local_*.json'),
               SUPERVISOR_PROJECTS_DIR=projects_t, SUPERVISOR_HEAVY_JOB=os.path.join(tmp, 'fake-heavy'),
               SUPERVISOR_NOTIFY=os.path.join(tmp, 'fake-notify'), SUPERVISOR_NUDGE=os.path.join(tmp, 'fake-nudge'),
               SUPERVISOR_HANDOFF_GUARD=os.path.join(tmp, 'fake-handoff'),
               # what a reload covers: a folder of the sandbox, so the copied skills and rules never move the floor
               SUPERVISOR_RELOAD_GLOBS=os.path.join(tmp, 'reload-watch', '*'),
               ASK_GATE_DIR=os.path.join(tmp, 'ask-gate'), ASK_QUEUE_DIR=os.path.join(tmp, 'ask-queue'),
               ASK_GATE_XPROJECT_LOG=os.path.join(tmp, 'xproject-decisions.log'),
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    for name in ('ASK_GATE', 'ASK_GATE_PRESENCE_MIN', 'ASK_QUEUE_BIN', 'ASK_QUEUE_REASK_H'):
        env.pop(name, None)  # a developer's own kill switch must not leak into the suite
    # The watchdog and `beat` keep session titles in line by default (`titles_sync`); the checks below that read lock
    # titles and "nothing written" run with it off, and the titles section at the end calls `titles` directly.
    with open(os.path.join(env['CLAUDE_TOOLKIT_CONFIG_DIR'], 'supervision.json'), 'w') as fh:
        json.dump({'titles_sync': False}, fh)
    failures = []

    def check(name, ok):
        print(f'{"ok" if ok else "FAIL"} {name}')
        if not ok:
            failures.append(name)

    def run(*cli, cwd=None):
        return subprocess.run([sys.executable, runtime.ENTRY, *cli], capture_output=True, text=True, env=env, cwd=cwd)

    def sh(*cmd, cwd=None):
        subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True)

    def make_repo(path):
        sh('git', 'init', '-q', path)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init', cwd=path)

    repo = os.path.realpath(os.path.join(tmp, 'proj'))
    wt = os.path.join(tmp, 'proj-wt')
    other = os.path.realpath(os.path.join(tmp, 'other'))
    notrepo = os.path.join(tmp, 'plain')
    os.makedirs(notrepo)
    make_repo(repo)
    make_repo(other)
    sh('git', 'worktree', 'add', '-q', '-b', 'wt', wt, cwd=repo)
    wt = os.path.realpath(wt)

    # 0. read_json_files memo (in process): unchanged files are not parsed again, changed ones are, unread keys dropped
    memo_dir = os.path.join(tmp, 'memo')
    os.makedirs(memo_dir)
    memo_glob, memo_file = os.path.join(memo_dir, '*.json'), os.path.join(memo_dir, 'a.json')

    def memo_write(obj, bump):
        part = memo_file + '.part'
        with open(part, 'w') as fh:
            json.dump(obj, fh)
        os.replace(part, memo_file)  # what the app does: a new inode each write
        os.utime(memo_file, ns=(bump, bump))

    memo_write({'sessionId': 'one', 'remoteMcpServersConfig': {'big': 'x' * 5000}}, 10**18)
    first_read = list(census.read_json_files(memo_glob))
    check('memo: first read parses the file and drops the keys nobody reads',
          len(first_read) == 1 and first_read[0].get('sessionId') == 'one' and 'remoteMcpServersConfig' not in first_read[0])
    again = list(census.read_json_files(memo_glob))
    check('memo: an unchanged file comes from the memo (same object, not parsed again)',
          len(again) == 1 and again[0] is first_read[0])
    memo_write({'sessionId': 'two'}, 10**18 + 1)
    changed = list(census.read_json_files(memo_glob))
    check('memo: a changed file is parsed again', len(changed) == 1 and changed[0].get('sessionId') == 'two')
    with open(memo_file, 'w') as fh:
        fh.write('{"sessionId": "thr')  # caught half-written
    os.utime(memo_file, ns=(10**18 + 2, 10**18 + 2))
    check('memo: a half-written file is skipped, not served stale', list(census.read_json_files(memo_glob)) == [])
    memo_write({'sessionId': 'three'}, 10**18 + 3)
    check('memo: once complete it is read', [r.get('sessionId') for r in census.read_json_files(memo_glob)] == ['three'])
    os.remove(memo_file)
    check('memo: a deleted file is gone', list(census.read_json_files(memo_glob)) == [])

    # 1. project resolution + registry-dir
    p1 = json.loads(run('project', '--dir', repo, '--json').stdout or '{}')
    p2 = json.loads(run('project', '--dir', wt, '--json').stdout or '{}')
    check('project: worktree maps to the same key', bool(p1) and p1.get('key') == p2.get('key'))
    check('project: key is <name>-<8 hex>', p1.get('key', '').startswith('proj-') and len(p1.get('key', '')) == 13)
    check('project: checkout of a worktree is the main checkout', p2.get('checkout') == repo)
    check('project: other repo has another key', json.loads(run('project', '--dir', other, '--json').stdout)['key'] != p1.get('key'))
    r = run('project', '--dir', notrepo)
    check('project: not a git repo -> exit 2 + message', r.returncode == 2 and 'NOT A GIT REPOSITORY' in r.stderr)
    r = run('registry-dir', '--dir', wt)
    check('registry-dir: creates the dir in the main checkout', r.returncode == 0 and r.stdout.strip() == p1['registry_dir'] and os.path.isdir(p1['registry_dir']))
    run('registry-dir', '--dir', repo)
    exclude = open(os.path.join(repo, '.git', 'info', 'exclude')).read().splitlines()
    check('registry-dir: exclude line added once', exclude.count('/.claude/context/supervisor/') == 1)
    check('registry-dir: git now ignores the dir', subprocess.run(['git', '-C', repo, 'check-ignore', '-q', '.claude/context/supervisor/probe.md']).returncode == 0)

    # 2. acquire / beat / release / status / list / reclaim
    lock_file = os.path.join(lock_home, 'locks', p1['key'] + '.json')

    def load():
        with open(lock_file) as fh:
            return json.load(fh)

    def save(data):
        with open(lock_file, 'w') as fh:
            json.dump(data, fh)

    def shift_heartbeat(seconds):
        data = load()
        data['heartbeat'] = datetime.fromtimestamp(datetime.now().timestamp() - seconds).astimezone().isoformat(timespec='seconds')
        save(data)

    r = run('status', '--dir', repo)
    check('status: free', r.returncode == 0 and r.stdout.startswith('FREE '))
    r = run('acquire', '--dir', repo, '--session', 'A', '--title', 'first')
    check('acquire: free -> ACQUIRED, exit 0', r.returncode == 0 and r.stdout.startswith('ACQUIRED '))
    started = load()['started']
    r = run('acquire', '--dir', wt, '--session', 'A')
    check('acquire: same session from a worktree -> RESUMED, exit 0', r.returncode == 0 and r.stdout.startswith('RESUMED ') and load()['started'] == started and load()['title'] == 'first')
    held_before = open(lock_file).read()
    r = run('acquire', '--dir', repo, '--session', 'B')
    check('acquire: other session, fresh -> HELD, exit 3', r.returncode == 3 and r.stdout.startswith('HELD ') and 'heartbeat_age_s=' in r.stdout)
    check('acquire: other session, fresh -> lock left untouched', open(lock_file).read() == held_before)
    r = run('status', '--dir', repo)
    check('status: HELD line has session and title', r.stdout.startswith('HELD ') and 'session=A' in r.stdout and 'title=first' in r.stdout)
    check('status --session: the owner reads MINE for its own lock', run('status', '--dir', repo, '--session', 'A').stdout.startswith('MINE '))
    check('status --session: another session still reads HELD', run('status', '--dir', repo, '--session', 'B').stdout.startswith('HELD '))
    # work mode: normal by default, publish-first only with the developer's order, shown on the status line
    check('mode: default is normal', run('mode', '--dir', repo, '--get').stdout.strip() == 'normal'
          and 'mode=' not in r.stdout)
    r_m = run('mode', '--dir', repo, '--set', 'publish-first')
    check('mode: --set without --order refused (exit 2)', r_m.returncode == 2 and run('mode', '--dir', repo, '--get').stdout.strip() == 'normal')
    r_m = run('mode', '--dir', wt, '--set', 'publish-first', '--order', 'se publica primero y los tests van al final')
    check('mode: --set from a worktree -> MODE_SET, same project', r_m.returncode == 0 and r_m.stdout.startswith('MODE_SET ')
          and run('mode', '--dir', repo, '--get').stdout.strip() == 'publish-first')
    r_m = run('mode', '--dir', repo)
    check('mode: plain read shows the order', r_m.stdout.startswith('MODE ') and 'publish-first' in r_m.stdout and '«se publica primero' in r_m.stdout)
    check('mode: status line carries mode=publish-first', 'mode=publish-first' in run('status', '--dir', repo).stdout)
    check('mode: another project stays normal', run('mode', '--dir', other, '--get').stdout.strip() == 'normal')
    r_m = run('mode', '--dir', repo, '--set', 'normal', '--order', 'vuelve al modo habitual')
    check('mode: back to normal -> no flag on status', r_m.returncode == 0 and 'mode=' not in run('status', '--dir', repo).stdout)
    check('mode: a bad mode is refused by argparse', run('mode', '--dir', repo, '--set', 'yolo', '--order', 'x').returncode == 2)
    shift_heartbeat(7200 + 600)
    before = load()
    r = run('acquire', '--dir', repo, '--session', 'B')
    check('acquire: other session, stale -> STALE, exit 4', r.returncode == 4 and r.stdout.startswith('STALE '))
    check('acquire: stale lock left untouched', load() == before)
    r = run('reclaim', '--dir', repo, '--session', 'B', '--from', 'WRONG')
    check('reclaim: wrong --from -> HELD, exit 3, untouched', r.returncode == 3 and r.stdout.startswith('HELD ') and load() == before)
    r = run('reclaim', '--dir', repo, '--session', 'B', '--from', 'A', '--title', 'second')
    cur = load()
    check('reclaim: right --from -> RECLAIMED, exit 0', r.returncode == 0 and r.stdout.startswith('RECLAIMED ') and cur['session_id'] == 'B')
    check('reclaim: reclaimed_from recorded', cur.get('reclaimed_from', {}).get('session_id') == 'A' and set(cur['reclaimed_from']) == {'session_id', 'heartbeat', 'state', 'registry'})
    r = run('beat', '--dir', repo, '--session', 'A')
    check('beat: non-owner -> NOT OWNER, exit 5', r.returncode == 5 and 'NOT OWNER' in r.stderr)
    r = run('release', '--dir', repo, '--session', 'A')
    check('release: non-owner -> NOT OWNER, exit 5, file kept', r.returncode == 5 and os.path.exists(lock_file))
    r = run('beat', '--dir', repo, '--session', 'B', '--state', 'paused', '--phase', 'merge', '--round', '3')
    cur = load()
    check('beat: owner updates state/phase/round', r.returncode == 0 and r.stdout.startswith('BEAT ') and cur['state'] == 'paused' and cur['phase'] == 'merge' and cur['round'] == 3)
    data = load()
    saved_state, saved_started = data.get('state'), data.get('started')
    data['state'] = 'running'
    data['started'] = datetime.fromtimestamp(datetime.now().timestamp() - 3600).astimezone().isoformat(timespec='seconds')
    save(data)
    r = run('beat', '--dir', repo, '--session', 'B')
    check('beat: running 1 h with no mailbox -> tells the owner on stderr (survives `>/dev/null`), stdout unchanged',
          r.returncode == 0 and r.stdout.strip().startswith('BEAT ') and '\n' not in r.stdout.strip()
          and 'SIN SESIÓN DE PREGUNTAS' in r.stderr and '--mailbox' in r.stderr)
    r = run('beat', '--dir', repo, '--session', 'B', '--mailbox', 'local_box_selftest')
    check('beat: with --mailbox -> no NOMAILBOX line', r.returncode == 0 and 'SIN SESIÓN DE PREGUNTAS' not in r.stdout + r.stderr)
    data = load()
    data.pop('mailbox', None)
    for field, value in (('state', saved_state), ('started', saved_started)):
        if value is None:
            data.pop(field, None)
        else:
            data[field] = value
    save(data)
    shift_heartbeat(3600)
    r = run('acquire', '--dir', repo, '--session', 'C')
    check('ttl: paused lock 1 h old is still fresh (3)', r.returncode == 3)
    shift_heartbeat(3 * 3600)
    r = run('acquire', '--dir', repo, '--session', 'C')
    check('ttl: paused lock 3 h old is stale (4)', r.returncode == 4)
    data = load()
    data['state'] = 'running'
    save(data)
    shift_heartbeat(3600)
    r = run('acquire', '--dir', repo, '--session', 'C')
    check('ttl: running lock 1 h old is stale (4)', r.returncode == 4)
    r = run('list')
    check('list: shows the lock with checkout', r.returncode == 0 and 'STALE ' in r.stdout and f'checkout={repo}' in r.stdout)
    os.makedirs(os.path.join(lock_home, 'MASTER.lock.d'))
    check('list: legacy line, dir untouched', 'LEGACY ' in run('list').stdout and os.path.isdir(os.path.join(lock_home, 'MASTER.lock.d')))
    r = run('release', '--dir', repo, '--session', 'B')
    check('release: owner -> RELEASED, file gone', r.returncode == 0 and r.stdout.startswith('RELEASED ') and not os.path.exists(lock_file))
    r = run('release', '--dir', repo, '--session', 'B')
    check('release: free -> ALREADY FREE, exit 0', r.returncode == 0 and r.stdout.startswith('ALREADY FREE '))
    r = run('reclaim', '--dir', repo, '--session', 'D', '--from', 'X')
    check('reclaim: free lock behaves like acquire', r.returncode == 0 and load()['session_id'] == 'D' and 'reclaimed_from' not in load())
    r = run('release', '--dir', repo, '--session', 'D')
    procs = [subprocess.Popen([sys.executable, runtime.ENTRY, 'acquire', '--dir', repo, '--session', f'S{i}'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for i in range(12)]
    codes = sorted(pr.wait() for pr in procs)
    for pr in procs:
        pr.stdout.close()
        pr.stderr.close()
    check('concurrency: 12 acquires -> one exit 0, eleven exit 3', codes == [0] + [3] * 11)
    locks = glob.glob(os.path.join(lock_home, 'locks', '*'))
    check('concurrency: one lock file, valid json', len(locks) == 1 and load()['session_id'].startswith('S'))

    # 3. sessions
    dead = subprocess.Popen([sys.executable, '-c', 'pass'])
    dead.wait()

    def put(directory, name, data):
        with open(os.path.join(directory, name), 'w') as fh:
            json.dump(data, fh)

    now_ms = int(time.time() * 1000)
    put(sessions_dir, '1.json', {'pid': os.getpid(), 'cwd': wt, 'hostSessionId': 'local_live', 'name': 'live cli', 'status': 'busy',
                                 'updatedAt': now_ms - 120000, 'statusUpdatedAt': now_ms - 90000})
    put(sessions_dir, '2.json', {'pid': dead.pid, 'cwd': repo, 'hostSessionId': 'local_dead', 'name': 'dead cli', 'status': 'idle'})
    put(sessions_dir, '5.json', {'pid': dead.pid, 'cwd': repo, 'hostSessionId': 'local_ghost', 'name': 'ghost', 'status': 'idle'})
    # two pid files for one id: the live one must win whatever the glob order
    put(sessions_dir, '6-live.json', {'pid': os.getpid(), 'cwd': wt, 'hostSessionId': 'local_dup', 'name': 'new proc', 'status': 'busy'})
    put(sessions_dir, '7-dead.json', {'pid': dead.pid, 'cwd': repo, 'hostSessionId': 'local_dup', 'name': 'old proc', 'status': 'idle'})
    put(sessions_dir, '8-dead.json', {'pid': dead.pid, 'cwd': repo, 'hostSessionId': 'local_dup2', 'name': 'old proc 2', 'status': 'idle'})
    put(sessions_dir, '9-live.json', {'pid': os.getpid(), 'cwd': wt, 'hostSessionId': 'local_dup2', 'name': 'new proc 2', 'status': 'busy'})
    put(sessions_dir, '3.json', {'pid': os.getpid(), 'cwd': other, 'hostSessionId': 'local_other_cli', 'name': 'elsewhere'})
    with open(os.path.join(sessions_dir, '4.json'), 'w') as fh:
        fh.write('{not json')
    put(app_dir, 'local_live.json', {'sessionId': 'local_live', 'cwd': wt, 'title': 'live app title', 'model': 'claude-sonnet-5-5', 'effort': 'low', 'isArchived': False,
                                     'permissionMode': 'auto'})
    put(app_dir, 'local_dead.json', {'sessionId': 'local_dead', 'cwd': repo, 'title': 'dead app title', 'model': 'm', 'effort': 'high',
                                     'interruptedAwaitingPerson': True, 'queryCrashes': [1, 2], 'completedTurns': 7, 'lastActivityAt': now_ms - 300000})
    put(app_dir, 'local_arch.json', {'sessionId': 'local_arch', 'cwd': repo, 'title': 'archived', 'isArchived': True})
    put(app_dir, 'local_foreign.json', {'sessionId': 'local_foreign', 'cwd': other, 'title': 'foreign'})
    put(app_dir, 'local_gone.json', {'sessionId': 'local_gone', 'cwd': os.path.join(tmp, 'missing'), 'title': 'gone'})
    put(app_dir, 'local_plain.json', {'sessionId': 'local_plain', 'cwd': notrepo, 'title': 'plain'})
    put(app_dir, 'local_apponly.json', {'sessionId': 'local_apponly', 'cwd': repo, 'title': 'app only'})
    r = run('sessions', '--dir', repo, '--json')
    rows = json.loads(r.stdout or '[]')
    by_id = {x['id']: x for x in rows}
    check('sessions: only the project\'s non-archived ones, dead CLI-only hidden',
          set(by_id) == {'local_live', 'local_dead', 'local_apponly', 'local_dup', 'local_dup2'})
    all_ids = {x['id'] for x in json.loads(run('sessions', '--dir', repo, '--json', '--all').stdout or '[]')}
    check('sessions: --all shows the dead CLI-only record', all_ids == set(by_id) | {'local_ghost'})
    check('sessions: live flag follows /proc', by_id.get('local_live', {}).get('live') is True and by_id.get('local_dead', {}).get('live') is False and by_id.get('local_apponly', {}).get('live') is False)
    check('sessions: duplicate ids merge, live pid file wins (dead sorts after)',
          by_id.get('local_dup', {}).get('live') is True and by_id['local_dup']['status'] == 'busy'
          and by_id['local_dup']['title'] == 'new proc' and by_id['local_dup']['cwd'] == wt)
    check('sessions: duplicate ids merge, live pid file wins (dead sorts before)',
          by_id.get('local_dup2', {}).get('live') is True and by_id['local_dup2']['status'] == 'busy'
          and by_id['local_dup2']['title'] == 'new proc 2')
    live_row, dead_row, app_row = by_id.get('local_live', {}), by_id.get('local_dead', {}), by_id.get('local_apponly', {})
    check('sessions: idle_s = newest of updatedAt/statusUpdatedAt/lastActivityAt', isinstance(live_row.get('idle_s'), int) and 89 <= live_row['idle_s'] <= 100)
    check('sessions: idle_s from app lastActivityAt alone', isinstance(dead_row.get('idle_s'), int) and 299 <= dead_row['idle_s'] <= 310)
    check('sessions: idle_s null without timestamps', app_row.get('idle_s') is None and app_row.get('turns') is None)
    check('sessions: awaiting / crashes / turns', dead_row.get('awaiting') is True and dead_row.get('crashes') == 2 and dead_row.get('turns') == 7
          and live_row.get('awaiting') is False and live_row.get('crashes') == 0)
    check('sessions: cli and app records merged by id', by_id.get('local_live', {}).get('model') == 'claude-sonnet-5-5' and by_id['local_live']['status'] == 'busy' and by_id['local_live']['title'] == 'live app title')
    check('sessions: worktree cwd counts', by_id.get('local_live', {}).get('cwd') == wt)
    check('sessions: live sorted first', [x['live'] for x in rows] == [True, True, True, False, False])
    text = run('sessions', '--dir', wt).stdout.splitlines()
    check('sessions: text line format', len(text) == 5 and any(re.fullmatch(
        r'local_live \| live=yes \| status=busy \| model=claude-sonnet-5-5 \| effort=low \| mode=auto \| idle_s=\d+ \| awaiting=no \| crashes=0 \| turns=- \| '
        + re.escape(wt) + r' \| live app title', ln) for ln in text))
    check('sessions: text line with awaiting/crashes/turns', any(
        re.fullmatch(r'local_dead \| live=no \| status=idle \| model=m \| effort=high \| mode=- \| idle_s=\d+ \| awaiting=yes \| crashes=2 \| turns=7 \| .* \| dead app title', ln)
        for ln in text))
    check('sessions: text line idle_s dash', any('local_apponly | live=no | status=- | model=- | effort=- | mode=- | idle_s=- |' in ln for ln in text))
    check('sessions: mode from the app record, null without one', live_row.get('mode') == 'auto' and app_row.get('mode') is None)

    # 3b. transcripts feed idle_s
    def iso(ago=0):
        return datetime.fromtimestamp(time.time() - ago, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    def text_rec(ago, kind='assistant'):
        return {'type': kind, 'timestamp': iso(ago), 'message': {'role': kind, 'content': [{'type': 'text', 'text': 'x'}]}}

    def tool_rec(ago, name, tid):
        return {'type': 'assistant', 'timestamp': iso(ago), 'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'name': name, 'id': tid}]}}

    def result_rec(ago, tid):
        return {'type': 'user', 'timestamp': iso(ago), 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tid}]}}

    def write_jsonl(path, records, age=0):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as fh:
            for rec in records:
                fh.write(json.dumps(rec) + '\n')
        os.utime(path, (time.time() - age, time.time() - age))

    def tpath(cli_id, cwd=repo):
        return os.path.join(projects_t, transcripts.slug_of(cwd), cli_id + '.jsonl')

    def spath(cli_id, name, cwd=repo):
        return os.path.join(projects_t, transcripts.slug_of(cwd), cli_id, 'subagents', name)

    old_ms = int(time.time() * 1000) - 3600000
    for n in (1, 2, 3, 4):
        put(sessions_dir, f't{n}.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': f'cli-t{n}', 'hostSessionId': f'local_t{n}',
                                         'name': f't{n}', 'status': 'idle', 'updatedAt': old_ms})
    write_jsonl(tpath('cli-t1'), [text_rec(3600)])
    write_jsonl(tpath('cli-t2'), [text_rec(3600)], age=7200)
    write_jsonl(spath('cli-t2', 'agent-x.jsonl'), [text_rec(3600)])
    write_jsonl(os.path.join(projects_t, 'some-other-slug', 'cli-t3.jsonl'), [text_rec(3600)], age=2000)
    trows = {x['id']: x for x in json.loads(run('sessions', '--dir', repo, '--json').stdout or '[]')}
    check('transcript: touched now -> idle_s ~0 although the records and updatedAt are old',
          trows.get('local_t1', {}).get('idle_s') is not None and trows['local_t1']['idle_s'] <= 3)
    check('transcript: a fresh subagent file counts too', trows.get('local_t2', {}).get('idle_s') is not None and trows['local_t2']['idle_s'] <= 3)
    check('transcript: found by glob in another slug dir, idle from its mtime',
          1995 <= (trows.get('local_t3', {}).get('idle_s') or 0) <= 2010 and trows['local_t3']['transcript'].endswith('some-other-slug/cli-t3.jsonl'))
    check('transcript: none -> idle from the record stamps, transcript null',
          trows.get('local_t4', {}).get('transcript') is None and 3590 <= (trows['local_t4']['idle_s'] or 0) <= 3610)
    check('transcript: --json carries path and cli id', trows.get('local_t1', {}).get('transcript') == tpath('cli-t1') and trows['local_t1']['cli'] == 'cli-t1')
    check('slug: every char outside [A-Za-z0-9-] becomes -',
          transcripts.slug_of('/home/user/projects/htdocs/some-app') == '-home-user-projects-htdocs-some-app'
          and transcripts.slug_of('/x/.claude/worktrees/w') == '-x--claude-worktrees-w')
    unit_n = [0]

    def unit(records, age=0):
        unit_n[0] += 1
        path = os.path.join(tmp, f'unit{unit_n[0]}.jsonl')
        write_jsonl(path, records, age)
        return path

    now_t = time.time()
    check('waiting: AskUserQuestion / browser / chrome tools without result',
          all((transcripts.waiting_on_human(transcripts.conv_records(unit([text_rec(50), tool_rec(50, name, 'u')])), now_t) or ('', 0))[0] == name
              for name in ('AskUserQuestion', 'mcp__Claude_Browser__computer', 'mcp__claude-in-chrome__navigate')))
    check('waiting: an answered call, an ordinary tool or a later assistant text do not count',
          transcripts.waiting_on_human(transcripts.conv_records(unit([tool_rec(50, 'AskUserQuestion', 'a'), result_rec(40, 'a')])), now_t) is None
          and transcripts.waiting_on_human(transcripts.conv_records(unit([tool_rec(50, 'Bash', 'b')])), now_t) is None
          and transcripts.waiting_on_human(transcripts.conv_records(unit([tool_rec(50, 'AskUserQuestion', 'c'), text_rec(40)])), now_t) is None)
    check('modelstall: only a trailing tool_result user record',
          transcripts.model_stall_age(transcripts.conv_records(unit([tool_rec(900, 'Bash', 'd'), result_rec(800, 'd')])), now_t) in range(799, 804)
          and transcripts.model_stall_age(transcripts.conv_records(unit([tool_rec(900, 'Bash', 'e')])), now_t) is None
          and transcripts.model_stall_age(transcripts.conv_records(unit([result_rec(900, 'f'), text_rec(10, 'user')])), now_t) is None)
    check('tail: a record bigger than the window still parses, partial first line skipped',
          len(transcripts.conv_records(unit([dict(text_rec(5), pad='y' * 300000), text_rec(1)]))) >= 1)

    # 4. wait: fresh fixtures, then mutate them while `wait` runs in the background
    for directory in (sessions_dir, app_dir):
        for name in os.listdir(directory):
            os.remove(os.path.join(directory, name))
    me = os.getpid()

    def fixture(sid, cwd=repo, **app):
        put(app_dir, sid + '.json', dict({'sessionId': sid, 'cwd': cwd, 'title': sid, 'completedTurns': 1}, **app))

    def cli(sid, **extra):
        put(sessions_dir, sid + '.json', dict({'pid': me, 'cwd': repo, 'hostSessionId': sid, 'name': sid, 'status': 'idle'}, **extra))

    def waiting(*extra, timeout='6', settle=True, hold=False):
        """`hold=True`: the watcher takes its first snapshot and then polls nothing until `release(pr)`, so that a
        test that makes several changes gets all of them in one poll however slow the machine is."""
        ready = os.path.join(tmp, f'ready-{time.monotonic_ns()}')
        wait_env = dict(env, SUPERVISOR_WAIT_READY=ready)
        if hold:
            wait_env['SUPERVISOR_WAIT_HOLD'] = ready + '.hold'
            open(ready + '.hold', 'w').close()
        pr = subprocess.Popen([sys.executable, runtime.ENTRY, 'wait', '--dir', repo, '--interval', '0.2', '--timeout', timeout, *extra],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=wait_env)
        pr.hold_file = ready + '.hold' if hold else None
        limit = time.monotonic() + 20
        while settle and not os.path.exists(ready) and pr.poll() is None and time.monotonic() < limit:
            time.sleep(0.02)  # a change made before its first snapshot would be part of the baseline
        return pr

    def release(pr):
        os.remove(pr.hold_file)

    def finish(pr):
        out, err = pr.communicate(timeout=20)
        return pr.returncode, out.splitlines()

    for sid in ('local_gone', 'local_vanish', 'local_status', 'local_turn', 'local_await', 'local_crash', 'local_steady'):
        fixture(sid)
    cli('local_gone')
    cli('local_status')
    pr = waiting('--exclude', 'local_excl', timeout='20', hold=True)
    cli('local_gone', pid=dead.pid)
    os.remove(os.path.join(app_dir, 'local_vanish.json'))
    cli('local_status', status='busy')
    fixture('local_turn', completedTurns=2)
    fixture('local_await', interruptedAwaitingPerson=True, completedTurns=1)
    fixture('local_crash', queryCrashes=[{'at': 1}])
    fixture('local_new')
    fixture('local_excl')
    release(pr)
    code, lines = finish(pr)
    check('wait: exit 0 on events', code == 0)
    check('wait: NEW', 'NEW local_new' in lines)
    check('wait: GONE when a live session dies', 'GONE local_gone' in lines)
    check('wait: GONE when a session disappears', 'GONE local_vanish' in lines)
    check('wait: STATUS', 'STATUS local_status idle->busy' in lines)
    check('wait: TURN', 'TURN local_turn 1->2' in lines)
    check('wait: AWAITING', 'AWAITING local_await' in lines)
    check('wait: CRASH', 'CRASH local_crash 0->1' in lines)
    check('wait: --exclude hides a session', not any('local_excl' in ln for ln in lines) and 'local_steady' not in ' '.join(lines))

    for directory in (sessions_dir, app_dir):
        for name in os.listdir(directory):
            os.remove(os.path.join(directory, name))
    fixture('local_hung')
    cli('local_hung', status='busy', updatedAt=int(time.time() * 1000))
    pr = waiting('--hung-after', '1', timeout='5')
    code, lines = finish(pr)
    check('wait: HUNG when a busy session crosses the threshold during the wait', code == 0 and len(lines) == 1 and re.fullmatch(r'HUNG local_hung idle_s=\d+', lines[0]) is not None)

    cli('local_hung', status='busy', updatedAt=int(time.time() * 1000) - 3600000)
    started = time.time()
    pr = waiting('--hung-after', '1', timeout='2', settle=0)
    code, lines = finish(pr)
    check('wait: already hung at start is not reported, TIMEOUT', code == 0 and lines == ['TIMEOUT 2s'] and time.time() - started >= 1.9)
    r = run('wait', '--dir', notrepo, '--timeout', '1')
    check('wait: not a git repo -> exit 2', r.returncode == 2 and 'NOT A GIT REPOSITORY' in r.stderr)

    # 4b. wait: transcript-driven events, heavy-job aware ALLIDLE, refs, owner heartbeat
    def reset():
        for directory in (sessions_dir, app_dir):
            for name in os.listdir(directory):
                os.remove(os.path.join(directory, name))
        shutil.rmtree(projects_t)
        os.makedirs(projects_t)
        if os.path.exists(lock_file):
            os.remove(lock_file)

    def timed(*extra, timeout='8', settle=True, mutate=None):
        held = bool(mutate) and bool(settle)
        pr = waiting(*extra, timeout=timeout, settle=settle, hold=held)
        if mutate:
            mutate()
        if held:
            release(pr)
        return finish(pr)

    reset()
    cli('local_w1', sessionId='cli-w1')
    write_jsonl(tpath('cli-w1'), [tool_rec(100, 'AskUserQuestion', 'q1')])  # already blocked: true at start
    cli('local_w2', sessionId='cli-w2')
    write_jsonl(tpath('cli-w2'), [text_rec(100)])
    cli('local_w3', sessionId='cli-w3')
    write_jsonl(tpath('cli-w3'), [tool_rec(100, 'AskUserQuestion', 'q3'), result_rec(90, 'q3')])
    code, lines = timed('--waiting-after', '5', mutate=lambda: write_jsonl(tpath('cli-w2'), [text_rec(100), tool_rec(100, 'AskUserQuestion', 'q2')]))
    check('wait: WAITING when a session newly blocks on a human; already blocked at start and answered ones are not reported',
          code == 0 and len(lines) == 1 and re.fullmatch(r'WAITING local_w2 AskUserQuestion \d+s', lines[0]) is not None)

    reset()
    cli('local_m1', sessionId='cli-m1', status='busy')
    write_jsonl(tpath('cli-m1'), [tool_rec(900, 'Bash', 'a'), result_rec(800, 'a')])  # stalled already at start
    cli('local_m2', sessionId='cli-m2', status='busy')
    write_jsonl(tpath('cli-m2'), [text_rec(900)])
    cli('local_m3', sessionId='cli-m3', status='busy')
    write_jsonl(tpath('cli-m3'), [text_rec(900)])
    write_jsonl(spath('cli-m3', 'agent-1.jsonl'), [text_rec(0)])  # its subagent is alive
    cli('local_m4', sessionId='cli-m4', status='idle')
    write_jsonl(tpath('cli-m4'), [text_rec(900)])

    def stall():
        for n in (2, 3, 4):
            write_jsonl(tpath(f'cli-m{n}'), [tool_rec(900, 'Bash', 'b'), result_rec(800, 'b')])

    code, lines = timed('--model-stall-after', '5', mutate=stall)
    check('wait: MODELSTALL for a busy session that newly stalls (not at start, not idle, not with a live subagent)',
          code == 0 and len(lines) == 1 and re.fullmatch(r'MODELSTALL local_m2 \d+s', lines[0]) is not None)

    reset()
    fixture('local_p1', permissionMode='auto')  # already out of bypass at start: the census shows it, wait stays quiet
    cli('local_p1')
    fixture('local_p2', permissionMode='bypassPermissions')
    cli('local_p2')
    fixture('local_p3', permissionMode='bypassPermissions')  # not live: nothing to raise
    fixture('local_p4', permissionMode='bypassPermissions')  # goes to plan on purpose: left alone
    cli('local_p4')

    def drop_modes():
        fixture('local_p2', permissionMode='acceptEdits')
        fixture('local_p3', permissionMode='auto')
        fixture('local_p4', permissionMode='plan')

    code, lines = timed(mutate=drop_modes)
    check('wait: MODE for a live session that leaves bypass (not at start, not a dead one, not plan)',
          code == 0 and lines == ['MODE local_p2 acceptEdits'])

    reset()
    fixture('local_q1', permissionMode='bypassPermissions')
    cli('local_q1')

    def open_by_hand():  # the developer opens a session: its app record is born in the developer's default mode
        fixture('local_q2', permissionMode='auto')
        cli('local_q2')

    code, lines = timed(mutate=open_by_hand)
    check('wait: a session opened by hand in auto -> NEW and MODE in the same wake-up',
          code == 0 and 'MODE local_q2 auto' in lines and any(ln.startswith('NEW local_q2') for ln in lines))

    # HANDOFF: an idle session whose closing prose hands work back, once the developer has not written there for a while
    def said(ago, text):
        return {'type': 'assistant', 'timestamp': iso(ago), 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}

    def typed(ago, text='sigue'):
        return {'type': 'user', 'timestamp': iso(ago), 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': text}}

    reset()
    for n in (1, 2, 3, 4):
        cli(f'local_h{n}', sessionId=f'cli-h{n}', status='busy' if n == 3 else 'idle')
        write_jsonl(tpath(f'cli-h{n}'), [typed(900), said(800, 'Trabajando.')])

    def hand_back():
        handing = 'Ya he rellenado la ficha.\n\nCuando me confirmes sigo con el resto.'
        write_jsonl(tpath('cli-h1'), [typed(900), said(5, handing)])               # the developer left 15 min ago -> HANDOFF
        write_jsonl(tpath('cli-h2'), [typed(30), said(5, handing)])                # the developer wrote 30 s ago: the developer is driving it
        write_jsonl(tpath('cli-h3'), [typed(900), said(5, handing)])               # busy: still working
        write_jsonl(tpath('cli-h4'), [typed(900), said(5, 'Todo desplegado y verificado.')])  # no hand-back

    code, lines = timed('--handoff-after', '600', mutate=hand_back)
    check('wait: HANDOFF for an idle session whose closing prose hands work back and where the developer has not written for '
          '--handoff-after s (not while the developer drives it, not busy, not for a plain report)',
          code == 0 and lines == ['HANDOFF local_h1 «Cuando me confirmes»'])
    check('closing_text: trailing assistant text only; a tool call or a user record last -> None',
          transcripts.closing_text([typed(9), said(5, 'a'), said(4, 'b')]) == 'a\nb' and transcripts.closing_text([said(5, 'a'), typed(4)]) is None
          and transcripts.closing_text([{'type': 'assistant', 'timestamp': iso(1), 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'id': 't'}]}}]) is None)

    # --guard: after the final batch only what needs the supervisor wakes it
    reset()
    fixture('local_g1', permissionMode='bypassPermissions')
    cli('local_g1')

    def turn_only():
        fixture('local_g1', permissionMode='bypassPermissions', completedTurns=5)
        cli('local_g1', status='busy')

    code, lines = timed('--guard', '--all-idle-after', '1', timeout='3', mutate=turn_only)
    check('wait --guard: a turn, a status flip and a quiet project wake nobody (TIMEOUT)', code == 0 and lines == ['TIMEOUT 3s'])

    def opened():
        fixture('local_g2', permissionMode='bypassPermissions')
        cli('local_g2')

    code, lines = timed('--guard', mutate=opened)
    check('wait --guard: a new session still wakes the supervisor', code == 0 and lines == ['NEW local_g2'])

    # a dialog in a session the developer is driving is the developer's; it becomes WAITING once the developer left
    reset()
    for n in (1, 2):
        cli(f'local_wd{n}', sessionId=f'cli-wd{n}')
        write_jsonl(tpath(f'cli-wd{n}'), [typed(900), said(800, 'Trabajando.')])

    def ask_developer():
        write_jsonl(tpath('cli-wd1'), [typed(30), tool_rec(20, 'AskUserQuestion', 'd1')])   # the developer wrote 30 s ago
        write_jsonl(tpath('cli-wd2'), [typed(900), tool_rec(20, 'AskUserQuestion', 'd2')])  # the developer left 15 min ago

    code, lines = timed('--waiting-after', '5', '--away-after', '600', mutate=ask_developer)
    check('wait: WAITING only for the dialog of a session the developer left (--away-after), not for one the developer is driving',
          code == 0 and len(lines) == 1 and re.fullmatch(r'WAITING local_wd2 AskUserQuestion \d+s', lines[0]) is not None)

    # IDLE: on guard, a session that stops with prose no pattern knows is still seen once the developer has not written for a while
    reset()
    cli('local_i1', sessionId='cli-i1')
    write_jsonl(tpath('cli-i1'), [typed(5), said(1, 'Me quedo aquí hasta que vuelvas a mirarlo tú.')])
    code, lines = timed('--guard', '--away-after', '2', timeout='8')
    check('wait --guard: IDLE once a stopped session (closing prose no pattern matches) has had no input for '
          '--away-after s', code == 0 and len(lines) == 1 and re.fullmatch(r'IDLE local_i1 \d+s', lines[0]) is not None)
    write_jsonl(tpath('cli-i1'), [typed(5), said(1, 'Me quedo aquí hasta que vuelvas a mirarlo tú.')])
    code, lines = timed('--away-after', '2', timeout='4')
    check('wait without --guard: no IDLE (TURN and ALLIDLE cover it there)', code == 0 and lines == ['TIMEOUT 4s'])
    code, lines = timed('--guard', '--away-after', '2', timeout='3', settle=True)
    check('wait --guard: an IDLE already true at start is not reported again', code == 0 and lines == ['TIMEOUT 3s'])

    # CLOSABLE: on guard, a session that becomes due for F4b wakes the owner (nothing else would for 6 h)
    reset()
    run('acquire', '--dir', repo, '--session', 'local_own', '--title', 'own')
    run('beat', '--dir', repo, '--session', 'local_own', '--skill-seen')
    cli('local_own', sessionId='cli-own')
    old_ms = int(time.time() * 1000) - 3 * 3600 * 1000
    fixture('local_c1', permissionMode='bypassPermissions', updatedAt=old_ms)
    cli('local_c1', sessionId='cli-c1', status='busy', updatedAt=old_ms)
    code, lines = timed('--owner', 'local_own', '--guard',
                        mutate=lambda: cli('local_c1', sessionId='cli-c1', status='idle', updatedAt=old_ms))
    check('wait --owner --guard: CLOSABLE when a session becomes due for F4b during the guard',
          code == 0 and lines == ['CLOSABLE local_c1 3.0 h'])
    code, lines = timed('--owner', 'local_own', timeout='2', settle=0)
    check('wait --owner without --guard: no CLOSABLE (the Stop hook pushes it there)', lines == ['TIMEOUT 2s'])

    reset()
    cli('local_o', sessionId='cli-o')
    write_jsonl(tpath('cli-o'), [text_rec(10)])
    write_jsonl(spath('cli-o', 'agent-s1.jsonl'), [tool_rec(2000, 'Bash', 'z')], age=2000)  # silent already at start
    write_jsonl(spath('cli-o', 'agent-s2.jsonl'), [text_rec(2000)], age=2000)  # finished
    write_jsonl(spath('cli-o', 'agent-s3.jsonl'), [tool_rec(9000, 'Bash', 'z')], age=4 * 3600)  # older than 3 h
    write_jsonl(spath('cli-o', 'agent-s4.jsonl'), [tool_rec(100, 'Bash', 'z')], age=100)  # not silent long enough
    code, lines = timed('--owner', 'local_o', '--subagent-silent-after', '1200',
                        mutate=lambda: write_jsonl(spath('cli-o', 'agent-s2.jsonl'), [tool_rec(2000, 'Bash', 'y')], age=2000))
    check('wait: SUBAGENT_SILENT for the owner\'s subagent that goes mid-work and quiet (not at start, not old, not recent)',
          code == 0 and len(lines) == 1 and re.fullmatch(r'SUBAGENT_SILENT agent-s2\.jsonl \d+s', lines[0]) is not None)
    check('subagent: a user tool_result is mid-work, text is not',
          transcripts.subagent_silent_age(unit([result_rec(10, 'k')], age=2000), time.time()) in range(1999, 2004)
          and transcripts.subagent_silent_age(unit([text_rec(10)], age=2000), time.time()) is None)

    def forget_allidle():
        for name in glob.glob(os.path.join(lock_home, 'announced', '*.allidle.json')):
            os.remove(name)

    reset()
    forget_allidle()
    cli('local_i1', sessionId='cli-i1', updatedAt=int(time.time() * 1000) - 1000)
    started = time.time()
    code, lines = timed('--all-idle-after', '2', timeout='8', settle=0)
    check('wait: the first ALLIDLE comes the threshold after the watcher first saw the project quiet', code == 0
          and len(lines) == 1 and re.fullmatch(r'ALLIDLE [23]s', lines[0]) is not None and 1.8 <= time.time() - started <= 5)
    started = time.time()
    code, lines = timed('--all-idle-after', '2', timeout='10', settle=0)
    check('wait: re-arming does not restart the quiet clock, and the next ALLIDLE needs twice the quiet time',
          code == 0 and len(lines) == 1 and re.fullmatch(r'ALLIDLE [45]s', lines[0]) is not None
          and 1.5 <= time.time() - started <= 6)
    cli('local_i1', sessionId='cli-i1', updatedAt=int(time.time() * 1000) - 500)
    code, lines = timed('--all-idle-after', '2', timeout='8', settle=0)
    check('wait: any activity resets the ALLIDLE back-off to the base threshold',
          code == 0 and len(lines) == 1 and re.fullmatch(r'ALLIDLE [23]s', lines[0]) is not None)
    forget_allidle()
    code, lines = timed('--all-idle-after', '0', timeout='3', settle=0)
    check('wait: --all-idle-after 0 disables ALLIDLE', lines == ['TIMEOUT 3s'])
    cli('local_i2', status='busy', updatedAt=int(time.time() * 1000) - 3600000)
    code, lines = timed('--all-idle-after', '2', timeout='3.5', settle=0)
    check('wait: no ALLIDLE while a live session is busy', lines == ['TIMEOUT 3.5s'])
    os.remove(os.path.join(sessions_dir, 'local_i2.json'))
    zeta = os.path.join(tmp, 'zeta-tree')
    sh('git', 'worktree', 'add', '-q', '-b', 'zeta', zeta, cwd=repo)
    for label, text in (('project name', '  hueco 0: OCUPADO por pid 1 [gate] "proj gate" proyecto x desde hace 1 min: make\n'),
                        ('worktree folder', '  hueco 0: OCUPADO por pid 1 [suite] "build" proyecto zeta-tree desde hace 1 min: make\n')):
        with open(heavy_txt, 'w') as fh:
            fh.write(text)
        code, lines = timed('--all-idle-after', '2', timeout='3.5', settle=0)
        check(f'wait: no ALLIDLE while a heavy-job slot mentions the {label}', lines == ['TIMEOUT 3.5s'])
    with open(heavy_txt, 'w') as fh:
        fh.write('  hueco 0: OCUPADO por pid 1 [gate] "elsewhere" proyecto other-thing desde hace 1 min: x\n  hueco 1: libre (proj antes)\n')
    code, lines = timed('--all-idle-after', '2', timeout='8', settle=0)
    check('wait: ALLIDLE ignores other projects\' slots and free lines', len(lines) == 1 and lines[0].startswith('ALLIDLE '))
    open(heavy_txt, 'w').close()
    forget_allidle()

    reset()
    sh('git', 'branch', 'refa', cwd=repo)
    old_sha = subprocess.run(['git', '-C', repo, 'rev-parse', 'refa'], capture_output=True, text=True, env=env).stdout.strip()

    def move_ref():
        sh('git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'c2', cwd=repo)
        sh('git', 'branch', '-f', 'refa', 'HEAD', cwd=repo)

    code, lines = timed('--refs', 'refa,refmissing', mutate=move_ref)
    new_sha = subprocess.run(['git', '-C', repo, 'rev-parse', 'refa'], capture_output=True, text=True, env=env).stdout.strip()
    check('wait: REF when a watched branch moves (missing branch ignored)', lines == [f'REF refa {old_sha[:8]}->{new_sha[:8]}'] and old_sha != new_sha)

    reset()
    run('acquire', '--dir', repo, '--session', 'local_own', '--title', 'own')
    run('beat', '--dir', repo, '--session', 'local_own', '--phase', 'P1', '--round', '4', '--skill-seen')
    shift_heartbeat(1000)
    cli('local_own', sessionId='cli-own')
    code, lines = timed('--owner', 'local_own', '--beat-every', '0.5', timeout='3',
                        mutate=lambda: cli('local_own', sessionId='cli-own', status='busy'))
    cur = load()
    check('wait --owner: owner excluded from the events', lines == ['TIMEOUT 3s'])
    check('wait --owner: heartbeat refreshed, state/phase/round untouched',
          util.age_seconds(cur['heartbeat']) <= 3 and cur['phase'] == 'P1' and cur['round'] == 4 and cur['state'] == 'running')
    shift_heartbeat(1000)
    code, lines = timed('--owner', 'local_zzz', '--beat-every', '0.5', timeout='2', settle=0)
    check('wait --owner: a lock held by someone else is not refreshed', util.age_seconds(load()['heartbeat']) >= 990)

    # 4c. wait --owner: advisory REGISTRY_BIG
    reg_dir = os.path.join(tmp, 'registries')
    os.makedirs(reg_dir)

    def reg_file(name, size, age=0):
        path = os.path.join(reg_dir, name)
        open(path, 'w').write('x' * size)
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    reset()
    big = reg_file('SUPERVISOR-2026-11-04.md', 50000, 10)
    run('acquire', '--dir', repo, '--session', 'local_rg', '--registry', big)
    run('beat', '--dir', repo, '--session', 'local_rg', '--skill-seen')  # acquire does not mark the skill as read
    code, lines = timed('--owner', 'local_rg', timeout='2', settle=0)
    check('wait --owner: a registry over the limit adds REGISTRY_BIG after TIMEOUT, exit 0',
          code == 0 and lines == ['TIMEOUT 2s', f'REGISTRY_BIG {big} 50000 (move closed history to HISTORIAL-2026-11-04.md next to it; '
                                                'keep only the state sections)'])
    code, lines = timed('--owner', 'local_rg', '--registry-max', '60000', timeout='2', settle=0)
    check('wait --owner: --registry-max raises the limit', lines == ['TIMEOUT 2s'])
    code, lines = timed('--owner', 'local_rg', '--registry-max', '100', timeout='2', settle=0)
    check('wait --owner: --registry-max lowers the limit', len(lines) == 2 and lines[1].startswith(f'REGISTRY_BIG {big} 50000 '))
    code, lines = timed('--owner', 'local_zz', timeout='2', settle=0)
    check('wait --owner: no REGISTRY_BIG when the lock belongs to someone else', lines == ['TIMEOUT 2s'])
    code, lines = timed('--owner', 'local_rg', mutate=lambda: fixture('local_rgnew'))
    check('wait --owner: REGISTRY_BIG also follows an event line, last',
          code == 0 and len(lines) == 2 and lines[0] == 'NEW local_rgnew' and lines[1].startswith('REGISTRY_BIG '))
    code, lines = timed(timeout='1', settle=0)
    check('wait without --owner: never REGISTRY_BIG', not any(x.startswith('REGISTRY_BIG') for x in lines))
    small = reg_file('SUPERVISOR-small.md', 1000, 10)
    run('beat', '--dir', repo, '--session', 'local_rg')
    data = load()
    data['registry'] = small
    save(data)
    code, lines = timed('--owner', 'local_rg', timeout='2', settle=0)
    check('wait --owner: a small registry adds nothing', lines == ['TIMEOUT 2s'])
    for name in os.listdir(reg_dir):
        os.remove(os.path.join(reg_dir, name))
    reg_file('SUPERVISOR-2026-11-01.md', 100, 500)
    reg_file('SUPERVISOR-2026-11-04.md', 50000, 100)
    reg_file('HISTORIAL-2026-11-05.md', 90000, 0)
    data['registry'] = reg_dir
    save(data)
    code, lines = timed('--owner', 'local_rg', timeout='2', settle=0)
    check('wait --owner: a directory registry -> newest SUPERVISOR-*.md; a newer HISTORIAL-*.md is ignored',
          lines == ['TIMEOUT 2s', f'REGISTRY_BIG {os.path.join(reg_dir, "SUPERVISOR-2026-11-04.md")} 50000 (move closed history to '
                                  'HISTORIAL-2026-11-04.md next to it; keep only the state sections)'])
    os.remove(os.path.join(reg_dir, 'SUPERVISOR-2026-11-04.md'))
    code, lines = timed('--owner', 'local_rg', timeout='2', settle=0)
    check('wait --owner: only a big HISTORIAL-*.md and a small registry -> nothing', lines == ['TIMEOUT 2s'])
    os.remove(os.path.join(reg_dir, 'SUPERVISOR-2026-11-01.md'))
    code, lines = timed('--owner', 'local_rg', timeout='2', settle=0)
    check('wait --owner: a registry dir with no registry file -> nothing, wait unaffected', code == 0 and lines == ['TIMEOUT 2s'])

    # 5. release guard
    reset()
    shutil.rmtree(os.path.join(lock_home, 'closed'), ignore_errors=True)  # earlier sections released locks too
    closed_file = os.path.join(lock_home, 'closed', p1['key'] + '.json')
    run('acquire', '--dir', repo, '--session', 'local_sup', '--title', 'sup')
    cli('local_sup', status='busy')
    cli('local_bz', status='busy')
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'DONE')
    check('release: other live session busy -> exit 6 with OPEN WORK, lock kept, nothing recorded',
          r.returncode == 6 and 'OPEN WORK local_bz status=busy' in r.stdout and 'local_sup' not in r.stdout
          and os.path.exists(lock_file) and not os.path.exists(closed_file))
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'PARTIAL', '--force-close', 'dev ordered')
    hist = [json.loads(x) for x in open(closed_file).read().splitlines()] if os.path.exists(closed_file) else []
    check('release: --force-close frees the lock and records reason, verdict, session',
          r.returncode == 0 and r.stdout.startswith('RELEASED ') and not os.path.exists(lock_file) and len(hist) == 1
          and hist[0]['force_close'] == 'dev ordered' and hist[0]['verdict'] == 'PARTIAL' and hist[0]['session'] == 'local_sup'
          and hist[0]['open_work'] == ['local_bz'] and 'time' in hist[0])
    for sid in ('local_bz',):
        os.remove(os.path.join(sessions_dir, sid + '.json'))  # closed and archived: no longer in the census
    run('acquire', '--dir', repo, '--session', 'local_sup')
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'OK')
    hist = [json.loads(x) for x in open(closed_file).read().splitlines()]
    check('release: no other busy session and none open -> released, history appended (verdict, no force_close)',
          r.returncode == 0 and len(hist) == 2 and hist[1]['verdict'] == 'OK' and 'force_close' not in hist[1])
    run('acquire', '--dir', repo, '--session', 'local_sup')
    run('beat', '--dir', repo, '--session', 'local_sup', '--mailbox', 'local_qs')
    cli('local_qs', status='busy')
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'PREPROD DEPLOYED')
    hist = [json.loads(x) for x in open(closed_file).read().splitlines()]
    check('release: only the registered questions session is busy -> released (exit 0), closed entry records the mailbox',
          r.returncode == 0 and r.stdout.startswith('RELEASED ') and not os.path.exists(lock_file) and len(hist) == 3
          and hist[2]['verdict'] == 'PREPROD DEPLOYED' and hist[2].get('mailbox') == 'local_qs' and 'force_close' not in hist[2])
    run('acquire', '--dir', repo, '--session', 'local_sup')
    run('beat', '--dir', repo, '--session', 'local_sup', '--mailbox', 'local_qs')
    cli('local_bz', status='busy')
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'DONE')
    check('release: the questions session plus another busy session -> exit 6, OPEN WORK names the other one only, lock kept',
          r.returncode == 6 and 'OPEN WORK local_bz status=busy' in r.stdout and 'local_qs' not in r.stdout
          and os.path.exists(lock_file) and len(open(closed_file).read().splitlines()) == 3)
    for sid in ('local_bz', 'local_qs'):
        os.remove(os.path.join(sessions_dir, sid + '.json'))  # closed and archived: no longer in the census
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'OK')
    check('release: cleanup release after the open sessions are gone', r.returncode == 0 and not os.path.exists(lock_file))

    # 5b. release and `open`: every session of the project must be archived, whoever opened it
    all_exit = 'open: %d session(s) besides the supervisor and its questions session'
    for sid in ('local_sup', 'local_qs', 'local_nb'):
        fixture(sid)  # app records, not archived, no CLI process: the owner, its questions session and a stranger
    r = run('open', '--dir', repo)
    check('open: no lock -> nobody is excluded, exit 6 and the count line',
          r.returncode == 6 and r.stdout.splitlines()[-1] == all_exit % 3 and r.stdout.count('OPEN local_') == 3)
    run('acquire', '--dir', repo, '--session', 'local_sup', '--title', 'sup')
    run('beat', '--dir', repo, '--session', 'local_sup', '--mailbox', 'local_qs')
    hist_len = len(open(closed_file).read().splitlines())
    r = run('open', '--dir', repo)
    lines = r.stdout.splitlines()
    check('open: owner and questions session are not counted, exit 6, OPEN <session line> + count line',
          r.returncode == 6 and len(lines) == 2 and lines[0].startswith('OPEN local_nb | live=no | status=- | ') and lines[1] == all_exit % 1
          and 'local_sup' not in r.stdout and 'local_qs' not in r.stdout)
    oj = json.loads(run('open', '--dir', repo, '--json').stdout or '{}')
    check('open --json: count and the rows', oj.get('count') == 1 and [x['id'] for x in oj.get('open', [])] == ['local_nb'])
    same = [run('open', '--dir', repo, '--session', sid) for sid in ('local_sup', 'local_nb')]
    check('open --session (the owner or any other session): accepted, the same rows and exit code as without it',
          all(x.returncode == r.returncode and x.stdout == r.stdout for x in same))
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'DONE')
    check('release: a session nobody opened (not archived) is still open -> exit 6, OPEN line, explanation, lock kept, nothing recorded',
          r.returncode == 6 and r.stdout.startswith('OPEN local_nb | ') and 'local_qs' not in r.stdout and 'local_sup' not in r.stdout
          and '/cierra-sesion' in r.stderr and '--open-ok' in r.stderr and os.path.exists(lock_file)
          and len(open(closed_file).read().splitlines()) == hist_len)
    r = run('release', '--dir', repo, '--session', 'local_sup', '--open-ok', '  ')
    check('release: a blank --open-ok is a usage error (exit 2), lock kept', r.returncode == 2 and os.path.exists(lock_file))
    fixture('local_nb', isArchived=True)
    r = run('open', '--dir', repo)
    check('open: once archived -> exit 0 and `open: 0 session(s)...`', r.returncode == 0 and r.stdout == all_exit % 0 + '\n')
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'PREPROD DEPLOYED')
    hist = [json.loads(x) for x in open(closed_file).read().splitlines()]
    check('release: allowed once the stranger is archived (owner and questions session never count), no open_ok recorded',
          r.returncode == 0 and r.stdout.startswith('RELEASED ') and not os.path.exists(lock_file) and len(hist) == hist_len + 1
          and 'open_ok' not in hist[-1] and 'open_sessions' not in hist[-1] and hist[-1].get('mailbox') == 'local_qs')
    fixture('local_nb')
    run('acquire', '--dir', repo, '--session', 'local_sup')
    run('beat', '--dir', repo, '--session', 'local_sup', '--mailbox', 'local_qs')
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'PARTIAL', '--open-ok', 'ON HOLD: rule forbids archiving')
    hist = [json.loads(x) for x in open(closed_file).read().splitlines()]
    check('release: --open-ok REASON frees the lock and records the reason and the ids left open',
          r.returncode == 0 and r.stdout.startswith('RELEASED ') and 'open-ok: ON HOLD: rule forbids archiving' in r.stdout
          and 'local_nb' in r.stdout and not os.path.exists(lock_file) and len(hist) == hist_len + 2
          and hist[-1]['open_ok'] == 'ON HOLD: rule forbids archiving' and hist[-1]['open_sessions'] == ['local_nb']
          and hist[-1]['verdict'] == 'PARTIAL' and 'force_close' not in hist[-1])
    run('acquire', '--dir', repo, '--session', 'local_sup')
    r = run('release', '--dir', repo, '--session', 'local_sup', '--verdict', 'PARTIAL', '--force-close', 'dev ordered')
    hist = [json.loads(x) for x in open(closed_file).read().splitlines()]
    check('release: --force-close still frees the lock with an open session (as before) and does not claim open_ok',
          r.returncode == 0 and hist[-1]['force_close'] == 'dev ordered' and 'open_ok' not in hist[-1])
    r = run('release', '--dir', repo, '--session', 'local_sup')
    check('release: a lock that is already free is not checked (ALREADY FREE, exit 0)', r.returncode == 0 and r.stdout.startswith('ALREADY FREE '))
    for sid in ('local_sup', 'local_qs', 'local_nb'):
        os.remove(os.path.join(app_dir, sid + '.json'))

    # 6. watchdog
    reset()
    os.makedirs(os.path.join(lock_home, 'locks'), exist_ok=True)

    def hb_ago(seconds):
        return datetime.fromtimestamp(time.time() - seconds).astimezone().isoformat(timespec='seconds')

    def put_lock(key, session, ago, state='running'):
        put(os.path.join(lock_home, 'locks'), key + '.json', {'key': key, 'project': 'proj', 'session_id': session, 'title': 'T ' + key,
                                                               'state': state, 'phase': 'F1', 'round': 2, 'heartbeat': hb_ago(ago)})

    for sid in ('local_ws1', 'local_ws2', 'local_ws3', 'local_ws4'):
        cli(sid)
    put(sessions_dir, 'wd2.json', {'pid': dead.pid, 'cwd': repo, 'hostSessionId': 'local_wd2', 'status': 'idle'})
    put_lock('k-dead1', 'local_wd1', 3600)       # no process at all (past DEAD_ALERT_GRACE_S: the reviver had its turn)
    put_lock('k-dead2', 'local_wd2', 3600)       # pid file of a dead process
    put_lock('k-young', 'local_wd3', 100)        # no process but a recent heartbeat
    put_lock('k-stale1', 'local_ws1', 3000)      # alive, silent
    put_lock('k-pause1', 'local_ws2', 3000, 'paused')   # paused gets double time
    put_lock('k-pause2', 'local_ws3', 6000, 'paused')
    put_lock('k-fresh', 'local_ws4', 100)
    snapshot_locks = {n[:-5]: open(os.path.join(lock_home, 'locks', n)).read() for n in os.listdir(os.path.join(lock_home, 'locks'))}
    r = run('watchdog')
    got = sorted(ln.split()[0] + ' ' + ln.split()[1] for ln in r.stdout.splitlines())
    check('watchdog: DEAD / STALE reported, healthy locks silent, exit 0',
          r.returncode == 0 and got == ['DEAD k-dead1', 'DEAD k-dead2', 'STALE k-pause2', 'STALE k-stale1']
          and re.search(r'^DEAD k-dead1 T k-dead1 since \d{4}-\d\d-\d\dT', r.stdout, re.M) is not None)
    check('watchdog: without --notify nothing is notified or written',
          os.path.getsize(notify_log) == 0 and snapshot_locks == {n[:-5]: open(os.path.join(lock_home, 'locks', n)).read() for n in os.listdir(os.path.join(lock_home, 'locks'))})
    r = run('watchdog', '--notify')
    sent = open(notify_log).read().splitlines()
    dead_msg = [x for x in sent if 'no tiene proceso' in x]
    stale_msg = [x for x in sent if 'no da señales' in x]
    k1 = json.load(open(os.path.join(lock_home, 'locks', 'k-dead1.json')))
    hhmm = datetime.fromisoformat(k1['heartbeat']).strftime('%H:%M')
    check('watchdog --notify: one notification per incident with the Spanish text',
          r.returncode == 0 and len(sent) == 4 and len(dead_msg) == 2 and len(stale_msg) == 2
          and f'Supervisión parada: proj|La sesión «T k-dead1» no tiene proceso desde las {hhmm} y la tarea programada de reanimación no la ha podido despertar (¿está abierta la app?). Ábrela y escribe «reanuda».' in sent
          and all(x.startswith('Supervisión parada: proj|La sesión «T k-') and x.endswith('y no encuentro su transcripción. Ábrela: si está parada, escribe «reanuda».') for x in stale_msg))
    after_locks = {n[:-5]: json.load(open(os.path.join(lock_home, 'locks', n))) for n in os.listdir(os.path.join(lock_home, 'locks'))}
    stripped = {n: {k: v for k, v in d.items() if k not in ('alerted_at', 'alert_kind', 'alert_reason')} for n, d in after_locks.items()}
    check('watchdog --notify: alerted_at/alert_kind/alert_reason stored, nothing else changed, healthy locks untouched',
          after_locks['k-dead1']['alert_kind'] == 'DEAD' and after_locks['k-stale1']['alert_kind'] == 'STALE'
          and after_locks['k-stale1']['alert_reason'] == 'unknown' and 'alert_reason' not in after_locks['k-dead1']
          and 'alerted_at' not in after_locks['k-fresh'] and 'alerted_at' not in after_locks['k-young']
          and all(json.dumps(stripped[n], sort_keys=True) == json.dumps(json.loads(t), sort_keys=True) for n, t in snapshot_locks.items()))
    run('watchdog', '--notify')
    check('watchdog --notify: the same incident is not notified again', len(open(notify_log).read().splitlines()) == 4)
    d1 = after_locks['k-dead1']
    d1['alerted_at'] = hb_ago(11000)
    put(os.path.join(lock_home, 'locks'), 'k-dead1.json', d1)
    d2 = after_locks['k-dead2']
    d2['alert_kind'] = 'STALE'
    put(os.path.join(lock_home, 'locks'), 'k-dead2.json', d2)
    run('watchdog', '--notify')
    check('watchdog --notify: no reminder by default, and STALE -> DEAD is the same stop',
          len(open(notify_log).read().splitlines()) == 4)
    run('watchdog', '--notify', '--realert-after', '10800')
    sent = open(notify_log).read().splitlines()
    check('watchdog --notify --realert-after S: re-alerts once the last notice is older than S',
          len(sent) == 5 and 'k-dead1' in sent[-1]
          and util.age_seconds(json.load(open(os.path.join(lock_home, 'locks', 'k-dead1.json')))['alerted_at']) < 60)
    put_lock('k-stale1', 'local_ws1', 10)
    run('watchdog', '--notify')
    recovered = json.load(open(os.path.join(lock_home, 'locks', 'k-stale1.json')))
    check('watchdog --notify: a recovered lock loses its alert fields',
          'alert_kind' not in recovered and 'alert_reason' not in recovered and 'alerted_at' not in recovered
          and len(open(notify_log).read().splitlines()) == 5)
    put_lock('k-stale1', 'local_ws1', 3000)
    run('watchdog', '--notify')
    check('watchdog --notify: its next stop notifies again', len(open(notify_log).read().splitlines()) == 6)
    for name in os.listdir(os.path.join(lock_home, 'locks')):
        os.remove(os.path.join(lock_home, 'locks', name))

    # 6a-1. revive: the app task wakes a supervisor whose process died; the developer hears of it only after
    put_lock('k-rv', 'local_rv1', 1200)          # dead 20 min: the reviver's turn, no desktop alert yet
    put_lock('k-rvok', 'local_ws4', 1200)        # silent 20 min but alive: not the reviver's business
    before = len(open(notify_log).read().splitlines())
    r = run('watchdog', '--notify')
    check('revive: a supervisor dead for less than DEAD_ALERT_GRACE_S is not notified while the reviver has attempts',
          'DEAD k-rv ' in r.stdout and len(open(notify_log).read().splitlines()) == before)
    usage_env = dict(env, SUPERVISOR_USAGE='no')
    r = subprocess.run([sys.executable, runtime.ENTRY, 'revive'], capture_output=True, text=True, env=usage_env)
    check('revive: nobody is woken while the account is out of usage',
          r.returncode == 0 and r.stdout.startswith('HOLD ') and 'REVIVE' not in r.stdout
          and not os.path.exists(os.path.join(lock_home, 'revive.json')))
    yes_env = dict(env, SUPERVISOR_USAGE='yes')
    revive = lambda *a: subprocess.run([sys.executable, runtime.ENTRY, 'revive', *a], capture_output=True, text=True, env=yes_env)
    r = revive('--json')
    plan = json.loads(r.stdout)
    targets = [t['session_id'] for t in plan['targets']]
    msg = plan['targets'][0]['message'] if plan['targets'] else ''
    check('revive --plan: the dead owner is named once, with the marker, the census and the watcher in its text',
          r.returncode == 0 and targets == ['local_rv1'] and msg.startswith('[reanimar supervisora] ')
          and 'censo' in msg and 'supervisor-lock wait' in msg and 'get_usage' in msg
          and plan['targets'][0]['attempt'] == 1)
    r = revive()
    check('revive --plan: within REVIVE_RETRY_S the same death waits', 'WAIT local_rv1 k-rv' in r.stdout and 'REVIVE' not in r.stdout)
    r = revive('--sent', 'local_rv1', '--delivery', 'delivered')
    state = json.load(open(os.path.join(lock_home, 'revive.json')))
    check('revive --sent: the delivery is recorded', r.returncode == 0 and state['k-rv']['delivery'] == 'delivered')
    state['k-rv']['planned_at'] -= 3600
    put(lock_home, 'revive.json', state)
    r = revive()
    check('revive --plan: after REVIVE_RETRY_S it tries again', 'REVIVE local_rv1 k-rv' in r.stdout and 'attempt=2/3' in r.stdout)
    state = json.load(open(os.path.join(lock_home, 'revive.json')))
    state['k-rv'].update(attempts=3, planned_at=time.time() - 3600)
    put(lock_home, 'revive.json', state)
    r = revive()
    check('revive --plan: after 3 attempts it gives up', 'GIVEUP local_rv1 k-rv' in r.stdout and 'REVIVE' not in r.stdout)
    r = run('watchdog', '--notify')
    sent = open(notify_log).read().splitlines()
    check('revive: once the reviver gave up, the watchdog tells the developer',
          len(sent) == before + 1 and 'T k-rv' in sent[-1] and 'tarea programada de reanimación' in sent[-1])
    put_lock('k-rv', 'local_rv1', 1500)          # a new death (another heartbeat): a new incident
    r = revive()
    check('revive --plan: a new death starts again at attempt 1', 'REVIVE local_rv1 k-rv' in r.stdout and 'attempt=1/3' in r.stdout)
    os.remove(os.path.join(lock_home, 'locks', 'k-rv.json'))
    r = revive()
    check('revive --plan: a lock no longer dead leaves the state', 'NONE' in r.stdout
          and 'k-rv' not in json.load(open(os.path.join(lock_home, 'revive.json'))))
    for name in os.listdir(os.path.join(lock_home, 'locks')):
        os.remove(os.path.join(lock_home, 'locks', name))

    # 6a-2. a running supervision without a questions session
    open(notify_log, 'w').close()
    nm_key = projects.resolve(repo)['key']
    cli('local_nm1')

    def nm_lock(**extra):
        base = {'key': nm_key, 'project': 'proj', 'session_id': 'local_nm1', 'title': 'T nm', 'state': 'running', 'phase': 'F1',
                'round': 1, 'heartbeat': hb_ago(10), 'started': hb_ago(2000)}
        put(os.path.join(lock_home, 'locks'), nm_key + '.json', dict(base, **extra))

    def nm_stored():
        return json.load(open(os.path.join(lock_home, 'locks', nm_key + '.json')))

    nm_lock()
    r = run('status', '--dir', repo)
    check('status: a running lock without mailbox is flagged SIN SESIÓN DE PREGUNTAS',
          r.returncode == 0 and r.stdout.startswith('HELD ') and 'SIN SESIÓN DE PREGUNTAS' in r.stdout)
    check('list: the same flag shows in `list`', 'SIN SESIÓN DE PREGUNTAS' in run('list').stdout)
    nm_lock(mailbox='local_qs')
    check('status: with a mailbox, or paused, there is no flag',
          'SIN SESIÓN' not in run('status', '--dir', repo).stdout and 'mailbox=local_qs' in run('status', '--dir', repo).stdout
          and (nm_lock(state='paused') or 'SIN SESIÓN' not in run('status', '--dir', repo).stdout))
    nm_lock()
    r = run('watchdog')
    check('watchdog: a healthy running lock without mailbox is a NOMAILBOX warning line (exit 0, nothing written)',
          r.returncode == 0 and re.search(rf'^NOMAILBOX {re.escape(nm_key)} T nm since ', r.stdout, re.M) is not None
          and 'nomailbox_alerted_at' not in nm_stored() and open(notify_log).read() == '')
    r = run('watchdog', '--notify')
    sent = open(notify_log).read().splitlines()
    check('watchdog --notify: one desktop alert in Spanish, the mark is stored in the lock',
          len(sent) == 1 and sent[0].startswith('Supervisión sin sesión de preguntas: proj|La supervisión «T nm» lleva en marcha sin sesión de preguntas')
          and 'beat --mailbox' in sent[0] and util.age_seconds(nm_stored().get('nomailbox_alerted_at')) < 60)
    run('watchdog', '--notify')
    check('watchdog --notify: not again within the hour', len(open(notify_log).read().splitlines()) == 1)
    nm_lock(nomailbox_alerted_at=hb_ago(3700))
    run('watchdog', '--notify')
    check('watchdog --notify: again once the hour has passed', len(open(notify_log).read().splitlines()) == 2)
    nm_lock(started=hb_ago(100))
    r = run('watchdog', '--notify')
    check('watchdog: a lock younger than 10 min is not warned about', 'NOMAILBOX' not in r.stdout
          and len(open(notify_log).read().splitlines()) == 2)
    nm_lock(mailbox='local_qs', nomailbox_alerted_at=hb_ago(100))
    run('watchdog', '--notify')
    check('watchdog --notify: once the mailbox is registered the mark is cleared and nothing is sent',
          'nomailbox_alerted_at' not in nm_stored() and len(open(notify_log).read().splitlines()) == 2)
    nm_lock(heartbeat=hb_ago(3000))
    r = run('watchdog')
    check('watchdog: a STALE lock without mailbox gets its STALE line, not a NOMAILBOX one',
          r.stdout.startswith('STALE ') and 'NOMAILBOX' not in r.stdout)
    os.remove(os.path.join(lock_home, 'locks', nm_key + '.json'))
    open(notify_log, 'w').close()

    # 6b. watchdog: why a supervisor is STALE
    open(notify_log, 'w').close()

    def api_rec(ago, error, text):
        return {'type': 'assistant', 'timestamp': iso(ago), 'isApiErrorMessage': True, 'error': error,
                'message': {'model': '<synthetic>', 'content': [{'type': 'text', 'text': text}]}}

    def wd_session(sid, key, records, age=5000, ago=3000):
        cli(sid, sessionId='cli-' + sid)
        put_lock(key, sid, ago)
        if records is not None:
            write_jsonl(tpath('cli-' + sid), records, age=age)

    api_text = "API Error: Can't reach the API server \u2014 check your internet or DNS (EAI_AGAIN)"
    lim_text = "You've hit your session limit \u00b7 resets 5:30am (Europe/Madrid)"
    wd_session('local_wb1', 'k-busy1', [text_rec(4000)], age=10)                    # main transcript touched now
    wd_session('local_wb2', 'k-busy2', [text_rec(4000)])                            # only a subagent is touched
    write_jsonl(spath('cli-local_wb2', 'agent-a.jsonl'), [text_rec(4000)], age=10)
    wd_session('local_wa', 'k-api', [text_rec(4100), api_rec(4000, 'server_error', api_text)])
    wd_session('local_wl', 'k-limit', [text_rec(4100), api_rec(4000, 'rate_limit', lim_text)])
    wd_session('local_wh', 'k-human', [text_rec(4100), tool_rec(4000, 'AskUserQuestion', 'qh')])
    wd_session('local_wi', 'k-idle', [text_rec(4100), text_rec(4000)])
    wd_session('local_wn', 'k-unknown', None)
    wd_session('local_wr', 'k-recovered', [text_rec(4100), api_rec(4000, 'server_error', api_text), text_rec(3900)])  # answered after the error
    r = run('watchdog')
    reasons = dict(re.findall(r'^STALE (\S+) .* reason=(\w+)$', r.stdout, re.M))
    check('watchdog: STALE lines say why; a busy owner (own or subagent transcript touched) is silent',
          r.returncode == 0 and reasons == {'k-api': 'api', 'k-limit': 'limit', 'k-human': 'human', 'k-idle': 'idle',
                                            'k-unknown': 'unknown', 'k-recovered': 'idle'}
          and not any(x in r.stdout for x in ('k-busy1', 'k-busy2')))
    hh = lambda ago: datetime.fromtimestamp(time.time() - ago).strftime('%H:%M')
    r = run('watchdog', '--notify')
    sent = open(notify_log).read().splitlines()
    t = lambda k: 'Supervisión parada: proj|La sesión «T ' + k + '» '
    check('watchdog --notify: api text with the event time and the error excerpt',
          t('k-api') + f'se paró a las {hh(4000)} por un error de conexión con la API («{api_text}»). Ábrela y escribe «reanuda».' in sent)
    check('watchdog --notify: limit text',
          t('k-limit') + f'se paró a las {hh(4000)} al agotar el límite de uso («{lim_text}»). '
          'Cuando se renueve o cambies de cuenta, ábrela y escribe «reanuda».' in sent)
    check('watchdog --notify: human text names the tool',
          t('k-human') + f'espera una respuesta tuya (AskUserQuestion) desde las {hh(4000)}. Ábrela y contéstala.' in sent)
    check('watchdog --notify: idle text, unknown text (time from the heartbeat)',
          any(x.startswith(t('k-idle') + 'está quieta desde las ') and x.endswith(': terminó un turno sin dejar armado su vigilante. Ábrela y escribe «reanuda».') for x in sent)
          and t('k-unknown') + f'no da señales desde las {hh(3000)} y no encuentro su transcripción. Ábrela: si está parada, escribe «reanuda».' in sent)
    check('watchdog --notify: exactly one notification per stale incident, none for busy ones',
          len(sent) == 6 and not any('k-busy' in x for x in sent))
    stored = {k: json.load(open(os.path.join(lock_home, 'locks', k + '.json'))) for k in ('k-api', 'k-limit', 'k-busy1')}
    check('watchdog --notify: alert_reason stored',
          stored['k-api']['alert_reason'] == 'api' and stored['k-limit']['alert_reason'] == 'limit' and 'alert_kind' not in stored['k-busy1'])
    run('watchdog', '--notify')
    check('watchdog --notify: same reason is not notified again', len(open(notify_log).read().splitlines()) == 6)
    cli('local_wl', sessionId='cli-local_wl', pid=dead.pid)  # the quiet session loses its process (app restart)
    r = run('watchdog', '--notify')
    check('watchdog --notify: a STALE session that loses its process is the same stop, not notified again',
          re.search(r'^DEAD k-limit ', r.stdout, re.M) is not None and len(open(notify_log).read().splitlines()) == 6)
    write_jsonl(tpath('cli-local_wa'), [text_rec(4100), api_rec(4000, 'server_error', api_text), text_rec(3900)], age=5000)
    run('watchdog', '--notify')
    sent = open(notify_log).read().splitlines()
    check('watchdog --notify: a change of reason re-alerts and is stored',
          len(sent) == 7 and 'está quieta desde' in sent[-1] and json.load(open(os.path.join(lock_home, 'locks', 'k-api.json')))['alert_reason'] == 'idle')
    os.utime(tpath('cli-local_wa'))  # the supervisor wakes up and works: busy again
    run('watchdog', '--notify')
    woke = json.load(open(os.path.join(lock_home, 'locks', 'k-api.json')))
    check('watchdog --notify: an owner that is busy again loses its alert fields, no new notification',
          len(open(notify_log).read().splitlines()) == 7 and not {'alerted_at', 'alert_kind', 'alert_reason'} & set(woke))
    for name in os.listdir(os.path.join(lock_home, 'locks')):
        os.remove(os.path.join(lock_home, 'locks', name))

    # 6b-2. revive: a live, idle supervisor whose turn was cut by the usage limit (its process alive, so never DEAD)
    # is woken once the account has usage again, on guard too; busy, paused, young, waiting on the developer, or quiet
    # on guard without a cut, it is not
    fake_pause = os.path.join(tmp, 'fake-project-pause')
    with open(fake_pause, 'w') as fh:
        fh.write("def paused_marker(path):\n    return {'by': 'test'} if str(path).endswith('paused-proj') else None\n")
    st_env = lambda usage: dict(env, SUPERVISOR_USAGE=usage, PROJECT_PAUSE_BIN=fake_pause)
    srevive = lambda usage, *a: subprocess.run([sys.executable, runtime.ENTRY, 'revive', *a], capture_output=True,
                                               text=True, env=st_env(usage))
    cut_recs = [text_rec(4100), api_rec(4000, 'rate_limit', lim_text)]
    wd_session('local_sc', 'k-cut', cut_recs, ago=3600)                      # F1, running, silent 1 h, cut by the limit
    wd_session('local_sg', 'k-guard', cut_recs, ago=3600)
    put(os.path.join(lock_home, 'locks'), 'k-guard.json',
        dict(json.load(open(os.path.join(lock_home, 'locks', 'k-guard.json'))), phase='guardia'))
    wd_session('local_sq', 'k-gquiet', [text_rec(4100)], ago=3600)           # on guard, quiet 1 h, not cut: normal
    put(os.path.join(lock_home, 'locks'), 'k-gquiet.json',
        dict(json.load(open(os.path.join(lock_home, 'locks', 'k-gquiet.json'))), phase='guardia'))
    wd_session('local_sb', 'k-sbusy', [text_rec(4100), tool_rec(4000, 'Bash', 'sb')], ago=3600)  # busy, not cut
    cli('local_sb', sessionId='cli-local_sb', status='busy')                 # the CLI says it is working now
    wd_session('local_sp', 'k-spaused', cut_recs, ago=3600)
    put(os.path.join(lock_home, 'locks'), 'k-spaused.json',
        dict(json.load(open(os.path.join(lock_home, 'locks', 'k-spaused.json'))), checkout=os.path.join(tmp, 'paused-proj')))
    wd_session('local_sy', 'k-syoung', [text_rec(1300)], age=1200, ago=1200)  # quiet 20 min, not cut: within the 45
    young_cut = [text_rec(1300), api_rec(1200, 'rate_limit', lim_text)]
    wd_session('local_sl', 'k-slimit', young_cut, age=1200, ago=1200)         # cut by the limit 20 min ago: no 45 min wait
    wd_session('local_sn', 'k-snew', young_cut, age=120, ago=120)             # cut 2 min ago: within LIMIT_CUT_AFTER_S
    wd_session('local_sw', 'k-swork', young_cut, age=1200, ago=1200)         # cut, but its subagents work on:
    cli('local_sw', sessionId='cli-local_sw', status='busy')                 # the CLI says busy and a subagent
    write_jsonl(spath('cli-local_sw', 'agent-w.jsonl'), [text_rec(5)], age=5)  # transcript moves: still cut
    wd_session('local_sh', 'k-shuman', [text_rec(4100), tool_rec(4000, 'AskUserQuestion', 'qs')], ago=3600)
    rv_file = os.path.join(lock_home, 'revive.json')
    if os.path.exists(rv_file):
        os.remove(rv_file)
    r = srevive('no')
    check('revive: a supervisor cut by the limit is not woken while the account has no usage (HOLD)',
          r.returncode == 0 and r.stdout.startswith('HOLD ') and 'STALLED' not in r.stdout and not os.path.exists(rv_file))
    r = srevive('unknown')
    check('revive: with the usage unknown, a live supervisor with a cut turn is not woken either',
          r.returncode == 0 and 'HOLD-STALLED' in r.stdout and not re.search(r'^STALLED ', r.stdout, re.M))
    plan = json.loads(srevive('yes', '--json').stdout or '{}')
    named = sorted(t['session_id'] for t in plan.get('targets') or [])
    msg = next((t['message'] for t in plan.get('targets') or [] if t['session_id'] == 'local_sc'), '')
    check('revive: cut by the limit and usage back -> woken, also one cut 20 min ago, one on guard and one whose subagents still work',
          named == ['local_sc', 'local_sg', 'local_sl', 'local_sw'] and all(t['reason'] == 'stalled' and t['cause'] == 'limit' and t['attempt'] == 1
                                                    for t in plan['targets']))
    check('revive: its text says the truth (turn cut by the limit, process alive), with the marker and the F1 census',
          msg.startswith('[reanimar supervisora] ') and 'sigue vivo' in msg and 'límite de uso' in msg
          and lim_text in msg and 'murió hacia' not in msg and 'censo' in msg and 'supervisor-lock wait' in msg
          and 'get_usage' in msg and f'se cortó hacia las {hh(4000)}' in msg)
    rv = json.load(open(rv_file))
    check('revive: its plan entry lets the cross-project gate pass the marker (session, fresh planned_at)',
          rv['k-cut']['session'] == 'local_sc' and rv['k-cut']['kind'] == 'stalled' and time.time() - rv['k-cut']['planned_at'] < 60)
    notes = '\n'.join(plan.get('notes') or [])
    check('revive: on guard without a cut, paused, quiet less than 45 min without a cut, cut less than 5 min ago -> not '
          'woken; busy and waiting on the developer -> said, not woken; on guard and cut by the limit -> woken',
          not any(k in rv for k in ('k-gquiet', 'k-sbusy', 'k-spaused', 'k-syoung', 'k-shuman', 'k-snew'))
          and 'k-guard' in rv
          and 'BUSY local_sb k-sbusy' in notes and 'HUMAN local_sh k-shuman' in notes
          and not any(x in notes for x in ('k-gquiet', 'k-spaused', 'k-syoung', 'k-snew')))
    r = srevive('yes')
    check('revive: within REVIVE_RETRY_S the same cut waits', 'WAIT-STALLED local_sc k-cut' in r.stdout
          and not re.search(r'^STALLED ', r.stdout, re.M))
    rv = json.load(open(rv_file))
    rv['k-cut']['planned_at'] -= 3600
    put(lock_home, 'revive.json', rv)
    r = srevive('yes')
    check('revive: after REVIVE_RETRY_S it tries again', re.search(r'^STALLED local_sc k-cut cause=limit .*attempt=2/3$', r.stdout, re.M) is not None)
    rv = json.load(open(rv_file))
    rv['k-cut'].update(attempts=3, planned_at=time.time() - 3600)
    put(lock_home, 'revive.json', rv)
    r = srevive('yes')
    check('revive: after 3 attempts it gives up (the watchdog tells the developer)', 'GIVEUP-STALLED local_sc k-cut' in r.stdout
          and not re.search(r'^STALLED ', r.stdout, re.M))
    put_lock('k-cut', 'local_sc', 3700)                                      # another stop (another heartbeat): anew
    r = srevive('yes')
    check('revive: a new cut starts again at attempt 1', re.search(r'^STALLED local_sc k-cut .*attempt=1/3$', r.stdout, re.M) is not None)
    put_lock('k-cut', 'local_sc', 10)                                        # it beats again: attended
    r = srevive('yes')
    check('revive: a supervisor that beats again leaves the state', 'k-cut' not in json.load(open(rv_file))
          and not re.search(r'^STALLED ', r.stdout, re.M))
    for name in os.listdir(os.path.join(lock_home, 'locks')):
        os.remove(os.path.join(lock_home, 'locks', name))
    os.remove(rv_file)

    # 6b-3. a pause for the usage limit lasts only while the account has no usage: `beat` refuses it once usage is back
    # (exit 9) unless all that is left waits on a third party (`--third-party`); the watcher prints USAGE, `revive` plans
    # paused-limit (one incident per pause, not per heartbeat) and the Stop hook sends the owner back to work
    urun = lambda usage, *a: subprocess.run([sys.executable, runtime.ENTRY, *a], capture_output=True, text=True,
                                            env=st_env(usage))
    pz_key = p1['key']
    load_lock = lambda k: json.load(open(os.path.join(lock_home, 'locks', k + '.json')))
    aside = os.path.join(tmp, 'pause-aside')  # the sessions of the cases above (cut ones among them) are set aside
    for directory, name in ((sessions_dir, 'cli'), (app_dir, 'app')):
        os.makedirs(os.path.join(aside, name))
        for f in os.listdir(directory):
            os.replace(os.path.join(directory, f), os.path.join(aside, name, f))
    run('acquire', '--dir', repo, '--session', 'local_pz')
    save(dict(load(), skill_seen=os.path.getmtime(skill)))  # read: SKILL_CHANGED and its Stop block stay quiet
    shift_heartbeat(900)
    r = urun('yes', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'paused', '--phase', 'F4', '--round', '7')
    cur = load()
    check('beat --state paused with usage and no --third-party: refused (exit 9), Spanish reason on stderr, state kept',
          r.returncode == lock_mod.PAUSE_REFUSED == 9 and f'PAUSE REFUSED {pz_key}: la cuenta tiene uso ahora' in r.stderr
          and 'no la hora' in r.stderr and 'no es motivo de pausa' in r.stderr and 'F1' in r.stderr
          and '--third-party' in r.stderr and cur['state'] == 'running' and not set(lock_mod.PAUSE_FIELDS) & set(cur))
    check('beat refused: the heartbeat, phase and round of the beat still count',
          util.age_seconds(cur['heartbeat']) < 60 and cur['phase'] == 'F4' and cur['round'] == 7)
    r = urun('no', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'paused')
    cur = load()
    check('beat --state paused without usage: accepted as a limit pause with paused_at',
          r.returncode == 0 and cur['state'] == 'paused' and cur.get('pause_cause') == 'limit' and bool(cur.get('paused_at'))
          and 'pause_why' not in cur and lock_mod.paused_for_limit(cur))
    save(dict(cur, paused_at=hb_ago(7200)))
    first_pause = load()['paused_at']
    r = urun('unknown', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'paused')
    check('beat --state paused with the usage unknown: accepted, and paused_at stays across repeated paused beats',
          r.returncode == 0 and load()['paused_at'] == first_pause and load()['pause_cause'] == 'limit')
    r = urun('yes', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'paused')
    check('beat --state paused with usage on a limit pause: refused, the lock stays paused for the limit (the signals push it)',
          r.returncode == 9 and load()['state'] == 'paused' and load()['paused_at'] == first_pause)
    legacy = {k: v for k, v in load().items() if k not in lock_mod.PAUSE_FIELDS}
    save(legacy)
    check('a paused lock without pause_cause (older lock) counts as a limit pause', lock_mod.paused_for_limit(load()))
    urun('no', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'paused')
    check('beat paused on an older lock records the cause and when the pause was first seen',
          load().get('pause_cause') == 'limit' and bool(load().get('paused_at')))
    r = urun('yes', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'paused', '--third-party', 'corto')
    check('beat --third-party needs a real reason (exit 2)', r.returncode == 2 and '--third-party' in r.stderr)
    r = urun('yes', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'running', '--third-party', 'la revisión de la tienda de aplicaciones')
    check('beat --third-party only goes with --state paused (exit 2)', r.returncode == 2 and load()['state'] == 'paused')
    tp_why = 'la revisión de la tienda de aplicaciones, que hace la propia tienda'
    r = urun('yes', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'paused', '--third-party', tp_why)
    cur = load()
    check('beat --state paused --third-party with usage: accepted, third-party cause and why recorded',
          r.returncode == 0 and cur['state'] == 'paused' and cur['pause_cause'] == 'third-party' and cur['pause_why'] == tp_why
          and not lock_mod.paused_for_limit(cur) and cur['paused_at'] != first_pause)

    def pz_wait(usage, timeout='1.5'):
        began = time.time()
        out = subprocess.run([sys.executable, runtime.ENTRY, 'wait', '--dir', repo, '--owner', 'local_pz', '--interval', '0.2',
                              '--timeout', timeout, '--all-idle-after', '0'], capture_output=True, text=True, env=st_env(usage))
        return out.stdout.splitlines(), time.time() - began

    lines, _ = pz_wait('yes')
    check('wait --owner: a pause for a third party is not a USAGE signal', lines == ['TIMEOUT 1.5s'])
    save(dict(load(), pause_cause='limit', paused_at=first_pause))
    pz_lines, took = pz_wait('yes', timeout='20')
    check('wait --owner: a limit pause while the account has usage -> one USAGE line at once, then wait returns',
          took < 5 and len(pz_lines) == 1 and pz_lines[0].startswith(f'USAGE {pz_key} (la cuenta tiene uso ahora')
          and 'get_usage' in pz_lines[0] and 'beat --session local_pz --state running' in pz_lines[0]
          and 'F1' in pz_lines[0] and '--third-party' in pz_lines[0])
    check('wait --owner: a limit pause without usage, or with the usage unknown, is no signal',
          pz_wait('no')[0] == ['TIMEOUT 1.5s'] and pz_wait('unknown')[0] == ['TIMEOUT 1.5s'])
    pz_cli = os.path.join(sessions_dir, 'pz.json')
    put(sessions_dir, 'pz.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-pz', 'hostSessionId': 'local_pz', 'status': 'idle'})
    pz_task = {'id': 'bz', 'type': 'shell', 'status': 'running', 'description': 'vigilante',
               'command': '~/.claude/scripts/supervisor-lock wait --owner local_pz --timeout 600'}
    pz_stop = lambda usage, **extra: subprocess.run(
        [sys.executable, runtime.ENTRY, 'hook'], capture_output=True, text=True, env=st_env(usage),
        input=json.dumps(dict({'hook_event_name': 'Stop', 'session_id': 'cli-pz', 'cwd': repo, 'stop_hook_active': False,
                               'background_tasks': [pz_task]}, **extra)))
    out = json.loads(pz_stop('yes').stdout or '{}')
    check('hook Stop: the owner of a lock paused for the limit, with usage back, may not end the turn (Spanish reason)',
          out.get('decision') == 'block' and 'en pausa por el límite de uso' in out.get('reason', '')
          and 'tiene uso ahora' in out['reason'] and 'beat --session local_pz --state running' in out['reason']
          and 'F1' in out['reason'] and '--third-party' in out['reason'])
    check('hook Stop: blocked once per turn (stop_hook_active), and not without usage or with the usage unknown',
          pz_stop('yes', stop_hook_active=True).stdout == '' and pz_stop('no').stdout == '' and pz_stop('unknown').stdout == '')
    save(dict(load(), pause_cause='third-party', pause_why=tp_why))
    check('hook Stop: a pause for a third party is not blocked', pz_stop('yes').stdout == '')
    r = urun('yes', 'beat', '--dir', repo, '--session', 'local_pz', '--state', 'running')
    check('beat --state running clears pause_cause, pause_why and paused_at',
          r.returncode == 0 and load()['state'] == 'running' and not set(lock_mod.PAUSE_FIELDS) & set(load()))
    os.remove(pz_cli)
    os.remove(lock_file)

    def pl_lock(key, sid, **extra):
        put(os.path.join(lock_home, 'locks'), key + '.json',
            dict({'key': key, 'project': 'proj', 'session_id': sid, 'title': 'T ' + key, 'state': 'paused', 'phase': 'F4',
                  'round': 3, 'heartbeat': hb_ago(60), 'pause_cause': 'limit', 'paused_at': hb_ago(7200)}, **extra))

    pl_clis = ('local_pl', 'local_pt', 'local_pg', 'local_pp', 'local_pb', 'local_pd')
    for sid in pl_clis:
        cli(sid, sessionId='cli-' + sid, status='busy' if sid == 'local_pb' else 'idle')
    pl_lock('k-plim', 'local_pl')                                                 # limit pause, beats every 15 min
    pl_lock('k-ptp', 'local_pt', pause_cause='third-party', pause_why=tp_why)     # waits on a third party
    pl_lock('k-plegacy', 'local_pg', pause_cause=None, paused_at=None)            # an older lock: no cause recorded
    pl_lock('k-pproj', 'local_pp', checkout=os.path.join(tmp, 'paused-proj'))     # the developer paused the project
    pl_lock('k-pbusy', 'local_pb')                                                # in a turn now
    pl_lock('k-pguard', 'local_pd', phase='guardia')                              # on guard
    r = srevive('no')
    check('revive: a supervisor paused for the limit is not woken while the account has no usage',
          r.returncode == 0 and r.stdout.startswith('HOLD ') and not re.search(r'^PAUSED ', r.stdout, re.M) and not os.path.exists(rv_file))
    r = srevive('unknown')
    check('revive: nor while the usage is unknown (HOLD-PAUSED)',
          'HOLD-PAUSED' in r.stdout and not re.search(r'^PAUSED ', r.stdout, re.M))
    plan = json.loads(srevive('yes', '--json').stdout or '{}')
    paused_t = {t['session_id']: t for t in plan.get('targets') or [] if t.get('reason') == 'paused-limit'}
    msg = (paused_t.get('local_pl') or {}).get('message', '')
    check('revive: with usage, live supervisors paused for the limit (older locks too) are planned as paused-limit',
          sorted(paused_t) == ['local_pg', 'local_pl'] and paused_t['local_pl']['attempt'] == 1
          and paused_t['local_pl']['cause'] == 'limit')
    check('revive: the paused-limit text (marker, usage now, get_usage, beat running, F1 census, watcher, third party)',
          msg.startswith('[reanimar supervisora] La cuenta tiene uso ahora') and 'en pausa por el límite de uso' in msg
          and 'no es motivo de pausa' in msg and 'get_usage' in msg and 'beat --session local_pl --state running' in msg
          and 'censo de F1' in msg and 'supervisor-lock wait' in msg and '--third-party' in msg
          and f'desde las {hh(7200)}' in msg)
    rv = json.load(open(rv_file))
    notes = '\n'.join(plan.get('notes') or [])
    check('revive: the paused-limit entry lets the cross-project gate pass the marker (session, fresh planned_at)',
          rv['k-plim']['session'] == 'local_pl' and rv['k-plim']['kind'] == 'paused-limit'
          and time.time() - rv['k-plim']['planned_at'] < 60 and rv['k-plim']['incident'] == load_lock('k-plim')['paused_at'])
    check('revive: third-party pauses, paused projects and guards are not planned; a busy one is said, kept, not woken',
          not any(k in rv for k in ('k-ptp', 'k-pproj', 'k-pguard')) and 'BUSY local_pb k-pbusy' in notes
          and rv['k-pbusy']['attempts'] == 0 and 'local_pb' not in paused_t)
    check('revive: PLAN-PAUSED is logged with its cause',
          'PLAN-PAUSED k-plim local_pl cause=limit attempt=1' in open(os.path.join(lock_home, 'revive.log')).read())
    legacy_incident = rv['k-plegacy']['incident']
    pl_lock('k-plim', 'local_pl', paused_at=load_lock('k-plim')['paused_at'])   # it beats again, still paused
    pl_lock('k-plegacy', 'local_pg', pause_cause=None, paused_at=None)
    r = srevive('yes')
    check('revive: a paused supervisor that beats again waits (the incident is the pause, not the heartbeat)',
          'WAIT-PAUSED local_pl k-plim' in r.stdout and 'WAIT-PAUSED local_pg k-plegacy' in r.stdout
          and not re.search(r'^PAUSED ', r.stdout, re.M) and json.load(open(rv_file))['k-plegacy']['incident'] == legacy_incident)
    rv = json.load(open(rv_file))
    rv['k-plim']['planned_at'] -= 3600
    put(lock_home, 'revive.json', rv)
    pl_lock('k-plim', 'local_pl', paused_at=load_lock('k-plim')['paused_at'])
    r = srevive('yes')
    check('revive: after REVIVE_RETRY_S the same pause is tried again (attempt 2)',
          re.search(r'^PAUSED local_pl k-plim cause=limit .*attempt=2/3$', r.stdout, re.M) is not None)
    rv = json.load(open(rv_file))
    rv['k-plim'].update(attempts=3, planned_at=time.time() - 3600)
    put(lock_home, 'revive.json', rv)
    pl_lock('k-plim', 'local_pl', paused_at=load_lock('k-plim')['paused_at'])
    r = srevive('yes')
    check('revive: after 3 attempts on the same pause it gives up, whatever the heartbeat',
          'GIVEUP-PAUSED local_pl k-plim' in r.stdout and not re.search(r'^PAUSED local_pl ', r.stdout, re.M))
    pl_lock('k-plim', 'local_pl', paused_at=hb_ago(30))                           # a new pause: a new incident
    r = srevive('yes')
    check('revive: a new pause starts again at attempt 1',
          re.search(r'^PAUSED local_pl k-plim .*attempt=1/3$', r.stdout, re.M) is not None)
    pl_lock('k-plim', 'local_pl', state='running', pause_cause=None, paused_at=None)
    srevive('yes')
    check('revive: a supervisor running again leaves the state', 'k-plim' not in json.load(open(rv_file)))
    for name in os.listdir(os.path.join(lock_home, 'locks')):
        os.remove(os.path.join(lock_home, 'locks', name))
    for sid in pl_clis:
        os.remove(os.path.join(sessions_dir, sid + '.json'))
    os.remove(rv_file)
    for directory, name in ((sessions_dir, 'cli'), (app_dir, 'app')):
        for f in os.listdir(os.path.join(aside, name)):
            os.replace(os.path.join(aside, name, f), os.path.join(directory, f))
    shutil.rmtree(aside)

    # 6c. watchdog --nudge: wakes stopped sessions through session-nudge, independent of the locks
    open(nudge_log, 'w').close()
    with open(nudge_out, 'w') as fh:
        fh.write('SENT 00000000-0000-0000-0000-000000000001 sent\nQUESTION x pid=1 waiting 20 min "t"\nnudged 1 session(s)\n')
    r = run('watchdog')
    check('watchdog without --nudge never calls session-nudge', r.returncode == 0 and open(nudge_log).read() == '')
    r = run('watchdog', '--notify')
    check('watchdog --notify alone never calls session-nudge', r.returncode == 0 and open(nudge_log).read() == '')
    r = run('watchdog', '--nudge')
    check('watchdog --nudge: runs `stuck --send --min-minutes 15 --max 6` and reports what was sent',
          r.returncode == 0 and open(nudge_log).read().strip() == 'stuck --send --min-minutes 15 --max 6'
          and r.stdout.splitlines() == ['NUDGE SENT 00000000-0000-0000-0000-000000000001 sent'])
    with open(nudge_out + '.rc', 'w') as fh:
        fh.write('2')
    r = run('watchdog', '--nudge')
    check('watchdog --nudge: a failing session-nudge is reported but never fails the watchdog',
          r.returncode == 0 and 'NUDGE-FAILED exit 2' in r.stdout)
    os.remove(nudge_out + '.rc')
    env_missing = dict(env, SUPERVISOR_NUDGE=os.path.join(tmp, 'does-not-exist'))
    r = subprocess.run([sys.executable, runtime.ENTRY, 'watchdog', '--nudge'], capture_output=True, text=True, env=env_missing)
    check('watchdog --nudge: a missing session-nudge is reported, exit 0', r.returncode == 0 and 'NUDGE-FAILED' in r.stdout)
    r = subprocess.run([sys.executable, runtime.ENTRY, 'watchdog', '--nudge'], capture_output=True, text=True,
                       env=dict(env, SUPERVISOR_NUDGE=''))
    check('watchdog --nudge: SUPERVISOR_NUDGE empty switches it off', r.returncode == 0 and 'NUDGE' not in r.stdout)
    put_lock('k-dead1', 'local_wd1', 1200)
    open(nudge_log, 'w').close()
    r = run('watchdog', '--nudge')
    check('watchdog --nudge: also reports the lock incidents and nudges once',
          r.returncode == 0 and 'DEAD k-dead1' in r.stdout and open(nudge_log).read().count('stuck') == 1)
    os.remove(os.path.join(lock_home, 'locks', 'k-dead1.json'))

    # 6d. T5: the alert of an incident the nudge of this run already pushed says nothing needs doing
    def push_case(nudge_text, rc=0, flags=('--notify', '--nudge')):
        wd_session('local_wp', 'k-push', [text_rec(4100), text_rec(4000)])   # quiet, alive, idle; nothing alerted yet
        open(notify_log, 'w').close()
        with open(nudge_out, 'w') as fh:
            fh.write(nudge_text)
        with open(nudge_out + '.rc', 'w') as fh:
            fh.write(str(rc))
        r = run('watchdog', *flags)
        return r, [x for x in open(notify_log).read().splitlines() if 'k-push' in x]

    pushed_line = 'SENT   QUESTION cli-local_wp pid=1 waiting 20 min "T k-push"\nnudged 1 session(s)\n'
    r, msgs = push_case(pushed_line)
    check('watchdog --notify --nudge: a session the nudge woke -> the alert says the developer need do nothing, no manual «reanuda»',
          r.returncode == 0 and len(msgs) == 1 and msgs[0].endswith('Ya la he empujado yo: no tienes que hacer nada.')
          and 'Ábrela' not in msgs[0] and 'reanuda' not in msgs[0] and msgs[0].startswith('Supervisión parada: proj|La sesión «T k-push» estaba quieta desde las ')
          and 'NUDGE SENT' in r.stdout)
    r, msgs = push_case(pushed_line, rc=2)
    check('watchdog --notify --nudge: the nudge failed (exit 2) -> the manual «Ábrela y escribe «reanuda»» stays',
          len(msgs) == 1 and 'Ábrela y escribe «reanuda»' in msgs[0] and 'Ya la he empujado' not in msgs[0])
    r, msgs = push_case(pushed_line, flags=('--notify',))
    check('watchdog --notify without --nudge -> manual text',
          len(msgs) == 1 and 'Ábrela y escribe «reanuda»' in msgs[0] and 'Ya la he empujado' not in msgs[0])
    r, msgs = push_case('SENT   QUESTION cli-other-session pid=1 waiting 20 min "x"\nnudged 1 session(s)\n')
    check('watchdog --notify --nudge: another session was woken, not this one -> manual text',
          len(msgs) == 1 and 'Ábrela y escribe «reanuda»' in msgs[0] and 'Ya la he empujado' not in msgs[0])
    held_line = 'HELD   QUESTION cli-local_wp pid=1 waiting 20 min "T k-push"\nnudged 0 session(s), 1 held\n'
    r, msgs = push_case(held_line)
    check('watchdog --notify --nudge: a HELD nudge (bypass recipient keeps it) did not wake the session -> manual «reanuda» text, line still printed',
          r.returncode == 0 and len(msgs) == 1 and 'Ábrela y escribe «reanuda»' in msgs[0] and 'Ya la he empujado' not in msgs[0]
          and 'NUDGE HELD' in r.stdout and 'NUDGE SENT' not in r.stdout)
    r, msgs = push_case(held_line + 'SENT   QUESTION cli-local_wp pid=1 waiting 20 min "T k-push"\nnudged 1 session(s), 1 held\n')
    check('watchdog --notify --nudge: HELD and a real SENT line for the same session -> pushed text (the SENT one counts)',
          len(msgs) == 1 and msgs[0].endswith('Ya la he empujado yo: no tienes que hacer nada.'))
    r, msgs = push_case('HELD   HANDOFF cli-local_wp pid=1 stopped 20 min ago (x) "T k-push"\nSENT   QUESTION cli-other-session pid=1 waiting 20 min "x"\nnudged 1 session(s), 1 held\n')
    check('watchdog --notify --nudge: HELD for this session, SENT only for another -> manual text',
          len(msgs) == 1 and 'Ábrela y escribe «reanuda»' in msgs[0] and 'Ya la he empujado' not in msgs[0])
    r, msgs = push_case('SENT   OPEN_DIALOG cli-local_wp pid=1 open 20 min, 1 question(s) to copy to ask-queue "T k-push"\nnudged 0 session(s)\n')
    check('watchdog --notify --nudge: an OPEN_DIALOG is queued, not woken -> manual text',
          len(msgs) == 1 and 'Ábrela y escribe «reanuda»' in msgs[0] and 'Ya la he empujado' not in msgs[0])
    check('stale_text: every reason has a pushed variant ending in the same sentence, without «Ábrela»',
          all(watchdog.stale_text(x, 'T', '10:00', 'd', pushed=True).endswith(watchdog.PUSHED_TAIL) and 'Ábrela' not in watchdog.stale_text(x, 'T', '10:00', 'd', pushed=True)
              for x in ('api', 'limit', 'human', 'idle', 'unknown')))
    os.remove(nudge_out + '.rc')
    os.remove(os.path.join(lock_home, 'locks', 'k-push.json'))

    # 7. hook
    reset()
    shutil.rmtree(os.path.join(lock_home, 'closable'), ignore_errors=True)  # caches left by the `wait --owner` cases above
    open(notify_log, 'w').close()
    run('acquire', '--dir', repo, '--session', 'local_sup', '--title', 'Supervisión proj')
    run('beat', '--dir', repo, '--session', 'local_sup', '--phase', 'F2', '--round', '5', '--skill-seen')
    put(sessions_dir, 'sup.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-sup', 'hostSessionId': 'local_sup', 'name': 'sup', 'status': 'busy'})
    put(sessions_dir, 'oth.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-oth', 'hostSessionId': 'local_oth', 'name': 'oth', 'status': 'busy'})

    def hook(payload, raw=None, hook_env=None):
        return subprocess.run([sys.executable, runtime.ENTRY, 'hook'], input=raw if raw is not None else json.dumps(payload),
                              capture_output=True, text=True, env=hook_env or env)

    def stop(**extra):
        return dict({'hook_event_name': 'Stop', 'session_id': 'cli-sup', 'cwd': repo, 'stop_hook_active': False}, **extra)

    armed_task = {'id': 'b1', 'type': 'shell', 'status': 'running', 'description': 'supervisor-lock wait',
                  'command': '~/.claude/scripts/supervisor-lock wait --owner local_sup --timeout 600'}
    r = hook(stop(session_id='cli-oth'))
    check('hook: a session that is not a supervisor -> empty output, exit 0', r.returncode == 0 and r.stdout == '')
    r = hook(stop(session_id='cli-nobody'))
    check('hook: unknown session -> empty output', r.returncode == 0 and r.stdout == '')
    r = hook(stop(background_tasks=[armed_task]))
    check('hook: Stop with a running `wait --owner` task -> nothing', r.returncode == 0 and r.stdout == '')
    via_variable = dict(armed_task, description='vigilante',
                        command='L=~/.claude/scripts/supervisor-lock; $L wait --owner local_sup --guard --timeout 21600')
    check('hook: the watcher armed as the skill writes it (`$L wait`) counts as armed',
          hook(stop(background_tasks=[via_variable])).stdout == '')
    closer_task = dict(armed_task, description='cierre',
                       command='~/.claude/scripts/supervisor-lock wait-closer --session local_sup --timeout 600')
    check('hook: `wait-closer` is not the supervisor\'s watcher -> blocked',
          'sin vigilante' in hook(stop(background_tasks=[closer_task])).stdout)
    wrapped = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'supervisor-lock', 'wait', '--owner', 'local_sup'])
    try:
        check('hook: a watcher armed through a wrapper (the task does not name the script, the process does) counts',
              hook(stop(background_tasks=[dict(armed_task, description='w', command='tk L wait --owner local_sup')])).stdout == '')
    finally:
        wrapped.kill()
        wrapped.wait()
    check('hook: background tasks without a watcher and no watcher process -> blocked',
          'sin vigilante' in hook(stop(background_tasks=[dict(armed_task, description='x', command='sleep 600')])).stdout)

    # 7a. finished sessions: `closable`, `hold`, the cache written by `wait --owner`, the Stop block.
    # 7a-7a3 run with archiving authorised in config (archive_preauthorised); the default policy is checked after 7a3.
    authorised_cfg = os.path.join(tmp, 'config-archive-authorised')
    os.makedirs(authorised_cfg)
    with open(os.path.join(authorised_cfg, 'supervision.json'), 'w') as fh:
        json.dump({'archive_preauthorised': True}, fh)
    default_cfg = env.get('CLAUDE_TOOLKIT_CONFIG_DIR')
    env['CLAUDE_TOOLKIT_CONFIG_DIR'] = authorised_cfg
    ms = int(time.time() * 1000)
    fake_cli = subprocess.Popen(['bash', '-c', '(exec -a shell-snapshots-selftest sleep 60) & wait'], start_new_session=True)
    quiet_cli = subprocess.Popen(['sleep', '60'])  # a live CLI process with nothing running under it
    time.sleep(0.3)
    for sid, cli_id, title, ago_h in (('local_fin', None, 'Terminada sin proceso', 5), ('local_box', None, 'Sesión de preguntas de proj', 9),
                                   ('local_young', 'cli-young', 'Ociosa hace poco', 0.2), ('local_bg', 'cli-bg', 'Espera su compilación', 3),
                                   ('local_oi', 'cli-oi', 'Ociosa terminada', 3)):
        rec = {'sessionId': sid, 'cwd': repo, 'title': title, 'lastActivityAt': ms - int(ago_h * 3600000)}
        if cli_id:
            rec['cliSessionId'] = cli_id
            put(sessions_dir, cli_id + '.json', {'pid': fake_cli.pid if cli_id == 'cli-bg' else quiet_cli.pid, 'cwd': repo, 'sessionId': cli_id, 'hostSessionId': sid,
                                              'status': 'idle', 'updatedAt': ms - int(ago_h * 3600000)})
        put(app_dir, sid + '.json', rec)
    r = run('closable', '--dir', repo)
    out = r.stdout
    if 'CLOSABLE local_fin' not in out:
        print(out + r.stderr)
    check('closable: finished (no process, or quiet 2 h) listed oldest first; owner, busy, mailbox and young ones are not',
          0 <= out.find('CLOSABLE local_fin sin proceso') < out.find('CLOSABLE local_oi ociosa')
          and 'local_box' not in out and 'local_young' not in out and 'local_sup' not in out and 'CLOSABLE local_oth' not in out)
    check('closable: a quiet session with a Bash-tool process of its own still running is WORKING, not closable',
          f'WORKING local_bg' in out and f'(pid ' in out and 'CLOSABLE local_bg' not in out)
    r = run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_fin', '--hours', '1')
    check('hold: without --reason -> exit 2', r.returncode == 2)
    r = run('hold', '--dir', repo, '--session', 'local_oth', '--target', 'local_fin', '--reason', 'x')
    check('hold: only the lock owner may hold', r.returncode != 0 and not os.path.exists(os.path.join(lock_home, 'holds')))
    r = run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_fin', '--reason', 'regla X: rama sin integrar', '--hours', '50')
    out = run('closable', '--dir', repo).stdout
    check('hold: the owner parks one for at most 12 h; closable shows it as HOLD with its reason',
          r.returncode == 0 and r.stdout.startswith('HELD local_fin until ') and 'HOLD local_fin hasta ' in out
          and 'regla X: rama sin integrar' in out and 'CLOSABLE local_fin' not in out
          and 11.9 * 3600 < json.load(open(glob.glob(os.path.join(lock_home, 'holds', '*.json'))[0]))['local_fin']['until_epoch'] - time.time() <= 12 * 3600)
    first = json.load(open(glob.glob(os.path.join(lock_home, 'holds', '*.json'))[0]))['local_fin']['first_epoch']
    r = run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_fin', '--reason', 'regla X otra vez')
    renewed = json.load(open(glob.glob(os.path.join(lock_home, 'holds', '*.json'))[0]))['local_fin']
    check('hold: holding it again is a renewal: first_epoch kept, counted, shown by hold and closable',
          renewed['first_epoch'] == first and renewed['renewals'] == 1 and 'renewal 1, held since' in r.stdout
          and '1 renovaciones' in run('closable', '--dir', repo).stdout)
    run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_fin', '--clear')
    check('hold --clear: listed again', 'CLOSABLE local_fin' in run('closable', '--dir', repo).stdout)
    run('wait', '--dir', repo, '--owner', 'local_sup', '--timeout', '0.5', '--interval', '0.2', '--all-idle-after', '0')
    caches = glob.glob(os.path.join(lock_home, 'closable', '*.json'))
    cache = json.load(open(caches[0])) if caches else {}
    check('wait --owner writes the closable cache the Stop hook reads (owner, time, candidates in order)',
          cache.get('owner') == 'local_sup' and [e['id'] for e in cache.get('closable', [])] == ['local_fin', 'local_oi'])
    blocked = os.path.join(os.path.dirname(caches[0]), os.path.basename(caches[0])[:-5] + '.blocked') if caches else ''
    r = hook(stop(background_tasks=[armed_task]))
    reason = json.loads(r.stdout or '{}').get('reason', '')
    check('hook: armed watcher + a finished session -> block naming the oldest one, how to close it and how to hold it',
          json.loads(r.stdout or '{}').get('decision') == 'block' and '(local_fin)' in reason and '/cierra-sesion' in reason
          and 'archive_session' in reason and 'supervisor-lock hold --session local_sup --target local_fin' in reason
          and 'Quedan 1 más' in reason)
    check('hook: the closable block comes at most once every 10 min per lock',
          hook(stop(background_tasks=[armed_task])).stdout == '')
    blocked and os.path.exists(blocked) and os.remove(blocked)
    check('hook: stop_hook_active -> never the closable block', hook(stop(background_tasks=[armed_task], stop_hook_active=True)).stdout == '')
    run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_fin', '--reason', 'regla X')
    reason = json.loads(hook(stop(background_tasks=[armed_task])).stdout or '{}').get('reason', '')
    check('hook: a held session is skipped (the hold is re-read, the cache may be older)', '(local_oi)' in reason and 'local_fin' not in reason)
    blocked and os.path.exists(blocked) and os.remove(blocked)
    put(app_dir, 'local_oi.json', dict(json.load(open(os.path.join(app_dir, 'local_oi.json'))), isArchived=True))
    check('hook: a session archived since the cache was written is skipped', hook(stop(background_tasks=[armed_task])).stdout == '')
    put(app_dir, 'local_oi.json', dict(json.load(open(os.path.join(app_dir, 'local_oi.json'))), isArchived=False))
    with open(caches[0], 'w') as fh:
        json.dump(dict(cache, owner='local_old'), fh)
    check('hook: a fresh cache written by a previous owner\'s watcher never blocks', hook(stop(background_tasks=[armed_task])).stdout == '')
    with open(caches[0], 'w') as fh:
        json.dump(dict(cache, time=time.time() - 3600), fh)
    check('hook: a stale cache (watcher not refreshed in 20 min) never blocks', hook(stop(background_tasks=[armed_task])).stdout == '')
    check('hook: no watcher armed -> the watcher block, not the closable one',
          'sin vigilante' in json.loads(hook(stop(background_tasks=[])).stdout or '{}').get('reason', ''))

    # 7a2. cut sessions: a transcript ending in an API error is never closable; `wait --owner` announces it
    # once it can be resumed, even when it was already cut when the wait started; the Stop hook asks for the resume
    cut_specs = (('local_cutl', 'cli-cutl', 'Cortada por el límite', 4000, 'rate_limit', lim_text),
                 ('local_cuta', 'cli-cuta', 'Cortada por la API', 300, 'server_error', api_text),
                 ('local_cutn', 'cli-cutn', 'API hace nada', 30, 'server_error', api_text),
                 ('local_cuth', 'cli-cuth', 'Cortada y aparcada', 4000, 'rate_limit', lim_text))
    for sid, cli_id, title, ago, error, text in cut_specs:
        put(app_dir, sid + '.json', {'sessionId': sid, 'cliSessionId': cli_id, 'cwd': repo, 'title': title,
                                     'lastActivityAt': ms - ago * 1000})
        put(sessions_dir, cli_id + '.json', {'pid': quiet_cli.pid, 'cwd': repo, 'sessionId': cli_id, 'hostSessionId': sid,
                                          'status': 'idle', 'updatedAt': ms - ago * 1000})
        write_jsonl(tpath(cli_id), [text_rec(ago + 100), api_rec(ago, error, text)], age=ago)
    out = run('closable', '--dir', repo).stdout
    check('closable: sessions whose transcript ends in an API error are CUT (reanudar, no cerrar), never CLOSABLE',
          re.search(r'^CUT local_cutl limit desde \d\d:\d\d: reanudar, no cerrar \| Cortada por el límite$', out, re.M) is not None
          and re.search(r'^CUT local_cuta api desde ', out, re.M) is not None
          and not re.search(r'^CLOSABLE local_cut', out, re.M) and ', 4 cut (resume, never close)' in out)
    data = json.loads(run('closable', '--dir', repo, '--json').stdout)
    check('closable --json: a "cut" list (before any hold: all four)',
          sorted(e['id'] for e in data['cut']) == ['local_cuta', 'local_cuth', 'local_cutl', 'local_cutn'])
    cut_row = next(e for e in data['cut'] if e['id'] == 'local_cuta')
    check('closable --json: cut entry fields and reasons',
          {'id', 'title', 'idle_s', 'reason', 'since', 'text'} <= set(cut_row) and cut_row['reason'] == 'api'
          and cut_row['text'].startswith("API Error") and len(cut_row['text']) <= 100
          and next(e for e in data['cut'] if e['id'] == 'local_cutl')['reason'] == 'limit'
          and not any(e['id'].startswith('local_cut') for e in data['closable']))
    r = run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_cuth', '--reason', 'regla: espera su rama', '--hours', '1')
    out = run('closable', '--dir', repo).stdout
    check('closable: a held cut session is HOLD, not CUT',
          r.returncode == 0 and 'HOLD local_cuth ' in out and 'CUT local_cuth' not in out)

    def cut_wait(usage):
        pr = subprocess.run([sys.executable, runtime.ENTRY, 'wait', '--dir', repo, '--owner', 'local_sup', '--timeout', '3',
                             '--interval', '0.3', '--all-idle-after', '0'], capture_output=True, text=True,
                            env=dict(env, SUPERVISOR_USAGE=usage))
        return [ln for ln in pr.stdout.splitlines() if ln.startswith('CUT ')]

    check('wait --owner, no usage: only the API cut older than 120 s is announced (not the young one, the limit ones, the held one)',
          cut_wait('no') == ['CUT local_cuta api'])
    check('wait --owner, usage back: the limit cut is announced although it existed before the wait; the API one is not repeated',
          cut_wait('yes') == ['CUT local_cutl limit'])
    check('wait --owner: the same (id, cut time) pair is never announced again', cut_wait('yes') == [])
    cuts_file = glob.glob(os.path.join(lock_home, 'cuts', '*.json'))
    announced = json.load(open(cuts_file[0])) if cuts_file else {}
    check('wait --owner: announced pairs are kept per lock', sorted(k.split('@')[0] for k in announced) == ['local_cuta', 'local_cutl'])
    with open(cuts_file[0], 'w') as fh:   # a pair announced 49 h ago is pruned and, being still cut, announced again
        json.dump({k: time.time() - 49 * 3600 for k in announced}, fh)
    check('wait --owner: pairs older than 48 h are pruned', sorted(cut_wait('yes')) == ['CUT local_cuta api', 'CUT local_cutl limit'])
    r = subprocess.run([sys.executable, runtime.ENTRY, 'wait', '--dir', repo, '--owner', 'local_sup', '--timeout', '3', '--interval', '0.3',
                        '--all-idle-after', '0', '--guard'], capture_output=True, text=True, env=dict(env, SUPERVISOR_USAGE='yes'))
    check('wait --owner --guard: CUT is one of the guard events (already announced pairs stay quiet)',
          'CUT' in watch.GUARD_EVENTS and 'CUT local_cut' not in r.stdout)
    shutil.rmtree(os.path.join(lock_home, 'cuts'), ignore_errors=True)
    r = subprocess.run([sys.executable, runtime.ENTRY, 'wait', '--dir', repo, '--owner', 'local_sup', '--timeout', '3', '--interval', '0.3',
                        '--all-idle-after', '0', '--guard'], capture_output=True, text=True, env=dict(env, SUPERVISOR_USAGE='yes'))
    check('wait --owner --guard: the CUT lines come through the guard filter',
          'CUT local_cutl limit' in r.stdout.splitlines() and 'CUT local_cuta api' in r.stdout.splitlines())
    caches = glob.glob(os.path.join(lock_home, 'closable', '*.json'))
    cache = json.load(open(caches[0]))
    check('wait --owner: the closable cache also holds the resumable, non-held cut sessions (no second census)',
          sorted(e['id'] for e in cache.get('cut', [])) == ['local_cuta', 'local_cutl'] and cache['owner'] == 'local_sup')
    cut_stamp = os.path.join(lock_home, 'closable', os.path.basename(caches[0])[:-5] + '.cutblocked')
    r = hook(stop(background_tasks=[armed_task]))
    reason = json.loads(r.stdout or '{}').get('reason', '')
    check('hook: armed watcher + resumable cut sessions -> block naming all of them, SendMessage, get_usage, hold; no «close it»',
          json.loads(r.stdout or '{}').get('decision') == 'block' and '«Cortada por el límite» (local_cutl)' in reason
          and '«Cortada por la API» (local_cuta)' in reason and 'local_cuth' not in reason and 'local_cutn' not in reason
          and 'SendMessage' in reason and 'get_usage' in reason and 'supervisor-lock hold --session local_sup --target <id>' in reason
          and 'Una sesión cortada no se cierra: no ha terminado.' in reason and 'cierra una sesión terminada' not in reason
          and 'La cuenta tiene uso ahora.' in reason and 'Eres la supervisora de proj' in reason)
    r = hook(stop(background_tasks=[armed_task]))
    check('hook: the cut block comes at most once every 10 min per lock (the closable block has its own stamp)',
          'cortadas por el límite' not in json.loads(r.stdout or '{}').get('reason', ''))
    check('hook: stop_hook_active -> never the cut block',
          (os.remove(cut_stamp) or True) and hook(stop(background_tasks=[armed_task], stop_hook_active=True)).stdout == '')
    write_jsonl(tpath('cli-cutl'), [text_rec(4100), api_rec(4000, 'rate_limit', lim_text), text_rec(10, 'user')], age=10)  # resumed
    reason = json.loads(hook(stop(background_tasks=[armed_task])).stdout or '{}').get('reason', '')
    check('hook: a cut session resumed since the cache was written is skipped', '(local_cuta)' in reason and 'local_cutl' not in reason)
    os.remove(cut_stamp)
    run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_cuta', '--reason', 'regla Y')
    reason = json.loads(hook(stop(background_tasks=[armed_task])).stdout or '{}').get('reason', '')
    check('hook: a held cut session is skipped; nothing left -> no cut block', 'cortadas' not in reason)
    if os.path.exists(cut_stamp):
        os.remove(cut_stamp)
    put(app_dir, 'local_cuta.json', dict(json.load(open(os.path.join(app_dir, 'local_cuta.json'))), isArchived=True))
    run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_cuta', '--clear')
    check('hook: an archived cut session is skipped',
          'cortadas' not in json.loads(hook(stop(background_tasks=[armed_task])).stdout or '{}').get('reason', ''))
    with open(caches[0], 'w') as fh:
        json.dump(dict(cache, owner='local_old'), fh)
    check('hook: a cut list written by a previous owner\'s watcher never blocks',
          'cortadas' not in json.loads(hook(stop(background_tasks=[armed_task])).stdout or '{}').get('reason', ''))
    for sid, cli_id, *_ in cut_specs:
        os.remove(os.path.join(app_dir, sid + '.json'))
        os.remove(os.path.join(sessions_dir, cli_id + '.json'))
        os.remove(tpath(cli_id))
    for name in ('cuts',):
        shutil.rmtree(os.path.join(lock_home, name), ignore_errors=True)
    for stamp in glob.glob(os.path.join(lock_home, 'closable', '*.*blocked')):
        os.remove(stamp)

    # 7a2b. the developer's own messages: the Stop hook quotes each
    # message the developer typed in the supervisor's session once, before the cut and closable blocks; SessionStart/compact
    # repeats them word for word
    def human_rec(ago, text, origin=True, meta=False):
        rec = {'type': 'user', 'timestamp': iso(ago), 'uuid': f'u-{ago}', 'message': {'role': 'user', 'content': text}}
        if origin:
            rec['origin'] = {'kind': 'human'}
        if meta:
            rec['isMeta'] = True
        return rec

    dev_path = os.path.join(tmp, 'dev-transcript.jsonl')
    write_jsonl(dev_path, [
        human_rec(9 * 3600, 'un mensaje de hace nueve horas'),
        human_rec(400, 'hay varias pestañas abiertas sin terminar'),
        dict(human_rec(380, '<task-notification> <task-id>x</task-id>'), origin={'kind': 'task-notification'}),
        dict(human_rec(360, 'Another Claude session sent a message: <cross-session-message from="local_x">hola</cross-session-message>'),
             origin={'kind': 'peer', 'from': 'local_x'}),
        human_rec(340, 'continúa'),
        human_rec(330, '<command-name>/model</command-name>'),
        human_rec(320, 'Stop hook feedback: arma el vigilante', origin=False, meta=True),
        human_rec(300, '<system-reminder>contexto de la app</system-reminder>\n¿qué espera cada pestaña?', origin=False),
        text_rec(200)])
    dev_stamp_dir = os.path.join(lock_home, 'answered')
    shutil.rmtree(dev_stamp_dir, ignore_errors=True)
    for stamp in glob.glob(os.path.join(lock_home, 'closable', '*.*blocked')):
        os.remove(stamp)
    reason = json.loads(hook(stop(background_tasks=[armed_task], transcript_path=dev_path)).stdout or '{}').get('reason', '')
    check('hook: the developer\'s messages typed in its session are quoted at the turn end, newest last, with what to do',
          '«hay varias pestañas abiertas sin terminar»' in reason and '«¿qué espera cada pestaña?»' in reason
          and reason.find('pestañas abiertas') < reason.find('qué espera') and 'no otra cosa' in reason
          and 'es una orden ignorada' in reason)
    check('hook: notifications, other sessions, «continúa», slash commands, hook feedback and old messages are not the developer\'s questions',
          not any(x in reason for x in ('task-notification', 'cross-session', 'continúa', '/model', 'arma el vigilante', 'nueve horas')))
    reason = json.loads(hook(stop(background_tasks=[armed_task], transcript_path=dev_path)).stdout or '{}').get('reason', '')
    check('hook: each of the developer\'s messages is quoted once', 'te ha escrito' not in reason)
    with open(dev_path, 'a') as fh:
        fh.write(json.dumps(human_rec(10, 'atiende las pestañas')) + '\n')
    reason = json.loads(hook(stop(background_tasks=[armed_task], transcript_path=dev_path)).stdout or '{}').get('reason', '')
    check('hook: a new message of the developer\'s is quoted alone', '«atiende las pestañas»' in reason and 'sin terminar' not in reason)
    check('hook: stop_hook_active -> never the developer\'s block', hook(stop(background_tasks=[armed_task], transcript_path=dev_path,
                                                                 stop_hook_active=True)).stdout == '')
    ctx = json.loads(hook({'hook_event_name': 'SessionStart', 'source': 'compact', 'session_id': 'cli-sup',
                           'transcript_path': dev_path}).stdout or '{}').get('hookSpecificOutput', {}).get('additionalContext', '')
    check('hook: SessionStart/compact repeats the developer\'s recent messages word for word',
          'literales por si el resumen los ha perdido' in ctx and '«atiende las pestañas»' in ctx and 'nueve horas' not in ctx)
    shutil.rmtree(dev_stamp_dir, ignore_errors=True)
    for stamp in glob.glob(os.path.join(lock_home, 'closable', '*.*blocked')):
        os.remove(stamp)

    # 7a3. «Sí, puedes cerrar»: the /cierra-sesion verdict makes a session closable at
    # once, whatever its idle time; no hold parks it; `hold` refuses it and any Remote Control reason; `wait --owner`
    # announces it once even when it was given before the wait; the Stop hook asks to archive it first
    def verdict_rec(ago, text):
        return {'type': 'assistant', 'timestamp': iso(ago), 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}

    def user_text(ago, text):
        return {'type': 'user', 'timestamp': iso(ago), 'message': {'role': 'user', 'content': text}}

    verdict_specs = (('local_vok', 'cli-vok', 'Veredicto dado', [verdict_rec(100, '**Sí, puedes cerrar.** Todo publicado.')]),
                     ('local_vwr', 'cli-vwr', 'Le escribieron después', [verdict_rec(100, 'Sí, puedes cerrar.'), user_text(50, 'una cosa más')]),
                     ('local_vno', 'cli-vno', 'Aún no', [verdict_rec(100, 'No, todavía no puedes cerrar: falta el push.')]))
    for sid, cli_id, title, recs_ in verdict_specs:
        put(app_dir, sid + '.json', {'sessionId': sid, 'cliSessionId': cli_id, 'cwd': repo, 'title': title, 'lastActivityAt': ms - 300 * 1000})
        put(sessions_dir, cli_id + '.json', {'pid': quiet_cli.pid, 'cwd': repo, 'sessionId': cli_id, 'hostSessionId': sid,
                                          'status': 'idle', 'updatedAt': ms - 300 * 1000})
        write_jsonl(tpath(cli_id), [tool_rec(200, 'mcp__ccd_turn__wrap_up', 'w-' + cli_id), result_rec(150, 'w-' + cli_id)] + list(recs_), age=50)
    out = run('closable', '--dir', repo).stdout
    check('closable: «Sí, puedes cerrar» as the last message -> CLOSABLE at once (5 min idle); not if someone wrote after it, not for «No…»',
          re.search(r'^CLOSABLE local_vok dijo «Sí, puedes cerrar» ', out, re.M) is not None
          and 'local_vwr' not in out and 'local_vno' not in out)
    r = run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_vok', '--reason', 'regla X')
    check('hold: refused (exit 2) for a session that already said «Sí, puedes cerrar»',
          r.returncode == 2 and 'ya contestó «Sí, puedes cerrar»' in r.stderr)
    r = run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_vno', '--reason', 'Remote Control activo; se queda encendido')
    check('hold: a Remote Control reason is refused (exit 2) for any session', r.returncode == 2 and 'Remote Control no es motivo' in r.stderr)
    hold_files = glob.glob(os.path.join(lock_home, 'holds', '*.json'))
    hold_data = json.load(open(hold_files[0])) if hold_files else {}
    hold_data['local_vok'] = {'reason': 'puesto antes del veredicto', 'by': 'local_sup', 'until_epoch': time.time() + 3600, 'until': 'x'}
    with open(hold_files[0] if hold_files else os.path.join(lock_home, 'holds', 'x.json'), 'w') as fh:
        json.dump(hold_data, fh)
    out = run('closable', '--dir', repo).stdout
    check('closable: a hold set before the verdict does not park it', 'CLOSABLE local_vok dijo' in out and 'HOLD local_vok' not in out)

    def verdict_wait(*extra):
        pr = subprocess.run([sys.executable, runtime.ENTRY, 'wait', '--dir', repo, '--owner', 'local_sup', '--timeout', '3',
                             '--interval', '0.3', '--all-idle-after', '0', *extra], capture_output=True, text=True, env=dict(env, SUPERVISOR_USAGE='no'))
        return [ln for ln in pr.stdout.splitlines() if ln.startswith('CLOSABLE ')]

    check('wait --owner: a verdict given before the wait is announced at once as CLOSABLE <id> cierre-ok', verdict_wait() == ['CLOSABLE local_vok cierre-ok'])
    check('wait --owner: the same verdict is not announced twice', verdict_wait() == [])
    shutil.rmtree(os.path.join(lock_home, 'verdicts'), ignore_errors=True)
    check('wait --owner --guard: the verdict comes through the guard filter', 'CLOSABLE local_vok cierre-ok' in verdict_wait('--guard'))
    for stamp in glob.glob(os.path.join(lock_home, 'closable', '*.*blocked')):
        os.remove(stamp)
    reason = json.loads(hook(stop(background_tasks=[armed_task])).stdout or '{}').get('reason', '')
    check('hook: the session that said «Sí, puedes cerrar» is asked first: archive it now, no new /cierra-sesion, no hold, Remote Control is no reason',
          '«Veredicto dado» (local_vok)' in reason and 'ya contestó «Sí, puedes cerrar»' in reason and 'archive_session' in reason
          and 'no le mandes otro /cierra-sesion ni la aparques' in reason and 'Remote Control activo no es motivo' in reason)
    # the default policy: archiving is not authorised, so the block asks to queue the decision and park the session,
    # `hold` accepts that, and the next turn end is free: the supervisor is never asked for what it may not do
    if default_cfg is None:
        env.pop('CLAUDE_TOOLKIT_CONFIG_DIR', None)
    else:
        env['CLAUDE_TOOLKIT_CONFIG_DIR'] = default_cfg
    for stamp in glob.glob(os.path.join(lock_home, 'closable', '*.*blocked')):
        os.remove(stamp)
    reason = json.loads(hook(stop(background_tasks=[armed_task])).stdout or '{}').get('reason', '')
    check('hook (default policy): a session that said «Sí, puedes cerrar» is not archived: the block asks to queue the '
          'decision in ask-queue and park it, never archive_session',
          '«Veredicto dado» (local_vok)' in reason and 'no la archives' in reason and 'ask-queue add' in reason
          and 'hold --session local_sup --target local_vok --reason "ask-queue' in reason
          and 'archive_session' not in reason and 'Archívala ahora' not in reason)
    r = run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_vok', '--reason', 'regla X')
    check('hold (default policy): a session with the verdict is parked only with its decision queued (exit 2 otherwise)',
          r.returncode == 2 and 'ask-queue' in r.stderr)
    r = run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_vok', '--reason',
            'ask-queue q-1: espera autorización', '--hours', '1')
    out = run('closable', '--dir', repo).stdout
    check('hold (default policy): with the decision queued the session is parked (HELD, listed as HOLD, not CLOSABLE)',
          r.returncode == 0 and r.stdout.startswith('HELD local_vok') and 'CLOSABLE local_vok' not in out)
    for stamp in glob.glob(os.path.join(lock_home, 'closable', '*.*blocked')):
        os.remove(stamp)
    again = json.loads(hook(stop(background_tasks=[armed_task])).stdout or '{}').get('reason', '')
    check('hook (default policy): once the decision is queued the turn may end: no block names that session again',
          '(local_vok)' not in again)
    run('hold', '--dir', repo, '--session', 'local_sup', '--target', 'local_vok', '--clear')
    hold_data = json.load(open(hold_files[0])) if hold_files else {}
    hold_data.pop('local_vok', None)
    with open(hold_files[0] if hold_files else os.path.join(lock_home, 'holds', 'x.json'), 'w') as fh:
        json.dump(hold_data, fh)
    for sid, cli_id, *_ in verdict_specs:
        os.remove(os.path.join(app_dir, sid + '.json'))
        os.remove(os.path.join(sessions_dir, cli_id + '.json'))
        os.remove(tpath(cli_id))
    shutil.rmtree(os.path.join(lock_home, 'verdicts'), ignore_errors=True)
    for stamp in glob.glob(os.path.join(lock_home, 'closable', '*.*blocked')):
        os.remove(stamp)

    # account_has_usage(): only through account-switch, only for the app's organization, cached 120 s, overridable
    fake_acct = os.path.join(tmp, 'fake-account-switch')
    fake_state = os.path.join(tmp, 'fake-usage.json')
    with open(fake_acct, 'w') as fh:
        fh.write('import json, os\nSTATE = "x"\n_f = lambda: json.load(open(os.environ["FAKE_USAGE"]))\n'
                 'def load(path, default):\n    return {"org": _f()["app_org"]}\n'
                 'def cli_org():\n    return _f()["cli_org"]\n'
                 'def usage():\n    return _f().get("usage")\n'
                 'def usage_limit(data):\n    return None if data.get("ok") else {"until": 1, "what": "five_hour"}\n')
    saved_env = {k: os.environ.get(k) for k in ('SUPERVISOR_LOCK_HOME', 'SUPERVISOR_ACCOUNT_SWITCH', 'FAKE_USAGE', 'SUPERVISOR_USAGE')}
    os.environ.update(SUPERVISOR_LOCK_HOME=lock_home, SUPERVISOR_ACCOUNT_SWITCH=fake_acct, FAKE_USAGE=fake_state)
    os.environ.pop('SUPERVISOR_USAGE', None)
    usage_cache = os.path.join(lock_home, 'usage-cache.json')

    def usage_is(app_org='o', cli_org='o', usage=None, fresh=True):
        if fresh and os.path.exists(usage_cache):
            os.remove(usage_cache)
        with open(fake_state, 'w') as fh:
            json.dump({'app_org': app_org, 'cli_org': cli_org, 'usage': usage}, fh)
        return providers.account_has_usage()

    try:
        got = [usage_is(usage={'ok': True}), usage_is(usage={'ok': False}), usage_is(cli_org='other', usage={'ok': True}),
               usage_is(usage=None)]
        check('account_has_usage: True with no limit, False with one, None for another organization or without an answer',
              got == [True, False, None, None])
        usage_is(usage={'ok': True})
        check('account_has_usage: the answer is cached for 120 s (a changed fake is not asked again)',
              usage_is(usage={'ok': False}, fresh=False) is True and json.load(open(usage_cache))['has_usage'] is True)
        with open(usage_cache, 'w') as fh:
            json.dump({'time': time.time() - 130, 'has_usage': True}, fh)
        check('account_has_usage: an older cache is asked again', usage_is(usage={'ok': False}, fresh=False) is False)
        os.environ['SUPERVISOR_USAGE'] = 'yes'
        forced = [providers.account_has_usage()]
        os.environ['SUPERVISOR_USAGE'] = 'no'
        forced.append(providers.account_has_usage())
        os.environ['SUPERVISOR_USAGE'] = 'unknown'
        forced.append(providers.account_has_usage())
        check('account_has_usage: SUPERVISOR_USAGE=yes|no|unknown overrides it', forced == [True, False, None])
        os.environ.pop('SUPERVISOR_USAGE')
        os.environ['SUPERVISOR_ACCOUNT_SWITCH'] = os.path.join(tmp, 'does-not-exist')
        os.remove(usage_cache)
        check('account_has_usage: a missing account-switch is None, not an exception', providers.account_has_usage() is None)
    finally:
        for k, v in saved_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        if os.path.exists(usage_cache):
            os.remove(usage_cache)
    os.killpg(fake_cli.pid, signal.SIGKILL)
    for proc in (fake_cli, quiet_cli):
        proc.kill()
        proc.wait()
    # the fake Bash-tool child lives in fake_cli's own process group (start_new_session), killed with it
    for name in ('local_fin', 'local_box', 'local_young', 'local_bg', 'local_oi'):
        os.remove(os.path.join(app_dir, name + '.json'))
    for name in ('cli-young', 'cli-bg', 'cli-oi'):
        os.remove(os.path.join(sessions_dir, name + '.json'))
    shutil.rmtree(os.path.join(lock_home, 'holds'), ignore_errors=True)
    shutil.rmtree(os.path.join(lock_home, 'closable'), ignore_errors=True)

    r = hook(stop(background_tasks=[]))
    out = json.loads(r.stdout or '{}')
    reason = out.get('reason', '')
    check('hook: Stop with no task -> block with the Spanish reason',
          r.returncode == 0 and out.get('decision') == 'block' and 'supervisor de proj (cerrojo ' in reason and 'fase F2, ronda 5)' in reason
          and '~/.claude/scripts/supervisor-lock wait --owner local_sup --timeout 600' in reason
          and '~/.claude/scripts/supervisor-lock release --session local_sup --verdict <VEREDICTO>' in reason)
    check('hook: another owner\'s or a finished task does not count',
          all(json.loads(hook(stop(background_tasks=[t])).stdout or '{}').get('decision') == 'block'
              for t in (dict(armed_task, command=armed_task['command'].replace('local_sup', 'local_oth')), dict(armed_task, status='completed'),
                        dict(armed_task, command='sleep 5', description='sleep'))))
    check('hook: description alone can match, status pending counts',
          hook(stop(background_tasks=[{'id': 'b2', 'type': 'monitor', 'status': 'pending', 'description': 'supervisor-lock wait --owner local_sup'}])).stdout == '')
    fake_wait = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'supervisor-lock', 'wait', '--owner', 'local_sup'])
    fake_other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'supervisor-lock', 'wait', '--owner', 'local_oth'])
    time.sleep(0.3)
    r = hook(stop())
    fallback_armed = r.stdout == ''
    fake_wait.kill()
    fake_wait.wait()
    fake_excl = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'supervisor-lock', 'wait', '--exclude', 'local_sup'])
    fake_excl2 = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'supervisor-lock', 'wait', '--exclude=local_sup'])
    time.sleep(0.3)
    excl_armed = hook(stop()).stdout == ''
    fake_excl.kill()
    fake_excl.wait()
    excl2_armed = hook(stop()).stdout == ''  # the `--exclude=ID` one is still running
    fake_excl2.kill()
    fake_excl2.wait()
    check('hook: /proc fallback also accepts `wait --exclude ID` and `--exclude=ID`', excl_armed and excl2_armed)
    r = hook(stop())
    fake_other.kill()
    fake_other.wait()
    check('hook: no background_tasks -> /proc fallback (armed, then not armed once the process is gone)',
          fallback_armed and json.loads(r.stdout or '{}').get('decision') == 'block')
    r = hook(stop(stop_hook_active=True))
    check('hook: second Stop is not blocked again, notifies once and logs',
          r.returncode == 0 and r.stdout == '' and open(notify_log).read().count('Supervisión sin vigilante: proj|') == 1
          and 'local_sup' in open(os.path.join(lock_home, 'hook.log')).read())
    r = hook(stop(stop_hook_active=True, background_tasks=[armed_task]))
    check('hook: armed + stop_hook_active -> no extra notification', r.stdout == '' and open(notify_log).read().count('Supervisión sin vigilante') == 1)
    for source in ('startup', 'resume', 'clear', 'compact'):
        r = hook({'hook_event_name': 'SessionStart', 'source': source, 'session_id': 'cli-sup'})
        ctx = json.loads(r.stdout or '{}').get('hookSpecificOutput', {})
        check(f'hook: SessionStart/{source} adds the re-arm context',
              ctx.get('hookEventName') == 'SessionStart' and 'supervisora de proj (cerrojo ' in ctx.get('additionalContext', '')
              and 'fase F2, ronda 5, último latido hace 0 min)' in ctx['additionalContext'] and 'supervisa-sesiones' in ctx['additionalContext']
              and 'supervisor-lock wait --owner local_sup' in ctx['additionalContext']
              and ctx['additionalContext'].endswith('Del registro, lee solo las secciones de estado, nunca el fichero entero.'))
        text = ctx.get('additionalContext', '')
        if source == 'compact':
            check('hook: SessionStart/compact keeps the skill core (no re-invoke), points at the reference files',
                  'no la vuelvas a invocar' in text and 'vuelve a invocar la skill' not in text and 'El contexto se ha compactado' in text
                  and 'lee solo su fichero de referencia' in text)
        else:
            check(f'hook: SessionStart/{source} tells it to re-invoke the skill', 'vuelve a invocar la skill' in text and 'no la vuelvas' not in text)
    os.remove(os.path.join(sessions_dir, 'sup.json'))
    put(app_dir, 'local_sup.json', {'sessionId': 'local_sup', 'cliSessionId': 'cli-sup', 'cwd': repo, 'title': 'sup'})
    check('hook: id mapped through the app record when the CLI record is gone',
          json.loads(hook(stop(background_tasks=[])).stdout or '{}').get('decision') == 'block')
    # speed: 3 locks + 400 app records (some 200 KB) must not be scanned for a session that owns nothing
    for n in range(2):
        put_lock(f'k-speed{n}', f'local_speed{n}', 10)
    big_dir = os.path.join(tmp, 'app', 'big', 'dir')
    os.makedirs(big_dir)
    for n in range(400):
        put(big_dir, f'local_fake{n}.json', {'sessionId': f'local_fake{n}', 'cliSessionId': f'cli-fake{n}', 'cwd': repo,
                                              'pad': 'x' * (200000 if n % 8 == 0 else 500)})
    saved = {k: os.environ.get(k) for k in env if k.startswith(('SUPERVISOR_', 'ASK_GATE'))}
    os.environ.update({k: v for k, v in env.items() if k.startswith(('SUPERVISOR_', 'ASK_GATE'))})
    began = time.perf_counter()
    speedy = hook_mod.hook_decide(json.dumps(stop(session_id='cli-not-an-owner', background_tasks=[])))
    took = time.perf_counter() - began
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    check(f'hook: 3 locks + 400 app records, non-owner session -> \'\' in {took:.2f} s (< 0.3)', speedy == '' and took < 0.3)
    check('hook: the owner is still found through its own app record among 400', json.loads(hook(stop(background_tasks=[])).stdout or '{}').get('decision') == 'block')
    empty_env = dict(env, SUPERVISOR_LOCK_HOME=os.path.join(tmp, 'no-locks-here'))
    r = hook(stop(), hook_env=empty_env)
    check('hook: no locks at all -> fast path, empty output', r.returncode == 0 and r.stdout == '')
    errors_log = os.path.join(lock_home, 'hook-errors.log')
    for raw in ('not json{', '', '[1, 2]'):
        r = hook(None, raw=raw)
        check(f'hook: malformed stdin {raw!r} -> empty output, exit 0', r.returncode == 0 and r.stdout == '')
    check('hook: failures are logged with a traceback', os.path.exists(errors_log) and open(errors_log).read().count('Traceback') == 3)
    gate = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(runtime.ENTRY))), 'hooks', 'supervisor-stop-gate')
    if os.path.exists(gate) and os.path.realpath(os.path.expanduser('~/.claude/scripts/supervisor-lock')) == os.path.realpath(runtime.ENTRY):
        r = subprocess.run([gate], input=json.dumps(stop(background_tasks=[])), capture_output=True, text=True, env=env)
        check('supervisor-stop-gate: passes stdin through to the hook, exit 0',
              r.returncode == 0 and json.loads(r.stdout or '{}').get('decision') == 'block')
        r = subprocess.run([gate], input='{}', capture_output=True, text=True, env=dict(env, HOME=os.path.join(tmp, 'nohome')))
        check('supervisor-stop-gate: missing script -> silent, exit 0', r.returncode == 0 and r.stdout == '')

    # 8. workspace mode: a non-git folder that groups repos
    def clear_locks():
        for name in os.listdir(os.path.join(lock_home, 'locks')):
            os.remove(os.path.join(lock_home, 'locks', name))

    def clear_sessions():
        for directory in (sessions_dir, app_dir):
            for name in os.listdir(directory):
                os.remove(os.path.join(directory, name))

    clear_locks()
    clear_sessions()
    ws = os.path.realpath(os.path.join(tmp, 'ws'))
    os.makedirs(os.path.join(ws, 'notes'))
    open(os.path.join(ws, 'CLAUDE.md'), 'w').write('workspace\n')
    ws_a, ws_b = os.path.join(ws, 'a'), os.path.join(ws, 'b')
    make_repo(ws_a)
    make_repo(ws_b)
    ws_wt = os.path.join(tmp, 'ws-a-wt')  # a worktree of a nested repo, living outside the workspace
    sh('git', 'worktree', 'add', '-q', '-b', 'wsb', ws_wt, cwd=ws_a)
    ws_wt = os.path.realpath(ws_wt)
    ws_extra = os.path.join(tmp, 'ws-extra')  # shares the textual prefix of the root, is not inside it
    os.makedirs(ws_extra)
    pw = json.loads(run('project', '--dir', ws, '--json').stdout or '{}')
    check('workspace: project kind/key/checkout/registry, no common dir',
          pw.get('kind') == 'workspace' and re.fullmatch(r'ws-[0-9a-f]{8}', pw.get('key', '')) is not None and pw.get('name') == 'ws'
          and pw.get('checkout') == ws and pw.get('common_dir') is None
          and pw.get('registry_dir') == os.path.join(ws, '.claude', 'context', 'supervisor'))
    check('workspace: key = <name>-sha1(realpath)[:8]', pw.get('key') == 'ws-' + hashlib.sha1(ws.encode()).hexdigest()[:8])
    check('workspace: a plain subfolder of a workspace is not a project by itself (exit 2)',
          run('project', '--dir', os.path.join(ws, 'notes')).returncode == 2)
    check('workspace: a nested git repo is a git project of its own', json.loads(run('project', '--dir', ws_a, '--json').stdout or '{}').get('kind') == 'git')
    check('project: git projects report kind=git, text output shows kind',
          p1.get('kind') == 'git' and 'kind=git' in run('project', '--dir', repo).stdout and 'kind=workspace' in run('project', '--dir', ws).stdout
          and 'common_dir=-' in run('project', '--dir', ws).stdout)
    r = run('project', '--dir', ws_extra)
    check('workspace: a plain dir without markers -> exit 2 (NOT A GIT REPOSITORY)', r.returncode == 2 and 'NOT A GIT REPOSITORY' in r.stderr)
    mark_dirs = {}
    for label, make in (('openspec/', lambda d: os.makedirs(os.path.join(d, 'openspec'))),
                        ('a subfolder with .git', lambda d: os.makedirs(os.path.join(d, 'sub', '.git')))):
        mark_dirs[label] = os.path.join(tmp, 'mark-' + re.sub(r'\W', '', label))
        os.makedirs(mark_dirs[label])
        make(mark_dirs[label])
    check('workspace: openspec/ or a subfolder with .git are markers too',
          all(json.loads(run('project', '--dir', d, '--json').stdout or '{}').get('kind') == 'workspace' for d in mark_dirs.values()))
    fake_home = os.path.join(tmp, 'up', 'home')
    os.makedirs(fake_home)
    for d in (fake_home, os.path.dirname(fake_home)):
        open(os.path.join(d, 'CLAUDE.md'), 'w').write('x\n')
    check('workspace: the same folders are accepted when HOME is elsewhere',
          all(run('project', '--dir', d).returncode == 0 for d in (fake_home, os.path.dirname(fake_home))))
    home_env = dict(env, HOME=fake_home)
    check('workspace: $HOME and an ancestor of $HOME -> exit 2 even with CLAUDE.md',
          all(subprocess.run([sys.executable, runtime.ENTRY, 'project', '--dir', d], capture_output=True, text=True, env=home_env).returncode == 2
              for d in (fake_home, os.path.dirname(fake_home))))
    r = run('registry-dir', '--dir', ws)
    check('registry-dir: workspace -> only mkdir, stderr note, no git exclude',
          r.returncode == 0 and r.stdout.strip() == pw['registry_dir'] and os.path.isdir(pw['registry_dir'])
          and 'workspace' in r.stderr and not os.path.exists(os.path.join(ws, '.git')))
    cli('local_ws_root', sessionId='cli-wsr', cwd=ws)
    cli('local_ws_nested', sessionId='cli-wsn', cwd=ws_a)
    cli('local_ws_outside', sessionId='cli-wso', cwd=ws_wt)
    cli('local_ws_sub', sessionId='cli-wss', cwd=os.path.join(ws, 'notes'))
    cli('local_ws_unrelated', sessionId='cli-wsu', cwd=other)
    cli('local_ws_prefix', sessionId='cli-wsp', cwd=ws_extra)
    wrows = json.loads(run('sessions', '--dir', ws, '--json').stdout or '[]')
    check('workspace sessions: root, nested repo, outside worktree of a nested repo and a subfolder; not a foreign repo or a prefix sibling',
          {x['id'] for x in wrows} == {'local_ws_root', 'local_ws_nested', 'local_ws_outside', 'local_ws_sub'})
    check('git sessions of a nested repo: its worktree too, not the workspace root',
          {x['id'] for x in json.loads(run('sessions', '--dir', ws_a, '--json').stdout or '[]')} == {'local_ws_nested', 'local_ws_outside'})
    run('acquire', '--dir', ws, '--session', 'local_wsup', '--title', 'ws sup')
    cli('local_ws_root', sessionId='cli-wsr', cwd=ws, status='busy')
    r = run('release', '--dir', ws_a, '--session', 'local_wsup')
    check('workspace: a git project of a nested repo has its own lock (not the owner here)', r.returncode == 0 and r.stdout.startswith('ALREADY FREE '))
    r = run('release', '--dir', ws, '--session', 'local_wsup')
    check('workspace: release refuses (exit 6, OPEN WORK) while a session of the workspace is busy',
          r.returncode == 6 and 'OPEN WORK local_ws_root status=busy' in r.stdout and os.path.exists(os.path.join(lock_home, 'locks', pw['key'] + '.json')))
    cli('local_ws_root', sessionId='cli-wsr', cwd=ws, status='idle')
    r = run('release', '--dir', ws, '--session', 'local_wsup', '--verdict', 'OK')
    check('workspace: release refuses (exit 6, OPEN lines) while idle sessions of the workspace are still open',
          r.returncode == 6 and {ln.split(' ')[1] for ln in r.stdout.splitlines()} == {'local_ws_root', 'local_ws_nested', 'local_ws_outside', 'local_ws_sub'}
          and os.path.exists(os.path.join(lock_home, 'locks', pw['key'] + '.json')))
    for sid in ('local_ws_root', 'local_ws_nested', 'local_ws_outside', 'local_ws_sub'):
        os.remove(os.path.join(sessions_dir, sid + '.json'))
    r = run('release', '--dir', ws, '--session', 'local_wsup', '--verdict', 'OK')
    check('workspace: release works once nothing is busy or open', r.returncode == 0 and r.stdout.startswith('RELEASED '))
    sh('git', 'branch', 'refw', cwd=ws_a)
    old_w = subprocess.run(['git', '-C', ws_a, 'rev-parse', 'refw'], capture_output=True, text=True, env=env).stdout.strip()
    pr = subprocess.Popen([sys.executable, runtime.ENTRY, 'wait', '--dir', ws, '--interval', '0.2', '--timeout', '8', '--all-idle-after', '0',
                           '--refs', 'a:refw,refw,b:nope'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    time.sleep(1.0)
    sh('git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'c3', cwd=ws_a)
    sh('git', 'branch', '-f', 'refw', 'HEAD', cwd=ws_a)
    code, lines = finish(pr)
    new_w = subprocess.run(['git', '-C', ws_a, 'rev-parse', 'refw'], capture_output=True, text=True, env=env).stdout.strip()
    check('wait --refs: workspace accepts <subdir>:<branch> (a plain name or a missing branch stays silent)',
          code == 0 and lines == [f'REF a:refw {old_w[:8]}->{new_w[:8]}'] and old_w != new_w)

    # 9. mailbox and skill_seen live in the lock
    clear_locks()
    clear_sessions()
    t0 = time.time() - 5000
    os.utime(skill, (t0, t0))
    run('acquire', '--dir', repo, '--session', 'local_mb', '--title', 'mb')
    check('acquire: leaves skill_seen unset (taking the lock is not reading the skill)', 'skill_seen' not in load() and 'mailbox' not in load())
    before = time.time()
    run('beat', '--dir', repo, '--session', 'local_mb', '--skill-seen')
    after = time.time()
    check('beat --skill-seen right after acquire: stores the skill file mtime', load().get('skill_seen') == t0)
    check('beat --skill-seen: also stores when the skill was read (skill_seen_at), which the message gate compares with',
          before <= (load().get('skill_seen_at') or 0) <= after)
    check('status: no mailbox= while unset', 'mailbox=' not in run('status', '--dir', repo).stdout)
    r = run('beat', '--dir', repo, '--session', 'local_mb', '--mailbox', 'local_box')
    check('beat --mailbox: stores the mailbox, state untouched', r.returncode == 0 and load().get('mailbox') == 'local_box' and load()['state'] == 'running')
    check('status / list / json show mailbox=', 'mailbox=local_box' in run('status', '--dir', repo).stdout
          and 'mailbox=local_box' in run('list').stdout and json.loads(run('status', '--dir', repo, '--json').stdout).get('mailbox') == 'local_box')
    t1 = t0 + 3000
    os.utime(skill, (t1, t1))
    run('beat', '--dir', repo, '--session', 'local_mb', '--phase', 'F3')
    check('beat without --skill-seen leaves skill_seen and mailbox alone', load().get('skill_seen') == t0 and load().get('mailbox') == 'local_box')
    r = run('beat', '--dir', repo, '--session', 'local_mb', '--skill-seen')
    check('beat --skill-seen: stores the current mtime', r.returncode == 0 and load().get('skill_seen') == os.stat(skill).st_mtime and load().get('skill_seen') != t0)
    missing_env = dict(env, SUPERVISOR_SKILL_FILE=os.path.join(tmp, 'no-skill.md'))
    r = subprocess.run([sys.executable, runtime.ENTRY, 'acquire', '--dir', other, '--session', 'local_nosk'], capture_output=True, text=True, env=missing_env)
    other_lock = os.path.join(lock_home, 'locks', json.loads(run('project', '--dir', other, '--json').stdout)['key'] + '.json')
    r2 = subprocess.run([sys.executable, runtime.ENTRY, 'beat', '--dir', other, '--session', 'local_nosk', '--skill-seen'], capture_output=True, text=True, env=missing_env)
    check('skill file missing: acquire and beat --skill-seen skip it silently',
          r.returncode == 0 and r2.returncode == 0 and r2.stderr == '' and 'skill_seen' not in json.load(open(other_lock)))
    os.utime(skill, (t0 + 100, t0 + 100))
    shift = json.load(open(other_lock))
    shift['heartbeat'] = hb_ago(9000)
    put(os.path.join(lock_home, 'locks'), os.path.basename(other_lock), shift)
    run('reclaim', '--dir', other, '--session', 'local_recl', '--from', 'local_nosk')
    check('reclaim: leaves skill_seen unset too', json.load(open(other_lock)).get('session_id') == 'local_recl' and 'skill_seen' not in json.load(open(other_lock)))
    os.utime(skill, (t1, t1))

    # 9b. beat --skill-seen needs proof: a load of the skill in the session's own transcript after the newest update
    # (the skill, a global rule or the supervisor-lock code). The marker is what the message gate and the Stop hook
    # trust, so a supervisor that only runs the beat must not get it.
    clear_locks()
    clear_sessions()
    reload_dir = os.path.join(tmp, 'reload-watch')
    os.makedirs(reload_dir, exist_ok=True)
    t0 = time.time() - 5000
    os.utime(skill, (t0, t0))
    run('acquire', '--dir', repo, '--session', 'local_pf', '--title', 'pf')
    put(app_dir, 'local_pf.json', {'sessionId': 'local_pf', 'cliSessionId': 'cli-pf', 'cwd': repo, 'title': 'pf'})
    hook_log_path = os.path.join(lock_home, 'hook.log')

    def skill_use(ago, tid, name='supervisa-sesiones', side=False):
        return {'type': 'assistant', 'timestamp': iso(ago), 'isSidechain': side, 'message': {'role': 'assistant', 'content': [
            {'type': 'tool_use', 'name': 'Skill', 'id': tid, 'input': {'skill': name, 'args': 'recarga'}}]}}

    def skill_result(ago, tid, error=False):
        item = {'type': 'tool_result', 'tool_use_id': tid, 'content': 'Launching skill: supervisa-sesiones'}
        if error:
            item.update(is_error=True, content='denied')
        return {'type': 'user', 'timestamp': iso(ago), 'message': {'role': 'user', 'content': [item]}}

    def command_rec(ago, text=None):
        body = text or ('<command-message>supervisa-sesiones</command-message>\n<command-name>/supervisa-sesiones'
                        '</command-name>\n<command-args></command-args>')
        return {'type': 'user', 'timestamp': iso(ago), 'message': {'role': 'user', 'content': body}}

    def pf_beat(records, *extra, cli_id='cli-pf', beat_env=None):
        if records is not None:
            write_jsonl(tpath(cli_id), records)
        return subprocess.run([sys.executable, runtime.ENTRY, 'beat', '--dir', repo, '--session', 'local_pf', '--skill-seen', *extra],
                              capture_output=True, text=True, env=beat_env or env)

    def forget():
        data = load()
        for key in ('skill_seen', 'skill_seen_at', 'skill_seen_proof'):
            data.pop(key, None)
        save(data)

    def refused(r):
        return r.returncode == 8 and 'SKILL SEEN REFUSED' in r.stderr and 'skill_seen' not in load()

    r = pf_beat([text_rec(300), tool_rec(200, 'Bash', 'b1'), result_rec(190, 'b1')], '--phase', 'F3', '--round', '7')
    check('skill-seen proof: a beat with no Skill call in the transcript is refused (exit 8), skill_seen stays unset',
          refused(r) and 'BEAT' not in r.stdout)
    check('skill-seen proof: the refusal says in Spanish to invoke the skill with the Skill tool and repeat the beat',
          'herramienta Skill' in r.stderr and 'supervisor-lock beat --session local_pf --skill-seen' in r.stderr
          and 'Ejecutar beat --skill-seen no la carga' in r.stderr)
    check('skill-seen proof: a refused beat still records the heartbeat and its other fields',
          load().get('phase') == 'F3' and load().get('round') == 7 and util.age_seconds(load().get('heartbeat')) < 30)
    check('skill-seen proof: a Skill call older than the skill file is refused',
          refused(pf_beat([skill_use(6000, 's1'), skill_result(5999, 's1'), text_rec(100)])))
    check('skill-seen proof: a Skill call for another skill is refused',
          refused(pf_beat([skill_use(100, 's2', name='panel-de-decision'), skill_result(99, 's2')])))
    check('skill-seen proof: a Skill call made only by a subagent (sidechain) is refused',
          refused(pf_beat([skill_use(100, 's3', side=True), skill_result(99, 's3')])))
    check('skill-seen proof: a Skill call whose result is an error, or that has no result, is refused',
          refused(pf_beat([skill_use(100, 's4'), skill_result(99, 's4', error=True)]))
          and refused(pf_beat([skill_use(100, 's5')])))
    check('skill-seen proof: a cross-session message that quotes the command is not a load',
          refused(pf_beat([command_rec(100, 'Another Claude session sent a message:\n<command-name>/supervisa-sesiones</command-name>')])))
    # refused for the skill and for the pause at once: the skill wins (8, not 9), both reasons are printed, the state stays
    pf_state = load().get('state')
    r = pf_beat([text_rec(30)], '--state', 'paused', beat_env=dict(env, SUPERVISOR_USAGE='yes'))
    cur = load()
    check('skill-seen proof: a beat refused for the skill and for the pause exits 8 with both reasons, state kept',
          r.returncode == 8 and 'PAUSE REFUSED' in r.stderr and 'SKILL SEEN REFUSED' in r.stderr and 'BEAT' not in r.stdout
          and pf_state == 'running' and cur.get('state') == 'running' and 'pause_cause' not in cur and 'skill_seen' not in cur)
    before = time.time()
    r = pf_beat([text_rec(300), skill_use(100, 's6'), skill_result(99, 's6'), text_rec(50)], '--phase', 'F4')
    check('skill-seen proof: a Skill call after the newest update is accepted: skill_seen, skill_seen_at and the proof',
          r.returncode == 0 and 'BEAT ' in r.stdout and load().get('skill_seen') == t0
          and before <= (load().get('skill_seen_at') or 0) <= time.time()
          and abs((util.parse_ts(load().get('skill_seen_proof')) or 0) - (time.time() - 100)) < 5 and load().get('phase') == 'F4')
    forget()
    big = dict(text_rec(40), message={'role': 'assistant', 'content': [{'type': 'text', 'text': 'y' * 400000}]})
    check('skill-seen proof: a load far beyond the 256 KB tail window is still found (the whole file is scanned backwards)',
          pf_beat([skill_use(100, 's7'), skill_result(99, 's7'), big, big, text_rec(10)]).returncode == 0 and load().get('skill_seen') == t0)
    forget()
    check('skill-seen proof: the /supervisa-sesiones slash command that started the session counts as a load',
          pf_beat([command_rec(100), text_rec(90)]).returncode == 0 and load().get('skill_seen') == t0)
    # the incident this closes: the supervisor loaded the skill, the supervisor-lock code (or a rule) changed later and
    # a reload order came; answering it with the beat alone must not mark the update as read
    forget()
    open(os.path.join(reload_dir, 'lock.py'), 'w').close()
    os.utime(os.path.join(reload_dir, 'lock.py'), (time.time() - 50, time.time() - 50))
    r = pf_beat([skill_use(100, 's8'), skill_result(99, 's8'), text_rec(20)])
    check('skill-seen proof: a load older than a later change to the code or a rule (reload_globs) is refused', refused(r))
    check('skill-seen proof: after invoking the skill again, the same beat is accepted',
          pf_beat([skill_use(100, 's8'), skill_result(99, 's8'), skill_use(10, 's9'), skill_result(9, 's9')]).returncode == 0
          and load().get('skill_seen') == t0)
    os.remove(os.path.join(reload_dir, 'lock.py'))
    # whose transcript: the running process's own only when it is the lock owner; otherwise the owner's app record
    forget()
    write_jsonl(tpath('cli-pf'), [text_rec(100)])
    mine = dict(env, CLAUDE_CODE_HOST_SESSION_ID='local_pf', CLAUDE_CODE_SESSION_ID='cli-env')
    other_env = dict(env, CLAUDE_CODE_HOST_SESSION_ID='local_other', CLAUDE_CODE_SESSION_ID='cli-env')
    write_jsonl(tpath('cli-env', cwd=other), [skill_use(100, 'e1'), skill_result(99, 'e1')])
    check('skill-seen proof: run by another session, the beat reads the owner\'s transcript, not the caller\'s',
          refused(pf_beat(None, beat_env=other_env)))
    os.remove(os.path.join(app_dir, 'local_pf.json'))
    check('skill-seen proof: inside the owner\'s own process, CLAUDE_CODE_SESSION_ID names its transcript (found in any '
          'project folder)', pf_beat(None, beat_env=mine).returncode == 0 and load().get('skill_seen') == t0)
    forget()
    put(app_dir, 'local_pf.json', {'sessionId': 'local_pf', 'cliSessionId': 'cli-pf', 'cwd': repo, 'title': 'pf'})
    put(sessions_dir, 'pf-old.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-pf-old',
                                       'hostSessionId': 'local_pf', 'name': 'pf', 'status': 'idle'})
    write_jsonl(tpath('cli-pf-old'), [skill_use(100, 'o1'), skill_result(99, 'o1')])
    check('skill-seen proof: a session restarted with a new CLI id is checked in each of its transcripts',
          pf_beat(None).returncode == 0 and load().get('skill_seen') == t0)
    os.remove(os.path.join(sessions_dir, 'pf-old.json'))
    os.remove(os.path.join(app_dir, 'local_pf.json'))
    # Fail open when no transcript can be found or read. The refusal exists for a supervisor that skips the Skill call,
    # and that one always has a transcript. A missing one means the check cannot run at all (another layout of the
    # Claude dir, a renamed projects folder), and nothing the supervisor does would fix it: failing closed would leave
    # every supervisor of such a machine blocked at the end of every turn by a SKILL_CHANGED it can never clear. So the
    # beat is recorded as before, marked `unverified` in the lock, logged and said on stderr.
    forget()
    r = pf_beat(None)
    check('skill-seen proof: no transcript at all fails open: recorded, marked unverified, said on stderr and logged',
          r.returncode == 0 and load().get('skill_seen') == t0 and load().get('skill_seen_proof') == 'unverified'
          and 'SKILL SEEN UNVERIFIED' in r.stderr
          and 'local_pf skill-seen unverified' in (open(hook_log_path).read() if os.path.exists(hook_log_path) else ''))
    check('skill-seen proof: the default reload_globs are the message gate\'s list (one config key for both)',
          list(settings.DEFAULTS['reload_globs']) == ['~/.claude/skills/*/SKILL.md', '~/.claude/skills/*/reference/*.md',
                                                     '~/.claude/rules/*.md', '~/.claude/scripts/supervisor-lock',
                                                     '~/.claude/scripts/lib/supervisor/*.py'])
    for name in os.listdir(os.path.join(projects_t, transcripts.slug_of(repo))):
        if name.startswith('cli-pf'):
            os.remove(os.path.join(projects_t, transcripts.slug_of(repo), name))
    os.utime(skill, (t1, t1))

    # 10. wait --owner: SKILL_CHANGED
    def owner_wait(owner, *extra, timeout='1.5'):
        began = time.time()
        out = subprocess.run([sys.executable, runtime.ENTRY, 'wait', '--dir', repo, '--owner', owner, '--interval', '0.2', '--timeout', timeout,
                              '--all-idle-after', '0', *extra], capture_output=True, text=True, env=env)
        return out.returncode, out.stdout.splitlines(), time.time() - began

    clear_locks()
    os.utime(skill, (t0, t0))
    run('acquire', '--dir', repo, '--session', 'local_sk')
    code, lines, took = owner_wait('local_sk', timeout='20')
    iso_t0 = datetime.fromtimestamp(t0).astimezone().isoformat(timespec='seconds')
    check('SKILL_CHANGED: acquire leaves no skill_seen, so a never-read lock is reported at once with the «not read» wording',
          'skill_seen' not in load() and code == 0 and took < 5
          and lines == [f'SKILL_CHANGED {iso_t0} (the skill has not been read since the lock was taken: invoke supervisa-sesiones, '
                        f'open the question mailbox (F0b-F0c), then: supervisor-lock beat --session local_sk --skill-seen)'])
    run('beat', '--dir', repo, '--session', 'local_sk', '--skill-seen')
    check('SKILL_CHANGED: beat --skill-seen on a never-read lock stores the mtime', load().get('skill_seen') == t0)
    code, lines, _ = owner_wait('local_sk')
    check('SKILL_CHANGED: silent when the skill file mtime equals skill_seen', code == 0 and lines == ['TIMEOUT 1.5s'])
    os.utime(skill, (t0 + 500, t0 + 500))
    code, lines, took = owner_wait('local_sk', timeout='20')
    iso_new = datetime.fromtimestamp(t0 + 500).astimezone().isoformat(timespec='seconds')
    check('SKILL_CHANGED: reported at once at start when the file is newer, exit 0, with the exact instructions',
          code == 0 and took < 5 and lines == [f'SKILL_CHANGED {iso_new} (re-invoke supervisa-sesiones and re-read the reference files you are using, then: '
                                               f'supervisor-lock beat --session local_sk --skill-seen)'])
    code, lines, _ = owner_wait('local_other')
    check('SKILL_CHANGED: only for the session that holds the lock', code == 0 and lines == ['TIMEOUT 1.5s'])
    run('beat', '--dir', repo, '--session', 'local_sk', '--skill-seen')
    code, lines, _ = owner_wait('local_sk')
    check('SKILL_CHANGED: silent again after beat --skill-seen', lines == ['TIMEOUT 1.5s'])
    ref_dir = os.path.join(os.path.dirname(skill), 'reference')
    os.makedirs(ref_dir)
    ref_file = os.path.join(ref_dir, 'x.md')
    open(ref_file, 'w').write('ref\n')
    open(os.path.join(ref_dir, 'notes.txt'), 'w').write('not markdown\n')
    os.utime(os.path.join(ref_dir, 'notes.txt'), (t0 + 650, t0 + 650))
    os.utime(ref_file, (t0 + 700, t0 + 700))
    code, lines, _ = owner_wait('local_sk', timeout='20')
    iso_ref = datetime.fromtimestamp(t0 + 700).astimezone().isoformat(timespec='seconds')
    check('SKILL_CHANGED: a reference/*.md newer than skill_seen fires, stamped with its mtime (other files ignored)',
          code == 0 and len(lines) == 1 and lines[0].startswith(f'SKILL_CHANGED {iso_ref} '))
    run('beat', '--dir', repo, '--session', 'local_sk', '--skill-seen')
    code, lines, _ = owner_wait('local_sk')
    check('SKILL_CHANGED: beat --skill-seen stores the reference mtime and silences it',
          load().get('skill_seen') == t0 + 700 and lines == ['TIMEOUT 1.5s'])
    shutil.rmtree(ref_dir)
    os.utime(skill, (t0 + 500, t0 + 500))
    run('beat', '--dir', repo, '--session', 'local_sk', '--skill-seen')
    pr = subprocess.Popen([sys.executable, runtime.ENTRY, 'wait', '--dir', repo, '--owner', 'local_sk', '--interval', '0.2', '--timeout', '10',
                           '--all-idle-after', '0'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    time.sleep(1.0)
    os.utime(skill, (t0 + 900, t0 + 900))
    code, lines = finish(pr)
    check('SKILL_CHANGED: also detected on a poll while waiting', code == 0 and len(lines) == 1 and lines[0].startswith('SKILL_CHANGED '))
    data = load()
    data.pop('skill_seen', None)
    save(data)
    os.utime(skill, (time.time() - 3600, time.time() - 3600))
    code, lines, _ = owner_wait('local_sk')
    check('SKILL_CHANGED: without skill_seen, even a file older than `started` fires (never read), «not read» wording',
          len(lines) == 1 and lines[0].startswith('SKILL_CHANGED ') and 'has not been read since the lock was taken' in lines[0])
    os.utime(skill, (time.time() + 60, time.time() + 60))
    code, lines, _ = owner_wait('local_sk')
    check('SKILL_CHANGED: without skill_seen, a file newer than `started` fires too', len(lines) == 1 and lines[0].startswith('SKILL_CHANGED '))
    run('beat', '--dir', repo, '--session', 'local_sk', '--skill-seen')
    os.utime(skill, (time.time() + 600, time.time() + 600))
    code, lines, _ = owner_wait('local_sk')
    check('SKILL_CHANGED: changed after a read keeps the old «re-invoke» wording, not the «not read» one',
          len(lines) == 1 and lines[0].startswith('SKILL_CHANGED ') and '(re-invoke supervisa-sesiones and re-read the reference files' in lines[0]
          and 'has not been read' not in lines[0])
    os.utime(skill, (t0, t0))

    # 11. hook: PreToolUse keeps questions out of the supervisor's own dialogs and end-of-turn box
    clear_locks()
    clear_sessions()
    run('acquire', '--dir', repo, '--session', 'local_pt', '--title', 'sup pt')
    put(sessions_dir, 'pt.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-pt', 'hostSessionId': 'local_pt', 'name': 'pt', 'status': 'busy'})
    put(sessions_dir, 'px.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-px', 'hostSessionId': 'local_px', 'name': 'px', 'status': 'busy'})

    def pre(tool, session='cli-pt', tool_input=None):
        return {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'session_id': session, 'tool_input': {} if tool_input is None else tool_input}

    def verdict(r):
        try:
            return json.loads(r.stdout).get('hookSpecificOutput', {})
        except ValueError:
            return {}

    r = hook(pre('AskUserQuestion'))
    out = verdict(r)
    reason = out.get('permissionDecisionReason', '')
    check('hook PreToolUse: owner AskUserQuestion without mailbox -> deny, exit 0, with the open-a-mailbox instructions',
          r.returncode == 0 and out.get('hookEventName') == 'PreToolUse' and out.get('permissionDecision') == 'deny'
          and 'Eres la supervisora de proj (cerrojo ' in reason and 'ábrela' in reason and settings.questions_title('proj') in reason
          and 'supervisor-lock beat --session local_pt --mailbox <id>' in reason and 'sin pregunta ni botones' in reason and '\n' not in reason)
    run('beat', '--dir', repo, '--session', 'local_pt', '--mailbox', 'local_box')
    put(app_dir, 'local_box.json', {'sessionId': 'local_box', 'cwd': repo, 'title': 'Sesión de preguntas de proj', 'isArchived': False})
    reason = verdict(hook(pre('AskUserQuestion'))).get('permissionDecisionReason', '')
    check('hook PreToolUse: owner with a live mailbox -> deny naming the mailbox id, no "ábrela"',
          'la sesión de preguntas es local_box (SendMessage)' in reason and 'ábrela' not in reason and 'sin pregunta ni botones' in reason
          and 'ni en prosa' in reason and settings.DECISION_CRITERION in reason and 'pre-producción' in reason and 'radical por unanimidad' in reason)
    put(app_dir, 'local_box.json', {'sessionId': 'local_box', 'cwd': repo, 'isArchived': True})
    reason = verdict(hook(pre('AskUserQuestion'))).get('permissionDecisionReason', '')
    check('hook PreToolUse: archived mailbox is treated as missing (and named)', 'ábrela' in reason and 'local_box' in reason and 'la sesión de preguntas es local_box (SendMessage)' not in reason)
    os.remove(os.path.join(app_dir, 'local_box.json'))
    check('hook PreToolUse: mailbox without any app record is treated as missing',
          'ábrela' in verdict(hook(pre('AskUserQuestion'))).get('permissionDecisionReason', ''))
    wrap = 'mcp__ccd_turn__wrap_up'
    check('hook PreToolUse: owner wrap_up with ask -> deny', verdict(hook(pre(wrap, tool_input={'recap': 'r', 'ask': '¿Seguimos?'}))).get('permissionDecision') == 'deny')
    check('hook PreToolUse: owner wrap_up with actions -> deny',
          verdict(hook(pre(wrap, tool_input={'recap': 'r', 'actions': [{'label': 'Sí'}]}))).get('permissionDecision') == 'deny')
    check('hook PreToolUse: owner wrap_up with only recap (or empty ask/actions) -> nothing',
          all(hook(pre(wrap, tool_input=ti)).stdout == '' for ti in ({'recap': 'r'}, {'recap': 'r', 'ask': '  ', 'actions': []}, {}, 'text')))
    check('hook PreToolUse: owner running another tool -> nothing', all(hook(pre(t)).stdout == '' for t in ('Bash', 'SendMessage', 'Edit')))
    r = hook(pre('AskUserQuestion', session='cli-px'))
    check('hook PreToolUse: a session that owns no lock may ask -> nothing', r.returncode == 0 and r.stdout == '')
    check('hook PreToolUse: unknown session -> nothing', hook(pre('AskUserQuestion', session='cli-nobody')).stdout == '')
    check('hook PreToolUse: non-owner wrap_up with ask -> nothing', hook(pre(wrap, session='cli-px', tool_input={'ask': 'q', 'actions': [1]})).stdout == '')
    for n in range(2):
        put_lock(f'k-pre{n}', f'local_pre{n}', 10)
    saved = {k: os.environ.get(k) for k in env if k.startswith(('SUPERVISOR_', 'ASK_GATE'))}
    os.environ.update({k: v for k, v in env.items() if k.startswith(('SUPERVISOR_', 'ASK_GATE'))})
    began = time.perf_counter()
    speedy = hook_mod.hook_decide(json.dumps(pre('AskUserQuestion', session='cli-not-an-owner')))
    took = time.perf_counter() - began
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    check(f'hook PreToolUse: 3 locks + 400 app records, non-owner AskUserQuestion -> \'\' in {took:.2f} s (< 0.3)',
          speedy == '' and took < 0.3 and len(glob.glob(os.path.join(tmp, 'app', 'big', 'dir', '*.json'))) == 400)
    if os.path.exists(gate) and os.path.realpath(os.path.expanduser('~/.claude/scripts/supervisor-lock')) == os.path.realpath(runtime.ENTRY):
        r = subprocess.run([gate], input=json.dumps(pre('AskUserQuestion')), capture_output=True, text=True, env=env)
        check('supervisor-stop-gate: passes a PreToolUse deny through', verdict(r).get('permissionDecision') == 'deny')


    # 11b. ask gate: a session that is not a lock owner may not ask the developer while the developer is away
    clear_locks()
    clear_sessions()
    ag_dir = os.path.join(tmp, 'ask-gate')
    ag_xlog = env['ASK_GATE_XPROJECT_LOG']
    os.makedirs(os.path.join(tmp, 'ag'), exist_ok=True)
    ag_n = [0]

    def stamp(mins):
        return datetime.fromtimestamp(time.time() - mins * 60, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    def u_text(mins, text, **extra):
        return dict({'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]},
                     'timestamp': stamp(mins)}, **extra)

    def a_tool(mins, name='Bash', tid='toolu_x1', **inp):
        return {'type': 'assistant', 'timestamp': stamp(mins),
                'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}]}}

    def u_result(mins, tid='toolu_x1', **extra):
        item = dict({'type': 'tool_result', 'tool_use_id': tid, 'content': 'ok'}, **extra)
        return {'type': 'user', 'message': {'role': 'user', 'content': [item]}, 'timestamp': stamp(mins)}

    def queued(mins, prompt, **extra):
        att = dict({'type': 'queued_command', 'prompt': prompt, 'commandMode': 'prompt'}, **extra)
        return {'type': 'attachment', 'attachment': att, 'timestamp': stamp(mins)}

    def ag_transcript(records):
        ag_n[0] += 1
        path = os.path.join(tmp, 'ag', f't{ag_n[0]}.jsonl')
        with open(path, 'w') as fh:
            for rec in records:
                fh.write(json.dumps(rec, separators=(',', ':'), ensure_ascii=False) + '\n')
        return path

    def ag_ask(records, tool='AskUserQuestion', session='cli-ag', tool_input=None, hook_env=None, path=None):
        payload = {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'session_id': session, 'cwd': repo,
                   'tool_input': {} if tool_input is None else tool_input}
        if records is not None:
            payload['transcript_path'] = path or ag_transcript(records)
        return hook(payload, hook_env=hook_env)

    def denied(r):
        return r.returncode == 0 and verdict(r).get('permissionDecision') == 'deny'

    def allowed(r):
        return r.returncode == 0 and r.stdout == ''

    old_human = u_text(30, 'hazlo todo', origin={'kind': 'human'})
    busy = [a_tool(2), u_result(2), a_tool(1, tid='toolu_x2'), u_result(1, tid='toolu_x2')]
    r = ag_ask([old_human] + busy)
    reason = verdict(r).get('permissionDecisionReason', '')
    check('ask gate: developer away -> AskUserQuestion denied, exit 0',
          denied(r) and verdict(r).get('hookEventName') == 'PreToolUse')
    check('ask gate: deny text (Spanish, one line) names the panel skill, ask-queue, the 20 min and the hard limits',
          '\n' not in reason and 'no está delante' in reason and 'últimos 20 min' in reason
          and '~/.claude/skills/panel-de-decision/SKILL.md' in reason and 'hasta 3 agentes' in reason
          and 'registro de decisiones' in reason and '~/.claude/scripts/ask-queue add' in reason and 'límite duro' in reason
          and 'despliegue-y-limites-duros.md' in reason and settings.DECISION_CRITERION in reason and 'pre-producción' in reason
          and 'decisiones_abiertas' in reason and 'deja solo el recap' in reason and 'despliego' in reason)
    check('ask gate: by default the deny text does not pre-authorise deploys (it names the written rule instead)',
          'no está autorizado salvo' in reason and 'ya está autorizado' not in reason)
    saved_deploy = (settings.DEPLOY_PREAUTHORISED, settings.EXCLUDED_PROJECTS)
    try:
        settings.DEPLOY_PREAUTHORISED, settings.EXCLUDED_PROJECTS = True, ('proj-x', 'proj-y')
        authorised = json.loads(deny.deny_absent(20))['hookSpecificOutput']['permissionDecisionReason']
        settings.EXCLUDED_PROJECTS = ()
        unexcluded = json.loads(deny.deny_absent(20))['hookSpecificOutput']['permissionDecisionReason']
    finally:
        settings.DEPLOY_PREAUTHORISED, settings.EXCLUDED_PROJECTS = saved_deploy
    check('ask gate: with deploy_preauthorised in config the text says deploys are authorised, naming the excluded '
          'projects as exceptions and as a hard limit',
          'ya está autorizado, salvo en proj-x, proj-y' in authorised and 'push o deploy en proj-x, proj-y' in authorised
          and 'despliego' in authorised and 'no está autorizado salvo' not in authorised
          and 'ya está autorizado:' in unexcluded and 'salvo en' not in unexcluded)
    check('ask gate: wrap_up with ask -> denied',
          denied(ag_ask([old_human] + busy, tool=wrap, tool_input={'recap': 'r', 'ask': '¿Sigo?'})))
    check('ask gate: wrap_up with actions -> denied',
          denied(ag_ask([old_human] + busy, tool=wrap, tool_input={'recap': 'r', 'actions': [{'label': 'Sí'}]})))
    check('ask gate: wrap_up with only a recap (or empty ask/actions) -> allowed',
          all(allowed(ag_ask([old_human] + busy, tool=wrap, tool_input=ti))
              for ti in ({'recap': 'r'}, {'recap': 'r', 'ask': ' ', 'actions': []})))
    check('ask gate: other tools are never touched', allowed(ag_ask([old_human] + busy, tool='Bash')))
    check('ask gate: developer typed 2 min ago -> allowed',
          allowed(ag_ask([old_human, u_text(2, 'sigue', origin={'kind': 'human'})] + busy)))
    check('ask gate: old record without `origin` but with plain text 2 min ago -> allowed',
          allowed(ag_ask([old_human, u_text(2, 'sigue')] + busy)))
    # presence alone only authorises a question for ASK_GATE_FRESH_MIN minutes
    r = ag_ask([old_human, u_text(5, 'sigue', origin={'kind': 'human'})] + busy)
    check('ask gate: developer typed 5 min ago (inside the 20 min window, no request) -> denied, stale presence worded',
          denied(r) and 'último mensaje en esta sesión fue hace 5 min' in verdict(r).get('permissionDecisionReason', '')
          and 'no pide que se le pregunte' in verdict(r).get('permissionDecisionReason', '')
          and '~/.claude/skills/panel-de-decision/SKILL.md' in verdict(r).get('permissionDecisionReason', '')
          and '~/.claude/scripts/ask-queue add' in verdict(r).get('permissionDecisionReason', '')
          and '\n' not in verdict(r).get('permissionDecisionReason', ''))
    check('ask gate: stale presence also denies wrap_up with ask, and the 19 min old message',
          denied(ag_ask([old_human, u_text(5, 'sigue', origin={'kind': 'human'})] + busy, tool=wrap, tool_input={'recap': 'r', 'ask': '¿Sigo?'}))
          and denied(ag_ask([old_human, u_text(19, 'termina lo de ayer', origin={'kind': 'human'})] + busy)))
    check('ask gate: a 5 min old message that explicitly asks to be asked -> allowed (every wording, accents or not)',
          all(allowed(ag_ask([old_human, u_text(5, wording, origin={'kind': 'human'})] + busy))
              for wording in ('Pregúntame antes de borrar nada', 'preguntame', 'pregunta antes de decidir', 'PREGUNTAME ANTES',
                              'consúltame esto', 'dame opciones y ya elijo', 'déjame elegir', 'elijo yo', 'quiero elegir el nombre',
                              'quiero decidir yo', 'ask me before you ship it')))
    check('ask gate: a 5 min old message that only resembles a request -> denied',
          all(denied(ag_ask([old_human, u_text(5, wording, origin={'kind': 'human'})] + busy))
              for wording in ('no me preguntes nada', 'hazlo y listo', 'quiero que lo hagas ya', 'te preguntaré luego')))
    check('ask gate: only the developer\'s LAST message counts: an old request followed by a plain 5 min old one -> denied',
          denied(ag_ask([old_human, u_text(8, 'pregúntame antes', origin={'kind': 'human'}),
                         u_text(5, 'sigue', origin={'kind': 'human'})] + busy)))
    check('ask gate: a request older than the 20 min window does not count -> denied (deny-absent)',
          denied(ag_ask([u_text(25, 'pregúntame antes', origin={'kind': 'human'})] + busy)))
    check('ask gate: ASK_GATE_FRESH_MIN moves the fresh window',
          allowed(ag_ask([old_human, u_text(5, 'sigue', origin={'kind': 'human'})] + busy, hook_env=dict(env, ASK_GATE_FRESH_MIN='10')))
          and denied(ag_ask([old_human, u_text(2, 'sigue', origin={'kind': 'human'})] + busy, hook_env=dict(env, ASK_GATE_FRESH_MIN='1'))))
    reminder = '<system-reminder>\nuno <system-reminder>\ndentro\n</system-reminder> dos\n</system-reminder>\n\n'
    mid = queued(2, [{'type': 'text', 'text': reminder}, {'type': 'text', 'text': 'voy a dormir'}],
                 origin={'kind': 'human'}, humanTurn=True)
    check('ask gate: mid-turn message (queued_command, nested system-reminders, human origin) -> allowed',
          allowed(ag_ask([old_human, mid] + busy)))
    check('ask gate: a mid-turn queued_command that is only system-reminders does not count',
          denied(ag_ask([old_human, queued(3, [{'type': 'text', 'text': reminder}], origin={'kind': 'human'})] + busy)))
    check('ask gate: compaction summary (flag, or just its text) does not count',
          denied(ag_ask([old_human, u_text(4, 'This session is being continued from a previous conversation that ran '
                                              'out of context.', isCompactSummary=True),
                         u_text(3, 'This session is being continued from a previous conversation.')] + busy)))
    check('ask gate: a user record that is only a system-reminder does not count',
          denied(ag_ask([old_human, u_text(4, '<system-reminder>\nrecordatorio\n</system-reminder>'),
                         u_text(3, '<system-reminder>x</system-reminder>', origin={'kind': 'human'})] + busy)))
    check('ask gate: relayed messages do not count (peer, task-notification, start_session background, hand-back)',
          denied(ag_ask([old_human, u_text(4, 'hola', origin={'kind': 'peer', 'from': 'local_z'}),
                         u_text(3, 'x', origin={'kind': 'task-notification'}),
                         u_text(3, 'Background (from the session that started this one) haz esto'),
                         u_text(3, '[Subagent hand-back] informe'), u_text(3, '<task-notification>fin</task-notification>'),
                         queued(2, 'hola', origin={'kind': 'peer'}), u_text(2, 'meta', isMeta=True)] + busy)))
    events = ('<side-sessions-event>{"kind":"wake"}</side-sessions-event>', '<ci-monitor-event>build ok</ci-monitor-event>',
              '[SYSTEM NOTIFICATION] algo ha pasado')
    check('ask gate: app events without `origin` (side-sessions, ci-monitor, SYSTEM NOTIFICATION) are not human input',
          all(not human_turns.human_input(u_text(3, ev)) for ev in events)
          and not human_turns.human_input(u_text(3, '<cross-session-message from="x">hola</cross-session-message>'))
          and human_turns.human_input(u_text(3, 'sigue')))
    check('ask gate: a transcript whose only recent record is such an event -> AskUserQuestion denied (non-owner)',
          all(denied(ag_ask([old_human, u_text(3, ev)] + busy)) for ev in events))
    check('ask gate: an AskUserQuestion the developer answered counts as presence',
          allowed(ag_ask([old_human, a_tool(3, name='AskUserQuestion', tid='toolu_q1'), u_result(2, tid='toolu_q1')] + busy)))
    check('ask gate: an AskUserQuestion that errored (hook deny) does not',
          denied(ag_ask([old_human, a_tool(6, name='AskUserQuestion', tid='toolu_q1'),
                         u_result(5, tid='toolu_q1', is_error=True)] + busy)))
    check('ask gate: presence window comes from ASK_GATE_PRESENCE_MIN',
          denied(ag_ask([old_human, u_text(2, 'sigue', origin={'kind': 'human'})] + busy, hook_env=dict(env, ASK_GATE_PRESENCE_MIN='1', ASK_GATE_FRESH_MIN='0.5')))
          and allowed(ag_ask([old_human, u_text(25, 'pregúntame antes', origin={'kind': 'human'})] + busy, hook_env=dict(env, ASK_GATE_PRESENCE_MIN='30'))))
    put(sessions_dir, 'mb.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-mb', 'hostSessionId': 'local_mb',
                                  'name': 'Sesión de preguntas de proj', 'status': 'waiting'})
    put(sessions_dir, 'mc.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-mc', 'hostSessionId': 'local_mc',
                                  'name': 'BUZÓN DE PREGUNTAS otro-proyecto', 'status': 'waiting'})
    put(app_dir, 'local_md.json', {'sessionId': 'local_md', 'cliSessionId': 'cli-md', 'cwd': repo, 'title': 'Buzón de preguntas', 'isArchived': False})
    put(sessions_dir, 'me.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-me', 'hostSessionId': 'local_me', 'name': 'Otra cosa', 'status': 'busy'})
    check('ask gate: question mailbox by title (CLI record, any case, and app record) -> allowed',
          all(allowed(ag_ask([old_human] + busy, session=s)) for s in ('cli-mb', 'cli-mc', 'cli-md')))
    check('ask gate: an ordinary titled session is still denied', denied(ag_ask([old_human] + busy, session='cli-me')))
    put_lock('k-owner-mb', 'local_owner', 10)
    owner_file = os.path.join(lock_home, 'locks', 'k-owner-mb.json')
    data = json.load(open(owner_file))
    data['mailbox'] = 'local_me'
    json.dump(data, open(owner_file, 'w'))
    check('ask gate: the id recorded as `mailbox` by a lock owner -> allowed (and others still denied)',
          allowed(ag_ask([old_human] + busy, session='cli-me')) and denied(ag_ask([old_human] + busy, session='cli-nobody')))
    put(sessions_dir, 'ow.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-owner', 'hostSessionId': 'local_owner', 'name': 'sup', 'status': 'busy'})
    r = ag_ask([old_human] + busy, session='cli-owner')
    check('ask gate: a lock owner with the developer away gets the owner deny, not the ask-gate text',
          denied(r) and 'Eres la supervisora de proj' in verdict(r).get('permissionDecisionReason', '')
          and 'panel-de-decision' not in verdict(r).get('permissionDecisionReason', ''))
    check('...but with the developer typing in it (2 min ago) the lock owner may ask (a supervisor the developer is '
          'writing to is not denied for being the owner)',
          allowed(ag_ask([old_human, u_text(2, 'sigue', origin={'kind': 'human'})] + busy, session='cli-owner')))
    clear_locks()
    os.remove(os.path.join(sessions_dir, 'ow.json'))

    # 11b-2. backstop against asking twice: queue ids in metadata.source, and near-identical answered questions
    aq_bin = os.path.expanduser(env.get('ASK_QUEUE_BIN', os.path.join(os.path.dirname(runtime.ENTRY), 'ask-queue')))
    env['ASK_QUEUE_BIN'] = aq_bin  # the hook reads the same queue CLI (the sandbox HOME has none installed)

    def aq(*cli_args):
        r = subprocess.run([sys.executable, aq_bin, *cli_args], capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def aq_item(question):
        return aq('add', '--project', repo, '--question', question, '--default', 'd', '--why', 'w', '--blocks', 'b')

    def ask_in(question, ids=None, **extra):
        meta = {'source': 'ask-queue:' + ','.join(ids)} if ids else {'source': 'supervisor'}
        return {'questions': [{'question': question, 'header': 'h', 'options': []}], 'metadata': meta, **extra}

    def answered_dialog(mins, question, answer, tid='toolu_q9', **result_extra):
        use = a_tool(mins + 0.1, name='AskUserQuestion', tid=tid, questions=[{'question': question}])
        res = u_result(mins, tid=tid, **result_extra)
        res['toolUseResult'] = {'questions': [{'question': question}], 'answers': {question: answer}}
        return [use, res]

    def bare_dialog(mins, question, tid='toolu_q8'):
        return [a_tool(mins + 0.1, name='AskUserQuestion', tid=tid, questions=[{'question': question}]), u_result(mins, tid=tid)]

    here = u_text(2, 'sigue', origin={'kind': 'human'})
    q_voice = aq_item('¿Grabo las voces del vídeo de portada?')
    q_open = aq_item('¿Pago el dominio nuevo?')
    q_closed = aq_item('¿Borro la rama vieja?')
    aq('answer', q_voice, '--text', 'Sí, grábalas con la voz de la locución')
    aq('close', q_closed, '--note', 'ya no aplica')
    r = ag_ask([old_human, here] + busy, tool_input=ask_in('¿Voz sí o voz no?', [q_voice]))
    reason = verdict(r).get('permissionDecisionReason', '')
    check('ask gate backstop: a dialog naming an answered queue id is denied even with the developer present',
          denied(r) and q_voice in reason and 'Sí, grábalas con la voz de la locución' in reason and 'respondida el' in reason
          and 'ask-queue add' in reason and 'quítalas' in reason.lower() and '\n' not in reason)
    r = ag_ask([old_human, here] + busy, tool_input=ask_in('x', [q_closed]))
    check('ask gate backstop: a closed id is denied too, with its note',
          denied(r) and 'cerrada el' in verdict(r).get('permissionDecisionReason', '') and 'ya no aplica' in verdict(r).get('permissionDecisionReason', ''))
    r = ag_ask([old_human, here] + busy, tool_input=ask_in('x', [q_open, q_voice]))
    reason = verdict(r).get('permissionDecisionReason', '')
    check('ask gate backstop: a mix of open and answered ids -> denied, naming only the answered one',
          denied(r) and q_voice in reason and q_open not in reason)
    check('ask gate backstop: open ids, an unknown id, or no ids -> allowed (developer present)',
          allowed(ag_ask([old_human, here] + busy, tool_input=ask_in('x', [q_open])))
          and allowed(ag_ask([old_human, here] + busy, tool_input=ask_in('x', ['q-ghost'])))
          and allowed(ag_ask([old_human, here] + busy, tool_input=ask_in('x'))))
    aq('asked', q_open, '--to', 'local_mb')
    check('ask gate backstop: an `asked` id is still pending -> allowed',
          allowed(ag_ask([old_human, here] + busy, tool_input=ask_in('x', [q_open]))))
    check('ask gate backstop: kill switch ASK_GATE=off lets the stale dialog through',
          allowed(ag_ask([old_human, here] + busy, tool_input=ask_in('x', [q_voice]), hook_env=dict(env, ASK_GATE='off'))))
    check('ask gate backstop: wrap_up is not touched by it',
          allowed(ag_ask([old_human, here] + busy, tool=wrap, tool_input={'recap': 'r', 'ask': '¿Voz?', 'metadata': {'source': f'ask-queue:{q_voice}'}})))
    check('ask gate backstop: queue unreadable (ASK_QUEUE_BIN missing) -> fails open, error logged',
          allowed(ag_ask([old_human, here] + busy, tool_input=ask_in('x', [q_voice]), hook_env=dict(env, ASK_QUEUE_BIN='/nonexistent/ask-queue')))
          and 'backstop' in open(os.path.join(ag_dir, 'errors.log')).read())

    question = '¿Quieres que grabe las voces del vídeo de portada con tu voz o con una voz sintética del equipo?'
    earlier = answered_dialog(30, question, 'Con mi voz, grábalas ya')
    same = question.replace('del equipo', 'de equipo')
    r = ag_ask([old_human] + earlier + [here] + busy, tool_input=ask_in(same))
    reason = verdict(r).get('permissionDecisionReason', '')
    check('ask gate backstop: a near-identical question answered 30 min ago -> denied (even with the developer present)',
          denied(r) and 'casi idéntica' in reason and 'Con mi voz, grábalas ya' in reason and 'No la repitas' in reason
          and '\n' not in reason)
    check('ask gate backstop: a reworded or different question -> allowed',
          allowed(ag_ask([old_human] + earlier + [here] + busy, tool_input=ask_in('¿Publico el vídeo en el canal o solo lo dejo guardado?')))
          and allowed(ag_ask([old_human] + earlier + [here] + busy, tool_input=ask_in('¿Prefieres voz humana o sintética?'))))
    check('ask gate backstop: the same question answered more than 24 h ago -> allowed',
          allowed(ag_ask([old_human] + answered_dialog(25 * 60, question, 'sí') + [here] + busy, tool_input=ask_in(question))))
    check('ask gate backstop: an earlier dialog that errored (denied by a hook) does not count',
          allowed(ag_ask([old_human] + answered_dialog(30, question, 'sí', is_error=True) + [here] + busy, tool_input=ask_in(question))))
    r = ag_ask([old_human] + bare_dialog(30, question) + [here] + busy, tool_input=ask_in(question))
    check('ask gate backstop: a transcript without toolUseResult falls back to the tool_use (answer unknown)',
          denied(r) and 'consta su respuesta en esta misma conversación' in verdict(r).get('permissionDecisionReason', ''))
    check('ask gate backstop: one of several questions matching is enough',
          denied(ag_ask([old_human] + earlier + [here] + busy, tool_input={
              'questions': [{'question': 'Otra cosa distinta por completo'}, {'question': same}], 'metadata': {}})))
    check('ask gate backstop: a dialog nobody has answered yet (no result) does not block its retry',
          allowed(ag_ask([old_human, a_tool(30, name='AskUserQuestion', tid='toolu_q7', questions=[{'question': question}]), here] + busy,
                         tool_input=ask_in(question))))
    check('ask gate backstop: an unreadable transcript -> fails open',
          allowed(ag_ask(None, path=os.path.join(tmp, 'ag', 'missing.jsonl'), tool_input=ask_in(question))))
    dup_log = open(os.path.join(ag_dir, 'decisions.log')).read()
    check('ask gate backstop: deny-answered and deny-duplicate are in decisions.log',
          '\tdeny-answered\t' in dup_log and '\tdeny-duplicate\t' in dup_log)
    put_lock('k-owner-bs', 'local_owner', 10)
    put(sessions_dir, 'ow.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-owner', 'hostSessionId': 'local_owner', 'name': 'sup', 'status': 'busy'})
    r = ag_ask([old_human] + busy, session='cli-owner', tool_input=ask_in('x', [q_voice]))
    check('ask gate backstop: a lock owner with the developer away gets only the owner deny',
          denied(r) and 'Eres la supervisora de proj' in verdict(r).get('permissionDecisionReason', '')
          and 'ya no están pendientes' not in verdict(r).get('permissionDecisionReason', ''))
    r = ag_ask([old_human, here] + busy, session='cli-owner', tool_input=ask_in('x', [q_voice]))
    check('ask gate backstop: a lock owner the developer is typing in may ask, but not a question the developer already answered',
          denied(r) and 'ya no están pendientes' in verdict(r).get('permissionDecisionReason', ''))
    clear_locks()
    os.remove(os.path.join(sessions_dir, 'ow.json'))

    # 11b-3. session_role: owner / mailbox / supervised / free, judged by live locks
    saved_env = {k: os.environ.get(k) for k in env if k.startswith(('SUPERVISOR_', 'ASK_GATE'))}
    os.environ.update({k: v for k, v in env.items() if k.startswith(('SUPERVISOR_', 'ASK_GATE'))})
    try:
        lock_key = projects.resolve(repo)['key']
        role_lock = {'key': lock_key, 'project': 'proj', 'session_id': 'local_rown', 'title': 'T', 'state': 'running',
                     'phase': 'F1', 'round': 1, 'heartbeat': hb_ago(10), 'mailbox': 'local_rmb'}
        put(os.path.join(lock_home, 'locks'), lock_key + '.json', role_lock)
        for name, local, title in (('rown', 'local_rown', 'sup'), ('rmb', 'local_rmb', 'Otra cosa'), ('rsv', 'local_rsv', 'trabajo'),
                                   ('rtl', 'local_rtl', 'Sesión de preguntas de proj')):
            put(sessions_dir, name + '.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-' + name, 'hostSessionId': local,
                                               'name': title, 'status': 'busy'})
        roles = {n: session_roles.session_role('cli-' + n, repo) for n in ('rown', 'rmb', 'rsv', 'rtl', 'nobody')}
        check('session_role: lock owner / mailbox recorded in the lock / mailbox by title / ordinary session',
              [roles[n][0] for n in ('rown', 'rmb', 'rtl', 'rsv')] == ['owner', 'mailbox', 'mailbox', 'supervised']
              and roles['rown'][1]['session_id'] == 'local_rown' and roles['rsv'][1]['key'] == lock_key)
        check('session_role: a worktree of the project and an unknown session are supervised; another project is free',
              session_roles.session_role('cli-rsv', wt)[0] == 'supervised' and roles['nobody'][0] == 'supervised'
              and session_roles.session_role('cli-rsv', other)[0] == 'free' and session_roles.session_role('cli-rsv', notrepo) == ('free', None)
              and session_roles.session_role('cli-rsv', None)[0] in ('supervised', 'free'))
        put(os.path.join(lock_home, 'locks'), lock_key + '.json', dict(role_lock, heartbeat=hb_ago(5000)))
        check('session_role: a stale unreleased lock (< 24 h) still supervises: ordinary -> supervised, mailbox kept, owner stays free',
              session_roles.session_role('cli-rown', repo) == ('free', None) and session_roles.session_role('cli-rsv', repo)[0] == 'supervised'
              and session_roles.session_role('cli-rsv', repo)[1]['key'] == lock_key and session_roles.session_role('cli-rmb', repo)[0] == 'mailbox'
              and session_roles.session_role('cli-rsv', other)[0] == 'free')
        put(os.path.join(lock_home, 'locks'), lock_key + '.json', dict(role_lock, heartbeat=hb_ago(86400 - 600), state='paused'))
        check('session_role: a paused lock silent for 23 h 50 min still supervises',
              session_roles.session_role('cli-rsv', repo)[0] == 'supervised')
        put(os.path.join(lock_home, 'locks'), lock_key + '.json', dict(role_lock, heartbeat=hb_ago(86400 + 600)))
        check('session_role: a stale lock older than 24 h is no lock (owner and ordinary session become free; title mailbox stays)',
              session_roles.session_role('cli-rown', repo) == ('free', None) and session_roles.session_role('cli-rsv', repo) == ('free', None)
              and session_roles.session_role('cli-rmb', repo) == ('free', None) and session_roles.session_role('cli-rtl', repo)[0] == 'mailbox')
        os.remove(os.path.join(lock_home, 'locks', lock_key + '.json'))
        check('session_role: no lock at all -> free; a title-matched mailbox is still a mailbox',
              session_roles.session_role('cli-rsv', repo) == ('free', None) and session_roles.session_role('cli-rtl', repo)[0] == 'mailbox')
        # T8: the title is normalized and only counts inside its project
        put(os.path.join(lock_home, 'locks'), lock_key + '.json', {k: v for k, v in role_lock.items() if k != 'mailbox'})
        for name, local, title, where in (('tn1', 'local_tn1', 'PREGUNTAS DE LA SUPERVISION DE PROJ', repo),
                                          ('tn2', 'local_tn2', 'Buzon de preguntas', wt),
                                          ('tn3', 'local_tn3', 'Sesión de preguntas de zeta', other),
                                          ('tn4', 'local_tn4', 'Sesión de preguntas de proj', other),
                                          ('tn5', 'local_tn5', 'Sesión de preguntas de zeta', repo)):
            put(sessions_dir, name + '.json', {'pid': os.getpid(), 'cwd': where, 'sessionId': 'cli-' + name,
                                               'hostSessionId': local, 'name': title, 'status': 'busy'})
        check('session_role (T8): a running lock without a registered mailbox still recognizes the questions session by '
              'its title, without accents and in any case, inside the project (also from one of its worktrees)',
              session_roles.session_role('cli-tn1', repo)[0] == 'mailbox' and session_roles.session_role('cli-tn2', wt)[0] == 'mailbox')
        check('session_role (T8): the same title in ANOTHER project that it does not name stays a free session',
              session_roles.session_role('cli-tn3', other) == ('free', None))
        check('session_role (T8): the title naming the supervised project counts even from another folder; '
              'and any questions title inside the supervised project counts, whatever project it names',
              session_roles.session_role('cli-tn4', other)[0] == 'mailbox' and session_roles.session_role('cli-tn5', repo)[0] == 'mailbox')
        os.remove(os.path.join(lock_home, 'locks', lock_key + '.json'))
        for n in ('tn1', 'tn2', 'tn3', 'tn4', 'tn5'):
            os.remove(os.path.join(sessions_dir, n + '.json'))
        # T6: the lock is the one that CONTAINS the cwd, the most specific, not resolve(cwd)['key']
        ws_lock = {'key': pw['key'], 'project': 'ws', 'checkout': ws, 'common_dir': None, 'session_id': 'local_wsown',
                   'title': 'Sup ws', 'state': 'running', 'phase': 'F1', 'round': 1, 'heartbeat': hb_ago(10)}
        put(os.path.join(lock_home, 'locks'), pw['key'] + '.json', ws_lock)
        in_notes = session_roles.session_role('cli-w1', os.path.join(ws, 'notes'))
        in_nested = session_roles.session_role('cli-w1', ws_a)
        in_nested_wt = session_roles.session_role('cli-w1', ws_wt)
        check('session_role: a subfolder of a workspace without git is supervised by the workspace lock (it was free)',
              in_notes[0] == 'supervised' and in_notes[1]['key'] == pw['key'])
        check('session_role: a nested git repo inside the workspace, and its worktree living elsewhere, are supervised too',
              in_nested[0] == 'supervised' and in_nested[1]['key'] == pw['key']
              and in_nested_wt[0] == 'supervised' and in_nested_wt[1]['key'] == pw['key'])
        check('session_role: a folder outside the workspace (even with its textual prefix) stays free',
              session_roles.session_role('cli-w1', ws_extra) == ('free', None) and session_roles.session_role('cli-w1', other) == ('free', None))
        nested = projects.resolve(ws_a)
        nested_lock = {'key': nested['key'], 'project': 'a', 'checkout': nested['checkout'], 'common_dir': nested['common_dir'],
                       'session_id': 'local_anown', 'title': 'Sup a', 'state': 'running', 'phase': 'F1', 'round': 1,
                       'heartbeat': hb_ago(10)}
        put(os.path.join(lock_home, 'locks'), nested['key'] + '.json', nested_lock)
        check('session_role: with a lock of the nested repo too, the most specific one wins (repo and its worktree), '
              'the rest of the workspace keeps the workspace lock',
              session_roles.session_role('cli-w1', ws_a)[1]['key'] == nested['key'] and session_roles.session_role('cli-w1', ws_wt)[1]['key'] == nested['key']
              and session_roles.session_role('cli-w1', ws_b)[1]['key'] == pw['key'] and session_roles.session_role('cli-w1', os.path.join(ws, 'notes'))[1]['key'] == pw['key'])
        os.remove(os.path.join(lock_home, 'locks', nested['key'] + '.json'))
        os.remove(os.path.join(lock_home, 'locks', pw['key'] + '.json'))
        check('session_role: the workspace lock gone -> all free again', session_roles.session_role('cli-w1', ws_a) == ('free', None))
    finally:
        for k, v in saved_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    clear_locks()
    clear_sessions()

    # 11b-4. pre-production model: supervised sessions never get `allow-present`; Stop on a prose question
    sup_key = projects.resolve(repo)['key']
    sup_lock = {'key': sup_key, 'project': 'proj', 'session_id': 'local_sown', 'title': 'Supervisora P', 'state': 'running',
                'phase': 'F1', 'round': 1, 'heartbeat': hb_ago(10), 'mailbox': 'local_smb'}
    put(os.path.join(lock_home, 'locks'), sup_key + '.json', sup_lock)
    for name, local, title, where in (('sown', 'local_sown', 'sup', repo), ('smb', 'local_smb', 'Otra cosa', repo),
                                      ('ssv', 'local_ssv', 'trabajo', repo), ('sfree', 'local_sfree', 'libre', other)):
        put(sessions_dir, name + '.json', {'pid': os.getpid(), 'cwd': where, 'sessionId': 'cli-' + name, 'hostSessionId': local,
                                           'name': title, 'status': 'busy'})
    typing = u_text(2, 'sigue', origin={'kind': 'human'})
    sv_path = ag_transcript([old_human, typing] + busy)

    def sv_ask(session, cwd=repo, tool='AskUserQuestion', tool_input=None, records=None):
        payload = {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'session_id': session, 'cwd': cwd,
                   'transcript_path': ag_transcript(records) if records is not None else sv_path,
                   'tool_input': {} if tool_input is None else tool_input}
        return hook(payload)

    away = [old_human] + busy
    r = sv_ask('cli-ssv', records=away)
    reason = verdict(r).get('permissionDecisionReason', '')
    check('pre-production: a supervised session is denied a question while the developer is away',
          denied(r) and 'Esta sesión la supervisa «Supervisora P» (proj)' in reason and '\n' not in reason
          and 'no ha escrito aquí' in reason
          and 'decisiones_abiertas' in reason and 'pre-producción' in reason and 'despliegue-y-limites-duros.md' in reason
          and '~/.claude/skills/panel-de-decision/SKILL.md' in reason and 'ask-queue add' in reason
          and 'deja solo el recap' in reason)
    check('pre-production: ...also a wrap_up with ask/actions, but not a recap-only wrap_up',
          denied(sv_ask('cli-ssv', tool=wrap, tool_input={'recap': 'r', 'ask': '¿Sigo?'}, records=away))
          and denied(sv_ask('cli-ssv', tool=wrap, tool_input={'recap': 'r', 'actions': [{'label': 'Sí'}]}, records=away))
          and allowed(sv_ask('cli-ssv', tool=wrap, tool_input={'recap': 'r'}, records=away)))
    check('a supervised session the developer is driving (input 2 min ago) may ask them, '
          'AskUserQuestion and a wrap_up with ask, logged allow-present-supervised',
          allowed(sv_ask('cli-ssv')) and allowed(sv_ask('cli-ssv', tool=wrap, tool_input={'recap': 'r', 'ask': '¿Sigo?'}))
          and '\tallow-present-supervised\t' in open(os.path.join(ag_dir, 'decisions.log')).read())
    stale_here = [old_human, u_text(10, 'sigue con lo tuyo', origin={'kind': 'human'})] + busy
    asked_to = [old_human, u_text(10, 'pregúntame antes', origin={'kind': 'human'})] + busy
    check('no looser than a free session: the developer\'s message 10 min ago (past ASK_GATE_FRESH_MIN) does '
          'not let a supervised session ask; one that asks to be asked, inside the presence window, does',
          denied(sv_ask('cli-ssv', records=stale_here)) and 'ha pedido que se le pregunte' in verdict(sv_ask('cli-ssv', records=stale_here)).get('permissionDecisionReason', '')
          and allowed(sv_ask('cli-ssv', records=asked_to)))
    check('pre-production: an unknown session in the project\'s cwd is supervised too',
          denied(sv_ask('cli-nobody-here', records=away)))
    check('pre-production: a free session (project without a live lock) with the developer typing -> still allowed',
          allowed(sv_ask('cli-sfree', cwd=other)))
    r = sv_ask('cli-sfree', cwd=other, records=[old_human] + busy)
    check('pre-production: a free session with the developer away -> still deny-absent (new text)',
          denied(r) and 'no está delante' in verdict(r).get('permissionDecisionReason', '')
          and 'Esta sesión la supervisa' not in verdict(r).get('permissionDecisionReason', ''))
    check('pre-production: a mailbox of a live lock is allowed (developer away, and also typing)',
          allowed(sv_ask('cli-smb', records=[old_human] + busy)) and allowed(sv_ask('cli-smb')))
    # T10: ExitPlanMode and start_session(initiation "offer") park the session like a question
    plan_t, offer_t = 'ExitPlanMode', 'mcp__ccd_session__start_session'
    offer = {'initiation': 'offer', 'prompt': 'haz x'}
    r = sv_ask('cli-ssv', tool=plan_t, tool_input={'plan': 'hacer x'})
    reason = verdict(r).get('permissionDecisionReason', '')
    check('T10: a supervised session may not call ExitPlanMode: deny, Spanish one-liner, says to note the plan in the report',
          denied(r) and '\n' not in reason and 'Esta sesión la supervisa «Supervisora P» (proj)' in reason
          and 'ningún plan' in reason and 'informe' in reason and 'ejecútalo' in reason)
    r = sv_ask('cli-ssv', tool=offer_t, tool_input=offer)
    reason = verdict(r).get('permissionDecisionReason', '')
    check('T10: ...nor start_session with initiation «offer»: deny, says to do it here or use user_asked/own_initiative',
          denied(r) and '\n' not in reason and 'initiation «offer»' in reason and 'esta misma sesión' in reason
          and 'user_asked' in reason and 'own_initiative' in reason)
    check('T10: start_session with initiation user_asked / own_initiative / none passes the gate (it is not a question)',
          all(allowed(sv_ask('cli-ssv', tool=offer_t, tool_input=ti)) for ti in
              ({'initiation': 'user_asked'}, {'initiation': 'own_initiative'}, {'prompt': 'x'}, None)))
    r = sv_ask('cli-sown', tool=plan_t, tool_input={'plan': 'x'})
    check('T10: the lock owner is denied ExitPlanMode and offered sessions too, with the owner-flavoured head',
          denied(r) and 'ningún plan' in verdict(r).get('permissionDecisionReason', '')
          and denied(sv_ask('cli-sown', tool=offer_t, tool_input=offer)))
    check('T10: a free session (project without a supervisor) and the mailbox keep ExitPlanMode and offers, even with the '
          'developer away (the presence rule is for questions)',
          all(allowed(sv_ask(sid, cwd=cwd, tool=t, tool_input=ti, records=[old_human] + busy))
              for sid, cwd in (('cli-sfree', other), ('cli-smb', repo))
              for t, ti in ((plan_t, {'plan': 'x'}), (offer_t, offer))))
    check('T10: wrap_up with only a recap is still allowed for a supervised session (unchanged)',
          allowed(sv_ask('cli-ssv', tool=wrap, tool_input={'recap': 'r'})))
    t10_log = open(os.path.join(ag_dir, 'decisions.log')).read()
    check('T10: decisions.log records deny-plan, deny-offer, allow-plan and allow-offer',
          all(f'\t{d}\t' in t10_log for d in ('deny-plan', 'deny-offer', 'allow-plan', 'allow-offer')))

    def dialog_row(sid8, mins=2):
        when = datetime.fromtimestamp(time.time() - mins * 60).strftime('%Y-%m-%d %H:%M:%S')
        with open(ag_xlog, 'a') as fh:
            fh.write(f'{when}\t{sid8}\tdeny-dialog\tlocal_dest\twhy\n')

    dialog_row('cli-ssv')
    dialog_row('cli-sfre')
    r_sup = sv_ask('cli-ssv', records=[old_human] + busy)
    r_free = sv_ask('cli-sfree', cwd=other, records=[old_human] + busy)
    check('a supervised session with a recent cross-project deny-dialog and the developer away is STILL '
          'denied (a dialog there would park it waiting for them)',
          denied(r_sup) and 'Esta sesión la supervisa' in verdict(r_sup).get('permissionDecisionReason', ''))
    check('a free session (developer away) with a recent deny-dialog may still use the dialog once',
          allowed(r_free) and '\tallow-dialog\t' in open(os.path.join(ag_dir, 'decisions.log')).read())
    # the developer asked here for a message to another project; the cross-project gate's dialog confirms the developer's order
    asked_here = u_text(4, 'pregúntale a cada sesión supervisora', origin={'kind': 'human'})
    r_sup_here = sv_ask('cli-ssv', records=[old_human, asked_here] + busy)
    check('a supervised session with a recent deny-dialog and the developer typing here (4 min ago, inside '
          'the presence window) may open that dialog, logged allow-dialog-supervised',
          allowed(r_sup_here) and '\tallow-dialog-supervised\t' in open(os.path.join(ag_dir, 'decisions.log')).read())
    check('...a plan and an offered session stay denied in that same supervised session (they park it)',
          denied(sv_ask('cli-ssv', tool=plan_t, tool_input={'plan': 'x'}, records=[old_human, asked_here] + busy))
          and denied(sv_ask('cli-ssv', tool=offer_t, tool_input=offer, records=[old_human, asked_here] + busy)))
    peer_here = dict(u_text(4, 'pregúntale a cada sesión supervisora'), origin={'kind': 'peer', 'from': 'local_x'})
    check('a message from another session is no developer presence: the dialog stays denied',
          denied(sv_ask('cli-ssv', records=[old_human, peer_here] + busy)))
    # the supervisor itself, while the developer types in it, asks them exactly like a supervised session the developer drives
    check('the lock owner the developer is typing in (2 min ago) may ask them, AskUserQuestion and a wrap_up with ask, '
          'logged allow-present-owner',
          allowed(sv_ask('cli-sown')) and allowed(sv_ask('cli-sown', tool=wrap, tool_input={'recap': 'r', 'ask': '¿Sigo?'}))
          and '\tallow-present-owner\t' in open(os.path.join(ag_dir, 'decisions.log')).read())
    r = sv_ask('cli-sown', records=away)
    reason = verdict(r).get('permissionDecisionReason', '')
    check('...with the developer away the owner is still denied, with the owner text, which now says when '
          'it may ask',
          denied(r) and 'Eres la supervisora de proj' in reason and 'te está escribiendo aquí' in reason and '\n' not in reason)
    check('...the developer\'s message 10 min ago, not asking to be asked, does not let the owner ask; one asking to be '
          'asked does',
          denied(sv_ask('cli-sown', records=stale_here)) and allowed(sv_ask('cli-sown', records=asked_to)))
    dialog_row('cli-sown')
    check('the owner sent to a cross-project dialog for an order the developer gave there 4 min ago may open it, logged '
          'allow-dialog-owner; with only a message from another session it may not',
          allowed(sv_ask('cli-sown', records=[old_human, asked_here] + busy))
          and '\tallow-dialog-owner\t' in open(os.path.join(ag_dir, 'decisions.log')).read()
          and denied(sv_ask('cli-sown', records=[old_human, peer_here] + busy)))
    check('...a plan and an offered session stay denied to the owner even while the developer types',
          denied(sv_ask('cli-sown', tool=plan_t, tool_input={'plan': 'x'}))
          and denied(sv_ask('cli-sown', tool=offer_t, tool_input=offer)))
    os.remove(ag_xlog)
    dialog_row('cli-ssv', mins=30)  # a denial older than the 10-minute window
    just_now = u_text(2, 'sigue con eso', origin={'kind': 'human'})
    check('without a cross-project denial a supervised session the developer drives asks as a free one: '
          'the developer\'s message 2 min ago -> allowed; 4 min ago and not asking to be asked -> denied',
          allowed(sv_ask('cli-ssv', records=[old_human, just_now] + busy))
          and denied(sv_ask('cli-ssv', records=[old_human, asked_here] + busy)))
    os.remove(ag_xlog)
    check('pre-production: a stale unreleased lock (5000 s) still supervises: a question is denied with the developer away',
          (put(os.path.join(lock_home, 'locks'), sup_key + '.json', dict(sup_lock, heartbeat=hb_ago(5000))) or True)
          and denied(sv_ask('cli-ssv', records=away)) and allowed(sv_ask('cli-smb', records=[old_human] + busy)))
    check('pre-production: a lock silent for more than 24 h is no supervision: the session is free again (typing -> allowed)',
          (put(os.path.join(lock_home, 'locks'), sup_key + '.json', dict(sup_lock, heartbeat=hb_ago(86400 + 600))) or True)
          and allowed(sv_ask('cli-ssv')))
    put(os.path.join(lock_home, 'locks'), sup_key + '.json', sup_lock)
    sv_log = open(os.path.join(ag_dir, 'decisions.log')).read()
    check('pre-production: decisions.log records deny-supervised (with the lock key) and allow-mailbox',
          '\tdeny-supervised\t' in sv_log and f'live lock {sup_key}' in sv_log and '\tallow-mailbox\t' in sv_log)

    # questions session of a recently released lock: it presents the final batch after the supervisor let go
    os.remove(os.path.join(lock_home, 'locks', sup_key + '.json'))
    put(sessions_dir, 'cbx.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-cbx', 'hostSessionId': 'local_cbx',
                                   'name': 'Otra cosa', 'status': 'busy'})
    closed_dir = os.path.join(lock_home, 'closed')
    closed_path = os.path.join(closed_dir, sup_key + '.json')
    os.makedirs(closed_dir, exist_ok=True)

    def write_closed(*entries):
        with open(closed_path, 'w') as fh:
            fh.write('not json\n[1, 2]\n')  # bad lines are skipped
            for entry in entries:
                fh.write(json.dumps(entry, sort_keys=True) + '\n')

    def released(hours_ago, **extra):
        when = datetime.fromtimestamp(time.time() - hours_ago * 3600).astimezone().isoformat(timespec='seconds')
        return dict({'time': when, 'key': sup_key, 'project': 'proj', 'session': 'local_sown', 'verdict': 'PREPROD DEPLOYED'}, **extra)

    away = [old_human] + busy
    write_closed(released(1, mailbox='local_cbx'))
    check('questions session: the mailbox of a lock released 1 h ago may ask with no live lock (developer away too)',
          allowed(sv_ask('cli-cbx', records=away)) and allowed(sv_ask('cli-cbx')))
    check('questions session: ...that path is logged as allow-mailbox',
          '\tallow-mailbox\t' in open(os.path.join(ag_dir, 'decisions.log')).read())
    write_closed(released(8 * 24, mailbox='local_cbx'))
    r = sv_ask('cli-cbx', records=away)
    check('questions session: released 8 days ago (past the 7-day window) -> not recognised, denied as absent',
          denied(r) and 'no está delante' in verdict(r).get('permissionDecisionReason', ''))
    check('questions session: ASK_GATE_MAILBOX_CLOSED_DAYS widens the window (10 days -> allowed again)',
          allowed(hook({'hook_event_name': 'PreToolUse', 'tool_name': 'AskUserQuestion', 'session_id': 'cli-cbx', 'cwd': repo,
                        'transcript_path': ag_transcript(away), 'tool_input': {}},
                       hook_env=dict(env, ASK_GATE_MAILBOX_CLOSED_DAYS='10'))))
    write_closed(released(1, mailbox='local_other'), released(1))
    check('questions session: a released lock that names another mailbox, or none, does not cover this session',
          denied(sv_ask('cli-cbx', records=away)))
    write_closed(released(1, mailbox='local_cbx'))
    check('released lock: another session of the project is free, not supervised (typing -> allowed, away -> deny-absent)',
          allowed(sv_ask('cli-ssv'))
          and 'no está delante' in verdict(sv_ask('cli-ssv', records=away)).get('permissionDecisionReason', '')
          and 'Esta sesión la supervisa' not in verdict(sv_ask('cli-ssv', records=away)).get('permissionDecisionReason', ''))
    if os.path.exists(closed_path):
        os.remove(closed_path)
    os.remove(os.path.join(sessions_dir, 'cbx.json'))
    put(os.path.join(lock_home, 'locks'), sup_key + '.json', sup_lock)

    real_alive = session_roles.mailbox_alive
    texts = {}
    try:
        session_roles.mailbox_alive = lambda mailbox: True
        texts['question alive'] = json.loads(deny.deny_question({'project': 'proj', 'key': 'k', 'mailbox': 'local_qs'}, 'local_o'))
        session_roles.mailbox_alive = lambda mailbox: False
        texts['question missing'] = json.loads(deny.deny_question({'project': 'proj', 'key': 'k'}, 'local_o'))
        texts['question archived'] = json.loads(deny.deny_question({'project': 'proj', 'key': 'k', 'mailbox': 'local_gone'}, 'local_o'))
    finally:
        session_roles.mailbox_alive = real_alive
    texts['absent'] = json.loads(deny.deny_absent(20))
    texts['supervised'] = json.loads(deny.deny_supervised(sup_lock, 20))
    reasons = {k: v['hookSpecificOutput']['permissionDecisionReason'] for k, v in texts.items()}
    check('deny texts: none of the five variants says «buzón» (it is the questions session now)',
          len(reasons) == 5 and not any('buzón' in r.lower() for r in reasons.values()))
    check('deny texts: the owner variants send the final batch to the questions session once each child session is archived or parked in ask-queue',
          all('sesión hija está archivada o' in reasons[k] and 'aparcada con su' in reasons[k] and 'conservas el cerrojo de guardia' in reasons[k] and 'sin informe aparte' in reasons[k] and '--radical --cost' in reasons[k]
              for k in ('question alive', 'question missing', 'question archived'))
          and 'sesión de preguntas es local_qs (SendMessage)' in reasons['question alive']
          and 'ábrela' in reasons['question missing'] and 'La sesión de preguntas local_gone guardada' in reasons['question archived'])
    check('deny texts: absent and supervised ones say the final batch is asked in the questions session',
          all('sesión de preguntas' in reasons[k] and 'sesión hija está archivada o aparcada con su decisión en ask-queue' in reasons[k] for k in ('absent', 'supervised')))
    check('deny texts: the owner variants name the partial batch of blocking questions next to the radical path',
          all('tanda parcial' in reasons[k] and 'ask-queue list --due' in reasons[k] and 'ASKDUE' in reasons[k]
              and '\n' not in reasons[k] for k in ('question alive', 'question missing', 'question archived')))
    check('deny texts: absent and supervised ones teach a real --blocks and --order for an order of the developer',
          all('--order "<sus palabras>"' in reasons[k] and 'tanda parcial' in reasons[k] and '--blocks' in reasons[k]
              for k in ('absent', 'supervised')))

    # 11c. partial batch of blocking questions: ask-queue decides what is due, beat and the watcher tell the owner
    ad_repo = os.path.realpath(os.path.join(tmp, 'askdue-proj'))
    make_repo(ad_repo)
    ad_locks = set(os.listdir(os.path.join(lock_home, 'locks')))
    try:
        r = run('acquire', '--dir', ad_repo, '--session', 'local_ad')
        check('ASKDUE: a fresh project takes its own lock', r.returncode == 0 and 'ACQUIRED' in r.stdout)
        r = run('beat', '--dir', ad_repo, '--session', 'local_ad')
        check('ASKDUE: an empty queue -> beat says nothing about it', r.returncode == 0 and 'ASKDUE' not in r.stderr)
        aq('add', '--project', ad_repo, '--question', '¿Qué valor pongo?', '--default', 'Esperar', '--why', 'w',
           '--blocks', 'nada: solo su archivado')
        aq('add', '--project', ad_repo, '--question', '¿Qué dato falta?', '--default', 'Esperar', '--why', 'w',
           '--blocks', 'la tarea ordenada')
        r = run('beat', '--dir', ad_repo, '--session', 'local_ad')
        check('ASKDUE: young items, or items that block nothing, are not due', r.returncode == 0 and 'ASKDUE' not in r.stderr)
        q_order = aq('add', '--project', ad_repo, '--question', '¿Qué cuenta uso?', '--default', 'Esperar', '--why', 'w',
                     '--blocks', 'la tarea ordenada', '--order', 'hazlo primero')
        r = run('beat', '--dir', ad_repo, '--session', 'local_ad')
        check('ASKDUE: an --order item -> beat tells the owner on stderr, stdout unchanged',
              r.returncode == 0 and r.stdout.strip().startswith('BEAT ') and f'ASKDUE 1 {q_order} ' in r.stderr
              and 'ask-queue list --due' in r.stderr)
        ad_saved = {k: os.environ.get(k) for k in ('ASK_QUEUE_BIN', 'ASK_QUEUE_DIR', 'SUPERVISOR_LOCK_HOME')}
        os.environ.update({k: env[k] for k in ad_saved})
        try:
            from . import askdue
            ad_project = projects.resolve(ad_repo)
            first, again = askdue.askdue_events(ad_project), askdue.askdue_events(ad_project)
        finally:
            for k, v in ad_saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        check('ASKDUE: the watcher announces a set of due ids once, and it is a guard event',
              len(first) == 1 and first[0].startswith(f'ASKDUE 1 {q_order} ') and again == [] and 'ASKDUE' in watch.GUARD_EVENTS)
        aq('asked', q_order, '--to', 'local_box')
        r = run('beat', '--dir', ad_repo, '--session', 'local_ad')
        check('ASKDUE: once presented (asked) the item is not due any more', r.returncode == 0 and 'ASKDUE' not in r.stderr)
    finally:
        for name in set(os.listdir(os.path.join(lock_home, 'locks'))) - ad_locks:
            os.remove(os.path.join(lock_home, 'locks', name))

    def a_text(mins, text):
        return {'type': 'assistant', 'timestamp': stamp(mins),
                'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}

    def sv_stop(session, records=None, cwd=repo, **extra):
        payload = dict({'hook_event_name': 'Stop', 'session_id': session, 'cwd': cwd, 'stop_hook_active': False}, **extra)
        if records is not None:
            payload['transcript_path'] = ag_transcript(records)
        return hook(payload)

    def sv_blocked(r):
        out = json.loads(r.stdout) if r.stdout else {}
        return r.returncode == 0 and out.get('decision') == 'block' and 'Tu mensaje final termina en una pregunta' in out.get('reason', '')

    ending_q = [old_human, a_tool(3), u_result(3), a_text(1, 'Hecho lo anterior.\n\n¿Quieres que despliegue ahora?')]
    r = sv_stop('cli-ssv', ending_q)
    reason = json.loads(r.stdout or '{}').get('reason', '')
    check('Stop supervised: the final paragraph ends in `?` -> block, naming the supervisor, project and panel',
          sv_blocked(r) and '«Supervisora P» (proj)' in reason and 'decisiones_abiertas' in reason
          and '~/.claude/skills/panel-de-decision/SKILL.md' in reason and 'termina igual' in reason and '\n' not in reason)
    check('a supervised session the developer is driving (input 2 min ago) may end on a question',
          sv_stop('cli-ssv', [old_human, u_text(2, 'ayúdame con esto', origin={'kind': 'human'}),
                              a_text(1, 'Hecho lo anterior.\n\n¿Marco la casilla yo o tú?')]).stdout == '')
    check('Stop supervised: markdown/quote closers after the `?` still count',
          all(sv_blocked(sv_stop('cli-ssv', [old_human, a_text(1, f'Resumen.\n\n{tail}')]))
              for tail in ('**¿Sigo?**', '«¿Sigo?»', '`¿Sigo?`', '(¿Sigo?)', '_¿Sigo?_  ')))
    put(os.path.join(lock_home, 'locks'), sup_key + '.json', dict(sup_lock, heartbeat=hb_ago(5000)))
    check('Stop supervised: a stale unreleased lock (5000 s) still blocks a final question',
          sv_blocked(sv_stop('cli-ssv', ending_q)))
    put(os.path.join(lock_home, 'locks'), sup_key + '.json', dict(sup_lock, heartbeat=hb_ago(86400 + 600)))
    check('Stop supervised: a lock silent for more than 24 h does not',
          sv_stop('cli-ssv', ending_q).stdout == '')
    put(os.path.join(lock_home, 'locks'), sup_key + '.json', sup_lock)
    check('Stop supervised: stop_hook_active -> never blocked',
          sv_stop('cli-ssv', ending_q, stop_hook_active=True).stdout == '')
    check('Stop supervised: the final paragraph does not end in `?` -> nothing',
          sv_stop('cli-ssv', [old_human, a_text(1, 'Todo desplegado en pre-producción.')]).stdout == '')
    check('Stop supervised: a `?` only in an earlier paragraph -> nothing',
          sv_stop('cli-ssv', [old_human, a_text(1, 'Me preguntaba: ¿y si falla?\n\n' + '\n'.join(f'Línea {i} del resumen.' for i in range(14)))]).stdout == '')
    check('Stop supervised (T7): a question 4 lines above the end, then a short list -> block',
          sv_blocked(sv_stop('cli-ssv', [old_human, a_text(1, 'Terminado el despliegue.\n\n¿Quieres que lo despliegue?\n\n- opción A\n- opción B\n- opción C')])))
    check('Stop supervised (T7): `?` followed by a short tail in the last paragraph -> block',
          sv_blocked(sv_stop('cli-ssv', [old_human, a_text(1, 'Listo.\n\n¿Despliego ahora? (responde sí o no)')]))
          and sv_blocked(sv_stop('cli-ssv', [old_human, a_text(1, 'Listo. ¿Despliego ahora? Dime.')])))
    check('Stop supervised (T7): `?` inside a code block, a `>` quote or a «…» span is not a question; a long tail neither',
          all(sv_stop('cli-ssv', [old_human, a_text(1, msg)]).stdout == '' for msg in (
              'Hecho.\n\n```\nwhile true; do echo "¿ok?"\n```\n\nFin del informe.',
              'Hecho.\n\n> ¿Sigo?\n\nFin del informe.',
              'El log decía «¿Sigo?» y seguí con lo documentado.',
              'Me pregunté si era seguro (¿lo es?) y lo comprobé en el entorno de pre-producción con los datos de prueba.')))
    check('Stop supervised: the newest assistant record is a tool call (older text had a `?`) -> nothing',
          sv_stop('cli-ssv', [old_human, a_text(5, '¿Sigo?'), u_text(4, 'sí', origin={'kind': 'human'}), a_tool(1)]).stdout == '')
    check('Stop supervised: last_assistant_message in the payload is used when present (and wins over the transcript)',
          sv_blocked(sv_stop('cli-ssv', [old_human, a_text(1, 'Fin.')], last_assistant_message='Dime algo.\n\n¿Despliego?'))
          and sv_stop('cli-ssv', ending_q, last_assistant_message='Fin.').stdout == '')
    check('Stop supervised: no readable transcript -> fails open', sv_stop('cli-ssv').stdout == ''
          and hook({'hook_event_name': 'Stop', 'session_id': 'cli-ssv', 'cwd': repo, 'transcript_path': '/nonexistent/t.jsonl'}).stdout == '')
    check('Stop free session (project without a live lock) ending in `?` -> nothing',
          sv_stop('cli-sfree', ending_q, cwd=other).stdout == '')
    check('Stop question mailbox ending in `?` -> nothing', sv_stop('cli-smb', ending_q).stdout == '')
    r = sv_stop('cli-sown', ending_q, background_tasks=[])
    out = json.loads(r.stdout or '{}')
    check('Stop owner: unchanged (no watcher / skill logic, never the supervised-question text)',
          out.get('decision') == 'block' and 'Tu mensaje final termina en una pregunta' not in out.get('reason', '')
          and ('cerrojo' in out.get('reason', '') or 'vigilante' in out.get('reason', '')))
    big_tail = os.path.join(tmp, 'ag', 'bigstop.jsonl')
    filler_s = json.dumps(a_tool(300, command='x' * 900), separators=(',', ':'))
    with open(big_tail, 'w') as fh:
        fh.write(json.dumps(old_human, separators=(',', ':')) + '\n')
        for _ in range(24000):
            fh.write(filler_s + '\n')
        fh.write(json.dumps(a_text(1, 'Listo.\n\n¿Sigo?'), separators=(',', ':')) + '\n')
    began = time.perf_counter()
    r = hook({'hook_event_name': 'Stop', 'session_id': 'cli-ssv', 'cwd': repo, 'stop_hook_active': False, 'transcript_path': big_tail})
    took_stop = time.perf_counter() - began
    check(f'Stop supervised: {os.path.getsize(big_tail) // (1 << 20)} MB transcript read from the tail ({took_stop:.2f} s, < 3 s)',
          sv_blocked(r) and took_stop < 3)
    stop_log = open(os.path.join(lock_home, 'hook.log')).read() if os.path.exists(os.path.join(lock_home, 'hook.log')) else ''
    check('Stop supervised: the block is logged in hook.log without message text',
          'stop-supervised-question block' in stop_log and '¿Sigo?' not in stop_log)
    clear_locks()
    clear_sessions()

    def xlog(mins, sid8, decision='deny-dialog'):
        when = datetime.fromtimestamp(time.time() - mins * 60).strftime('%Y-%m-%d %H:%M:%S')
        with open(ag_xlog, 'a') as fh:
            fh.write(f'{when}\t{sid8}\t{decision}\tlocal_dest\twhy\n')

    xlog(30, 'cli-nobo')
    xlog(2, 'cli-other', 'deny-dialog')
    xlog(2, 'cli-nobo', 'allow-after-dialog')
    check('ask gate: an old deny-dialog, another session\'s, or another decision does not open the gate',
          denied(ag_ask([old_human] + busy, session='cli-nobody')))
    xlog(4, 'cli-nobo')
    check('ask gate: a deny-dialog of this session within 10 min -> allowed', allowed(ag_ask([old_human] + busy, session='cli-nobody')))
    os.remove(ag_xlog)
    check('ask gate: kill switch env ASK_GATE=off -> allowed', allowed(ag_ask([old_human] + busy, hook_env=dict(env, ASK_GATE='off'))))
    open(os.path.join(ag_dir, 'disabled'), 'w').close()
    check('ask gate: kill switch file -> allowed', allowed(ag_ask([old_human] + busy)))
    os.remove(os.path.join(ag_dir, 'disabled'))
    check('ask gate: switched back on -> denied again', denied(ag_ask([old_human] + busy)))
    check('ask gate: no transcript to judge from -> allowed (fail open)', allowed(ag_ask(None, session='cli-nobody')))
    errors_log = os.path.join(ag_dir, 'errors.log')
    for bad in ('not json PreToolUse', '[1,2] PreToolUse', ''):
        r = hook(None, raw=bad)
        check(f'ask gate: malformed payload {bad[:14]!r} -> exit 0, no output', allowed(r))
    check('ask gate: malformed payloads left a traceback in errors.log',
          os.path.exists(errors_log) and open(errors_log).read().count('Traceback') >= 2)
    saved_env = {k: os.environ.get(k) for k in env if k.startswith(('SUPERVISOR_', 'ASK_GATE'))}
    os.environ.update({k: v for k, v in env.items() if k.startswith(('SUPERVISOR_', 'ASK_GATE'))})
    real_scan = human_turns.last_human_input

    def boom(*args):
        raise RuntimeError('boom')

    human_turns.last_human_input = boom
    try:
        out = hook_mod.hook_decide(json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'AskUserQuestion', 'session_id': 'cli-ag',
                                      'transcript_path': ag_transcript([old_human])}))
    finally:
        human_turns.last_human_input = real_scan
        for k, v in saved_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    check('ask gate: an exception inside the gate -> allowed and the traceback is logged',
          out == '' and 'RuntimeError: boom' in open(errors_log).read())

    def over_budget(*args):
        raise TimeoutError('transcript scan over budget')

    human_turns.last_human_input = over_budget
    os.environ.update({k: v for k, v in env.items() if k.startswith(('SUPERVISOR_', 'ASK_GATE'))})
    try:
        out = hook_mod.hook_decide(json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'AskUserQuestion', 'session_id': 'cli-ag',
                                      'transcript_path': ag_transcript([old_human])}))
    finally:
        human_turns.last_human_input = real_scan
        for k, v in saved_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    to_rows = [ln.split('\t') for ln in open(os.path.join(ag_dir, 'decisions.log')).read().splitlines()]
    check('ask gate: a TimeoutError reading the transcript counts as absent -> denied, logged deny-timeout (not allow-error)',
          json.loads(out)['hookSpecificOutput']['permissionDecision'] == 'deny'
          and 'no está delante' in json.loads(out)['hookSpecificOutput']['permissionDecisionReason']
          and to_rows[-1][2] == 'deny-timeout')
    # a big transcript: only the tail inside the window is read
    big = os.path.join(tmp, 'ag', 'big.jsonl')
    filler = json.dumps(a_tool(300, command='x' * 900), separators=(',', ':'))
    with open(big, 'w') as fh:
        fh.write(json.dumps(old_human, separators=(',', ':')) + '\n')
        for _ in range(24000):
            fh.write(filler + '\n')
        fh.write(json.dumps(u_text(1, 'sigue', origin={'kind': 'human'}), separators=(',', ':')) + '\n')
    payload_big = {'hook_event_name': 'PreToolUse', 'tool_name': 'AskUserQuestion', 'session_id': 'cli-ag', 'transcript_path': big}
    began = time.perf_counter()
    r_present = hook(payload_big)
    took_present = time.perf_counter() - began
    with open(big) as src, open(big + '.absent', 'w') as dst:
        dst.writelines(line for line in src if 'sigue' not in line)
    os.replace(big + '.absent', big)
    began = time.perf_counter()
    r_absent = hook(payload_big)
    took_absent = time.perf_counter() - began
    check(f'ask gate: {os.path.getsize(big) // (1 << 20)} MB transcript, present {took_present:.2f} s / absent {took_absent:.2f} s '
          f'(whole hook process, < 1.5 s each)',
          allowed(r_present) and denied(r_absent) and took_present < 1.5 and took_absent < 1.5)
    log_rows = [ln.split('\t') for ln in open(os.path.join(ag_dir, 'decisions.log')).read().splitlines()]
    decisions = {row[2] for row in log_rows}
    check('ask gate: decisions.log has `ts sid8 decision tool reason` rows for allow and deny',
          all(len(row) == 5 and row[1] for row in log_rows) and {'deny-absent', 'deny-supervised', 'allow-fresh', 'allow-requested', 'deny-stale-presence', 'allow-mailbox', 'allow-dialog',
                                                                  'allow-off', 'allow-no-transcript', 'allow-error', 'owner-deny', 'deny-timeout'} <= decisions)

    # 12. hook Stop: the skill changed on disk after the owner loaded it
    clear_locks()
    clear_sessions()
    os.utime(skill, (t0, t0))
    run('acquire', '--dir', repo, '--session', 'local_sc', '--title', 'sup sc')
    put(sessions_dir, 'sc.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-sc', 'hostSessionId': 'local_sc', 'name': 'sc', 'status': 'busy'})
    put(sessions_dir, 'sx.json', {'pid': os.getpid(), 'cwd': repo, 'sessionId': 'cli-sx', 'hostSessionId': 'local_sx', 'name': 'sx', 'status': 'busy'})
    sc_task = dict(armed_task, command=armed_task['command'].replace('local_sup', 'local_sc'))

    def stop_sc(session='cli-sc', **extra):
        return dict({'hook_event_name': 'Stop', 'session_id': session, 'cwd': repo, 'stop_hook_active': False}, **extra)

    r = hook(stop_sc(background_tasks=[sc_task]))
    out = json.loads(r.stdout or '{}')
    check('hook Stop: a fresh lock (no skill_seen) blocks even with an armed watcher, with the «no consta» text',
          r.returncode == 0 and out.get('decision') == 'block'
          and out.get('reason', '').startswith('Tienes el cerrojo de supervisor de proj y no consta que hayas cargado la skill supervisa-sesiones. Antes de terminar el turno: ')
          and 'invócala con la herramienta Skill' in out['reason'] and 'abrir la sesión de preguntas y registrarla con beat --mailbox' in out['reason']
          and 'supervisor-lock beat --session local_sc --skill-seen' in out['reason'] and 'supervisor-lock release' in out['reason']
          and 'cambió en disco' not in out['reason'])
    r = hook(stop_sc(stop_hook_active=True, background_tasks=[sc_task]))
    check('hook Stop: the «no consta» block happens once: stop_hook_active -> nothing', r.returncode == 0 and r.stdout == '')
    r = hook(stop_sc(stop_hook_active=True, background_tasks=[]))
    check('hook Stop: stop_hook_active, never read, no watcher -> existing watcher logic, not the «no consta» text', 'no consta' not in r.stdout and r.returncode == 0)
    run('beat', '--dir', repo, '--session', 'local_sc', '--skill-seen')
    check('hook Stop: skill_seen equal to the file + armed watcher -> nothing', hook(stop_sc(background_tasks=[sc_task])).stdout == '')
    os.utime(skill, (t0 + 600, t0 + 600))
    r = hook(stop_sc(background_tasks=[sc_task]))
    out = json.loads(r.stdout or '{}')
    hhmm = datetime.fromtimestamp(t0 + 600).strftime('%H:%M')
    check('hook Stop: skill newer than skill_seen blocks even with an armed watcher, with the Spanish text',
          r.returncode == 0 and out.get('decision') == 'block'
          and out.get('reason', '').startswith(f'La skill supervisa-sesiones cambió en disco ({hhmm}) después de que la cargaras. Antes de terminar el turno: ')
          and 'vuelve a leer las referencias que estés usando' in out['reason']
          and 'supervisor-lock beat --session local_sc --skill-seen' in out['reason'] and 'Rearma también el vigilante' in out['reason'])
    check('hook Stop: skill block also when no watcher is armed (skill text first)',
          'La skill supervisa-sesiones' in json.loads(hook(stop_sc(background_tasks=[])).stdout or '{}').get('reason', ''))
    r = hook(stop_sc(stop_hook_active=True, background_tasks=[sc_task]))
    check('hook Stop: stop_hook_active -> no skill block (falls through to the armed watcher: nothing)', r.returncode == 0 and r.stdout == '')
    r = hook(stop_sc(stop_hook_active=True, background_tasks=[]))
    check('hook Stop: stop_hook_active and no watcher -> existing logic, not the skill text', 'La skill' not in r.stdout and r.returncode == 0)
    check('hook Stop: a non-owner gets nothing although the skill changed', hook(stop_sc(session='cli-sx', background_tasks=[])).stdout == '')
    run('beat', '--dir', repo, '--session', 'local_sc', '--skill-seen')
    check('hook Stop: after beat --skill-seen + armed watcher -> not blocked', hook(stop_sc(background_tasks=[sc_task])).stdout == '')
    check('hook Stop: after beat --skill-seen, no watcher -> the usual watcher block, not the skill one',
          'vigilante' in json.loads(hook(stop_sc(background_tasks=[])).stdout or '{}').get('reason', '')
          and 'La skill' not in hook(stop_sc(background_tasks=[])).stdout)
    data = load()
    data.pop('skill_seen', None)
    save(data)
    os.utime(skill, (time.time() - 3600, time.time() - 3600))
    check('hook Stop: no skill_seen, file older than started -> «no consta» block (never read)', 'no consta que hayas cargado' in hook(stop_sc(background_tasks=[sc_task])).stdout)
    os.utime(skill, (time.time() + 60, time.time() + 60))
    check('hook Stop: no skill_seen, file newer than started -> «no consta» block', 'no consta que hayas cargado' in hook(stop_sc(background_tasks=[sc_task])).stdout)
    os.utime(skill, (t0, t0))
    for n in range(2):
        put_lock(f'k-stp{n}', f'local_stp{n}', 10)
    saved = {k: os.environ.get(k) for k in env if k.startswith(('SUPERVISOR_', 'ASK_GATE'))}
    os.environ.update({k: v for k, v in env.items() if k.startswith(('SUPERVISOR_', 'ASK_GATE'))})
    began = time.perf_counter()
    speedy = hook_mod.hook_decide(json.dumps(stop_sc(session='cli-not-an-owner', background_tasks=[])))
    took = time.perf_counter() - began
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    check(f'hook Stop: 3 locks + 400 app records, non-owner -> \'\' in {took:.2f} s (< 0.3)', speedy == '' and took < 0.3)


    # 30. cloud sessions of the project and its jobs in the machine queue: none is left without a verdict and an action.
    # The cloud provider is optional and not shipped: a sandbox stand-in reads the sessions from a json file.
    crepo = os.path.realpath(os.path.join(tmp, 'cproj'))
    make_repo(crepo)
    sh('git', 'remote', 'add', 'origin', 'https://github.com/t/cproj.git', cwd=crepo)
    ct_state = os.path.join(tmp, 'ct-state')
    os.makedirs(ct_state)
    api = os.path.join(tmp, 'cloud-api.json')
    sent_log = os.path.join(tmp, 'claude-sent.log')
    heavy_json = os.path.join(tmp, 'heavy.json')

    def iso_utc(ago):
        return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - ago))

    def iso_local(ago):
        return datetime.fromtimestamp(time.time() - ago).astimezone().isoformat(timespec='seconds')

    def cs(sid, repo_slug='t/cproj', kind='anthropic_cloud', worker='idle', bucket='completed', ago=3 * 3600, needs=''):
        return {'id': 'cse_' + sid, 'title': 'T ' + sid, 'environment_kind': kind, 'status': 'active',
                'worker_status': worker, 'status_bucket': bucket, 'last_event_at': iso_utc(ago),
                'config': {'sources': [{'type': 'git_repository', 'url': f'https://github.com/{repo_slug}'}],
                           'outcomes': [{'type': 'git_repository',
                                         'git_info': {'repo': repo_slug, 'branches': ['claude/' + sid]}}]},
                'external_metadata': {'post_turn_summary': {'needs_action': needs}}}

    with open(api, 'w') as fh:
        json.dump({'sessions': [cs('check'), cs('recent', ago=600),
                                cs('working', worker='running', bucket='working', ago=60),
                                cs('hung', worker='running', bucket='working', ago=3600),
                                cs('waiting', bucket='blocked', needs='confirm X'), cs('runner'), cs('held'),
                                cs('asking', bucket='blocked', needs='¿sigo?', ago=300),
                                cs('foreign', repo_slug='t/other'), cs('bridge', kind='bridge')]}, fh)
    fake_cloud = os.path.join(tmp, 'fake-cloud-tests')
    with open(fake_cloud, 'w') as fh:
        fh.write(FAKE_CLOUD_PROVIDER)
    for name, body in (('fake-claude', f'echo "$@" >> {sent_log}; echo "Sent to cloud session"'),
                       ('fake-heavy-json', f'cat {heavy_json}')):
        with open(os.path.join(tmp, name), 'w') as fh:
            fh.write(f'#!/bin/sh\n{body}\n')
        os.chmod(os.path.join(tmp, name), 0o755)
    sleepers = [subprocess.Popen(['sleep', '120'], cwd=crepo), subprocess.Popen(['sleep', '120'], cwd=other)]
    with open(heavy_json, 'w') as fh:
        json.dump({'queue': [{'pid': sleepers[0].pid, 'position': 1, 'label': 'mi suite', 'project': 'cproj',
                              'queued': iso_local(25 * 60)},
                             {'pid': sleepers[1].pid, 'position': 2, 'label': 'suite de otro', 'project': 'other',
                              'queued': iso_local(40 * 60)}],
                   'jobs': [{'pid': me, 'slots': [0], 'label': 'trabajo ajeno', 'project': 'other', 'cwd': other,
                             'started_ts': time.time() - 3 * 3600},
                            {'pid': me, 'slots': [1], 'label': 'mi smoke', 'project': 'cproj', 'cwd': crepo,
                             'started_ts': time.time() - 2 * 3600}],
                   'light': {'queue': [], 'jobs': []}}, fh)
    cenv = dict(env, CLOUD_TESTS_API_FAKE=api, CLOUD_TESTS_STATE=ct_state, CLOUD_TESTS_CLAUDE=os.path.join(tmp, 'fake-claude'),
                SUPERVISOR_HEAVY_JOB=os.path.join(tmp, 'fake-heavy-json'), SUPERVISOR_CLOUD_TESTS=fake_cloud)
    crun = lambda *a: subprocess.run([sys.executable, runtime.ENTRY, *a], capture_output=True, text=True, env=cenv)
    ckey = json.loads(crun('project', '--dir', crepo, '--json').stdout)['key']
    with open(os.path.join(ct_state, ckey + '.json'), 'w') as fh:
        json.dump({'project': ckey, 'repo': 't/cproj', 'runner': {'session': 'session_runner'}, 'runs': {}}, fh)
    crun('acquire', '--dir', crepo, '--session', 'local_cown', '--title', 'cloud')
    crun('beat', '--dir', crepo, '--session', 'local_cown', '--skill-seen')
    crun('hold', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_held', '--reason', 'regla X')
    r = crun('cloud', '--dir', crepo, '--json')
    verdicts = {x['id'][4:]: x['verdict'] for x in json.loads(r.stdout or '{}').get('rows', [])}
    check('cloud: each cloud session of the repo gets its verdict (CHECK RECENT WORKING HUNG WAITING RUNNER HOLD)',
          verdicts == {'check': 'CHECK', 'recent': 'RECENT', 'working': 'WORKING', 'hung': 'HUNG',
                       'waiting': 'WAITING', 'runner': 'RUNNER', 'held': 'HOLD', 'asking': 'RECENT'})
    r = crun('cloud', '--dir', crepo)
    check('cloud: the text census says what to do with each one and counts what is due',
          'cloud: 3 to act on now' in r.stdout and 'cloud-archive' in r.stdout and 'cloud-tests sweep' in r.stdout)
    r = crun('cloud', '--dir', repo)
    check('cloud: a project with no GitHub remote has none (and asks no API)', r.returncode == 0 and 'cloud: 0 to act' in r.stdout)

    pr = subprocess.Popen([sys.executable, runtime.ENTRY, 'wait', '--dir', crepo, '--owner', 'local_cown', '--interval', '0.2',
                           '--timeout', '8'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=cenv)
    out, _ = pr.communicate(timeout=60)
    check('wait: cloud sessions already due before the wait started are announced (CLOUD HUNG, WAITING, CHECK)',
          all(f'CLOUD cse_{x} {v}' in out for x, v in (('hung', 'HUNG'), ('waiting', 'WAITING'), ('check', 'CHECK'))))
    check('wait: working, recent, held and runner cloud sessions are not announced',
          not any(f'cse_{x} ' in out for x in ('working', 'recent', 'held', 'runner', 'foreign', 'bridge', 'asking')))
    check('wait: a job of the project queued 25 min is announced with who holds the slots (QUEUED)',
          f'QUEUED pid={sleepers[0].pid}' in out and 'trabajo ajeno' in out and 'mi smoke' in out)
    check('wait: a job of another project in the queue is not this supervisor\'s QUEUED', f'pid={sleepers[1].pid}' not in out)
    check('wait: a job of the project holding a slot 2 h while others queue is announced (SLOTHELD)',
          'SLOTHELD pid=' in out and '«mi smoke»' in out and 'suite de otro' in out)
    pr = subprocess.Popen([sys.executable, runtime.ENTRY, 'wait', '--dir', crepo, '--owner', 'local_cown', '--interval', '0.2',
                           '--timeout', '2', '--guard'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=cenv)
    out2, _ = pr.communicate(timeout=60)
    check('wait: each item is announced once (the next wait, on guard, is quiet about them)',
          'CLOUD' not in out2 and 'QUEUED' not in out2 and 'TIMEOUT' in out2)
    check('wait: CLOUD, QUEUED and SLOTHELD wake a supervisor on guard', {'CLOUD', 'QUEUED', 'SLOTHELD'} <= set(watch.GUARD_EVENTS))

    r = crun('cloud-archive', '--dir', crepo, '--session', 'local_other', '--target', 'cse_check', '--reason', 'x')
    check('cloud-archive: only the owner of the lock', r.returncode == 5 and 'ARCHIVED' not in r.stdout)
    r = crun('cloud-archive', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_working', '--reason', 'x')
    check('cloud-archive: a working session is refused', r.returncode == 2 and 'cse_working' not in str(
        json.load(open(api)).get('archived')) and ('trabajando' in r.stderr or 'puede llevarla el desarrollador' in r.stderr))
    r = crun('cloud-send', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_asking', '--text', 'sí')
    check('cloud-send: a cloud session with activity in the last 20 min may be the developer\'s: refused, not answered for them',
          r.returncode == 2 and 'puede llevarla el desarrollador' in r.stderr and not os.path.exists(sent_log))
    r = crun('cloud-archive', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_asking', '--reason', 'x')
    check('cloud-archive: the same for archiving it', r.returncode == 2 and 'puede llevarla el desarrollador' in r.stderr)
    r = crun('cloud-archive', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_check')
    check('cloud-archive: --reason (what was checked) is required', r.returncode == 2 and 'reason' in r.stderr)
    r = crun('cloud-archive', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_foreign', '--reason', 'x')
    check('cloud-archive: a session of another repository is refused', r.returncode == 2)
    r = crun('cloud-archive', '--dir', crepo, '--session', 'local_cown', '--target', 'session_check', '--reason', 'rama integrada')
    with open(api) as fh:
        st = json.load(fh)
    check('cloud-archive: archives through the API (session_ and cse_ ids are the same) and logs it',
          r.returncode == 0 and 'ARCHIVED cse_check' in r.stdout and 'cse_check' in st.get('archived', [])
          and 'ARCHIVED ' + ckey + ' cse_check' in open(os.path.join(lock_home, 'cloud-actions.log')).read())
    r = crun('cloud', '--dir', crepo, '--json')
    check('cloud: an archived session leaves the census at once',
          'cse_check' not in {x['id'] for x in json.loads(r.stdout or '{}').get('rows', [])})
    r = crun('cloud-send', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_waiting', '--text', 'sí, sigue')
    check('cloud-send: the answer goes to the cloud session through the CLI',
          r.returncode == 0 and 'SENT cse_waiting' in r.stdout and os.path.exists(sent_log)
          and 'session_waiting' in open(sent_log).read() and 'sí, sigue' in open(sent_log).read())

    saved = {k: os.environ.get(k) for k in cenv if k.startswith(('SUPERVISOR_', 'CLOUD_TESTS_'))}
    os.environ.update({k: v for k, v in cenv.items() if k.startswith(('SUPERVISOR_', 'CLOUD_TESTS_'))})
    try:
        cowner = lock_mod.Store().read(ckey)
        reason = cloud.cloud_block(cowner, 'local_cown')
        check('Stop hook: blocks a supervisor while cloud sessions of its project wait, naming them with the commands',
              'cse_waiting' in reason and 'cse_hung' in reason and 'cloud-archive' in reason and 'cloud-send' in reason
              and 'cse_check' not in reason and 'cse_held' not in reason)
        check('Stop hook: not again within CLOUD_BLOCK_EVERY_S', cloud.cloud_block(cowner, 'local_cown') == '')
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    put(sessions_dir, 'cown.json', {'pid': me, 'cwd': crepo, 'hostSessionId': 'local_cown', 'status': 'idle'})
    yes_cenv = dict(cenv, SUPERVISOR_USAGE='yes')
    crevive = lambda *a: subprocess.run([sys.executable, runtime.ENTRY, 'revive', *a], capture_output=True, text=True, env=yes_cenv)
    r = crevive('--json')
    plan = json.loads(r.stdout or '{}')
    check('revive: a live supervisor is not woken the first time its items are seen',
          not any(t['session_id'] == 'local_cown' for t in plan.get('targets', [])))
    seen_path = os.path.join(lock_home, 'unattended.json')
    seen = json.load(open(seen_path))
    seen[ckey] = {k: time.time() - unattended.UNATTENDED_AFTER_S - 60 for k in seen.get(ckey, {})}
    json.dump(seen, open(seen_path, 'w'))
    plan = json.loads(crevive('--json').stdout or '{}')
    mine = [t for t in plan.get('targets', []) if t['session_id'] == 'local_cown']
    check('revive: a live supervisor that left cloud sessions unattended 45 min is woken with the marker and the list',
          len(mine) == 1 and mine[0].get('reason') == 'unattended' and revival.REVIVE_MARKER in mine[0]['message']
          and 'cse_waiting' in mine[0]['message'] and 'cse_hung' in mine[0]['message'])
    rv = json.load(open(os.path.join(lock_home, 'revive.json'))).get(ckey) or {}
    check('revive: its plan entry lets the cross-project gate pass the marker (session, fresh planned_at)',
          rv.get('session') == 'local_cown' and time.time() - rv.get('planned_at', 0) < 60)
    r = crevive()
    check('revive: within UNATTENDED_RETRY_S it is not woken again', 'WAIT-UNATTENDED local_cown' in r.stdout)
    put(sessions_dir, 'cown.json', {'pid': me, 'cwd': crepo, 'hostSessionId': 'local_cown', 'status': 'busy'})
    rvd = json.load(open(os.path.join(lock_home, 'revive.json')))
    rvd[ckey]['planned_at'] = 0
    json.dump(rvd, open(os.path.join(lock_home, 'revive.json'), 'w'))
    r = crevive()
    check('revive: a supervisor busy right now is left to work', f'BUSY local_cown {ckey}' in r.stdout)
    put(sessions_dir, 'cown.json', {'pid': me, 'cwd': crepo, 'hostSessionId': 'local_cown', 'status': 'idle'})
    rvd = json.load(open(os.path.join(lock_home, 'revive.json')))
    rvd[ckey].update(attempts=unattended.UNATTENDED_MAX_ATTEMPTS, planned_at=time.time() - unattended.UNATTENDED_RETRY_S - 60)
    json.dump(rvd, open(os.path.join(lock_home, 'revive.json'), 'w'))
    r = crevive()
    check('revive: past the max attempts it never gives up: an hour later it waits for the slow retry',
          'WAIT-UNATTENDED local_cown' in r.stdout and 'GIVEUP' not in r.stdout)
    rvd = json.load(open(os.path.join(lock_home, 'revive.json')))
    rvd[ckey]['planned_at'] = time.time() - unattended.UNATTENDED_SLOW_RETRY_S - 60
    json.dump(rvd, open(os.path.join(lock_home, 'revive.json'), 'w'))
    plan = json.loads(crevive('--json').stdout or '{}')
    mine = [t for t in plan.get('targets', []) if t['session_id'] == 'local_cown']
    check('revive: ... and after UNATTENDED_SLOW_RETRY_S it wakes it again, saying how many warnings it ignored',
          len(mine) == 1 and mine[0]['attempt'] == unattended.UNATTENDED_MAX_ATTEMPTS + 1
          and f'aviso n.º {unattended.UNATTENDED_MAX_ATTEMPTS + 1}' in mine[0]['message'])
    put(sessions_dir, 'cown.json', {'pid': me, 'cwd': crepo, 'hostSessionId': 'local_cown', 'status': 'busy'})
    crun('hold', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_waiting', '--reason', 'regla Y')
    crun('hold', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_hung', '--reason', 'regla Z')
    crun('cloud', '--dir', crepo)
    put(sessions_dir, 'cown.json', {'pid': me, 'cwd': crepo, 'hostSessionId': 'local_cown', 'status': 'idle'})
    plan = json.loads(crevive('--json').stdout or '{}')
    check('revive: once everything is handled (held or archived) the supervisor is left alone',
          not any(t['session_id'] == 'local_cown' for t in plan.get('targets', []))
          and ckey not in (json.load(open(os.path.join(lock_home, 'revive.json'))) or {}))
    os.remove(os.path.join(lock_home, 'cloud', 'active.json'))
    os.remove(api)
    r = crun('cloud', '--dir', crepo)
    check('cloud: an unreadable API is CLOUD-UNKNOWN with exit 3, never «none»',
          r.returncode == 3 and 'CLOUD-UNKNOWN' in r.stdout and 'cloud: 0' not in r.stdout)
    # the owner's archive and send cannot check the target while the rows are unreadable: exit 3, nothing done or logged
    cloud_log_path = os.path.join(lock_home, 'cloud-actions.log')
    cloud_log_before = open(cloud_log_path).read() if os.path.exists(cloud_log_path) else ''
    cloud_lock = os.path.join(lock_home, 'locks', ckey + '.json')
    still_owner = json.load(open(cloud_lock)) if os.path.exists(cloud_lock) else {}  # its owner still holds it here
    r = crun('cloud-archive', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_waiting', '--reason', 'x')
    check('cloud-archive: unreadable cloud rows -> exit 3, nothing archived',
          still_owner.get('session_id') == 'local_cown' and r.returncode == 3 and 'CLOUD-UNKNOWN' in r.stderr
          and 'ARCHIVED' not in r.stdout and open(cloud_log_path).read() == cloud_log_before)
    r = crun('cloud-send', '--dir', crepo, '--session', 'local_cown', '--target', 'cse_waiting', '--text', 'x')
    check('cloud-send: unreadable cloud rows -> exit 3, nothing sent',
          r.returncode == 3 and 'CLOUD-UNKNOWN' in r.stderr and 'SENT' not in r.stdout
          and open(cloud_log_path).read() == cloud_log_before)
    # no cloud provider at all: CLOUD-UNAVAILABLE (exit 3), never an empty census
    no_provider = dict(cenv, SUPERVISOR_CLOUD_TESTS=os.path.join(tmp, 'no-such-cloud-tests'))
    r = subprocess.run([sys.executable, runtime.ENTRY, 'cloud', '--dir', crepo], capture_output=True, text=True, env=no_provider)
    check('cloud: no cloud provider -> CLOUD-UNAVAILABLE, exit 3, never «none»',
          r.returncode == 3 and r.stdout.startswith('CLOUD-UNAVAILABLE') and 'cloud: 0' not in r.stdout)
    r = subprocess.run([sys.executable, runtime.ENTRY, 'cloud', '--dir', crepo, '--json'], capture_output=True, text=True,
                       env=no_provider)
    got = json.loads(r.stdout) if r.stdout.strip().startswith('{') else {}
    check('cloud --json: no cloud provider -> available false, exit 3',
          r.returncode == 3 and got.get('ok') is False and got.get('available') is False)
    for s in sleepers:
        s.kill()
        s.wait()


    # 31. work left: the backlog, the guard gate, the developer's messages on guard, language and the skill lint.
    ghome = os.path.join(tmp, 'guard-home')
    genv = dict(env, SUPERVISOR_LOCK_HOME=ghome)
    grepo = os.path.realpath(os.path.join(tmp, 'gproj'))
    make_repo(grepo)

    def grun(*cli):
        return subprocess.run([sys.executable, runtime.ENTRY, *cli], capture_output=True, text=True, env=genv)

    def tasks(change, body):
        d = os.path.join(grepo, 'openspec', 'changes', change)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'tasks.md'), 'w') as fh:
            fh.write(body)

    os.makedirs(os.path.join(tmp, 'greg'))
    open(os.path.join(tmp, 'greg', 'SUPERVISOR-20261101-0000.md'), 'w').write('# ciclo viejo\n')
    os.utime(os.path.join(tmp, 'greg', 'SUPERVISOR-20261101-0000.md'), (time.time() - 9000, time.time() - 9000))
    gold = os.path.join(tmp, 'greg', 'SUPERVISOR-20261101-0000.md')
    greg = os.path.join(tmp, 'greg', 'SUPERVISOR-20261121-2241.md')
    open(greg, 'w').write('# Supervisión\n\n## Objetivos\n- T1 hecho\n')
    grun('acquire', '--dir', grepo, '--session', 'local_g', '--title', 'Sup g', '--registry', gold)  # the lock keeps the first cycle's file
    r = grun('backlog', '--dir', grepo)
    check('backlog: a project without OpenSpec changes has no work', r.returncode == 0 and r.stdout.strip() == 'BACKLOG work=0 parked=0')
    tasks('done-change', '- [x] 1.1 hecho\n- [X] 1.2 hecho\n')
    tasks('archive', '- [ ] 9.9 no cuenta\n')
    tasks('eval-suite', '## 8\n- [x] 8.0 hecho\n- [ ] 8.1 Medir el tiempo\n* [ ] 8.2 Informe\n')
    tasks('ranking-page', '- [ ] 2.3 curl tras el deploy\n')
    r = grun('backlog', '--dir', grepo)
    check('backlog: each change with unchecked tasks is WORK (done and archived ones are not), exit 7',
          r.returncode == 7 and 'WORK eval-suite open=2 «8.1 Medir el tiempo»' in r.stdout
          and 'WORK ranking-page open=1' in r.stdout and 'done-change' not in r.stdout and '9.9' not in r.stdout
          and 'BACKLOG work=2 parked=0' in r.stdout)
    r = grun('beat', '--dir', grepo, '--session', 'local_g', '--phase', 'guardia')
    cur = json.load(open(os.path.join(ghome, 'locks', os.listdir(os.path.join(ghome, 'locks'))[0])))
    check('beat --phase guardia: refused (7) while the project has documented work left; the phase does not change',
          r.returncode == 7 and 'GUARD REFUSED' in r.stderr and 'eval-suite' in r.stderr
          and 'backlog --session local_g --park' in r.stderr and cur.get('phase') != 'guardia')
    r = grun('backlog', '--dir', grepo, '--session', 'local_other', '--park', 'ranking-page', '--as', 'tercero', '--why', 'x' * 30)
    check('backlog --park: only the owner of the lock', r.returncode == 5)
    r = grun('backlog', '--dir', grepo, '--session', 'local_g', '--park', 'ranking-page', '--as', 'tercero', '--why', 'corto')
    check('backlog --park: a reason of a few characters is refused', r.returncode == 2 and 'USAGE' in r.stderr)
    r = grun('backlog', '--dir', grepo, '--session', 'local_g', '--park', 'nope', '--as', 'tercero', '--why', 'x' * 30)
    check('backlog --park: an unknown change is refused', r.returncode == 2 and 'NOT FOUND' in r.stderr)
    grun('backlog', '--dir', grepo, '--session', 'local_g', '--park', 'ranking-page', '--as', 'tercero',
         '--why', 'espera la revisión de Google Play; comprobado en la consola')
    r = grun('backlog', '--dir', grepo, '--session', 'local_g', '--park', 'eval-suite', '--as', 'protegido',
             '--why', 'D65: el desarrollador ordenó no tocar este change')
    check('backlog --park: parked changes are listed with their kind and reason and stop being work',
          r.returncode == 0 and 'PARKED ranking-page as=tercero open=1' in r.stdout and 'Google Play' in r.stdout
          and 'PARKED eval-suite as=protegido' in r.stdout and 'BACKLOG work=0 parked=2' in r.stdout)
    r = grun('beat', '--dir', grepo, '--session', 'local_g', '--phase', 'guardia')
    check('beat --phase guardia: refused while the registry does not explain the guard',
          r.returncode == 7 and 'Motivo de la guardia' in r.stderr and 'la meta escrita del proyecto' in r.stderr)
    open(greg, 'a').write('\n## Motivo de la guardia\n- mensajes: ninguno desde el ciclo\n- tanda: todo confirmado\n'
                          '- backlog: 0 de trabajo, 2 aparcados\n- meta: publicada la versión; nada derivable\n\n## Otra\n')
    r = grun('beat', '--dir', grepo, '--session', 'local_g', '--phase', 'guardia')
    cur = json.load(open(os.path.join(ghome, 'locks', os.listdir(os.path.join(ghome, 'locks'))[0])))
    check('beat --phase guardia: accepted once nothing is left and the newest registry of the folder says why (the lock '
          'still names the first cycle\'s file)', r.returncode == 0 and cur.get('phase') == 'guardia' and cur.get('registry') == gold)
    tasks('ranking-page', '- [ ] 2.3 curl tras el deploy\n- [ ] 2.4 otra tarea nueva\n')
    r = grun('backlog', '--dir', grepo)
    check('backlog: a park is void once the open tasks of the change are not the ones it was written for',
          r.returncode == 7 and 'WORK ranking-page open=2' in r.stdout and 'PARKED eval-suite' in r.stdout)

    # a checkout that lags behind its integration branch (change cloud-per-test-and-backlog-ref, D6)
    lrepo = os.path.realpath(os.path.join(tmp, 'lagproj'))
    sh('git', 'init', '-q', '-b', 'main', lrepo)

    def lcommit(msg):
        sh('git', 'add', '-A', cwd=lrepo)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', msg, cwd=lrepo)

    def ltasks(change, body):
        d = os.path.join(lrepo, 'openspec', 'changes', change)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'tasks.md'), 'w') as fh:
            fh.write(body)

    ltasks('kept', '- [ ] 1.1 sigue abierta\n')
    ltasks('gone', '- [ ] 1.1 se archiva en main\n')
    lcommit('one')
    sh('git', 'branch', 'develop', cwd=lrepo)
    ltasks('newer', '- [ ] 2.1 solo en main\n')
    os.makedirs(os.path.join(lrepo, 'openspec', 'changes', 'archive'))
    os.rename(os.path.join(lrepo, 'openspec', 'changes', 'gone'),
              os.path.join(lrepo, 'openspec', 'changes', 'archive', '2026-11-01-gone'))
    lcommit('two')
    sh('git', 'checkout', '-q', 'develop', cwd=lrepo)
    ltasks('local-only', '- [ ] 3.1 sin commitear\n')
    lids = sorted(i['id'] for i in backlog.backlog_items(lrepo))
    check('backlog: a checkout behind its integration branch reads that branch (no fetch): its changes count, the ones '
          'it archived do not, and changes only in the working tree are added', lids == ['kept', 'local-only', 'newer'])
    sh('git', 'checkout', '-q', 'main', cwd=lrepo)
    ltasks('newer', '- [x] 2.1 marcada en el árbol\n')
    lids = sorted(i['id'] for i in backlog.backlog_items(lrepo))
    check('backlog: a checkout that contains its integration branch reads its working tree as before',
          lids == ['kept', 'local-only'])

    put(app_dir, 'local_g.json', {'sessionId': 'local_g', 'cliSessionId': 'cli-g', 'cwd': grepo, 'title': 'Sup g'})
    garmed = dict(armed_task, command='~/.claude/scripts/supervisor-lock wait --owner local_g --guard --timeout 21600')
    quiet = os.path.join(tmp, 'quiet.jsonl')
    write_jsonl(quiet, [text_rec(30)])
    grun('beat', '--dir', grepo, '--session', 'local_g', '--skill-seen')
    r = hook(stop(session_id='cli-g', cwd=grepo, background_tasks=[garmed], transcript_path=quiet), hook_env=genv)
    reason = json.loads(r.stdout or '{}').get('reason', '')
    check('hook (end to end): Stop of a supervisor on guard, watcher armed, documented work left -> blocked with the change',
          'estás de guardia en gproj' in reason and 'ranking-page (2 tareas' in reason)
    check('hook (end to end): stop_hook_active -> the guard block never loops',
          hook(stop(session_id='cli-g', cwd=grepo, background_tasks=[garmed], transcript_path=quiet, stop_hook_active=True), hook_env=genv).stdout == '')
    eng = ('The deploy is still waiting in the machine queue and there is nothing else that I can do until the tests have '
           'finished, because the suite has to run on the merged tree. I will check it again when the watcher wakes me, '
           'and then the release will be published with the usual command that the project has for it.')
    r = hook(stop(session_id='cli-gchild', cwd=grepo, last_assistant_message=eng), hook_env=genv)
    check('hook (end to end): a supervised session that ends its turn in English is sent back to Spanish',
          'en español' in json.loads(r.stdout or '{}').get('reason', ''))
    r = hook(stop(session_id='cli-gchild', cwd=other, last_assistant_message=eng), hook_env=genv)
    check('hook (end to end): a session of a project nobody supervises is left alone', r.stdout == '')

    # the closing session: a sibling of the questions session that verifies, closes and archives finished sessions
    put(app_dir, 'local_gclose.json', {'sessionId': 'local_gclose', 'cliSessionId': 'cli-gclose', 'cwd': grepo,
                                       'title': 'Cierre de sesiones de gproj'})
    put(sessions_dir, 'gclose.json', {'pid': os.getpid(), 'cwd': grepo, 'hostSessionId': 'local_gclose', 'sessionId': 'cli-gclose',
                                      'name': 'Cierre de sesiones de gproj', 'status': 'idle', 'updatedAt': now_ms})
    put(app_dir, 'local_gdone.json', {'sessionId': 'local_gdone', 'cliSessionId': 'cli-gdone', 'cwd': grepo, 'title': 'Hija terminada',
                                      'lastActivityAt': now_ms - 4 * 3600 * 1000})
    r = grun('closable', '--dir', grepo)
    check('closer: the closing session is never a session to close (by title, before it is registered)',
          'CLOSABLE local_gdone' in r.stdout and 'local_gclose' not in r.stdout)
    r = grun('wait-closer', '--dir', grepo, '--session', 'local_gclose', '--timeout', '1')
    check('wait-closer: only the registered closing session', r.returncode == 5)
    grun('beat', '--dir', grepo, '--session', 'local_g', '--closer', 'local_gclose')
    r = grun('open', '--dir', grepo)
    check('closer: `open` does not count the closing session', 'local_gclose' not in r.stdout and 'local_gdone' in r.stdout)
    r = grun('wait-closer', '--dir', grepo, '--session', 'local_gclose', '--timeout', '5', '--interval', '1')
    check('wait-closer: wakes the closing session with the finished sessions of the project',
          r.returncode == 0 and 'CLOSABLE local_gdone' in r.stdout)
    r = grun('wait-closer', '--dir', grepo, '--session', 'local_gclose', '--timeout', '2', '--interval', '1')
    check('wait-closer: each finished session is announced once (then TIMEOUT)', r.stdout.strip() == 'TIMEOUT 2s')
    r = hook(stop(session_id='cli-gclose', cwd=grepo, background_tasks=[]), hook_env=genv)
    check('hook: the closing session may not end a turn without its watcher',
          'wait-closer --session local_gclose' in json.loads(r.stdout or '{}').get('reason', ''))
    cwatch = {'id': 'c1', 'type': 'shell', 'status': 'running', 'command': '~/.claude/scripts/supervisor-lock wait-closer --session local_gclose --timeout 1800'}
    r = hook(stop(session_id='cli-gclose', cwd=grepo, background_tasks=[cwatch]), hook_env=genv)
    reason = json.loads(r.stdout or '{}').get('reason', '')
    check('hook: the closing session is told which finished sessions are left, with verification',
          'local_gdone' in reason and 'comprobaciones en disco' in reason and 'no se archiva' in reason)
    r = hook(stop(session_id='cli-gclose', cwd=grepo, background_tasks=[cwatch]), hook_env=genv)
    check('hook: the closing block comes at most once every 5 min', r.stdout == '')
    r = grun('hold', '--dir', grepo, '--session', 'local_gclose', '--target', 'local_gdone', '--reason', 'la app se niega: fijada por el desarrollador')
    check('closer: the closing session may park a session with a written reason, like the owner', r.returncode == 0)
    grun('hold', '--dir', grepo, '--session', 'local_gclose', '--target', 'local_gdone', '--clear')
    for f in ('local_gdone.json',):
        os.remove(os.path.join(app_dir, f))

    # nobody working + documented work left, in a cycle: waiting is not working
    grun('beat', '--dir', grepo, '--session', 'local_g', '--phase', 'F6')
    cyc = dict(armed_task, command='~/.claude/scripts/supervisor-lock wait --owner local_g --timeout 600')
    queued_job = {'id': 'b9', 'type': 'shell', 'status': 'running', 'command': '~/.claude/scripts/heavy-job run --kind e2e -- make e2e'}
    r = hook(stop(session_id='cli-g', cwd=grepo, background_tasks=[cyc, queued_job], transcript_path=quiet), hook_env=genv)
    reason = json.loads(r.stdout or '{}').get('reason', '')
    check('hook (end to end): in a cycle, only waits running, no busy session, work left -> «esperar no es trabajar»',
          'no trabaja nadie' in reason and 'ranking-page' in reason and 'Esperar no es trabajar' in reason)
    r = hook(stop(session_id='cli-g', cwd=grepo, background_tasks=[cyc, queued_job], transcript_path=quiet), hook_env=genv)
    check('hook: the idle block comes at most once every 30 min per lock', 'no trabaja nadie' not in r.stdout)
    if 'no trabaja nadie' not in reason:
        print('DEBUG', r.stdout[:300], r.stderr[:300], open(os.path.join(ghome, 'hook-errors.log')).read()[-1500:] if os.path.exists(os.path.join(ghome, 'hook-errors.log')) else 'no errors', grun('backlog', '--dir', grepo).stdout)
    for st in glob.glob(os.path.join(ghome, 'backlog', '*.idle-blocked')):
        os.remove(st)
    agent_task = {'id': 'a1', 'type': 'agent', 'status': 'running', 'description': 'implementa ranking-page'}
    r = hook(stop(session_id='cli-g', cwd=grepo, background_tasks=[cyc, agent_task], transcript_path=quiet), hook_env=genv)
    check('hook: a subagent of hers running -> somebody is working, no idle block', 'no trabaja nadie' not in r.stdout)
    r = hook(stop(session_id='cli-g', cwd=grepo, transcript_path=quiet), hook_env=genv)
    check('hook: without the list of its background tasks the idle block never guesses', 'no trabaja nadie' not in r.stdout)
    put(sessions_dir, 'gbusy.json', {'pid': os.getpid(), 'cwd': grepo, 'hostSessionId': 'local_gbusy', 'name': 'impl', 'status': 'busy',
                                     'updatedAt': now_ms, 'statusUpdatedAt': now_ms})
    r = hook(stop(session_id='cli-g', cwd=grepo, background_tasks=[cyc], transcript_path=quiet), hook_env=genv)
    check('hook: a busy session of the project -> somebody is working, no idle block', 'no trabaja nadie' not in r.stdout)
    os.remove(os.path.join(sessions_dir, 'gbusy.json'))
    r = grun('backlog', '--dir', grepo, '--session', 'local_g', '--park', 'ranking-page', '--as', 'tercero',
             '--why', 'Tarea 2.3 en vuelo desde las 23:20 con un subagente; se revisa al acabar')
    check('backlog --park: what is in flight is not parked', r.returncode == 2 and 'IN FLIGHT' in r.stderr)
    r = grun('backlog', '--dir', grepo, '--session', 'local_g', '--park', 'ranking-page', '--as', 'tercero',
             '--why', 'needs a physical parcel to inspect the delivery note; nothing that an agent can check for it')
    check('backlog --park: a reason in English is sent back', r.returncode == 2 and 'IN ENGLISH' in r.stderr)
    lock_file = os.path.join(ghome, 'locks', os.listdir(os.path.join(ghome, 'locks'))[0])
    cur = dict(json.load(open(lock_file)), phase='guardia')   # back on guard for the cases below (work is left: beat would refuse)
    json.dump(cur, open(lock_file, 'w'))

    saved = {k: os.environ.get(k) for k in genv if k.startswith(('SUPERVISOR_', 'ASK_GATE'))}
    os.environ.update({k: v for k, v in genv.items() if k.startswith(('SUPERVISOR_', 'ASK_GATE'))})
    try:
        gkey = cur['key']
        reason = backlog.guard_block(cur, 'local_g')
        check('hook: a supervisor on guard with documented work left is blocked, with the change and what to do',
              'ranking-page (2 tareas' in reason and 'estar parada' in reason and '--phase F1' in reason)
        check('hook: the guard block never fires outside guard', backlog.guard_block(dict(cur, phase='F4'), 'local_g') == '')
        parks = util.read_json(backlog.backlog_path(gkey), {})
        parks['ranking-page']['digest'] = backlog.backlog_items(grepo)[1]['digest'] if backlog.backlog_items(grepo)[1]['id'] == 'ranking-page' else backlog.backlog_items(grepo)[0]['digest']
        util.write_json_atomic(backlog.backlog_path(gkey), parks)
        check('hook: nothing left -> no guard block', backlog.guard_block(cur, 'local_g') == '')
        parks['ranking-page']['until'] = time.time() - 5
        util.write_json_atomic(backlog.backlog_path(gkey), parks)
        check('hook: an expired park is work again (a third party is asked again)', 'ranking-page' in backlog.guard_block(cur, 'local_g'))
        parks['ranking-page']['until'] = time.time() + 3600
        util.write_json_atomic(backlog.backlog_path(gkey), parks)
        lines = cloud.announce_once(gkey, 'backlog', [('x:1', 'BACKLOG x open=1 «t»')], backlog.BACKLOG_REANNOUNCE_S)
        check('wait --guard: BACKLOG is a guard event, announced once per change and state',
              'BACKLOG' in watch.GUARD_EVENTS and lines == ['BACKLOG x open=1 «t»']
              and cloud.announce_once(gkey, 'backlog', [('x:1', 'BACKLOG x open=1 «t»')], backlog.BACKLOG_REANNOUNCE_S) == [])

        # replay of a supervisor on guard that filed the developer's message as a decision («No hay trabajo abierto; la supervisora
        # sigue de guardia») instead of opening the cycle it asked for
        incident = os.path.join(tmp, 'incident.jsonl')
        said = ('lo que me entregues es una prueba de concepto: si sale bien se publica tal cual y si no servirá de '
                'referencia')
        write_jsonl(incident, [{'type': 'user', 'timestamp': iso(60), 'uuid': 'u-incident', 'origin': {'kind': 'human'},
                                'message': {'role': 'user', 'content': said}}, text_rec(30)])
        reason = developer.developer_block(cur, 'local_g', {'transcript_path': incident})
        with lock_mod.Store() as store:
            after = store.read(gkey)
        check('replay: the developer\'s message to a supervisor on guard is an order that opens the next cycle',
              'prueba de concepto' in reason and 'Estás de guardia' in reason and '--phase F1' in reason
              and '--no-work' in reason and 'no otra cosa' in reason
              and (after.get('guard_order') or {}).get('uuid') == 'u-incident')
        again = backlog.guard_block(after, 'local_g')
        check('replay: filing it as a note and staying on guard is blocked at every later turn end',
              'prueba de concepto' in again and 'no consta qué hiciste' in again)
        r = grun('beat', '--dir', grepo, '--session', 'local_g', '--phase', 'guardia')
        check('replay: `beat --phase guardia` is refused while the developer\'s message has no outcome',
              r.returncode == 7 and 'prueba de concepto' in r.stderr)
        r = grun('beat', '--dir', grepo, '--session', 'local_g', '--no-work', 'vale')
        check('beat --no-work: needs a real reason', r.returncode == 2)
        r = grun('beat', '--dir', grepo, '--session', 'local_g', '--phase', 'F1')
        with lock_mod.Store() as store:
            after = store.read(gkey)
        check('replay: leaving guard for a new cycle is the outcome (the order is cleared)',
              r.returncode == 0 and after.get('phase') == 'F1' and 'guard_order' not in after)
        with lock_mod.Store() as store:
            store.write(gkey, dict(after, phase='guardia', guard_order={'at': 'x', 'uuid': 'u2', 'text': 'gracias, perfecto'}))
        r = grun('beat', '--dir', grepo, '--session', 'local_g', '--no-work', 'solo da las gracias por el ciclo anterior')
        with lock_mod.Store() as store:
            after = store.read(gkey)
        check('beat --no-work: a message that asks for nothing is recorded with its reason and the guard goes on',
              r.returncode == 0 and 'guard_order' not in after and 'no-work «gracias, perfecto»' in open(os.path.join(ghome, 'hook.log')).read()
              and backlog.guard_block(after, 'local_g') == '')
        goon = os.path.join(tmp, 'goon.jsonl')
        write_jsonl(goon, [{'type': 'user', 'timestamp': iso(40), 'uuid': 'u-goon', 'origin': {'kind': 'human'},
                            'message': {'role': 'user', 'content': 'continua'}}, text_rec(20)])
        reason = developer.developer_block(dict(after, key=gkey), 'local_g', {'transcript_path': goon})
        with lock_mod.Store() as store:
            after = store.read(gkey)
        check('a bare «continua» to a supervisor on guard is an order too (mid-cycle it is still skipped)',
              '«continua»' in reason and (after.get('guard_order') or {}).get('uuid') == 'u-goon'
              and developer.developer_block(dict(after, phase='F4', key=gkey + '-go'), 'local_g', {'transcript_path': goon}) == '')
        with lock_mod.Store() as store:
            store.write(gkey, {k: v for k, v in after.items() if k != 'guard_order'})
            after = store.read(gkey)
        mid = developer.developer_block(dict(after, phase='F4', key=gkey + '-mid'), 'local_g', {'transcript_path': incident})
        check('hook: mid-cycle, a message of the developer\'s that implies work is an objective to launch in that turn, and an '
              'answered one is not repeated', 'es un objetivo nuevo' in mid and 'Estás de guardia' not in mid
              and 'sin repetir la respuesta' in mid)
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    english = ('The deploy is still waiting in the machine queue and there is nothing else that I can do until the tests '
               'have finished, because the suite has to run on the merged tree. I will check it again when the watcher '
               'wakes me, and then the release will be published with the usual command from `make deploy`.')
    spanish = ('El deploy sigue en la cola de la máquina y mientras tanto he lanzado la revisión de las traducciones, que '
               'no depende de él. Cuando termine la suite sobre el árbol integrado publico con `make deploy` y compruebo '
               'la web desde fuera. The build is green, dice el log, y no hay más que hacer en esa parte por ahora.')
    check('language: a closing message in English is recognised; Spanish with code and a quote is not; short text is never judged',
          language.looks_english(english) and not language.looks_english(spanish) and not language.looks_english('Done. The build is green.'))
    real_home = os.environ.get('SUPERVISOR_LOCK_HOME')
    os.environ['SUPERVISOR_LOCK_HOME'] = ghome   # the block is logged: never in the developer's own hook.log
    try:
        check('language: the Stop block asks for Spanish', 'en español' in language.english_block({'last_assistant_message': english}, 'cli-x')
              and language.english_block({'last_assistant_message': spanish}, 'cli-x') == '')
    finally:
        os.environ.pop('SUPERVISOR_LOCK_HOME', None) if real_home is None else os.environ.__setitem__('SUPERVISOR_LOCK_HOME', real_home)

    rep_owner = {'key': 'rep-test', 'project': 'rep', 'checkout': tmp, 'phase': 'F6'}
    parte = ('En espera, no parada. Esperamos a que la implementadora pase las pruebas completas; sin ese verde no se '
             'integra. Lo acabo de comprobar: su trabajo es el primero de la cola (`heavy-job status`: primero de 10) y main '
             'no se ha movido (`git log -1 origin/main`: 3f2a9c1). ' + 'Sigo mirando la cola y relanzo si su proceso muere. ' * 4)
    os.environ['SUPERVISOR_LOCK_HOME'] = ghome
    os.environ.pop('SUPERVISOR_SELFTEST_NO_REPORT', None)
    try:
        check('report: a long message with two proofs is a report; a short «todo bien» is not',
              guard_report.looks_report(parte) and not guard_report.looks_report('Todo bien, sigo.') and not guard_report.looks_report('x' * 900))
        first = guard_report.report_block(rep_owner, 'local-rep', {'last_assistant_message': 'Sigo esperando.'}, 'cli-x', now=10_000)
        check('report: with no report ever, a turn that ends without one is sent back', 'parte de estado' in first and 'nunca' in first)
        check('report: a closing message that is a report passes and resets the clock',
              guard_report.report_block(rep_owner, 'local-rep', {'last_assistant_message': parte}, 'cli-x', now=10_000) == ''
              and guard_report.report_block(rep_owner, 'local-rep', {'last_assistant_message': 'Sigo.'}, 'cli-x', now=10_000 + guard_report.REPORT_EVERY_S - 5) == '')
        check('report: 30 minutes after the last report the next short ending is sent back',
              'hace 30 min' in guard_report.report_block(rep_owner, 'local-rep', {'last_assistant_message': 'Sigo.'}, 'cli-x', now=10_000 + guard_report.REPORT_EVERY_S + 1))
        check('report: on guard the interval is two hours',
              guard_report.report_block(dict(rep_owner, phase='guardia', state='guard'), 'local-rep', {'last_assistant_message': 'Sigo.'}, 'cli-x',
                           now=10_000 + guard_report.REPORT_EVERY_S + 1) == '' or not backlog.on_guard(dict(rep_owner, phase='guardia', state='guard')))
    finally:
        os.environ['SUPERVISOR_SELFTEST_NO_REPORT'] = '1'
        os.environ.pop('SUPERVISOR_LOCK_HOME', None) if real_home is None else os.environ.__setitem__('SUPERVISOR_LOCK_HOME', real_home)

    # 31. session titles: a lock title that looks like status output is refused, the default is the supervisor title,
    # `titles` lists what each session must be renamed to and `--fix` repairs the lock and the Remote Control copy.
    trepo = os.path.realpath(os.path.join(tmp, 'tproj'))
    make_repo(trepo)
    tapi = os.path.join(tmp, 'titles-api.json')
    with open(tapi, 'w') as fh:
        json.dump({'sessions': [cs('tbridge', kind='bridge')]}, fh)
    shutil.rmtree(os.path.join(lock_home, 'cloud'), ignore_errors=True)   # the shared listing cache of the sections above
    trun = lambda *a: subprocess.run([sys.executable, runtime.ENTRY, *a], capture_output=True, text=True,
                                     env=dict(cenv, CLOUD_TESTS_API_FAKE=tapi))
    r = trun('acquire', '--dir', trepo, '--session', 'local_tsup', '--title', 'HELD tproj session=local_x state=running')
    check('titles: acquire refuses a title that looks like supervisor-lock output', r.returncode == 2 and 'TITLE REFUSED' in r.stderr)
    r = trun('acquire', '--dir', trepo, '--session', 'local_tsup')
    tkey = json.loads(trun('project', '--dir', trepo, '--json').stdout)['key']
    tlock = os.path.join(lock_home, 'locks', tkey + '.json')
    check('titles: acquire without a title takes the supervisor title of the project',
          r.returncode == 0 and json.load(open(tlock))['title'] == 'Supervisora de tproj')
    fixture('local_tsup', cwd=trepo, title='old name')
    fixture('local_tbridge', cwd=trepo, title='tproj · tarea', bridgeSessionIds=['session_tbridge'])
    r = trun('titles', '--session', 'local_tsup')
    check('titles: lists the local session to rename and the Remote Control copy that must follow its local title',
          r.returncode == 0 and 'RENAME local_tsup supervisor «old name» -> «Supervisora de tproj»' in r.stdout
          and 'REMOTE cse_tbridge «T tbridge» -> «tproj · tarea»' in r.stdout)
    with open(tlock) as fh:
        tdata = json.load(fh)
    tdata['title'] = 'STALE tproj session=local_tsup'
    with open(tlock, 'w') as fh:
        json.dump(tdata, fh)
    r = trun('titles', '--fix', '--session', 'local_tsup')
    with open(tapi) as fh:
        tst = json.load(fh)
    check('titles --fix: repairs the lock title, renames the bridge through the API and edits no app record',
          r.returncode == 0 and json.load(open(tlock))['title'] == 'Supervisora de tproj'
          and tst.get('renamed') == [['cse_tbridge', 'tproj · tarea']]
          and json.load(open(os.path.join(app_dir, 'local_tsup.json')))['title'] == 'old name')
    r = trun('titles', '--fix', '--session', 'local_tsup')
    check('titles --fix: a second run has nothing to rename in the cloud', 'REMOTE' not in r.stdout
          and len(json.load(open(tapi)).get('renamed', [])) == 1)
    others = (settings.supervisor_title('p'), settings.worker_title('p', 'x'))
    is_questions = lambda t: any(util.fold_text(m) in util.fold_text(t) for m in session_roles.ASK_GATE_MAILBOX_TITLES)
    is_closer = lambda t: any(c in util.fold_text(t) for c in settings.CLOSER_TITLES)
    check('titles: the questions and closing titles keep matching their recognisers; the others match neither',
          is_questions(settings.questions_title('p')) and is_closer(settings.closer_title('p'))
          and not any(is_questions(t) or is_closer(t) for t in others))

    lint_dir = os.path.join(tmp, 'lint-skill')
    os.makedirs(os.path.join(lint_dir, 'reference'))
    anchors = '\n'.join(lint.SKILL_ANCHORS)
    good = '---\nname: x\n---\n' + anchors + '\n`reference/cambios.md`\n'
    open(os.path.join(lint_dir, 'reference', 'cambios.md'), 'w').write('Al recargarla tras el cambio: historia\n')
    open(os.path.join(lint_dir, 'SKILL.md'), 'w').write(good)
    lenv = dict(env, SUPERVISOR_SKILL_FILE=os.path.join(lint_dir, 'SKILL.md'), SUPERVISOR_LINT_ROOTS=lint_dir)
    r = subprocess.run([sys.executable, runtime.ENTRY, 'skill-lint'], capture_output=True, text=True, env=lenv)
    check('skill-lint: a sound skill passes (the history file may quote what each fix replaced)', r.returncode == 0 and 'SKILL_LINT ok' in r.stdout)
    open(os.path.join(lint_dir, 'SKILL.md'), 'w').write(good + 'x' * 21000 + '\n## Prohibido al final\n`reference/nope.md`\n')
    open(os.path.join(lint_dir, 'reference', 'viejo.md'), 'w').write('cierra con `PREPROD DEPLOYED — TANDA FINAL` y libera el cerrojo.\n'
                                                                  'no pregunta ni aunque acabe de escribir en ella\n')
    r = subprocess.run([sys.executable, runtime.ENTRY, 'skill-lint'], capture_output=True, text=True, env=lenv)
    check('skill-lint: a core past the compaction cut, a missing reference and text an old fix replaced all fail',
          r.returncode == 1 and 'CORE_TOO_LONG' in r.stdout and 'FILE_TOO_LONG' in r.stdout and 'REFERENCE_MISSING reference/nope.md' in r.stdout
          and r.stdout.count('STALE ') == 2 and 'viejo.md:1' in r.stdout)
    open(os.path.join(lint_dir, 'SKILL.md'), 'w').write('---\nname: x\n---\n' + 'x' * 100 + '\n')
    r = subprocess.run([sys.executable, runtime.ENTRY, 'skill-lint'], capture_output=True, text=True, env=lenv)
    check('skill-lint: a core without what must survive a compaction fails', r.stdout.count('ANCHOR_MISSING') == len(lint.SKILL_ANCHORS))
    if not os.environ.get('SUPERVISOR_SKIP_INSTALLED_LINT'):
        installed_env = dict(os.environ)
        if os.environ.get(INSTALLED_CONFIG_ENV):
            installed_env['CLAUDE_TOOLKIT_CONFIG_DIR'] = os.environ[INSTALLED_CONFIG_ENV]
        r = subprocess.run([sys.executable, runtime.ENTRY, 'skill-lint'], capture_output=True, text=True, env=installed_env)
        check('skill-lint: the installed skill, its references and the rules are sound\n' + r.stdout.strip(), r.returncode == 0)


    shutil.rmtree(tmp, ignore_errors=True)
    print(f'{"FAIL" if failures else "ok"}: {len(failures)} failed')
    return 1 if failures else 0
