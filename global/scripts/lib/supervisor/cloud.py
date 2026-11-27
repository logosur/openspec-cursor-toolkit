"""Cloud sessions of a project, through the optional provider."""
import fcntl
import glob
import json
import os
import re
import sys
import time

from . import closable, lock as lock_mod, projects, providers, settings, util


CLOUD_CACHE_TTL_S = 300        # one API listing per 5 min for every supervisor together
CLOUD_FAIL_TTL_S = 60          # a failed listing is retried after a minute, not by six waits at once
CLOUD_HUNG_S = 30 * 60         # running without an event this long: hung
CLOUD_CHECK_AFTER_S = 2 * 3600 # stopped this long: its reason to stay open must be checked (same as a local one, F4b)
CLOUD_AWAY_S = settings.PRESENCE_MIN * 60  # activity this recent: the developer may be driving it (like --away-after)
CLOUD_REANNOUNCE_S = 6 * 3600  # an item still unhandled is announced again
CLOUD_ACTIONABLE = ('HUNG', 'WAITING', 'CHECK')
CLOUD_POLL_S = 300
CLOUD_BLOCK_EVERY_S = 20 * 60
UNAVAILABLE = 'el proveedor de sesiones en la nube (cloud-tests) no está instalado'


def cloud_dir():
    return os.path.join(util.home(), 'cloud')


def slim_cloud_session(s):
    cfg = s.get('config') or {}
    meta = s.get('external_metadata') or {}
    repos, branches = set(), []
    ct = providers.cloud_tests_module()
    for src in cfg.get('sources') or []:
        slug = ct.github_slug(str(src.get('url') or ''))
        if slug:
            repos.add(slug.lower())
    for out in cfg.get('outcomes') or []:
        info = out.get('git_info') or {}
        if info.get('repo'):
            repos.add(str(info['repo']).lower())
        branches += [b for b in info.get('branches') or [] if isinstance(b, str)]
    branches += [b for b in (meta.get('current_branches') or {}).values() if isinstance(b, str)]
    summary = meta.get('post_turn_summary') or {}
    return {'id': s.get('id'), 'title': s.get('title') or '', 'kind': s.get('environment_kind'),
            'status': s.get('status'), 'worker': s.get('worker_status'), 'bucket': s.get('status_bucket'),
            'last_event_at': s.get('last_event_at') or s.get('updated_at'), 'created_at': s.get('created_at'),
            'repos': sorted(repos), 'branches': list(dict.fromkeys(branches)), 'origin': cfg.get('origin'),
            'needs_action': str(summary.get('needs_action') or '')[:300],
            'detail': str(s.get('status_line') or summary.get('status_detail') or '')[:300]}


def cloud_active(max_age=CLOUD_CACHE_TTL_S):
    """(sessions, None) from a cache shared by every supervisor, refreshed under flock when older than `max_age`, or
    (None, reason) when the API cannot be read or the provider is absent. Never an empty list on failure: unknown is not
    none."""
    if providers.cloud_tests_module() is None:
        return None, UNAVAILABLE
    path = os.path.join(cloud_dir(), 'active.json')

    def fresh(data):
        if not isinstance(data, dict):
            return False
        ttl = max_age if data.get('ok') else CLOUD_FAIL_TTL_S
        return time.time() - (util.num(data.get('fetched')) or 0) < ttl

    data = util.read_json(path)
    if not fresh(data):
        os.makedirs(cloud_dir(), exist_ok=True)
        with open(path + '.lock', 'a+') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            data = util.read_json(path)
            if not fresh(data):
                try:
                    rows = [slim_cloud_session(s) for s in providers.cloud_tests_module().active_cloud_sessions()]
                    data = {'fetched': time.time(), 'ok': True, 'sessions': rows}
                except Exception as err:  # the API is unavailable, or anything else: reported, never "none"
                    data = {'fetched': time.time(), 'ok': False, 'error': str(err)[:200] or type(err).__name__}
                util.write_json_atomic(path, data)
    if data.get('ok'):
        return data.get('sessions') or [], None
    return None, data.get('error') or 'unknown error'


