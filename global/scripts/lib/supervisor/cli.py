"""The command line."""
import argparse
import sys

from . import (
    backlog, census, closable, closing, cloud, hook as hook_mod,
    lint, lock as lock_mod, projects, revival, settings, titles, usage_role, watch,
    watchdog, workmode,
)


# ---------------------------------------------------------------- cli

def build_parser():
    parser = argparse.ArgumentParser(prog='supervisor-lock', description='One session supervisor per project.')
    sub = parser.add_subparsers(dest='cmd', required=True)

    def add(name, func, session=False, json_out=False, directory=True):
        p = sub.add_parser(name)
        if directory:
            p.add_argument('--dir', default=None)
        if session:
            p.add_argument('--session', required=True)
        if json_out:
            p.add_argument('--json', action='store_true')
        p.set_defaults(func=func)
        return p

    add('project', projects.cmd_project, json_out=True)
    add('registry-dir', projects.cmd_registry_dir)
    for name, func in (('acquire', lock_mod.cmd_acquire), ('reclaim', lock_mod.cmd_reclaim)):
        p = add(name, func, session=True)
        p.add_argument('--title', help='defaults to the supervisor title of the project (config `supervisor_session_title`)')
        p.add_argument('--registry')
        if name == 'reclaim':
            p.add_argument('--from', dest='from_id', required=True)
    p = add('beat', lock_mod.cmd_beat, session=True)
    p.add_argument('--state', choices=['running', 'paused'],
                   help='paused only with --third-party, or for the usage limit while the account has no usage; a paused '
                        'beat without --third-party while the account has usage is refused (exit 9) and the state stays')
    p.add_argument('--third-party', metavar='WHAT', help='with --state paused: what is left waits on a third party: what and on whom')
    p.add_argument('--phase')
    p.add_argument('--round', type=int)
    p.add_argument('--mailbox', metavar='LOCAL_ID', help='local id of the question mailbox session')
    p.add_argument('--skill-seen', action='store_true', help='record that the current skill file has been read; refused (exit 8) unless the session\'s own '
                   'transcript shows a load of the skill (Skill tool or slash command) after the newest update')
    p.add_argument('--closer', metavar='LOCAL_ID', help='local id of the closing session (verifies, closes and archives)')
    p.add_argument('--title', help="change the lock's title (the owner's); refused when it looks like supervisor-lock output")
    p.add_argument('--no-work', metavar='WHY', help="on guard: a message of the developer's neither asks for nor implies work, and why")
    p = add('release', lock_mod.cmd_release, session=True)
    p.add_argument('--verdict')
    p.add_argument('--force-close', metavar='REASON')
    p.add_argument('--open-ok', metavar='REASON', help='release although other sessions of the project are still open')
    p = add('open', lock_mod.cmd_open, json_out=True)
    p.add_argument('--session', help='the session that asks, as `status` takes it; the list is the same, because '
                   'the supervisor, its questions session and its closing session are always left out')
    add('closable', closable.cmd_closable, json_out=True)
    p = add('hold', closable.cmd_hold, session=True)
    p.add_argument('--target', required=True, metavar='LOCAL_ID', help='the finished session to leave open for now')
    p.add_argument('--reason', help='the written rule or fact that forbids closing it now')
    p.add_argument('--hours', type=float, default=closable.HOLD_DEFAULT_H, help=f'expiry, at most {closable.HOLD_MAX_H}')
    p.add_argument('--clear', action='store_true', help='drop the hold')
    add('cloud', cloud.cmd_cloud, json_out=True)
    p = add('cloud-archive', cloud.cmd_cloud_archive, session=True)
    p.add_argument('--target', required=True, metavar='CLOUD_ID', help='cse_… or session_… of a cloud session of the project')
    p.add_argument('--reason', help='what was checked: its branch pushed or merged, the project no longer needs it')
    p.add_argument('--force-working', action='store_true', help='archive although it is working (with a written reason)')
    p = add('cloud-send', cloud.cmd_cloud_send, session=True)
    p.add_argument('--target', required=True, metavar='CLOUD_ID')
    p.add_argument('--text', required=True)
    p = add('status', lock_mod.cmd_status, json_out=True)
    p.add_argument('--session', help='the session that asks: its own live lock reads MINE instead of HELD')
    p = add('backlog', backlog.cmd_backlog, json_out=True)
    p.add_argument('--session', help='local id of the supervisor (required with --park / --unpark)')
    p.add_argument('--park', metavar='CHANGE', help='a change with open tasks that no session can finish now')
    p.add_argument('--as', dest='kind', choices=backlog.BACKLOG_KINDS)
    p.add_argument('--why', help='what is missing, who it depends on and what was checked')
    p.add_argument('--hours', type=float, default=None,
                   help=f'expiry: {backlog.BACKLOG_PARK_H} by default, {backlog.BACKLOG_PARK_MAX_H} for limite-duro and protegido (the maximum)')
    p.add_argument('--unpark', metavar='CHANGE')
    add('skill-lint', lint.cmd_skill_lint, directory=False)
    p = add('wait-closer', closing.cmd_wait_closer, session=True)
    p.add_argument('--timeout', type=float, default=1800)
    p.add_argument('--interval', type=float, default=closing.CLOSER_POLL_S)
    p = add('mode', workmode.cmd_mode)
    p.add_argument('--set', choices=workmode.WORK_MODES, help="switch the project work mode (only on the developer's order)")
    p.add_argument('--order', help="the developer's words, quoted, that ask for the mode (required with --set)")
    p.add_argument('--session', help='local id of the session that records it')
    p.add_argument('--get', action='store_true', help='print only the mode word')
    add('list', lock_mod.cmd_list, json_out=True)
    p = add('usage-role', usage_role.cmd_usage_role, session=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--claim', action='store_true', help='take the machine-wide usage role (RESUMED for the holder)')
    g.add_argument('--beat', action='store_true', help="refresh the holder's heartbeat")
    g.add_argument('--release', action='store_true', help='drop the role (the holder only)')
    p.add_argument('--from', dest='from_id', help='with --claim: the stale holder to take the role over from')
    p.add_argument('--title')
    p = add('sessions', census.cmd_sessions, json_out=True)
    p.add_argument('--all', action='store_true', help='also list CLI-only records whose process is dead')
    p = add('wait', watch.cmd_wait)
    p.add_argument('--owner', help='local id of the supervisor: excluded, and its lock heartbeat is refreshed')
    p.add_argument('--exclude', action='append', default=[])
    p.add_argument('--timeout', type=float, default=600)
    p.add_argument('--hung-after', type=float, default=1200)
    p.add_argument('--interval', type=float, default=15)
    p.add_argument('--waiting-after', type=float, default=180)
    p.add_argument('--model-stall-after', type=float, default=600)
    p.add_argument('--all-idle-after', type=float, default=900, help='0 disables ALLIDLE')
    p.add_argument('--subagent-silent-after', type=float, default=1200)
    p.add_argument('--away-after', '--handoff-after', dest='away_after', type=float, default=settings.PRESENCE_MIN * 60,
                   help="seconds without the developer's input after which a session they were driving counts as left: its dialog "
                        'becomes WAITING, a closing message that hands work back becomes HANDOFF and, on --guard, any '
                        'other stop becomes IDLE; 0 disables the three (WAITING then ignores presence)')
    p.add_argument('--guard', action='store_true',
                   help='guard after the final batch: report only ' + ' '.join(watch.GUARD_EVENTS) + ' (no TURN, STATUS, ALLIDLE)')
    p.add_argument('--refs', help='comma list of local branches whose commit is watched (workspace: subdir:branch)')
    # the registry is re-read after every compaction, and a supervisor in the desktop app keeps only ~10-25k tokens of
    # room after compacting: a registry over ~20 KB eats most of it
    p.add_argument('--registry-max', type=int, default=20000, help='bytes; --owner adds a REGISTRY_BIG line above it')
    p.add_argument('--beat-every', type=float, default=60, help=argparse.SUPPRESS)
    p = add('watchdog', watchdog.cmd_watchdog_with_nudge, directory=False)
    p.add_argument('--notify', action='store_true')
    p.add_argument('--nudge', action='store_true', help='also wake stopped sessions (question unanswered, usage limit renewed)')
    p.add_argument('--dead-after', type=float, default=600)
    p.add_argument('--stalled-after', type=float, default=revival.STALLED_AFTER_S,
                   help='wake a live, idle supervisor (running, not on guard) silent this long, when the account has usage')
    p.add_argument('--stale-after', type=float, default=2700)
    p.add_argument('--realert-after', type=float, default=0)
    p = add('titles', titles.cmd_titles, directory=False)
    p.add_argument('--fix', action='store_true', help="rewrite the locks' titles and rename the Remote Control copies "
                   '(the local sessions are renamed by the sessions themselves, with the app tool)')
    p.add_argument('--session', metavar='LOCAL_ID', help='only the project of this supervisor, questions or closing session')
    p = add('revive', revival.cmd_revive, json_out=True, directory=False)
    p.add_argument('--plan', action='store_true', help='(default) list the dead supervisors to wake now')
    p.add_argument('--sent', metavar='LOCAL_ID', help='record the delivery of a revive message')
    p.add_argument('--delivery', help='delivered | queued | error, with --sent')
    p.add_argument('--dead-after', type=float, default=600)
    p.add_argument('--stalled-after', type=float, default=revival.STALLED_AFTER_S,
                   help='wake a live, idle supervisor (running, not on guard) silent this long, when the account has usage')
    add('hook', hook_mod.cmd_hook, directory=False)
    add('self-test', run_self_test)
    return parser


def main():
    args = build_parser().parse_args()
    sys.exit(args.func(args))


def run_self_test(args):
    from . import selftest  # only here: the hook must not pay for it

    return selftest.cmd_self_test(args)
