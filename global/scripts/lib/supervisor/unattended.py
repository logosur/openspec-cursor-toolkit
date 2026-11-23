"""Projects whose sessions or work nobody supervises."""
import glob
import os
import time

from . import closable, cloud, lock as lock_mod, providers, revival, util


UNATTENDED_AFTER_S = 45 * 60   # an item still unhandled this long after it was first seen wakes the supervisor
UNATTENDED_RETRY_S = 60 * 60
UNATTENDED_MAX_ATTEMPTS = 3  # wakes 1 h apart; after them it never gives up, it insists every UNATTENDED_SLOW_RETRY_S
UNATTENDED_SLOW_RETRY_S = 3 * 60 * 60


def unattended_items(key, owner, now=None):
    """What of the project has waited on its supervisor: cloud sessions to act on (snapshot), finished local sessions
    (closable cache), jobs queued too long. [(item id, text)]."""
    now = time.time() if now is None else now
    out = []
    ct = providers.cloud_tests_module()
    holds = closable.read_holds(key, now)
    held = {ct.sid_key(t) for t in holds} if ct else set(holds)
    archived = cloud.archived_cloud_ids()
    snap = util.read_json(os.path.join(cloud.cloud_dir(), f'{key}.rows.json')) if ct else None
    if isinstance(snap, dict) and now - (util.num(snap.get('at')) or 0) < 2 * 3600:
        for r in snap.get('rows') or []:
            k = ct.sid_key((r or {}).get('id'))
            if r.get('verdict') in cloud.CLOUD_ACTIONABLE and k not in held and k not in archived:
                out.append((f'cloud:{k}', f'la sesión de la nube «{r.get("title")}» ({r.get("id")}, '
                                          f'{r.get("verdict")}, parada desde hace {util.span(r.get("age_s"))})'))
    cache = util.read_json(closable.closable_cache_path(key))
    if (isinstance(cache, dict) and cache.get('owner') == owner.get('session_id')
            and now - (util.num(cache.get('time')) or 0) <= closable.CLOSABLE_CACHE_FRESH_S):
        for e in cache.get('closable') or []:
            if isinstance(e, dict) and e.get('id') and (e.get('verdict') or e.get('id') not in holds):
                out.append((f'local:{e["id"]}', f'la sesión «{e.get("title")}» ({e["id"]}), terminada y sin cerrar'))
    return out


def unattended_supervisors(now=None):
    """[(key, owner, items)] of live supervisors (process alive, project not paused) with items unhandled for more
    than UNATTENDED_AFTER_S since first seen (<home>/unattended.json keeps when each was first seen)."""
    now = time.time() if now is None else now
    live = revival.live_hosts()
    store = lock_mod.Store()
    path = os.path.join(util.home(), 'unattended.json')
    seen = util.read_json(path, {}) or {}
    out, fresh = [], {}
    for p in sorted(glob.glob(os.path.join(util.home(), 'locks', '*.json'))):
        key = os.path.basename(p)[:-5]
        owner = store.read(key)
        if not owner or owner.get('session_id') not in live or providers.pause_of(owner.get('checkout')):
            continue
        cloud.refresh_cloud_snapshot(owner)
        items = unattended_items(key, owner, now)
        prev = seen.get(key) if isinstance(seen.get(key), dict) else {}
        fresh[key] = {i: util.num(prev.get(i)) or now for i, _ in items}
        due = [(i, t) for i, t in items if now - fresh[key][i] >= UNATTENDED_AFTER_S]
        if due:
            out.append((key, owner, due))
    util.write_json_atomic(path, fresh)
    return out


def unattended_text(owner, items, attempt=1):
    listed = '\n'.join(f'- {t}' for _, t in items[:8])
    more = f'\n- y {len(items) - 8} más' if len(items) > 8 else ''
    ignored = (f' Es el aviso n.º {attempt}: los {attempt - 1} anteriores no los atendiste, y no dejarán de llegar '
               'mientras quede algo de esta lista.' if attempt > 1 else '')
    return (f'{revival.REVIVE_MARKER}{ignored} No es que tu proceso muriera: estás viva, pero llevas más de '
            f'{UNATTENDED_AFTER_S // 60} min sin atender esto de {owner.get("project")}:\n{listed}{more}\n\n'
            'Te despierta la tarea programada de reanimación, no el desarrollador. Una sesión que nadie comprueba se '
            'queda colgada o abierta sin motivo, y la supervisora la atiende sin esperar a nadie. Ahora, en este turno: `supervisor-lock cloud` y `supervisor-lock closable`; para cada una, comprueba '
            'por qué sigue ahí y actúa (archivarla, contestarle, recoger su trabajo o aparcarla con `hold` y la regla '
            'escrita que lo obliga). Anótalo en el registro y vuelve a armar el vigilante.')