def forget_cloud_session(session_id):
    """Drop one session from the shared cache after archiving it, so the next census does not list it again."""
    if providers.cloud_tests_module() is None:
        return
    path = os.path.join(cloud_dir(), 'active.json')
    with open(path + '.lock', 'a+') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = util.read_json(path)
        if isinstance(data, dict) and data.get('ok'):
            key = providers.cloud_tests_module().sid_key(session_id)
            data['sessions'] = [s for s in data.get('sessions') or []
                                if providers.cloud_tests_module().sid_key(s.get('id')) != key]
            util.write_json_atomic(path, data)


def rename_cloud_session(session_id, title):
    """Record a new title in the shared cache after renaming a session, so the next census does not redo it."""
    if providers.cloud_tests_module() is None:
        return
    path = os.path.join(cloud_dir(), 'active.json')
    with open(path + '.lock', 'a+') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = util.read_json(path)
        if isinstance(data, dict) and data.get('ok'):
            key = providers.cloud_tests_module().sid_key(session_id)
            for row in data.get('sessions') or []:
                if providers.cloud_tests_module().sid_key(row.get('id')) == key:
                    row['title'] = title
            util.write_json_atomic(path, data)


def project_slugs(project):
    """GitHub owner/repo (lower case) of the project's repositories: the checkout, and in a workspace its nested repos."""
    ct = providers.cloud_tests_module()
    dirs = [project['checkout']]
    if project.get('kind') == 'workspace':
        dirs += sorted(os.path.dirname(p) for p in glob.glob(os.path.join(glob.escape(project['checkout']), '*', '.git')))
    out = set()
    for d in dirs:
        slug = ct.github_slug(projects.git(['remote', 'get-url', 'origin'], d) or '')
        if slug:
            out.add(slug.lower())
    return out


def cloud_runner_ids(key):
    """(proven runner ids, ids a sent run waits on) from the project's cloud-tests ledger: cloud-tests owns those."""
    ct = providers.cloud_tests_module()
    data = util.read_json(os.path.join(ct.STATE_DIR, f'{key}.json'), {}) or {}
    runs = data.get('runs') if isinstance(data.get('runs'), dict) else {}
    ids = {ct.sid_key((data.get('runner') or {}).get('session'))}
    ids |= {ct.sid_key(x.get('session')) for x in data.get('retired') or [] if isinstance(x, dict)}
    ids |= {ct.sid_key(e.get('session')) for e in runs.values() if isinstance(e, dict) and e.get('session')}
    busy = {ct.sid_key(e.get('session')) for e in runs.values()
            if isinstance(e, dict) and e.get('state') == 'sent' and e.get('session')}
    ids.discard('')
    return ids, busy


def cloud_verdict(s, runners, held, now):
    ct = providers.cloud_tests_module()
    k = ct.sid_key(s.get('id'))
    age = now - (ct.iso_epoch(s.get('last_event_at')) or now)
    if k in runners:
        return 'RUNNER', age
    if k in held:
        return 'HOLD', age
    if s.get('worker') == 'running' or s.get('bucket') == 'working':
        return ('WORKING' if age < CLOUD_HUNG_S else 'HUNG'), age
    if age < CLOUD_AWAY_S:
        return 'RECENT', age  # the developer may be driving it right now: a question there is for them
    if s.get('bucket') in ('blocked', 'requires_action') or s.get('needs_action'):
        return 'WAITING', age
    return ('CHECK' if age >= CLOUD_CHECK_AFTER_S else 'RECENT'), age


