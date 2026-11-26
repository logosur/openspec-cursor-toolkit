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
# A supervisor whose turn was cut (the account's usage limit, an API error) keeps its process alive and idle: it is not
# dead, and nothing wakes it once the account has usage again. `revive` wakes a live, idle supervisor whose lock is
# running in a working phase (not `guardia`, where a still heartbeat is normal) and whose heartbeat is older than
# STALLED_AFTER_S, the 45 min the skill allows without attending; only while the account has usage. A turn cut by the
# usage limit (its newest record is the limit's error) counts after LIMIT_CUT_AFTER_S instead.
STALLED_AFTER_S = 45 * 60


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


def stalled_supervisors(stalled_after, now=None):
    """[(key, owner, verdict)] of live owners (project not paused) whose lock is running in a phase other than
    `guardia` with a heartbeat older than `stalled_after` s. verdict is ('busy', None, '') when the session works now
    (its CLI status, or a transcript touched within `stalled_after`), else the watchdog's (reason, epoch, detail)."""
    from . import backlog, watchdog  # imported here: both import this module
    now = time.time() if now is None else now
    live = live_hosts()
    store = lock_mod.Store()
    out = []
    for path in sorted(glob.glob(os.path.join(util.home(), 'locks', '*.json'))):
        key = os.path.basename(path)[:-5]
        owner = store.read(key)
        rec = live.get((owner or {}).get('session_id'))
        short = min(LIMIT_CUT_AFTER_S, stalled_after)
        if (not owner or not rec or owner.get('state') != 'running' or backlog.on_guard(owner)
                or util.age_seconds(owner.get('heartbeat')) <= short or providers.pause_of(owner.get('checkout'))):
            continue
        late = util.age_seconds(owner.get('heartbeat')) > stalled_after
        if rec.get('status') == 'busy':
            if late:
                out.append((key, owner, ('busy', None, '')))
            continue
        # a turn cut by the usage limit shows at once (its newest record is the limit's error), so it needs no 45 min
        # of silence: a cut shortly before the window renews, or a watcher that fires and is cut again just before
        # it, would otherwise keep the supervisor still for up to 45 min after the account has usage again
        cut = watchdog.stale_reason(rec, now, short)
        if cut and cut[0] == 'limit':
            out.append((key, owner, cut))
            continue
        if not late:
            continue
        verdict = watchdog.stale_reason(rec, now, stalled_after)
        out.append((key, owner, verdict or ('busy', None, '')))
    return out


LIMIT_CUT_AFTER_S = 5 * 60  # quiet time after which a turn cut by the usage limit counts as stalled


def stalled_text(owner, reason, ts, detail):
    since = time.strftime('%H:%M', time.localtime(ts)) if ts else util.clock(owner.get('heartbeat'))
    quiet = int(util.age_seconds(owner.get('heartbeat')) / 60)
    what = {'limit': f'tu turno se cortó hacia las {since} al agotarse el límite de uso de la cuenta («{detail}»)',
            'api': f'tu turno se cortó hacia las {since} por un error de la API («{detail}»)',
            'idle': f'terminaste un turno hacia las {since} sin dejar armado tu vigilante',
            }.get(reason, f'no das señales desde las {since}')
    return (f'{REVIVE_MARKER} No es que tu proceso muriera: sigue vivo, pero {what}, y llevas {quiet} min sin atender '
            f'la supervisión de {owner.get("project")} (fase {owner.get("phase") or "-"}). La cuenta tiene uso ahora. Te '
            'despierta la tarea programada de reanimación, no el desarrollador.\n\n'
            'Antes de seguir: haz el censo de F1 (el corte pudo dejar a medias un merge, un deploy o un test), mira '
            'get_usage antes de dar por vigente un límite de uso que anotaste (la cuenta pudo cambiar), vuelve a '
            'armar tu vigilante (`supervisor-lock wait`) y sigue tu ciclo desde donde lo dejaste, sin repetir lo hecho.')


