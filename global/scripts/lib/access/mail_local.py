"""`local` backend of `mailbox`, part 1: finding a desktop mail client's store, and reading its mbox files.

Only the Thunderbird layout is implemented (profiles.ini, prefs.js, one extension-less mbox file per folder, `.sbd`
directories for subfolders). Nothing is configured by path: the profile, the account directory and the role folders
are derived on every run from the client's own files and the account's address (design D4).

Read-only by construction: every file is opened `rb`, no lock is taken, nothing is ever written next to the store.
Mbox files are streamed in binary chunks and never loaded whole; they can be several gigabytes.
"""
from __future__ import annotations

import configparser
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from access import settings
from access.mail_message import NotFound, Unavailable, mutf7_decode

DEFAULT_ROOTS = ['~/.thunderbird', '~/snap/thunderbird/common/.thunderbird',
                 '~/.var/app/org.mozilla.Thunderbird/.thunderbird']

ROLE_NAMES = {
    'inbox': ['inbox', 'bandeja de entrada', 'posteingang', 'boite de reception', 'boîte de réception',
              'posta in arrivo', 'caixa de entrada'],
    'sent': ['sent', 'sent items', 'sent mail', 'sent messages', 'enviados', 'elementos enviados', 'mensajes enviados',
             'gesendet', 'gesendete elemente', 'envoyés', 'inviati', 'itens enviados'],
    'drafts': ['drafts', 'draft', 'borradores', 'borrador', 'entwürfe', 'brouillons', 'bozze', 'rascunhos'],
}
ROLES = tuple(ROLE_NAMES)
SKIP_EXTENSIONS = ('.msf', '.dat', '.bak', '.tmp', '.json', '.html', '.rdf', '.lock', '.log')
_SUFFIX = re.compile(r'[-_ ]\d+$')


# ---------------------------------------------------------------- profile and account resolution

def _read_ini(path: Path) -> configparser.ConfigParser | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(path.read_text(encoding='utf-8', errors='replace'))
    except (OSError, configparser.Error):
        return None
    return parser


def _ini_path(root: Path, section) -> Path:
    path = Path(section.get('Path', ''))
    relative = section.get('IsRelative', '1').strip() != '0'
    return root / path if relative else path


def profiles_of(root: Path) -> tuple[list[Path], set[Path]]:
    """(profile directories, those the installation uses by default) found under one profile root."""
    profiles: list[Path] = []
    defaults: set[Path] = set()
    flagged: set[Path] = set()
    ini = _read_ini(root / 'profiles.ini')
    if ini is not None:
        for name in ini.sections():
            section = ini[name]
            if name.lower().startswith('profile') and section.get('Path'):
                path = _ini_path(root, section)
                profiles.append(path)
                if section.get('Default', '0').strip() == '1':
                    flagged.add(path)
            elif name.lower().startswith('install') and section.get('Default'):
                defaults.add(root / section['Default'])
    installs = _read_ini(root / 'installs.ini')
    if installs is not None:
        for name in installs.sections():
            if installs[name].get('Default'):
                defaults.add(root / installs[name]['Default'])
    if not profiles:
        try:
            profiles = [entry for entry in sorted(root.iterdir()) if (entry / 'prefs.js').is_file()]
        except OSError:
            profiles = []
    for path in defaults:
        if path not in profiles and (path / 'prefs.js').is_file():
            profiles.append(path)
    return profiles, (defaults or flagged)


_PREF = re.compile(r'^\s*user_pref\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*(.*?)\s*\)\s*;\s*$')


def read_prefs(path: Path) -> dict[str, object]:
    prefs: dict[str, object] = {}
    try:
        text = path.read_bytes().decode('utf-8', 'replace')
    except OSError:
        return prefs
    for line in text.splitlines():
        match = _PREF.match(line)
        if not match:
            continue
        key, raw = match.groups()
        try:
            prefs[key] = json.loads(raw)
        except ValueError:
            prefs[key] = raw.strip('"')
    return prefs


