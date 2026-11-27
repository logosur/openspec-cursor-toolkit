"""Connector accounts of `mailbox`: nothing is read here.

The assistant session, not this script, holds the mail connector. For a connector account the command only prints
the call the session has to make: the connector's search tool and its arguments, with the filters translated to the
connector's own query language (Gmail search operators for `kind: gmail`), and the one cheap call that reveals which
mailbox the connector is signed in to. The connector's server identifier is never stored or printed: only the short
tool names from the configuration.
"""
from __future__ import annotations

import datetime as dt
import re

from access.mail_message import Filters

ROLE_QUERY = {'inbox': 'in:inbox', 'sent': 'in:sent', 'drafts': 'in:drafts', 'all': ''}


class Unsupported(Exception):
    """A filter has no equivalent in the connector's query language."""


def _quote(value: str) -> str:
    value = value.replace('"', '')
    return f'"{value}"' if re.search(r'[\s{}()]', value) else value


def _day(day: dt.date) -> str:
    return day.strftime('%Y/%m/%d')


def gmail_query(f: Filters) -> str:
    """The Gmail search string for FILTERS. `--until` is inclusive, so `before:` names the next day."""
    if f.header:
        raise Unsupported('--header has no equivalent in the connector search; use --from, --to, --subject or --text')
    parts: list[str] = []
    folder = (f.folder or 'all').strip()
    if folder.lower() in ROLE_QUERY:
        if ROLE_QUERY[folder.lower()]:
            parts.append(ROLE_QUERY[folder.lower()])
    else:
        parts.append(f'label:{_quote(folder)}')
    if f.from_:
        parts.append(f'from:{_quote(f.from_)}')
    if f.to:
        word = _quote(f.to)
        parts.append(f'{{to:{word} cc:{word} bcc:{word}}}')
    if f.subject:
        parts.append(f'subject:{_quote(f.subject)}')
    if f.since:
        parts.append(f'after:{_day(f.since)}')
    if f.until:
        parts.append(f'before:{_day(f.until + dt.timedelta(days=1))}')
    if f.has_attachment:
        parts.append('has:attachment')
    if f.text:
        parts.append(f'"{f.text.replace(chr(34), "")}"')
    return ' '.join(parts)


def connector_settings(account: dict) -> dict:
    cfg = account.get('connector') if isinstance(account.get('connector'), dict) else {}
    return {'kind': str(cfg.get('kind') or 'gmail'), 'search_tool': str(cfg.get('search_tool') or 'search_threads'),
            'read_tool': str(cfg.get('read_tool') or 'get_thread')}


def search_document(account: dict, f: Filters, limit: int) -> dict:
    cfg = connector_settings(account)
    if cfg['kind'] != 'gmail':
        raise Unsupported(f'no query translation for the connector kind {cfg["kind"]!r}')
    return {'delegate': 'connector', 'kind': cfg['kind'], 'tool': cfg['search_tool'],
            'arguments': {'query': gmail_query(f), 'pageSize': int(limit)}, 'read_tool': cfg['read_tool']}


def read_document(account: dict) -> dict:
    cfg = connector_settings(account)
    return {'delegate': 'connector', 'kind': cfg['kind'], 'tool': cfg['read_tool'],
            'note': 'call this tool with the id returned by the search call'}


def whoami_call(account: dict) -> dict:
    """The cheap call whose result shows the connector's own address (the From of a sent message)."""
    cfg = connector_settings(account)
    return {'tool': cfg['search_tool'], 'arguments': {'query': 'in:sent', 'pageSize': 1}}


def sender_matches(account: dict, sender: str) -> bool:
    wanted = {str(account.get('address', '')).strip().lower(),
              *[str(a).strip().lower() for a in account.get('aliases') or []]} - {''}
    return sender.strip().lower() in wanted
