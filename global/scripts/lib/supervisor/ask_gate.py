"""The question gate: may this session open a dialog to the developer now."""
import os
import re
import time
import traceback
from datetime import datetime

from . import answered, deny, human_turns, providers, session_roles, settings, transcripts, util


ASK_TOOL = 'AskUserQuestion'
WRAP_UP_TOOL = 'mcp__ccd_turn__wrap_up'
PLAN_TOOL = 'ExitPlanMode'
OFFER_TOOL = 'mcp__ccd_session__start_session'


def parked_tool_kind(payload):
    """'plan' for ExitPlanMode, 'offer' for start_session with initiation "offer" (a card the developer must press),
    else None. Both park the session until the developer answers, like a question."""
    tool = payload.get('tool_name')
    if tool == PLAN_TOOL:
        return 'plan'
    if tool == OFFER_TOOL:
        tool_input = payload.get('tool_input')
        if isinstance(tool_input, dict) and str(tool_input.get('initiation') or '').strip().lower() == 'offer':
            return 'offer'
    return None


def asks_developer(payload):
    """True when a PreToolUse payload is a question for the developer: AskUserQuestion, wrap_up with ask/actions, or
    a tool that waits for the developer's approval (ExitPlanMode, start_session with initiation "offer")."""
    tool = payload.get('tool_name')
    if tool == ASK_TOOL:
        return True
    if parked_tool_kind(payload):
        return True
    if tool == WRAP_UP_TOOL:
        tool_input = payload.get('tool_input')
        if not isinstance(tool_input, dict):
            return False
        ask, actions = tool_input.get('ask'), tool_input.get('actions')
        return bool(isinstance(ask, str) and ask.strip()) or bool(actions)
    return False


# ---------------------------------------------------------------- ask gate
# A session that is NOT a lock owner may not ask the developer while they are away. The deny text sends it to
# the decision panel (hard limits go to ask-queue). Fail open: any error allows the question and is logged.

ASK_GATE_PRESENCE_MIN = settings.PRESENCE_MIN  # minutes of genuine input that count as "present" (env ASK_GATE_PRESENCE_MIN)
ASK_GATE_FRESH_MIN = settings.FRESH_MIN  # the last message must be this recent for presence alone to allow a question (env ASK_GATE_FRESH_MIN)
ASK_GATE_DIALOG_MIN = 10         # minutes a cross-project `deny-dialog` entry lets the session ask once
ASK_GATE_BUDGET_S = 1.2          # time budget of the transcript scan; past it the gate allows
ASK_GATE_MAX_BYTES = 96 << 20


def ask_gate_dir():
    return os.path.expanduser(os.environ.get('ASK_GATE_DIR', '~/.claude/state/ask-gate'))


def ask_gate_xproject_log():
    return os.path.expanduser(os.environ.get('ASK_GATE_XPROJECT_LOG',
                                             '~/.claude/state/cross-project-message-gate/decisions.log'))


def ask_gate_append(name, line):
    os.makedirs(ask_gate_dir(), exist_ok=True)
    with open(os.path.join(ask_gate_dir(), name), 'a') as fh:
        fh.write(line.rstrip('\n') + '\n')


def ask_gate_log(session, decision, tool, reason):
    try:
        clean = re.sub(r'\s+', ' ', str(reason))
        ask_gate_append('decisions.log', '\t'.join((
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), str(session or '')[:8], decision, str(tool or ''), clean)))
    except Exception:
        pass


def ask_gate_error(text):
    try:
        ask_gate_append('errors.log', f'{util.now_iso()} {text}')
    except Exception:
        pass


def ask_gate_presence_minutes():
    try:
        value = float(os.environ.get('ASK_GATE_PRESENCE_MIN', ''))
        if value > 0:
            return value
    except ValueError:
        pass
    return float(ASK_GATE_PRESENCE_MIN)


def ask_gate_fresh_minutes():
    try:
        value = float(os.environ.get('ASK_GATE_FRESH_MIN', ''))
        if value > 0:
            return value
    except ValueError:
        pass
    return float(ASK_GATE_FRESH_MIN)


# The developer's last message, inside the presence window, explicitly asks to be asked (accents and case are folded away first).
_RE_ASK_ME = re.compile(r'\b(?:pregunt[ae]me|pregunta(?:me)?\s+antes|consultame|dame\s+opciones|dejame\s+elegir|elijo\s+yo'
                        r'|quiero\s+(?:elegir|decidir)|ask\s+me)\b')


