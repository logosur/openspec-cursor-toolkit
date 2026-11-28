"""Message-level helpers shared by the `local` and `imap` backends of `mailbox`.

Header decoding, dates, addresses, body extraction (HTML reduced to text), quote stripping, attachment listing and
safe saving, and the common data types (filters, result items, the two exceptions a backend may raise). Everything
here works on bytes or strings handed in; it never opens a mailbox and never raises on a malformed message.
"""
from __future__ import annotations

import base64
import datetime as dt
import email
import email.header
import email.policy
import email.utils
import errno
import html.parser
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


class Unavailable(Exception):
    """A backend cannot answer; the text is the one-line reason."""


class Interrupted(Unavailable):
    """A live lookup failed after the message itself had been read (a timeout, a dropped connection). It carries the
    message's identifiers, so another backend can finish the job from them."""

    def __init__(self, reason: str, message_ids):
        super().__init__(reason)
        self.message_ids = [m for m in message_ids if m]


class NotFound(Exception):
    """An id no longer resolves."""


@dataclass
class Filters:
    folder: str = 'all'
    from_: str = ''
    to: str = ''
    subject: str = ''
    header: str = ''          # "Name: text"
    text: str = ''
    since: dt.date | None = None
    until: dt.date | None = None   # inclusive
    has_attachment: bool = False

    def bounds(self) -> tuple[float | None, float | None]:
        """Epoch bounds [lo, hi) in the local time zone."""
        lo = hi = None
        if self.since:
            lo = dt.datetime.combine(self.since, dt.time.min).timestamp()
        if self.until:
            hi = dt.datetime.combine(self.until + dt.timedelta(days=1), dt.time.min).timestamp()
        return lo, hi

    def header_pair(self) -> tuple[str, str] | None:
        if not self.header:
            return None
        name, _, text = self.header.partition(':')
        return name.strip().lower(), text.strip().casefold()


@dataclass
class Item:
    id: str
    ts: float | None
    direction: str            # '>' sent by the account, '<' received
    party: str
    subject: str
    attachment: bool
    folder: str = ''
    message_id: str = ''      # the normalised Message-ID (lowercase, no angle brackets); '' when the message has none

    def as_json(self) -> dict:
        return {'id': self.id, 'date': iso(self.ts), 'direction': self.direction, 'party': self.party,
                'subject': self.subject, 'attachment': self.attachment, 'folder': self.folder,
                'message_id': self.message_id or None}


@dataclass
class SearchResult:
    items: list[Item]
    total: int
    notes: list[str] = field(default_factory=list)
    fresh: str = 'live'


# ---------------------------------------------------------------- folder names (IMAP modified UTF-7)

def mutf7_decode(name: str) -> str:
    """`Rese&APE-as` -> `Reseñas`. A malformed run is left as it is."""
    def repl(match):
        chunk = match.group(1)
        if chunk == '':
            return '&'
        data = chunk.replace(',', '/')
        data += '=' * (-len(data) % 4)
        try:
            return base64.b64decode(data).decode('utf-16-be')
        except Exception:  # noqa: BLE001
            return match.group(0)
    return re.sub(r'&([^-]*)-', repl, name)


def mutf7_encode(name: str) -> str:
    out, pending = [], ''

    def flush():
        nonlocal pending
        if pending:
            data = base64.b64encode(pending.encode('utf-16-be')).decode('ascii').rstrip('=').replace('/', ',')
            out.append(f'&{data}-')
            pending = ''
    for char in name:
        if 0x20 <= ord(char) <= 0x7e:
            flush()
            out.append('&-' if char == '&' else char)
        else:
            pending += char
    flush()
    return ''.join(out)


# ---------------------------------------------------------------- headers, addresses, dates

def decode_words(value) -> str:
    """RFC 2047 words decoded; an unknown charset or broken encoding never raises, and the result can always be encoded
    as UTF-8 (a charset can name a codec that raises, or that yields lone surrogates)."""
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    value = str(value or '')
    if '=?' not in value:
        return value.strip()
    try:
        parts = email.header.decode_header(value)
    except Exception:  # noqa: BLE001 - malformed encoded words must not stop a listing
        return value.strip()
    out = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(charset or 'utf-8', 'replace'))
            except Exception:  # noqa: BLE001 - not only LookupError: some codecs reject 'replace' or the bytes
                out.append(chunk.decode('utf-8', 'replace'))
        else:
            out.append(chunk)
    return ''.join(out).encode('utf-8', 'replace').decode('utf-8').strip()


