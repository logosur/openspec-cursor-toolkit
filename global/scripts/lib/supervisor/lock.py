"""The lock of a project: one supervisor, its heartbeat, its release and its listing."""
import fcntl
import glob
import json
import os
import socket
import sys
import time
from datetime import datetime

from . import backlog, census, lint, projects, providers, session_roles, settings, util, workmode


TTL = {'running': 1800, 'paused': 7200}


# ---------------------------------------------------------------- lock storage

class Store:
    """Exclusive flock on <home>/.flock for the whole read-modify-write."""

    def __enter__(self):
        os.makedirs(os.path.join(util.home(), 'locks'), exist_ok=True)
        self.fh = open(os.path.join(util.home(), '.flock'), 'w')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()

    @staticmethod
    def path(key):
        return os.path.join(util.home(), 'locks', key + '.json')

    def read(self, key):
        try:
            with open(self.path(key)) as fh:
                return json.load(fh)
        except (FileNotFoundError, ValueError):
            return None

    def write(self, key, owner):
        path = self.path(key)
        tmp = path + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(owner, fh, indent=2, sort_keys=True)
            fh.write('\n')
        os.replace(tmp, path)

    def delete(self, key):
        try:
            os.remove(self.path(key))
        except FileNotFoundError:
            pass


def is_stale(owner):
    return util.age_seconds(owner.get('heartbeat')) > TTL.get(owner.get('state'), TTL['running'])


def new_owner(project, args, **extra):
    stamp = util.now_iso()
    owner = {
        'key': project['key'], 'project': project['name'], 'checkout': project['checkout'],
        'common_dir': project['common_dir'], 'session_id': args.session,
        'title': args.title or settings.supervisor_title(project['name']),
        'host': socket.gethostname(), 'registry': args.registry or project['registry_dir'],
        'state': 'running', 'phase': '', 'round': 0, 'started': stamp, 'heartbeat': stamp,
    }
    # No `skill_seen` here: taking the lock does not mean the skill was read. Only `beat --skill-seen` records it.
    owner.update(extra)
    return owner


def status_word(owner):
    return 'STALE' if is_stale(owner) else 'HELD'


NO_MAILBOX_FLAG = 'SIN SESIÓN DE PREGUNTAS'
NO_MAILBOX_GRACE_S = 600     # a young lock still has time to open and register its questions session
NO_MAILBOX_ALERT_EVERY_S = 3600  # one desktop alert per lock and hour


def lacks_mailbox(owner):
    """True for a running supervision that has not registered its questions session (`beat --mailbox`)."""
    return owner.get('state') == 'running' and not owner.get('mailbox')


def status_line(owner, with_checkout=False, asking=None):
    """`asking` is the session that asks: the owner reads MINE for its own live lock, never the HELD of «another»."""
    word = status_word(owner)
    if asking and word == 'HELD' and owner.get('session_id') == asking:
        word = 'MINE'
    line = (f'{word} {owner["key"]} session={owner.get("session_id")} state={owner.get("state")} '
            f'phase={owner.get("phase") or "-"} round={owner.get("round")} '
            f'heartbeat_age_s={util.age_seconds(owner.get("heartbeat"))} title={owner.get("title") or "-"}')
    if owner.get('mailbox'):
        line += f' mailbox={owner["mailbox"]}'
    elif lacks_mailbox(owner):
        line += f' {NO_MAILBOX_FLAG}'
    mode = workmode.read_mode(owner.get('key')).get('mode') if owner.get('key') else None
    if mode and mode != 'normal':
        line += f' mode={mode}'
    return line + (f' checkout={owner.get("checkout")}' if with_checkout else '')


def report_held(owner, always_held=False):
    word = 'HELD' if always_held else status_word(owner)
    print(f'{word} {owner["key"]}')
    print(json.dumps(owner, indent=2, sort_keys=True))
    print(f'heartbeat_age_s={util.age_seconds(owner.get("heartbeat"))}')
    return 3 if word == 'HELD' else 4