def cloud_rows(project, now=None, fresh=False):
    """(rows, None) for the active anthropic_cloud sessions of the project's repositories, each with its verdict, or
    (None, reason) when the API cannot be read. Remote Control mirrors (environment_kind bridge) are local sessions:
    the local census has them."""
    now = time.time() if now is None else now
    if providers.cloud_tests_module() is None:
        return None, UNAVAILABLE
    slugs = project_slugs(project)
    if not slugs:
        return [], None  # no GitHub remote: no cloud session can be the project's
    sessions, err = cloud_active(0 if fresh else CLOUD_CACHE_TTL_S)
    if sessions is None:
        return None, err
    ct = providers.cloud_tests_module()
    runners, busy = cloud_runner_ids(project['key'])
    holds = closable.read_holds(project['key'], now)
    held = {ct.sid_key(t): v for t, v in holds.items()}
    rows = []
    for s in sessions:
        if s.get('kind') != 'anthropic_cloud' or s.get('status') != 'active' or not set(s.get('repos') or []) & slugs:
            continue
        verdict, age = cloud_verdict(s, runners, held, now)
        k = ct.sid_key(s.get('id'))
        rows.append(dict(s, verdict=verdict, age_s=int(age), busy=k in busy,
                         hold=(held.get(k) or {}).get('reason')))
    order = {v: i for i, v in enumerate(('HUNG', 'WAITING', 'CHECK', 'WORKING', 'RECENT', 'HOLD', 'RUNNER'))}
    return sorted(rows, key=lambda r: (order.get(r['verdict'], 9), -r['age_s'])), None


CLOUD_TODO = {
    'HUNG': 'trabaja sin dar señal: mándale un mensaje (cloud-send); si sigue sin avanzar, recoge su rama y archívala',
    'WAITING': 'espera una respuesta o un permiso: contéstale tú (cloud-send) como a una sesión local, o archívala si '
               'lo que pedía ya no hace falta',
    'CHECK': 'parada: comprueba su rama (¿subida, integrada?) y si el proyecto la necesita; si no, archívala '
             '(cloud-archive); si su trabajo falta por integrar, intégralo si las reglas del proyecto lo autorizan, o déjalo '
             'anotado, y archívala',
    'WORKING': 'trabajando', 'RECENT': f'actividad reciente (puede llevarla el desarrollador): se revisa cuando lleve {CLOUD_AWAY_S // 60} min quieta o 2 h '
              'parada',
    'HOLD': 'aparcada con motivo', 'RUNNER': 'corredor de cloud-tests: lo archiva solo `cloud-tests sweep`',
}


def cloud_line(r):
    parts = [f'CLOUD {r["id"]}', f'verdict={r["verdict"]}', f'worker={r.get("worker") or "-"}',
             f'bucket={r.get("bucket") or "-"}', f'last={util.span(r["age_s"])}']
    if r.get('branches'):
        parts.append('branch=' + ','.join(r['branches'][:3]))
    if r.get('origin'):
        parts.append(f'origin={r["origin"]}')
    if len(r.get('repos') or []) > 1:
        parts.append('repos=' + ','.join(r['repos']) + ' (también de otro repositorio: compruébalo en los dos)')
    parts.append(f'«{r.get("title") or "-"}»')
    if r.get('needs_action'):
        parts.append(f'needs={r["needs_action"][:160]}')
    if r.get('detail'):
        parts.append(f'detail={r["detail"][:160]}')
    if r.get('hold'):
        parts.append(f'hold={r["hold"][:120]}')
    return ' | '.join(parts)


