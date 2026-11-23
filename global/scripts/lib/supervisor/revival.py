"""Dead supervisors to wake and the record of each wake-up."""
import contextlib
import fcntl
import glob
import json
import os
import sys
import time

from . import census, lock as lock_mod, providers, settings, unattended, util


# ---------------------------------------------------------------- revive
# A supervisor whose process died (the app restarted, a crash) ends its turn normally, so no hook and no watcher of its
# own wakes it. Only the app can start a session without a process: a scheduled task of the app (optional, not part of
# the toolkit) runs `revive --plan` every few minutes and sends each target its text. The cross-project message gate lets
# the marker through only for a target this plan named in the last REVIVE_VALID_S.
REVIVE_MARKER = settings.REVIVE_MARKER
REVIVE_MAX_ATTEMPTS = 3
REVIVE_RETRY_S = 10 * 60
REVIVE_VALID_S = settings.REVIVE_VALID_S
DEAD_ALERT_GRACE_S = 50 * 60  # a DEAD supervisor reaches the developer only after the reviver had its chances


def revive_path():
    return os.path.join(util.home(), 'revive.json')


@contextlib.contextmanager
def revive_locked():
    os.makedirs(util.home(), exist_ok=True)
    with open(revive_path() + '.lock', 'a') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def revive_load():
    try:
        with open(revive_path()) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def revive_save(data):
    tmp = revive_path() + f'.{os.getpid()}.tmp'
    with open(tmp, 'w') as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, revive_path())


def live_hosts():
    live = {}
    for rec in census.read_json_files(os.path.join(census.cli_dir(), '*.json')):
        if census.pid_alive(rec.get('pid')) and rec.get('hostSessionId'):
            live[rec['hostSessionId']] = rec
    return live


def dead_supervisors(dead_after):
    """(key, owner) of every lock whose owner has no process and no heartbeat for `dead_after` s, paused projects out."""
    live = live_hosts()
    store = lock_mod.Store()
    out = []
    for path in sorted(glob.glob(os.path.join(util.home(), 'locks', '*.json'))):
        key = os.path.basename(path)[:-5]
        owner = store.read(key)
        if not owner or not owner.get('session_id') or providers.pause_of(owner.get('checkout')):
            continue
        if owner.get('session_id') not in live and util.age_seconds(owner.get('heartbeat')) > dead_after:
            out.append((key, owner))
    return out


def revive_text(owner):
    since = util.clock(owner.get('heartbeat'))
    return (f'{REVIVE_MARKER} Tu proceso murió hacia las {since} (un reinicio de la app u otro corte) y nadie te '
            'despertó. Te despierta la tarea programada de reanimación, no el desarrollador.\n\n'
            'Antes de seguir: haz el censo de F1 (pudiste morir a mitad de un merge, un deploy o un test), mira '
            'get_usage antes de dar por vigente un límite de uso que anotaste (la cuenta pudo cambiar), vuelve a '
            'armar tu vigilante (`supervisor-lock wait`) y sigue tu ciclo desde donde lo dejaste, sin repetir lo hecho.')


def revive_exhausted(key, owner):
    entry = revive_load().get(key) or {}
    return entry.get('incident') == owner.get('heartbeat') and entry.get('attempts', 0) >= REVIVE_MAX_ATTEMPTS


