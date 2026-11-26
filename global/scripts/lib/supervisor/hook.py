"""The hook entry: PreToolUse, SessionStart and Stop decisions."""
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime

from . import (
    ask_gate, backlog, census, closable, closing, cloud,
    deny, developer, guard_report, interrupted, language, lint,
    lock as lock_mod, providers, supervised, util,
)


def wait_armed_in_proc(owner_id):
    """Fallback when the hook payload has no background_tasks: look for `supervisor-lock wait --owner ID`."""
    for entry in os.listdir('/proc'):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        try:
            with open(f'/proc/{entry}/cmdline', 'rb') as fh:
                argv = fh.read().decode('utf-8', 'replace').split('\0')
        except OSError:
            continue
        # older supervisors arm `wait --exclude <own id>`, which is the same watcher
        if 'wait' in argv and any(os.path.basename(a) == 'supervisor-lock' for a in argv) and any(
                a in (f'--owner={owner_id}', f'--exclude={owner_id}')
                or (a in ('--owner', '--exclude') and i + 1 < len(argv) and argv[i + 1] == owner_id)
                for i, a in enumerate(argv)):
            return True
    return False


# the watcher as a session writes it: the script by its path or through a variable (`L=…/supervisor-lock; $L wait …`),
# never `wait-closer`, which is another session's watcher
_RE_WAIT_COMMAND = re.compile(r'supervisor-lock(?![\w-]).*?(?<![\w-])wait(?![\w-])', re.S)


def wait_armed(payload, owner_id):
    tasks = payload.get('background_tasks')
    if not isinstance(tasks, list):
        return wait_armed_in_proc(owner_id)
    for task in tasks:
        if not isinstance(task, dict) or str(task.get('status') or 'running').lower() not in ('running', 'pending'):
            continue
        for field in ('command', 'description'):
            text = task.get(field)
            if isinstance(text, str) and owner_id in text and _RE_WAIT_COMMAND.search(text):
                return True
    # a watcher armed through a wrapper or an alias does not name the script in its command: the process does
    return wait_armed_in_proc(owner_id)


def paused_limit_block(owner, local):
    """Stop-hook reason for an owner whose lock is still paused for the usage limit while the account has usage, or ''.
    Bounded like the other reasons of the chain: one block per turn (stop_hook_active)."""
    if not lock_mod.paused_for_limit(owner) or providers.account_has_usage() is not True:
        return ''
    return (f'Tienes el cerrojo de supervisor de {owner.get("project")} en pausa por el límite de uso, pero la cuenta '
            f'tiene uso ahora (lo dice el uso real, no la hora del límite). El límite de uso no es motivo de pausa: antes '
            f'de terminar el turno, mira get_usage, ejecuta supervisor-lock beat --session {local} --state running y '
            f'sigue el ciclo desde F1. Si lo único que queda espera a un tercero, dilo con --state paused --third-party '
            f'"<qué espera y de quién>".')


