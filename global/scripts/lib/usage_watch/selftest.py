"""`usage-watch self-test`: the counting and every rule's firing and healthy case, in a throwaway home; with the
supervision scripts next to this one (ask-queue, supervisor-lock), also the sub-supervision role: the walk of a finding,
the refused transitions (an untrusted answer, a hand-edited store), the ticket gate and the watcher.

Nothing outside its own temporary directory is read or written: HOME and every path variable point inside it while it
runs, and the directory is removed at the end. One line per failed check; exit 0 only when none failed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import collect as collect_mod
from . import config as C
from . import rules, scenarios
from .data import Data
from .fixtures import Home

NOW = C.parse_time('2026-01-15T12:00:00Z')
ENV_KEYS = ('HOME', 'CLAUDE_TOOLKIT_CONFIG_DIR', 'SUPERVISOR_LOCK_HOME', 'ASK_QUEUE_DIR', 'CLAUDE_TOOLKIT_OVERRIDE',
            'USAGE_WATCH_NOW', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', 'CLAUDE_CODE_SESSION_ID',
            'CLAUDE_CODE_HOST_SESSION_ID')


class Sandbox:
    """A Home with os.environ pointed at it for the duration of the block."""

    def __init__(self, root: str):
        self.home = Home(root)
        self.saved = {}

    def __enter__(self) -> Home:
        self.saved = {k: os.environ.get(k) for k in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update({k: v for k, v in self.home.env(base={}).items()})
        return self.home

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


def detect_rule(root: str, builder, overrides: dict, rule: str) -> list[dict]:
    with Sandbox(root) as home:
        home.config(**overrides)
        builder(home, NOW)
        cfg = C.load()
        collect_mod.collect(cfg, NOW)
        return [c for c in rules.detect(cfg, NOW) if c['rule'] == rule]


def counting_checks(root: str) -> list[str]:
    fails = []
    with Sandbox(root) as home:
        tr = home.transcript('s-count')
        tr.user(NOW - 600, 'go')
        tr.assistant(NOW - 500, msg_id='m1', out=1)
        tr.assistant(NOW - 499, msg_id='m1', out=2)
        tr.assistant(NOW - 498, msg_id='m1', out=3)
        tr.assistant(NOW - 400, msg_id='m2', cw5=50, cw1h=100)
        tr.assistant(NOW - 300, msg_id='m3', iterations=[
            {'type': 'message', 'input_tokens': 7, 'output_tokens': 1},
            {'type': 'advisor_message', 'model': 'model-adv', 'input_tokens': 40, 'output_tokens': 4}])
        tr.raw('{not json')
        home.transcript('s-count-resumed').assistant(NOW - 200, msg_id='m2', cw5=50, cw1h=100)
        cfg = C.load()
        collect_mod.collect(cfg, NOW)
        collect_mod.collect(cfg, NOW)
        d = Data(cfg, NOW)
        by_id = {c['id']: c for c in d.calls}
        if len([c for c in d.calls if c['id'] == 'm1']) != 1 or by_id.get('m1', {}).get('out') != 3:
            fails.append('counting: several lines of one response count once, with the last usage')
        if (by_id.get('m2') or {}).get('cw1h') != 100 or (by_id.get('m2') or {}).get('cw5') != 50:
            fails.append('counting: cache writes split into 5 minutes and 1 hour')
        if len(d.calls) != 4:
            fails.append(f'counting: same id in two transcripts and two runs counted once (got {len(d.calls)} calls)')
        adv = [c for c in d.calls if c['kind'] == 'advisor']
        if len(adv) != 1 or adv[0]['model'] != 'model-adv' or (by_id.get('m3') or {}).get('in') != 7:
            fails.append('counting: advisor iterations split from the main call')
        if collect_mod.skipped_lines(cfg) != 1:
            fails.append('counting: a broken line is skipped and counted')
    return fails


ROLE_APP, ROLE_CLI, DEV = 'local_role', 'cli-role', 'local_dev'
H = 3600


def merge_in(root: str, build, steps) -> list:
    """Build fixtures in a sandbox, detect once, then run each (floor, mutation) step through `store.merge`; returns the
    stored findings after every step."""
    from . import store
    out = []
    with Sandbox(root) as home:
        build(home, NOW)
        cfg = C.load()
        collect_mod.collect(cfg, NOW)
        plan = rules.plan(cfg, NOW)
        for floor, mutate in steps:
            if mutate:
                found = store.read(cfg)
                mutate(found, plan)
                store.write(cfg, found)
            store.merge(cfg, plan['candidates'], NOW, floor=plan['floor'] if floor is None else floor,
                        retire=plan['retire'])
            out.append(store.read(cfg))
        out.append(plan)
    return out


def selection_checks(root: str) -> tuple[list[str], int]:
    """What reaches the developer: the materiality floor, grouping, live sessions and the pace duplicate."""
    from . import store
    fails = []

    def check(name, ok):
        if not ok:
            fails.append(name)

    def sub(name):
        return os.path.join(root, name)

    # grouping: fifty one-run routine sessions give one grouped note, never fifty; healthy gives none
    found = detect_rule(sub('routines'), scenarios.routines_fire, {}, 'role-model')
    check('grouping: fifty one-run routine sessions give exactly one finding',
          len(found) == 1 and found[0]['scope']['kind'] == 'project' and found[0]['evidence']['sessions'] == 50
          and len(found[0]['evidence']['top_sessions']) == 5)
    check('grouping: the grouped finding is a note for the project supervisor',
          bool(found) and found[0]['applier'] == 'project-supervisor' and found[0]['proposal']['kind'] == 'note'
          and found[0]['target_app_id'] is None)
    check('grouping: healthy routines raise nothing',
          not detect_rule(sub('routines-ok'), scenarios.routines_healthy, {}, 'role-model'))

    # a session-model proposal needs a live session
    def kinds(name, **kw):
        found = detect_rule(sub(name), lambda h, n: scenarios.automation_session(h, n, **kw), {}, 'expensive-automation')
        return [(c['scope']['kind'], c['proposal']['kind']) for c in found]
    check('live session: an open, active session keeps its session-model proposal',
          kinds('live') == [('session', 'session-model')])
    check('live session: a closed session never yields a session-model proposal',
          kinds('closed', archived=True) == [('project', 'note')])
    quiet = detect_rule(sub('quiet'), lambda h, n: scenarios.automation_session(h, n, last=n - 10 * H),
                        {'session_active_window_h': 6}, 'expensive-automation')
    check('live session: an open session quiet for the window goes through grouping',
          [(c['scope']['kind'], c['proposal']['kind']) for c in quiet] == [('project', 'note')])

    # at least group_min_sessions live sessions fold, fewer do not
    three = detect_rule(sub('three'), lambda h, n: scenarios.large_sessions(h, n, 3), {}, 'large-context')
    two = detect_rule(sub('two'), lambda h, n: scenarios.large_sessions(h, n, 2), {}, 'large-context')
    check('grouping: three live sessions of one rule and project fold into one',
          [c['scope']['kind'] for c in three] == ['project'])
    check('grouping: two live sessions stay separate', [c['scope']['kind'] for c in two] == ['session', 'session'])

    # the pace duplicate
    pace_cfg = dict(scenarios.CASES[7][3])
    pace = detect_rule(sub('pace-closed'), scenarios.pace_fire, pace_cfg, 'pace')
    check('pace: a session that is most of its project keeps only the project finding when not live',
          [c['scope']['kind'] for c in pace] == ['project'])

    def live_pace(home, now):
        scenarios.pace_fire(home, now)
        home.live('s-pace')
    pace = detect_rule(sub('pace-live'), live_pace, pace_cfg, 'pace')
    check('pace: ... and only the session finding when it is live', [c['scope']['kind'] for c in pace] == ['session'])

    # the floor: exactly at it, just under it, back above it, and never over a finding already asked
    def saving_of(name):
        return detect_rule(sub(name), scenarios.large_fire, {}, 'large-context')[0]['saving_units_per_day']
    s = saving_of('floor-probe')
    at = merge_in(sub('floor-at'), scenarios.large_fire, [(s, None)])[0]
    under = merge_in(sub('floor-under'), scenarios.large_fire, [(s + 0.0001, None)])[0]
    check('floor: a finding exactly at the floor is new', [f['state'] for f in at.values()] == ['new'])
    check('floor: a finding just under the floor is minor', [f['state'] for f in under.values()] == ['minor'])

    def ask(found, plan):
        for f in found.values():
            f['state'] = 'asked'
    steps = merge_in(sub('floor-moves'), scenarios.large_fire,
                     [(s + 1, None), (0, None), (s + 1, None), (0, ask), (s + 1, None)])
    states = [[f['state'] for f in found.values()] for found in steps[:-1]]
    check('floor: re-evaluated on each detect (minor, new, minor again)', states[:3] == [['minor'], ['new'], ['minor']])
    check('floor: a finding already asked is never touched by it', states[3:] == [['asked'], ['asked']])

    # an old file: new session findings are folded or made minor, asked ones stay
    def old_file(home, now):
        scenarios.routines_fire(home, now)
        cfg = C.load()
        collect_mod.collect(cfg, now)
        det = rules.Detector(cfg, now)
        det.group = lambda found: found
        old = {c['id']: dict(c, state='new', first_seen='x', last_seen='x', history=[]) for c in det.run()
               if c['rule'] == 'role-model'}
        first = sorted(old)[0]
        old[first].update(state='asked', queue={'project': 'p', 'id': 'q1'})
        store.write(cfg, old)
        first_id['id'] = first

    first_id = {}
    migrated = merge_in(sub('old-file'), old_file, [(None, None)])
    after, plan = migrated[0], migrated[-1]
    first = first_id['id']
    group = [c['id'] for c in plan['candidates'] if c['rule'] == 'role-model']
    others = [f for fid, f in after.items() if f['rule'] == 'role-model' and fid not in group and fid != first]
    check('old file: the asked finding is untouched and every other new session finding is folded',
          after[first]['state'] == 'asked' and after[first]['queue'] == {'project': 'p', 'id': 'q1'}
          and len(others) == 49 and all(f['state'] == 'minor' and f.get('folded_into') in group for f in others))
    print('selection checks: grouping, live sessions, pace duplicate, floor, old file (15 checks)')
    return fails, 15


def cap_checks(root: str, script: str) -> tuple[list[str], int]:
    """`wait` holds FINDING back with `max_open_questions` unanswered and frees one slot per answer."""
    here = os.path.dirname(os.path.realpath(script)) if script else ''
    tools = {n: os.path.join(here, n) for n in ('ask-queue', 'supervisor-lock')}
    if not all(os.path.isfile(p) for p in tools.values()):
        return [], 0
    from .store import read as read_store, write as write_store
    fails = []

    def check(name, ok):
        if not ok:
            fails.append(name)

    with Sandbox(root) as home:
        bin_dir = os.path.join(home.root, '.claude', 'scripts')
        os.makedirs(bin_dir, exist_ok=True)
        for name, path in tools.items():
            os.symlink(path, os.path.join(bin_dir, name))
        home_repo = home.git_repo('home-proj')
        home.usage_role(ROLE_APP, ROLE_CLI, home_project=home_repo)

        def call(*args, env=None, tool=None):
            e = home.env(now=NOW)
            e.update(env if env is not None else {'CLAUDE_CODE_SESSION_ID': ROLE_CLI,
                                                  'CLAUDE_CODE_HOST_SESSION_ID': ROLE_APP})
            argv = [tools[tool]] if tool else [os.path.realpath(script)]
            return subprocess.run([sys.executable, *argv, *args], capture_output=True, text=True, env=e, timeout=120)

        ids = [f'large-context-{i:010d}' for i in range(7)]
        savings = [5, 1, 9, 2, 8, 3, 7]
        cfg = C.load()
        write_store(cfg, {fid: {
            'id': fid, 'rule': 'large-context', 'scope': {'kind': 'session', 'id': f's{i}'}, 'project': 'p',
            'project_root': None, 'role': 'worker', 'evidence': {'locations': []}, 'saving_units_per_day': savings[i],
            'proposal': {'kind': 'note', 'text': 't'}, 'applier': 'project-supervisor', 'undo': 'u',
            'target_app_id': None, 'state': 'new', 'first_seen': 'x', 'last_seen': 'x', 'history': []}
            for i, fid in enumerate(ids)})
        for fid in ids[:4]:
            call('ask', fid, '--question', 'Look at it?')
        r = call('wait', '--session', ROLE_APP, '--timeout', '1', '--interval', '0.1')
        check('cap: four unanswered questions hold every FINDING back', r.stdout == 'TIMEOUT 1s\n')
        qid = (read_store(cfg)[ids[0]].get('queue') or {}).get('id')
        call('answer', qid, '--text', 'no', tool='ask-queue', env={'CLAUDE_CODE_HOST_SESSION_ID': 'local_dev'})
        r = call('wait', '--session', ROLE_APP, '--timeout', '3', '--interval', '0.1')
        check('cap: one answer frees one slot, for the largest saving, and the ANSWER is not held back',
              r.stdout.splitlines() == [f'FINDING {ids[4]} large-context session:s4', f'ANSWER {ids[0]}'])
    print('cap checks: hold back at the cap, one slot per answer (2 checks)')
    return fails, 2


def role_checks(root: str, script: str) -> tuple[list[str], int]:
    """(failures, check groups) of the sub-supervision role. Needs ask-queue and supervisor-lock next to `script`."""
    here = os.path.dirname(os.path.realpath(script)) if script else ''
    tools = {n: os.path.join(here, n) for n in ('ask-queue', 'supervisor-lock')}
    if not all(os.path.isfile(p) for p in tools.values()):
        print('skip role checks: the supervision scripts are not installed next to usage-watch')
        return [], 0
    from . import gate
    from .store import read as read_store, write as write_store
    fails = []

    def check(name, ok):
        if not ok:
            fails.append(name)

    with Sandbox(root) as home:
        bin_dir = os.path.join(home.root, '.claude', 'scripts')
        os.makedirs(bin_dir, exist_ok=True)
        for name, path in tools.items():
            os.symlink(path, os.path.join(bin_dir, name))
        home_repo = home.git_repo('home-proj')
        home.usage_role(ROLE_APP, ROLE_CLI, home_project=home_repo)

        def call(*args, now=NOW, env=None, tool=None):
            e = home.env(now=now)
            e.update(env if env is not None else {'CLAUDE_CODE_SESSION_ID': ROLE_CLI, 'CLAUDE_CODE_HOST_SESSION_ID': ROLE_APP})
            argv = [tools[tool]] if tool else [os.path.realpath(script)]
            return subprocess.run([sys.executable, *argv, *args], capture_output=True, text=True, env=e, timeout=120)

        def findings():
            return read_store(C.load())

        def only(rule):
            ids = [k for k, f in findings().items() if f['rule'] == rule]
            return ids[0] if len(ids) == 1 else None

        def answer(fid, text, by):
            qid = (findings()[fid].get('queue') or {}).get('id')
            call('answer', qid, '--text', text, tool='ask-queue', env={'CLAUDE_CODE_HOST_SESSION_ID': by})

        # the walk: new -> asked -> authorized -> applied (a one-use ticket) -> measured
        scenarios.role_fire(home, NOW)
        call('tick')
        fid = only('role-model')
        steps = [call('ask', fid, '--question', 'Run it on the cheaper model?').returncode]
        answer(fid, 'apply', DEV)
        steps += [call('decide', fid).returncode, call('apply', fid).returncode,
                  call('measure', fid, now=NOW + 25 * H).returncode]
        states = [h['state'] for h in findings()[fid]['history']]
        check('role walk: new, asked, authorized, applied (ticket), measured',
              steps == [0, 0, 0, 0] and states == ['new', 'asked', 'authorized', 'applied', 'measured'])

        # refused: an answer recorded by the role itself is not trusted
        tr = home.transcript('s-ctx')
        tr.user(NOW - 3 * H, 'go')
        for i in range(25):
            tr.assistant(NOW - 3 * H + i * 60, cr=200000)
        call('tick')
        nid = only('large-context')
        call('ask', nid, '--question', 'Compact it?')
        answer(nid, 'apply', ROLE_APP)
        r = call('decide', nid)
        check('role refusal: an untrusted answer (the role answering itself) moves nothing',
              r.returncode == 3 and findings()[nid]['state'] == 'asked')

        # refused: a store edited by hand to authorized, with the queue item not authorising
        found = findings()
        found[nid].update(state='authorized', answer={'text': 'apply', 'by': DEV})
        write_store(C.load(), found)
        r = call('apply', nid, '--how', 'edited by hand')
        check('role refusal: a hand-edited store (authorized without the queue) applies nothing',
              r.returncode == 3 and findings()[nid]['state'] == 'authorized')

        # the ticket gate: the role passes once with the ticket apply issued, never without one
        cfg = C.load()
        cheap = cfg['cheap_model']

        def gate_call(caller=ROLE_CLI, model=cheap):
            return gate.check({'tool_name': 'mcp__ccd_session_mgmt__set_session_model', 'session_id': caller,
                               'tool_input': {'session_id': 'local_box', 'model': model}}, cfg, NOW)
        check('ticket gate: a value no ticket names is denied for the role', gate_call(model='other') is not None)
        check('ticket gate: the ticket from apply lets one call through', gate_call() is None)
        check('ticket gate: the same ticket does not open a second call', gate_call() is not None)
        check('ticket gate: another session is left alone', gate_call(caller='cli-other', model='other') is None)

        # the watcher: silence, FINDING, ANSWER, NOT HOLDER
        call('wait', '--session', ROLE_APP, '--timeout', '1', '--interval', '0.1')   # announce what is there
        r = call('wait', '--session', ROLE_APP, '--timeout', '1', '--interval', '0.1')
        check('wait: nothing new prints only TIMEOUT', r.returncode == 0 and r.stdout == 'TIMEOUT 1s\n')
        scenarios.idle_fire(home, NOW)
        call('tick')
        iid = only('idle-rewrite')
        r = call('wait', '--session', ROLE_APP, '--timeout', '5', '--interval', '0.1')
        check('wait: a new finding prints FINDING once',
              r.returncode == 0 and r.stdout.startswith(f'FINDING {iid} idle-rewrite ')
              and call('wait', '--session', ROLE_APP, '--timeout', '1').stdout == 'TIMEOUT 1s\n')
        call('ask', iid, '--question', 'Look at it?')
        answer(iid, 'no', DEV)
        r = call('wait', '--session', ROLE_APP, '--timeout', '5', '--interval', '0.1')
        check('wait: an answered question prints ANSWER once',
              r.returncode == 0 and r.stdout == f'ANSWER {iid}\n'
              and call('wait', '--session', ROLE_APP, '--timeout', '1').stdout == 'TIMEOUT 1s\n')
        os.remove(os.path.join(home.supervisor, 'usage-role.json'))
        call('usage-role', '--claim', '--session', ROLE_APP, '--dir', home_repo, tool='supervisor-lock',
             env={'CLAUDE_CODE_SESSION_ID': ROLE_CLI})
        r = call('wait', '--session', 'local_other', '--timeout', '1')
        check('wait: another live holder gives NOT HOLDER and exit 5', r.returncode == 5 and 'NOT HOLDER' in r.stderr)
        held = json.loads(call('list', '--json', tool='supervisor-lock').stdout or '{}').get('usage_role') or {}
        check('wait: the usage role is recorded by supervisor-lock', held.get('session_id') == ROLE_APP)
    print('role checks: walk, untrusted answer, hand-edited store, ticket gate, wait (14 checks)')
    return fails, 14


def run(script: str = '') -> int:
    tmp = tempfile.mkdtemp(prefix='usage-watch-selftest-')
    fails, checks = [], 0
    try:
        checks += 1
        fails += counting_checks(os.path.join(tmp, 'counting'))
        for rule, fire, healthy, overrides in scenarios.CASES:
            checks += 2
            if not detect_rule(os.path.join(tmp, rule + '-fire'), fire, overrides, rule):
                fails.append(f'rule {rule}: the firing case raised no finding')
            if detect_rule(os.path.join(tmp, rule + '-healthy'), healthy, overrides, rule):
                fails.append(f'rule {rule}: the healthy case raised a finding')
        sel_fails, sel_groups = selection_checks(os.path.join(tmp, 'selection'))
        fails += sel_fails
        checks += sel_groups
        role_fails, role_groups = role_checks(os.path.join(tmp, 'role'), script)
        fails += role_fails
        checks += role_groups
        cap_fails, cap_groups = cap_checks(os.path.join(tmp, 'cap'), script)
        fails += cap_fails
        checks += cap_groups
    except Exception as exc:  # a crash is a failed self-test, reported, never a traceback for the caller
        fails.append(f'self-test crashed: {type(exc).__name__}: {exc}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for line in fails:
        print(f'FAIL {line}')
    print(f'usage-watch self-test: {checks} check group(s), {len(fails)} failure(s)')
    return 1 if fails else 0
