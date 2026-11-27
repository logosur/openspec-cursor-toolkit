#!/usr/bin/env python3
"""Replay recorded supervisor wakes and report what a fixed sleep rule would have saved and missed.

Stage 0 of the llm-pool change (task 6.1, design decision D15). Standard library only, Python 3.10+.

It reads Claude Code transcripts (JSONL, `<projects-dir>/<project-slug>/<session>.jsonl`), finds the supervisors (a
transcript that arms the watcher with a background `supervisor-lock wait ... --owner ...` command), finds each wake (a
task-notification turn of such an arming), classifies it and compares today's behaviour with a fixed rule "B" that
sleeps soft wakes within two bounds history can rebuild.

Definitions used here (all from D15 unless noted):

* Turn of a wake: from the notification record to the next user record that is not a tool result. NOTE: D15 says
  "until the supervisor's next arming of the watcher". Real supervisors re-arm and then keep acting, so the end of
  the turn is used instead (the spec is to be corrected). User records flagged `isMeta` are text the harness injects
  inside a turn (for example a loaded skill), so they do not end it.
* Hard / soft: a wake of a watcher armed with `--guard` is hard. Otherwise it is soft when every event line is
  `STATUS <id> idle->busy`, or when the only event line is `TIMEOUT ...`; anything else is hard. The advisory
  `REGISTRY_BIG` line the watcher may append after its events never causes a wake, so it is ignored here. A wake
  with no event line whose notification status is not `completed` is also hard (reason "watcher stopped"): the
  watcher was stopped or died and never finished, so no triage could have slept it; with status `completed` or
  unknown it stays unclassified.
* Needed: any tool_use of the closed list (message, session start/stop/archive, git write, deploy, panel, question)
  anywhere in the turn of a soft wake, main transcript only.
* Rule B: per supervisor, in time order, sleep every classified soft wake while fewer than 4 sleeps in a row were made
  and less than 2 hours passed since the first sleep of the current stretch. Its saving and its needed-wake misses
  are UPPER BOUNDS: the deadline, the time the periodic report falls due and "something waits for the supervisor"
  are not in the history.

The report never prints a path, a project slug, a session id, a command or any text from a transcript.
"""
import argparse
import calendar
import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

CLASSES = ('fresh', 'cache_read', 'cache_write', 'output')
USAGE_KEYS = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')

# Every event line the watcher (and the modules it calls) prints, taken from global/scripts/lib/supervisor:
# watch.py (NEW GONE STATUS TURN AWAITING CRASH HUNG MODE WAITING MODELSTALL HANDOFF IDLE CLOSABLE SUBAGENT_SILENT
# ALLIDLE REF TIMEOUT REGISTRY_BIG USAGE RESUMED), interrupted.py (CUT), cloud.py (CLOUD), backlog.py (BACKLOG),
# machine_queue.py (QUEUED SLOTHELD), lint.py (SKILL_CHANGED), askdue.py (ASKDUE).
EVENT_KEYWORDS = (
    'NEW', 'GONE', 'STATUS', 'TURN', 'AWAITING', 'CRASH', 'HUNG', 'MODE', 'WAITING', 'MODELSTALL', 'HANDOFF', 'IDLE',
    'CLOSABLE', 'SUBAGENT_SILENT', 'ALLIDLE', 'REF', 'TIMEOUT', 'REGISTRY_BIG', 'USAGE', 'RESUMED', 'CUT', 'CLOUD',
    'BACKLOG', 'QUEUED', 'SLOTHELD', 'SKILL_CHANGED', 'ASKDUE',
)
ADVISORY_KEYWORDS = ('REGISTRY_BIG',)
_EVENT_RE = re.compile(r'^(?:\s*\d+[\u2192\t])?\s*(' + '|'.join(EVENT_KEYWORDS) + r')(?=\s|$)')
_SOFT_STATUS_RE = re.compile(r'^STATUS \S+ idle->busy$')

