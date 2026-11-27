"""Incremental counting of the model responses in the local transcripts (design D2).

Main transcripts are `<projects_dir>/<slug>/<session>.jsonl`; subagent transcripts are
`<projects_dir>/<slug>/<session>/subagents/<agent>.jsonl` with `<agent>.meta.json` next to them. The transcript format
is not documented (design, evidence map): every field is read tolerantly, and a line that cannot be read is counted in
`skipped_lines`, never raised.

Each run reads every file from its cursor (inode, size, byte offset) and appends normalised records to
`<state_dir>/calls/<day>.jsonl` and `<state_dir>/turns/<day>.jsonl`. Readers deduplicate by id, the last record winning,
so one pass and several passes give the same totals. A file whose inode changed or that shrank is read again from the
start.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone

from . import config as C
from .state import Locked, ensure_dir, read_json, write_json

USAGE_FIELDS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')

# Values of origin.kind / turnOrigin / promptSource and what they mean. Anything else read there is `other`.
ORIGIN_KINDS = {
    'human': 'human', 'user': 'human', 'typed': 'human', 'prompt': 'human',
    'task-notification': 'task', 'task_notification': 'task', 'task': 'task',
    'peer': 'peer', 'peer-message': 'peer', 'peer_message': 'peer', 'send-message': 'peer',
    'child': 'child', 'child-message': 'child', 'child_message': 'child',
    'app': 'app', 'app-notice': 'app', 'app_notice': 'app', 'notification': 'app',
    'routine': 'routine', 'scheduled-task': 'routine', 'scheduled_task': 'routine',
    'compact': 'compact',
}
AUTOMATIC = {'task', 'peer', 'child', 'app', 'routine', 'other'}


class Malformed(Exception):
    """A line that cannot be counted as it is: counted in skipped_lines."""


def normalize_text(text: str) -> str:
    text = re.sub(r'\d+', '#', text.lower())
    return re.sub(r'\s+', ' ', text).strip()


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]


def _int(value) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Malformed('token count of the wrong type')
    return value


def usage_of(usage) -> dict:
    """The five token counts of one usage object. Only `cache_creation_input_tokens` present: all of it is 5-minute."""
    if not isinstance(usage, dict):
        raise Malformed('usage is not an object')
    total_cw = _int(usage.get('cache_creation_input_tokens'))
    split = usage.get('cache_creation')
    if isinstance(split, dict) and ('ephemeral_5m_input_tokens' in split or 'ephemeral_1h_input_tokens' in split):
        cw5, cw1h = _int(split.get('ephemeral_5m_input_tokens')), _int(split.get('ephemeral_1h_input_tokens'))
    elif split is not None and not isinstance(split, dict):
        raise Malformed('cache_creation is not an object')
    else:
        cw5, cw1h = total_cw, 0
    counts = {'in': _int(usage.get('input_tokens')), 'cw5': cw5, 'cw1h': cw1h,
              'cr': _int(usage.get('cache_read_input_tokens')), 'out': _int(usage.get('output_tokens'))}
    counts['ctx'] = counts['in'] + counts['cw5'] + counts['cw1h'] + counts['cr']
    return counts


def _add(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in ('in', 'cw5', 'cw1h', 'cr', 'out', 'ctx')}


def message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
    return ''


def tool_signatures(content) -> list[str]:
    out = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'tool_use' and isinstance(block.get('name'), str):
                canonical = json.dumps(block.get('input'), sort_keys=True, ensure_ascii=False, default=str)
                out.append(short_hash(block['name'] + '\0' + canonical))
    return out


def assistant_calls(obj: dict) -> list[dict]:
    """Records for one `assistant` line: [] when it is not counted (synthetic, no usage); Malformed when broken."""
    msg = obj.get('message')
    if not isinstance(msg, dict):
        raise Malformed('message is not an object')
    model = msg.get('model')
    if model == '<synthetic>' or 'usage' not in msg or msg.get('usage') is None:
        return []
    if not isinstance(model, str) or not model:
        raise Malformed('model missing')
    msg_id = msg.get('id')
    if not isinstance(msg_id, str) or not msg_id:
        raise Malformed('message id missing')
    usage = msg['usage']
    if not isinstance(usage, dict):
        raise Malformed('usage is not an object')
    content = msg.get('content')
    text = message_text(content).strip()
    base = {'model': model, 'tools': tool_signatures(content),
            'text': short_hash(normalize_text(text)) if text else None}
    iterations = usage.get('iterations')
    calls = []
    if isinstance(iterations, list) and iterations:
        main = None
        for i, item in enumerate(iterations):
            if not isinstance(item, dict):
                raise Malformed('iteration is not an object')
            if item.get('type') == 'message':
                main = _add(main or {}, usage_of(item))
            elif item.get('type') == 'advisor_message':
                adv_model = item.get('model') if isinstance(item.get('model'), str) and item.get('model') else model
                calls.append({'id': f'{msg_id}#advisor{i}', 'kind': 'advisor', 'model': adv_model, 'tools': [],
                              'text': None, **usage_of(item)})
        main = main if main is not None else usage_of(usage)
    elif iterations is not None and not isinstance(iterations, list):
        raise Malformed('iterations is not a list')
    else:
        main = usage_of(usage)
    calls.insert(0, {'id': msg_id, 'kind': 'main', **base, **main})
    return calls


def is_turn_start(obj: dict) -> bool:
    if obj.get('type') != 'user' or obj.get('isMeta') is True or obj.get('isSidechain') is True:
        return False
    msg = obj.get('message')
    if not isinstance(msg, dict):
        return False
    content = msg.get('content')
    if isinstance(content, list):
        kinds = {b.get('type') for b in content if isinstance(b, dict)}
        return bool(kinds) and kinds != {'tool_result'}
    return isinstance(content, str)


def classify_origin(obj: dict, prefixes: dict) -> str:
    """human, task, peer, child, app, routine (set later from the app record), compact or other."""
    if obj.get('isCompactSummary') is True:
        return 'compact'
    for value in ((obj.get('origin') or {}).get('kind') if isinstance(obj.get('origin'), dict) else None,
                  obj.get('turnOrigin'), obj.get('promptSource')):
        if isinstance(value, str) and value:
            return ORIGIN_KINDS.get(value.strip().lower(), 'other')
    text = message_text((obj.get('message') or {}).get('content')).lstrip()
    for prefix, origin in prefixes.items():
        if text.startswith(prefix):
            return origin
    return 'human'


def discover(projects_dir: str) -> list[tuple[str, str, str | None]]:
    """(path, session, agent) for every transcript; agent is None for main transcripts."""
    out = []
    base = glob.escape(projects_dir)
    for path in sorted(glob.glob(os.path.join(base, '*', '*.jsonl'))):
        out.append((path, os.path.basename(path)[:-len('.jsonl')], None))
    for path in sorted(glob.glob(os.path.join(base, '*', '*', 'subagents', '*.jsonl'))):
        session = os.path.basename(os.path.dirname(os.path.dirname(path)))
        out.append((path, session, os.path.basename(path)[:-len('.jsonl')]))
    return out


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d')


def _read_new_lines(path: str, cursor: dict):
    """New complete lines from the cursor, resetting it on a replaced or truncated file. Yields (lineno, bytes)."""
    st = os.stat(path)
    if cursor.get('inode') != st.st_ino or st.st_size < cursor.get('offset', 0):
        cursor.clear()
        cursor.update(inode=st.st_ino, offset=0, line=0, turn=None, skipped=0)
    with open(path, 'rb') as fh:
        fh.seek(cursor['offset'])
        data = fh.read()
    end = data.rfind(b'\n')
    if end < 0:
        return []
    lines = []
    for raw in data[:end].split(b'\n'):
        cursor['line'] += 1
        lines.append((cursor['line'], raw))
    cursor['offset'] += end + 1
    cursor['size'] = st.st_size
    return lines


def _meta_of(path: str) -> dict:
    meta_path = path[:-len('.jsonl')] + '.meta.json'
    try:
        with open(meta_path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def process_file(path, session, agent, cursor, sessions, cfg, calls, turns):
    try:
        lines = _read_new_lines(path, cursor)
    except OSError:
        cursor.update(unreadable=True, skipped=1)
        return
    cursor.pop('unreadable', None)
    info = sessions.setdefault(session, {})
    if agent is not None:
        sub = info.setdefault('agents', {}).setdefault(agent, {})
        meta = _meta_of(path)
        if isinstance(meta.get('description'), str):
            sub['description'] = meta['description']
    for lineno, raw in lines:
        if not raw.strip():
            continue
        loc = f'{path}:{lineno}'
        try:
            obj = json.loads(raw.decode('utf-8'))
            if not isinstance(obj, dict):
                raise Malformed('line is not an object')
            if isinstance(obj.get('cwd'), str) and obj['cwd'] and not info.get('cwd'):
                info['cwd'] = obj['cwd']
            kind = obj.get('type')
            if kind == 'user':
                if agent is not None:
                    if 'first_prompt' not in sub and is_turn_start(obj):
                        sub['first_prompt'] = message_text(obj['message'].get('content'))[:2000]
                    continue
                if not is_turn_start(obj):
                    continue
                ts = C.parse_time(obj.get('timestamp'))
                if ts is None:
                    raise Malformed('timestamp missing')
                turn_id = obj.get('uuid') if isinstance(obj.get('uuid'), str) and obj.get('uuid') else loc
                cursor['turn'] = turn_id
                turns.append({'id': turn_id, 'session': session, 'ts': ts,
                              'origin': classify_origin(obj, cfg['origin_text_prefixes']), 'loc': loc})
            elif kind == 'assistant':
                found = assistant_calls(obj)
                if not found:
                    continue
                ts = C.parse_time(obj.get('timestamp'))
                if ts is None:
                    raise Malformed('timestamp missing')
                for call in found:
                    if agent is not None and call['kind'] == 'main':
                        call['kind'] = 'subagent'
                    call.update(session=session, agent=agent, ts=ts, loc=loc,
                                turn=cursor.get('turn') if agent is None else None)
                    calls.append(call)
        except (Malformed, ValueError, UnicodeDecodeError, AttributeError, TypeError):
            cursor['skipped'] = cursor.get('skipped', 0) + 1


def _append(dirname: str, records: list[dict]) -> None:
    by_day = {}
    for rec in records:
        by_day.setdefault(day_of(rec['ts']), []).append(rec)
    ensure_dir(dirname)
    for day, recs in by_day.items():
        with open(os.path.join(dirname, day + '.jsonl'), 'a', encoding='utf-8') as fh:
            for rec in recs:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + '\n')


def prune(state_dir: str, now_ts: float, retention_days: float) -> int:
    """Delete day files older than the retention window; findings are never touched."""
    cutoff = day_of(now_ts - retention_days * 86400)
    removed = 0
    for sub in ('calls', 'turns'):
        for path in glob.glob(os.path.join(glob.escape(state_dir), sub, '*.jsonl')):
            if os.path.basename(path)[:-len('.jsonl')] < cutoff:
                os.remove(path)
                removed += 1
    return removed


def collect(cfg: dict, now_ts: float) -> dict:
    state_dir = C.path(cfg, 'state_dir')
    ensure_dir(state_dir)
    with Locked(os.path.join(state_dir, 'collect')):
        cursors = read_json(os.path.join(state_dir, 'cursors.json'), {}, aside=True)
        sessions = read_json(os.path.join(state_dir, 'sessions.json'), {}, aside=True)
        calls, turns = [], []
        for path, session, agent in discover(C.path(cfg, 'projects_dir')):
            cursor = cursors.setdefault(path, {})
            if not isinstance(cursor, dict):
                cursor = cursors[path] = {}
            process_file(path, session, agent, cursor, sessions, cfg, calls, turns)
        _append(os.path.join(state_dir, 'calls'), calls)
        _append(os.path.join(state_dir, 'turns'), turns)
        write_json(os.path.join(state_dir, 'cursors.json'), cursors)
        write_json(os.path.join(state_dir, 'sessions.json'), sessions)
        removed = prune(state_dir, now_ts, cfg['retention_days'])
    return {'calls': len(calls), 'turns': len(turns), 'pruned_files': removed}


def skipped_lines(cfg: dict) -> int:
    cursors = read_json(os.path.join(C.path(cfg, 'state_dir'), 'cursors.json'), {})
    return sum(c.get('skipped', 0) for c in cursors.values() if isinstance(c, dict) and isinstance(c.get('skipped'), int))
