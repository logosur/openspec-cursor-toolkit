"""Merge hook fragments into settings.json without touching anything else.

An entry's identity is (event, matcher, normalised command): a leading interpreter
(python3/bash/sh) is ignored and $HOME or the absolute home is written as ~.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

INTERPRETER_RE = re.compile(r'^(?:python3?|bash|sh)\s+')


class SettingsError(Exception):
    pass


def normalise(command: str, home: str | None = None) -> str:
    cmd = INTERPRETER_RE.sub('', command.strip())
    home = home or os.path.expanduser('~')
    cmd = cmd.replace('$HOME/', '~/').replace('${HOME}/', '~/')
    if home and home != '/':
        cmd = cmd.replace(home.rstrip('/') + '/', '~/')
    return cmd


def identities(hooks_block: dict) -> list[tuple[str, str, str]]:
    out = []
    for event, entries in (hooks_block or {}).items():
        for entry in entries or []:
            for hook in entry.get('hooks') or []:
                out.append((event, entry.get('matcher', ''), normalise(hook.get('command', ''))))
    return out


def fragment_entries(fragment: dict, target: Path) -> list[dict]:
    """Flatten a fragment into one record per command, retargeting ~/.claude/ to TARGET."""
    out = []
    default_dir = os.path.expanduser('~/.claude')
    for event, entries in fragment.items():
        for entry in entries or []:
            for hook in entry.get('hooks') or []:
                h = dict(hook)
                if target != Path(default_dir):
                    h['command'] = h['command'].replace('~/.claude/', f'{target}/')
                out.append({'event': event, 'matcher': entry.get('matcher'), 'hook': h,
                            'disabled': bool(entry.get('disabled'))})
    return out


def read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise SettingsError(f'{path} is not valid JSON ({exc}); nothing was written') from exc
    if not isinstance(data, dict):
        raise SettingsError(f'{path} is not a JSON object; nothing was written')
    return data


def _key(rec: dict) -> tuple[str, str, str]:
    return (rec['event'], rec.get('matcher') or '', normalise(rec['hook']['command']))


def plan_add(settings: dict, records: list[dict]) -> list[dict]:
    """Records not yet present (and not disabled), in order, without duplicates."""
    present = set(identities(settings.get('hooks') or {}))
    disabled = {_key(r) for r in records if r['disabled']}
    out, seen = [], set()
    for rec in records:
        k = _key(rec)
        if rec['disabled'] or k in present or k in seen or k in disabled:
            continue
        seen.add(k)
        out.append(rec)
    return out


def add(settings: dict, records: list[dict]) -> dict:
    hooks = settings.setdefault('hooks', {})
    for rec in records:
        entry = {'hooks': [rec['hook']]}
        if rec.get('matcher') is not None:
            entry = {'matcher': rec['matcher'], **entry}
        hooks.setdefault(rec['event'], []).append(entry)
    return settings


def remove(settings: dict, keys: list[tuple[str, str, str]]) -> tuple[dict, int]:
    """Remove hook commands whose identity is in KEYS; drop entries and events left empty."""
    wanted = set(map(tuple, keys))
    removed = 0
    hooks = settings.get('hooks') or {}
    for event in list(hooks):
        kept_entries = []
        for entry in hooks[event] or []:
            kept = []
            for hook in entry.get('hooks') or []:
                if (event, entry.get('matcher', '') or '', normalise(hook.get('command', ''))) in wanted:
                    removed += 1
                else:
                    kept.append(hook)
            if kept:
                kept_entries.append({**entry, 'hooks': kept})
        if kept_entries:
            hooks[event] = kept_entries
        else:
            del hooks[event]
    if 'hooks' in settings and not settings['hooks']:
        del settings['hooks']
    return settings, removed


def dumps(settings: dict) -> bytes:
    return (json.dumps(settings, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def key_of(rec: dict) -> list[str]:
    return list(_key(rec))