def refuse_title(title):
    """Exit code 2 (and a message) when `title` looks like `supervisor-lock` output; None when it is fine or absent."""
    why = util.title_refusal(title) if title else None
    if why:
        print(f'TITLE REFUSED: {why}', file=sys.stderr)
        return 2
    return None


def cmd_acquire(args):
    refused = refuse_title(args.title)
    if refused:
        return refused
    project = projects.resolve(args.dir)
    with Store() as store:
        owner = store.read(project['key'])
        if owner is None:
            store.write(project['key'], new_owner(project, args))
            print(f'ACQUIRED {project["key"]}')
            return 0
        if owner.get('session_id') == args.session:
            owner.update(state='running', heartbeat=util.now_iso())
            clear_pause(owner)
            if args.title:
                owner['title'] = args.title
            if args.registry:
                owner['registry'] = args.registry
            store.write(project['key'], owner)
            print(f'RESUMED {project["key"]}')
            return 0
        return report_held(owner)


def cmd_reclaim(args):
    refused = refuse_title(args.title)
    if refused:
        return refused
    project = projects.resolve(args.dir)
    with Store() as store:
        owner = store.read(project['key'])
        if owner is not None and owner.get('session_id') != args.from_id:
            return report_held(owner, always_held=True)
        extra = {}
        if owner is not None:
            extra['reclaimed_from'] = {k: owner.get(k) for k in ('session_id', 'heartbeat', 'state', 'registry')}
        store.write(project['key'], new_owner(project, args, **extra))
        print(f'RECLAIMED {project["key"]}')
        return 0


def not_owner(key):
    print(f'NOT OWNER {key}', file=sys.stderr)
    return 5


SKILL_NOT_LOADED = 8   # `beat --skill-seen` without a load of the skill in the session's transcript
PAUSE_REFUSED = 9      # `beat --state paused` without --third-party while the account has usage


# ---------------------------------------------------------------- why a lock is paused
# A supervisor may pause only when all that is left waits on a third party (`--third-party`). A pause for the usage
# limit is recorded as such and lasts only while the account has no usage: `beat` refuses it once usage is back, and
# the watcher (USAGE), `revive` (paused-limit) and the Stop hook push a limit pause back to work.
PAUSE_THIRD_PARTY = 'third-party'
PAUSE_LIMIT = 'limit'
PAUSE_FIELDS = ('pause_cause', 'pause_why', 'paused_at')


def pause_cause(owner):
    """'third-party' or 'limit' for a paused lock, None for any other state. A paused lock without a cause (written
    before the field existed) counts as a limit pause."""
    if (owner or {}).get('state') != 'paused':
        return None
    return PAUSE_THIRD_PARTY if owner.get('pause_cause') == PAUSE_THIRD_PARTY else PAUSE_LIMIT


def paused_for_limit(owner):
    return pause_cause(owner) == PAUSE_LIMIT


def clear_pause(owner):
    for field in PAUSE_FIELDS:
        owner.pop(field, None)


def apply_pause(owner, cause, why=None):
    """Record a pause with its cause; `paused_at` is set when a pause of that cause starts and kept while it lasts."""
    same = pause_cause(owner) == cause and owner.get('paused_at')
    owner['state'] = 'paused'
    owner['pause_cause'] = cause
    if not same:
        owner['paused_at'] = util.now_iso()
    if why:
        owner['pause_why'] = why
    else:
        owner.pop('pause_why', None)


def pause_refusal(key, owner):
    return (f'PAUSE REFUSED {key}: la cuenta tiene uso ahora (lo dice el uso real de la cuenta, no la hora a la que se '
            f'agotó el límite), así que el cerrojo sigue en «{owner.get("state")}». El límite de uso no es motivo de '
            f'pausa: sigue el ciclo desde F1. Si lo único que queda espera a un tercero, dilo con '
            f'--state paused --third-party "<qué espera y de quién>".')