MAX_RUN = 4                   # consecutive sleeps (D8 bound 5)
MAX_SPAN_S = 2 * 3600         # maximum silent time (D8 bound 2)
SOFT_KINDS = ('soft_idle', 'soft_timeout')
KIND_ORDER = ('hard', 'soft_idle', 'soft_timeout', 'unclassified')
KIND_LABEL = {'hard': 'hard', 'soft_idle': 'soft, idle to busy', 'soft_timeout': 'soft, timeout',
              'unclassified': 'unclassified'}
HARD_REASONS = ('guard', 'event', 'watcher stopped')
CRITERIA = ('message', 'session-control', 'git-write', 'deploy', 'panel', 'question')

DECISIONS = {
    1: 'open: too little data',
    2: 'no-go: too small',
    3: 'no-go: the rule is enough',
    4: 'open: a model must be tested',
}


# --------------------------------------------------------------------------------------------------------- time

_TS_RE = re.compile(r'^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.(\d+))?')


def to_epoch(text):
    """Seconds since the epoch of an ISO timestamp read as UTC, or None."""
    m = _TS_RE.match(text or '')
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    frac = float('0.' + m.group(7)) if m.group(7) else 0.0
    return calendar.timegm((y, mo, d, h, mi, s)) + frac


def window_bound(text):
    """Normalise a --since/--until value to 'YYYY-MM-DDTHH:MM:SS' in UTC (a naive value is read as UTC)."""
    if not text:
        return None
    dt = datetime.fromisoformat(str(text).strip().replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def _out_of_window(line, since, until):
    """Cheap pre-filter on the `"timestamp":"..."` substring, before json.loads (first and last occurrence)."""
    a = line.find('"timestamp":"')
    if a < 0:
        return False
    b = line.rfind('"timestamp":"')
    ta, tb = line[a + 13:a + 32], line[b + 13:b + 32]
    if since and ta < since and tb < since:
        return True
    return bool(until and ta > until and tb > until)


# ------------------------------------------------------------------------------------------- tool_use detection

_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
_QUOTED_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'[^\']*\'')
_SPLIT_RE = re.compile(r'&&|\|\||\$\(|[;|&\n`(){}]')
_ASSIGN_RE = re.compile(r'^[A-Za-z_]\w*=')
_PREFIXES = ('sudo', 'time', 'nohup', 'env', 'command', 'exec', 'nice')
_DEPLOY_TOKEN_RE = re.compile(r'(?:^|/)deploy(?:[-_.:][\w.:-]*)?$')
_GIT_WRITES = ('commit', 'merge', 'push', 'rebase', 'cherry-pick', 'revert')
_TAG_READ_FLAGS = ('-l', '--list', '-n', '-v', '--verify', '--contains', '--points-at', '--merged', '--no-merged')
# Commands that only read or move files: `deploy` as an argument of one of them is a path or a pattern, not a deploy.
_FILE_COMMANDS = frozenset((
    'cat', 'sed', 'grep', 'egrep', 'fgrep', 'rg', 'ls', 'head', 'tail', 'less', 'more', 'awk', 'find', 'wc', 'stat',
    'file', 'diff', 'cmp', 'echo', 'printf', 'test', '[', 'cd', 'mkdir', 'rm', 'mv', 'cp', 'touch', 'chmod', 'chown',
    'tree', 'bat', 'vim', 'vi', 'nano', 'code', 'readlink', 'realpath', 'dirname', 'basename', 'du', 'sort', 'uniq',
    'jq', 'tee',
))


def _segments(command):
    """Split a shell command into simple-command word lists, ignoring heredoc bodies and quoted text."""
    text = _HEREDOC_RE.sub(r' \3', command)
    text = _QUOTED_RE.sub('""', text)
    out = []
    for seg in _SPLIT_RE.split(text):
        words = seg.split()
        while words and (_ASSIGN_RE.match(words[0]) or words[0] in _PREFIXES):
            words.pop(0)
        if words:
            out.append(words)
    return out


def _git_write(words):
    i = 1
    while i < len(words):
        w = words[i]
        if w in ('-C', '-c', '--git-dir', '--work-tree', '--namespace'):
            i += 2
        elif w.startswith('-'):
            i += 1
        else:
            break
    sub = words[i] if i < len(words) else ''
    if sub in _GIT_WRITES:
        return True
    if sub == 'tag':
        rest = words[i + 1:]
        return bool(rest) and rest[0] not in _TAG_READ_FLAGS
    return False