def cmd_cloud(args):
    project = projects.resolve(args.dir)
    rows, err = cloud_rows(project)
    if rows is None:
        if args.json:
            print(json.dumps({'ok': False, 'error': err, 'available': err != UNAVAILABLE}, ensure_ascii=False))
        elif err == UNAVAILABLE:
            print(f'CLOUD-UNAVAILABLE {err}: las sesiones en la nube de {project["name"]} no se pueden listar ni tocar '
                  f'desde aquí; no lo des por vacío.')
        else:
            print(f'CLOUD-UNKNOWN {err}: no se sabe qué sesiones de la nube tiene {project["name"]}; no lo des por '
                  f'vacío. Se reintenta solo en 1 min.')
        return 3
    write_cloud_rows(project['key'], rows)
    if args.json:
        print(json.dumps({'ok': True, 'rows': rows}, ensure_ascii=False, indent=1))
        return 0
    for r in rows:
        print(cloud_line(r))
        print(f'      → {CLOUD_TODO.get(r["verdict"], "")}')
    if not settings.ARCHIVE_PREAUTHORISED and any('archívala' in CLOUD_TODO.get(r['verdict'], '') for r in rows):
        print('      (archivar necesita la autorización escrita del desarrollador o de una regla del proyecto: si no '
              'consta, la decisión va a ask-queue y la sesión se aparca con hold)')
    count = lambda *vs: sum(1 for r in rows if r['verdict'] in vs)
    print(f'cloud: {count(*CLOUD_ACTIONABLE)} to act on now (HUNG/WAITING/CHECK), {count("WORKING")} working, '
          f'{count("RECENT")} recent, {count("HOLD")} on hold, {count("RUNNER")} cloud-tests runners')
    return 0


def write_cloud_rows(key, rows):
    """Per-lock snapshot for the Stop hook and the unattended plan (no network there)."""
    try:
        util.write_json_atomic(os.path.join(cloud_dir(), key + '.rows.json'), {'at': time.time(), 'rows': rows})
    except OSError:
        pass


def cloud_owned_target(args):
    """(project, row) when --session owns the lock and --target is an active cloud session of the project; dies else."""
    project = projects.resolve(args.dir)
    owner = lock_mod.Store().read(project['key'])
    if owner is None or owner.get('session_id') != args.session:
        sys.exit(lock_mod.not_owner(project['key']))
    rows, err = cloud_rows(project, fresh=True)  # act on its state now, not on the 5-min cache
    if rows is None:
        util.die(f'{"CLOUD-UNAVAILABLE" if err == UNAVAILABLE else "CLOUD-UNKNOWN"} {err}: no se puede comprobar que '
                 f'la sesión sea de {project["name"]}', 3)
    ct = providers.cloud_tests_module()
    row = next((r for r in rows if ct.sid_key(r['id']) == ct.sid_key(args.target)), None)
    if row is None:
        util.die(f'{args.target} no es una sesión activa en la nube de {project["name"]} (o ya está archivada): '
            f'`supervisor-lock cloud` lista las suyas', 2)
    if row['age_s'] < CLOUD_AWAY_S and row['verdict'] != 'RUNNER' and not getattr(args, 'force_working', False):
        util.die(f'«{row.get("title")}» tuvo actividad hace {util.span(row["age_s"])}: puede llevarla el desarrollador ahora '
            f'(desde el móvil o claude.ai). Se espera a que pasen {CLOUD_AWAY_S // 60} min sin actividad, como con una '
            f'sesión local que lleva el desarrollador', 2)
    return project, row


def cloud_log(line):
    util.hook_log('cloud-actions.log', line)


def cmd_cloud_archive(args):
    project, row = cloud_owned_target(args)
    reason = (args.reason or '').strip()
    if not reason:
        util.die('--reason es obligatorio: qué comprobaste (su rama subida o integrada, que el proyecto ya no la necesita)', 2)
    if row['verdict'] == 'RUNNER' and row.get('busy'):
        util.die('es el corredor de tests con un run en vuelo: no se archiva (lo archiva `cloud-tests sweep` cuando acaba)', 2)
    if row['verdict'] == 'WORKING' and not args.force_working:
        util.die('está trabajando ahora: mándale un mensaje (cloud-send) o espera a que pare; con un motivo escrito para '
            'cortarla, repite con --force-working', 2)
    code, _ = providers.cloud_tests_module().api_call('POST', f'/v1/code/sessions/{row["id"]}/archive', {})
    if code not in (200, 204, 404, 409):
        cloud_log(f'ARCHIVE-FAILED {project["key"]} {row["id"]} http={code}')
        print(f'FAILED {row["id"]} HTTP {code}')
        return 1
    forget_cloud_session(row['id'])
    cloud_log(f'ARCHIVED {project["key"]} {row["id"]} by={args.session} verdict={row["verdict"]} '
              f'title={row.get("title")!r} reason={reason!r}')
    print(f'ARCHIVED {row["id"]} «{row.get("title")}» (el desarrollador puede deshacerlo desde la app: archivar no '
          f'borra)')
    return 0