def skill_seen_refusal(key, session, floor):
    stamp = datetime.fromtimestamp(floor).strftime('%d-%m %H:%M') if floor else '?'
    return (f'SKILL SEEN REFUSED {key}: tu transcripción no muestra que hayas cargado la skill {lint.skill_name()} '
            f'después del último cambio de la skill, de una regla global o de supervisor-lock ({stamp}). Ejecutar '
            f'beat --skill-seen no la carga: invócala con la herramienta Skill, aplica lo nuevo y repite '
            f'supervisor-lock beat --session {session} --skill-seen.')


def cmd_beat(args):
    refused = refuse_title(getattr(args, 'title', None))
    if refused:
        return refused
    project = projects.resolve(args.dir)
    third_party = ' '.join((getattr(args, 'third_party', None) or '').split())
    if getattr(args, 'third_party', None) is not None and (args.state != 'paused' or len(third_party) < backlog.BACKLOG_WHY_MIN):
        print(f'USAGE: --state paused --third-party "<qué espera y de quién; {backlog.BACKLOG_WHY_MIN} caracteres o más>"',
              file=sys.stderr)
        return 2
    # before the flock: the transcript scan reads a file of up to hundreds of MB, and it does not need the lock
    proof = lint.skill_load_proof(args.session) if args.skill_seen and lint.skill_mtime() is not None else None
    # also before the flock: the usage answer may come from the network (cached for a couple of minutes)
    has_usage = providers.account_has_usage() if args.state == 'paused' and not third_party else None
    refused_pause = False
    with Store() as store:
        owner = store.read(project['key'])
        if owner is None or owner.get('session_id') != args.session:
            return not_owner(project['key'])
        owner['heartbeat'] = util.now_iso()
        if getattr(args, 'no_work', None):
            why = ' '.join(args.no_work.split())
            order = owner.pop('guard_order', None)
            if len(why) < backlog.BACKLOG_WHY_MIN:
                print(f'USAGE: --no-work "<por qué el mensaje del desarrollador no pide trabajo; {backlog.BACKLOG_WHY_MIN} '
                      f'caracteres o más>"',
                      file=sys.stderr)
                return 2
            util.hook_log('hook.log', f'{project["key"]} {args.session} no-work «{(order or {}).get("text", "")[:200]}»: {why[:300]}')
        if args.phase is not None and not str(args.phase).strip().lower().startswith('guardia'):
            owner.pop('guard_order', None)  # leaving guard is the outcome of the developer's message
        if args.phase is not None and str(args.phase).strip().lower().startswith('guardia'):
            refusal = backlog.guard_refusal(dict(owner, phase=args.phase), args.session)
            if refusal:
                store.write(project['key'], owner)  # the heartbeat (and a --no-work) still count
                print(f'GUARD REFUSED {project["key"]}: {refusal}.', file=sys.stderr)
                return 7
        if args.state == 'running':
            owner['state'] = 'running'
            clear_pause(owner)
        elif args.state == 'paused' and third_party:
            apply_pause(owner, PAUSE_THIRD_PARTY, third_party)
        elif args.state == 'paused' and has_usage is True:
            refused_pause = True  # the state stays as it is; the heartbeat and the other fields of this beat still count
        elif args.state == 'paused':
            apply_pause(owner, PAUSE_LIMIT)
        if args.phase is not None:
            owner['phase'] = args.phase
        if args.round is not None:
            owner['round'] = args.round
        if args.mailbox:
            owner['mailbox'] = args.mailbox
        if getattr(args, 'closer', None):
            owner['closer'] = args.closer
        if getattr(args, 'title', None):
            owner['title'] = args.title
        if args.skill_seen and proof is not None:
            verdict, when = proof
            if verdict == 'not-loaded':
                # the marker is the proof the message gate and the Stop hook trust: only a load in the session's own
                # transcript sets it. The heartbeat and the other fields of this beat still count.
                store.write(project['key'], owner)
                if refused_pause:
                    print(pause_refusal(project['key'], owner), file=sys.stderr)
                print(skill_seen_refusal(project['key'], args.session, when), file=sys.stderr)
                return SKILL_NOT_LOADED
            mtime = lint.skill_mtime()
            if mtime is not None:
                owner['skill_seen'] = mtime
                # when it was read: the message gate counts as a new update only what changed after this moment
                owner['skill_seen_at'] = time.time()
                # where the proof came from: the load's time, or none when no transcript could be read (fail open)
                owner['skill_seen_proof'] = (datetime.fromtimestamp(when).astimezone().isoformat(timespec='seconds')
                                             if verdict == 'loaded' else 'unverified')
                if verdict == 'no-transcript':
                    util.hook_log('hook.log', f'{project["key"]} {args.session} skill-seen unverified: no transcript found')
                    print(f'SKILL SEEN UNVERIFIED {project["key"]}: no encuentro la transcripción de {args.session}; '
                          f'se anota sin comprobar que la skill se cargó.', file=sys.stderr)
        store.write(project['key'], owner)
        print(f'BEAT {project["key"]}')
    if refused_pause:
        util.hook_log('hook.log', f'{project["key"]} {args.session} paused beat refused: the account has usage')
        print(pause_refusal(project['key'], owner), file=sys.stderr)  # stdout goes to /dev/null
        return PAUSE_REFUSED
    hint = no_mailbox_hint(project, owner)
    if hint:
        print(hint, file=sys.stderr)  # supervisors call `beat … >/dev/null`: stdout never reaches them
    askdue_hint(project)
    rename_hint(owner)
    return 0