def bash_criteria(command):
    """The needed-criteria a Bash command fires: a subset of git-write, deploy, question."""
    found = set()
    for words in _segments(command or ''):
        cmd = os.path.basename(words[0])
        if cmd == 'git':
            if _git_write(words):
                found.add('git-write')
            continue
        if cmd == 'gh':
            if len(words) > 2 and words[1] == 'pr' and words[2] in ('create', 'merge'):
                found.add('git-write')
            continue
        if cmd in _FILE_COMMANDS:
            continue
        if any(os.path.basename(words[i]) == 'ask-queue' and words[i + 1] == 'add' for i in range(len(words) - 1)):
            found.add('question')
        if any(_DEPLOY_TOKEN_RE.search(w) for w in words):
            found.add('deploy')
    return found


def tool_criteria(name, tool_input):
    """The needed-criteria one tool_use block fires (closed list of D15)."""
    found = set()
    inp = tool_input if isinstance(tool_input, dict) else {}
    if name in ('SendMessage', 'CrossSessionMessage') or name.endswith('send_message'):
        found.add('message')
    if name.endswith(('start_session', 'stop_session', 'archive_session')):
        found.add('session-control')
    skill = inp.get('skill') if isinstance(inp.get('skill'), str) else ''
    if name == 'Skill' and (skill == 'panel-de-decision' or skill.endswith(':panel-de-decision')):
        found.add('panel')
    if name == 'AskUserQuestion':
        found.add('question')
    if name == 'Bash':
        found |= bash_criteria(str(inp.get('command') or ''))
    return found


# ----------------------------------------------------------------------------------------------- transcript parsing

def event_lines(text):
    """The watcher event lines of a text (a tool result or the output file), without any other line."""
    out = []
    for line in (text or '').splitlines():
        m = _EVENT_RE.match(line)
        if m:
            out.append(line[m.start(1):].strip())
    return out


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get('text') if isinstance(b.get('text'), str) else text_of(b.get('content')))
            elif isinstance(b, str):
                parts.append(b)
        return '\n'.join(parts)
    return ''


def _is_tool_result(content):
    return (isinstance(content, list) and bool(content) and isinstance(content[0], dict)
            and content[0].get('type') == 'tool_result')


def _is_arming(tool_input):
    cmd = str(tool_input.get('command') or '')
    return 'supervisor-lock wait' in cmd and '--owner' in cmd


def _is_guard(tool_input):
    return re.search(r'(?<![\w-])--guard(?![\w-])', str(tool_input.get('command') or '')) is not None


def file_has_marker(path, marker=b'supervisor-lock wait'):
    """Fast byte scan: can this transcript hold a watcher arming at all?"""
    keep = len(marker) - 1
    tail = b''
    with open(path, 'rb') as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                return False
            if marker in tail + chunk:
                return True
            tail = chunk[-keep:]


def _new_turn(turns, kind, ts):
    turn = {'index': len(turns), 'kind': kind, 'ts': ts, 'ended': False, 'compacted': False, 'guard': False,
            'task_id': None, 'output_file': None, 'status': None, 'events': [], 'tools': Counter(),
            'criteria': set(), 'usage': dict.fromkeys(CLASSES, 0)}
    turns.append(turn)
    return turn


def _read_output_file(path):
    try:
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            return []
        with open(path, encoding='utf-8', errors='replace') as fh:
            return event_lines(fh.read(2_000_000))
    except OSError:
        return []