def _server_directory(profile: Path, prefs: dict, server: str, hostname: str, kind: str) -> Path | None:
    relative = prefs.get(f'mail.server.{server}.directory-rel')
    if isinstance(relative, str) and relative.startswith('[ProfD]'):
        path = profile / relative[len('[ProfD]'):]
        if path.is_dir():
            return path
    absolute = prefs.get(f'mail.server.{server}.directory')
    if isinstance(absolute, str) and absolute and Path(absolute).is_dir():
        return Path(absolute)
    for base in ('ImapMail' if kind == 'imap' else 'Mail',):
        path = profile / base / hostname
        if hostname and path.is_dir():
            return path
    return None


def account_directories(profile: Path, addresses: set[str]) -> tuple[list[tuple[Path, dict]], bool]:
    """([(existing account directory, folder hints)] in this profile for ADDRESSES, whether the preferences define
    the account). The hints are the identity's own sent and drafts folder names (`fcc_folder`, `draft_folder`)."""
    prefs = read_prefs(profile / 'prefs.js')
    servers = sorted({m.group(1) for key in prefs for m in [re.match(r'mail\.server\.(server\d+)\.', key)] if m})
    identities_of: dict[str, list[str]] = {}
    for key, value in prefs.items():
        match = re.fullmatch(r'mail\.account\.(account\d+)\.server', key)
        if match and isinstance(value, str):
            ids = prefs.get(f'mail.account.{match.group(1)}.identities')
            identities_of.setdefault(value, []).extend(i.strip() for i in str(ids).split(',') if ids)
    found: list[tuple[int, Path, dict]] = []
    defined = False
    for server in servers:
        kind = str(prefs.get(f'mail.server.{server}.type', ''))
        if kind not in ('imap', 'pop3'):
            continue
        user = str(prefs.get(f'mail.server.{server}.userName', '')).strip().lower()
        mails = {str(prefs.get(f'mail.identity.{i}.useremail', '')).strip().lower() for i in identities_of.get(server, [])}
        if user not in addresses and not (mails & addresses):
            continue
        defined = True
        hints: dict[str, list[str]] = {'sent': [], 'drafts': []}
        for ident in identities_of.get(server, []):
            for role, key in (('sent', 'fcc_folder'), ('drafts', 'draft_folder')):
                value = prefs.get(f'mail.identity.{ident}.{key}')
                if isinstance(value, str) and value:
                    segment = unquote(urlsplit(value).path.rsplit('/', 1)[-1])
                    if segment:
                        hints[role].append(mutf7_decode(segment))
        directory = _server_directory(profile, prefs, server, str(prefs.get(f'mail.server.{server}.hostname', '')), kind)
        if directory is not None:
            found.append((0 if kind == 'imap' else 1, directory, hints))
    return [(path, hints) for _, path, hints in sorted(found, key=lambda item: item[0])], defined


@dataclass
class Store:
    profile: Path
    account_dir: Path
    folders: dict[str, Path]                 # decoded folder name -> mbox file
    roles: dict[str, list[str]] = field(default_factory=dict)   # role -> folder names, most recently changed first
    aliases: dict[str, str] = field(default_factory=dict)       # casefolded raw (on-disk) name -> folder name

    def find(self, selector: str) -> str | None:
        """The folder named SELECTOR, in its decoded or its on-disk (modified UTF-7) form, any case."""
        key = selector.strip().casefold()
        for name in self.folders:
            if name.casefold() == key:
                return name
        return self.aliases.get(key)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def roots_of(local_cfg: dict) -> list[Path]:
    configured = local_cfg.get('profile_roots') if isinstance(local_cfg, dict) else None
    entries = [str(item) for item in configured] if isinstance(configured, list) and configured else DEFAULT_ROOTS
    return [settings.expand(entry) for entry in entries]