def parse_addresses(raw) -> list[tuple[str, str]]:
    """[(display name, address)] of an address header; names decoded, addresses kept as written."""
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    if not raw:
        return []
    try:
        pairs = email.utils.getaddresses([str(raw)])
    except Exception:  # noqa: BLE001
        return []
    return [(decode_words(name), addr.strip()) for name, addr in pairs if name or addr]


def format_address(name: str, addr: str) -> str:
    return f'{name} <{addr}>' if name and addr else (addr or name)


def short_party(name: str, addr: str) -> str:
    return name or addr


def parse_date(raw) -> float | None:
    """Epoch seconds (UTC) of a Date header, or None. A naive value counts as UTC; garbage is None."""
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    if not raw or not str(raw).strip():
        return None
    try:
        moment = email.utils.parsedate_to_datetime(str(raw).strip())
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=dt.timezone.utc)
        ts = moment.timestamp()
    except (TypeError, ValueError, IndexError, OverflowError, OSError):
        return None
    return ts if 0 < ts < 4_102_444_800 else None   # 1970 .. 2100


def date_from_received(raw) -> float | None:
    """The date after the last `;` of a Received header."""
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    return parse_date(str(raw or '').rsplit(';', 1)[-1])


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    try:
        return dt.datetime.fromtimestamp(ts).astimezone().isoformat(timespec='minutes')
    except (OverflowError, OSError, ValueError):
        return None


def format_when(ts: float | None) -> str:
    """Local date and time for a listing line."""
    if ts is None:
        return '----------- --:--'
    try:
        return dt.datetime.fromtimestamp(ts).astimezone().strftime('%Y-%m-%d %H:%M')
    except (OverflowError, OSError, ValueError):
        return '----------- --:--'