def cmd_revive(args):
    now = time.time()
    if args.sent:
        with revive_locked():
            data = revive_load()
            for key, entry in data.items():
                if entry.get('session') == args.sent:
                    entry['delivery'] = args.delivery or 'unknown'
                    entry['sent_at'] = now
                    revive_save(data)
                    util.hook_log('revive.log', f'SENT {key} {args.sent} delivery={entry["delivery"]} '
                                           f'attempt={entry.get("attempts")}')
                    print(f'recorded {key} delivery={entry["delivery"]}')
                    return 0
        print(f'unknown target {args.sent}', file=sys.stderr)
        return 2
    has_usage = providers.account_has_usage()
    targets, lines = [], []
    if has_usage is False:
        lines.append('HOLD the account is out of usage: nobody is woken until it has usage again')
    else:
        with revive_locked():
            data = revive_load()
            dead = dead_supervisors(args.dead_after)
            dead_keys = {k for k, _ in dead}
            for key in [k for k in data if k not in dead_keys and (data[k] or {}).get('kind') != 'unattended']:
                del data[key]  # alive again (or released): the next death is a new incident
            for key, owner in dead:
                entry = data.get(key) or {}
                if entry.get('incident') != owner.get('heartbeat') or entry.get('session') != owner['session_id']:
                    entry = {'session': owner['session_id'], 'incident': owner.get('heartbeat'), 'attempts': 0}
                if entry['attempts'] >= REVIVE_MAX_ATTEMPTS:
                    lines.append(f'GIVEUP {owner["session_id"]} {key} attempts={entry["attempts"]}: the watchdog tells '
                                 'the developer')
                elif now - entry.get('planned_at', 0) < REVIVE_RETRY_S:
                    lines.append(f'WAIT {owner["session_id"]} {key} last_attempt_min='
                                 f'{int((now - entry["planned_at"]) / 60)}')
                else:
                    entry['attempts'] += 1
                    entry['planned_at'] = now
                    entry.pop('delivery', None)
                    targets.append({'session_id': owner['session_id'], 'project': owner.get('project') or key,
                                    'key': key, 'reason': 'dead', 'dead_since': util.clock(owner.get('heartbeat')),
                                    'attempt': entry['attempts'], 'message': revive_text(owner)})
                    util.hook_log('revive.log', f'PLAN {key} {owner["session_id"]} attempt={entry["attempts"]}')
                data[key] = entry
            # a live supervisor that leaves sessions of its project unattended (cloud sessions to check, finished
            # sessions, ...) for UNATTENDED_AFTER_S is woken the same way, with the same marker and gate (the plan
            # names it, fresh)
            live = live_hosts()
            pending = {k: (o, items) for k, o, items in unattended.unattended_supervisors(now) if k not in dead_keys}
            for key in [k for k in data if (data[k] or {}).get('kind') == 'unattended' and k not in pending]:
                del data[key]
            for key, (owner, items) in sorted(pending.items()):
                ids = sorted(i for i, _ in items)
                entry = data.get(key) or {}
                if (entry.get('kind') != 'unattended' or entry.get('session') != owner['session_id']
                        or set(ids) - set(entry.get('items') or [])):
                    entry = {'session': owner['session_id'], 'kind': 'unattended', 'attempts': 0}  # new items: anew
                entry['items'] = ids
                if (live.get(owner['session_id']) or {}).get('status') == 'busy':
                    lines.append(f'BUSY {owner["session_id"]} {key}: working now, not woken')
                elif now - entry.get('planned_at', 0) < (unattended.UNATTENDED_RETRY_S if entry['attempts'] < unattended.UNATTENDED_MAX_ATTEMPTS
                                                         else unattended.UNATTENDED_SLOW_RETRY_S):
                    # no silent give-up: after UNATTENDED_MAX_ATTEMPTS wakes an hour apart it keeps waking it every
                    # UNATTENDED_SLOW_RETRY_S, saying how many it has ignored
                    lines.append(f'WAIT-UNATTENDED {owner["session_id"]} {key} last_attempt_min='
                                 f'{int((now - entry["planned_at"]) / 60)} attempts={entry["attempts"]}')
                else:
                    entry['attempts'] += 1
                    entry['planned_at'] = now
                    entry.pop('delivery', None)
                    targets.append({'session_id': owner['session_id'], 'project': owner.get('project') or key,
                                    'key': key, 'reason': 'unattended', 'items': len(ids),
                                    'attempt': entry['attempts'],
                                    'message': unattended.unattended_text(owner, items, entry['attempts'])})
                    util.hook_log('revive.log', f'PLAN-UNATTENDED {key} {owner["session_id"]} attempt={entry["attempts"]} '
                                           f'items={",".join(ids)[:300]}')
                data[key] = entry
            revive_save(data)
    if args.json:
        print(json.dumps({'targets': targets, 'notes': lines}, ensure_ascii=False, indent=1))
        return 0
    for t in targets:
        if t.get('reason') == 'unattended':
            print(f'UNATTENDED {t["session_id"]} {t["key"]} items={t["items"]} attempt={t["attempt"]}')
            continue
        print(f'REVIVE {t["session_id"]} {t["key"]} dead_since={t["dead_since"]} attempt={t["attempt"]}/'
              f'{REVIVE_MAX_ATTEMPTS}')
    print('\n'.join(lines))
    if not targets:
        print('NONE nothing to revive')
    return 0
