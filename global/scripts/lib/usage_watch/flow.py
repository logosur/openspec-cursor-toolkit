"""The state machine of a finding: ask, decide, apply, measure (design D7).

`new → asked → authorized | rejected → applied → measured`. Each transition runs under the store's flock and appends
`{state, at, by, ref}` to the finding's history. `apply` is the single place where anything outside the state directory
changes or a session-tool ticket is issued, and it refuses (exit 3, nothing written) unless the finding is `authorized`
and the queue, read again at that moment, still holds the trusted authorising answer that `decide` recorded.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

from . import config as C
from . import role, store
from .data import Data
from .state import Locked, read_json, read_json_quiet, write_json

OK, USAGE, REFUSED, TOO_EARLY = 0, 2, 3, 4
HOUR = 3600


def _err(text: str) -> None:
    print(f'usage-watch: {text}', file=sys.stderr)


def _by() -> str:
    ids = role.asker_ids()
    return ids['host_session'] or ids['session'] or 'usage-watch'


def _history(finding: dict, state: str, now_ts: float, ref=None, **extra) -> None:
    finding['state'] = state
    finding.setdefault('history', []).append(dict({'state': state, 'at': C.iso(now_ts), 'by': _by(), 'ref': ref}, **extra))


def evidence_line(cfg: dict, f: dict) -> str:
    figures = {k: v for k, v in (f.get('evidence') or {}).items() if k not in ('locations', 'per_session', 'top_sessions')}
    return (f'usage-watch {f.get("rule")} ({(f.get("scope") or {}).get("kind")}): '
            f'{json.dumps(figures, ensure_ascii=False, sort_keys=True)}; '
            f'saving about {f.get("saving_units_per_day")} {cfg["unit_label"]} per day')


def change_text(f: dict) -> str:
    """The exact change `apply` would make for this finding, as written into its question (G-16).

    `apply` makes a change only while the queue item's question still holds this text, so the answer authorises the
    change the developer read, never another proposal or target edited into the store afterwards.
    """
    p = f.get('proposal') or {}
    kind = p.get('kind')
    if kind == 'config':
        return f'config {p.get("piece")} {p.get("key")} = {json.dumps(p.get("value"), ensure_ascii=False)}'
    if kind in ('session-model', 'session-effort'):
        field = 'model' if kind == 'session-model' else 'effort'
        return f'session {f.get("target_app_id")} {field} = {p.get("value")}'
    return f'{kind}: {p.get("text")}'


def change_line(cfg: dict, f: dict) -> str:
    return f'{cfg["labels"]["change"]}: {change_text(f)}'


# ------------------------------------------------------------------------------------------------ ask
def queue_project(cfg: dict, f: dict, explicit: str | None) -> str | None:
    """The finding's project when a questions session would present it; else the role's home project; else --project."""
    if (f.get('scope') or {}).get('kind') != 'machine' and role.supervised_with_mailbox(cfg, f.get('project_root')):
        return f['project_root']
    return role.home_project(cfg) or explicit


def ask(cfg: dict, fid: str, question: str | None, project: str | None, now_ts: float) -> int:
    with store.locked(cfg):
        findings = store.read(cfg)
        f = findings.get(fid)
        if f is None:
            _err(f'no finding {fid}')
            return USAGE
        if f.get('state') != 'new':
            _err(f'{fid} is {f.get("state")}: only a new finding is asked, and only once')
            return REFUSED
        target = queue_project(cfg, f, project)
        if not target:
            _err('no queue to register the question in: no usage role home project and no --project')
            return REFUSED
        text = (question or '').strip() or f'{(f.get("proposal") or {}).get("text")} ({f.get("rule")})'
        args = ['add', '--project', target, '--question',
                f'{text}\n\n{change_line(cfg, f)}\n\n{cfg["authorize_hint"]}',
                '--default', cfg['no_default'], '--why', evidence_line(cfg, f), '--blocks', 'nothing',
                '--key', f'usage-watch:{fid}']
        if str(cfg['order_text']).strip():
            args += ['--order', str(cfg['order_text']).strip()]
        r = role.run(role.ASK_QUEUE, *args)
        qid = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ''
        if not qid:
            _err(f'ask-queue add failed (exit {r.returncode}): {r.stderr.strip()[:300]}')
            return REFUSED
        f['queue'] = {'project': target, 'id': qid}
        f['asked_by'] = role.asker_ids()
        _history(f, 'asked', now_ts, ref=qid)
        store.write(cfg, findings)
    print(f'ASKED {fid} {qid}')
    return OK


# ------------------------------------------------------------------------------------------------ decide
def decide(cfg: dict, fid: str, now_ts: float) -> int:
    with store.locked(cfg):
        findings = store.read(cfg)
        f = findings.get(fid)
        if f is None:
            _err(f'no finding {fid}')
            return USAGE
        if f.get('state') != 'asked':
            _err(f'{fid} is {f.get("state")}: only an asked finding is decided')
            return REFUSED
        outcome, item = role.verdict(cfg, f)
        if outcome == role.PENDING:
            _err(f'{fid}: its question is not answered yet; nothing changed')
            return REFUSED
        if outcome == role.UNTRUSTED:
            _err(f'{fid}: the answer was recorded by the session that asked, by the usage role or by nobody; '
                 'it is not trusted and nothing changed')
            return REFUSED
        answer = {'text': item.get('answer'), 'by': item.get('answered_by'), 'ts': item.get('answered_ts'),
                  'status': item.get('status')}
        f['answer'] = answer
        state = 'authorized' if outcome == role.AUTHORIZE else 'rejected'
        _history(f, state, now_ts, ref=item.get('id'), answer=answer['text'], answered_by=answer['by'],
                 answered_ts=answer['ts'])
        store.write(cfg, findings)
    print(f'{state.upper()} {fid}')
    return OK


# ------------------------------------------------------------------------------------------------ apply
def override_dir() -> str:
    return os.path.expanduser(os.environ.get('CLAUDE_TOOLKIT_OVERRIDE') or '~/.config/claude-toolkit')


def installed_dir() -> str:
    return os.path.expanduser(os.environ.get('CLAUDE_TOOLKIT_CONFIG_DIR') or '~/.claude/toolkit/config')


def render(values: dict) -> str:
    """The installer's rendering of a config piece (scripts/toolkit/config.py `render`)."""
    return json.dumps(values, indent=2, ensure_ascii=False, sort_keys=True) + '\n'


