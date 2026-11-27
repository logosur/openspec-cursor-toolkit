"""Session titles: the name each session of a supervision should carry, and the Remote Control copies that follow it.

A supervisor, its questions session and its closing session have a title fixed by the config piece `supervision`
(`supervisor_session_title`, `questions_session_title`, `closer_session_title`). This module compares them with the
titles of the app's session records and says which session has to be renamed (`RENAME …`): a script never edits the
app's records, the session renames itself with the app tool. It also says which helper sits in the wrong place of the
app's sidebar: the closing session that is not a child of the supervisor (`ADOPT …`) and the questions session that
hangs from any session (`DETACH …`), whose dialogs would show in its parent's window.

A Remote Control copy of a local session (an environment of kind `bridge` in the cloud listing) keeps the title it had
when Remote Control was switched on; it does not follow a later rename. `sync` renames each active copy through the
sessions API (the newest copy gets the local title, older copies of the same session the local title plus
`remote_previous_suffix`), and rewrites the title of a lock that carries another one.
"""
import glob
import os
import sys

from . import census, cloud, lock as lock_mod, providers, session_roles, settings, util


UNAVAILABLE_HTTP = (403, 404)   # a copy of another account's session, or one that is gone: skipped quietly

# the lock field that names the session, the role word in the output and the title that role gets
ROLES = (
    ('session_id', 'supervisor', settings.supervisor_title),
    ('mailbox', 'questions', settings.questions_title),
    ('closer', 'closer', settings.closer_title),
)


def app_records(ids=None):
    """{local id: record}: the newest non-archived app record of each session (there may be one copy per account).
    `ids` limits the read to those sessions' files."""
    if ids is None:
        patterns = [census.app_glob()]
    else:
        base = os.path.dirname(census.app_glob())
        patterns = [os.path.join(base, glob.escape(str(i)) + '.json') for i in ids]
    found = {}
    for pattern in patterns:
        for rec in census.read_json_files(pattern):
            sid = rec.get('sessionId')
            if not sid or rec.get('isArchived'):
                continue
            if sid not in found or (util.num(rec.get('lastActivityAt')) or 0) >= (util.num(found[sid].get('lastActivityAt')) or 0):
                found[sid] = rec
    return found


def expected_titles(lock):
    """[(role, local id, expected title)] for the sessions a lock names; empty when it does not name its project."""
    project = lock.get('project')
    if not project:
        return []
    return [(role, lock[field], title(project)) for field, role, title in ROLES
            if isinstance(lock.get(field), str) and lock.get(field)]


def same_title(a, b):
    return ' '.join(str(a or '').split()) == ' '.join(str(b or '').split())


def rename_lines(lock, records=None):
    """`RENAME <local id> <role> «current» -> «expected»` for each session of the lock whose local title differs.
    A session with no live app record is not listed (nothing to rename)."""
    wanted = expected_titles(lock)
    if records is None:
        records = app_records([sid for _, sid, _ in wanted])
    lines = []
    for role, sid, want in wanted:
        rec = records.get(sid)
        if rec is not None and not same_title(rec.get('title'), want):
            lines.append(f'RENAME {sid} {role} «{rec.get("title") or ""}» -> «{want}»')
    return lines


def adopt_lines(lock, records=None):
    """`ADOPT <local id> closer (abierta por <parent id or ->)` when the lock's closing session is not a child of the lock
    owner in the app's sidebar: its record says another session opened it (`spawnedFrom.sessionId`), or it was moved to
    the top level (`lineageDetached`). No record, or a record that says neither, prints nothing. The questions session
    is not adopted: its right place is the top level (see detach_lines). Cosmetic: the role keeps working through the
    lock."""
    owner = lock.get('session_id')
    wanted = [(role, sid) for role, sid, _ in expected_titles(lock) if role == 'closer']
    if records is None:
        records = app_records([sid for _, sid in wanted])
    lines = []
    for role, sid in wanted:
        rec = records.get(sid)
        if rec is None:
            continue
        spawned = rec.get('spawnedFrom')
        parent = spawned.get('sessionId') if isinstance(spawned, dict) else None
        parent = parent if isinstance(parent, str) and parent else None
        if rec.get('lineageDetached') is True or (parent is not None and parent != owner):
            lines.append(f'ADOPT {sid} {role} (abierta por {parent or "-"})')
    return lines


def detach_lines(lock, records=None):
    """`DETACH <local id> questions (cuelga de <parent id>)` when the lock's questions session hangs from any session in
    the app's sidebar, the lock owner included (session_roles.hangs_from). A session that hangs shows its dialogs in its
    parent's window, so it belongs at the top level. No record, or a top-level record, prints nothing."""
    wanted = [sid for role, sid, _ in expected_titles(lock) if role == 'questions']
    if records is None:
        records = app_records(wanted)
    lines = []
    for sid in wanted:
        parent = session_roles.hangs_from(records.get(sid))
        if parent is not None:
            lines.append(f'DETACH {sid} questions (cuelga de {parent})')
    return lines


def hint_lines(lock, records=None):
    """The RENAME, ADOPT and DETACH lines of a lock (what `beat` shows its owner)."""
    if records is None:
        records = app_records([sid for _, sid, _ in expected_titles(lock)])
    return rename_lines(lock, records) + adopt_lines(lock, records) + detach_lines(lock, records)


