"""Finished sessions to close: report, holds, cache and Stop block."""
import glob
import json
import os
import time
from datetime import datetime

from . import census, closing, interrupted, lock as lock_mod, projects, settings, transcripts, util, verdicts


# ---------------------------------------------------------------- finished sessions (F4b, mechanical)
# Left to judgment, finished sessions stay open: an old registry line, a label nobody re-checks, a child kept "waiting
# for another piece". `closable` decides it from facts, and the Stop hook enforces it.
CLOSE_IDLE_S = 7200          # quiet for 2 h with nothing of its own running: finished, whoever opened it
SUBAGENT_RECENT_S = 600      # a subagent transcript written this recently means the session is still working
HOLD_DEFAULT_H, HOLD_MAX_H = 6, 12
CLOSABLE_CACHE_FRESH_S = 1200
CLOSABLE_BLOCK_EVERY_S = 600


def background_work(pid, kids):
    """pid of a Bash-tool command or heavy-job still running under the CLI process `pid`, or None."""
    stack, seen = list(kids.get(pid, [])), set()
    while stack:
        child = stack.pop()
        if child in seen:
            continue
        seen.add(child)
        try:
            with open(f'/proc/{child}/cmdline', 'rb') as fh:
                argv = fh.read()
        except OSError:
            continue
        if b'shell-snapshots' in argv or b'heavy-job' in argv:
            return child
        stack.extend(kids.get(child, []))
    return None


def holds_path(key):
    return os.path.join(util.home(), 'holds', key + '.json')


def read_holds(key, now=None, expired=False):
    """Holds of a lock: {target id: {reason, until, by, first_epoch, renewals}}; expired ones are dropped unless
    `expired` (cmd_hold keeps them for a while so a re-hold does not reset first_epoch)."""
    now = time.time() if now is None else now
    try:
        with open(holds_path(key)) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, dict) and (expired or (util.num(v.get('until_epoch')) or 0) > now)}


HOLD_HISTORY_S = 48 * 3600  # an expired hold is remembered this long: holding it again counts as a renewal


def closable_report(project, owner, rows=None, kids=None, now=None):
    """(candidates, held, working, cut): sessions of the project that F4b must close now, oldest first.

    A candidate is any non-archived session except the lock owner and its questions session (by lock field or
    title) that is not busy, not awaiting the developer, has no Bash/heavy-job process running under its CLI
    process, no subagent transcript written in the last 10 min, and has been quiet for CLOSE_IDLE_S, or has no
    process at all. `held` are candidates the owner parked with `hold` (reason and expiry); `working` the quiet ones
    that still run something of their own (for the report). `cut` are sessions whose last record is an API error: not
    finished, never candidates (entries {id, title, idle_s, reason: limit|api, since, text}); a held one is in `held`.
    A session whose last message is the /cierra-sesion verdict «Sí, puedes cerrar» is a candidate at once, whatever
    its idle time, and a hold does not park it (entry `verdict`: when it said so)."""
    now = time.time() if now is None else now
    rows = census.collect_sessions(project, False, {}) if rows is None else rows
    kids = census.children_map() if kids is None else kids
    pids = {}
    for rec in census.read_json_files(os.path.join(census.cli_dir(), '*.json')):
        if isinstance(rec.get('sessionId'), str) and census.pid_alive(rec.get('pid')):
            pids[rec['sessionId']] = rec['pid']
    holds = read_holds(project['key'], now)
    mine = {i for i in ((owner or {}).get('session_id'),) if i}
    candidates, held, working, cut = [], [], [], []
    for r in rows:
        if r['id'] in mine or r.get('cli') in mine or closing.is_helper_row(r, owner):
            continue
        if r['live'] and (r.get('status') not in (None, 'idle') or r.get('awaiting')):
            continue
        idle = r.get('idle_s')
        stop = interrupted.cut_info(r)
        verdict = None if stop else verdicts.close_verdict(r)
        if not stop and not verdict and r['live'] and (idle is None or idle < CLOSE_IDLE_S):
            continue
        entry = {'id': r['id'], 'title': r.get('title') or '-', 'idle_s': idle,
                 'reason': 'dijo «Sí, puedes cerrar»' if verdict else ('ociosa' if r['live'] else 'sin proceso')}
        if verdict:
            entry['verdict'] = verdict['since']
        pid = pids.get(r.get('cli'))
        bg = background_work(pid, kids) if pid else None
        subs = transcripts.session_files(r.get('cli'), r.get('cwd'))[1] if r.get('cli') else []
        if bg or any(now - util.file_mtime(p) < SUBAGENT_RECENT_S for p in subs):
            working.append(dict(entry, pid=bg))
            continue
        hold = holds.get(r['id'])
        if verdict and (settings.ARCHIVE_PREAUTHORISED or not settings.archive_queued(hold)):
            hold = None   # a verdict is the end of the work: only a queued archiving decision parks it
        if hold:
            held.append(dict(entry, hold=hold))
            continue
        if stop:
            cut.append({'id': r['id'], 'title': entry['title'], 'idle_s': idle, **stop})
            continue
        candidates.append(entry)
    key = lambda e: -(e['idle_s'] or 0)
    return sorted(candidates, key=key), sorted(held, key=key), working, sorted(cut, key=lambda e: e['since'])