def cmd_cloud_send(args):
    project, row = cloud_owned_target(args)
    text = (args.text or '').strip()
    if not text:
        util.die('--text es obligatorio', 2)

    class _Proj:
        top = project['checkout']

    ct = providers.cloud_tests_module()
    ok, out = ct.send_followup(_Proj, 'session_' + ct.sid_key(row['id']), text)
    cloud_log(f'SEND {"OK" if ok else "FAILED"} {project["key"]} {row["id"]} by={args.session} text={text[:200]!r}')
    if ok:
        print(f'SENT {row["id"]} «{row.get("title")}»')
        return 0
    tail = ' | '.join(l.strip() for l in out.splitlines() if l.strip() and not l.startswith('Script '))[-300:]
    print(f'FAILED {row["id"]}: {tail or "sin salida"}')
    return 1


def announce_once(key, name, items, reannounce_s, now=None):
    """Lines for the items not announced yet, or announced more than `reannounce_s` ago and still there. `items` is
    [(pair, line)]; the pairs live in <home>/announced/<key>.<name>.json (48 h). Unlike a quiet level, an item already
    true when the wait starts is announced, so a lingering session is never ignored."""
    now = time.time() if now is None else now
    path = os.path.join(util.home(), 'announced', f'{key}.{name}.json')
    lines = []
    with lock_mod.Store():
        data = util.read_json(path, {})
        data = {k: v for k, v in (data if isinstance(data, dict) else {}).items()
                if util.num(v) is not None and now - v < closable.HOLD_HISTORY_S}
        changed = False
        for pair, line in items:
            if pair not in data or now - data[pair] >= reannounce_s:
                data[pair] = now
                lines.append(line)
                changed = True
        if changed:
            util.write_json_atomic(path, data)
    return lines


def cloud_events(project, now=None):
    """`CLOUD <id> <verdict> <age> «title»` for the cloud sessions of the project to act on, once per (id, verdict,
    last event) and again every CLOUD_REANNOUNCE_S while they stay so. Writes the snapshot the Stop hook reads."""
    rows, err = cloud_rows(project, now)
    if rows is None:
        return []
    write_cloud_rows(project['key'], rows)
    items = [(f'{r["id"]}@{r["verdict"]}@{r.get("last_event_at")}',
              f'CLOUD {r["id"]} {r["verdict"]} {util.span(r["age_s"])} «{(r.get("title") or "-")[:60]}»')
             for r in rows if r['verdict'] in CLOUD_ACTIONABLE]
    return announce_once(project['key'], 'cloud', items, CLOUD_REANNOUNCE_S, now)


