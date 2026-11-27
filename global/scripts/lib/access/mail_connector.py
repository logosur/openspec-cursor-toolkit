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

# Values of the Gmail connector's tool schema. A setting left out means the default below, resolved when the call is
# built (never copied into the account defaults at import), so a changed constant is noticed by the self-test.
SEARCH_VIEWS = ('THREAD_VIEW_METADATA_ONLY', 'THREAD_VIEW_MINIMAL', 'THREAD_VIEW_IDS_ONLY', 'THREAD_VIEW_SUMMARY')
DEFAULT_SEARCH_VIEW = 'THREAD_VIEW_SUMMARY'
READ_FORMATS = ('MINIMAL', 'FULL_CONTENT', 'METADATA_ONLY', 'PLAIN_TEXT')
DEFAULT_READ_FORMAT = 'PLAIN_TEXT'
FULL_CONTENT = 'FULL_CONTENT'
PAGE_SIZE_MAX = 50
WHOAMI_VIEW = 'THREAD_VIEW_METADATA_ONLY'     # fixed: the check must work on an account whose search view carries no sender


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


def _section(account: dict) -> dict:
    return account.get('connector') if isinstance(account.get('connector'), dict) else {}


def connector_settings(account: dict) -> dict:
    """The account's connector settings with their defaults. Absent or null is the default; validation is `setting_problem`."""
    cfg = _section(account)

    def given(key, default):
        return default if cfg.get(key) is None else cfg[key]
    return {'kind': str(cfg.get('kind') or 'gmail'), 'search_tool': str(cfg.get('search_tool') or 'search_threads'),
            'read_tool': str(cfg.get('read_tool') or 'get_thread'), 'search_view': given('search_view', DEFAULT_SEARCH_VIEW),
            'read_format': given('read_format', DEFAULT_READ_FORMAT), 'page_size_max': given('page_size_max', PAGE_SIZE_MAX)}


def setting_problem(account: dict) -> str:
    """What is wrong with the account's search_view, read_format or page_size_max ('' when nothing). Exact matching:
    a wrong case is refused, not repaired. Only for a Gmail connector: other kinds have no known values."""
    cfg = _section(account)
    if str(cfg.get('kind') or 'gmail') != 'gmail':
        return ''
    for key, known in (('search_view', SEARCH_VIEWS), ('read_format', READ_FORMATS)):
        value = cfg.get(key)
        if value is not None and not (isinstance(value, str) and value in known):
            return f'connector.{key} is not one of: ' + ', '.join(known)
    size = cfg.get('page_size_max')
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 1):
        return 'connector.page_size_max is not a whole number of at least 1'
    return ''


def search_document(account: dict, f: Filters, limit: int) -> dict:
    cfg = connector_settings(account)
    if cfg['kind'] != 'gmail':
        raise Unsupported(f'no query translation for the connector kind {cfg["kind"]!r}')
    limit = max(int(limit), 1)
    page = min(limit, cfg['page_size_max'])
    paging = {'requested': limit, 'page_size': page, 'capped': page < limit}
    if paging['capped']:
        paging.update(continue_with='pageToken', how="repeat this call adding the connector's pageToken from its previous "
                                                    'response to get further results')
    return {'delegate': 'connector', 'kind': cfg['kind'], 'tool': cfg['search_tool'],
            'arguments': {'query': gmail_query(f), 'pageSize': page, 'view': cfg['search_view']},
            'paging': paging, 'read_tool': cfg['read_tool']}


def read_document(account: dict) -> dict:
    """The legacy document (no arguments): what `folders`, `save` and a connector kind other than gmail print."""
    cfg = connector_settings(account)
    return {'delegate': 'connector', 'kind': cfg['kind'], 'tool': cfg['read_tool'],
            'note': 'call this tool with the id returned by the search call'}


def read_call(account: dict, thread_id: str, full_content: bool = False) -> dict:
    """The complete read call for `show` and `thread`: the id as typed and the message format, so the session chooses nothing."""
    cfg = connector_settings(account)
    if not thread_id.strip():
        raise Unsupported('the id is empty: give the id that a search printed')
    return {'delegate': 'connector', 'kind': cfg['kind'], 'tool': cfg['read_tool'],
            'arguments': {'threadId': thread_id, 'messageFormat': FULL_CONTENT if full_content else cfg['read_format']},
            'note': 'call this tool with these arguments as printed'}


def whoami_call(account: dict) -> dict:
    """The cheap call whose result shows the connector's own address (the From of a sent message)."""
    cfg = connector_settings(account)
    arguments = {'query': 'in:sent', 'pageSize': 1}
    if cfg['kind'] == 'gmail':
        arguments['view'] = WHOAMI_VIEW
    return {'tool': cfg['search_tool'], 'arguments': arguments}


def sender_matches(account: dict, sender: str) -> bool:
    wanted = {str(account.get('address', '')).strip().lower(),
              *[str(a).strip().lower() for a in account.get('aliases') or []]} - {''}
    return sender.strip().lower() in wanted