def cmd_closable(args):
    project = projects.resolve(args.dir)
    with lock_mod.Store() as store:
        owner = store.read(project['key'])
    candidates, held, working, cut = closable_report(project, owner)
    if args.json:
        print(json.dumps({'key': project['key'], 'closable': candidates, 'held': held, 'working': working, 'cut': cut},
                         indent=2))
        return 0
    for e in cut:
        print(f'CUT {e["id"]} {e["reason"]} desde {time.strftime("%H:%M", time.localtime(e["since"]))}: '
              f'reanudar, no cerrar | {e["title"]}')
    for e in candidates:
        print(f'CLOSABLE {e["id"]} {e["reason"]} {util.hours(e["idle_s"])} | {e["title"]}')
    for e in held:
        hold = e['hold']
        since = util.num(hold.get('first_epoch'))
        age = (f', aparcada desde hace {util.hours(time.time() - since)}'
               f'{", " + str(hold.get("renewals")) + " renovaciones" if hold.get("renewals") else ""}') if since else ''
        print(f'HOLD {e["id"]} hasta {hold.get("until") or "-"}{age}: {hold.get("reason")} | {e["title"]}')
    for e in working:
        print(f'WORKING {e["id"]} quieta {util.hours(e["idle_s"])} pero con trabajo propio en marcha'
              f'{" (pid " + str(e["pid"]) + ")" if e.get("pid") else " (subagente)"} | {e["title"]}')
    print(f'closable: {len(candidates)} to close now (F4b), {len(held)} on hold, {len(working)} quiet but working, '
          f'{len(cut)} cut (resume, never close)')
    return 0


def cmd_hold(args):
    """Owner only: park one finished session for a while, with the written rule that forbids closing it."""
    project = projects.resolve(args.dir)
    if not args.clear and not (args.reason or '').strip():
        util.die('--reason is required: the written rule or fact that forbids closing this session now', 2)
    if not args.clear and verdicts._RE_REMOTE_CONTROL.search(args.reason):
        util.die('Remote Control no es motivo para aparcar una sesión: puede estar encendido en casi todas sin que el '
                 'desarrollador lo pida, y no impide cerrarla.'
                 + (' Archívala con archive_session.' if settings.ARCHIVE_PREAUTHORISED else
                    ' Si archivarla espera autorización, regístralo en ask-queue y aparca con ese motivo.'), 2)
    if not args.clear:
        row = next((r for r in census.collect_sessions(project, False, {}) if args.target in (r['id'], r.get('cli'))), None)
        if row and verdicts.close_verdict(row) and settings.ARCHIVE_PREAUTHORISED:
            util.die(f'«{row.get("title") or args.target}» ya contestó «Sí, puedes cerrar» a /cierra-sesion: se archiva '
                     f'ahora con archive_session, no se aparca: ese veredicto es el final de su trabajo.', 2)
        if row and verdicts.close_verdict(row) and settings.QUEUED_MARK not in args.reason:
            util.die(f'«{row.get("title") or args.target}» ya contestó «Sí, puedes cerrar» a /cierra-sesion. Archivarla '
                     f'necesita la autorización escrita del desarrollador o de una regla del proyecto: registra la '
                     f'decisión con ask-queue add y apárcala con --reason "ask-queue <id>: …".', 2)
    hours_ = min(max(float(args.hours or HOLD_DEFAULT_H), 0.25), HOLD_MAX_H)
    with lock_mod.Store() as store:
        owner = store.read(project['key'])
        if not closing.acts_for(owner, args.session):
            return lock_mod.not_owner(project['key'])
        path = holds_path(project['key'])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        now = time.time()
        data = {k: v for k, v in read_holds(project['key'], now, expired=True).items()
                if (util.num(v.get('until_epoch')) or 0) > now - HOLD_HISTORY_S}
        if args.clear:
            data.pop(args.target, None)
            word = 'UNHELD'
        else:
            # a hold renewed every 12 h would keep a session open for ever; keep when it started and how often it was
            # renewed, so `closable` and the round report show it
            prev = data.get(args.target) or {}
            until = now + hours_ * 3600
            data[args.target] = {'reason': args.reason.strip(), 'by': args.session, 'until_epoch': until,
                                 'until': datetime.fromtimestamp(until).astimezone().isoformat(timespec='minutes'),
                                 'first_epoch': util.num(prev.get('first_epoch')) or now,
                                 'renewals': int(util.num(prev.get('renewals')) or 0) + 1 if prev else 0}
            word = 'HELD'
        tmp = path + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    extra = ''
    if not args.clear:
        hold = data[args.target]
        extra = f' until {hold["until"]}'
        if hold['renewals']:
            extra += (f' (renewal {hold["renewals"]}, held since {util.hours(time.time() - hold["first_epoch"])} ago: '
                      f'say why it is still not closable in the round report)')
    print(f'{word} {args.target}{extra}')
    return 0