def askdue_hint(project):
    """The ASKDUE line on stderr when the project's partial batch of blocking questions may be sent now (ask-queue
    decides). Every beat, like the NOMAILBOX hint: it costs no wake. Only reads; a failure prints nothing."""
    try:
        from . import askdue  # lazily: askdue imports cloud, which imports this module
        line = askdue.askdue_line(project)
        if line:
            print(line, file=sys.stderr)
    except Exception:
        pass


def rename_hint(owner):
    """The RENAME, ADOPT and DETACH lines of the project's supervisor, questions and closing sessions, so a supervisor
    sees on its next heartbeat which of them carry another title, which closing session is not its child, and whether
    the questions session hangs from a session instead of living at the top level. Only reads; a failure never changes
    what `beat` returns."""
    if not settings.TITLES_SYNC:
        return
    try:
        from . import titles  # lazily: titles imports this module
        for line in titles.hint_lines(owner):
            print(line, file=sys.stderr)
    except Exception:
        pass


def no_mailbox_hint(project, owner):
    """The NOMAILBOX desktop alert reaches only the developer, never the supervisor, which may run for hours with no
    registered questions session and learn it only when its AskUserQuestion is denied at the final batch. `beat` tells
    the owner itself, naming an existing questions session of the project (exact title) when there is one."""
    if not lacks_mailbox(owner):
        return ''
    if owner.get('started') and util.age_seconds(owner.get('started')) <= NO_MAILBOX_GRACE_S:
        return ''
    root = os.path.realpath(project.get('checkout') or '')
    found = []
    for rec in census.read_json_files(census.app_glob()):
        title, cwd = rec.get('title'), rec.get('cwd')
        if rec.get('isArchived') or not isinstance(title, str) or not isinstance(cwd, str) or not rec.get('sessionId'):
            continue
        if not any(util.fold_text(m) in util.fold_text(title) for m in session_roles.ASK_GATE_MAILBOX_TITLES):
            continue
        real = os.path.realpath(cwd)
        if root and (real == root or real.startswith(root + os.sep)):
            found.append((rec.get('lastActivityAt') or 0, rec['sessionId'], title))
    register = f'supervisor-lock beat --session {owner.get("session_id")} --mailbox <local_id>'
    if found:
        _, local_id, title = max(found, key=lambda f: util.num(f[0]) or 0)
        return (f'{NO_MAILBOX_FLAG}: la tanda final no tiene dónde abrirse. Ya existe «{title}» ({local_id}): '
                f'regístrala ahora con `{register.replace("<local_id>", local_id)}`; la tanda final se le presenta ahí, '
                f'cuando toque.')
    return (f'{NO_MAILBOX_FLAG}: la tanda final no tiene dónde abrirse. Abre la sesión '
            f'«{settings.questions_title(project.get("name"))}» (F0b) y regístrala con `{register}`.')


