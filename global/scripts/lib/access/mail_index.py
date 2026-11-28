"""Incremental header index of one mbox file (SQLite), for the `local` backend of `mailbox` (design D5).

* Header blocks only: bodies are never stored; each row keeps the offsets needed to read the message back later.
* Incremental: when the file grew and the last indexed message still starts where recorded, only the bytes from that
  message on are parsed. When it shrank, or that check fails, the client compacted the file and the index is rebuilt.
* The mbox is only opened `rb`, without a lock, so a running mail client is never blocked.
* The index is the owner's correspondence metadata: its directory is 0700, its file 0600, and it lives in the user's
  cache directory, never in a repository or a notes folder.
* A message whose status flags carry the client's "deleted" bit is not indexed, and the bit is read again from the file
  for every result, because the client rewrites that line in place without changing the file's size.
* Header index: the decoded, case-folded values of a few configured headers (`hdrs`). A row of `hdr_cov` says that every
  value of that name of that message is there (possibly none); it is committed in the same transaction as the values,
  and a trigger stored in the file removes both with the message row, also for a copy of this code that does not know
  these tables. A message without that row is read from the file, so a missing or partial index never changes an answer.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from access import mail_local
from access.mail_message import Filters, Unavailable, decode_words, split_headers, summarize

VERSION = '3'
BATCH = 2000
PROGRESS_EVERY = BATCH       # messages between two progress reports of a build
SIGNATURE_BYTES = 256
DELETED = 0x0008

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS msgs (
  rid INTEGER PRIMARY KEY, start INTEGER, hstart INTEGER, hend INTEGER, mend INTEGER,
  idh TEXT, mid TEXT, date REAL, from_text TEXT, from_addr TEXT, from_party TEXT, rcpt TEXT, to_first TEXT,
  subject TEXT, att INTEGER, st_off INTEGER, st_len INTEGER, has_status INTEGER);
CREATE TABLE IF NOT EXISTS refs (rid INTEGER, ref TEXT);
CREATE INDEX IF NOT EXISTS msgs_idh ON msgs(idh);
CREATE INDEX IF NOT EXISTS msgs_mid ON msgs(mid);
CREATE INDEX IF NOT EXISTS msgs_date ON msgs(date);
CREATE INDEX IF NOT EXISTS msgs_start ON msgs(start);
CREATE INDEX IF NOT EXISTS refs_ref ON refs(ref);
CREATE INDEX IF NOT EXISTS refs_rid ON refs(rid);
"""
# apart from SCHEMA because a file written before it has to be written to take it; the trigger stays last, so no value
# is ever kept in a file that lacks it
HEADER_SCHEMA = """
CREATE TABLE IF NOT EXISTS hdrs (rid INTEGER, name TEXT, value TEXT);
CREATE INDEX IF NOT EXISTS hdrs_name ON hdrs(name, rid);
CREATE INDEX IF NOT EXISTS hdrs_rid ON hdrs(rid);
CREATE TABLE IF NOT EXISTS hdr_cov (rid INTEGER, name TEXT, PRIMARY KEY (name, rid));
CREATE INDEX IF NOT EXISTS hdr_cov_rid ON hdr_cov(rid);
CREATE TRIGGER IF NOT EXISTS msgs_headers_delete AFTER DELETE ON msgs BEGIN
  DELETE FROM hdrs WHERE rid = old.rid;
  DELETE FROM hdr_cov WHERE rid = old.rid;
END;
"""
COLUMNS = ('start, hstart, hend, mend, idh, mid, date, from_text, from_addr, from_party, rcpt, to_first, subject, att, '
           'st_off, st_len, has_status')


@dataclass
class RefreshStats:
    opened: bool = False          # the mbox file was opened at all
    rebuilt: bool = False
    bytes_scanned: int = 0        # bytes searched for separators
    messages: int = 0             # rows added
    deleted_skipped: int = 0


def _cf(value):
    return value.casefold() if isinstance(value, str) else ''


def header_values(headers, name: str):
    """The values of every occurrence of NAME in a parsed header list, as a header filter compares them."""
    return (decode_words(value).casefold() for found, value, _ in headers if found == name)