def closable_cache_path(key):
    return os.path.join(util.home(), 'closable', key + '.json')


def write_closable_cache(project, owner_id, rows):
    """Called by `wait --owner` each round (its census is already read, with the json memo): the Stop hook only
    reads this file, so the check costs the hook nothing. Returns (candidates, resumable cut sessions); the cache holds
    both, so the hook never asks the network."""
    with lock_mod.Store() as store:
        owner = store.read(project['key'])
    candidates, _, _, cut = closable_report(project, owner, rows=list(rows))
    cuts = interrupted.resumable_cuts(cut)
    path = closable_cache_path(project['key'])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f'.{os.getpid()}.tmp'
    with open(tmp, 'w') as fh:
        json.dump({'time': time.time(), 'owner': owner_id, 'closable': candidates, 'cut': cuts}, fh)
    os.replace(tmp, path)
    return candidates, cuts


def read_closable_cache(key, local):
    """The cache `wait --owner` wrote for this lock, or None when it is missing, older than CLOSABLE_CACHE_FRESH_S or
    written by a previous owner's watcher (reclaim: this owner's own `wait` rewrites it within a round)."""
    try:
        with open(closable_cache_path(key)) as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(cache, dict) or time.time() - (util.num(cache.get('time')) or 0) > CLOSABLE_CACHE_FRESH_S:
        return None
    return cache if cache.get('owner') == local else None


