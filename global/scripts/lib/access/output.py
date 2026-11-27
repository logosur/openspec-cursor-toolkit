"""Bounded, single-line output and exit codes shared by `mailbox` and `stores`.

Text by default, one line per item, at most 160 characters; `print_json` for scripts. Failures are one line
on stderr and a fixed exit code (design D11): 0 ok, 1 unexpected or remote error, 2 usage or unknown
account, 3 not available or not connected, 4 not found, 10 delegated to a connector.
"""
from __future__ import annotations

import json
import sys

OK, ERROR, USAGE, UNAVAILABLE, NOT_FOUND, DELEGATED = 0, 1, 2, 3, 4, 10
DEFAULT_WIDTH = 160


def _printable(text: str) -> str:
    # Message content is untrusted: control characters (terminal escape sequences) never reach the output.
    return ''.join('?' if (ord(ch) < 32 or 0x7f <= ord(ch) < 0xa0) and not ch.isspace() else ch for ch in text)


def clip(text: str, width: int = DEFAULT_WIDTH) -> str:
    """One line: whitespace collapsed, control characters replaced, cut with an ellipsis."""
    line = ' '.join(_printable(str(text)).split())
    width = max(int(width), 2)
    if len(line) <= width:
        return line
    return line[:width - 1].rstrip() + '…'


def emit(line: str = '') -> None:
    """print() that survives a terminal or pipe whose encoding cannot show the text."""
    try:
        print(line)
    except UnicodeEncodeError:
        data = (line + '\n').encode('utf-8', 'replace')
        buffer = getattr(sys.stdout, 'buffer', None)
        if buffer is not None:
            sys.stdout.flush()
            buffer.write(data)
            buffer.flush()
        else:
            sys.stdout.write(data.decode('ascii', 'replace'))


def print_items(lines: list[str], total: int, limit: int, header: str = '') -> None:
    """The header, then at most LIMIT clipped lines, then "N of TOTAL shown" when the list was cut."""
    if header:
        for part in header.split('\n'):
            emit(clip(part))
    shown = lines[:max(int(limit), 0)]
    for line in shown:
        emit(clip(line))
    if total > len(shown):
        emit(f'{len(shown)} of {total} shown')


def print_json(document: dict) -> None:
    """One compact JSON document, keys sorted, UTF-8 kept."""
    emit(json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str))


def fail(piece: str, code: int, message: str):
    """"piece: message" on stderr (one line) and exit with CODE."""
    sys.stdout.flush()
    sys.stderr.write(f'{piece}: {clip(message, 400)}\n')
    sys.stderr.flush()
    sys.exit(code)