def any_contains(values, needle: str) -> bool:
    """The one match of a header filter, on the file and on the index: NEEDLE in any value (an empty one: presence)."""
    return any(needle in value for value in values)


def _identity(row) -> tuple:
    """What must be equal, besides the row id (ids are reused), for two rows to be the same message."""
    return row['start'], row['hstart'], row['hend'], row['idh']


def _state(info) -> tuple[str, str]:
    """A file's size and modification time, as `meta` records them."""
    return str(info.st_size), str(info.st_mtime_ns)


def _signature(fh, start: int, limit: int) -> str:
    """Hash of the separator line and the first header bytes of the message at START, without the client's own
    status lines (they are rewritten in place)."""
    header_start, _, block = mail_local.read_header_block(fh, start, limit)
    kept = b'\n'.join(line for line in block.split(b'\n') if not line.lower().startswith(b'x-mozilla-'))
    fh.seek(start)
    return hashlib.sha1(fh.read(header_start - start) + kept[:SIGNATURE_BYTES]).hexdigest()


def message_row(fh, start: int, end: int):
    """(row values as a tuple for COLUMNS, deleted?, reference ids, parsed headers) of the message at START."""
    hstart, hend, block = mail_local.read_header_block(fh, start, end)
    headers = split_headers(block)
    info = summarize(headers)
    status = info['status']
    if info['mid']:
        idh = hashlib.sha1(info['mid'].encode('utf-8', 'replace')).hexdigest()[:12]
    else:
        seed = '|'.join(('nomid', info['date_raw'], info['from_raw'], info['subject']))
        idh = hashlib.sha1(seed.encode('utf-8', 'replace')).hexdigest()[:12]
    deleted = bool(status and status[0] & DELETED)
    values = (start, hstart, hend, end, idh, info['mid'], info['date'], info['from_text'], info['from_addr'],
              info['from_party'], info['rcpt'], info['to_first'], info['subject'], 1 if info['att'] else 0,
              hstart + status[1] if status else -1, status[2] if status else 0, 1 if status else 0)
    return values, deleted, info['refs'], headers