def resolve(account: dict) -> Store:
    """The store of ACCOUNT, derived from the client's own files. Raises Unavailable with the reason."""
    addresses = {str(account.get('address', '')).strip().lower(),
                 *[str(a).strip().lower() for a in account.get('aliases') or []]} - {''}
    local_cfg = account.get('local') if isinstance(account.get('local'), dict) else {}
    if not addresses:
        raise Unavailable('the account has no address')
    reasons = []
    roots = [root for root in roots_of(local_cfg) if root.is_dir()]
    if not roots:
        raise Unavailable('no mail client profile directory found')
    for root in roots:
        profiles, defaults = profiles_of(root)
        candidates = []
        for profile in profiles:
            if not (profile / 'prefs.js').is_file():
                continue
            directories, defined = account_directories(profile, addresses)
            if defined:
                candidates.append((profile, directories))
        if not candidates:
            reasons.append(f'{len(profiles)} profile(s) in {root.name}, none defines the account')
            continue
        candidates.sort(key=lambda item: (item[0] not in defaults, -_mtime(item[0] / 'prefs.js')))
        for profile, directories in candidates:
            if directories:
                directory, hints = directories[0]
                folders, aliases = list_folders(directory)
                store = Store(profile, directory, folders, aliases=aliases)
                store.roles = role_folders(folders, local_cfg.get('folders') or {}, hints, store.find)
                return store
        raise Unavailable('the account is defined in a profile, but its mail directory is missing there')
    raise Unavailable('no profile defines this account (' + '; '.join(reasons) + ')')


# ---------------------------------------------------------------- folders

def list_folders(account_dir: Path) -> tuple[dict[str, Path], dict[str, str]]:
    """({folder name: mbox file}, {casefolded on-disk name: folder name}). Names are decoded from the client's modified
    UTF-7; subfolders are `Parent/Child`. Index files and other side files are skipped."""
    folders: dict[str, Path] = {}
    aliases: dict[str, str] = {}

    def walk(directory: Path, prefix: str, raw_prefix: str):
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith('.'):
                continue
            if entry.is_dir(follow_symlinks=False) and entry.name.endswith('.sbd'):
                walk(Path(entry.path), prefix + mutf7_decode(entry.name[:-4]) + '/', raw_prefix + entry.name[:-4] + '/')
            elif entry.is_file(follow_symlinks=False) and not entry.name.lower().endswith(SKIP_EXTENSIONS):
                name = prefix + mutf7_decode(entry.name)
                folders[name] = Path(entry.path)
                aliases[(raw_prefix + entry.name).casefold()] = name

    walk(Path(account_dir), '', '')
    return folders, aliases


def _normal_base(name: str) -> str:
    return _SUFFIX.sub('', name.rsplit('/', 1)[-1].strip()).casefold()


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def role_folders(folders: dict[str, Path], pins: dict | None = None, hints: dict | None = None,
                 find=None) -> dict[str, list[str]]:
    """{role: [folder names]}, most recently changed first.

    A role is a list: the pinned name(s) of the configuration if any (a string or a list, replacing the rest);
    otherwise every non-empty folder whose base name (numeric suffix ignored) is a known name of the role or the name
    the identity's own preferences give for it. Empty folders count only when no other exists."""
    roles: dict[str, list[str]] = {}
    for role in ROLES:
        pin = (pins or {}).get(role)
        if isinstance(pin, str):
            pin = [pin]
        pinned = [p for p in pin if isinstance(p, str) and p] if isinstance(pin, list) else []
        resolved = [name for name in (find(p) if find else (p if p in folders else None) for p in pinned) if name]
        if resolved:
            roles[role] = list(dict.fromkeys(resolved))
            continue
        known = set(ROLE_NAMES[role]) | {_normal_base(h) for h in (hints or {}).get(role, [])}
        matches = [(name, path) for name, path in folders.items() if _normal_base(name) in known]
        full = [(n, p) for n, p in matches if _size(p) > 0]
        if not full and matches:
            full = [max(matches, key=lambda item: (_mtime(item[1]), item[0]))]
        if full:
            roles[role] = [n for n, _ in sorted(full, key=lambda item: (-_mtime(item[1]), item[0]))]
    return roles


def folder_info(name: str, path: Path, roles: dict[str, list[str]]) -> dict:
    try:
        info = path.stat()
        size, mtime = info.st_size, info.st_mtime
    except OSError:
        size, mtime = 0, 0.0
    role = next((r for r, names in roles.items() if name in names), '')
    return {'name': name, 'role': role, 'size': size, 'mtime': mtime}