def hook_decide(raw):
    """What the hook prints for a payload (a json string): '' or a json document."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError('hook payload is not a json object')
    event = payload.get('hook_event_name')
    if event == 'PreToolUse' and not ask_gate.asks_developer(payload):
        return ''  # fires on every tool call of every session: only a question needs the lock and gate lookups
    locks = lock_mod.read_locks()
    if not locks:
        # nobody supervises anything: Stop / SessionStart have nothing to do; a developer question meets the ask gate
        return ask_gate.ask_gate_decide(payload, locks) if event == 'PreToolUse' else ''
    session = payload.get('session_id')
    local = census.local_owner_of(session, locks)
    if local is None:
        if event == 'Stop' and not payload.get('stop_hook_active'):
            closer, closer_lock = closing.closer_lock_of(session, locks)
            if closer:
                try:
                    reason = closing.closer_stop(closer, closer_lock, payload) or language.english_block(payload, session)
                except Exception:
                    util.hook_log('hook-errors.log', traceback.format_exc().rstrip())
                    reason = ''
                return json.dumps({'decision': 'block', 'reason': reason}) if reason else ''
            # a supervised session may not end its turn on a question, nor in English
            return supervised.stop_supervised_question(payload) or supervised.stop_supervised_english(payload)
        return ask_gate.ask_gate_decide(payload, locks) if event == 'PreToolUse' else ''
    owner = locks[local]
    paused = providers.pause_of(owner.get('checkout')) if event in ('Stop', 'SessionStart') else None
    if paused:
        # The developer paused the project (optional project-pause provider): its supervisor may end any turn, and on
        # start it does nothing
        if event == 'SessionStart':
            context = (f'El proyecto {owner.get("project")} está en pausa por orden del desarrollador desde '
                       f'{paused.get("paused_at")}. No retomes la supervisión, no armes vigilantes ni lances '
                       f'sesiones: espera a que el desarrollador ordene reanudarlo.')
            return json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': context}})
        return ''
    where = (f'{owner.get("project")} (cerrojo {owner.get("key")}, fase {owner.get("phase") or "-"}, '
             f'ronda {owner.get("round")}')
    if event == 'PreToolUse':
        # An owner the developer is driving in person (writing in it right now, or asking to be asked, or giving an
        # order another gate wants confirmed in a dialog) may ask exactly as a supervised session may
        # (present_verdict); otherwise every question is denied, and a plan or an offer card still waits for nobody.
        if not ask_gate.parked_tool_kind(payload):
            try:
                verdict = ask_gate.present_verdict(payload, session, time.time(), ask_gate.ask_gate_presence_minutes())
            except Exception:
                ask_gate.ask_gate_error(f'{str(session)[:8]} owner presence\n' + traceback.format_exc().rstrip())
                verdict = None
            if verdict:
                repeated = ask_gate.ask_gate_backstop(payload, session)  # never raises; an answered question is not asked again
                if repeated:
                    return repeated
                ask_gate.ask_gate_log(session, f'allow-{verdict[0]}-owner', payload.get('tool_name'), verdict[1])
                return ''
        ask_gate.ask_gate_log(session, 'owner-deny', payload.get('tool_name'), f'lock owner {local}')
        if ask_gate.parked_tool_kind(payload):
            return deny.deny_parked_tool(ask_gate.parked_tool_kind(payload), owner)
        return deny.deny_question(owner, local)
    if event == 'SessionStart':
        head = (f'Esta sesión es la supervisora de {where}, último latido hace '
                f'{util.age_seconds(owner.get("heartbeat")) // 60} min). ')
        if payload.get('source') == 'compact':  # the skill core is still whole in the context: do not load it twice
            context = (head + f'El contexto se ha compactado: la vigilancia anterior ya no existe, pero el núcleo de la '
                       f'skill supervisa-sesiones sigue entero en tu contexto, así que no la vuelvas a invocar. Rearma '
                       f'supervisor-lock wait --owner {local} en segundo plano y haz un tick. Para el detalle de una fase, '
                       f'lee solo su fichero de referencia (el índice está en el núcleo). Del registro, lee solo las '
                       f'secciones de estado, nunca el fichero entero.')
            try:
                context += developer.developer_context(payload)
            except Exception:
                util.hook_log('hook-errors.log', traceback.format_exc().rstrip())
        else:
            context = (head + f'Si el proceso es nuevo o el contexto se ha compactado, la vigilancia anterior ya no existe: '
                       f'antes de nada, vuelve a invocar la skill supervisa-sesiones, rearma supervisor-lock wait --owner '
                       f'{local} en segundo plano y haz un tick. Del registro, lee solo las secciones de estado, nunca el '
                       f'fichero entero.')
        return json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': context}})
    if event == 'Stop' and not payload.get('stop_hook_active'):
        mtime = lint.skill_newer(owner)  # before the watcher check: an old watcher runs old code and never says so
        if mtime is not None and util.num(owner.get('skill_seen')) is None:
            reason = (f'Tienes el cerrojo de supervisor de {owner.get("project")} y no consta que hayas cargado la skill '
                      f'supervisa-sesiones. Antes de terminar el turno: invócala con la herramienta Skill, sigue su '
                      f'arranque (incluido abrir la sesión de preguntas y registrarla con beat --mailbox) y confirma con '
                      f'supervisor-lock beat --session {local} --skill-seen. Si no vas a supervisar, libera el cerrojo '
                      f'con supervisor-lock release.')
            return json.dumps({'decision': 'block', 'reason': reason})
        if mtime is not None:
            reason = (f'La skill supervisa-sesiones cambió en disco ({datetime.fromtimestamp(mtime).strftime("%H:%M")}) '
                      f'después de que la cargaras. Antes de terminar el turno: vuelve a invocarla, vuelve a leer las '
                      f'referencias que estés usando, aplica lo nuevo a tu supervisión y confirma con '
                      f'supervisor-lock beat --session {local} --skill-seen. Rearma también '
                      f'el vigilante: el que tienes arrancó con el código anterior.')
            return json.dumps({'decision': 'block', 'reason': reason})
    if event != 'Stop':
        return ''
    if wait_armed(payload, local):
        # only once the watcher check passed, so this block never uses up the one block of the turn
        if not payload.get('stop_hook_active'):
            try:
                # the developer's own messages first; a cut is resumed, never closed
                reason = (developer.developer_block(owner, local, payload) or paused_limit_block(owner, local)
                          or interrupted.cut_block(owner, local)
                          or ('' if closing.closer_attending(owner) else closable.closable_block(owner, local))
                          or cloud.cloud_block(owner, local)
                          or backlog.guard_block(owner, local) or backlog.idle_block(owner, local, payload)
                          or language.english_block(payload, session)
                          or guard_report.report_block(owner, local, payload, session))
            except Exception:
                util.hook_log('hook-errors.log', traceback.format_exc().rstrip())
                reason = ''
            if reason:
                return json.dumps({'decision': 'block', 'reason': reason})
        return ''
    if not payload.get('stop_hook_active'):
        reason = (f'Eres el supervisor de {where}) y vas a terminar el turno sin vigilante: nada te despertaría. '
                  f'Antes de terminar, arma en segundo plano (run_in_background: true): '
                  f'~/.claude/scripts/supervisor-lock wait --owner {local} --timeout 600. Si la supervisión terminó '
                  f'de verdad, con todos sus objetivos verificados, libera el cerrojo: '
                  f'~/.claude/scripts/supervisor-lock release --session {local} --verdict <VEREDICTO>.')
        return json.dumps({'decision': 'block', 'reason': reason})
    util.hook_log('hook.log', f'{owner.get("key")} {local} stopped twice without a watcher armed; not blocked again')
    providers.notify(f'Supervisión sin vigilante: {owner.get("project")}',
           f'La sesión «{owner.get("title") or local}» ha terminado el turno sin vigilante armado y no se la ha '
           f'vuelto a bloquear. Ábrela y escribe «reanuda».')
    return ''


def cmd_hook(args):
    """Stop / SessionStart / PreToolUse hook: never fails the session, prints only a decision or context."""
    raw = ''
    try:
        raw = sys.stdin.read()
        out = hook_decide(raw)
    except Exception:
        trace = traceback.format_exc().rstrip()
        try:
            util.hook_log('hook-errors.log', trace)
        except Exception:
            pass
        if 'PreToolUse' in raw:
            ask_gate.ask_gate_error(trace)  # a broken PreToolUse payload fails open
        return 0
    if out:
        print(out)
    return 0
