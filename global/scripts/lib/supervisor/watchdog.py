"""The watchdog: stale or dead supervisors, alerts and nudges."""
import glob
import os
import time
from datetime import datetime

from . import census, cloud, lock as lock_mod, providers, revival, settings, titles, transcripts, util


def stale_reason(rec, now, window):
    """Why an alive owner with an old heartbeat is quiet: (reason, event epoch or None, detail) or None when busy.

    rec is its CLI record (None when unknown). busy: a transcript was touched within `window` s. api/limit: the
    newest record is an API error. human: a human-bound tool call nobody answered. idle: none of those.
    """
    main, subs = transcripts.session_files(rec.get('sessionId'), rec.get('cwd')) if rec else (None, [])
    if not main:
        return 'unknown', None, ''
    if any(now - util.file_mtime(path) <= window for path in [main, *subs]):
        return None
    recs = transcripts.conv_records(main)
    if recs and recs[-1]['type'] == 'assistant' and recs[-1].get('isApiErrorMessage'):
        text = next((it.get('text') for it in transcripts.content_items(recs[-1]) if it.get('type') == 'text'), '')
        return ('limit' if recs[-1].get('error') == 'rate_limit' else 'api'), recs[-1]['_ts'], str(text or '').strip()[:100]
    hit = transcripts.waiting_on_human(recs, now)
    if hit:
        return 'human', now - hit[1], hit[0]
    return 'idle', None, ''


PUSHED_TAIL = 'Ya la he empujado yo: no tienes que hacer nada.'


def stale_text(reason, title, hh, detail, pushed=False):
    """Desktop notification text for a STALE incident. `pushed`: the nudge of this run already woke the session, so the
    text says nothing needs doing instead of asking the developer to open it and type «reanuda»."""
    if pushed:
        what = {'api': f'se paró a las {hh} por un error de conexión con la API («{detail}»).',
                'limit': f'se paró a las {hh} al agotar el límite de uso («{detail}»).',
                'human': f'esperaba una respuesta tuya ({detail}) desde las {hh}.',
                'idle': f'estaba quieta desde las {hh}: terminó un turno sin dejar armado su vigilante.'
                }.get(reason, f'no daba señales desde las {hh}.')
        return f'La sesión «{title}» {what} {PUSHED_TAIL}'
    if reason == 'api':
        return (f'La sesión «{title}» se paró a las {hh} por un error de conexión con la API («{detail}»). '
                f'Ábrela y escribe «reanuda».')
    if reason == 'limit':
        return (f'La sesión «{title}» se paró a las {hh} al agotar el límite de uso («{detail}»). '
                f'Cuando se renueve o cambies de cuenta, ábrela y escribe «reanuda».')
    if reason == 'human':
        return f'La sesión «{title}» espera una respuesta tuya ({detail}) desde las {hh}. Ábrela y contéstala.'
    if reason == 'idle':
        return (f'La sesión «{title}» está quieta desde las {hh}: terminó un turno sin dejar armado su vigilante. '
                f'Ábrela y escribe «reanuda».')
    return (f'La sesión «{title}» no da señales desde las {hh} y no encuentro su transcripción. '
            f'Ábrela: si está parada, escribe «reanuda».')


def alert_due(owner, kind, reason, realert_after):
    """True when this incident needs a notification: once per stop, never a reminder by default.

    A stop lasts until the owner is healthy or busy again (the alert fields are then cleared). Within it, only a
    new STALE reason (its transcript has a newer event) notifies again; STALE <-> DEAD is the same stop, and time
    alone re-alerts only with --realert-after > 0.
    """
    if not kind:
        return False
    if not owner.get('alerted_at'):
        return True
    if kind == 'STALE' and owner.get('alert_kind') == 'STALE' and owner.get('alert_reason') != reason:
        return True
    return realert_after > 0 and util.age_seconds(owner.get('alerted_at')) > realert_after


def warn_no_mailbox(flagged, every):
    """Desktop alert for each lock in `flagged` (key, owner) that has none within the hour; clears the mark of the rest.

    The mark is `nomailbox_alerted_at` in the lock, the only field this touches (re-read under the flock)."""
    flagged_keys = {key for key, _ in flagged}
    for key, owner in every:
        mark = owner.get('nomailbox_alerted_at')
        if key in flagged_keys:
            if mark and util.age_seconds(mark) <= lock_mod.NO_MAILBOX_ALERT_EVERY_S:
                continue
            title, project = owner.get('title') or owner.get('session_id'), owner.get('project') or key
            text = (f'La supervisión «{title}» lleva en marcha sin sesión de preguntas: al acabar no tendrá dónde '
                    f'presentarte la tanda final. Que abra «{settings.questions_title(project)}» y la registre '
                    f'con `supervisor-lock beat --mailbox`.')
            if not providers.notify(f'Supervisión sin sesión de preguntas: {project}', text):
                continue
            new_mark = util.now_iso()
        elif mark:
            new_mark = None  # it has its mailbox now (or stopped running): the next gap alerts at once
        else:
            continue
        with lock_mod.Store() as locked:
            current = locked.read(key)
            if current is None or current.get('session_id') != owner.get('session_id'):
                continue
            if new_mark:
                current['nomailbox_alerted_at'] = new_mark
            else:
                current.pop('nomailbox_alerted_at', None)
            locked.write(key, current)