def format_age(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    days, rest = divmod(seconds, 86400)
    hours = rest // 3600
    if days:
        return f'{days}d {hours}h'
    minutes = rest % 3600 // 60
    return f'{hours}h {minutes}m' if hours else f'{minutes}m'


def split_headers(block: bytes) -> list[tuple[str, bytes, int]]:
    """[(lowercase name, unfolded value, offset of the value in BLOCK)] of a header block, in order."""
    out: list[list] = []
    pos = 0
    for line in block.splitlines(keepends=True):
        stripped = line.rstrip(b'\r\n')
        if stripped[:1] in (b' ', b'\t') and out:
            out[-1][1] += b' ' + stripped.strip()
        else:
            name, sep, rest = stripped.partition(b':')
            if sep and name and not name.strip() != name and b' ' not in name:
                lead = len(rest) - len(rest.lstrip(b' \t'))
                out.append([name.decode('ascii', 'replace').lower(), rest.strip(), pos + len(name) + 1 + lead])
        pos += len(line)
    return [(n, v, o) for n, v, o in out]


def summarize(headers: list[tuple[str, bytes, int]]) -> dict:
    """The listing fields of one message from its parsed header list (see split_headers). Shared by the index and
    the IMAP backend so both give the same answers for the same message."""
    fields: dict[str, bytes] = {}
    status = None
    for name, value, offset in headers:
        if name in ('to', 'cc', 'bcc'):
            fields[name] = fields[name] + b', ' + value if name in fields else value
        elif name == 'x-mozilla-status' and status is None:
            try:
                status = (int(value.strip() or b'0', 16), offset, len(value.strip()))
            except ValueError:
                status = None
        elif name not in fields:
            fields[name] = value
    text = {name: value.decode('utf-8', 'replace') for name, value in fields.items()}
    sender = parse_addresses(text.get('from', ''))
    rcpts = [pair for header in ('to', 'cc', 'bcc') for pair in parse_addresses(text.get(header, ''))]
    to_pairs = parse_addresses(text.get('to', '')) or parse_addresses(text.get('cc', '')) or rcpts
    ids = message_ids(text.get('message-id', ''))
    return {
        'from_text': ', '.join(format_address(n, a) for n, a in sender),
        'from_addr': sender[0][1].lower() if sender else '',
        'from_party': short_party(*sender[0]) if sender else '',
        'rcpt': ', '.join(format_address(n, a) for n, a in rcpts),
        'to_first': short_party(*to_pairs[0]) if to_pairs else '',
        'subject': decode_words(text.get('subject', '')),
        'date': parse_date(text.get('date')) or date_from_received(text.get('received')),
        'date_raw': text.get('date', ''), 'from_raw': text.get('from', ''),
        'mid': ids[0] if ids else '',
        'refs': sorted(set(message_ids(text.get('in-reply-to', '')) + message_ids(text.get('references', '')))),
        'att': looks_like_attachment(text.get('content-type', ''), text.get('x-ms-has-attach', '')),
        'status': status,
    }


def message_ids(value) -> list[str]:
    """Normalised (lowercase, without brackets) message identifiers found in a header value."""
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    found = re.findall(r'<([^<>\s]+)>', str(value or ''))
    return [item.lower() for item in found]


def looks_like_attachment(content_type: str, has_attach_header: str = '') -> bool:
    """Header-only guess used by the index: a mixed multipart or a non-text top-level type."""
    ctype = (content_type or '').strip().lower()
    if has_attach_header.strip().lower() == 'yes':
        return True
    if ctype.startswith('multipart/mixed') or ctype.startswith('multipart/report'):
        return True
    return bool(ctype) and not ctype.startswith(('text/', 'multipart/'))


# ---------------------------------------------------------------- bodies

class _TextExtractor(html.parser.HTMLParser):
    BLOCKS = {'p', 'div', 'br', 'tr', 'li', 'ul', 'ol', 'table', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'hr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head', 'title'):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head', 'title'):
            self.skip = max(self.skip - 1, 0)
        elif tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001
        return re.sub(r'<[^>]+>', ' ', markup)
    text = ''.join(parser.parts).replace('\xa0', ' ')
    lines = [' '.join(line.split()) for line in text.splitlines()]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def parse_message(raw: bytes):
    return email.message_from_bytes(raw, policy=email.policy.default)


def _part_text(part) -> str:
    try:
        return part.get_content()
    except Exception:  # noqa: BLE001 - unknown charset, bad encoding...
        try:
            payload = part.get_payload(decode=True) or b''
            return payload.decode(part.get_content_charset() or 'utf-8', 'replace')
        except Exception:  # noqa: BLE001
            return ''


def body_text(msg) -> str:
    """The readable body: the plain part, else the HTML part reduced to text."""
    try:
        part = msg.get_body(preferencelist=('plain', 'html'))
    except Exception:  # noqa: BLE001
        part = None
    if part is None:
        return ''
    text = _part_text(part)
    if part.get_content_subtype() == 'html':
        text = html_to_text(text)
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()


_CUT_LINES = [
    re.compile(r'^On .{3,300}wrote:\s*$', re.I | re.S),
    re.compile(r'^El .{3,300}escribi[oó]:\s*$', re.I | re.S),
    re.compile(r'^Le .{3,300}a [ée]crit\s*:\s*$', re.I | re.S),
    re.compile(r'^Am .{3,300}schrieb.{0,200}:\s*$', re.I | re.S),
    re.compile(r'^-{2,}\s*(Original Message|Mensaje original|Forwarded message|Message d.origine)', re.I),
]
_OUTLOOK_FROM = re.compile(r'^(From|De|Von):\s.+')
_OUTLOOK_NEXT = re.compile(r'^(Sent|Enviado|Date|Fecha|Gesendet):\s', re.I)


def strip_quotes(text: str) -> str:
    """Drop quoted previous messages: everything from a reply marker on, and every `>` line."""
    lines = text.split('\n')
    kept: list[str] = []
    for index, line in enumerate(lines):
        pair = line.strip() + ' ' + (lines[index + 1].strip() if index + 1 < len(lines) else '')
        if any(rx.match(line.strip()) or rx.match(pair.strip()) for rx in _CUT_LINES):
            break
        if _OUTLOOK_FROM.match(line.strip()) and any(_OUTLOOK_NEXT.match(n.strip()) for n in lines[index + 1:index + 4]):
            break
        if line.lstrip().startswith('>'):
            continue
        kept.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(kept)).strip()


# ---------------------------------------------------------------- attachments

