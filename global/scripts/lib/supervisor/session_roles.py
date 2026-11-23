"""The role of a session in a supervised project (owner, questions, supervised, free)."""
import glob
import json
import os
import re
import time

from . import census, lock as lock_mod, settings, util


def mailbox_alive(mailbox):
    """True when the mailbox id still has a non-archived app record."""
    if not mailbox:
        return False
    pattern = os.path.join(os.path.dirname(census.app_glob()), glob.escape(str(mailbox)) + '.json')
    return any(not rec.get('isArchived') for rec in census.read_json_files(pattern))


ASK_GATE_MAILBOX_TITLES = settings.QUESTIONS_TITLES  # config `questions_session_titles`
ASK_GATE_MAILBOX_CLOSED_DAYS = 7  # days a released lock's questions session may still ask (env ASK_GATE_MAILBOX_CLOSED_DAYS)
ASK_GATE_CLOSED_TAIL = 256 << 10  # bytes read from the end of each closed-history file


def ask_gate_mailbox_closed_days():
    try:
        value = float(os.environ.get('ASK_GATE_MAILBOX_CLOSED_DAYS', ''))
        if value > 0:
            return value
    except ValueError:
        pass
    return float(ASK_GATE_MAILBOX_CLOSED_DAYS)


def recent_closed_mailboxes():
    """Questions-session ids (`local_…`) of locks released within ASK_GATE_MAILBOX_CLOSED_DAYS. Never raises.

    A supervisor that released its lock (the developer ordered it, or the project ended) may leave a questions session
    that still has the final batch to present; this keeps recognising it for a while.
    Reads only the tail of each closed-history file whose mtime is inside the window; bad lines are skipped.
    """
    window = ask_gate_mailbox_closed_days() * 86400
    found = set()
    for path in sorted(glob.glob(os.path.join(util.home(), 'closed', '*.json'))):
        try:
            if time.time() - os.path.getmtime(path) > window:
                continue
            with open(path, 'rb') as fh:
                size = fh.seek(0, os.SEEK_END)
                fh.seek(max(0, size - ASK_GATE_CLOSED_TAIL))
                data = fh.read()
        except OSError:
            continue
        for line in data.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (isinstance(entry, dict) and isinstance(entry.get('mailbox'), str) and entry['mailbox']
                    and util.age_seconds(entry.get('time')) <= window):
                found.add(entry['mailbox'])
    return found


def title_names_project(title, project):
    """True when `project` appears in `title` as a whole word, ignoring case and accents."""
    name = util.fold_text(project).strip()
    return bool(name) and re.search(r'(?<![a-z0-9])' + re.escape(name) + r'(?![a-z0-9])', util.fold_text(title)) is not None


def mailbox_title_in_scope(title, cwd):
    """A questions-session title only counts inside the project it belongs to: the cwd is inside a
    supervised project (the lock that contains it, a stale one up to 24 h too) or the title names that project. With no
    cwd to judge, or no lock to scope against, the title is taken as before."""
    if not cwd:
        return True
    scope = [lock for lock in lock_mod.all_lock_files() if lock_mod.lock_still_supervises(lock)]
    if not scope or lock_mod.lock_containing(cwd, scope) is not None:
        return True
    return any(title_names_project(title, lock.get('project')) for lock in scope)


def is_mailbox_session(session, locks, cwd=None):
    """True when the session is the questions session: by app title (normalized: no accents, lower case) inside its
    project (`cwd`, see mailbox_title_in_scope), because a live supervisor lock records its local id, or because a lock
    released within ASK_GATE_MAILBOX_CLOSED_DAYS did."""
    local, titles = None, []
    for rec in census.read_json_files(os.path.join(census.cli_dir(), '*.json')):
        if rec.get('sessionId') == session:
            local = rec.get('hostSessionId') or local
            titles.append(rec.get('name'))
    if local is None or not any(titles):
        for path in glob.glob(census.app_glob()):
            try:
                with open(path) as fh:
                    text = fh.read()
                if session not in text:
                    continue
                rec = json.loads(text)
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get('cliSessionId') == session:
                local = rec.get('sessionId') or local
                titles += [rec.get('title'), rec.get('name')]
                break
    for title in titles:
        if isinstance(title, str) and any(util.fold_text(m) in util.fold_text(title) for m in ASK_GATE_MAILBOX_TITLES) \
                and mailbox_title_in_scope(title, cwd):
            return True
    if not local:
        return False
    return any(owner.get('mailbox') == local for owner in locks.values()) or local in recent_closed_mailboxes()


def session_role(session, cwd):
    """(role, lock) of a CLI session in the project of `cwd`, judged by supervisor locks (live, or stale <= 24 h old).

    'owner': holds a live lock. 'mailbox': the questions session (title, recorded in a live lock, or in a recently released one). 'supervised':
    any other session of a project whose lock is live. 'free': nobody supervises the project. `lock` is the project's
    lock (or the session's own), else None. A stale lock still supervises up to STALE_LOCK_SUPERVISED_S after its heartbeat
    (owner: free, as before). Never raises on a bad directory.
    """
    every = lock_mod.read_locks()
    live = {sid: lock for sid, lock in every.items() if not lock_mod.is_stale(lock)}
    # A stale lock that was never released (its supervisor died or went quiet) still supervises the project
    # for the ask gate for STALE_LOCK_SUPERVISED_S after its last heartbeat; only the owner and who may take the lock
    # keep the old rule (stale = no lock).
    recent = {sid: lock for sid, lock in every.items() if lock_mod.lock_still_supervises(lock)}
    project_lock = lock_mod.lock_containing(cwd, [lock for lock in lock_mod.all_lock_files() if lock_mod.lock_still_supervises(lock)])
    own = census.local_owner_of(session, live) if live else None
    if own is not None:
        return 'owner', live[own]
    if recent and census.local_owner_of(session, recent) is not None:
        return 'free', None
    if is_mailbox_session(session, recent, cwd):
        return 'mailbox', project_lock
    return ('supervised', project_lock) if project_lock is not None else ('free', None)
