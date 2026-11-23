"""The closing verdict a session writes in its last message."""
import json
import os
import re
import time

from . import closable, lock as lock_mod, transcripts, util


# A session that answered /cierra-sesion «Sí, puedes cerrar» has finished: it is closable at once (no 2 h of quiet),
# `wait --owner` announces it once (any phase), the Stop hook asks for it, and no hold keeps it open. Remote Control
# being on is never a reason to keep it: it can be on in almost every session without anyone asking for it.
CLOSE_VERDICT = 'si, puedes cerrar'
_VERDICT_LEAD = ' \t\r\n*_#>`«"'
_RE_REMOTE_CONTROL = re.compile(r'remote[\s_-]*control', re.I)


def close_verdict(row):
    """{since, text} when the last message of the session's main transcript (its trailing assistant text, after the
    last tool call or result) opens with the /cierra-sesion verdict «Sí, puedes cerrar» and nobody wrote to the
    session after it; else None."""
    main = transcripts.session_files(row.get('cli'), row.get('cwd'))[0] if row.get('cli') else None
    final = []  # the text blocks of the last message, newest first
    for rec in reversed(transcripts.conv_records(main) if main else []):
        if rec.get('isMeta'):
            continue
        content = (rec.get('message') or {}).get('content')
        items = transcripts.content_items(rec)
        texts = [content] if isinstance(content, str) else [str(it.get('text') or '') for it in items
                                                            if it.get('type') == 'text']
        texts = [t for t in texts if t.strip()]
        if rec['type'] == 'user':
            if texts:
                return None  # somebody wrote to it after its last words
            break  # a tool result: the last message starts after it
        if rec.get('isApiErrorMessage'):
            return None
        if any(it.get('type') == 'tool_use' for it in items):
            break
        final.extend((rec['_ts'], t) for t in reversed(texts))
    if not final:
        return None
    since, first = final[-1]
    if not util.fold_text(first.lstrip(_VERDICT_LEAD)).startswith(CLOSE_VERDICT):
        return None
    return {'since': since, 'text': first.strip()[:100]}


def announce_verdicts(key, entries, now=None):
    """`CLOSABLE <id> cierre-ok` lines for the sessions whose «Sí, puedes cerrar» was not announced yet: once per
    (id, verdict time) in <home>/verdicts/<key>.json, pairs older than 48 h pruned. Not a quiet level, so a verdict given
    before the wait started is still announced."""
    now = time.time() if now is None else now
    path = os.path.join(util.home(), 'verdicts', key + '.json')
    lines = []
    with lock_mod.Store():
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        data = {k: v for k, v in (data if isinstance(data, dict) else {}).items()
                if util.num(v) is not None and now - v < closable.HOLD_HISTORY_S}
        changed = False
        for e in entries:
            pair = f'{e["id"]}@{int(e["verdict"])}'
            if pair not in data:
                data[pair] = now
                lines.append(f'CLOSABLE {e["id"]} cierre-ok')
                changed = True
        if changed:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + f'.{os.getpid()}.tmp'
            with open(tmp, 'w') as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
    return lines
