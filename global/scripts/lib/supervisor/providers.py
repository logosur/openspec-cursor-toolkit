"""Adapters of optional scripts: each one degrades when its script is absent."""
import importlib.machinery
import importlib.util
import json
import os
import shlex
import subprocess
import time

from . import projects, util


USAGE_CACHE_S = 120          # account_has_usage() asks the network at most this often
_ACCOUNT_SWITCH = []


def account_switch_module():
    """The optional account-switch script loaded as a module (its helpers `load`, `STATE`, `cli_org`, `usage`,
    `usage_limit`); $SUPERVISOR_ACCOUNT_SWITCH overrides the path (tests). Raises when it is absent."""
    path = os.path.expanduser(os.environ.get('SUPERVISOR_ACCOUNT_SWITCH', '~/.claude/scripts/account-switch'))
    if not _ACCOUNT_SWITCH or _ACCOUNT_SWITCH[0] != path:
        loader = importlib.machinery.SourceFileLoader('account_switch_for_supervisor', path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        _ACCOUNT_SWITCH[:] = [path, module]
    return _ACCOUNT_SWITCH[1]


def account_has_usage():
    """True when the app's account has no exhausted window now, False when it has a limit, None when that cannot be
    told (the CLI is logged into another organization than the app, no answer, any error). The answer is cached
    USAGE_CACHE_S in <home>/usage-cache.json, so the wait loop and the hook never reach the network more than once per
    2 min. $SUPERVISOR_USAGE=yes|no|unknown overrides it (tests)."""
    forced = os.environ.get('SUPERVISOR_USAGE', '').strip().lower()
    if forced:
        return {'yes': True, 'no': False}.get(forced)
    path = os.path.join(util.home(), 'usage-cache.json')
    try:
        with open(path) as fh:
            cached = json.load(fh)
        if isinstance(cached, dict) and 0 <= time.time() - (util.num(cached.get('time')) or 0) < USAGE_CACHE_S:
            return cached.get('has_usage') if isinstance(cached.get('has_usage'), bool) else None
    except (OSError, ValueError):
        pass
    value = None
    try:
        acct = account_switch_module()
        org = (acct.load(acct.STATE, {}) or {}).get('org')
        if org and acct.cli_org() == org:
            data = acct.usage()
            if isinstance(data, dict):
                value = acct.usage_limit(data) is None
    except Exception:
        value = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f'.{os.getpid()}.tmp'
        with open(tmp, 'w') as fh:
            json.dump({'time': time.time(), 'has_usage': value}, fh)
        os.replace(tmp, path)
    except OSError:
        pass
    return value


_PAUSE = []  # the project-pause module, loaded once


def pause_of(path):
    """The pause marker of the project `path` belongs to, from the optional project-pause script, or None (also when
    the script is absent). A paused project keeps every session still until the developer resumes it. Never raises."""
    if not path:
        return None
    try:
        if not _PAUSE:
            bin_path = os.path.expanduser(os.environ.get('PROJECT_PAUSE_BIN', '~/.claude/scripts/project-pause'))
            loader = importlib.machinery.SourceFileLoader('project_pause_for_lock', bin_path)
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            _PAUSE.append(module)
        return _PAUSE[0].paused_marker(path)
    except Exception:
        return None


def heavy_job_busy(project):
    """True when a heavy-job slot marked OCUPADO mentions the project or one of its worktree folders."""
    cmd = os.environ.get('SUPERVISOR_HEAVY_JOB', '~/.claude/scripts/heavy-job')
    if not cmd.strip():
        return False
    argv = [os.path.expanduser(part) for part in shlex.split(cmd)] + ['status']
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    names = projects.project_names(project)
    return any('OCUPADO' in line and any(n in line for n in names) for line in out.splitlines())


HANDOFF_GUARD_TIMEOUT_S = 10
_HANDOFF_HITS = {}


def handoff_fragment(text):
    """The fragment `handoff-guard match` quotes when `text` hands work back to the developer, else None (also when the
    guard is missing, slow or failing). Cached by text: the guard is a process and the wait polls every few seconds."""
    if text in _HANDOFF_HITS:
        return _HANDOFF_HITS[text]
    path = os.path.expanduser(os.environ.get('SUPERVISOR_HANDOFF_GUARD', '~/.claude/scripts/handoff-guard'))
    hit = None
    if os.path.isfile(path):
        try:
            res = subprocess.run([path, 'match'], input=text, capture_output=True, text=True, timeout=HANDOFF_GUARD_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return None  # slow or failing on a loaded machine: not remembered, the next poll asks again
        if res.returncode == 0:
            line = next((ln for ln in res.stdout.splitlines() if ln.strip()), '')
            hit = ' '.join(line.partition('\t')[2].split())[:60] or 'handoff'
        elif res.returncode != 1:
            return None  # exit 1 is "no hand-back"; anything else is an error, not an answer
    _HANDOFF_HITS[text] = hit
    return hit


# ---------------------------------------------------------------- cloud sessions
# The app's census only sees local sessions. The cloud sessions of the project's repository come from the optional
# cloud provider; without it every cloud action says the provider is unavailable and the rest works.
CLOUD_TESTS_BIN = '~/.claude/scripts/cloud-tests'
_CLOUD_TESTS = []


def cloud_tests_module():
    """The optional cloud provider (the cloud-tests script) loaded as a module, once per path and process, or None
    when it is absent or does not load. Callers use only `github_slug`, `sid_key`, `iso_epoch`,
    `active_cloud_sessions`, `api_call`, `send_followup` and `STATE_DIR`; $SUPERVISOR_CLOUD_TESTS overrides the path."""
    path = os.path.expanduser(os.environ.get('SUPERVISOR_CLOUD_TESTS', CLOUD_TESTS_BIN))
    if not _CLOUD_TESTS or _CLOUD_TESTS[0] != path:
        module = None
        if os.path.isfile(path):
            try:
                loader = importlib.machinery.SourceFileLoader('cloud_tests_for_supervisor_lock', path)
                spec = importlib.util.spec_from_loader(loader.name, loader)
                module = importlib.util.module_from_spec(spec)
                loader.exec_module(module)
            except Exception:
                module = None
        _CLOUD_TESTS[:] = [path, module]
    return _CLOUD_TESTS[1]


def heavy_job_state():
    """`heavy-job status --json`, or None."""
    cmd = os.environ.get('SUPERVISOR_HEAVY_JOB', '~/.claude/scripts/heavy-job')
    if not cmd.strip():
        return None
    argv = [os.path.expanduser(part) for part in shlex.split(cmd)] + ['status', '--json']
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


# ---------------------------------------------------------------- watchdog

def notify(title, text):
    """Desktop notification through $SUPERVISOR_NOTIFY (default: the optional `routines notify`); True when it was
    delivered. Without the command nothing is notified."""
    cmd = os.environ.get('SUPERVISOR_NOTIFY', '~/.claude/scripts/routines notify')
    if not cmd.strip():
        return False
    argv = [os.path.expanduser(part) for part in shlex.split(cmd)] + [title, text]
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run_nudge():
    """Run the optional `session-nudge stuck --send`; returns (exit code, lines to print, CLI session ids it woke).

    A woken id is a `SENT` line of a wake-up kind (an `OPEN_DIALOG` is queued, not woken) of a run that exited 0.
    A `HELD` line (delivered but never shown in the recipient's transcript) is printed like a SENT one but never counts
    as woken. Without the command it prints NUDGE-FAILED and the watchdog goes on."""
    cmd = os.environ.get('SUPERVISOR_NUDGE', '~/.claude/scripts/session-nudge')
    if not cmd.strip():
        return 0, [], set()
    argv = [os.path.expanduser(part) for part in shlex.split(cmd)] + ['stuck', '--send', '--min-minutes', '15', '--max', '6']
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as err:
        return 1, [f'NUDGE-FAILED {err}'], set()
    lines, woken = [], set()
    for line in done.stdout.splitlines():
        word = line.split(None, 1)[0] if line.strip() else ''
        if word in ('SENT', 'HELD'):
            lines.append('NUDGE ' + line)
            if word == 'SENT' and done.returncode == 0 and 'OPEN_DIALOG' not in line:
                woken.update(line.split()[1:])  # the CLI id sits after the kind: `SENT  QUESTION <cli> pid=…`
    if done.returncode:
        lines.append(f'NUDGE-FAILED exit {done.returncode} {done.stderr.strip()[:200]}')
    return done.returncode, lines, woken


def ask_queue_module():
    path = os.path.expanduser(os.environ.get('ASK_QUEUE_BIN', '~/.claude/scripts/ask-queue'))
    loader = importlib.machinery.SourceFileLoader('ask_queue', path)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('ask_queue', loader))
    loader.exec_module(module)
    return module