def paused_limit_supervisors():
    """[(key, owner, busy)] of live owners (project not paused, not on guard) whose lock is paused for the usage limit
    (lock.paused_for_limit), whatever the heartbeat's age: a paused supervisor that ticks every few minutes keeps it
    fresh. busy is the CLI status only: such a supervisor touches its transcript at every tick."""
    from . import backlog  # imported here, as in stalled_supervisors
    live = live_hosts()
    store = lock_mod.Store()
    out = []
    for path in sorted(glob.glob(os.path.join(util.home(), 'locks', '*.json'))):
        key = os.path.basename(path)[:-5]
        owner = store.read(key)
        rec = live.get((owner or {}).get('session_id'))
        if (not owner or not rec or not lock_mod.paused_for_limit(owner) or backlog.on_guard(owner)
                or providers.pause_of(owner.get('checkout'))):
            continue
        out.append((key, owner, rec.get('status') == 'busy'))
    return out


def paused_limit_text(owner):
    since = util.clock(owner.get('paused_at') or owner.get('heartbeat'))
    sid = owner.get('session_id')
    return (f'{REVIVE_MARKER} La cuenta tiene uso ahora (lo dice el uso real, no la hora del límite que anotaste) y tu '
            f'cerrojo de {owner.get("project")} sigue en pausa por el límite de uso desde las {since}. El límite de uso '
            'no es motivo de pausa. Te despierta la tarea programada de reanimación, no el desarrollador.\n\n'
            f'Ahora: mira get_usage, ejecuta `supervisor-lock beat --session {sid} --state running`, haz el censo de F1, '
            'vuelve a armar tu vigilante (`supervisor-lock wait`) y sigue tu ciclo desde donde lo dejaste, sin repetir '
            'lo hecho. Si lo único que queda espera a un tercero, dilo con '
            '`--state paused --third-party "<qué espera y de quién>"`.')


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
            for key in [k for k in data if k not in dead_keys
                        and (data[k] or {}).get('kind') not in ('unattended', 'stalled', 'paused-limit')]:
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
            # a live, idle supervisor whose turn was cut (usage limit, API error) and that nobody woke: the same
            # attempts and give-up as a death, one incident per heartbeat; only while the account has usage
            stalled_keys = set()
            if has_usage is True:
                stalled = stalled_supervisors(args.stalled_after, now)
                for key, owner, (reason, ts, detail) in stalled:
                    if reason == 'busy':
                        lines.append(f'BUSY {owner["session_id"]} {key}: working now, not woken')
                        continue
                    if reason == 'human':
                        # a question to the developer is pending: a message would answer it; the watchdog tells him
                        lines.append(f'HUMAN {owner["session_id"]} {key}: waits on the developer ({detail}), not woken')
                        continue
                    stalled_keys.add(key)
                    entry = data.get(key) or {}
                    if (entry.get('kind') != 'stalled' or entry.get('incident') != owner.get('heartbeat')
                            or entry.get('session') != owner['session_id']):
                        entry = {'session': owner['session_id'], 'kind': 'stalled', 'incident': owner.get('heartbeat'),
                                 'attempts': 0}
                    if entry['attempts'] >= REVIVE_MAX_ATTEMPTS:
                        lines.append(f'GIVEUP-STALLED {owner["session_id"]} {key} attempts={entry["attempts"]}: the '
                                     'watchdog tells the developer')
                    elif now - entry.get('planned_at', 0) < REVIVE_RETRY_S:
                        lines.append(f'WAIT-STALLED {owner["session_id"]} {key} last_attempt_min='
                                     f'{int((now - entry["planned_at"]) / 60)}')
                    else:
                        entry['attempts'] += 1
                        entry['planned_at'] = now
                        entry.pop('delivery', None)
                        targets.append({'session_id': owner['session_id'], 'project': owner.get('project') or key,
                                        'key': key, 'reason': 'stalled', 'cause': reason,
                                        'quiet_since': util.clock(owner.get('heartbeat')), 'attempt': entry['attempts'],
                                        'message': stalled_text(owner, reason, ts, detail)})
                        util.hook_log('revive.log', f'PLAN-STALLED {key} {owner["session_id"]} cause={reason} '
                                               f'attempt={entry["attempts"]}')
                    data[key] = entry
                for key in [k for k in data if (data[k] or {}).get('kind') == 'stalled' and k not in stalled_keys]:
                    del data[key]  # attended again (or busy, on guard, released): the next cut is a new incident
            else:
                lines.append('HOLD-STALLED the account usage is unknown: no live supervisor with a cut turn is woken')
                stalled_keys = {k for k in data if (data[k] or {}).get('kind') == 'stalled'}  # kept as they are
            # a live supervisor whose lock is still paused for the usage limit although the account has usage again: the
            # same attempts and give-up, one incident per pause (`paused_at`, never the heartbeat, which a paused
            # supervisor that ticks keeps fresh, so the attempts would start anew every run)
            paused_keys = set()
            if has_usage is True:
                for key, owner, busy in paused_limit_supervisors():
                    if key in dead_keys or key in stalled_keys:
                        continue
                    paused_keys.add(key)
                    entry = data.get(key) or {}
                    same = entry.get('kind') == 'paused-limit' and entry.get('session') == owner['session_id']
                    incident = owner.get('paused_at') or (entry.get('incident') if same else None) or f'seen {util.now_iso()}'
                    if not same or entry.get('incident') != incident:
                        entry = {'session': owner['session_id'], 'kind': 'paused-limit', 'incident': incident, 'attempts': 0}
                    if busy:
                        lines.append(f'BUSY {owner["session_id"]} {key}: working now, not woken')
                    elif entry['attempts'] >= REVIVE_MAX_ATTEMPTS:
                        lines.append(f'GIVEUP-PAUSED {owner["session_id"]} {key} attempts={entry["attempts"]}: its watcher '
                                     '(USAGE) and the Stop hook keep telling it')
                    elif now - entry.get('planned_at', 0) < REVIVE_RETRY_S:
                        lines.append(f'WAIT-PAUSED {owner["session_id"]} {key} last_attempt_min='
                                     f'{int((now - entry["planned_at"]) / 60)}')
                    else:
                        entry['attempts'] += 1
                        entry['planned_at'] = now
                        entry.pop('delivery', None)
                        targets.append({'session_id': owner['session_id'], 'project': owner.get('project') or key,
                                        'key': key, 'reason': 'paused-limit', 'cause': 'limit',
                                        'paused_since': util.clock(owner.get('paused_at') or owner.get('heartbeat')),
                                        'attempt': entry['attempts'], 'message': paused_limit_text(owner)})
                        util.hook_log('revive.log', f'PLAN-PAUSED {key} {owner["session_id"]} cause=limit '
                                               f'attempt={entry["attempts"]}')
                    data[key] = entry
                for key in [k for k in data if (data[k] or {}).get('kind') == 'paused-limit' and k not in paused_keys]:
                    del data[key]  # running again, paused for a third party or released: the next pause is a new incident
            else:
                lines.append('HOLD-PAUSED the account usage is unknown: no live supervisor paused for the limit is woken')
                paused_keys = {k for k in data if (data[k] or {}).get('kind') == 'paused-limit'}  # kept as they are
            # a live supervisor that leaves sessions of its project unattended (cloud sessions to check, finished
            # sessions, ...) for UNATTENDED_AFTER_S is woken the same way, with the same marker and gate (the plan
            # names it, fresh)
            live = live_hosts()
            pending = {k: (o, items) for k, o, items in unattended.unattended_supervisors(now)
                       if k not in dead_keys and k not in stalled_keys and k not in paused_keys}  # one wake per supervisor: its F1 census sees them
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
        if t.get('reason') == 'stalled':
            print(f'STALLED {t["session_id"]} {t["key"]} cause={t["cause"]} quiet_since={t["quiet_since"]} '
                  f'attempt={t["attempt"]}/{REVIVE_MAX_ATTEMPTS}')
            continue
        if t.get('reason') == 'paused-limit':
            print(f'PAUSED {t["session_id"]} {t["key"]} cause={t["cause"]} paused_since={t["paused_since"]} '
                  f'attempt={t["attempt"]}/{REVIVE_MAX_ATTEMPTS}')
            continue
        if t.get('reason') == 'unattended':
            print(f'UNATTENDED {t["session_id"]} {t["key"]} items={t["items"]} attempt={t["attempt"]}')
            continue
        print(f'REVIVE {t["session_id"]} {t["key"]} dead_since={t["dead_since"]} attempt={t["attempt"]}/'
              f'{REVIVE_MAX_ATTEMPTS}')
    print('\n'.join(lines))
    if not targets:
        print('NONE nothing to revive')
    return 0
