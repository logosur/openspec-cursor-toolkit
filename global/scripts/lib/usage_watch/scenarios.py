"""One firing case and one healthy case per rule, built on a synthetic home (spec scenarios of each rule).

Shared by `self-test` and the unit tests. Each entry: (rule, kind, config overrides, builder). A builder writes the
fixtures for a clock `now`; the expectation is that `detect` raises a finding of `rule` for `fire` and none for
`healthy`.
"""
from __future__ import annotations

from .fixtures import Home

EXPENSIVE = 'model-opus-x'
CHEAP = 'model-small'
H = 3600
UNIT_PER_INPUT_TOKEN = {'.': [1000000, 0, 0, 0, 0]}   # 1 unit per input token: readable pace figures


def loop_fire(home: Home, now):
    tr = home.transcript('s-loop')
    for i in range(6):
        tr.turn(now - 6 * H + i * 600, text='check', origin='task-notification', end_text=f'Nothing new ({i + 3}), waiting.')


def loop_healthy(home: Home, now):
    tr = home.transcript('s-loop')
    for i in range(8):
        t = now - 2 * H + i * 200
        tr.user(t, f'step {i}')
        tr.assistant(t + 1, tools=[('Read', {'file_path': f'/tmp/f{i}'})], text=f'Answer number {i} about {"abcdefgh"[i]}')


def empty_fire(home: Home, now):
    tr = home.transcript('s-wake')
    for i in range(30):
        tr.turn(now - 23 * H + i * 2700, text='notice', origin='task-notification', out=200)


def empty_healthy(home: Home, now):
    tr = home.transcript('s-wake')
    for i in range(30):
        tr.turn(now - 23 * H + i * 2700, text=f'question {i}', out=200)


def _questions_session(home: Home, model, now):
    repo = home.git_repo('proj-q')
    home.lock('proj-q', repo, 'local_sup', mailbox='local_box')
    home.app_record('local_box', 'cli-box', repo, title='questions')
    tr = home.transcript('cli-box', cwd=repo)
    for i in range(3):
        tr.turn(now - 3 * H + i * 600, model=model)


def role_fire(home: Home, now):
    _questions_session(home, EXPENSIVE, now)


def role_healthy(home: Home, now):
    home.app_record('local_w', 'cli-worker', home.root)
    tr = home.transcript('cli-worker', cwd=home.root)
    for i in range(3):
        tr.turn(now - 3 * H + i * 600, model=EXPENSIVE)


def subagents_fire(home: Home, now):
    home.transcript('s-sub').turn(now - 2 * H)
    for i in range(3):
        home.subagent('s-sub', f'agent-{i}', description=f'Explore part {i}', first_prompt='look around',
                      ts=now - H + i * 60, model=EXPENSIVE)


def subagents_healthy(home: Home, now):
    home.transcript('s-sub').turn(now - 2 * H)
    home.subagent('s-sub', 'agent-p', description='Panel member 1', ts=now - H, model=EXPENSIVE)
    home.subagent('s-sub', 'agent-m', description='Hard refactor', first_prompt='[opus: cross-module refactor] go',
                  ts=now - H + 60, model=EXPENSIVE)


def _advisor(tr, ts, n):
    its = [{'type': 'message', 'input_tokens': 5, 'output_tokens': 5}]
    its += [{'type': 'advisor_message', 'model': EXPENSIVE, 'input_tokens': 50, 'output_tokens': 10} for _ in range(n)]
    tr.assistant(ts, iterations=its)


def advisor_fire(home: Home, now):
    tr = home.transcript('s-adv')
    tr.user(now - 5 * H, 'work')
    for i in range(6):
        _advisor(tr, now - 5 * H + i * 600, 1)


def advisor_healthy(home: Home, now):
    tr = home.transcript('s-adv')
    tr.user(now - 31 * H, 'work')
    for i in range(3):
        _advisor(tr, now - 31 * H + i * 600, 1)
    tr.user(now - H, 'more')
    for i in range(3):
        _advisor(tr, now - H + i * 60, 1)


def large_fire(home: Home, now):
    home.live('s-ctx')
    tr = home.transcript('s-ctx')
    tr.user(now - 3 * H, 'go')
    for i in range(25):
        tr.assistant(now - 3 * H + i * 60, cr=200000)