# ---------------------------------------------------------------- mbox reader

CHUNK = 8 << 20
HEADER_SCAN_MAX = 50000       # default of the setting `header_scan_max`: never below the cut this replaced
HEADER_START_READ = 16 << 10
HEADER_MAX = 4 << 20
_NEEDLE = b'\nFrom - '
_SEPARATOR = re.compile(rb'From - [A-Z][a-z]{2} [A-Z][a-z]{2} [ 0-9][0-9] [0-9]{2}:[0-9]{2}:[0-9]{2} [0-9]{4}\r?\n')
_HEADER_END = re.compile(rb'\r?\n\r?\n')


def iter_separators(fh, begin: int, size: int, chunk: int = CHUNK):
    """Yield (offset, length of the separator line) for every separator at or after BEGIN and before SIZE.

    A separator is `From - ` plus an asctime date, exactly, at the start of the file or after a blank line. The
    file is read in CHUNK-byte pieces; a candidate cut by a chunk boundary is carried to the next read."""
    chunk = max(int(chunk), 16)
    if begin <= 0:
        data, base, position = b'\n\n', -2, 0     # a virtual blank line before the first byte
    else:
        base = max(begin - 3, 0)
        position = base
        data = b''
    last = begin - 1
    while True:
        want = min(chunk, size - position)
        fh.seek(position)   # the caller may read headers through the same handle between two yields
        new = fh.read(want) if want > 0 else b''
        position += len(new)
        data += new
        eof = not new or position >= size
        unresolved = None
        index = data.find(_NEEDLE)
        while index != -1:
            start = index + 1
            offset = base + start
            if offset > last and offset >= begin:
                if len(data) - start < 64 and not eof:
                    unresolved = index
                    break
                blank = data[index - 1:index] == b'\n' or data[index - 2:index] == b'\n\r'
                match = _SEPARATOR.match(data, start)
                if blank and match:
                    last = offset
                    yield offset, match.end() - match.start()
            index = data.find(_NEEDLE, index + 1)
        if eof:
            return
        cut = max(unresolved - 3, 0) if unresolved is not None else max(len(data) - 10, 0)
        base += cut
        data = data[cut:]


def first_separator_ok(fh, offset: int) -> bool:
    """True when a separator line starts exactly at OFFSET (used to check an index against its file)."""
    try:
        fh.seek(offset)
        return bool(_SEPARATOR.match(fh.read(64)))
    except OSError:
        return False


def read_header_block(fh, start: int, end: int) -> tuple[int, int, bytes]:
    """(offset of the first header byte, offset of the first body byte, header block) of the message that starts
    with its separator line at START and ends before END."""
    length = min(end - start, HEADER_START_READ)
    while True:
        fh.seek(start)
        data = fh.read(length)
        sep = _SEPARATOR.match(data)
        sep_len = sep.end() if sep else 0
        block = data[sep_len:]
        found = _HEADER_END.search(b'\n' + block)
        if found:
            return (start + sep_len, start + sep_len + found.end() - 1, block[:found.start()])
        if length >= end - start or length >= HEADER_MAX:
            return start + sep_len, start + len(data), block
        length = min(length * 4, end - start, HEADER_MAX)


def read_message(fh, header_start: int, end: int, cap: int = 64 << 20) -> bytes:
    """The message bytes after its separator line, without the client's own status lines."""
    fh.seek(header_start)
    raw = fh.read(min(max(end - header_start, 0), cap))
    while raw.startswith((b'X-Mozilla-Status:', b'X-Mozilla-Status2:', b'X-Mozilla-Keys:')):
        raw = raw.split(b'\n', 1)[1] if b'\n' in raw else b''
    return raw


def open_mbox(path):
    """The only way this module opens a store file: read-only binary, no lock."""
    return open(path, 'rb')


# ---------------------------------------------------------------- the backend

