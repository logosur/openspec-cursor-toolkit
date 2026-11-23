"""The Stop check that keeps the final message in Spanish."""
import os
import re
import traceback

from . import transcripts, util


# ---------------------------------------------------------------- language
# The developer reads in Spanish, and long sessions drift into English. The Stop hook sends back a closing message
# written in English.
_EN_WORDS = frozenset('the and is are was were to of that this with for it not have has will but from which been '
                      'there their would should because when what its into than then still only'.split())
_ES_WORDS = frozenset('el la los las de que y en se por con para una un es no lo del al ha su sus como pero mas ya '
                      'esta este porque cuando sin sobre tambien hay'.split())
_RE_CODE = re.compile(r'```.*?```|`[^`\n]*`|https?://\S+', re.S)
_RE_WORD = re.compile(r"[a-zñ']+")
ENGLISH_MIN_WORDS = 40


def looks_english(text):
    """True when a closing message is prose in English: code, paths and links aside, English function words outnumber
    Spanish ones three to one. Short messages are never judged."""
    words = _RE_WORD.findall(util.fold_text(_RE_CODE.sub(' ', text or '')).replace('ñ', 'n'))
    if len(words) < ENGLISH_MIN_WORDS:
        return False
    en = sum(1 for w in words if w in _EN_WORDS)
    es = sum(1 for w in words if w in _ES_WORDS)
    return en >= 8 and en >= 3 * max(es, 1) and en / len(words) >= 0.12


def final_text(payload, session):
    text = payload.get('last_assistant_message')
    if isinstance(text, str) and text.strip():
        return text
    path = payload.get('transcript_path')
    if not (isinstance(path, str) and os.path.isfile(path)):
        path = transcripts.session_files(str(session or ''), payload.get('cwd'))[0]
    return transcripts.last_assistant_text(path) if path else ''


def english_block(payload, session):
    """Stop-hook reason when the closing message is in English, or ''. Never raises."""
    try:
        if not looks_english(final_text(payload, session)):
            return ''
        util.hook_log('hook.log', f'{str(session)[:8]} stop-english block')
        return ('Tu mensaje final está en inglés. El desarrollador lee en español: vuelve a '
                'escribirlo entero en español, en prosa llana, y a partir de ahora escribe en español todo lo que se ve en '
                'la sesión, también entre herramientas. Código, rutas, identificadores y comandos van en inglés. Si el '
                'texto en inglés es una cita o un entregable que el desarrollador pidió en inglés, termina igual.')
    except Exception:
        try:
            util.hook_log('hook-errors.log', 'stop-english\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
        return ''
