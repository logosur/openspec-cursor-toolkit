"""The wake journal: one durable record per run of `supervisor-lock wait --owner`, beside the project's lock.

The watcher prints its events on stdout and exits, so without a journal they are lost once the caller's context
moves on. The file is <home>/wakes/<key>.jsonl, one JSON object per line, named after the lock's key. It has a folder of
its own, next to `locks`, because the locks folder holds only locks: its readers and the self-test take every file in
it for one. Appends and pruning happen under the same machine-wide flock as the locks.
"""
import json
import os
from datetime import datetime, timezone

from . import lock as lock_mod, util

WAKES_KEEP_S = 30 * 86400


def path(key):
    return os.path.join(util.home(), 'wakes', key + '.jsonl')


def iso(epoch):
    """Epoch seconds as UTC ISO-8601 with milliseconds and a Z suffix."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def parse_iso(text):
    """Epoch seconds of a stamp written by `iso`, or None when it is not one."""
    try:
        return datetime.strptime(text, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def parse_line(line):
    """The record of one journal line, or None when it is not a JSON object."""
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


def is_old(rec, cutoff):
    """True when the record is unreadable or ended before `cutoff` (epoch seconds)."""
    ended = parse_iso(rec.get('ended')) if rec else None
    return ended is None or ended < cutoff


def write_private(target, text):
    """Replace `target` atomically with `text`, mode 0600."""
    tmp = f'{target}.{os.getpid()}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(text)
    os.replace(tmp, target)


def record(key, owner, started, ended, lines, now=None):
    """Append one record of a wake (epoch seconds in, ISO out) and drop the records older than WAKES_KEEP_S.

    The file is rewritten only when its first line is old or unreadable; otherwise the record is appended."""
    now = ended if now is None else now
    cutoff = now - WAKES_KEEP_S
    entry = json.dumps({'owner': owner, 'started': iso(started), 'ended': iso(ended), 'events': list(lines)},
                       sort_keys=True, ensure_ascii=False) + '\n'
    target = path(key)
    with lock_mod.Store():
        os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
        try:
            with open(target, encoding='utf-8') as fh:
                first = fh.readline()
        except FileNotFoundError:
            first = ''
        if first and is_old(parse_line(first), cutoff):
            with open(target, encoding='utf-8') as fh:
                kept = [l if l.endswith('\n') else l + '\n' for l in fh
                        if l.strip() and not is_old(parse_line(l), cutoff)]
            write_private(target, ''.join(kept) + entry)
            return
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(entry)


def read(key):
    """The records of the journal, oldest first; lines that do not parse are skipped."""
    try:
        with open(path(key), encoding='utf-8') as fh:
            return [rec for rec in map(parse_line, fh) if rec is not None]
    except FileNotFoundError:
        return []
