"""Stop checks of a supervised session."""
import json
import os
import re
import traceback

from . import ask_gate, deny, language, session_roles, transcripts, util


_CLOSERS = '*_`»"\')\u201d\u2019 \t'
ASK_TAIL_LINES = 12
ASK_TAIL_CHARS = 40


def question_lines(text):
    """The non-empty lines of `text` that can hold a question to the developer: no fenced code, no `>` quotes and no
    «…» spans (a line that is entirely one «…» quote is kept: that is a question with its closer)."""
    out = []
    fenced = False
    for raw in (text or '').splitlines():
        line = raw.strip()
        if line.startswith('```') or line.startswith('~~~'):
            fenced = not fenced
            continue
        if fenced or not line or line.startswith('>'):
            continue
        if not (line.startswith('«') and line.endswith('»') and line.count('«') == 1):
            line = re.sub(r'«[^»]*»', '', line).strip()
        if line:
            out.append(line)
    return out


def ends_with_question(text):
    """True when the message leaves a question to the developer open (widened):
    any of the last ASK_TAIL_LINES lines ends in `?` once trailing closers (markdown, quotes) are gone, or the last
    paragraph has a `?` followed by a short tail (<= ASK_TAIL_CHARS), such as `¿Despliego? (responde sí o no)`."""
    paragraphs = [[]]
    for raw in (text or '').splitlines():
        if raw.strip():
            paragraphs[-1].append(raw)
        elif paragraphs[-1]:
            paragraphs.append([])
    lines = question_lines(text)
    if any(l.rstrip().rstrip(_CLOSERS).endswith('?') for l in lines[-ASK_TAIL_LINES:]):
        return True
    last = question_lines('\n'.join(paragraphs[-1]))
    joined = ' '.join(last)
    cut = joined.rfind('?')
    return cut != -1 and len(joined[cut + 1:].strip()) <= ASK_TAIL_CHARS


def stop_supervised_question(payload):
    """The Stop block json when a supervised session (not owner, not mailbox) ends its turn on a question, else ''."""
    session = str(payload.get('session_id') or '')
    try:
        role, lock = session_roles.session_role(session, payload.get('cwd'))
        if role != 'supervised':
            return ''
        text = payload.get('last_assistant_message')
        if not (isinstance(text, str) and text.strip()):
            path = payload.get('transcript_path')
            if not (isinstance(path, str) and os.path.isfile(path)):
                path = transcripts.session_files(session, payload.get('cwd'))[0]
            text = transcripts.last_assistant_text(path) if path else ''
        if not ends_with_question(text):
            return ''
        if ask_gate.developer_present(payload, session) is not None:
            # the developer is driving this session in person, so a question to them waits on nobody
            util.hook_log('hook.log', f'{session[:8]} stop-supervised-question allow-present')
            return ''
        lock = lock or {}
        who = lock.get('title') or lock.get('session_id') or 'la supervisora'
        project = lock.get('project') or 'este proyecto'
        util.hook_log('hook.log', f'{session[:8]} stop-supervised-question block')
        reason = (f'Tu mensaje final termina en una pregunta, y esta sesión la supervisa «{who}» ({project}): el '
                  f'desarrollador no contesta preguntas hasta la tanda final y nadie debe quedarse esperándole. Si es '
                  f'una duda para decidir, decídela con lo documentado o con el panel ({deny.PANEL_SKILL}), o pásala a '
                  f'decisiones_abiertas de tu informe para la supervisora, y sigue con lo que no dependa de ella. Si no '
                  f'es una pregunta para el desarrollador (una pregunta retórica, una cita), termina igual.')
        return json.dumps({'decision': 'block', 'reason': reason})
    except Exception:
        try:
            util.hook_log('hook-errors.log', f'stop-supervised-question {session[:8]}\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
        return ''  # fail open


def stop_supervised_english(payload):
    """The Stop block json when a session of a supervised project ends its turn in English, else ''."""
    session = str(payload.get('session_id') or '')
    try:
        role, _ = session_roles.session_role(session, payload.get('cwd'))
        if role not in ('supervised', 'mailbox'):
            return ''
        reason = language.english_block(payload, session)
        return json.dumps({'decision': 'block', 'reason': reason}) if reason else ''
    except Exception:
        return ''  # fail open
