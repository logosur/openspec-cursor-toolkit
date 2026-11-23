"""The watcher: waits for an event of the supervised sessions."""
import glob
import os
import time
import traceback

from . import (
    backlog, census, closable, cloud, human_turns, interrupted,
    lint, lock as lock_mod, machine_queue, projects, providers, transcripts,
    util, verdicts,
)


def registry_big_line(project, owner_id, limit):
    """REGISTRY_BIG line when `owner_id` holds the lock and its registry file is over `limit` bytes, else None.

    The lock's `registry` is a file, or a directory: then the newest SUPERVISOR-*.md (HISTORIAL-*.md are logs).
    """
    lock = lock_mod.Store().read(project['key'])
    registry = os.path.expanduser((lock or {}).get('registry') or '')
    if lock is None or lock.get('session_id') != owner_id or not registry:
        return None
    if os.path.isdir(registry):
        files = glob.glob(os.path.join(glob.escape(registry), 'SUPERVISOR-*.md'))
        registry = max(files, key=util.file_mtime, default='')
    name = os.path.basename(registry)
    try:
        size = os.stat(registry).st_size
    except OSError:
        return None
    if not name or name.startswith('HISTORIAL-') or size <= limit:
        return None
    stamp = name[len('SUPERVISOR-'):] if name.startswith('SUPERVISOR-') else name
    return (f'REGISTRY_BIG {registry} {size} (move closed history to HISTORIAL-{stamp} next to it; '
            f'keep only the state sections)')


def cmd_wait(args):
    """Wait (see wait_events); with --owner, an oversized registry adds one advisory line at the end."""
    code = wait_events(args)
    if args.owner:
        try:
            line = registry_big_line(projects.resolve(args.dir), args.owner, args.registry_max)
        except Exception:
            line = None  # advisory only: never changes how wait ends
        if line:
            print(line)
    return code


def hold_while_paused(project, interval):
    """While the developer keeps the project paused (optional `project-pause`), the watcher neither times out nor
    reports: it holds, so nothing wakes the supervisor. When the pause ends it prints RESUMED and returns True."""
    marker = providers.pause_of(project['checkout'])
    if not marker:
        return False
    while providers.pause_of(project['checkout']):
        time.sleep(max(5.0, float(interval or 30)))
    print(f'RESUMED {project["key"]} (pausa levantada; estaba en pausa desde {marker.get("paused_at")})')
    return True


# After the final batch the supervisor keeps its lock and waits on guard, so a project is never left unsupervised.
# Only what needs it wakes it: a turn ending or a status flip in one of a dozen sessions the developer drives would wake
# it hundreds of times a day.
GUARD_EVENTS = ('NEW', 'GONE', 'AWAITING', 'CRASH', 'HUNG', 'MODE', 'WAITING', 'MODELSTALL', 'HANDOFF', 'IDLE',
                'CLOSABLE', 'CUT', 'SUBAGENT_SILENT', 'REF', 'CLOUD', 'QUEUED', 'SLOTHELD', 'BACKLOG')


