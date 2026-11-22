#!/usr/bin/env python3
"""Per-piece configuration for toolkit scripts and hooks.

Each piece reads only its own file, ~/.claude/toolkit/config/<piece>.json, written by the
installer from the toolkit defaults overlaid by the user's override. The directory can be
redirected with CLAUDE_TOOLKIT_CONFIG_DIR (tests). A missing or corrupt file never breaks a
piece: load() falls back to the defaults the piece passes in, so hooks fail open.

Python:  from toolkit_config import load; cfg = load('worktree-location', {'root': '~/worktrees'})
Shell:   python3 ~/.claude/scripts/lib/toolkit_config.py get worktree-location root [default]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_dir() -> Path:
    env = os.environ.get('CLAUDE_TOOLKIT_CONFIG_DIR')
    return Path(env).expanduser() if env else Path('~/.claude/toolkit/config').expanduser()


def load(piece: str, defaults: dict | None = None) -> dict:
    values = dict(defaults or {})
    try:
        data = json.loads((config_dir() / f'{piece}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return values
    if isinstance(data, dict):
        values.update(data)
    return values


def _same_shape(value, default) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    if isinstance(default, str):
        return isinstance(value, str) and (bool(value.strip()) or not default)
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
    return isinstance(value, type(default))


def load_checked(piece: str, defaults: dict) -> dict:
    """load() for pieces where a wrong value could widen a permission (an empty marker matches every
    text): only known keys count, and a value of the wrong shape keeps the code's default."""
    values = load(piece)
    return {key: values[key] if key in values and _same_shape(values[key], default) else default
            for key, default in defaults.items()}


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == 'get':
        default = argv[3] if len(argv) > 3 else ''
        value = load(argv[1]).get(argv[2], default)
        print(json.dumps(value) if isinstance(value, (dict, list)) else value)
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
