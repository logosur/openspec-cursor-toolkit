"""Helpers shared by every module: clock, JSON files, text and process exits."""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime


def home():
    return os.path.expanduser(os.environ.get('SUPERVISOR_LOCK_HOME', '~/.claude/supervisor'))


def die(message, code=2):
    print(message, file=sys.stderr)
    sys.exit(code)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def age_seconds(stamp):
    try:
        return max(0, int((datetime.now().astimezone() - datetime.fromisoformat(stamp)).total_seconds()))
    except (TypeError, ValueError):
        return 10 ** 9


def hours(seconds):
    return '-' if seconds is None else f'{seconds / 3600:.1f} h'


def num(value):
    """A json number (epoch ms, count) or None; bools and strings are not numbers."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def file_mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0


def parse_ts(stamp):
    try:
        return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


def write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f'.{os.getpid()}.tmp'
    with open(tmp, 'w') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def span(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds >= 2 * 86400:
        return f'{seconds // 86400} d'
    if seconds >= 3600:
        return f'{seconds // 3600} h {seconds % 3600 // 60:02d} min'
    return f'{seconds // 60} min'


def clock(stamp):
    try:
        return datetime.fromisoformat(stamp).strftime('%H:%M')
    except (TypeError, ValueError):
        return '??:??'


# ---------------------------------------------------------------- hook

def hook_log(name, text):
    os.makedirs(home(), exist_ok=True)
    with open(os.path.join(home(), name), 'a') as fh:
        fh.write(f'{now_iso()} {text}\n')


def fold_text(text):
    """Lower-case text without accents (NFKD), for matching human wording."""
    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).lower()


def clip(text, limit=300):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


# What a title must never be: the literal output of a `supervisor-lock` status line pasted in by mistake
_STATUS_TITLE = re.compile(r'^\s*(HELD|STALE|MINE|FREE|ACQUIRED|RESUMED)\b')


def title_refusal(title):
    """Why `title` cannot name a session or a lock (it looks like `supervisor-lock` output), or None when it can."""
    text = str(title or '')
    if _STATUS_TITLE.match(text) or 'session=local_' in text or 'heartbeat_age' in text:
        return ('el título parece la salida de `supervisor-lock` (una línea de estado), no un nombre de sesión: '
                f'«{clip(text, 80)}»')
    return None