def _write_text(path: str, text: str) -> None:
    """Atomic write that keeps the file's mode (0644 for a new one, the installer's mode for config pieces)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o644
    tmp = f'{path}.tmp-{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _apply_config(f: dict) -> tuple[int, dict | None]:
    p = f.get('proposal') or {}
    piece, key, value = p.get('piece'), p.get('key'), p.get('value')
    if not isinstance(piece, str) or not piece or not isinstance(key, str) or not key:
        _err('the config proposal names no piece or key')
        return REFUSED, None
    ov = override_dir()
    if not os.path.isdir(ov):
        _err(f'no override directory ({ov}): the change would be undone by the next install; nothing changed')
        return REFUSED, None
    installed_path = os.path.join(installed_dir(), f'{piece}.json')
    installed = read_json_quiet(installed_path)
    if not isinstance(installed, dict):
        _err(f'the installed piece {piece} is missing or unreadable; nothing changed')
        return REFUSED, None
    ov_path = os.path.join(ov, 'config', f'{piece}.json')
    ov_values = read_json_quiet(ov_path) if os.path.exists(ov_path) else {}
    if not isinstance(ov_values, dict):
        _err(f'the override piece {ov_path} is unreadable; nothing changed')
        return REFUSED, None
    previous = {'override': {'present': key in ov_values, 'value': ov_values.get(key)},
                'installed': {'present': key in installed, 'value': installed.get(key)}}
    _write_text(ov_path, json.dumps(dict(ov_values, **{key: value}), indent=2, ensure_ascii=False, sort_keys=True) + '\n')
    _write_text(installed_path, render(dict(installed, **{key: value})))
    return OK, {'kind': 'config', 'piece': piece, 'key': key, 'value': value, 'previous': previous,
                'files': [ov_path, installed_path]}


def tickets_path(cfg: dict) -> str:
    return os.path.join(C.path(cfg, 'state_dir'), 'tickets.json')


def read_tickets(cfg: dict) -> list:
    data = read_json(tickets_path(cfg), {})
    tickets = data.get('tickets') if isinstance(data, dict) else None
    return [t for t in tickets if isinstance(t, dict)] if isinstance(tickets, list) else []


def _issue_ticket(cfg: dict, f: dict, now_ts: float) -> tuple[int, dict | None]:
    p = f.get('proposal') or {}
    target = f.get('target_app_id')
    if not isinstance(target, str) or not target:
        _err('the finding has no target app id, so no session tool call can be allowed; nothing changed')
        return REFUSED, None
    field = 'model' if p.get('kind') == 'session-model' else 'effort'
    value = p.get('value')
    if not isinstance(value, str) or not value:
        _err('the proposal has no value; nothing changed')
        return REFUSED, None
    ticket = {'id': uuid.uuid4().hex[:12], 'finding': f['id'], 'session': target, 'field': field, 'value': value,
              'issued_at': C.iso(now_ts), 'expires_at': now_ts + float(cfg['ticket_ttl_s']), 'used': False}
    with Locked(tickets_path(cfg)):
        tickets = read_tickets(cfg)
        tickets.append(ticket)
        write_json(tickets_path(cfg), {'tickets': tickets})
    return OK, {'kind': p.get('kind'), 'ticket': ticket['id'], 'session': target, 'field': field, 'value': value}


def apply(cfg: dict, fid: str, how: str | None, now_ts: float) -> int:
    with store.locked(cfg):
        findings = store.read(cfg)
        f = findings.get(fid)
        if f is None:
            _err(f'no finding {fid}')
            return USAGE
        if f.get('state') != 'authorized':
            _err(f'{fid} is {f.get("state")}: only an authorised finding is applied; nothing changed')
            return REFUSED
        if not role.available():
            _err('the question queue cannot be read again (supervision not installed); nothing changed')
            return REFUSED
        outcome, item = role.verdict(cfg, f)
        recorded = (f.get('answer') or {}).get('text')
        if outcome != role.AUTHORIZE or recorded is None or (item or {}).get('answer') != recorded:
            _err(f'{fid}: its queue item does not hold the authorising answer that decide recorded; nothing changed')
            return REFUSED
        if change_text(f) not in str((item or {}).get('question') or ''):
            _err(f'{fid}: the change it holds now ({change_text(f)}) is not the one its question asked; nothing changed')
            return REFUSED
        kind = (f.get('proposal') or {}).get('kind')
        if kind == 'note':
            if not (how or '').strip():
                _err('a note finding needs --how: what was done')
                return USAGE
            code, done = OK, {'kind': 'note', 'how': how.strip()}
        elif kind == 'config':
            code, done = _apply_config(f)
        elif kind in ('session-model', 'session-effort'):
            code, done = _issue_ticket(cfg, f, now_ts)
        else:
            _err(f'unknown proposal kind {kind!r}; nothing changed')
            return REFUSED
        if code != OK:
            return code
        f['applied'] = dict(done, at=C.iso(now_ts), ts=now_ts)
        _history(f, 'applied', now_ts, ref=done.get('ticket'))
        store.write(cfg, findings)
    print(f'APPLIED {fid} ({kind})' + (f' ticket {done["ticket"]} for {done["session"]} {done["field"]}={done["value"]}'
                                       if done.get('ticket') else ''))
    return OK


# ------------------------------------------------------------------------------------------------ measure
def metric(cfg: dict, f: dict, d: Data, start: float, end: float) -> tuple[str, float]:
    """The rule's figure for the finding's scope over (start, end]."""
    import re
    expensive = re.compile(cfg['expensive_model_pattern'])
    scope = f.get('scope') or {}
    calls = d.since(start, end)
    if scope.get('kind') == 'session':
        calls = [c for c in calls if c['session'] == scope.get('id')]
    elif scope.get('kind') == 'project':
        calls = [c for c in calls if d.session(c['session'])['project'] == scope.get('id')]
    rule = f.get('rule')
    if rule == 'advisor-excess':
        return 'advisor calls', float(len([c for c in calls if c['kind'] == 'advisor']))
    if rule == 'expensive-subagents':
        return 'units of expensive subagents', round(sum(c['units'] for c in calls if c['kind'] == 'subagent'
                                                         and expensive.search(c['model'])), 4)
    if rule in ('role-model', 'expensive-automation'):
        return 'units on expensive models', round(sum(c['units'] for c in calls if c['kind'] == 'main'
                                                      and expensive.search(c['model'])), 4)
    if rule == 'empty-wakes':
        sid = scope.get('id')
        return 'automatic turns', float(len([t for t in d.turns.values() if t['session'] == sid
                                             and start < t['ts'] <= end and Data.is_automatic(t['origin'])]))
    return 'units', round(sum(c['units'] for c in calls), 4)


def measure(cfg: dict, fid: str, now_ts: float) -> int:
    window = float(cfg['measure_window_h']) * HOUR
    with store.locked(cfg):
        findings = store.read(cfg)
        f = findings.get(fid)
        if f is None:
            _err(f'no finding {fid}')
            return USAGE
        if f.get('state') != 'applied':
            _err(f'{fid} is {f.get("state")}: only an applied finding is measured')
            return REFUSED
        at = (f.get('applied') or {}).get('ts')
        if not isinstance(at, (int, float)):
            _err(f'{fid} has no apply time')
            return REFUSED
        if now_ts < at + window:
            _err(f'{fid}: too early, the after window ends {C.iso(at + window)}')
            return TOO_EARLY
        d = Data(cfg, at + window)
        name, before = metric(cfg, f, d, at - window, at)
        _, after = metric(cfg, f, d, at, at + window)
        f['measure'] = {'metric': name, 'before': before, 'after': after, 'window_h': cfg['measure_window_h']}
        _history(f, 'measured', now_ts)
        store.write(cfg, findings)
    print(f'MEASURED {fid} {name}: before {before:g}, after {after:g} ({cfg["measure_window_h"]} h each)')
    return OK