def fix_lock_title(lock):
    """Rewrite the lock's own title to the supervisor title, under the lock the other writes use. True when it changed."""
    want = settings.supervisor_title(lock.get('project'))
    with lock_mod.Store() as store:
        current = store.read(lock['key'])
        if current is None or current.get('session_id') != lock.get('session_id') or current.get('title') == want:
            return False
        current['title'] = want
        store.write(lock['key'], current)
        return True


# ---------------------------------------------------------------- Remote Control copies

def remote_plan(sessions, records, only_lock=None):
    """[(cloud row, expected title)] for the active Remote Control copies of the local sessions in `records`.

    Per local session: its copies, newest first by last event; the newest carries the local title, each older one the
    local title plus the previous-copy suffix. A copy with no local record, and a local record without a title, are
    left alone; so is a title that looks like `supervisor-lock` output. `only_lock` keeps the sessions inside that
    lock's project."""
    ct = providers.cloud_tests_module()
    bridges = {}
    for row in sessions:
        if row.get('kind') == 'bridge' and row.get('status') == 'active' and row.get('id'):
            bridges[ct.sid_key(row['id'])] = row
    plan, claimed = [], set()
    for sid in sorted(records):
        rec = records[sid]
        local = rec.get('title')
        if not isinstance(local, str) or not local.strip() or util.title_refusal(local):
            continue
        if only_lock is not None and lock_mod.lock_containing(rec.get('cwd'), [only_lock]) is None:
            continue
        keys = [ct.sid_key(b) for b in rec.get('bridgeSessionIds') or [] if isinstance(b, str)]
        rows = [bridges[k] for k in dict.fromkeys(keys) if k in bridges and k not in claimed]
        claimed.update(ct.sid_key(r['id']) for r in rows)
        rows.sort(key=lambda r: (-(ct.iso_epoch(r.get('last_event_at')) or 0), str(r['id'])))
        for number, row in enumerate(rows):
            plan.append((row, local if number == 0 else local + settings.REMOTE_PREVIOUS_SUFFIX))
    return plan


def sync_remote(records, fix, emit, only_lock=None):
    """Print (and with `fix` apply) the renames of the Remote Control copies. Returns {'fixed', 'skipped', 'failed'}.
    Never raises: an unreachable API or an absent provider is one `REMOTE unavailable` line."""
    counts = {'fixed': 0, 'skipped': 0, 'failed': 0}
    try:
        sessions, err = cloud.cloud_active()
        if sessions is None:
            emit(f'REMOTE unavailable: {err}')
            return counts
        ct = providers.cloud_tests_module()
        for row, want in remote_plan(sessions, records, only_lock):
            current = row.get('title') or ''
            if same_title(current, want):
                continue
            emit(f'REMOTE {row["id"]} «{current}» -> «{want}»')
            if not fix:
                continue
            code, _ = ct.api_call('PUT', f'/v1/code/sessions/{row["id"]}', {'title': want})
            if code == 200:
                counts['fixed'] += 1
                cloud.rename_cloud_session(row['id'], want)
            elif code in UNAVAILABLE_HTTP:
                counts['skipped'] += 1
            else:
                counts['failed'] += 1
                emit(f'REMOTE {row["id"]} HTTP {code}')
    except Exception as err:   # the API is down (ApiUnavailable) or anything else: reported once, never fatal
        emit(f'REMOTE unavailable: {str(err)[:200] or type(err).__name__}')
    if counts['skipped']:
        emit(f'REMOTE skipped {counts["skipped"]} (HTTP {"/".join(map(str, UNAVAILABLE_HTTP))}: another account or gone)')
    return counts


def sync(fix, emit=print, session=None, remote=True):
    """The whole job of `titles`: RENAME lines for the local sessions of every lock, the lock titles, and the Remote
    Control copies (unless `remote` is off). Returns 2 for an unknown `session`, else 0."""
    locks = lock_mod.all_lock_files()
    only = None
    if session:
        locks = [lock for lock in locks if session in (lock.get('session_id'), lock.get('mailbox'), lock.get('closer'))]
        if not locks:
            return 2
        only = locks[0]
    records = app_records()
    for lock in locks:
        try:   # one broken lock file must not stop the others, nor the Remote Control copies below
            for line in hint_lines(lock, records):
                emit(line)
            want = settings.supervisor_title(lock.get('project')) if lock.get('project') else None
            if want and lock.get('title') != want:
                emit(f'LOCK {lock.get("key")} «{lock.get("title") or ""}» -> «{want}»')
                if fix:
                    fix_lock_title(lock)
        except Exception as err:
            emit(f'LOCK {lock.get("key")} unreadable: {str(err)[:200] or type(err).__name__}')
    # the cloud copies of a local session are renamed whether or not the session belongs to a supervision
    if remote:
        sync_remote(records, fix, emit, only)
    return 0


def cmd_titles(args):
    code = sync(args.fix, print, args.session)
    if code:
        print(f'supervisor-lock: no lock names the session {args.session}', file=sys.stderr)
    return code


def watchdog_sync():
    """What the watchdog does each run when `titles_sync` is on: `titles --fix`, silently (no lines unless it fails)."""
    if settings.TITLES_SYNC:
        sync(True, lambda line: None, remote=os.environ.get('SUPERVISOR_WATCHDOG_CLOUD', '1') != '0')