def cmd_watchdog(args, pushed=frozenset()):
    """Report supervisor locks whose owner is gone (DEAD) or silent (STALE, with the reason); --notify tells the developer once.

    `pushed`: CLI session ids the nudge of this very run woke; a STALE alert for one of them says nothing needs doing."""
    live = {}
    for rec in census.read_json_files(os.path.join(census.cli_dir(), '*.json')):
        if census.pid_alive(rec.get('pid')) and rec.get('hostSessionId'):
            live[rec['hostSessionId']] = rec
    incidents, no_mailbox = [], []
    store = lock_mod.Store()  # reads need no lock: writes are atomic replaces
    now = time.time()
    for path in sorted(glob.glob(os.path.join(util.home(), 'locks', '*.json'))):
        key = os.path.basename(path)[:-5]
        owner = store.read(key)
        if not owner:
            continue
        if providers.pause_of(owner.get('checkout')):
            continue  # a project the developer paused is quiet on purpose: no alert, no incident
        if os.environ.get('SUPERVISOR_WATCHDOG_CLOUD', '1') != '0' and owner.get('checkout'):
            cloud.refresh_cloud_snapshot(owner)  # the Stop hook's cloud block reads it
        beat_age = util.age_seconds(owner.get('heartbeat'))
        alive = owner.get('session_id') in live
        limit = args.stale_after * (2 if owner.get('state') == 'paused' else 1)
        kind = 'DEAD' if not alive and beat_age > args.dead_after else 'STALE' if alive and beat_age > limit else None
        reason = ts = None
        detail = ''
        if kind == 'STALE':
            found = stale_reason(live[owner['session_id']], now, args.stale_after)
            if found is None:
                kind = None  # a long turn: it only beats while its wait runs
            else:
                reason, ts, detail = found
        if kind:
            print(f'{kind} {key} {owner.get("title") or "-"} since {owner.get("heartbeat")}'
                  + (f' reason={reason}' if reason else ''))
        elif (alive and lock_mod.lacks_mailbox(owner) and owner.get('started')
              and util.age_seconds(owner.get('started')) > lock_mod.NO_MAILBOX_GRACE_S):  # no `started`: age unknown, no warning
            # a healthy supervisor with no questions session has nowhere to present the final batch
            print(f'NOMAILBOX {key} {owner.get("title") or "-"} since {owner.get("started")}')
            no_mailbox.append((key, owner))
        incidents.append((key, owner, kind, reason, ts, detail, (live.get(owner.get('session_id')) or {}).get('sessionId') in pushed))
    if not args.notify:
        return 0
    warn_no_mailbox(no_mailbox, [(k, o) for k, o, *_ in incidents])
    for key, owner, kind, reason, ts, detail, was_pushed in incidents:
        stamp = datetime.fromtimestamp(ts).strftime('%H:%M') if ts else util.clock(owner.get('heartbeat'))
        title, project = owner.get('title') or owner.get('session_id'), owner.get('project') or key
        delivered = False
        if kind == 'DEAD' and util.age_seconds(owner.get('heartbeat')) < revival.DEAD_ALERT_GRACE_S \
                and not revival.revive_exhausted(key, owner):
            continue  # the scheduled revive task wakes it; the developer hears of it only if that fails
        if alert_due(owner, kind, reason, args.realert_after):
            text = (f'La sesión «{title}» no tiene proceso desde las {stamp} y la tarea programada de reanimación no la ha '
                    f'podido despertar (¿está abierta la app?). Ábrela y escribe «reanuda».' if kind == 'DEAD'
                    else stale_text(reason, title, stamp, detail, pushed=was_pushed))
            delivered = providers.notify(f'Supervisión parada: {project}', text)
        if not delivered and not (kind is None and ('alerted_at' in owner or 'alert_kind' in owner)):
            continue
        with lock_mod.Store() as locked:  # re-read under flock: only the alert fields are ever touched
            current = locked.read(key)
            if current is None or current.get('session_id') != owner.get('session_id'):
                continue
            current.pop('alert_reason', None)
            if delivered:
                current.update(alerted_at=util.now_iso(), alert_kind=kind)
                if reason:
                    current['alert_reason'] = reason
            else:
                current.pop('alerted_at', None)
                current.pop('alert_kind', None)
            locked.write(key, current)
    return 0


def nudge_stuck():
    """Wake stopped desktop sessions through `session-nudge stuck --send` ($SUPERVISOR_NUDGE overrides the command).

    Covers every live app session, not only lock owners: a question nobody answered for 15 min, a turn killed by a
    usage limit whose reset has passed. session-nudge keeps its own once-per-2-h state and the 6-per-run cap.
    Returns its exit code; a missing or failing command only prints a line (the watchdog must never fail on it).
    """
    code, lines, _ = providers.run_nudge()
    print('\n'.join(lines)) if lines else None
    return code


def cmd_watchdog_with_nudge(args):
    # nudge first, so the alert of an incident can say the session was already pushed; its lines still print after
    # the watchdog's own
    woken, lines = frozenset(), []
    if args.nudge:
        _, lines, woken = providers.run_nudge()
    code = cmd_watchdog(args, frozenset(woken))
    if lines:
        print('\n'.join(lines))
    try:
        titles.watchdog_sync()   # `titles --fix`: it never changes the watchdog's output contract or exit code
    except Exception as err:
        print(f'TITLES-FAILED {str(err)[:200] or type(err).__name__}')
    return code
