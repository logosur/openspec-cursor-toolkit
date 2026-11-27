"""The usage role: one consumption sub-supervision session per machine (usage-watch, design D8).

The record `<home>/usage-role.json` holds `session_id` (the app id), `cli_session_id` (CLAUDE_CODE_SESSION_ID at claim
time), `home_project` (the project of --dir: machine-wide questions go to its queue), `title`, `started` and
`heartbeat`. It is written under the same flock as the project locks and goes stale after the running TTL. The holder is
a helper row everywhere: no project's `open`, `closable` or `backlog` counts it as work, and no closing session is told
to archive it.

  supervisor-lock usage-role --claim --session ID [--from OLD] [--dir DIR] [--title T]
      CLAIMED (free role) · RESUMED (the holder again) · HELD + exit 3 (another live holder) · STALE + exit 4 (another
      stale holder; claim again with --from <its id> to take it over) · TAKEN (--from named the holder)
  supervisor-lock usage-role --beat --session ID       BEAT; exit 3 for any other session
  supervisor-lock usage-role --release --session ID    RELEASED; exit 3 for any other session (the record stays)
"""
import json
import os
import sys

from . import util

TTL_S = 1800   # the running TTL of a project lock (lock.TTL['running'])
NOT_HOLDER = 3
STALE = 4


def path():
    return os.path.join(util.home(), 'usage-role.json')


def read():
    """The record, or None when the role is free (no file, a corrupt file, or a record that names nobody)."""
    rec = util.read_json(path())
    return rec if isinstance(rec, dict) and rec.get('session_id') else None


def ids(rec=None):
    """The app and CLI ids of the holder (empty when the role is free)."""
    rec = read() if rec is None else rec
    return {v for v in ((rec or {}).get('session_id'), (rec or {}).get('cli_session_id')) if isinstance(v, str) and v}


def is_stale(rec):
    return util.age_seconds(rec.get('heartbeat')) > TTL_S


def with_age(rec):
    if not rec:
        return None
    return dict(rec, status='STALE' if is_stale(rec) else 'HELD', heartbeat_age_s=util.age_seconds(rec.get('heartbeat')))


def is_usage_row(row, rec=None):
    """True when a census row is the usage role holder (by app id or CLI id)."""
    held = ids(rec)
    return bool(held) and (row.get('id') in held or row.get('cli') in held)


def _write(rec):
    tmp = path() + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write('\n')
    os.replace(tmp, path())


def _home_project(directory):
    from . import projects
    try:
        return projects.resolve(directory)['checkout']
    except SystemExit:   # not a git repository nor a workspace: the folder itself
        return os.path.realpath(directory or os.getcwd())


def _new(args, **extra):
    stamp = util.now_iso()
    rec = {'session_id': args.session, 'cli_session_id': os.environ.get('CLAUDE_CODE_SESSION_ID') or None,
           'home_project': _home_project(args.dir), 'title': args.title or 'usage sub-supervision',
           'started': stamp, 'heartbeat': stamp}
    rec.update(extra)
    return rec


def _report(word, rec):
    print(f'{word} usage-role')
    print(json.dumps(with_age(rec), indent=2, sort_keys=True))


def cmd_usage_role(args):
    from . import lock as lock_mod   # lazily: lock imports census, which imports this module
    with lock_mod.Store():
        rec = read()
        if args.claim:
            if rec is None:
                _write(_new(args))
                print('CLAIMED usage-role')
                return 0
            if rec.get('session_id') == args.session:
                rec['heartbeat'] = util.now_iso()
                if os.environ.get('CLAUDE_CODE_SESSION_ID'):
                    rec['cli_session_id'] = os.environ['CLAUDE_CODE_SESSION_ID']
                if args.title:
                    rec['title'] = args.title
                if args.dir:
                    rec['home_project'] = _home_project(args.dir)
                _write(rec)
                print('RESUMED usage-role')
                return 0
            if args.from_id and args.from_id == rec.get('session_id'):
                _write(_new(args, taken_from={k: rec.get(k) for k in ('session_id', 'cli_session_id', 'heartbeat')}))
                print('TAKEN usage-role')
                return 0
            stale = is_stale(rec)
            _report('STALE' if stale else 'HELD', rec)
            return STALE if stale else NOT_HOLDER
        if rec is None or rec.get('session_id') != args.session:
            print('NOT HOLDER usage-role', file=sys.stderr)
            return NOT_HOLDER
        if args.beat:
            rec['heartbeat'] = util.now_iso()
            _write(rec)
            print('BEAT usage-role')
            return 0
        try:
            os.remove(path())
        except FileNotFoundError:
            pass
        print('RELEASED usage-role')
        return 0