def asks_to_be_asked(text):
    """True when a developer message explicitly requests to be asked (pregúntame, dame opciones, ask me...)."""
    return bool(_RE_ASK_ME.search(util.fold_text(text)))


def ask_gate_disabled():
    return os.environ.get('ASK_GATE', '').strip().lower() == 'off' \
        or os.path.exists(os.path.join(ask_gate_dir(), 'disabled'))


def recent_deny_dialog(session, now):
    """True when the cross-project gate sent this session to a dialog (`deny-dialog`) within the last minutes."""
    try:
        with open(ask_gate_xproject_log(), 'rb') as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 262144))
            lines = fh.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        cols = line.split('\t')
        if len(cols) < 3 or cols[1] != session[:8] or cols[2] != 'deny-dialog':
            continue
        try:
            when = time.mktime(time.strptime(cols[0], '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            continue
        if -60 <= now - when <= ASK_GATE_DIALOG_MIN * 60:
            return True
    return False


def ask_gate_backstop(payload, session):
    """The deny json when an AskUserQuestion repeats a decision already answered, else ''. Never raises."""
    tool_input = payload.get('tool_input')
    if payload.get('tool_name') != ASK_TOOL or not isinstance(tool_input, dict):
        return ''
    try:
        ids = answered.ask_source_ids(tool_input)
        if ids:
            found = providers.ask_queue_module().find_items(set(ids))
            done = [(i, found[i]) for i in ids if i in found and found[i].get('status') in ('answered', 'closed')]
            if done:
                ask_gate_log(session, 'deny-answered', ASK_TOOL, ', '.join(i for i, _ in done))
                return answered.deny_answered(done)
        mine = [(q, answered.norm_question(q)) for q in answered.ask_questions(tool_input)]
        path = payload.get('transcript_path')
        if not (isinstance(path, str) and os.path.isfile(path)):
            path = transcripts.session_files(session, payload.get('cwd'))[0]
        if mine and path:
            for stamp, question, answer in answered.answered_questions(path, time.time() - answered.ASK_GATE_DUP_HOURS * 3600):
                old = answered.norm_question(question)
                if any(answered.similar_questions(new, old) for _, new in mine):
                    ask_gate_log(session, 'deny-duplicate', ASK_TOOL,
                                 f'same question answered {int(time.time() - stamp)} s ago')
                    return answered.deny_duplicate(question, stamp, answer)
    except Exception:
        ask_gate_error(f'{session[:8]} {ASK_TOOL} backstop\n' + traceback.format_exc().rstrip())
    return ''


def developer_present(payload, session, now=None, minutes=None):
    """Epoch of the developer's newest genuine input in this session within the presence window, else None (also when
    there is no transcript or its scan runs over budget: unknown counts as away)."""
    now = time.time() if now is None else now
    minutes = ask_gate_presence_minutes() if minutes is None else minutes
    path = payload.get('transcript_path')
    if not (isinstance(path, str) and os.path.isfile(path)):
        path = transcripts.session_files(session, payload.get('cwd'))[0]
    if not path:
        return None
    try:
        return human_turns.last_human_input(path, now - minutes * 60)
    except TimeoutError:
        return None


def present_verdict(payload, session, now, minutes):
    """('dialog' | 'present', reason) when the developer is driving this session in person, else None. That is
    when their genuine message here is less than ASK_GATE_FRESH_MIN old, or inside the presence window and asks to be
    asked, or inside the presence window while another gate (cross-project) sent this session to a dialog for an order
    given here. Used for supervised sessions and for the supervisor itself. Never raises
    TimeoutError: a transcript too big to scan in budget counts as away."""
    path = payload.get('transcript_path')
    if not (isinstance(path, str) and os.path.isfile(path)):
        path = transcripts.session_files(session, payload.get('cwd'))[0]
    try:
        seen = human_turns.last_human_input(path, now - minutes * 60, True) if path else None
    except TimeoutError:
        ask_gate_error(f'{str(session)[:8]} presence scan over budget: counted as away')
        seen = None  # unknown counts as away
    if seen is None:
        return None
    age, said = now - seen[0], seen[1]
    if recent_deny_dialog(session, now):
        return 'dialog', f'cross-project dialog, developer input {int(age)} s ago'
    if age < ask_gate_fresh_minutes() * 60 or asks_to_be_asked(said):
        return 'present', f'developer input {int(age)} s ago'
    return None


def ask_gate_decide(payload, locks):
    """'' (allow) or the deny json for a developer question from a session that owns no supervisor lock."""
    session, tool = str(payload.get('session_id') or ''), payload.get('tool_name')
    try:
        if ask_gate_disabled():
            ask_gate_log(session, 'allow-off', tool, 'kill switch')
            return ''
        repeated = ask_gate_backstop(payload, session)
        if repeated:
            return repeated
        now = time.time()
        minutes = ask_gate_presence_minutes()
        # While a supervision of the project is alive, a session under it asks the developer only when they are
        # driving it (see present_verdict); the rest is batched at the very end. Free sessions keep the logic below.
        role, lock = session_roles.session_role(session, payload.get('cwd'))
        parked = parked_tool_kind(payload)
        if parked:
            # A plan to approve or an offered session waits for the developer like a question, but a free session
            # (the developer in front of it) and the mailbox may use them; only supervised sessions and owners are denied
            if role in ('supervised', 'owner'):
                ask_gate_log(session, f'deny-{parked}', tool, f'{role}: a {parked} waits for the developer')
                return deny.deny_parked_tool(parked, lock)
            ask_gate_log(session, f'allow-{parked}', tool, f'{role} session')
            return ''
        if role == 'mailbox':
            ask_gate_log(session, 'allow-mailbox', tool, 'question mailbox')
            return ''
        if role == 'supervised':
            # A supervisor stays on guard after the final batch, so every session of the project stays supervised.
            # One the developer is driving in person may ask exactly as a free session may (no more): their message
            # less than ASK_GATE_FRESH_MIN old, or one inside the presence window that asks to be asked. The dialog the
            # cross-project gate offers for an order given there only needs presence.
            verdict = present_verdict(payload, session, now, minutes)
            if verdict:
                ask_gate_log(session, f'allow-{verdict[0]}-supervised', tool, verdict[1])
                return ''
            ask_gate_log(session, 'deny-supervised', tool, f'live lock {(lock or {}).get("key") or "?"}')
            return deny.deny_supervised(lock, minutes)
        # Only a free session (the developer in front of it) may use the dialog the cross-project gate offered; a
        # supervised one was handled above, because a dialog there would park it waiting for the developer.
        if recent_deny_dialog(session, now):
            ask_gate_log(session, 'allow-dialog', tool, 'the cross-project gate sent this session to a dialog')
            return ''
        path = payload.get('transcript_path')
        if not (isinstance(path, str) and os.path.isfile(path)):
            path = transcripts.session_files(session, payload.get('cwd'))[0]
        if not path:
            ask_gate_log(session, 'allow-no-transcript', tool, 'no transcript to judge presence from')
            return ''
        fresh = ask_gate_fresh_minutes()
        try:
            seen = human_turns.last_human_input(path, now - minutes * 60, True)
        except TimeoutError:
            # A transcript too big to scan in budget is not proof of presence: treat it as absent
            if session_roles.is_mailbox_session(session, locks, payload.get('cwd')):
                ask_gate_log(session, 'allow-mailbox', tool, 'question mailbox')
                return ''
            ask_gate_log(session, 'deny-timeout', tool, 'transcript scan over budget; counted as absent')
            return deny.deny_absent(minutes)
        if seen is not None:
            when, said = seen
            age = now - when
            if age < fresh * 60:
                ask_gate_log(session, 'allow-fresh', tool, f'developer input {int(age)} s ago')
                return ''
            if asks_to_be_asked(said):
                ask_gate_log(session, 'allow-requested', tool, f'developer asked to be asked, {int(age)} s ago')
                return ''
            if session_roles.is_mailbox_session(session, locks, payload.get('cwd')):
                ask_gate_log(session, 'allow-mailbox', tool, 'question mailbox')
                return ''
            ask_gate_log(session, 'deny-stale-presence', tool,
                         f'last developer input {int(age)} s ago (fresh window {fresh:g} min), no request to be asked')
            return deny.deny_absent(minutes, age, fresh)
        if session_roles.is_mailbox_session(session, locks, payload.get('cwd')):
            ask_gate_log(session, 'allow-mailbox', tool, 'question mailbox')
            return ''
        ask_gate_log(session, 'deny-absent', tool, f'no developer input in {minutes:g} min')
        return deny.deny_absent(minutes)
    except Exception:
        ask_gate_error(f'{session[:8]} {tool}\n' + traceback.format_exc().rstrip())
        ask_gate_log(session, 'allow-error', tool, 'gate failed; failing open')
        return ''
