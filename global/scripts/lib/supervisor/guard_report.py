"""The report a supervisor owes the developer from time to time."""
import os
import re
import time
import traceback

from . import backlog, language, providers, util


# ---------------------------------------------------------------- periodic report
# The skill asks for a status report («parte», reference/vigilancia.md) every so often; text alone did not get it
# written, so the Stop hook asks for it when it is due.
REPORT_EVERY_S = 30 * 60
REPORT_EVERY_GUARD_S = 2 * 60 * 60
REPORT_MIN_CHARS = 350
REPORT_MIN_PROOFS = 2
_RE_PROOF = re.compile(r'`[^`\n]{3,}`')


def looks_report(text):
    """True when a closing message is a status report: enough prose and at least two commands or data quoted as proof."""
    text = text or ''
    prose = language._RE_CODE.sub(' ', text)
    return len(prose.strip()) >= REPORT_MIN_CHARS and len(_RE_PROOF.findall(text)) >= REPORT_MIN_PROOFS


def report_stamp(owner):
    return os.path.join(util.home(), 'backlog', (owner.get('key') or 'lock') + '.last-report')


def report_block(owner, local, payload, session, now=None):
    """Stop-hook reason for a supervisor whose last status report to the developer is older than REPORT_EVERY_S (two
    hours on guard) and whose closing message is not one; '' otherwise. A closing message that is a report resets the
    clock. Never raises."""
    try:
        if os.environ.get('SUPERVISOR_SELFTEST_NO_REPORT') or providers.pause_of(owner.get('checkout')):
            return ''  # the variable is set only by the self-test, around the checks of the other Stop blocks
        now = time.time() if now is None else now
        stamp = report_stamp(owner)
        if looks_report(language.final_text(payload, session)):
            os.makedirs(os.path.dirname(stamp), exist_ok=True)
            with open(stamp, 'w') as fh:
                fh.write(str(int(now)))
            os.utime(stamp, (now, now))
            return ''
        every = REPORT_EVERY_GUARD_S if backlog.on_guard(owner) else REPORT_EVERY_S
        age = now - util.file_mtime(stamp)
        if age < every:
            return ''
        since = 'nunca' if util.file_mtime(stamp) <= 0 else f'hace {int(age // 60)} min'
        util.hook_log('hook.log', f'{owner.get("key")} {local} stop-report block (last report {since})')
        return (f'Antes de terminar el turno: toca parte de estado para el desarrollador (el último, {since}; toca cada '
                f'{every // 60} min): sin él, el desarrollador no sabe en qué está la supervisión. Escríbelo como '
                f'mensaje final, en español y en prosa llana, según «Parte» de reference/vigilancia.md: qué está pasando '
                f'(qué hace cada sesión o subagente, qué se espera, de quién y desde cuándo), qué has comprobado ahora mismo '
                f'con su comando y su dato entre comillas invertidas (al menos dos: heavy-job status, supervisor-lock '
                f'sessions, git log -1, cloud-tests status…), qué has lanzado mientras y qué harás si falla. Sin pregunta '
                f'al final. El hook lo reconoce por su longitud y sus pruebas; un «todo bien» corto no cuenta.')
    except Exception:
        try:
            util.hook_log('hook-errors.log', 'stop-report\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
        return ''
