"""Configuration and local-file helpers shared by `mailbox` and `stores`.

Nothing here reads a path at import time: the home directory, the config directory and the cache directory are
resolved on every call, so a test can redirect them with HOME, CLAUDE_TOOLKIT_CONFIG_DIR and XDG_CACHE_HOME.
Secrets are never logged, printed or placed in an exception message.
"""
from __future__ import annotations

import copy
import json
import os
import re
import stat
from pathlib import Path


def _config_dir() -> Path:
    try:
        from toolkit_config import config_dir  # lives in the parent lib directory once installed
        return config_dir()
    except ImportError:
        env = os.environ.get('CLAUDE_TOOLKIT_CONFIG_DIR')
        return Path(env).expanduser() if env else Path('~/.claude/toolkit/config').expanduser()


def expand(path: str) -> Path:
    """`~` and environment variables."""
    return Path(os.path.expanduser(os.path.expandvars(str(path))))


def config_path(piece: str) -> Path:
    return _config_dir() / f'{piece}.json'


def load(piece: str, defaults: dict) -> tuple[dict, str | None]:
    """The config piece over DEFAULTS, deep-merged: the installer merges pieces shallowly, so an installed file may
    carry a partial nested object and the sibling defaults must survive. A missing file gives the defaults; a broken
    one gives the defaults and a one-line problem naming the file."""
    values = copy.deepcopy(defaults)
    path = config_path(piece)
    try:
        raw = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return values, None
    except (OSError, UnicodeDecodeError) as exc:
        return values, f'{path}: cannot be read ({type(exc).__name__})'
    try:
        data = json.loads(raw)
    except ValueError:
        return values, f'{path}: not valid JSON, using the defaults'
    if not isinstance(data, dict):
        return values, f'{path}: not a JSON object, using the defaults'
    return deep_merge(values, data), None


def deep_merge(base: dict, over: dict) -> dict:
    """OVER laid over BASE, recursively for dict values; lists and scalars are replaced. Returns a new dict."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def lookup(table: object, name: str) -> dict | None:
    """The entry NAME of a config table (accounts, apps), or None; a non-dict entry does not count."""
    if isinstance(table, dict) and isinstance(table.get(name), dict):
        return table[name]
    return None


def is_private(path) -> tuple[bool, str]:
    """A regular file owned by the user with no group or other permission bits; else the reason."""
    path = Path(path)
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return False, f'{path} does not exist'
    except OSError as exc:
        return False, f'{path} cannot be checked ({type(exc).__name__})'
    if not stat.S_ISREG(info.st_mode):
        return False, f'{path} is not a regular file'
    if info.st_uid != os.geteuid():
        return False, f'{path} is not owned by the current user'
    if info.st_mode & 0o077:
        return False, f'{path} has mode {stat.S_IMODE(info.st_mode):04o}; it must be 0600 (no access for group or others)'
    return True, ''


_ENV_LINE = re.compile(r'^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')


def read_env_file(path) -> dict[str, str]:
    """KEY=VALUE lines, optional `export`, matching quotes stripped, `#` comments. Values are taken literally
    (no escapes, no expansion). Raises OSError when unreadable; the message never carries file content."""
    result: dict[str, str] = {}
    with open(Path(path), 'r', encoding='utf-8', errors='replace') as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            match = _ENV_LINE.match(line)
            if not match:
                continue
            key, value = match.group(1), match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            else:
                value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
            result[key] = value
    return result


def cache_dir(piece: str) -> Path:
    """$XDG_CACHE_HOME (or ~/.cache)/claude-toolkit/<piece>, created with mode 0700."""
    if not re.fullmatch(r'[A-Za-z0-9._-]+', piece) or piece in ('.', '..'):
        raise ValueError('invalid piece name')
    base = os.environ.get('XDG_CACHE_HOME')
    root = Path(base).expanduser() if base else Path(os.path.expanduser('~')) / '.cache'
    toolkit = root / 'claude-toolkit'
    leaf = toolkit / piece
    root.mkdir(parents=True, exist_ok=True)
    for directory in (toolkit, leaf):
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
    return leaf