def parse_transcript(path, since=None, until=None):
    """Stream one transcript into turns.

    `since`/`until` are window_bound() values. Returns {'armings', 'first_arming', 'first_ts', 'last_ts', 'flow',
    'turns'}; a transcript with `armings == 0` is not a supervisor transcript. Each turn: kind ('preamble' = records
    before the first user turn, 'other', 'wake'), ts, usage by class, and for wakes the guard flag, the watcher event
    lines, the tool names, the needed-criteria that fired, and whether the turn ended or held a compaction.
    """
    armings = {}      # tool_use id -> armed with --guard
    turns = []
    cur = _new_turn(turns, 'preamble', None)
    messages = {}     # message id -> [turn index, [usage values]]
    seen_tool_use = set()
    pending = {}      # tool_use id of a read of a task's output file -> the wake turn
    first_ts = last_ts = first_arming = None
    record_no = 0
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if (since or until) and _out_of_window(line, since, until):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get('isSidechain'):
                continue
            record_no += 1
            stamp = rec.get('timestamp') if isinstance(rec.get('timestamp'), str) else None
            if stamp:
                if (since and stamp[:19] < since) or (until and stamp[:19] > until):
                    continue
                epoch = to_epoch(stamp)
                if epoch is not None:
                    first_ts = epoch if first_ts is None else min(first_ts, epoch)
                    last_ts = epoch if last_ts is None else max(last_ts, epoch)
            if rec.get('isCompactSummary') or rec.get('type') == 'summary' or rec.get('subtype') == 'compact_boundary':
                cur['compacted'] = True
            msg = rec.get('message') if isinstance(rec.get('message'), dict) else {}
            kind = rec.get('type')

            if kind == 'assistant':
                usage = msg.get('usage') if isinstance(msg.get('usage'), dict) else {}
                values = [int(usage.get(k) or 0) for k in USAGE_KEYS]
                mid = msg.get('id') or f'record-{record_no}'
                if mid in messages:   # the same message id repeats on several records: count it once
                    messages[mid][1] = [max(a, b) for a, b in zip(messages[mid][1], values)]
                else:
                    messages[mid] = [cur['index'], values]
                content = msg.get('content')
                for block in content if isinstance(content, list) else ():
                    if not isinstance(block, dict) or block.get('type') != 'tool_use':
                        continue
                    tid = block.get('id')
                    if tid is not None:
                        if tid in seen_tool_use:
                            continue
                        seen_tool_use.add(tid)
                    name = str(block.get('name') or '')
                    tool_input = block.get('input') if isinstance(block.get('input'), dict) else {}
                    if name == 'Bash' and tool_input.get('run_in_background') and _is_arming(tool_input):
                        armings[tid] = _is_guard(tool_input)
                        if first_arming is None:
                            first_arming = to_epoch(stamp)
                    if cur['kind'] == 'wake':
                        cur['tools'][name] += 1
                        cur['criteria'] |= tool_criteria(name, tool_input)
                        if cur['task_id'] and name in ('Bash', 'Read') and \
                                cur['task_id'] + '.output' in json.dumps(tool_input):
                            pending[tid] = cur

            elif kind == 'user':
                content = msg.get('content')
                if _is_tool_result(content):
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'tool_result':
                            turn = pending.pop(block.get('tool_use_id'), None)
                            if turn is not None and not turn['events']:
                                turn['events'] = event_lines(text_of(block.get('content')))
                    continue
                if rec.get('isMeta'):
                    continue
                cur['ended'] = True
                text = text_of(content)
                origin = rec.get('origin') if isinstance(rec.get('origin'), dict) else {}
                notified = origin.get('kind') == 'task-notification' or text.lstrip().startswith('<task-notification>')
                tuid = _tag(text, 'tool-use-id') if notified else None
                if tuid is not None and tuid in armings:
                    cur = _new_turn(turns, 'wake', to_epoch(stamp))
                    cur['guard'] = armings[tuid]
                    cur['task_id'] = _tag(text, 'task-id')
                    cur['output_file'] = _tag(text, 'output-file')
                    cur['status'] = _tag(text, 'status')
                else:
                    cur = _new_turn(turns, 'other', to_epoch(stamp))

    flow = dict.fromkeys(CLASSES, 0)
    for index, values in messages.values():
        for name, value in zip(CLASSES, values):
            turns[index]['usage'][name] += value
            flow[name] += value
    for turn in turns:
        if turn['kind'] == 'wake' and not turn['events'] and turn['output_file']:
            turn['events'] = _read_output_file(turn['output_file'])
    return {'armings': len(armings), 'first_arming': first_arming, 'first_ts': first_ts, 'last_ts': last_ts,
            'flow': flow, 'turns': turns}


def _tag(text, name):
    m = re.search(r'<%s>\s*(.*?)\s*</%s>' % (name, name), text or '', re.S)
    return m.group(1) if m and m.group(1) else None


