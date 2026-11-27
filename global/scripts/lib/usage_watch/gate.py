"""The ticket check of the `usage-apply-gate` hook (design D14).

Only the usage role holder is restricted: its call to the app's set-model or set-effort tool passes only against an
unused, unexpired ticket that names the tool input's session, the tool's field and the tool input's value, and that
ticket is marked used (one ticket, one call). Any other caller, or no usage role record, passes untouched.
"""
from __future__ import annotations

import os

from . import attribution
from . import config as C
from .flow import read_tickets, tickets_path
from .state import Locked, write_json

FIELDS = {'set_session_model': 'model', 'set_session_effort': 'effort'}

REASON = ('usage-apply-gate: as the usage role you change a session\'s {field} only after `usage-watch apply <finding>` '
          'issued a ticket for exactly this session and value, from a question the developer answered in the queue. '
          'There is no unused, unexpired ticket for {session} {field}={value}. Run `usage-watch apply` on the '
          'authorised finding, or leave the session as it is.')


def field_of(tool: str) -> str | None:
    for suffix, field in FIELDS.items():
        if tool.endswith(suffix):
            return field
    return None


def check(payload: dict, cfg: dict | None = None, now_ts: float | None = None) -> str | None:
    """The deny reason, or None to let the call through."""
    tool = payload.get('tool_name') if isinstance(payload.get('tool_name'), str) else ''
    field = field_of(tool)
    if field is None:
        return None
    cfg = cfg or C.load()
    holder = attribution.usage_role(cfg)
    if not holder:
        return None
    held = {v for v in (holder.get('session_id'), holder.get('cli_session_id')) if isinstance(v, str) and v}
    callers = {v for v in (payload.get('session_id'), os.environ.get('CLAUDE_CODE_HOST_SESSION_ID'))
               if isinstance(v, str) and v}
    if not held & callers:
        return None
    now_ts = C.now() if now_ts is None else now_ts
    args = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    session, value = args.get('session_id'), args.get(field)
    with Locked(tickets_path(cfg)):
        tickets = read_tickets(cfg)
        for t in tickets:
            if (t.get('used') is False and isinstance(t.get('expires_at'), (int, float)) and t['expires_at'] > now_ts
                    and t.get('session') == session and t.get('field') == field and t.get('value') == value):
                t.update(used=True, used_at=C.iso(now_ts), used_by=sorted(callers))
                write_json(tickets_path(cfg), {'tickets': tickets})
                return None
    return REASON.format(field=field, session=session, value=value)
