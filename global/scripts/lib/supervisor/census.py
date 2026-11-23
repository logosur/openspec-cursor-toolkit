"""The census of sessions: app records and CLI registry, joined and cached."""
import glob
import json
import os
from datetime import datetime

from . import projects, settings, transcripts, util


def open_sessions(project, owner, rows=None):
    """Census rows still open: every non-archived session of the project except the lock owner and its questions session.

    `owner` is the lock dict (or None). Ids match on the row id (`local_…`) or on its CLI session id. `rows` is an
    already collected census (collect_sessions(project, False, {})), to avoid reading it twice."""
    if rows is None:
        rows = collect_sessions(project, False, {})
    mine = {i for i in ((owner or {}).get('session_id'), (owner or {}).get('mailbox'), (owner or {}).get('closer')) if i}
    return [r for r in rows if r['id'] not in mine and r.get('cli') not in mine]


def open_lines(rows):
    return [f'OPEN {session_line(r)}' for r in rows]


def children_map():
    kids = {}
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            with open(f'/proc/{entry}/stat') as fh:
                stat = fh.read()
            ppid = int(stat[stat.rfind(')') + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(entry))
    return kids


# Every `wait` round reads every session file of the app: there can be a thousand records and over 100 MB of JSON per
# round. An unchanged file (same mtime_ns, size and inode) comes from this memo. Most of those bytes are keys this
# script never reads; they are dropped before caching so the memo stays small. Callers only read the records: never
# mutate one.
_JSON_FILES = {}
JSON_UNREAD_KEYS = frozenset({'remoteMcpServersConfig', 'promptAppendSnapshot', 'toolSurfaceSnapshot',
                              'sideSessionNotes', 'peerReceipts', 'pendingSystemReminder', 'lastTurnReport',
                              'postTurnSummary'})


def read_json_files(pattern):
    for path in sorted(glob.glob(pattern)):
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        hit = _JSON_FILES.get(path)
        if hit and hit[0] == sig:
            data = hit[1]
        else:
            try:
                with open(path) as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                _JSON_FILES.pop(path, None)  # half-written: parse it again next time
                continue
            if isinstance(data, dict):
                data = {k: v for k, v in data.items() if k not in JSON_UNREAD_KEYS}
            _JSON_FILES[path] = (sig, data)
        if isinstance(data, dict):
            yield data


def cli_dir():
    return os.path.expanduser(os.environ.get('SUPERVISOR_SESSIONS_DIR', '~/.claude/sessions'))


def app_glob():
    return os.path.expanduser(os.environ.get(
        'SUPERVISOR_APP_SESSIONS_GLOB', settings.APP_SESSIONS_GLOB))


def pid_alive(pid):
    return isinstance(pid, int) and os.path.exists(f'/proc/{pid}')


def collect_sessions(project, include_all, cache):
    """Rows for the Claude sessions of a project. `cache` maps cwd -> git common dir across calls."""

    root = project['checkout']

    def inside_root(path):
        return path == root or path.startswith(root + '/')

    def same_project(cwd):
        if not isinstance(cwd, str) or not os.path.isdir(cwd):
            return False
        if project['kind'] == 'workspace':
            if inside_root(os.path.realpath(cwd)):
                return True
            if cwd not in cache:
                cache[cwd] = projects.common_dir_of(cwd)
            return bool(cache[cwd]) and inside_root(cache[cwd])  # worktree of a nested repo living elsewhere
        if cwd not in cache:
            cache[cwd] = projects.common_dir_of(cwd)
        return cache[cwd] == project['common_dir']

    # CLI files: a restarted process leaves its old pid file behind, so several can share one id.
    groups = {}
    for rec in read_json_files(os.path.join(cli_dir(), '*.json')):
        if not same_project(rec.get('cwd')):
            continue
        pid = rec.get('pid')
        sid = rec.get('hostSessionId') or rec.get('sessionId') or f'pid-{pid}'
        live = pid_alive(pid)
        stamp = max([util.num(rec.get(k)) or 0 for k in ('updatedAt', 'statusUpdatedAt')])
        groups.setdefault(sid, []).append((live, stamp, rec))
    found = {}
    for sid, items in groups.items():
        _, stamp, rec = max(items, key=lambda it: (it[0], it[1]))
        found[sid] = {'id': sid, 'live': any(it[0] for it in items), 'status': rec.get('status'),
                      'model': None, 'effort': None, 'cwd': rec.get('cwd'), 'title': rec.get('name'),
                      'cli': rec.get('sessionId') if isinstance(rec.get('sessionId'), str) else None,
                      'awaiting': False, 'crashes': 0, 'turns': None, 'app': False,
                      'stamp': max(util.num(rec.get(k)) or 0 for k in ('updatedAt', 'statusUpdatedAt'))}
    for rec in read_json_files(app_glob()):
        if rec.get('isArchived') or not same_project(rec.get('cwd')):
            continue
        sid = rec.get('sessionId')
        if not sid:
            continue
        entry = found.setdefault(sid, {'id': sid, 'live': False, 'status': None, 'cwd': rec.get('cwd'),
                                       'title': None, 'cli': None, 'stamp': 0})
        if not entry['cli'] and isinstance(rec.get('cliSessionId'), str):
            entry['cli'] = rec['cliSessionId']
        crashes = rec.get('queryCrashes')
        # the permission mode comes from the app record, newest copy first (there may be one copy per account), so
        # the supervisor sees it for every session, not only the ones it started
        app_stamp = util.num(rec.get('lastActivityAt')) or 0
        if isinstance(rec.get('permissionMode'), str) and app_stamp >= entry.get('mode_stamp', -1):
            entry.update(mode=rec['permissionMode'], mode_stamp=app_stamp)
        entry.update(app=True, model=rec.get('model'), effort=rec.get('effort'),
                     title=rec.get('title') or entry['title'],
                     awaiting=bool(rec.get('interruptedAwaitingPerson')),
                     crashes=len(crashes) if isinstance(crashes, list) else int(util.num(crashes) or 0),
                     turns=int(util.num(rec.get('completedTurns'))) if util.num(rec.get('completedTurns')) is not None else None,
                     stamp=max(entry['stamp'], util.num(rec.get('lastActivityAt')) or 0))
    now_ms = datetime.now().timestamp() * 1000
    rows = []
    for entry in found.values():
        if not include_all and not entry['app'] and not entry['live']:
            continue  # stale pid file of a dead process with no app record
        newest = entry.pop('stamp') / 1000
        entry.pop('mode_stamp', None)
        entry.setdefault('mode', None)
        main, subs = transcripts.session_files(entry['cli'], entry['cwd'])
        entry['transcript'] = main
        newest = max([newest] + [util.file_mtime(p) for p in ([main] if main else []) + subs])
        entry['idle_s'] = max(0, int(now_ms / 1000 - newest)) if newest else None
        rows.append(entry)
    return sorted(rows, key=lambda r: (not r['live'], r['id']))


def session_line(r):
    return ' | '.join([
        r['id'], f'live={"yes" if r["live"] else "no"}', f'status={r["status"] or "-"}',
        f'model={r.get("model") or "-"}', f'effort={r.get("effort") or "-"}', f'mode={r.get("mode") or "-"}',
        f'idle_s={"-" if r["idle_s"] is None else r["idle_s"]}', f'awaiting={"yes" if r["awaiting"] else "no"}',
        f'crashes={r["crashes"]}', f'turns={"-" if r["turns"] is None else r["turns"]}',
        r['cwd'], r['title'] or '-'])


def cmd_sessions(args):
    project = projects.resolve(args.dir)
    rows = collect_sessions(project, args.all, {})
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        print(session_line(r))
    return 0


def local_owner_of(session, locks):
    """The app `local_…` id among `locks` whose session has this CLI session id, else None."""
    for rec in read_json_files(os.path.join(cli_dir(), '*.json')):
        if rec.get('sessionId') == session and rec.get('hostSessionId') in locks:
            return rec['hostSessionId']
    # the hook runs after every turn of every session: read only the app records of the lock owners
    app_base = os.path.dirname(app_glob())
    for owner_id in locks:
        for rec in read_json_files(os.path.join(app_base, glob.escape(owner_id) + '.json')):
            if rec.get('cliSessionId') == session:
                return owner_id
    return None