def closable_block(owner, local):
    """Stop-hook reason for the oldest finished session still open, or ''. Reads the cache written by `wait`;
    re-checks holds and the app's archived flag; at most one block per CLOSABLE_BLOCK_EVERY_S per lock. Without the
    developer's written authorisation to archive (config archive_preauthorised) it asks to queue the decision and park
    the session, which ends the block: it never demands what the supervisor may not do."""
    key = owner.get('key')
    cache = read_closable_cache(key, local)
    if cache is None:
        return ''
    stamp = os.path.join(util.home(), 'closable', key + '.blocked')
    if time.time() - util.file_mtime(stamp) < CLOSABLE_BLOCK_EVERY_S:
        return ''
    holds = read_holds(key)
    pending = []
    for e in cache.get('closable') or []:
        if not isinstance(e, dict):
            continue
        if e.get('id') in holds and (not e.get('verdict') or (not settings.ARCHIVE_PREAUTHORISED
                                                               and settings.archive_queued(holds[e.get('id')]))):
            continue
        recs = list(census.read_json_files(os.path.join(os.path.dirname(census.app_glob()), glob.escape(str(e.get('id'))) + '.json')))
        if any(rec.get('isArchived') for rec in recs):
            continue
        pending.append(e)
    if not pending:
        return ''
    open(stamp, 'w').close()
    pending.sort(key=lambda e: 0 if e.get('verdict') else 1)  # a session that already said it is done goes first
    e = pending[0]
    queue = (f'registra la decisión con `~/.claude/scripts/ask-queue add --project "$PWD" --question "¿Archivo la sesión '
             f'«{e.get("title")}»?" --default "No archivarla" --why … --blocks "nada: solo su archivado"` y apárcala con '
             f'~/.claude/scripts/supervisor-lock hold --session {local} --target {e.get("id")} --reason "ask-queue <id>: '
             f'espera autorización" --hours <hasta {HOLD_MAX_H}>')
    if e.get('verdict'):
        more = (f' Quedan {len(pending) - 1} más; `~/.claude/scripts/supervisor-lock closable` las lista.'
                if len(pending) > 1 else '')
        if not settings.ARCHIVE_PREAUTHORISED:
            return (f'Antes de terminar el turno: «{e.get("title")}» ({e.get("id")}) de {owner.get("project")} ya '
                    f'contestó «Sí, puedes cerrar» a /cierra-sesion. Archivarla necesita la autorización escrita del '
                    f'desarrollador o de una regla del proyecto, y no consta: no la archives. Comprueba en disco que su '
                    f'trabajo está publicado y es recuperable, {queue}. Con eso el turno puede terminar.{more}')
        return (f'Antes de terminar el turno, archiva «{e.get("title")}» ({e.get("id")}) de {owner.get("project")}: ya '
                f'contestó «Sí, puedes cerrar» a /cierra-sesion. Archívala ahora con archive_session y anótala ARCHIVED '
                f'en Liberaciones; no le mandes otro /cierra-sesion ni la aparques. Remote Control activo no es motivo '
                f'para dejarla abierta, y su archivado no va a la tanda final: ese veredicto es el final de su trabajo, '
                f'y una sesión que lo ha dado y sigue abierta solo estorba.{more}')
    more = (f' Quedan {len(pending) - 1} más; `~/.claude/scripts/supervisor-lock closable` las lista (una por turno, '
            f'sin ráfagas).') if len(pending) > 1 else ''
    if not settings.ARCHIVE_PREAUTHORISED:
        return (f'Antes de terminar el turno, revisa una sesión terminada de {owner.get("project")}: «{e.get("title")}» '
                f'({e.get("id")}), {e.get("reason")} desde hace {util.hours(e.get("idle_s"))} y sin nada suyo en marcha. '
                f'Hazlo por F4b: comprueba en disco que lo suyo está publicado y es recuperable y mándale `/cierra-sesion` '
                f'(si no tiene proceso, haz tú esas comprobaciones en disco). Archivarla necesita la autorización escrita '
                f'del desarrollador o de una regla del proyecto: si no consta, {queue}. Si una regla escrita impide '
                f'cerrarla ahora: ~/.claude/scripts/supervisor-lock hold --session {local} --target {e.get("id")} '
                f'--reason "<regla y motivo>" --hours <hasta {HOLD_MAX_H}>.{more}')
    return (f'Antes de terminar el turno, cierra una sesión terminada de {owner.get("project")}: «{e.get("title")}» '
            f'({e.get("id")}), {e.get("reason")} desde hace {util.hours(e.get("idle_s"))} y sin nada suyo en marcha. '
            f'Toda sesión del proyecto que ha terminado se cierra y se archiva, la abriera quien la abriera: abierta solo '
            f'ocupa memoria y atención. '
            f'Hazlo por F4b: comprueba en disco que lo suyo está publicado; mándale `/cierra-sesion` (si no tiene '
            f'proceso, haz tú esas comprobaciones en disco); con «Sí, puedes cerrar», archívala con archive_session y '
            f'anótala ARCHIVED en Liberaciones. Esperar a otra pieza no es motivo para dejarla abierta: pasa lo que le '
            f'quede a Trabajo en vuelo sin dueño, con su brief, para otra sesión cuando se desbloquee, y díselo en el '
            f'mensaje de /cierra-sesion. Una línea antigua del registro («nada se archiva sin que el desarrollador lo '
            f'elija», «no se toca», un ON HOLD sin motivo vigente) no cuenta: corrígela. Solo si una regla escrita impide '
            f'cerrarla ahora: ~/.claude/scripts/supervisor-lock hold --session {local} --target {e.get("id")} '
            f'--reason "<regla y motivo>" --hours <hasta {HOLD_MAX_H}>.{more}')