def cmd_open(args):
    project = projects.resolve(args.dir)
    with Store() as store:
        owner = store.read(project['key'])
    rows = census.open_sessions(project, owner)
    if args.json:
        print(json.dumps({'key': project['key'], 'count': len(rows), 'open': rows}, indent=2))
    else:
        for line in census.open_lines(rows):
            print(line)
        print(f'open: {len(rows)} session(s) besides the supervisor and its questions session')
    return 6 if rows else 0


def cmd_release(args):
    project = projects.resolve(args.dir)
    if args.open_ok is not None and not args.open_ok.strip():
        util.die('--open-ok needs a non-empty reason', 2)
    with Store() as store:
        owner = store.read(project['key'])
        if owner is None:
            print(f'ALREADY FREE {project["key"]}')
            return 0
        if owner.get('session_id') != args.session:
            return not_owner(project['key'])
        try:
            rows = census.collect_sessions(project, False, {})
        except Exception as exc:  # fail open: an unreadable census must not trap the lock
            print(f'supervisor-lock: warning: could not read the session census ({exc!r}); releasing without the checks',
                  file=sys.stderr)
            rows = []
        # the questions session is expected to be busy presenting the final batch when the supervisor lets go
        busy = [r for r in rows
                if r['live'] and r['status'] == 'busy' and r['id'] != args.session and r['id'] != owner.get('mailbox')]
        if busy and not args.force_close:
            for r in busy:
                print(f'OPEN WORK {r["id"]} status=busy idle_s={"-" if r["idle_s"] is None else r["idle_s"]} '
                      f'title={r["title"] or "-"}')
            print('release refused: finish or close those sessions, or pass --force-close REASON', file=sys.stderr)
            return 6
        # every session of the project must be closed and archived first, whoever opened it
        still_open = census.open_sessions(project, owner, rows)
        if still_open and not args.force_close and not args.open_ok:
            for line in census.open_lines(still_open):
                print(line)
            print('release refused: close (/cierra-sesion) and archive every session of the project first, whoever '
                  'opened it, or pass --open-ok "<reason>" for one that a rule forbids archiving', file=sys.stderr)
            return 6
        entry = {'time': util.now_iso(), 'key': project['key'], 'project': project['name'], 'session': args.session,
                 'verdict': args.verdict}
        if owner.get('mailbox'):
            entry['mailbox'] = owner['mailbox']  # the questions session keeps asking after the release (ask gate)
        if args.force_close:
            entry.update(force_close=args.force_close, open_work=[r['id'] for r in busy])
        if still_open and args.open_ok and not args.force_close:
            entry.update(open_ok=args.open_ok, open_sessions=[r['id'] for r in still_open])
        closed = os.path.join(util.home(), 'closed')
        os.makedirs(closed, exist_ok=True)
        with open(os.path.join(closed, project['key'] + '.json'), 'a') as fh:
            fh.write(json.dumps(entry, sort_keys=True) + '\n')
        store.delete(project['key'])
        note = f' (forced: {args.force_close})' if args.force_close else ''
        if 'open_ok' in entry:
            note += f' (open-ok: {args.open_ok}; left open: {", ".join(entry["open_sessions"])})'
        print(f'RELEASED {project["key"]}' + note)
        return 0


def with_age(owner):
    return dict(owner, status=status_word(owner), heartbeat_age_s=util.age_seconds(owner.get('heartbeat')))


def cmd_status(args):
    project = projects.resolve(args.dir)
    with Store() as store:
        owner = store.read(project['key'])
    if args.json:
        print(json.dumps({'key': project['key'], 'status': 'FREE'} if owner is None else with_age(owner),
                         indent=2, sort_keys=True))
    else:
        print(f'FREE {project["key"]}' if owner is None else status_line(owner, asking=args.session))
    return 0