# --------------------------------------------------------------------------------------------------- classification

def classify_wake(turn):
    """{'kind', 'reason', 'needed', 'criteria'} for a wake turn; kind is hard, soft_idle, soft_timeout or unclassified."""
    result = {'kind': None, 'reason': None, 'needed': None, 'criteria': []}
    if turn['guard']:
        result['kind'] = 'hard'
        result['reason'] = 'guard'
        return result
    events = [e for e in turn['events'] if e.split(' ', 1)[0] not in ADVISORY_KEYWORDS]
    if not events:
        status = turn.get('status')
        if isinstance(status, str) and status and status != 'completed':
            result.update(kind='hard', reason='watcher stopped')   # it never finished: nothing a triage could sleep
        else:
            result.update(kind='unclassified', reason='no output')
        return result
    if all(_SOFT_STATUS_RE.match(e) for e in events):
        kind = 'soft_idle'
    elif len(events) == 1 and re.match(r'^TIMEOUT(\s|$)', events[0]):
        kind = 'soft_timeout'
    else:
        result['kind'] = 'hard'
        result['reason'] = 'event'
        return result
    if turn['compacted']:
        result.update(kind='unclassified', reason='compaction in turn')
        return result
    if not turn['ended']:
        result.update(kind='unclassified', reason='turn not ended')
        return result
    result['kind'] = kind
    result['criteria'] = sorted(turn['criteria'])
    result['needed'] = bool(turn['criteria'])
    return result


def simulate_rule_b(turns, max_run=MAX_RUN, max_span=MAX_SPAN_S):
    """Indices of the turns rule B sleeps. `turns` are one supervisor's classified turns in order.

    A stretch of sleeps ends at any turn in which the supervisor is awake: a hard wake, a soft wake that was not slept,
    an unclassified wake, or any other turn (a human message, another task finishing).
    """
    slept = []
    run = 0
    first = None
    for i, turn in enumerate(turns):
        if turn['kind'] == 'preamble':
            continue
        soft = turn.get('class') in SOFT_KINDS and turn['ts'] is not None
        if soft and run < max_run and (run == 0 or turn['ts'] - first < max_span):
            if run == 0:
                first = turn['ts']
            run += 1
            slept.append(i)
        else:
            run = 0
            first = None
    return slept


def decide(classified_soft, unclassified, needed, saving, flow):
    """The first row of the D15 table that applies. Rates are per classified soft wake; saving and flow share a unit."""
    reason = None
    if classified_soft < 100:
        reason = f'{classified_soft} classified soft wakes, fewer than 100'
    elif unclassified * 10 > classified_soft + unclassified:
        reason = f'{unclassified} unclassified of {classified_soft + unclassified}, more than one in ten'
    if reason:
        row = 1
    elif flow <= 0 or saving * 100 < flow * 5:
        row, reason = 2, 'the fixed rule saves under 5 % of the flow'
    elif needed * 100 <= classified_soft:
        row, reason = 3, f'{needed} needed in {classified_soft} classified soft wakes, at most 1 in 100'
    else:
        row, reason = 4, f'{needed} needed in {classified_soft} classified soft wakes and the saving is worth it'
    return {'row': row, 'verdict': DECISIONS[row], 'reason': reason}


# ------------------------------------------------------------------------------------------------------ aggregation

def _cost(usage, weights):
    out = {name: int(usage.get(name, 0)) for name in CLASSES}
    out['raw'] = sum(out[name] for name in CLASSES)
    out['weighted'] = sum(w * out[name] for w, name in zip(weights, CLASSES)) if weights else None
    return out


def _metric(cost):
    return cost['weighted'] if cost['weighted'] is not None else cost['raw']


def _add(total, usage):
    for name in CLASSES:
        total[name] += usage[name]


def _tool_label(name):
    # MCP server names can carry ids; only the tool part is kept.
    return 'mcp__*__' + name.split('__')[-1] if name.startswith('mcp__') else name


