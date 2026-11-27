"""Project and role of each session (design D4), from files only.

Supervision's data is read as plain JSON and never written: lock files `<supervisor home>/locks/*.json`, the usage role
record `<supervisor home>/usage-role.json`, and the desktop app's session records
`<app_sessions_dir>/*/*/local_*.json`. No piece of the supervision module is run or imported (design D1), so this half
works the same with or without it. App ids (`local_…`) are joined to the transcripts' CLI ids through `cliSessionId`.
"""
from __future__ import annotations

import glob
import os
import subprocess

from . import config as C
from .state import read_json_quiet


def app_records(cfg: dict) -> list[dict]:
    base = glob.escape(C.path(cfg, 'app_sessions_dir'))
    out = []
    for path in sorted(glob.glob(os.path.join(base, '*', '*', 'local_*.json'))):
        rec = read_json_quiet(path)
        if isinstance(rec, dict) and isinstance(rec.get('sessionId'), str) and rec['sessionId']:
            out.append(rec)
    return out


def live_locks(cfg: dict) -> list[dict]:
    """Lock files that are not released; staleness is ignored (a quiet supervisor still names its sessions)."""
    out = []
    for path in sorted(glob.glob(os.path.join(glob.escape(C.supervisor_home(cfg)), 'locks', '*.json'))):
        lock = read_json_quiet(path)
        if not isinstance(lock, dict) or lock.get('released') or lock.get('state') == 'released':
            continue
        out.append(lock)
    return out


def usage_role(cfg: dict) -> dict | None:
    rec = read_json_quiet(os.path.join(C.supervisor_home(cfg), 'usage-role.json'))
    return rec if isinstance(rec, dict) and (rec.get('session_id') or rec.get('cli_session_id')) else None


def project_of(cwd, cache: dict) -> tuple[str, str]:
    """(name, root): the main checkout of `cwd` (git common dir), else its basename, else `unknown`."""
    if not isinstance(cwd, str) or not cwd:
        return 'unknown', ''
    if cwd in cache:
        return cache[cwd]
    result = (os.path.basename(cwd.rstrip('/')) or 'unknown', cwd)
    if os.path.isdir(cwd):
        try:
            r = subprocess.run(['git', '-C', cwd, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                               capture_output=True, text=True, timeout=10)
            common = r.stdout.strip() if r.returncode == 0 else ''
        except (OSError, subprocess.SubprocessError):
            common = ''
        if common:
            common = os.path.realpath(common)
            root = os.path.dirname(common) if os.path.basename(common) == '.git' else common
            result = (os.path.basename(root) or 'unknown', root)
    cache[cwd] = result
    return result


def sessions_info(cfg: dict, sessions_meta: dict) -> dict[str, dict]:
    """CLI session id -> {project, project_root, role, app_id, cwd, routine}."""
    records = app_records(cfg)
    by_cli = {}
    for rec in records:
        cli = rec.get('cliSessionId')
        if isinstance(cli, str) and cli:
            by_cli.setdefault(cli, rec)
    app_to_cli = {rec['sessionId']: rec.get('cliSessionId') for rec in records}

    def cli_ids(app_or_cli):
        if not isinstance(app_or_cli, str) or not app_or_cli:
            return set()
        return {app_or_cli} | ({app_to_cli[app_or_cli]} if isinstance(app_to_cli.get(app_or_cli), str) else set())

    roles = {}
    for lock in live_locks(cfg):
        for field, role in (('session_id', 'supervisor'), ('mailbox', 'questions'), ('closer', 'closer')):
            for cli in cli_ids(lock.get(field)):
                roles.setdefault(cli, role)
    holder = usage_role(cfg)
    if holder:
        for field in ('session_id', 'cli_session_id'):
            for cli in cli_ids(holder.get(field)):
                roles[cli] = 'usage'
    cache = {}
    out = {}
    for cli, meta in sessions_meta.items():
        rec = by_cli.get(cli, {})
        cwd = meta.get('cwd') if isinstance(meta, dict) else None
        cwd = cwd or (rec.get('cwd') if isinstance(rec.get('cwd'), str) else None)
        name, root = project_of(cwd, cache)
        routine = bool(rec.get('scheduledTaskId'))
        role = roles.get(cli) or ('routine' if routine else 'worker')
        out[cli] = {'project': name, 'project_root': root, 'role': role, 'cwd': cwd, 'routine': routine,
                    'app_id': rec.get('sessionId') if rec else None}
    return out