def cmd_list(args):
    rows = []
    with Store() as store:
        for path in sorted(glob.glob(os.path.join(util.home(), 'locks', '*.json'))):
            owner = store.read(os.path.basename(path)[:-5])
            if owner:
                rows.append(owner)
    legacy = os.path.join(util.home(), 'MASTER.lock.d')
    has_legacy = os.path.isdir(legacy)
    from . import usage_role  # the machine-wide usage role (usage-watch), null when free
    role = usage_role.with_age(usage_role.read())
    if args.json:
        print(json.dumps({'locks': [with_age(o) for o in rows], 'legacy': legacy if has_legacy else None,
                          'usage_role': role}, indent=2, sort_keys=True))
        return 0
    for owner in rows:
        print(status_line(owner, with_checkout=True))
    if role:
        print(f'USAGE-ROLE {role["status"]} session={role.get("session_id")} heartbeat_age_s={role["heartbeat_age_s"]} '
              f'home={role.get("home_project") or "-"}')
    if has_legacy:
        print(f'LEGACY {legacy} present (old multi-project supervisor)')
    return 0


def beat_owner(project, owner_id):
    """Refresh the heartbeat of the project lock when `owner_id` holds it; state/phase/round stay as they are."""
    try:
        with Store() as store:
            owner = store.read(project['key'])
            if owner is not None and owner.get('session_id') == owner_id:
                owner['heartbeat'] = util.now_iso()
                store.write(project['key'], owner)
    except OSError:
        pass


STALE_LOCK_SUPERVISED_S = 86400  # a stale, unreleased lock still supervises (ask gate, Stop) up to 24 h after its heartbeat


def read_locks():
    """{owner local id: lock} of every lock file that names an owner session."""
    locks = {}
    for path in sorted(glob.glob(os.path.join(util.home(), 'locks', '*.json'))):
        owner = Store().read(os.path.basename(path)[:-5])
        if owner and owner.get('session_id'):
            locks[owner['session_id']] = owner
    return locks


def all_lock_files():
    """Every lock file as a dict (live or stale), in file-name order."""
    store = Store()
    return [lock for lock in (store.read(os.path.basename(path)[:-5])
                              for path in sorted(glob.glob(os.path.join(util.home(), 'locks', '*.json')))) if isinstance(lock, dict)]


def lock_containing(cwd, locks):
    """The most specific lock whose project contains `cwd`, else None (the logic of collect_sessions).

    A git lock matches when the git common dir of `cwd` is its own (so a worktree counts). A workspace lock (no git
    common dir) matches when `cwd` is inside its checkout, or when the common dir of `cwd` is (a nested repo or a
    worktree of it that lives elsewhere). A git match beats a workspace one, and a deeper workspace beats a shallower."""
    if not cwd or not isinstance(cwd, str) or not os.path.isdir(cwd):
        return None
    real = os.path.realpath(cwd)
    common = projects.common_dir_of(cwd)
    best, rank = None, None
    for lock in locks:
        checkout = lock.get('checkout') if isinstance(lock.get('checkout'), str) else None
        if lock.get('common_dir'):
            if common != lock['common_dir']:
                continue
            found = (1, len(checkout or ''))
        else:
            if not checkout:
                # an old lock file without checkout/common_dir: only its key says which project it is (the old rule)
                try:
                    if lock.get('key') and lock['key'] == projects.resolve(cwd)['key'] and (rank is None or (1, 0) > rank):
                        best, rank = lock, (1, 0)
                except SystemExit:
                    pass
                continue
            root = os.path.realpath(checkout)
            if not (real == root or real.startswith(root + '/')
                    or (common and (common == root or common.startswith(root + '/')))):
                continue
            found = (0, len(root))
        if rank is None or found > rank:
            best, rank = lock, found
    return best


def lock_still_supervises(lock):
    """True while a lock (live, or stale but not released) is at most STALE_LOCK_SUPERVISED_S past its last heartbeat."""
    return not is_stale(lock) or util.age_seconds(lock.get('heartbeat')) <= STALE_LOCK_SUPERVISED_S