def analyze(projects_dir, since=None, until=None, weights=None):
    """Parse every supervisor transcript of the projects directory and return the report figures (no ids, no paths)."""
    since_n, until_n = window_bound(since), window_bound(until)
    since_epoch = to_epoch(since_n) if since_n else None
    found = []
    for path in glob.glob(os.path.join(os.path.expanduser(projects_dir), '*', '*.jsonl')):
        try:
            if since_epoch is not None and os.path.getmtime(path) < since_epoch:
                continue
            if not file_has_marker(path):
                continue
            parsed = parse_transcript(path, since_n, until_n)
        except OSError:
            continue
        if parsed['armings']:
            parsed['_order'] = (parsed['first_arming'] or 0, hashlib.sha256(path.encode()).hexdigest())
            found.append(parsed)
    found.sort(key=lambda p: p['_order'])
    return summarize(found, weights, since_n, until_n)


def summarize(parsed, weights, since=None, until=None):
    """Classify the wakes of parsed supervisor transcripts, simulate rule B and decide."""
    by_kind = {k: dict.fromkeys(CLASSES, 0) for k in (*KIND_ORDER, 'other')}
    wake_counts = Counter()
    reasons = Counter()
    hard_reasons = Counter()
    criteria_seen = Counter()
    needed_total = 0
    slept_counts = Counter()
    slept_cost = dict.fromkeys(CLASSES, 0)
    slept_needed = 0
    slept_criteria = Counter()
    slept_needed_wakes = 0
    tools = Counter()
    flow = dict.fromkeys(CLASSES, 0)
    supervisors = []
    firsts, lasts = [], []
    for number, sup in enumerate(parsed, 1):
        wakes = Counter()
        for turn in sup['turns']:
            if turn['kind'] == 'wake':
                info = classify_wake(turn)
                turn['class'], turn['reason'], turn['needed'], turn['criteria_fired'] = (
                    info['kind'], info['reason'], info['needed'], info['criteria'])
                wakes[info['kind']] += 1
                _add(by_kind[info['kind']], turn['usage'])
                if info['kind'] == 'unclassified':
                    reasons[info['reason']] += 1
                elif info['kind'] == 'hard':
                    hard_reasons[info['reason']] += 1
                if info['kind'] in SOFT_KINDS:
                    if info['needed']:
                        needed_total += 1
                        criteria_seen.update(info['criteria'])
                    else:
                        tools.update(_tool_label(n) for n in turn['tools'].elements())
            else:
                turn['class'] = None
                _add(by_kind['other'], turn['usage'])
        slept = simulate_rule_b(sup['turns'])
        for i in slept:
            turn = sup['turns'][i]
            slept_counts[turn['class']] += 1
            _add(slept_cost, turn['usage'])
            if turn['needed']:
                slept_needed += 1
                slept_criteria.update(turn['criteria_fired'])
        _add(flow, sup['flow'])
        if sup['first_ts'] is not None:
            firsts.append(sup['first_ts'])
            lasts.append(sup['last_ts'])
        hours = (sup['last_ts'] - sup['first_ts']) / 3600 if sup['first_ts'] is not None else 0.0
        supervisors.append({'label': f'S{number}', 'hours': round(hours, 2), 'wakes': sum(wakes.values()),
                            **{k: wakes[k] for k in KIND_ORDER}, 'slept_by_rule_b': len(slept)})
        wake_counts.update(wakes)

    classified_soft = wake_counts['soft_idle'] + wake_counts['soft_timeout']
    unclassified = wake_counts['unclassified']
    flow_cost = _cost(flow, weights)
    saving = _cost(slept_cost, weights)
    flow_metric, saving_metric = _metric(flow_cost), _metric(saving)
    slept_total = sum(slept_counts.values())
    decision = decide(classified_soft, unclassified, needed_total, saving_metric, flow_metric)
    return {
        'window': {'since': since, 'until': until,
                   'first_record': _iso(min(firsts)) if firsts else None,
                   'last_record': _iso(max(lasts)) if lasts else None},
        'weights': list(weights) if weights else None,
        'basis': 'weighted' if weights else 'raw',
        'supervisors': supervisors,
        'hours_total': round(sum(s['hours'] for s in supervisors), 2),
        'wakes': {'total': sum(wake_counts.values()), **{k: wake_counts[k] for k in KIND_ORDER},
                  'hard_reasons': {r: hard_reasons[r] for r in HARD_REASONS},
                  'unclassified_reasons': dict(sorted(reasons.items()))},
        'soft': {'classified': classified_soft, 'needed': needed_total, 'not_needed': classified_soft - needed_total,
                 'criteria': {c: criteria_seen[c] for c in CRITERIA}},
        'cost': {'flow': flow_cost, 'by_kind': {k: _cost(v, weights) for k, v in by_kind.items()}},
        'rule_b': {'max_run': MAX_RUN, 'max_span_hours': MAX_SPAN_S / 3600, 'upper_bound': True,
                   'slept': slept_total, 'slept_soft_idle': slept_counts['soft_idle'],
                   'slept_soft_timeout': slept_counts['soft_timeout'], 'saving': saving,
                   'saving_share_pct': round(100 * saving_metric / flow_metric, 2) if flow_metric else 0.0,
                   'needed_slept': slept_needed,
                   'needed_slept_criteria': {c: slept_criteria[c] for c in CRITERIA},
                   'needed_slept_per_100_slept': round(100 * slept_needed / slept_total, 2) if slept_total else 0.0},
        'rates': {'unclassified_share_pct': round(100 * unclassified / (classified_soft + unclassified), 2)
                  if classified_soft + unclassified else 0.0,
                  'needed_per_100_classified_soft': round(100 * needed_total / classified_soft, 2)
                  if classified_soft else 0.0},
        'decision': decision,
        'tools_in_not_needed_soft_turns': [[n, c] for n, c in tools.most_common(10)],
    }


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ------------------------------------------------------------------------------------------------------- the report