def safe_filename(name: str | None, fallback: str = 'attachment') -> str:
    """A base name that cannot leave the target directory or hide as a dotfile."""
    base = os.path.basename(str(name or '').replace('\\', '/').replace('\x00', ''))
    base = re.sub(r'[^\w.\- ()+@]', '_', base, flags=re.UNICODE).strip().lstrip('.').strip()
    if len(base) > 120:
        stem, dot, ext = base.rpartition('.')
        base = (stem[:100] + dot + ext[:15]) if dot and len(ext) <= 15 else base[:120]
    return base or fallback


def attachment_parts(msg) -> list:
    parts = []
    try:
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = (part.get_content_disposition() or '').lower()
            filename = part.get_filename()
            ctype = part.get_content_type()
            if disposition == 'attachment' or filename or (ctype not in ('text/plain', 'text/html')
                                                          and not ctype.startswith('multipart/')):
                if ctype == 'message/delivery-status':
                    continue
                parts.append(part)
    except Exception:  # noqa: BLE001
        pass
    return parts


def _payload(part) -> bytes:
    try:
        payload = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001
        payload = None
    if payload is None:
        try:
            content = part.get_content()
            payload = content if isinstance(content, bytes) else str(content).encode('utf-8', 'replace')
        except Exception:  # noqa: BLE001
            payload = b''
    return payload


def list_attachments(msg) -> list[dict]:
    out = []
    for number, part in enumerate(attachment_parts(msg), 1):
        try:
            name = decode_words(part.get_filename() or '') or f'part-{number}'
        except Exception:  # noqa: BLE001
            name = f'part-{number}'
        out.append({'name': name, 'type': part.get_content_type(), 'size': len(_payload(part))})
    return out


def save_attachments(msg, out_dir) -> list[Path]:
    """Write every attachment into OUT_DIR under its sanitised base name; an existing name gets a number."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for number, part in enumerate(attachment_parts(msg), 1):
        try:
            raw_name = decode_words(part.get_filename() or '')
        except Exception:  # noqa: BLE001
            raw_name = ''
        name = safe_filename(raw_name, f'attachment-{number}')
        stem, dot, ext = name.rpartition('.')
        if not dot:
            stem, ext = name, ''
        data = _payload(part)
        candidate, counter = name, 0
        while True:
            path = target / candidate
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                counter += 1
                candidate = f'{stem}-{counter}.{ext}' if ext else f'{stem}-{counter}'
                continue
            except OSError as exc:
                if exc.errno == errno.ENAMETOOLONG:
                    candidate = f'attachment-{number}'
                    continue
                raise
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
            written.append(path)
            break
    return written


# ---------------------------------------------------------------- listing lines and `show` text

def party_and_direction(from_addr: str, from_display: str, to_first: str, own: set[str]) -> tuple[str, str]:
    """('>' or '<', the other party) for an account whose addresses are OWN (lowercase)."""
    if from_addr.lower() in own:
        return '>', to_first or '(no recipient)'
    return '<', from_display or from_addr or '(unknown sender)'


def format_item_line(item: Item) -> str:
    mark = '@' if item.attachment else ' '
    return f'{item.id} {format_when(item.ts)} {item.direction}{mark} {item.party[:48]} | {item.subject or "(no subject)"}'


def message_headers(msg) -> dict[str, str]:
    out = {}
    for name in ('From', 'To', 'Cc', 'Date', 'Subject', 'Message-ID'):
        try:
            value = msg[name]
            out[name] = decode_words(str(value)) if value is not None else ''
        except Exception:  # noqa: BLE001
            out[name] = ''
    return out


def render_message(raw: bytes, body_chars: int, no_quote: bool = False, all_headers: bool = False) -> dict:
    """The data of `show`: headers, bounded body, attachments."""
    msg = parse_message(raw)
    headers = message_headers(msg)
    ts = parse_date(headers.get('Date'))
    body = body_text(msg)
    if no_quote:
        body = strip_quotes(body)
    total = len(body)
    shown = body[:max(body_chars, 0)]
    document = {'headers': headers, 'when': iso(ts), 'body': shown, 'body_chars': total,
                'left_out': total - len(shown), 'attachments': list_attachments(msg)}
    if all_headers:
        document['all_headers'] = [(str(k), decode_words(str(v))) for k, v in msg.items()]
    return document
