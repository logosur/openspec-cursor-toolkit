"""`usage-watch wait`: the usage role's watcher (design D9).

It exits only on an event: a `new` finding not announced before (`FINDING <id> <rule> <scope kind>:<scope id>`) or an
`asked` finding whose queue item became `answered` or `closed` (`ANSWER <id>`). Each event is announced once
(`<state_dir>/announced.json`). With no event it prints nothing, so the role gets no turn while nothing happens.
`--timeout 0` never times out; a positive timeout prints `TIMEOUT <s>s`. Exit 5 with `NOT HOLDER` when another live
session holds the usage role; exit 6 without the supervision pieces.
"""
from __future__ import annotations

import os
import sys
import time

from . import config as C
from . import role, store
from .state import read_json, write_json

NOT_HOLDER, NO_SUPERVISION, USAGE = 5, 6, 2


def announced_path(cfg: dict) -> str:
    return os.path.join(C.path(cfg, 'state_dir'), 'announced.json')


def _not_holder(cfg: dict, session: str) -> bool:
    held = role.holder(cfg)
    if not held or held.get('status') != 'HELD':
        return False
    return session not in {held.get('session_id'), held.get('cli_session_id')}


def events(cfg: dict) -> tuple[list[str], dict]:
    seen = read_json(announced_path(cfg), {})
    found_seen = set(seen.get('findings') or [])
    answer_seen = set(seen.get('answers') or [])
    findings = store.read(cfg)
    lines = []
    new_ids = sorted(fid for fid, f in findings.items() if f.get('state') == 'new' and fid not in found_seen)
    for fid in new_ids:
        f = findings[fid]
        scope = f.get('scope') or {}
        lines.append(f'FINDING {fid} {f.get("rule")} {scope.get("kind")}:{scope.get("id")}')
    asked = {fid: (f.get('queue') or {}).get('id') for fid, f in findings.items()
             if f.get('state') == 'asked' and fid not in answer_seen and (f.get('queue') or {}).get('id')}
    status = role.statuses(sorted(set(asked.values())))
    answered = sorted(fid for fid, qid in asked.items() if status.get(qid) in ('answered', 'closed'))
    lines += [f'ANSWER {fid}' for fid in answered]
    return lines, {'findings': sorted(found_seen | set(new_ids)), 'answers': sorted(answer_seen | set(answered))}


def wait(cfg: dict, session: str | None, timeout: float, interval: float) -> int:
    if not role.available():
        print(role.missing_message(), file=sys.stderr)
        return NO_SUPERVISION
    if not session:
        print('usage-watch wait: --session is required', file=sys.stderr)
        return USAGE
    deadline = time.monotonic() + timeout if timeout > 0 else None
    while True:
        if _not_holder(cfg, session):
            print('NOT HOLDER: another live session holds the usage role', file=sys.stderr)
            return NOT_HOLDER
        lines, seen = events(cfg)
        if lines:
            write_json(announced_path(cfg), seen)
            print('\n'.join(lines))
            return 0
        if deadline is not None and time.monotonic() >= deadline:
            print(f'TIMEOUT {timeout:g}s')
            return 0
        pause = max(0.05, interval)
        if deadline is not None:
            pause = max(0.01, min(pause, deadline - time.monotonic()))
        time.sleep(pause)