def cloud_block(owner, local):
    """Stop-hook reason while cloud sessions of the project wait for the supervisor (HUNG, WAITING, CHECK without a
    hold), from the snapshot `wait` and `cloud` write; at most once per CLOUD_BLOCK_EVERY_S per lock."""
    key = owner.get('key')
    snap = util.read_json(os.path.join(cloud_dir(), f'{key}.rows.json'))
    if not isinstance(snap, dict) or time.time() - (util.num(snap.get('at')) or 0) > 2 * 3600:
        return ''
    stamp = os.path.join(cloud_dir(), key + '.blocked')
    if time.time() - util.file_mtime(stamp) < CLOUD_BLOCK_EVERY_S:
        return ''
    ct = providers.cloud_tests_module()
    if ct is None:
        return ''
    held = {ct.sid_key(t) for t in closable.read_holds(key)}
    archived = archived_cloud_ids()
    pending = [r for r in snap.get('rows') or [] if isinstance(r, dict) and r.get('verdict') in CLOUD_ACTIONABLE
               and ct.sid_key(r.get('id')) not in held and ct.sid_key(r.get('id')) not in archived]
    if not pending:
        return ''
    open(stamp, 'w').close()
    listed = '; '.join(f'«{r.get("title")}» ({r.get("id")}, {r.get("verdict")}, {util.span(r.get("age_s"))})'
                       for r in pending[:6])
    more = f' y {len(pending) - 6} más' if len(pending) > 6 else ''
    return (f'Antes de terminar el turno: {owner.get("project")} tiene {len(pending)} sesión(es) en la nube que nadie ha '
            f'comprobado: {listed}{more}. Una sesión que nadie comprueba se queda colgada o abierta sin motivo, y la '
            f'supervisora la atiende sin esperar al desarrollador: por qué sigue ahí, si se ha colgado y si el proyecto '
            f'la necesita. Con `~/.claude/scripts/supervisor-lock cloud` ves cada una con su rama y lo que toca. Para cada '
            f'una: CHECK → mira su rama en origin (`git fetch` y `git log main..origin/<rama>`); si no aporta nada '
            f'pendiente o ya está integrada, `supervisor-lock cloud-archive --session {local} --target <id> --reason '
            f'"<lo comprobado>"`; si trae trabajo sin integrar, intégralo (F7) si las reglas del proyecto lo autorizan, o anótalo en Trabajo en '
            f'vuelo, y archívala. '
            f'WAITING → contéstale tú con `supervisor-lock cloud-send --session {local} --target <id> --text "…"` (F5) o '
            f'archívala si lo que pedía ya no hace falta. HUNG → mensaje con cloud-send; si no avanza en 10 min, recoge su '
            f'rama y archívala. Solo si una regla escrita obliga a dejarla abierta: `supervisor-lock hold --session '
            f'{local} --target <id> --reason "<regla>"`. Anota cada una en el registro.'
            + ('' if settings.ARCHIVE_PREAUTHORISED else
               ' Archivar necesita la autorización escrita del desarrollador o de una regla del proyecto: si no consta, '
               'registra la decisión en ask-queue y apárcala con hold --reason "ask-queue <id>: espera autorización".'))


def archived_cloud_ids():
    """Session keys archived through cloud-archive in the last 2 days (the Stop hook must not nag about them)."""
    out = set()
    ct = providers.cloud_tests_module()
    if ct is None:
        return out
    try:
        with open(os.path.join(util.home(), 'cloud-actions.log')) as fh:
            for line in fh.readlines()[-500:]:
                m = re.search(r'\bARCHIVED \S+ (\S+)', line)
                if m:
                    out.add(ct.sid_key(m.group(1)))
    except OSError:
        pass
    return out


def refresh_cloud_snapshot(owner):
    """Write the lock's cloud snapshot from the shared cache (one API call per 5 min for everybody), so the Stop hook
    and the unattended plan do not depend on the supervisor's own watcher having been re-armed with this code."""
    if not owner.get('checkout') or not os.path.isdir(owner['checkout']):
        return
    try:
        project = projects.resolve(owner['checkout'])
        rows, _ = cloud_rows(project)
        if rows is not None:
            write_cloud_rows(project['key'], rows)
    except BaseException as err:  # resolve() exits on a vanished checkout: never take the caller down
        if isinstance(err, KeyboardInterrupt):
            raise
        util.hook_log('wait-errors.log', f'refresh_cloud_snapshot {owner.get("key")}: {err!r}')
