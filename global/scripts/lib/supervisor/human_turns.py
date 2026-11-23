"""When the developer last wrote in a session, told apart from automatic turns."""
import json
import os
import re
import time

from . import ask_gate, settings, transcripts, util


_HUMAN_SEEN = {}


def human_seen_since(path, cutoff):
    """last_human_input with a memo per transcript state: while the file does not change, a window that only moves
    forward cannot find newer input, so a None stays None and an epoch stays valid until it leaves the window. Raises
    TimeoutError like last_human_input."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    sig = (st.st_mtime_ns, st.st_size)
    memo = _HUMAN_SEEN.get(path)
    if memo and memo[0] == sig and cutoff >= memo[1]:
        return memo[2] if memo[2] is not None and memo[2] >= cutoff else None
    seen = last_human_input(path, cutoff)
    _HUMAN_SEEN[path] = (sig, cutoff, seen)
    return seen


_TAG = re.compile(r'</?system-reminder\b[^>]*>')


def strip_reminders(text):
    """Remove <system-reminder> blocks, nested ones included (a depth counter, not a non-greedy regex)."""
    out, depth, pos = [], 0, 0
    for m in _TAG.finditer(text):
        if depth == 0:
            out.append(text[pos:m.start()])
        if m.group().startswith('</'):
            depth = max(0, depth - 1)
        else:
            depth += 1
        pos = m.end()
    if depth == 0:
        out.append(text[pos:])
    return ''.join(out).strip()


def block_text(content):
    """(text without system reminders, has_image) of a message/prompt content: a string or a list of blocks."""
    if isinstance(content, str):
        return strip_reminders(content), False
    parts, image = [], False
    for item in content if isinstance(content, list) else []:
        if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text'), str):
            parts.append(strip_reminders(item['text']))
        elif isinstance(item, dict) and item.get('type') == 'image':
            image = True
    return '\n'.join(p for p in parts if p).strip(), image


# Text that arrives in the user channel without being the developer's (used only when a record has no `origin`).
NOT_HUMAN_PREFIXES = ('This session is being continued from a previous conversation', 'Background (from the session',
                      '<task-notification', '<agent-message', '[Subagent hand-back]', '<local-command',
                      'Another Claude session sent a message', settings.ACCOUNT_SWITCH_MARKER, '<side-sessions-event',
                      '<ci-monitor-event', '<cross-session-message', '[SYSTEM NOTIFICATION')


def human_input(rec):
    """True when a transcript record is genuine developer input (user prompt, or a mid-turn message they typed)."""
    kind = rec.get('type')
    if kind == 'user':
        if rec.get('isMeta') or rec.get('isCompactSummary'):
            return False
        origin, content = rec.get('origin'), (rec.get('message') or {}).get('content')
    elif kind == 'attachment':
        att = rec.get('attachment')
        if not isinstance(att, dict) or att.get('type') != 'queued_command' or att.get('isMeta'):
            return False
        origin, content = att.get('origin'), att.get('prompt')
        if origin is None and att.get('humanTurn') is True:
            origin = {'kind': 'human'}
    else:
        return False
    if isinstance(content, list) and any(isinstance(i, dict) and i.get('type') == 'tool_result' for i in content):
        return False
    text, image = block_text(content)
    if text.startswith(NOT_HUMAN_PREFIXES):
        return False
    if isinstance(origin, dict) and origin.get('kind'):
        return origin['kind'] == 'human' and bool(text or image)
    return bool(text or image)  # old records without `origin`: the text heuristics above are all there is


def human_text(rec):
    """The text of a genuine developer record (without system reminders), '' when it has none."""
    if rec.get('type') == 'attachment':
        att = rec.get('attachment')
        content = att.get('prompt') if isinstance(att, dict) else None
    else:
        content = (rec.get('message') or {}).get('content')
    return block_text(content)[0]


_RE_TS = re.compile(rb'"timestamp"\s*:\s*"(\d{4}-\d\d-\d\dT[\d:.]+Z)"')
_RE_RESULT_ID = re.compile(rb'"tool_use_id"\s*:\s*"([^"]+)"')


def iter_lines_reverse(path, chunk=1 << 20):
    with open(path, 'rb') as fh:
        fh.seek(0, 2)
        pos, carry = fh.tell(), b''
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            fh.seek(pos)
            parts = (fh.read(step) + carry).split(b'\n')
            carry = parts[0]
            for line in reversed(parts[1:]):
                if line:
                    yield line
        if carry:
            yield carry


def last_human_input(path, cutoff, with_text=False):
    """Epoch seconds of the newest genuine developer input at or after `cutoff`, else None.

    With `with_text` it returns (epoch, text) instead: the text of that newest message ('' for an answered dialog).

    Reads the transcript backwards and stops at the first record older than the window (5 min of slack for records
    written out of order), so a 50 MB transcript costs only the last few minutes of it. An AskUserQuestion that the
    developer answered counts too: its non-error tool_result is the proof. Raises TimeoutError past the budget.
    """
    deadline = time.monotonic() + ask_gate.ASK_GATE_BUDGET_S
    seen, answered = 0, {}
    for line in iter_lines_reverse(path):
        seen += len(line)
        if time.monotonic() > deadline or seen > ask_gate.ASK_GATE_MAX_BYTES:
            raise TimeoutError('transcript scan over budget')
        stamp = _RE_TS.findall(line[-2048:]) or _RE_TS.findall(line)
        ts = util.parse_ts(stamp[-1].decode()) if stamp else None
        if ts is not None and ts < cutoff - 300:
            return None
        if ts is None:
            continue
        if b'tool_result' in line and b'"user"' in line:
            if b'"is_error":true' not in line:
                for tid in _RE_RESULT_ID.findall(line):
                    answered.setdefault(tid.decode(), ts)
            continue
        if b'AskUserQuestion' in line and b'"tool_use"' in line and answered:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            for item in transcripts.content_items(rec):
                if item.get('type') == 'tool_use' and item.get('name') == ask_gate.ASK_TOOL and item.get('id') in answered \
                        and answered[item['id']] >= cutoff:
                    return (answered[item['id']], '') if with_text else answered[item['id']]
            continue
        if ts < cutoff or not (b'"user"' in line or b'queued_command' in line):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and human_input(rec):
            return (ts, human_text(rec)) if with_text else ts
    return None