class FolderIndex:
    def __init__(self, mbox: Path, directory: Path, headers=(), progress=None):
        """HEADERS: the lowercase names the header index keeps. PROGRESS(event, done, total) is told while an index is
        being built (events `build`, `headers`; DONE 0 is the start)."""
        self.mbox = Path(mbox)
        self.headers = tuple(sorted(set(headers)))
        self.progress = progress or (lambda event, done, total: None)
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        key = hashlib.sha1(str(self.mbox.resolve()).encode('utf-8', 'replace')).hexdigest()[:16]
        self.db_path = directory / f'index-{key}.sqlite'
        if not self.db_path.exists():
            os.close(os.open(self.db_path, os.O_CREAT | os.O_RDWR, 0o600))
        self.db = sqlite3.connect(self.db_path, timeout=120, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('cf', 1, _cf, deterministic=True)
        self.db.executescript(SCHEMA)
        try:
            self.db.executescript(HEADER_SCHEMA)
        except sqlite3.OperationalError:      # held by another run, read only or full: this run scans the file
            self.headers = ()
        self.stats = RefreshStats()

    def close(self):
        self.db.close()

    # ------------------------------------------------------------ refresh
    def meta(self) -> dict[str, str]:
        return {row['key']: row['value'] for row in self.db.execute('SELECT key, value FROM meta')}

    def _put_meta(self, **values):
        self.db.executemany('INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)',
                            [(key, str(value)) for key, value in values.items()])

    def refresh(self, chunk: int = mail_local.CHUNK) -> RefreshStats:
        """Bring the index up to date with the file and say how much of it had to be read."""
        stats = RefreshStats()
        self.stats = stats
        try:
            info = os.stat(self.mbox)
        except OSError as exc:
            raise Unavailable(f'{self.mbox.name}: cannot be read ({type(exc).__name__})') from None
        meta = self.meta()
        self._purge_headers(meta)
        if (meta.get('version') == VERSION and meta.get('size') == str(info.st_size)
                and meta.get('mtime_ns') == str(info.st_mtime_ns)):
            return stats
        try:
            fh = mail_local.open_mbox(self.mbox)
        except OSError as exc:
            raise Unavailable(f'{self.mbox.name}: cannot be opened ({type(exc).__name__})') from None
        stats.opened = True
        with fh:
            fstat = os.fstat(fh.fileno())
            size = fstat.st_size
            last_start = int(meta.get('last_start', '-1')) if meta.get('version') == VERSION else None
            begin = 0
            if last_start is None or size < int(meta.get('size', '0')):
                rebuild = True
            elif last_start < 0:
                rebuild = False
                begin = 0
            else:
                rebuild = not (mail_local.first_separator_ok(fh, last_start) and meta.get('first_sig') == self._first_sig(fh, size)
                               and meta.get('last_sig') == _signature(fh, last_start, size))
                begin = last_start
            stats.rebuilt = rebuild
            self.db.execute('BEGIN IMMEDIATE')
            try:
                if rebuild:
                    self.db.execute('DELETE FROM msgs')
                    self.db.execute('DELETE FROM refs')
                    begin = 0
                elif size == int(meta.get('size', '0')):
                    # same size, newer mtime: the client flipped a flag in place; nothing to parse
                    self._put_meta(mtime_ns=fstat.st_mtime_ns)
                    self.db.execute('COMMIT')
                    return stats
                else:
                    self.db.execute('DELETE FROM refs WHERE rid IN (SELECT rid FROM msgs WHERE start >= ?)', (begin,))
                    self.db.execute('DELETE FROM msgs WHERE start >= ?', (begin,))
                if rebuild and size:
                    self.progress('build', 0, 0)
                self._scan(fh, begin, size, chunk, stats)
                self._put_meta(version=VERSION, size=size, mtime_ns=fstat.st_mtime_ns,
                               last_start=self._last_scanned, first_sig=self._first_sig(fh, size),
                               last_sig=_signature(fh, self._last_scanned, size) if self._last_scanned >= 0 else '')
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
        return stats

    _last_scanned = -1

    def _purge_headers(self, meta: dict):
        """Forget the header names no longer configured, in one transaction. A database that refuses (locked by another
        run) leaves it for the next one: rows that stay are still true."""
        wanted = ','.join(self.headers)
        if meta.get('hdr_names', '') == wanted:
            return
        marks = ','.join('?' * len(self.headers))
        try:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                for table in ('hdrs', 'hdr_cov'):
                    self.db.execute(f'DELETE FROM {table} WHERE name NOT IN ({marks})', self.headers)
                self._put_meta(hdr_names=wanted)
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
        except sqlite3.OperationalError:
            pass

    def _cover(self, rid: int, headers, name: str):
        """Keep the values of NAME of one message, once, with the row saying they are all there. Inside a transaction."""
        if self.db.execute('INSERT OR IGNORE INTO hdr_cov(rid, name) VALUES (?, ?)', (rid, name)).rowcount == 1:
            self.db.executemany('INSERT INTO hdrs(rid, name, value) VALUES (?, ?, ?)',
                                [(rid, name, value) for value in header_values(headers, name)])

    def _first_sig(self, fh, size: int) -> str:
        return _signature(fh, 0, size) if size and mail_local.first_separator_ok(fh, 0) else ''

    def _scan(self, fh, begin: int, size: int, chunk: int, stats: RefreshStats):
        stats.bytes_scanned = max(size - begin, 0)
        batch: list[tuple] = []
        refs_batch: list[tuple] = []
        kept_batch: list[list] = []
        self._last_scanned = begin if begin > 0 else -1
        pending = None

        def flush():
            nonlocal batch, refs_batch, kept_batch
            if not batch:
                return
            for values, refs, kept in zip(batch, refs_batch, kept_batch):
                cursor = self.db.execute(f'INSERT INTO msgs({COLUMNS}) VALUES ({",".join("?" * 17)})', values)
                if refs:
                    self.db.executemany('INSERT INTO refs(rid, ref) VALUES (?, ?)', [(cursor.lastrowid, r) for r in refs])
                rid = cursor.lastrowid
                for name in self.headers:
                    self._cover(rid, kept, name)
            batch, refs_batch, kept_batch = [], [], []

        def finish(start: int, end: int):
            values, deleted, refs, headers = message_row(fh, start, end)
            self._last_scanned = start
            if deleted:
                stats.deleted_skipped += 1
                return
            batch.append(values)
            refs_batch.append(refs)
            kept_batch.append([header for header in headers if header[0] in self.headers])
            stats.messages += 1
            if stats.rebuilt and stats.messages % PROGRESS_EVERY == 0:
                self.progress('build', stats.messages, 0)
            if len(batch) >= BATCH:
                flush()

        for offset, _length in mail_local.iter_separators(fh, begin, size, chunk):
            if pending is not None:
                finish(pending, offset)
            pending = offset
        if pending is not None:
            finish(pending, size)
        flush()

    # ------------------------------------------------------------ queries
    def count(self) -> int:
        return self.db.execute('SELECT COUNT(*) FROM msgs').fetchone()[0]

    def without_status(self) -> int:
        return self.db.execute('SELECT COUNT(*) FROM msgs WHERE has_status = 0').fetchone()[0]

    def select(self, f: Filters) -> list[sqlite3.Row]:
        """Rows matching the filters that the index can answer, newest first, undated last."""
        where, params = ['1=1'], []
        for column, needle in (('from_text', f.from_), ('rcpt', f.to), ('subject', f.subject)):
            if needle:
                where.append(f'instr(cf({column}), ?) > 0')
                params.append(needle.casefold())
        lo, hi = f.bounds()
        if lo is not None:
            where.append('date >= ?')
            params.append(lo)
        if hi is not None:
            where.append('date < ?')
            params.append(hi)
        if f.has_attachment:
            where.append('att = 1')
        sql = f'SELECT rid, {COLUMNS} FROM msgs WHERE {" AND ".join(where)} ORDER BY date IS NULL, date DESC, start DESC'
        return self.db.execute(sql, params).fetchall()

    def live(self, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
        """ROWS minus messages the client flagged deleted since indexing, and minus repeated Message-IDs."""
        flagged = set()
        with_status = [row for row in rows if row['st_off'] >= 0]
        if with_status:
            try:
                with mail_local.open_mbox(self.mbox) as fh:
                    for row in sorted(with_status, key=lambda r: r['st_off']):
                        fh.seek(row['st_off'])
                        digits = fh.read(row['st_len'])
                        try:
                            if int(digits, 16) & DELETED:
                                flagged.add(row['rid'])
                        except ValueError:
                            pass
            except OSError:
                pass
        seen, out = set(), []
        for row in rows:
            if row['rid'] in flagged or row['idh'] in seen:
                continue
            seen.add(row['idh'])
            out.append(row)
        return out

    def lookup(self, idh: str) -> sqlite3.Row | None:
        rows = self.db.execute(f'SELECT rid, {COLUMNS} FROM msgs WHERE idh = ? ORDER BY start', (idh,)).fetchall()
        live = self.live(rows)
        return live[0] if live else None

    def header_lookup(self, rows, name: str, needle: str):
        """`header_filter` for a name in `headers`: the same (matches, scanned), answering the messages the header index
        covers from it, reading only the others from the file and keeping what was read for the next search."""
        covered: dict[int, list] = {}      # rid -> [identity, matches]; one statement, so one snapshot
        for row in self.db.execute(
                'SELECT m.rid, m.start, m.hstart, m.hend, m.idh, h.value FROM hdr_cov c JOIN msgs m ON m.rid = c.rid '
                'LEFT JOIN hdrs h ON h.rid = c.rid AND h.name = c.name WHERE c.name = ?', (name,)):
            entry = covered.setdefault(row['rid'], [_identity(row), False])
            if row['value'] is not None and any_contains((row['value'],), needle):
                entry[1] = True
        known = [covered.get(row['rid']) for row in rows]
        known = [entry if entry and entry[0] == _identity(row) else None for row, entry in zip(rows, known)]
        total = known.count(None)

        out, scanned, reads = [], 0, 0
        fh, opened_as, read, storing = None, None, [], True
        try:
            try:
                for row, entry in zip(rows, known):
                    if entry is not None:
                        matched = entry[1]
                    else:
                        if fh is None:
                            self.progress('headers', 0, total)
                            fh = mail_local.open_mbox(self.mbox)
                            opened_as = _state(os.fstat(fh.fileno()))
                        fh.seek(row['hstart'])
                        length = max(row['hend'] - row['hstart'], 0)
                        block = fh.read(length)
                        headers = split_headers(block)
                        matched = any_contains(header_values(headers, name), needle)
                        reads += 1
                        if reads % PROGRESS_EVERY == 0:
                            self.progress('headers', reads, total)
                        if storing and len(block) == length:      # a short block is not the message's header
                            read.append((row, [header for header in headers if header[0] in self.headers]))
                            if len(read) >= BATCH:
                                storing, read = self._store_headers(fh, opened_as, read), []
                    scanned += 1
                    if matched:
                        out.append(row)
            except OSError:
                pass
            if read and storing:
                self._store_headers(fh, opened_as, read)
        finally:
            if fh is not None:
                fh.close()
        return out, scanned

    def _store_headers(self, fh, opened_as: tuple, read: list) -> bool:
        """Keep the headers READ [(row, parsed headers)] through FH, only while the file is the one the index describes:
        as it was when opened, as `meta` records it and as it is now. False: keep nothing more in this run. A database
        that cannot be written never fails the search."""
        try:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                meta = self.meta()
                same = (meta.get('size'), meta.get('mtime_ns')) == opened_as == _state(os.fstat(fh.fileno()))
                for row, headers in read if same else ():
                    if self.db.execute('SELECT 1 FROM msgs WHERE rid = ? AND start = ? AND hstart = ? AND hend = ? '
                                       'AND idh = ?', (row['rid'], *_identity(row))).fetchone():
                        for name in self.headers:
                            self._cover(row['rid'], headers, name)
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
        except (sqlite3.Error, OSError):
            return False
        return same

    def header_pairs(self, row) -> list[tuple[str, str]]:
        with mail_local.open_mbox(self.mbox) as fh:
            fh.seek(row['hstart'])
            block = fh.read(max(row['hend'] - row['hstart'], 0))
        return [(name, decode_words(value)) for name, value, _ in split_headers(block)]

    def header_filter(self, rows, name: str, needle: str):
        """(rows whose header NAME contains NEEDLE, number scanned). It has no bound of its own: the caller cuts ROWS
        to the candidates it is willing to read (`header_scan_max`), so the bound is stated in one place."""
        out, scanned = [], 0
        try:
            with mail_local.open_mbox(self.mbox) as fh:
                for row in rows:
                    fh.seek(row['hstart'])
                    block = fh.read(max(row['hend'] - row['hstart'], 0))
                    scanned += 1                      # counted once its header was read: a failed read is not a check
                    if any_contains(header_values(split_headers(block), name), needle):
                        out.append(row)
        except OSError:
            pass
        return out, scanned

    def raw(self, row, cap: int = 64 << 20) -> bytes:
        with mail_local.open_mbox(self.mbox) as fh:
            return mail_local.read_message(fh, row['hstart'], row['mend'], cap)

    def references_of(self, row) -> set[str]:
        ids = {r['ref'] for r in self.db.execute('SELECT ref FROM refs WHERE rid = ?', (row['rid'],))}
        if row['mid']:
            ids.add(row['mid'])
        return ids

    def related(self, ids: set[str]) -> list[sqlite3.Row]:
        """Rows whose Message-ID is in IDS or that reference one of them."""
        found: dict[int, sqlite3.Row] = {}
        listed = sorted(ids)
        for at in range(0, len(listed), 400):
            part = listed[at:at + 400]
            marks = ','.join('?' * len(part))
            for row in self.db.execute(
                    f'SELECT rid, {COLUMNS} FROM msgs WHERE mid IN ({marks}) OR rid IN '
                    f'(SELECT rid FROM refs WHERE ref IN ({marks}))', part + part):
                found[row['rid']] = row
        return self.live(sorted(found.values(), key=lambda r: r['start']))
