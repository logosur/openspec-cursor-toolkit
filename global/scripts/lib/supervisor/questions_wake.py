"""ANSWERED: the supervisor learns that its questions session got an answer.

The questions session lives at the top level of the app's sidebar, so the app no longer tells the supervisor when it
ends a turn. The watcher (`wait --owner`, also on guard and with the questions session in `--exclude`) prints one
`ANSWERED` line instead, from two triggers:

- the queue: an item of the project's ask-queue became `answered` within ANSWERED_WINDOW_S; each id once, recorded in
  <home>/announced/<key>.answered.json through cloud.announce_once (its 48 h history outlives the window);
- the turn: the questions session registered in the lock completed more turns than last recorded in
  <home>/announced/<key>.questions-turns.json (first sight, another id or fewer turns are recorded silently).

While the questions session is live and busy the queue trigger is held (it records each answer, then ends its turn), so
one batch of answers wakes the supervisor once, with the turn; an answer held longer than ANSWERED_HOLD_S fires alone.
What is announced is recorded before it is printed, under the store lock, so a later poll or wait never repeats it.
Advisory: the caller logs any failure and prints nothing for it.
"""
import os

from . import closable, cloud, lock as lock_mod, providers, util

ANSWERED_WINDOW_S = 24 * 3600   # an answer older than this is never announced
ANSWERED_HOLD_S = 600           # an answer held while the questions session is busy fires alone after this long


def queue_source(project):
    """(ask-queue module, the project's queue file), resolved once per wait (`project_root` runs git); (None, None)
    when no ask-queue is installed."""
    try:
        q = providers.ask_queue_module()
    except (OSError, ImportError):
        return None, None
    return q, q.queue_path(q.project_root(project['checkout']))


def recent_answers(source, now):
    """{id: answered epoch} for the items of the queue answered within ANSWERED_WINDOW_S."""
    q, path = source
    if q is None or not path or not os.path.isfile(path):
        return {}
    found = {}
    for item in q.read_items(path):
        if item.get('status') != 'answered':
            continue
        when = q.parse_ts(item.get('answered_ts'))
        if when is None:
            continue
        stamp = when.timestamp()
        if now - stamp <= ANSWERED_WINDOW_S:
            found[str(item['id'])] = stamp
    return found


def announced_path(key, name):
    return os.path.join(util.home(), 'announced', f'{key}.{name}.json')


def unannounced(key, answers):
    """The ids of `answers` not announced yet (read without recording)."""
    data = util.read_json(announced_path(key, 'answered'), {})
    data = data if isinstance(data, dict) else {}
    return {i: t for i, t in answers.items() if i not in data}


def turn_trigger(key, mailbox, row):
    """(old, new) when the registered questions session completed more turns than last recorded, else None. Records
    the current count in every case it can read one (first sight, another id, fewer turns: silently)."""
    if not mailbox or not row or row.get('turns') is None:
        return None
    turns = int(row['turns'])
    path = announced_path(key, 'questions-turns')
    with lock_mod.Store():
        state = util.read_json(path, {})
        state = state if isinstance(state, dict) else {}
        old = util.num(state.get('turns'))
        fired = (int(old), turns) if state.get('id') == mailbox and old is not None and turns > old else None
        if state.get('id') != mailbox or old != turns:
            util.write_json_atomic(path, {'id': mailbox, 'turns': turns})
    return fired


def answered_line(key, mailbox, rows, source, now):
    """The ANSWERED line of this poll, or None. `rows` are the unfiltered census rows {local id: row}."""
    row = rows.get(mailbox) if mailbox else None
    turn = turn_trigger(key, mailbox, row)
    pending = unannounced(key, recent_answers(source, now))
    busy = bool(row and row.get('live') and row.get('status') == 'busy')
    held = busy and turn is None and pending and now - min(pending.values()) < ANSWERED_HOLD_S
    ids = []
    if pending and not held:
        ids = sorted(cloud.announce_once(key, 'answered', [(i, i) for i in sorted(pending)], closable.HOLD_HISTORY_S, now))
    if turn is None and not ids:
        return None
    parts = [f'ANSWERED {mailbox or "-"}']
    if turn is not None:
        parts.append(f'turno {turn[0]}->{turn[1]}')
    if ids:
        parts.append(f'contestadas {",".join(ids)}')
    return (' '.join(parts) + ' (la sesión de preguntas tiene respuesta del desarrollador: lee el resultado con '
            'list_events de esa sesión y sigue según f5-decisiones.md, «La sesión de preguntas»)')