def _n(value):
    return f'{value:,.0f}'


def _cost_cells(cost):
    weighted = _n(cost['weighted']) if cost['weighted'] is not None else 'weights not set'
    return [_n(cost[c]) for c in CLASSES] + [_n(cost['raw']), weighted]


def _table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |', '|' + '|'.join('---' for _ in header) + '|']
    lines += ['| ' + ' | '.join(str(c) for c in row) + ' |' for row in rows]
    return lines


def render_markdown(res):
    out = []
    if not res['weights']:
        out += ['> WARNING: weights not set. Every token figure below is raw (fresh input, cache read, cache write and '
                'output each count as 1) and so is every share of the flow; cache tokens weigh differently on the '
                'usage limit.', '']
    out += ['# Supervisor wake simulation', '']
    out += ['The figures of rule B are UPPER BOUNDS: the deadline, the time the periodic report falls due and '
            '"something waits for the supervisor" are not in the history, so the saving can only be smaller and the '
            'needed wakes it would have slept can only be fewer.', '']
    w = res['window']
    out += ['## Window', '',
            f'- Requested: since {w["since"] or "no limit"}, until {w["until"] or "no limit"} (UTC).',
            f'- Observed records: {w["first_record"] or "none"} to {w["last_record"] or "none"}.',
            f'- Supervisor transcripts: {len(res["supervisors"])}, {res["hours_total"]} hours observed in total.', '']
    out += _table(['Supervisor', 'Hours observed', 'Wakes', 'Hard', 'Soft idle to busy', 'Soft timeout',
                   'Unclassified', 'Slept by rule B'],
                  [[s['label'], s['hours'], s['wakes'], s['hard'], s['soft_idle'], s['soft_timeout'],
                    s['unclassified'], s['slept_by_rule_b']] for s in res['supervisors']])
    wk = res['wakes']
    out += ['', '## Wakes by kind', '', f'Total wakes: {wk["total"]}.', '']
    out += _table(['Kind', 'Wakes'], [[KIND_LABEL[k], wk[k]] for k in KIND_ORDER])
    out += ['', 'Hard, by reason: ' + ', '.join(f'{r} {n}' for r, n in wk['hard_reasons'].items()) + '.']
    if wk['unclassified_reasons']:
        out += ['', 'Unclassified, by reason: ' + ', '.join(f'{r} {n}' for r, n in wk['unclassified_reasons'].items())
                + '. They are left out of every rate.']
    soft = res['soft']
    out += ['', '## Soft wakes: needed or not', '',
            f'Classified soft wakes: {soft["classified"]}. Needed: {soft["needed"]}. Not needed: {soft["not_needed"]}.',
            '', 'Criterion that fired among the needed wakes (a wake can fire several): '
            + ', '.join(f'{c} {n}' for c, n in soft['criteria'].items()) + '.']
    cost = res['cost']
    out += ['', '## Cost of the wakes and the flow', '',
            'Tokens of the main-model messages of each wake turn. The flow is every message of the supervisor '
            'transcripts in the window.', '']
    rows = [[KIND_LABEL[k]] + _cost_cells(cost['by_kind'][k]) for k in KIND_ORDER]
    rows.append(['turns that are not wakes'] + _cost_cells(cost['by_kind']['other']))
    rows.append(['**flow**'] + _cost_cells(cost['flow']))
    out += _table(['Kind', 'Fresh input', 'Cache read', 'Cache write', 'Output', 'Raw total', 'Weighted'], rows)
    if res['weights']:
        out += ['', 'Weights (fresh, cache read, cache write, output): ' + ', '.join(f'{x:g}' for x in res['weights']) + '.']
    rb = res['rule_b']
    out += ['', '## Rule B: sleep every soft wake within the two bounds (upper bounds)', '',
            f'Bounds: at most {rb["max_run"]} sleeps in a row and less than {rb["max_span_hours"]:g} hours since the '
            'first sleep of the stretch.', '',
            f'- Wakes it would have slept: {rb["slept"]} ({rb["slept_soft_idle"]} idle to busy, '
            f'{rb["slept_soft_timeout"]} timeout).',
            f'- Saving, at most: {_n(rb["saving"][res["basis"]])} {res["basis"]} tokens, '
            f'{rb["saving_share_pct"]} % of the flow ({res["basis"]} basis).',
            f'- Needed wakes it would have slept, at most: {rb["needed_slept"]} '
            f'({rb["needed_slept_per_100_slept"]} per 100 slept). By criterion: '
            + ', '.join(f'{c} {n}' for c, n in rb['needed_slept_criteria'].items()) + '.', '']
    rates, dec = res['rates'], res['decision']
    out += ['## Rates and decision', '',
            f'- Unclassified share: {rates["unclassified_share_pct"]} % of classified soft plus unclassified wakes.',
            f'- Needed wakes: {rates["needed_per_100_classified_soft"]} per 100 classified soft wakes.', '',
            f'**Decision, row {dec["row"]}: {dec["verdict"]}** ({dec["reason"]}).']
    if dec['row'] == 4:
        out += ['', 'What is missing: how a candidate member is tested is not specified yet; nothing is built until '
                'it is shown to sleep at most 1 needed wake in 100 while keeping at least half of the saving and no '
                'less than 3 % of the flow.']
    out += ['', '## Calibration: tools in the not-needed soft turns', '']
    if res['tools_in_not_needed_soft_turns']:
        out += _table(['Tool', 'Calls'], res['tools_in_not_needed_soft_turns'])
    else:
        out += ['No not-needed soft turn.']
    return '\n'.join(out) + '\n'


def _parse_weights(text):
    try:
        values = [float(x) for x in text.split(',')]
    except ValueError:
        values = []
    if len(values) != 4 or any(v < 0 for v in values):
        raise argparse.ArgumentTypeError('expected four non-negative numbers: FRESH,CACHE_READ,CACHE_WRITE,OUTPUT')
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description='Replay recorded supervisor wakes and compare today with a fixed rule.')
    parser.add_argument('--projects-dir', default='~/.claude/projects')
    parser.add_argument('--since', help='ISO date or time (UTC when it has no offset)')
    parser.add_argument('--until', help='ISO date or time (UTC when it has no offset)')
    parser.add_argument('--weights', type=_parse_weights, help='FRESH,CACHE_READ,CACHE_WRITE,OUTPUT')
    parser.add_argument('--json', metavar='FILE', help='also write the figures as JSON')
    args = parser.parse_args(argv)
    try:
        res = analyze(args.projects_dir, args.since, args.until, args.weights)
    except ValueError as err:
        parser.error(str(err))
    sys.stdout.write(render_markdown(res))
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(res, fh, indent=2, sort_keys=True)
            fh.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