def large_healthy(home: Home, now):
    tr = home.transcript('s-ctx')
    tr.user(now - 3 * H, 'go')
    for i in range(25):
        tr.assistant(now - 3 * H + i * 60, cr=900000 if i == 12 else 2000)


def idle_fire(home: Home, now):
    tr = home.transcript('s-idle')
    for i in range(5):
        tr.user(now - 20 * H + i * 2 * H, 'wake')
        tr.assistant(now - 20 * H + i * 2 * H + 1, cw5=90000, cr=10000)


def idle_healthy(home: Home, now):
    tr = home.transcript('s-idle')
    for i in range(5):
        tr.user(now - 20 * H + i * 2 * H, 'wake')
        tr.assistant(now - 20 * H + i * 2 * H + 1, cw5=500, cr=99000)


def _hours(home, session, now, per_hour, last):
    tr = home.transcript(session, cwd=home.root)
    tr.user(now - 7 * 24 * H, 'start')
    for h in range(2, 7 * 24, 3):
        tr.assistant(now - h * H, inp=per_hour)
    tr.assistant(now - 600, inp=last)


def pace_fire(home: Home, now):
    _hours(home, 's-pace', now, 10, 60)


def pace_healthy(home: Home, now):
    _hours(home, 's-pace', now, 50, 55)


def automation_fire(home: Home, now):
    tr = home.transcript('s-auto')
    for i in range(9):
        tr.turn(now - 10 * H + i * 600, text='notice', origin='task-notification', model=EXPENSIVE, out=100)
    tr.turn(now - H, text='typed', model=EXPENSIVE, out=100)


def automation_healthy(home: Home, now):
    tr = home.transcript('s-auto')
    for i in range(9):
        tr.turn(now - 10 * H + i * 600, text=f'typed {i}', model=EXPENSIVE, out=100)
    tr.turn(now - H, text='notice', origin='task-notification', model=EXPENSIVE, out=100)


def routines(home: Home, now, model=EXPENSIVE, runs=50):
    """`runs` one-run sessions of a scheduled routine in one project: each run is a new session with its own record."""
    repo = home.git_repo('proj-routine')
    for i in range(runs):
        sid = f's-run-{i:02d}'
        home.app_record(f'local_{sid}', sid, repo, scheduled='task-1')
        home.transcript(sid, cwd=repo).turn(now - 6 * H + i * 60, model=model, out=100 + i)
    return repo


def routines_fire(home: Home, now):
    routines(home, now)


def routines_healthy(home: Home, now):
    routines(home, now, model=CHEAP)


def automation_session(home: Home, now, archived=False, last=None):
    """One worker answering notices on the expensive model, with an app record (archived or not)."""
    repo = home.git_repo('proj-auto')
    home.app_record('local_auto', 's-auto', repo, archived=archived)
    tr = home.transcript('s-auto', cwd=repo)
    last = now - 2 * H if last is None else last
    for i in range(9):
        tr.turn(last - (9 - i) * 600, text='notice', origin='task-notification', model=EXPENSIVE, out=100)
    return repo


def large_sessions(home: Home, now, count, live=True):
    """`count` sessions of one project, each holding a large context for many calls."""
    repo = home.git_repo('proj-ctx')
    for k in range(count):
        sid = f's-big-{k}'
        if live:
            home.app_record(f'local_{sid}', sid, repo)
        tr = home.transcript(sid, cwd=repo)
        tr.user(now - 3 * H, 'go')
        for i in range(25):
            tr.assistant(now - 3 * H + i * 60, cr=200000 + k * 1000)
    return repo


CASES = [
    ('loop', loop_fire, loop_healthy, {}),
    ('empty-wakes', empty_fire, empty_healthy, {'empty_wakes_min_per_day': 24}),
    ('role-model', role_fire, role_healthy, {}),
    ('expensive-subagents', subagents_fire, subagents_healthy, {'expensive_subagents_min': 2}),
    ('advisor-excess', advisor_fire, advisor_healthy, {'advisor_max_per_day': 4}),
    ('large-context', large_fire, large_healthy, {'large_context_calls': 20}),
    ('idle-rewrite', idle_fire, idle_healthy, {'idle_rewrite_min_count': 3}),
    ('pace', pace_fire, pace_healthy, {'prices': UNIT_PER_INPUT_TOKEN, 'pace_factor': 3, 'pace_min_units': 20}),
    ('expensive-automation', automation_fire, automation_healthy, {'automation_min_share': 0.6}),
]
