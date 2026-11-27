"""Files under the state directory: atomic JSON writes, an exclusive lock, corrupt files moved aside."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def write_json(path: str, data) -> None:
    ensure_dir(os.path.dirname(path))
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write('\n')
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def move_aside(path: str) -> str:
    """Rename a corrupt file to <name>.corrupt-<n> (first free n) and return the new name."""
    n = 1
    while os.path.exists(f'{path}.corrupt-{n}'):
        n += 1
    os.replace(path, f'{path}.corrupt-{n}')
    return f'{path}.corrupt-{n}'


def read_json(path: str, default, aside: bool = False):
    """The file's JSON when it has the default's type; else the default. A corrupt file is moved aside when asked."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        if aside and os.path.exists(path):
            move_aside(path)
        return default
    if not isinstance(data, type(default)):
        if aside:
            move_aside(path)
        return default
    return data


def read_json_quiet(path: str):
    """Any JSON value, or None (missing, unreadable, corrupt). For files owned by other pieces: never touched."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class Locked:
    """Exclusive flock on <path>.lock for the duration of the block."""

    def __init__(self, path: str):
        self.path = path + '.lock'
        self.fh = None

    def __enter__(self):
        ensure_dir(os.path.dirname(self.path))
        self.fh = open(self.path, 'a')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()
        return False
