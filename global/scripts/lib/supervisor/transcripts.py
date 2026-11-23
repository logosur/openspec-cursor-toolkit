"""Read-only access to session transcripts."""
import glob
import json
import os
import re
import time

from . import ask_gate, human_turns, util


def projects_dir():
    return os.path.expanduser(os.environ.get('SUPERVISOR_PROJECTS_DIR', '~/.claude/projects'))


# ---------------------------------------------------------------- transcripts

_TRANSCRIPTS = {}
_TAILS = {}
HUMAN_TOOLS = ('mcp__Claude_Browser', 'mcp__claude-in-chrome')
TAIL_BYTES = 262144


def slug_of(cwd):
    return re.sub(r'[^A-Za-z0-9-]', '-', cwd or '')


def session_files(cli, cwd):
    """(main transcript or None, [subagent transcripts]) of a CLI session id."""
    if not cli:
        return None, []
    main = _TRANSCRIPTS.get(cli)
    if not main or not os.path.isfile(main):
        main = os.path.join(projects_dir(), slug_of(cwd), cli + '.jsonl')
        if not os.path.isfile(main):
            found = sorted(glob.glob(os.path.join(glob.escape(projects_dir()), '*', glob.escape(cli) + '.jsonl')))
            main = found[0] if found else None
        if main:
            _TRANSCRIPTS[cli] = main
    base = os.path.dirname(main) if main else os.path.join(projects_dir(), slug_of(cwd))
    subs = sorted(glob.glob(os.path.join(glob.escape(base), glob.escape(cli), 'subagents', '*.jsonl')))
    return main, subs


def conv_records(path):
    """assistant/user records from the tail of a jsonl transcript, oldest first, each with `_ts` (epoch s).

    Reads only the last 256 KB (transcripts reach tens of MB), growing the window when a single record is bigger.
    """
    try:
        st = os.stat(path)
    except OSError:
        return []
    sig = (st.st_mtime_ns, st.st_size)
    hit = _TAILS.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    recs = []
    for factor in (1, 4, 16, 64):
        size = TAIL_BYTES * factor
        start = max(0, st.st_size - size)
        try:
            with open(path, 'rb') as fh:
                fh.seek(start)
                data = fh.read()
        except OSError:
            return []
        lines = data.split(b'\n')
        if start > 0:
            lines = lines[1:]  # the first line is cut in the middle
        recs = []
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get('type') in ('assistant', 'user'):
                ts = util.parse_ts(rec.get('timestamp'))
                rec['_ts'] = ts if ts is not None else st.st_mtime
                recs.append(rec)
        if recs or start == 0:
            break
    _TAILS[path] = (sig, recs)
    return recs


def content_items(rec):
    content = (rec.get('message') or {}).get('content')
    return [it for it in content if isinstance(it, dict)] if isinstance(content, list) else []


def has_item(rec, kind):
    return any(it.get('type') == kind for it in content_items(rec))


def waiting_on_human(recs, now):
    """(tool name, age s) when the newest assistant record holds a human-bound tool call nobody answered."""
    last = max((i for i, r in enumerate(recs) if r['type'] == 'assistant'), default=None)
    if last is None:
        return None
    answered = {it.get('tool_use_id') for r in recs[last + 1:] if r['type'] == 'user'
                for it in content_items(r) if it.get('type') == 'tool_result'}
    for it in content_items(recs[last]):
        name = it.get('name')
        if it.get('type') == 'tool_use' and isinstance(name, str) and it.get('id') not in answered \
                and (name == 'AskUserQuestion' or name.startswith(HUMAN_TOOLS)):
            return name, max(0, int(now - recs[last]['_ts']))
    return None


def model_stall_age(recs, now):
    """Age in s of the newest record when it is a tool result the model never answered, else None."""
    if recs and recs[-1]['type'] == 'user' and has_item(recs[-1], 'tool_result'):
        return max(0, int(now - recs[-1]['_ts']))
    return None


def subagent_silent_age(path, now):
    """Silence in s of a subagent transcript changed in the last 3 h whose newest record is mid-work."""
    age = now - util.file_mtime(path)
    if age > 10800:
        return None
    recs = conv_records(path)
    if not recs:
        return None
    last = recs[-1]
    if (last['type'] == 'assistant' and has_item(last, 'tool_use')) or (last['type'] == 'user' and has_item(last, 'tool_result')):
        return max(0, int(age))
    return None


def closing_text(recs):
    """Text of the session's closing message: the trailing assistant records after the newest user record, when none
    of them calls a tool or is an API error; None otherwise."""
    tail = []
    for rec in reversed(recs):
        if rec['type'] != 'assistant':
            break
        tail.append(rec)
    if not tail or any(r.get('isApiErrorMessage') or has_item(r, 'tool_use') for r in tail):
        return None
    text = '\n'.join(str(it.get('text') or '') for r in reversed(tail) for it in content_items(r) if it.get('type') == 'text')
    return text.strip() or None


def last_assistant_text(path):
    """Text of the newest assistant record of a transcript ('' when it has none). Reads only the tail, under the budget.

    Only the newest assistant record counts: when it is a tool call without text, the turn did not end in prose and an
    older turn's text must not be judged. Sidechain (subagent) records are skipped. Raises TimeoutError past the budget.
    """
    deadline = time.monotonic() + ask_gate.ASK_GATE_BUDGET_S
    seen = 0
    for line in human_turns.iter_lines_reverse(path):
        seen += len(line)
        if time.monotonic() > deadline or seen > ask_gate.ASK_GATE_MAX_BYTES:
            raise TimeoutError('transcript scan over budget')
        if b'"assistant"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get('type') != 'assistant' or rec.get('isSidechain'):
            continue
        content = (rec.get('message') or {}).get('content')
        if isinstance(content, str):
            return content.strip()
        return '\n'.join(i['text'] for i in content_items(rec)
                         if i.get('type') == 'text' and isinstance(i.get('text'), str)).strip()
    return ''
