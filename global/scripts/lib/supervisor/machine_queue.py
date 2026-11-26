"""Jobs of a project that wait in, or hold, the machine queue."""
import os
import time

from . import census, cloud, projects, providers, settings, util


QUEUED_AFTER_S = 20 * 60       # a job of the project waiting this long in the machine queue
QUEUED_REANNOUNCE_S = settings.QUEUED_REANNOUNCE_MIN * 60   # config `queued_reannounce_min`
SLOTHELD_AFTER_S = 60 * 60     # a job of the project holding a slot this long while others queue
SLOTHELD_REANNOUNCE_S = settings.SLOTHELD_REANNOUNCE_MIN * 60   # config `slotheld_reannounce_min`
HEAVY_POLL_S = 60


def proc_cwd(pid):
    try:
        return os.readlink(f'/proc/{int(pid)}/cwd')
    except (OSError, ValueError, TypeError):
        return None


def heavy_job_items(project, state, now=None):
    """Queue and slot facts of the project: ([queued], [long holders], text of the slots) from heavy-job's JSON."""
    now = time.time() if now is None else now
    match = projects.project_dir_matcher(project)
    queued, holders, slots_text, waiting = [], [], [], []
    for pool in (state, state.get('light') or {}):
        for q in pool.get('queue') or []:
            waited = now - (util.parse_ts(q.get('queued')) or now)
            waiting.append((q, waited))
            if match(proc_cwd(q.get('pid'))):
                queued.append((q, waited))
        for j in pool.get('jobs') or []:
            held = now - (util.num(j.get('started_ts')) or util.parse_ts(j.get('started')) or now)
            alive = census.pid_alive(j.get('pid'))
            slots_text.append(f'hueco {",".join(str(s) for s in j.get("shown_slots") or j.get("slots") or [])} '
                              f'«{(j.get("label") or "-")[:60]}» de {j.get("project") or "?"} desde hace {util.span(held)}'
                              f'{"" if alive else " (SU PROCESO NO EXISTE)"}')
            if match(j.get('cwd')):
                holders.append((j, held))
    return queued, holders, slots_text, waiting


def project_job_queued(project, state=None):
    """True when a job of the project waits in the machine queue (heavy-job's JSON). Fails safe: without heavy-job, or
    when its answer cannot be read, False."""
    state = providers.heavy_job_state() if state is None else state
    if not isinstance(state, dict):
        return False
    try:
        return bool(heavy_job_items(project, state)[0])
    except Exception:
        return False


def heavy_events(project, state, now=None):
    """`QUEUED` for a job of the project waiting > QUEUED_AFTER_S, with who holds the slots; `SLOTHELD` for a job of
    the project holding a slot > SLOTHELD_AFTER_S while others queue. Persisted once-per-item announcements."""
    if not state:
        return []
    now = time.time() if now is None else now
    queued, holders, slots_text, waiting = heavy_job_items(project, state, now)
    slots = '; '.join(slots_text) or 'ninguno ocupado'
    items = []
    for q, waited in queued:
        if waited >= QUEUED_AFTER_S:
            items.append((f'Q{q.get("pid")}@{q.get("queued")}',
                          f'QUEUED pid={q.get("pid")} {util.span(waited)} en cola, puesto {q.get("position")} '
                          f'«{(q.get("label") or "-")[:60]}» — huecos: {slots}'))
    others = [(q, w) for q, w in waiting if not any(q is mine for mine, _ in queued)]
    for j, held in holders:
        if held >= SLOTHELD_AFTER_S and waiting:
            names = '; '.join(f'«{(q.get("label") or "-")[:40]}» de {q.get("project") or "?"} ({util.span(w)})'
                              for q, w in (others or waiting)[:4])
            items.append((f'S{j.get("pid")}@{j.get("started")}',
                          f'SLOTHELD pid={j.get("pid")} {util.span(held)} con hueco «{(j.get("label") or "-")[:60]}» '
                          f'mientras esperan {len(waiting)}: {names}'))
    reannounce = {'Q': QUEUED_REANNOUNCE_S, 'S': SLOTHELD_REANNOUNCE_S}
    lines = []
    for prefix in ('Q', 'S'):
        lines += cloud.announce_once(project['key'], 'heavy-' + prefix, [i for i in items if i[0].startswith(prefix)],
                               reannounce[prefix], now)
    return lines
