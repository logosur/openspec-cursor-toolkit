"""The developer's messages that a supervisor has not attended yet."""
import json
import os
import re
import time
import traceback
from datetime import datetime

from . import backlog, lock as lock_mod, util


# ---------------------------------------------------------------- the developer's own messages to the supervisor
# A supervisor can answer something else than what the developer asked and then compact, and the summary drops the
# question. The Stop hook quotes each message the developer typed in the supervisor's session once, at the first turn
# end after it, and asks the supervisor to check it answered exactly that; after a compaction the SessionStart context
# repeats the developer's recent messages word for word.
DEV_MSG_TAIL_BYTES = 8 * 1024 * 1024   # transcripts reach 100+ MB; the message is in the last minutes or hours
DEV_MSG_MAX_AGE_S = 6 * 3600
DEV_MSG_QUOTE = 600
_RE_LEADING_CONTEXT = re.compile(r'^\s*(?:<(system-reminder|artifact-view-context)\b[^>]*?(?:/>|>.*?</\1>)\s*)+', re.S)
_RE_JUST_GO_ON = re.compile(r'^(continua|continue|sigue|seguimos|adelante|ok|vale|si|reanuda|go on|intentalo de nuevo'
                            r'|vuelve a intentarlo)\W*$')
_RE_USER_LINE = re.compile(rb'"type":\s*"user"')
_AUTOMATIC_PREFIXES = ('<', '[', 'This session is being continued', 'Stop hook feedback', 'Another Claude session',
                       'Base directory for this skill', '(Re-invocation')


def developer_messages(path, now=None, max_age=DEV_MSG_MAX_AGE_S, go_on=False):
    """[(epoch, uuid, text)] the developer typed in this transcript in the last `max_age` s, oldest first.

    Typed by the developer: a user record with no tool result, not meta, not a compaction summary, whose origin is human (or
    absent, in older records), once the context blocks the app puts in front are stripped. Notifications, other
    sessions' messages, hook feedback, slash commands and a bare «continúa» are left out."""
    now = time.time() if now is None else now
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as fh:
            fh.seek(max(0, size - DEV_MSG_TAIL_BYTES))
            data = fh.read()
    except (OSError, TypeError):
        return []
    out = []
    for line in data.split(b'\n'):
        if b'tool_result' in line or not _RE_USER_LINE.search(line):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get('type') != 'user' or rec.get('isMeta') or rec.get('isCompactSummary'):
            continue
        origin = rec.get('origin')
        if isinstance(origin, dict) and origin.get('kind') not in (None, 'human'):
            continue
        content = (rec.get('message') or {}).get('content')
        if isinstance(content, list):
            content = '\n'.join(str(it.get('text') or '') for it in content
                                if isinstance(it, dict) and it.get('type') == 'text')
        text = _RE_LEADING_CONTEXT.sub('', content if isinstance(content, str) else '').strip()
        if not text or text.startswith(_AUTOMATIC_PREFIXES) or (not go_on and _RE_JUST_GO_ON.match(util.fold_text(text))):
            continue
        ts = util.parse_ts(rec.get('timestamp'))
        if ts is None or now - ts > max_age or ts > now + 60:
            continue
        out.append((ts, str(rec.get('uuid') or f'{ts:.3f}'), text))
    return out


def quote_messages(msgs):
    return ' '.join(f'[{datetime.fromtimestamp(ts).strftime("%H:%M")}] «{" ".join(text.split())[:DEV_MSG_QUOTE]}»'
                    for ts, _, text in msgs)


def developer_block(owner, local, payload, now=None):
    """Stop-hook reason quoting the developer's messages in this session not quoted before (each one once), or ''.
    On guard a bare «continúa» / «sigue» counts too: to a supervisor standing guard it says that the developer sees
    work where the supervisor sees none."""
    msgs = developer_messages(payload.get('transcript_path'), now, go_on=backlog.on_guard(owner))
    if not msgs:
        return ''
    path = os.path.join(util.home(), 'answered', (owner.get('key') or 'lock') + '.json')
    with lock_mod.Store():
        try:
            with open(path) as fh:
                done = json.load(fh)
        except (OSError, ValueError):
            done = {}
        done = {k: v for k, v in (done if isinstance(done, dict) else {}).items()
                if util.num(v) is not None and time.time() - v < 2 * DEV_MSG_MAX_AGE_S}
        unseen = [m for m in msgs if m[1] not in done]
        if not unseen:
            return ''
        fresh = unseen[-3:]   # the newest three are quoted; older unseen ones are taken as seen with them
        for m in unseen:
            done[m[1]] = time.time()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f'.{os.getpid()}.tmp'
        with open(tmp, 'w') as fh:
            json.dump(done, fh)
        os.replace(tmp, path)
    one = len(fresh) == 1
    work = (f'Si {"ese mensaje" if one else "alguno"} pide trabajo, lo da por supuesto o describe lo que espera recibir, '
            f'es un objetivo nuevo: anótalo en el registro y lanza su primer paso en este turno, sin esperar a que lo '
            f'repita. ')
    if backlog.on_guard(owner):
        # on guard the developer's message is the order that opens the next cycle, until the supervisor leaves guard
        # or says why not
        last = fresh[-1]
        try:
            with lock_mod.Store() as store:
                cur = store.read(owner.get('key'))
                if cur is not None and cur.get('session_id') == owner.get('session_id'):
                    cur['guard_order'] = {'at': datetime.fromtimestamp(last[0]).strftime('%d-%m %H:%M'),
                                          'uuid': last[1], 'text': ' '.join(last[2].split())[:DEV_MSG_QUOTE]}
                    store.write(owner.get('key'), cur)
        except Exception:
            util.hook_log('hook-errors.log', traceback.format_exc().rstrip())
        work = (f'Estás de guardia: si {"ese mensaje" if one else "alguno"} pide trabajo, lo da por supuesto o describe '
                f'lo que espera recibir, es la orden que abre el ciclo siguiente. Sal de guardia (`supervisor-lock beat '
                f'--session {local} --phase F1`), abre un registro con ese objetivo y lanza su primer paso en este turno. '
                f'Solo si no pide ni implica trabajo: `supervisor-lock beat --session {local} --no-work "<por qué>"`. '
                f'Anotarlo como decisión y seguir de guardia es dejar la supervisión parada con trabajo pendiente. ')
    return (f'Antes de terminar el turno: el desarrollador te ha escrito en esta sesión {quote_messages(fresh)}. '
            f'Comprueba que ya {"le has contestado eso" if one else "has contestado cada uno de esos mensajes"}, en '
            f'prosa llana, en español y en esta sesión: lo que pregunta o pide, no otra cosa que estés haciendo. Si no, '
            f'hazlo ahora, antes de seguir con lo tuyo: si pide explicaciones, dáselas; si pide un cambio, dile qué haces '
            f'y cuándo. {work}Si ya está contestado y no hay trabajo que lanzar, termina sin repetir la respuesta ni '
            f'escribir «ya te contesté»: como mucho, una línea con lo que estás haciendo. Un mensaje del desarrollador sin '
            f'contestar es una orden ignorada.')


def developer_context(payload, now=None):
    """SessionStart (compact) text repeating the developer's recent messages word for word, or ''."""
    msgs = developer_messages(payload.get('transcript_path'), now)[-3:]
    if not msgs:
        return ''
    return (f' Mensajes que te escribió el desarrollador en esta sesión en las últimas horas, literales por si el resumen '
            f'los ha perdido: {quote_messages(msgs)}. Si alguno no tiene todavía respuesta tuya, contéstalo antes que '
            f'nada.')
