"""Questions that the developer already answered."""
import difflib
import json
import re
import time
from datetime import datetime

from . import ask_gate, human_turns, transcripts, util


# Backstop against asking twice. The queue ids a dialog carries in `metadata.source` ("ask-queue:<id>,<id>") say which
# decisions it is about: if one is already answered or closed the question is stale (a questions session could ask the
# same decision again seconds after the developer answered it). Without ids, a question that is nearly identical to one this
# session already got answered in the last 24 h is a duplicate.
ASK_GATE_DUP_HOURS = 24
ASK_GATE_DUP_RATIO = 0.9
_ASK_IDS = re.compile(r'ask-queue:\s*([\w-]+(?:\s*,\s*[\w-]+)*)')


def ask_source_ids(tool_input):
    """Queue ids named in an AskUserQuestion's `metadata.source`, in order, without repeats."""
    meta = tool_input.get('metadata') if isinstance(tool_input, dict) else None
    source = meta.get('source') if isinstance(meta, dict) else None
    ids = []
    for match in _ASK_IDS.finditer(source if isinstance(source, str) else ''):
        ids += [i for i in re.split(r'\s*,\s*', match.group(1)) if i and i not in ids]
    return ids


def ask_questions(tool_input):
    """The question texts of an AskUserQuestion input."""
    items = tool_input.get('questions') if isinstance(tool_input, dict) else None
    return [q['question'] for q in items or [] if isinstance(q, dict) and isinstance(q.get('question'), str)]


def norm_question(text):
    return re.sub(r'[\W_]+', ' ', str(text).casefold()).strip()[:2000]


def similar_questions(a, b):
    """True when two normalized questions reach ASK_GATE_DUP_RATIO (cheap upper bounds first)."""
    if not a or not b:
        return False
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return (matcher.real_quick_ratio() >= ASK_GATE_DUP_RATIO and matcher.quick_ratio() >= ASK_GATE_DUP_RATIO
            and matcher.ratio() >= ASK_GATE_DUP_RATIO)


def answered_questions(path, cutoff):
    """[(epoch ts, question, answer text)] this transcript got answered at or after `cutoff`, newest first.

    Reads backwards under the same budget as the presence scan (TimeoutError past it). An answered dialog is a
    non-error user record whose `toolUseResult` has `questions` and `answers`; when a record lacks that, the question
    comes from the matching AskUserQuestion tool_use and the answer is unknown (empty).
    """
    deadline = time.monotonic() + ask_gate.ASK_GATE_BUDGET_S
    seen, found, answered = 0, [], {}
    for line in human_turns.iter_lines_reverse(path):
        seen += len(line)
        if time.monotonic() > deadline or seen > ask_gate.ASK_GATE_MAX_BYTES:
            raise TimeoutError('transcript scan over budget')
        stamp = human_turns._RE_TS.findall(line[-2048:]) or human_turns._RE_TS.findall(line)
        ts = util.parse_ts(stamp[-1].decode()) if stamp else None
        if ts is not None and ts < cutoff - 300:
            break
        if ts is None or ts < cutoff:
            continue
        if b'tool_result' in line and b'"user"' in line:
            if b'"is_error":true' in line or b'"is_error": true' in line:
                continue
            if b'"answers"' in line:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                result = rec.get('toolUseResult') if isinstance(rec, dict) else None
                answers = result.get('answers') if isinstance(result, dict) else None
                if isinstance(answers, dict):
                    for question in ask_questions(result):
                        found.append((ts, question, str(answers.get(question) or '')))
                    continue
            for tid in human_turns._RE_RESULT_ID.findall(line):
                answered.setdefault(tid.decode(), ts)
            continue
        if b'AskUserQuestion' in line and b'"tool_use"' in line and answered:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            for item in transcripts.content_items(rec):
                if item.get('type') == 'tool_use' and item.get('name') == ask_gate.ASK_TOOL and item.get('id') in answered:
                    found += [(answered[item['id']], q, '') for q in ask_questions(item.get('input'))
                              if not any(f[1] == q and f[0] == answered[item['id']] for f in found)]
    return sorted(found, key=lambda f: -f[0])


def deny_answered(done):
    """done: [(id, item)] queue items already answered or closed. The deny json."""
    parts = []
    for item_id, item in done:
        if item.get('status') == 'answered':
            parts.append(f'{item_id} (respondida el {str(item.get("answered_ts") or "?")[:16].replace("T", " ")} con '
                         f'«{util.clip(item.get("answer"))}»)')
        else:
            note = f': {util.clip(item.get("note"))}' if item.get('note') else ''
            parts.append(f'{item_id} (cerrada el {str(item.get("closed_ts") or "?")[:16].replace("T", " ")}{note})')
    reason = (f'No abras este diálogo tal cual: estas decisiones de la cola ya no están pendientes: {"; ".join(parts)}. '
              f'El desarrollador ya las contestó o se cerraron, y preguntarlas otra vez le repite el trabajo. Quítalas '
              f'del diálogo y aplica lo que respondió; si no queda ninguna pregunta, no abras diálogo. Si su respuesta '
              f'pedía algo nuevo, registra esa decisión nueva con `~/.claude/scripts/ask-queue add --project "$PWD" '
              f'--question … --default … --why … --blocks …` y pregunta solo esa, con sus ids en metadata.source.')
    return json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                              'permissionDecisionReason': reason}})


def deny_duplicate(question, stamp, answer):
    when = datetime.fromtimestamp(stamp).strftime('%Y-%m-%d %H:%M')
    told = f'su respuesta fue «{util.clip(answer)}»' if answer else 'consta su respuesta en esta misma conversación'
    reason = (f'Esta sesión ya le hizo al desarrollador una pregunta casi idéntica y la contestó el {when}: '
              f'«{util.clip(question, 160)}»; {told}. No la repitas: aplica esa respuesta. Si ha cambiado algo que la '
              f'invalide, pregunta solo lo nuevo y dilo en la primera frase de la pregunta.')
    return json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                              'permissionDecisionReason': reason}})
