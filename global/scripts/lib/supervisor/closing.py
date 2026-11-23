"""The closing session: which rows are helpers and what the closer attends."""
import glob
import os
import sys
import time
import traceback

from . import census, closable, cloud, lock as lock_mod, projects, providers, session_roles, settings, util


def is_mailbox_row(row, owner):
    box = (owner or {}).get('mailbox')
    if box and box in (row['id'], row.get('cli')):  # no mailbox and no CLI id must not match: None in (id, None)
        return True
    title = util.fold_text(row.get('title') or '')
    return any(util.fold_text(m) in title for m in session_roles.ASK_GATE_MAILBOX_TITLES)


# ---------------------------------------------------------------- the closing session
# A supervisor busy with its plan leaves finished sessions open. The closing session is a child of the supervisor,
# recorded in the lock (`beat --closer`), that verifies, closes and archives them. It has its own watcher
# (`wait-closer`); while it is alive the Stop hook gives it the finished sessions instead of the supervisor, and it may
# hold sessions and archive cloud sessions like the owner. It never asks the developer and never decides scope.
CLOSER_TITLES = settings.CLOSER_TITLES
CLOSER_POLL_S = 60
CLOSER_REANNOUNCE_S = 30 * 60
CLOSER_BLOCK_EVERY_S = 300
CLOSER_ALIVE_S = 45 * 60    # a closer whose record moved this recently, or with a live process, is attending


def is_closer_row(row, owner):
    box = (owner or {}).get('closer')
    if box and box in (row['id'], row.get('cli')):
        return True
    title = util.fold_text(row.get('title') or '')
    return any(m in title for m in CLOSER_TITLES)


def is_helper_row(row, owner):
    """The supervisor's fixed children, which are never closed nor counted as work: questions and closing sessions."""
    return is_mailbox_row(row, owner) or is_closer_row(row, owner)


def acts_for(owner, session):
    """True when `session` may act on the lock's finished sessions: its owner or its closing session."""
    return bool(owner) and session in (owner.get('session_id'), owner.get('closer'))


def closer_attending(owner):
    """True when the lock has a closing session with a live process: the finished sessions are hers, not the owner's."""
    closer = (owner or {}).get('closer')
    if not closer:
        return False
    try:
        for row in census.collect_sessions(projects.resolve(owner.get('checkout')), False, {}):
            if closer in (row['id'], row.get('cli')):
                return bool(row.get('live'))
    except Exception:
        util.hook_log('hook-errors.log', 'closer-attending\n' + traceback.format_exc().rstrip())
    return False


def closer_lock_of(session, locks):
    """(local id, lock) when the CLI session `session` is the closing session of one of `locks`, else (None, None)."""
    closers = {lock.get('closer'): lock for lock in locks.values() if lock.get('closer')}
    if not closers:
        return None, None
    for rec in census.read_json_files(os.path.join(census.cli_dir(), '*.json')):
        if rec.get('sessionId') == session and rec.get('hostSessionId') in closers:
            return rec['hostSessionId'], closers[rec['hostSessionId']]
    app_base = os.path.dirname(census.app_glob())
    for closer_id, lock in closers.items():
        for rec in census.read_json_files(os.path.join(app_base, glob.escape(closer_id) + '.json')):
            if rec.get('cliSessionId') == session:
                return closer_id, lock
    return None, None


def closer_pending(project, owner):
    """Finished sessions the closing session must deal with now: [(pair, line)] from `closable_report`."""
    candidates, _, _, _ = closable.closable_report(project, owner)
    return [(f'{e["id"]}:{e["reason"]}', f'CLOSABLE {e["id"]} {e["reason"]} {util.hours(e["idle_s"])} | {e["title"]}')
            for e in candidates]


def cmd_wait_closer(args):
    """The closing session's watcher: exits with the finished sessions of the project (each announced once every
    CLOSER_REANNOUNCE_S while still open), or TIMEOUT. Sleeps while the project is paused."""
    project = projects.resolve(args.dir)
    deadline = time.monotonic() + args.timeout
    while True:
        with lock_mod.Store() as store:
            owner = store.read(project['key'])
        if owner is None:
            print('NO LOCK: nadie supervisa el proyecto; no hay nada que cerrar por encargo')
            return 0
        if owner.get('closer') != args.session:
            print(f'NOT CLOSER {project["key"]}', file=sys.stderr)
            return 5
        if not providers.pause_of(project.get('checkout')):
            try:
                lines = cloud.announce_once(project['key'], 'closer', closer_pending(project, owner), CLOSER_REANNOUNCE_S)
            except Exception:
                util.hook_log('wait-errors.log', traceback.format_exc().rstrip())
                lines = []
            if lines:
                print('\n'.join(lines))
                return 0
        if time.monotonic() >= deadline:
            print(f'TIMEOUT {int(args.timeout)}s')
            return 0
        time.sleep(max(1.0, min(args.interval, deadline - time.monotonic() + 0.01)))


def closer_stop(closer, owner, payload):
    """Stop-hook reason for the closing session of a live lock, or ''."""
    if providers.pause_of(owner.get('checkout')) or lock_mod.is_stale(owner):
        return ''
    tasks = payload.get('background_tasks')
    armed = not isinstance(tasks, list)
    for task in tasks if isinstance(tasks, list) else []:
        if isinstance(task, dict) and str(task.get('status') or 'running').lower() in ('running', 'pending') and any(
                'supervisor-lock wait-closer' in str(task.get(f) or '') for f in ('command', 'description')):
            armed = True
    if not armed:
        return (f'Eres la sesión de cierre de {owner.get("project")} y vas a terminar el turno sin vigilante: nada te '
                f'despertaría cuando una sesión termine. Arma en segundo plano (run_in_background: true): '
                f'~/.claude/scripts/supervisor-lock wait-closer --session {closer} --timeout 14400.')
    stamp = os.path.join(util.home(), 'closable', (owner.get('key') or 'lock') + '.closer-blocked')
    if time.time() - util.file_mtime(stamp) < CLOSER_BLOCK_EVERY_S:
        return ''
    pending = closer_pending(projects.resolve(owner.get('checkout')), owner)
    if not pending:
        return ''
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    open(stamp, 'w').close()
    listed = '; '.join(line for _, line in pending[:5])
    archive = ('archive_session' if settings.ARCHIVE_PREAUTHORISED else
               'el archivado solo con autorización escrita del desarrollador o de una regla del proyecto (si no consta, '
               'la decisión va a ask-queue y la sesión se aparca con hold --reason "ask-queue <id>")')
    more = f' y {len(pending) - 5} más' if len(pending) > 5 else ''
    return (f'Antes de terminar el turno: {owner.get("project")} tiene {len(pending)} sesión(es) terminadas sin cerrar: '
            f'{listed}{more}. Es tu encargo: para cada una, las comprobaciones en disco, `/cierra-sesion`, la '
            f'comprobación de después y {archive}, como dice «La sesión de cierre» de '
            f'~/.claude/skills/supervisa-sesiones/reference/f4b-cierre-de-sesiones.md. La que no pase la verificación no '
            f'se archiva: le dices a la supervisora en una línea qué le queda. Una por una, sin ráfagas.')