class LocalBackend:
    """The `local` backend: answers from the desktop client's own mbox files through the header index."""
    name = 'local'
    NOTE_NO_STATUS = ('this local copy may hold mail deleted or moved since the client last compacted it '
                      '(its folder files carry no status lines)')

    def __init__(self, account: dict, own: set[str], defaults: dict):
        self.account, self.own, self.defaults = account, own, defaults
        self._store: Store | None = None
        self._indexes: dict[str, object] = {}
        self._builds: dict[str, int] = {}   # folder -> messages, for indexes this run built from scratch
        self.chunk = CHUNK

    # -- resolution
    def store(self) -> Store:
        if self._store is None:
            self._store = resolve(self.account)
        return self._store

    def folder_names(self, selector: str, strict: bool = True) -> list[str]:
        """The folders a `--folder` value stands for: a role is every folder of that role, `all` is inbox plus sent,
        anything else is one folder named in its decoded or on-disk form."""
        store = self.store()
        selector = (selector or 'all').strip()
        if selector.lower() in ('all', 'inbox', 'sent', 'drafts'):
            roles = ['inbox', 'sent'] if selector.lower() == 'all' else [selector.lower()]
            names = [n for r in roles for n in store.roles.get(r, [])]
            if not names or (strict and selector.lower() != 'all' and any(r not in store.roles for r in roles)):
                raise Unavailable(f'no {selector.lower()} folder found in the local store')
            return list(dict.fromkeys(names))
        found = store.find(selector)
        if found:
            return [found]
        raise Unavailable(f'the local store has no folder named {selector!r}')

    def index(self, name: str):
        from access import mail_index
        if name not in self._indexes:
            store = self.store()
            if name not in store.folders:
                raise Unavailable(f'the local store has no folder named {name!r}')
            index = mail_index.FolderIndex(store.folders[name], settings.cache_dir('mailbox') / 'index')
            index.refresh(self.chunk)
            if index.stats.rebuilt and index.count():
                self._builds[name] = index.count()
            self._indexes[name] = index
        return self._indexes[name]

    def close(self):
        for index in self._indexes.values():
            index.close()
        self._indexes = {}

    # -- ids
    @staticmethod
    def make_id(folder: str, idh: str) -> str:
        from urllib.parse import quote
        return f'l:{quote(folder, safe="")}:{idh}'

    @staticmethod
    def split_id(value: str) -> tuple[str, str]:
        parts = value.split(':')
        if len(parts) != 3 or parts[0] != 'l' or not parts[2]:
            raise NotFound(value)
        return unquote(parts[1]), parts[2]

    # -- helpers
    def freshness(self, names: list[str]) -> str:
        """The most recent change among the folders used, and how many folders that is."""
        import time
        from access.mail_message import format_age, format_when
        store = self.store()
        newest = max((_mtime(store.folders[n]) for n in names), default=0.0)
        count = f'{len(names)} folder' + ('' if len(names) == 1 else 's')
        return f'local copy: {count}, last change {format_when(newest)} ({format_age(time.time() - newest)} ago)'

    def _item(self, row, folder: str):
        from access.mail_message import Item, party_and_direction
        direction, party = party_and_direction(row['from_addr'], row['from_party'], row['to_first'], self.own)
        return Item(self.make_id(folder, row['idh']), row['date'], direction, party, row['subject'],
                    bool(row['att']), folder, row['mid'] or '')

    def status(self) -> dict:
        """Details of a usable store (raises Unavailable with the reason otherwise)."""
        store = self.store()
        names = [n for r in ROLES for n in store.roles.get(r, [])]
        return {'profile': store.profile.name, 'roles': {r: list(n) for r, n in store.roles.items()},
                'freshness': self.freshness(list(dict.fromkeys(names))) if names else ''}

    def folders(self) -> list[dict]:
        store = self.store()
        return [folder_info(n, p, store.roles) for n, p in sorted(store.folders.items())]

    # -- reads
    def search(self, f, limit: int):
        from access import mail_message as mm
        names = self.folder_names(f.folder)
        pair = f.header_pair()
        cap = max(int(self.defaults.get('header_scan_max', HEADER_SCAN_MAX)), 1)
        tagged, notes, seen = [], [], set()
        for name in names:
            index = self.index(name)
            if name in self._builds:
                notes.append(f'the index of {name} was built from scratch ({self._builds.pop(name)} messages)')
            rows = index.select(f)
            if pair:
                # the header is read before the status pass, on the newest candidates only, so that `live` reads the
                # matches and not the whole folder; the cut is the one setting `header_scan_max`, and it is stated
                candidates = len(rows)
                rows, scanned = index.header_filter(rows[:cap], pair[0], pair[1])
                if scanned < candidates:
                    notes.append(f'--header checked the newest {scanned} of {candidates} messages of {name} left by the '
                                 'other filters; narrow the search or raise header_scan_max')
            rows = index.live(rows)
            if index.without_status() and self.NOTE_NO_STATUS not in notes:
                notes.append(self.NOTE_NO_STATUS)
            tagged.extend((row, name) for row in rows)
        tagged.sort(key=lambda t: (t[0]['date'] is None, -(t[0]['date'] or 0), -t[0]['start']))
        unique = []
        for row, name in tagged:                       # the same message can sit in several folders of a role
            if row['idh'] in seen:
                continue
            seen.add(row['idh'])
            unique.append((row, name))
        tagged = unique
        if f.text:
            cap = int(self.defaults.get('text_scan_max', 1000))
            needle = f.text.casefold()
            kept = []
            for row, name in tagged[:cap]:
                try:
                    raw = self._indexes[name].raw(row, 2 << 20)
                    if needle in mm.body_text(mm.parse_message(raw)).casefold():
                        kept.append((row, name))
                except Exception:  # noqa: BLE001 - one unreadable message must not stop the scan
                    continue
            if len(tagged) > cap:
                notes.append(f'--text scanned the newest {cap} of {len(tagged)} messages left by the other filters; '
                             'add filters to narrow it')
            tagged = kept
        items = [self._item(row, name) for row, name in tagged[:max(limit, 0)]]
        return mm.SearchResult(items, len(tagged), notes, self.freshness(names))

    def fresh_of(self, item_id: str) -> str:
        folder, _ = self.split_id(item_id)
        return self.freshness([folder]) if folder in self.store().folders else 'local copy'

    def fetch(self, item_id: str) -> bytes:
        folder, idh = self.split_id(item_id)
        if folder not in self.store().folders:
            raise NotFound(item_id)
        index = self.index(folder)
        row = index.lookup(idh)
        if row is None:
            raise NotFound(item_id)
        return index.raw(row)

    def thread(self, item_id: str):
        folder, idh = self.split_id(item_id)
        if folder not in self.store().folders:
            raise NotFound(item_id)
        names = list(dict.fromkeys([folder, *self.folder_names('all', strict=False)]))
        origin = self.index(folder).lookup(idh)
        if origin is None:
            raise NotFound(item_id)
        return self._walk_thread(names, self.index(folder).references_of(origin))

    def thread_by_message_ids(self, message_ids):
        """The thread of a message this copy may hold, found from its Message-ID and references (the fallback of a
        live lookup that failed). Unavailable when the copy has none of them."""
        names = self.folder_names('all', strict=False)
        result = self._walk_thread(names, {m for m in message_ids if m})
        if not result.items:
            raise Unavailable('the local copy holds no message with that Message-ID')
        return result

    def _walk_thread(self, names: list[str], ids: set[str]):
        from access import mail_message as mm
        found: dict[str, tuple] = {}
        for _ in range(8):
            before = len(ids), len(found)
            for name in names:
                index = self.index(name)
                for row in index.related(ids):
                    found.setdefault(row['idh'], (row, name))
                    ids |= index.references_of(row)
            if (len(ids), len(found)) == before or len(found) >= 200:
                break
        ordered = sorted(found.values(), key=lambda t: (t[0]['date'] is None, t[0]['date'] or 0, t[0]['start']))
        items = [self._item(row, name) for row, name in ordered]
        notes = [self.NOTE_NO_STATUS] if any(self.index(n).without_status() for n in names) else []
        return mm.SearchResult(items, len(items), notes, self.freshness(names))

    def paths_of(self, selector: str) -> list[Path]:
        """The file of every folder a selector stands for, most recently changed first."""
        store = self.store()
        names = self.folder_names(selector or 'inbox', strict=True)
        return [store.folders[n].resolve() for n in names]