def wait_events(args):
    """Block until something worth waking the supervisor happens; print one line per event."""
    project = projects.resolve(args.dir)
    if hold_while_paused(project, args.interval):
        return 0
    cache = {}
    excluded = set(args.exclude or [])
    if args.owner:
        excluded.add(args.owner)
    refs = [x.strip() for x in (args.refs or '').split(',') if x.strip()]
    started = time.time()

    def everyone():
        return {r['id']: r for r in census.collect_sessions(project, False, cache)}

    def visible(rows):
        return {i: r for i, r in rows.items() if i not in excluded}

    def tick(value):
        return f'{value:g}'

    def driving(r, now):
        """True while the developer has written in this session within --away-after s (unknown counts as away, like
        the ask gate: a dialog there was only allowed after a successful scan)."""
        if args.away_after <= 0:
            return False
        try:
            return human_turns.human_seen_since(r['transcript'], now - args.away_after) is not None
        except TimeoutError:
            return False

    def levels(rows, now):
        """Conditions that hold until someone fixes them: (kind, subject) -> event line."""
        out = {}
        for sid, r in sorted(visible(rows).items()):
            if r['live'] and r.get('mode') and r['mode'] not in ('bypassPermissions', 'plan'):
                # a session the developer opened by hand is born in their default mode and stops at permission
                # prompts while nobody watches; the supervisor learns it (whether a mode may be raised is the
                # developer's choice). plan is a mode picked on purpose, so it is left alone
                out[('MODE', sid)] = f'MODE {sid} {r["mode"]}'
            if not r['live'] or not r.get('transcript'):
                continue
            recs = transcripts.conv_records(r['transcript'])
            hit = transcripts.waiting_on_human(recs, now)
            if hit and hit[1] > args.waiting_after and not driving(r, now):
                # a dialog in a session the developer is driving is for them, and they are in front of it; it
                # becomes WAITING once they have not written there for --away-after s
                out[('WAITING', sid)] = f'WAITING {sid} {hit[0]} {hit[1]}s'
            stall = transcripts.model_stall_age(recs, now) if r['status'] == 'busy' else None
            if stall is not None and stall > args.model_stall_after:
                subs = transcripts.session_files(r['cli'], r['cwd'])[1]
                if all(now - util.file_mtime(path) > args.model_stall_after for path in subs):
                    out[('MODELSTALL', sid)] = f'MODELSTALL {sid} {stall}s'
            if args.away_after > 0 and not hit and r['status'] != 'busy':
                # a closing message that hands work back to the developer («cuando me confirmes, sigo») leaves a
                # session idle, and prose is no WAITING; this level fires once the developer has not written there
                # for --away-after s, so a session they are driving is left alone while they are in front of it
                closing = transcripts.closing_text(recs)
                fragment = providers.handoff_fragment(closing) if closing else None
                if fragment:
                    try:
                        seen_input = human_turns.human_seen_since(r['transcript'], now - args.away_after)
                    except TimeoutError:
                        seen_input = now  # unknown: counted as present, so nothing fires on a guess
                    if seen_input is None:
                        out[('HANDOFF', sid)] = f'HANDOFF {sid} «{fragment}»'
                elif args.guard and not r.get('awaiting') and (r.get('idle_s') or 0) >= args.away_after:
                    # on guard TURN is filtered out, so a hand-back the patterns miss, or a session that simply
                    # stopped, would stay invisible until TIMEOUT. Once per idle stretch, without any pattern: idle_s
                    # counts the developer's messages too, so this is also --away-after s without their input
                    out[('IDLE', sid)] = f'IDLE {sid} {int(r["idle_s"])}s'
        owner_row = rows.get(args.owner) if args.owner else None
        if owner_row and owner_row.get('cli'):
            for path in transcripts.session_files(owner_row['cli'], owner_row['cwd'])[1]:
                silent = transcripts.subagent_silent_age(path, now)
                if silent is not None and silent > args.subagent_silent_after:
                    out[('SUBAGENT_SILENT', path)] = f'SUBAGENT_SILENT {os.path.basename(path)} {silent}s'
        return out

    def all_idle(after):
        if args.all_idle_after <= 0 or any(r['live'] and r['status'] == 'busy' for r in after.values()):
            return None
        idles = [r['idle_s'] for r in after.values() if r['idle_s'] is not None]
        since = max(started, time.time() - min(idles)) if idles else started
        quiet_for = time.time() - since
        if quiet_for < args.all_idle_after or providers.heavy_job_busy(project):
            return None
        return f'ALLIDLE {int(quiet_for)}s'

    def ref_target(name):
        """(repo dir, branch): in a workspace `<subdir>:<branch>` names a nested repo."""
        if project['kind'] == 'workspace' and ':' in name:
            sub, branch = name.split(':', 1)
            return os.path.join(project['checkout'], sub), branch
        return project['checkout'], name

    def heads():
        return {name: projects.git(['rev-parse', '--verify', '-q', 'refs/heads/' + ref_target(name)[1]], ref_target(name)[0])
                for name in refs}

    def skill_line():
        return lint.skill_changed_line(project, args.owner) if args.owner else None

    line = skill_line()  # a state to act on: reported at once, not only when it changes
    if line:
        print(line)
        return 0
    cut_now = []   # resumable cut sessions of the latest round (the same census as the closable cache)
    verdict_now = []  # closable sessions whose last message is «Sí, puedes cerrar» (same census)

    def closable_cache(rows):
        """Writes the Stop hook's cache; on guard also returns the CLOSABLE levels (F4b due: nothing else wakes a
        guard for a session that finished and stayed quiet 2 h). It also leaves the resumable cut sessions in `cut_now`
        for the CUT events: one census, one cache."""
        try:
            candidates, cuts = closable.write_closable_cache(project, args.owner, rows.values())
            cut_now[:] = [e for e in cuts if e['id'] not in excluded]
            verdict_now[:] = [e for e in candidates if e.get('verdict') and e['id'] not in excluded]
        except Exception:
            cut_now[:] = []
            verdict_now[:] = []
            return {}  # advisory for the Stop hook: never changes what wait reports
        if not args.guard:
            return {}
        return {('CLOSABLE', e['id']): f'CLOSABLE {e["id"]} {util.hours(e["idle_s"])}'
                for e in candidates if e['id'] not in excluded}

    deadline = time.monotonic() + args.timeout  # counts the first snapshot, which resolves every cwd once
    first = everyone()
    due = closable_cache(first) if args.owner else {}
    before = visible(first)
    # sessions already past the hung threshold when the wait starts are not reported
    quiet = {i for i, r in before.items() if r['idle_s'] is not None and r['idle_s'] >= args.hung_after}
    # same for every level condition (MODE, WAITING, MODELSTALL, HANDOFF, IDLE, CLOSABLE, SUBAGENT_SILENT) that is
    # already true now; a MODE already true is in the census (`sessions`, column mode=), and staying quiet here avoids
    # a wait that returns at once every round when a raise did not take
    quiet_levels = set(levels(first, time.time())) | set(due)
    heads_before = heads()
    last_beat = time.monotonic()
    polled = {'cloud': -1e9, 'heavy': -1e9, 'backlog': -1e9}

    def machine_events():
        """Cloud sessions of the project and its jobs in the machine queue, polled every few minutes and
        announced once per item (persisted), even when already true at the start of the wait."""
        out = []
        if not args.owner:
            return out
        if time.monotonic() - polled['cloud'] >= cloud.CLOUD_POLL_S:
            polled['cloud'] = time.monotonic()
            try:
                out += cloud.cloud_events(project)
            except Exception:
                util.hook_log('wait-errors.log', traceback.format_exc().rstrip())
        if args.guard and time.monotonic() - polled['backlog'] >= cloud.CLOUD_POLL_S:
            # a guard with documented work left is woken for it (a park that expired, a change that appeared)
            polled['backlog'] = time.monotonic()
            try:
                if not providers.pause_of(project.get('checkout')):
                    work, _ = backlog.backlog_state(project['key'], project['checkout'])
                    out += cloud.announce_once(project['key'], 'backlog',
                                         [(f'{w["id"]}:{w["digest"]}', f'BACKLOG {w["id"]} open={w["open"]} «{w["first"]}»')
                                          for w in work], backlog.BACKLOG_REANNOUNCE_S)
            except Exception:
                util.hook_log('wait-errors.log', traceback.format_exc().rstrip())
        if time.monotonic() - polled['heavy'] >= machine_queue.HEAVY_POLL_S:
            polled['heavy'] = time.monotonic()
            try:
                out += machine_queue.heavy_events(project, providers.heavy_job_state())
            except Exception:
                util.hook_log('wait-errors.log', traceback.format_exc().rstrip())
        return out
    ready = os.environ.get('SUPERVISOR_WAIT_READY')
    if ready:  # tests: the first snapshot is taken, so a change made from now on is an event
        open(ready, 'w').close()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f'TIMEOUT {tick(args.timeout)}s')
            return 0
        time.sleep(min(args.interval, remaining))
        if args.owner and time.monotonic() - last_beat >= args.beat_every:
            lock_mod.beat_owner(project, args.owner)
            last_beat = time.monotonic()
        line = skill_line()
        if line:
            print(line)
            return 0
        rows = everyone()
        due = closable_cache(rows) if args.owner else {}
        after = visible(rows)
        events = []
        for sid in sorted(after.keys() - before.keys()):
            events.append(f'NEW {sid}')
        for sid in sorted(before):
            old, new = before[sid], after.get(sid)
            if new is None or (old['live'] and not new['live']):
                events.append(f'GONE {sid}')
                continue
            if old['status'] and new['status'] and old['status'] != new['status']:
                events.append(f'STATUS {sid} {old["status"]}->{new["status"]}')
            if old['turns'] is not None and new['turns'] is not None and old['turns'] != new['turns']:
                events.append(f'TURN {sid} {old["turns"]}->{new["turns"]}')
            if new['awaiting'] and not old['awaiting']:
                events.append(f'AWAITING {sid}')
            if new['crashes'] > old['crashes']:
                events.append(f'CRASH {sid} {old["crashes"]}->{new["crashes"]}')
        for sid, r in sorted(after.items()):
            idle = r['idle_s']
            if idle is None or idle < args.hung_after:
                quiet.discard(sid)
            elif sid not in quiet and r['live'] and r['status'] == 'busy':
                events.append(f'HUNG {sid} idle_s={idle}')
        current = {**levels(rows, time.time()), **due}
        quiet_levels &= set(current)  # a condition that went away may fire again later
        events.extend(line for key, line in current.items() if key not in quiet_levels)
        if args.owner and cut_now:
            # not a level subject to quiet_levels: the supervisor re-arms right after a shared limit, when
            # every child is already cut, and that is exactly when it must hear about them. Once per (id, since).
            try:
                events.extend(interrupted.announce_cuts(project['key'], cut_now))
            except Exception:
                pass
        if args.owner and verdict_now:
            # a child that answered «Sí, puedes cerrar» is announced at once, in any phase and even when it
            # said so before the wait started (not a quiet level); once per (id, verdict time)
            try:
                said = {line.split(' ')[1] for line in verdicts.announce_verdicts(project['key'], verdict_now)}
                events = [e for e in events if not (e.startswith('CLOSABLE ') and e.split(' ')[1] in said)]
                events.extend(f'CLOSABLE {i} cierre-ok' for i in sorted(said))
            except Exception:
                pass
        line = None if args.guard else all_idle(after)
        if line:
            events.append(line)
        events.extend(machine_events())
        heads_now = heads()
        for name in refs:
            if heads_now[name] != heads_before[name]:
                events.append(f'REF {name} {(heads_before[name] or "-")[:8]}->{(heads_now[name] or "-")[:8]}')
        if args.guard:
            events = [e for e in events if e.split(' ', 1)[0] in GUARD_EVENTS]
        if events:
            print('\n'.join(events))
            return 0
