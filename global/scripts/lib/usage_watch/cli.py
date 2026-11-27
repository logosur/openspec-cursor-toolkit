"""Command line of usage-watch (design D7, D9, D11, D12, D13)."""
from __future__ import annotations

import argparse
import json
import sys

from . import collect as collect_mod
from . import config as C
from . import report, rules, store, timer

# Exit codes (design D13).
OK, USAGE, REFUSED, TOO_EARLY, NOT_HOLDER, NO_SUPERVISION = 0, 2, 3, 4, 5, 6


def cmd_collect(args, cfg, now):
    r = collect_mod.collect(cfg, now)
    print(f'collect: {r["calls"]} call record(s), {r["turns"]} turn record(s), {r["pruned_files"]} old file(s) pruned')
    return OK


def cmd_detect(args, cfg, now):
    added, refreshed = store.merge(cfg, rules.detect(cfg, now), now)
    print(f'detect: {len(added)} new finding(s), {len(refreshed)} refreshed')
    for fid in added:
        print(f'NEW {fid}')
    return OK


def cmd_status(args, cfg, now):
    s = report.status_data(cfg, now)
    print(json.dumps(s, indent=2, sort_keys=True) if args.json else report.status_line(s))
    return OK


def cmd_page(args, cfg, now):
    print(f'page: {report.write_page(cfg, now)}')
    return OK


def cmd_tick(args, cfg, now):
    collect_mod.collect(cfg, now)
    store.merge(cfg, rules.detect(cfg, now), now)
    report.write_page(cfg, now)
    return OK


def cmd_show(args, cfg, now):
    finding = store.read(cfg).get(args.id)
    if finding is None:
        print(f'usage-watch: no finding {args.id}', file=sys.stderr)
        return USAGE
    print(json.dumps(finding, indent=2, sort_keys=True) if args.json else report.show_text(finding))
    return OK


def cmd_list(args, cfg, now):
    found = report.list_findings(cfg, args.project, args.state, args.applier)
    if args.json:
        print(json.dumps(found, indent=2, sort_keys=True))
    else:
        for f in found:
            print(report.list_line(f))
    return OK


def cmd_timer(args, cfg, now):
    return timer.run(args.action, cfg, args.script)


def cmd_self_test(args, cfg, now):
    from . import selftest
    return selftest.run(args.script)


def _supervision(args) -> int | None:
    from . import role
    if role.available():
        return None
    print(role.missing_message(), file=sys.stderr)
    return NO_SUPERVISION


def cmd_ask(args, cfg, now):
    from . import flow
    return _supervision(args) or flow.ask(cfg, args.id, args.question, args.project, now)


def cmd_decide(args, cfg, now):
    from . import flow
    return _supervision(args) or flow.decide(cfg, args.id, now)


def cmd_apply(args, cfg, now):
    from . import flow
    return flow.apply(cfg, args.id, args.how, now)


def cmd_measure(args, cfg, now):
    from . import flow
    return flow.measure(cfg, args.id, now)


def cmd_wait(args, cfg, now):
    from . import watcher
    return watcher.wait(cfg, args.session, args.timeout, args.interval)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='usage-watch', description=(
        'Measure token usage from the local transcripts, detect usage far above normal, and turn each detection into '
        'a finding. Measuring commands write only to the state directory.'))
    p.add_argument('--now', help='simulated clock (ISO-8601 or epoch seconds); default USAGE_WATCH_NOW, else the clock')
    sub = p.add_subparsers(dest='cmd', required=True, metavar='COMMAND')
    s = sub.add_parser('collect', help='count new responses in the transcripts (incremental)')
    s.set_defaults(func=cmd_collect)
    s = sub.add_parser('detect', help='run the detection rules and store new findings')
    s.set_defaults(func=cmd_detect)
    s = sub.add_parser('status', help="one line: the week's pace and the findings per state")
    s.add_argument('--json', action='store_true')
    s.set_defaults(func=cmd_status)
    s = sub.add_parser('page', help='write the self-refreshing HTML page')
    s.set_defaults(func=cmd_page)
    s = sub.add_parser('tick', help='collect, detect and page (what the timer runs)')
    s.set_defaults(func=cmd_tick)
    s = sub.add_parser('show', help='one finding with the transcript locations that back it')
    s.add_argument('id')
    s.add_argument('--json', action='store_true')
    s.set_defaults(func=cmd_show)
    s = sub.add_parser('list', help='findings, filtered')
    s.add_argument('--project')
    s.add_argument('--state', choices=store.STATES)
    s.add_argument('--applier', choices=('usage-role', 'project-supervisor'))
    s.add_argument('--json', action='store_true')
    s.set_defaults(func=cmd_list)
    s = sub.add_parser('timer', help='systemd --user timer that runs tick: print (writes nothing), install, uninstall, status')
    s.add_argument('action', choices=('print', 'install', 'uninstall', 'status'))
    s.set_defaults(func=cmd_timer)
    s = sub.add_parser('self-test', help='check the counting and every rule on throwaway data')
    s.set_defaults(func=cmd_self_test)
    s = sub.add_parser('ask', help='register a new finding as a question in ask-queue (once)')
    s.add_argument('id')
    s.add_argument('--question', help='the question for the developer; authorize_hint is appended')
    s.add_argument('--project', help='queue to use only when the finding has no supervised project and the usage '
                   'role has no home project')
    s.set_defaults(func=cmd_ask)
    s = sub.add_parser('decide', help="move an asked finding by its queue item's answer (no outcome argument)")
    s.add_argument('id')
    s.set_defaults(func=cmd_decide)
    s = sub.add_parser('apply', help='apply an authorised finding (the single apply point)')
    s.add_argument('id')
    s.add_argument('--how', help='for a note finding: what was done')
    s.set_defaults(func=cmd_apply)
    s = sub.add_parser('measure', help="record the rule's metric before and after an applied finding")
    s.add_argument('id')
    s.set_defaults(func=cmd_measure)
    s = sub.add_parser('wait', help='the usage role watcher: exits on a new finding or an answer')
    s.add_argument('--session', help='the usage role holder (app or CLI id)')
    s.add_argument('--timeout', type=float, default=0, help='seconds; 0 (default) never times out')
    s.add_argument('--interval', type=float, default=30)
    s.set_defaults(func=cmd_wait)
    return p


def main(argv=None, script: str = 'usage-watch') -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.script = script
    cfg = C.load()
    now = C.now(args.now)
    return args.func(args, cfg, now)
