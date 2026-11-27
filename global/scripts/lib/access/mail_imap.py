"""`imap` backend of `mailbox`: live, read-only (design D6).

Read-only by construction. The only mailbox commands this module can issue are LOGIN, LIST, EXAMINE (through
`select(..., readonly=True)`), `UID SEARCH`, `UID FETCH ... BODY.PEEK[...]` and LOGOUT. It has no code path for STORE,
COPY, MOVE, APPEND, EXPUNGE, CREATE, DELETE, RENAME, SUBSCRIBE or CLOSE, and it never fetches with a form that sets
the "seen" flag. A test asserts this on the recorded command stream and on this file's text.

The password comes from the env-style file named in the account's configuration, is read at run time, and is never
printed, logged, placed in an exception message or passed as an argument. A login the server rejects is never retried:
a 0600 marker in the cache directory makes the backend unavailable for `auth_cooldown_minutes` without connecting. A
timeout, a DNS failure or a dropped connection is not a rejection: it makes the backend unavailable for this run only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import imaplib
import json
import os
import re
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import quote, unquote

from access import mail_local, settings
from access.mail_message import (Filters, Interrupted, Item, NotFound, SearchResult, Unavailable, decode_words, mutf7_decode,
                                 party_and_direction, split_headers, summarize)

TIMEOUT = 20
FETCH_BATCH = 200
ROLE_NAME_DEPTH = 2        # a folder is taken for a role by its name only at the top of the tree ('Sent', 'INBOX.Sent', '[Gmail]/Sent Mail')
THREAD_FOLDERS = 4        # a thread lookup opens the message's folder, the inbox and at most two sent folders
THREAD_ROUNDS = 2         # header searches per folder: the message's identifiers, then the ones that found
THREAD_IDS = 6            # identifiers searched per round
THREAD_OR = 4             # alternatives in one header search: a real server refused a chain of nine ('BAD Command Argument Error')
HEADER_FIELDS = ('FROM TO CC BCC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES CONTENT-TYPE X-MS-HAS-ATTACH RECEIVED')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
NETWORK_ERRORS = (OSError, EOFError, imaplib.IMAP4.abort, ssl.SSLError, socket.timeout)
_LIST = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$', re.S)


def factory(host: str, port: int, timeout: int):
    """Creates the connection. The tests replace this function with a recording fake."""
    return imaplib.IMAP4_SSL(host, port, timeout=timeout)


def _imap_date(day) -> str:
    return f'{day.day}-{MONTHS[day.month - 1]}-{day.year}'


def _quoted(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _clean(text: str) -> str:
    return ''.join(ch if ord(ch) >= 32 and ord(ch) != 127 else ' ' for ch in text)


def _ascii(text: str) -> bool:
    return text.isascii()


class ImapBackend:
    name = 'imap'

    def __init__(self, account_name: str, account: dict, own: set[str], defaults: dict):
        self.account_name, self.account, self.own, self.defaults = account_name, account, own, defaults
        cfg = account.get('imap') if isinstance(account.get('imap'), dict) else {}
        self.host = str(cfg.get('host') or '').strip()
        self.port = int(cfg.get('port') or 993)
        self.user = str(cfg.get('user') or '').strip() or str(account.get('address') or '').strip()
        self.credentials_file = str(cfg.get('credentials_file') or '').strip()
        self.password_var = str(cfg.get('password_var') or 'MAIL_PASSWORD').strip()
        self.cooldown = float(defaults.get('auth_cooldown_minutes', 30))
        self._conn = None
        self._folders: list[dict] | None = None

    # ------------------------------------------------------------ credentials and the authentication marker
    def marker_path(self) -> Path:
        key = hashlib.sha1(f'{self.account_name}|{self.host}|{self.user}'.encode('utf-8', 'replace')).hexdigest()[:12]
        return settings.cache_dir('mailbox') / f'auth-rejected-{key}'

    def _marker(self) -> dict | None:
        path = self.marker_path()
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if time.time() < float(data['until']):
                return data
        except (OSError, ValueError, KeyError, TypeError):
            return None
        try:
            path.unlink()                       # expired
        except OSError:
            pass
        return None

    def _write_marker(self) -> None:
        now = time.time()
        document = json.dumps({'at': now, 'until': now + self.cooldown * 60})
        fd = os.open(self.marker_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(document)

    def _credentials(self) -> str:
        """The password, or Unavailable with the reason. Never connects, never reveals the value."""
        if not self.host:
            raise Unavailable('imap.host is not configured')
        if not self.credentials_file:
            raise Unavailable('imap.credentials_file is not configured')
        path = settings.expand(self.credentials_file)
        ok, why = settings.is_private(path)
        if not ok:
            raise Unavailable(why)
        try:
            values = settings.read_env_file(path)
        except OSError as exc:
            raise Unavailable(f'{path} cannot be read ({type(exc).__name__})') from None
        if not values.get(self.password_var):
            raise Unavailable(f'{path} has no {self.password_var} value')
        marker = self._marker()
        if marker:
            until = time.strftime('%H:%M', time.localtime(float(marker['until'])))
            raise Unavailable(f'the server rejected the login earlier; not trying again until {until} '
                              f'(auth_cooldown_minutes); fix the credentials, then delete {self.marker_path()}')
        return values[self.password_var]

    def diagnose(self, live: bool = False) -> str:
        """One line for `mailbox doctor`. Without LIVE it never reaches the connection factory."""
        self._credentials()
        if not live:
            return f'configured ({self.host}:{self.port}, user and credentials file ok); not tested, use --live'
        folders = self._list_folders()
        roles = self.roles(folders)
        shown = ', '.join(f'{r}={"+".join(n)}' for r, n in roles.items()) or 'no role folder found'
        return f'available: login ok, {len(folders)} folders; {shown}'

    # ------------------------------------------------------------ connection
    def _connect(self):
        if self._conn is not None:
            return self._conn
        password = self._credentials()
        try:
            conn = factory(self.host, self.port, TIMEOUT)
        except NETWORK_ERRORS as exc:
            raise Unavailable(f'cannot connect to {self.host}:{self.port} ({type(exc).__name__})') from None
        except imaplib.IMAP4.error as exc:
            raise Unavailable(f'the server refused the connection ({type(exc).__name__})') from None
        try:
            conn.login(self.user, password)
        except NETWORK_ERRORS as exc:                      # also IMAP4.abort: not a rejection
            raise Unavailable(f'the connection failed during login ({type(exc).__name__})') from None
        except imaplib.IMAP4.error:
            try:
                self._write_marker()
            except OSError:
                pass
            raise Unavailable('the server rejected the login; it will not be retried for '
                              f'{int(self.cooldown)} minutes') from None
        finally:
            del password
        self._conn = conn
        return conn

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001 - the session is over either way
                pass

    def _call(self, function, *args, **kwargs):
        """A server call whose connection-level failures make the backend unavailable for this run only."""
        try:
            return function(*args, **kwargs)
        except NETWORK_ERRORS as exc:
            raise Unavailable(f'the connection failed ({type(exc).__name__})') from None
        except imaplib.IMAP4.error as exc:
            raise Unavailable(f'the server refused a command ({type(exc).__name__})') from None

    # ------------------------------------------------------------ folders
    def _list_folders(self) -> list[dict]:
        if self._folders is not None:
            return self._folders
        conn = self._connect()
        typ, data = self._call(conn.list)
        if typ != 'OK':
            raise Unavailable('the server did not list its folders')
        folders = []
        for item in data or []:
            if item is None:
                continue
            literal = None
            if isinstance(item, tuple):
                line, literal = item[0], item[1]
                line = re.sub(rb'\s*\{\d+\}\s*$', b'', line)
            else:
                line = item
            text = line.decode('utf-8', 'replace')
            match = _LIST.match(text)
            if not match:
                continue
            flags = {f.lower() for f in match.group('flags').split()}
            if '\\noselect' in flags:
                continue
            raw = literal.decode('utf-8', 'replace') if literal is not None else match.group('name').strip()
            if literal is None and raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
                raw = re.sub(r'\\(.)', r'\1', raw[1:-1])
            delim = match.group('delim')
            delimiter = None if delim == 'NIL' else re.sub(r'\\(.)', r'\1', delim[1:-1])
            folders.append({'raw': raw, 'name': mutf7_decode(raw), 'flags': flags, 'delimiter': delimiter})
        self._folders = folders
        return folders

    def roles(self, folders: list[dict] | None = None) -> dict[str, list[str]]:
        """{role: [decoded folder names]}: the special-use folder plus every folder with a known name of the role."""
        folders = folders if folders is not None else self._list_folders()
        roles: dict[str, list[str]] = {}
        for role, flag in (('sent', '\\sent'), ('drafts', '\\drafts')):
            names = [f['name'] for f in folders if flag in f['flags']]
            known = set(mail_local.ROLE_NAMES[role])
            for f in folders:
                parts = f['name'].split(f['delimiter']) if f['delimiter'] else [f['name']]
                if len(parts) > ROLE_NAME_DEPTH:      # an archive tree can hold hundreds of folders called "Sent"
                    continue
                if mail_local._normal_base(parts[-1]) in known and f['name'] not in names:
                    names.append(f['name'])
            if names:
                roles[role] = names
        inbox = [f['name'] for f in folders if f['name'].upper() == 'INBOX']
        if inbox:
            roles = {'inbox': inbox, **roles}
        return roles

    def folders(self) -> list[dict]:
        roles = self.roles()
        return [{'name': f['name'], 'role': next((r for r, names in roles.items() if f['name'] in names), ''),
                 'size': 0, 'mtime': 0} for f in self._list_folders()]

    def _raw_name(self, name: str) -> str | None:
        for f in self._list_folders():
            if f['name'].casefold() == name.casefold() or f['raw'].casefold() == name.casefold():
                return f['raw']
        return None

    def folder_names(self, selector: str) -> list[str]:
        roles = self.roles()
        selector = (selector or 'all').strip()
        low = selector.lower()
        if low in ('all', 'inbox', 'sent', 'drafts'):
            wanted = ['inbox', 'sent'] if low == 'all' else [low]
            names = [n for r in wanted for n in roles.get(r, [])]
            if not names:
                raise Unavailable(f'no {low} folder found on the server')
            return list(dict.fromkeys(names))
        raw = self._raw_name(selector)
        if raw is None:
            raise Unavailable(f'the server has no folder named {selector!r}')
        return [next(f['name'] for f in self._list_folders() if f['raw'] == raw)]

    def _select(self, name: str) -> int:
        """Open NAME read-only (EXAMINE). Returns its UIDVALIDITY."""
        raw = self._raw_name(name)
        if raw is None:
            raise NotFound(name)
        conn = self._connect()
        typ, _ = self._call(conn.select, _quoted(raw), readonly=True)
        if typ != 'OK':
            raise Unavailable(f'the folder {name!r} cannot be opened')
        typ, data = self._call(conn.response, 'UIDVALIDITY')
        try:
            return int(data[-1])
        except (TypeError, ValueError, IndexError):
            return 0

    # ------------------------------------------------------------ ids
    @staticmethod
    def make_id(folder: str, validity: int, uid: int) -> str:
        return f'i:{quote(folder, safe="")}:{validity}:{uid}'

    @staticmethod
    def split_id(value: str) -> tuple[str, int, int]:
        parts = value.split(':')
        if len(parts) != 4 or parts[0] != 'i' or not parts[2].isdigit() or not parts[3].isdigit():
            raise NotFound(value)
        return unquote(parts[1]), int(parts[2]), int(parts[3])

    # ------------------------------------------------------------ search
    def criteria(self, f: Filters) -> tuple[list[str], bool]:
        """(UID SEARCH keys, whether a non-ASCII term was left for the local re-filter)."""
        keys: list[str] = []
        left = False
        if f.since:
            keys += ['SINCE', _imap_date(f.since - dt.timedelta(days=1))]
        if f.until:
            keys += ['BEFORE', _imap_date(f.until + dt.timedelta(days=2))]

        def term(value: str):
            nonlocal left
            value = _clean(value)
            if not _ascii(value):
                left = True
                return None
            return _quoted(value)
        if f.from_ and (t := term(f.from_)):
            keys += ['FROM', t]
        if f.to and (t := term(f.to)):
            keys += ['OR', 'TO', t, 'OR', 'CC', t, 'BCC', t]
        if f.subject and (t := term(f.subject)):
            keys += ['SUBJECT', t]
        pair = f.header_pair()
        if pair and (t := term(pair[1])) and re.fullmatch(r'[A-Za-z0-9-]+', pair[0]):
            keys += ['HEADER', pair[0], t]
        if f.text and (t := term(f.text)):
            keys += ['TEXT', t]
        return keys or ['ALL'], left

    def _uid_search(self, keys: list[str]) -> list[int]:
        conn = self._connect()
        typ, data = self._call(conn.uid, 'SEARCH', *keys)
        if typ != 'OK' or not data or not data[0]:
            return []
        return sorted(int(x) for x in data[0].split() if x.isdigit())

    def _fetch_headers(self, uids: list[int], extra: str = '') -> dict[int, dict]:
        conn = self._connect()
        fields = HEADER_FIELDS + (f' {extra.upper()}' if extra and re.fullmatch(r'[A-Za-z0-9-]+', extra) else '')
        out: dict[int, dict] = {}
        for at in range(0, len(uids), FETCH_BATCH):
            part = uids[at:at + FETCH_BATCH]
            typ, data = self._call(conn.uid, 'FETCH', ','.join(map(str, part)), f'(BODY.PEEK[HEADER.FIELDS ({fields})])')
            if typ != 'OK' or not data:
                continue
            for index, item in enumerate(data):
                if not isinstance(item, tuple):
                    continue
                meta = item[0].decode('utf-8', 'replace')
                found = re.search(r'UID (\d+)', meta)
                uid_text = found.group(1) if found else None
                if uid_text is None and index + 1 < len(data) and isinstance(data[index + 1], bytes):
                    later = re.search(rb'UID (\d+)', data[index + 1])      # some servers put the UID after the literal
                    uid_text = later.group(1).decode() if later else None
                if uid_text is None:
                    continue
                headers = split_headers(item[1] or b'')
                info = summarize(headers)
                info['headers'] = headers
                out[int(uid_text)] = info
        return out

    def _match(self, info: dict, f: Filters, pair) -> bool:
        """Re-apply the filters to the fetched headers, so imap and local give the same answers."""
        def has(needle, text):
            return needle.casefold() in text.casefold()
        if f.from_ and not has(f.from_, info['from_text']):
            return False
        if f.to and not has(f.to, info['rcpt']):
            return False
        if f.subject and not has(f.subject, info['subject']):
            return False
        lo, hi = f.bounds()
        if lo is not None and (info['date'] is None or info['date'] < lo):
            return False
        if hi is not None and (info['date'] is None or info['date'] >= hi):
            return False
        if f.has_attachment and not info['att']:
            return False
        if pair and not any(name == pair[0] and pair[1] in decode_words(value).casefold()
                            for name, value, _ in info['headers']):
            return False
        return True

    def search(self, f: Filters, limit: int) -> SearchResult:
        names = self.folder_names(f.folder)
        keys, left = self.criteria(f)
        cap = int(self.defaults.get('imap_scan_max', 2000))
        pair = f.header_pair()
        notes, found = [], []
        if f.text:
            notes.append("--text uses the server's search on imap and is best effort")
        for name in names:
            validity = self._select(name)
            uids = self._uid_search(keys)
            if len(uids) > cap:
                notes.append(f'{name}: {len(uids)} candidates on the server, only the newest {cap} were checked; '
                             'narrow the search with a date or an ASCII filter')
                uids = uids[-cap:]
            for uid, info in self._fetch_headers(uids, pair[0] if pair else '').items():
                if self._match(info, f, pair):
                    found.append((info, name, validity, uid))
        if left:
            notes.append('a non-ASCII filter term was applied locally to the headers fetched, not by the server')
        found.sort(key=lambda t: (t[0]['date'] is None, -(t[0]['date'] or 0), -t[3]))
        seen, unique = set(), []
        for entry in found:                       # the same message can sit in several folders of a role
            key = entry[0]['mid'] or (entry[1], entry[3])
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        items = [self._item(info, name, validity, uid) for info, name, validity, uid in unique[:max(limit, 0)]]
        return SearchResult(items, len(unique), notes, 'live')

    def _item(self, info: dict, folder: str, validity: int, uid: int) -> Item:
        direction, party = party_and_direction(info['from_addr'], info['from_party'], info['to_first'], self.own)
        return Item(self.make_id(folder, validity, uid), info['date'], direction, party, info['subject'],
                    bool(info['att']), folder, info['mid'] or '')

    # ------------------------------------------------------------ reading one message
    def fresh_of(self, item_id: str) -> str:
        return 'live'

    def fetch(self, item_id: str) -> bytes:
        folder, validity, uid = self.split_id(item_id)
        if self._raw_name(folder) is None:
            raise NotFound(item_id)
        if self._select(folder) != validity:
            raise NotFound(item_id)
        conn = self._connect()
        typ, data = self._call(conn.uid, 'FETCH', str(uid), '(BODY.PEEK[])')
        if typ == 'OK':
            for item in data or []:
                if isinstance(item, tuple) and item[1]:
                    return item[1]
        raise NotFound(item_id)

    def fetch_head(self, item_id: str) -> bytes:
        """The header block of one message (peek form), without its body and attachments."""
        folder, validity, uid = self.split_id(item_id)
        if self._raw_name(folder) is None or self._select(folder) != validity:
            raise NotFound(item_id)
        typ, data = self._call(self._connect().uid, 'FETCH', str(uid), '(BODY.PEEK[HEADER])')
        if typ == 'OK':
            for item in data or []:
                if isinstance(item, tuple) and item[1]:
                    return item[1]
        raise NotFound(item_id)

    def thread_folders(self, origin: str) -> list[str]:
        """The folders a thread lookup searches: bounded however many folders the server has (a mailbox can hold
        hundreds, and every header search scans a whole folder)."""
        roles = self.roles()
        names = [origin, *roles.get('inbox', [])[:1], *roles.get('sent', [])[:2]]
        return list(dict.fromkeys(names))[:THREAD_FOLDERS]

    def thread(self, item_id: str) -> SearchResult:
        """Related messages through their identifiers, in a few bounded header searches. Once the message itself is
        read, a failure of the lookup raises Interrupted, which carries its identifiers for the caller's fallback."""
        folder = self.split_id(item_id)[0]
        origin = summarize(split_headers(self.fetch_head(item_id).split(b'\r\n\r\n', 1)[0].split(b'\n\n', 1)[0]))
        ids = list(dict.fromkeys([m for m in [origin['mid'], *origin['refs']] if m]))
        try:
            return self._thread_lookup(folder, ids)
        except Unavailable as exc:
            raise Interrupted(str(exc), ids) from None

    def _thread_lookup(self, folder: str, ids: list[str]) -> SearchResult:
        names = self.thread_folders(folder)
        found: dict[str, tuple] = {}
        tried: set[str] = set()
        for _ in range(THREAD_ROUNDS):
            batch = [one for one in ids if one not in tried and _ascii(one)][:THREAD_IDS]
            if not batch:
                break
            tried.update(batch)
            alternatives = [['HEADER', header, _quoted(_clean(one))] for one in batch
                            for header in ('MESSAGE-ID', 'IN-REPLY-TO', 'REFERENCES')]
            groups = []
            for start in range(0, len(alternatives), THREAD_OR):
                chunk = alternatives[start:start + THREAD_OR]
                keys: list[str] = []
                for position, alt in enumerate(chunk):
                    keys += (['OR'] if position < len(chunk) - 1 else []) + alt
                groups.append(keys)
            for name in names:
                validity = self._select(name)
                hits = sorted({uid for keys in groups for uid in self._uid_search(keys)})
                for uid, info in self._fetch_headers(hits).items():
                    found.setdefault(info['mid'] or f'{name}:{uid}', (info, name, validity, uid))
                    ids.extend(m for m in [info['mid'], *info['refs']] if m and m not in ids)
            if len(found) >= 200:
                break
        notes = []
        if any(one not in tried and _ascii(one) for one in ids):
            notes.append(f'the thread lookup is bounded ({len(names)} folders, {THREAD_ROUNDS} rounds); '
                         'older or newer messages of a long thread may be missing')
        ordered = sorted(found.values(), key=lambda t: (t[0]['date'] is None, t[0]['date'] or 0, t[3]))
        items = [self._item(info, name, val, u) for info, name, val, u in ordered]
        return SearchResult(items, len(items), notes, 'live')
