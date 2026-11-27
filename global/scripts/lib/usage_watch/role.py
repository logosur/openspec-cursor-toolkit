"""The bridge to the supervision module for the sub-supervision role (design D1, D7, D8).

`ask-queue` and `supervisor-lock` are run as subprocesses from their installed paths, never imported. Without them the
role commands (`ask`, `decide`, `wait`) exit 6; the measuring half does not need them.

The queue verdict (design D7, G-01) is the only place where an outcome comes from: no command takes it as an argument.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from . import attribution

ASK_QUEUE = '~/.claude/scripts/ask-queue'
SUPERVISOR_LOCK = '~/.claude/scripts/supervisor-lock'
TIMEOUT_S = 60

PENDING, UNTRUSTED, AUTHORIZE, REJECT = 'pending', 'untrusted', 'authorize', 'reject'


def script(name: str) -> str:
    return os.path.expanduser(name)


def available() -> bool:
    return all(os.path.isfile(script(s)) for s in (ASK_QUEUE, SUPERVISOR_LOCK))


def missing_message() -> str:
    return ('usage-watch: the supervision module is needed (ask-queue and supervisor-lock are not installed); '
            'the measuring commands work without it')


def run(name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, script(name), *args], capture_output=True, text=True, timeout=TIMEOUT_S)


# ------------------------------------------------------------------------------------------------ the usage role
def holder(cfg: dict) -> dict | None:
    """The usage role as `supervisor-lock list --json` reports it (with `status` HELD or STALE), else None."""
    try:
        r = run(SUPERVISOR_LOCK, 'list', '--json')
        data = json.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        data = {}
    role = data.get('usage_role') if isinstance(data, dict) else None
    return role if isinstance(role, dict) else None


def holder_ids(cfg: dict) -> set[str]:
    rec = attribution.usage_role(cfg) or {}
    return {v for v in (rec.get('session_id'), rec.get('cli_session_id')) if isinstance(v, str) and v}


def home_project(cfg: dict) -> str | None:
    rec = attribution.usage_role(cfg) or {}
    value = rec.get('home_project')
    return value if isinstance(value, str) and value else None


def supervised_with_mailbox(cfg: dict, root: str | None) -> bool:
    """True when `root` has a live supervision lock with a questions session: someone will present its queue."""
    if not root:
        return False
    real = os.path.realpath(root)
    for lock in attribution.live_locks(cfg):
        if isinstance(lock.get('checkout'), str) and os.path.realpath(lock['checkout']) == real and lock.get('mailbox'):
            return True
    return False


def asker_ids() -> dict:
    return {'session': os.environ.get('CLAUDE_CODE_SESSION_ID') or '',
            'host_session': os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or ''}


# ------------------------------------------------------------------------------------------------ the queue
def queue_item(finding: dict) -> dict | None:
    """The finding's queue item, read now from its project's queue; None when it cannot be found."""
    queue = finding.get('queue') or {}
    if not queue.get('id') or not queue.get('project'):
        return None
    try:
        r = run(ASK_QUEUE, 'list', '--project', queue['project'], '--json')
        items = json.loads(r.stdout) if r.returncode == 0 else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get('id') == queue['id']:
            return item
    return None


def normalise(text) -> str:
    """Case-folded, outer whitespace and punctuation stripped."""
    return re.sub(r'^[\W_]+|[\W_]+$', '', str(text or '').strip()).casefold()


def verdict(cfg: dict, finding: dict) -> tuple[str, dict | None]:
    """(pending | untrusted | authorize | reject, item). An answer is trusted only when it was recorded by a session
    other than the one that registered the item, the asker recorded by `ask`, and the usage role holder."""
    item = queue_item(finding)
    if item is None or item.get('status') in ('open', 'asked'):
        return PENDING, item
    if item.get('status') == 'closed':
        return REJECT, item
    if item.get('status') != 'answered':
        return PENDING, item
    by = item.get('answered_by') if isinstance(item.get('answered_by'), str) else ''
    untrusted = {v for v in (item.get('session'), item.get('host_session')) if isinstance(v, str) and v}
    untrusted |= {v for v in (finding.get('asked_by') or {}).values() if isinstance(v, str) and v}
    untrusted |= holder_ids(cfg)
    if not by or by in untrusted:
        return UNTRUSTED, item
    allowed = {normalise(a) for a in cfg['authorize_answers'] if isinstance(a, str)}
    return (AUTHORIZE if normalise(item.get('answer')) in allowed else REJECT), item


def statuses(ids: list[str]) -> dict[str, str]:
    """{queue id: status} through `ask-queue pending` (one call for every id); empty on any failure."""
    if not ids:
        return {}
    try:
        r = run(ASK_QUEUE, 'pending', *ids)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out
