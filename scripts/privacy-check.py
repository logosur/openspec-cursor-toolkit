#!/usr/bin/env python3
"""Fail when publishable content of this repository carries personal data.

Two layers of patterns:

* generic shapes (public IPv4, emails, UUIDs, home paths, dated orders, secrets),
  read from scripts/privacy-patterns.yaml and run everywhere, CI included;
* a private denylist (real names of people, clients, projects, hosts...), read from the
  local override and never committed: $CLAUDE_TOOLKIT_OVERRIDE/privacy-denylist.txt,
  else ~/.config/claude-toolkit/privacy-denylist.txt. Every guillemet quote of five
  words or more found in the override's text files is denied too, so a literal quote
  kept in a private rule cannot leak into the public version of that rule.

Scopes: the working tree (tracked + untracked, not ignored) by default; --staged for
the index; --message FILE for a commit message; --range A..B for the messages and
added lines of commits about to be pushed.

Private findings never print the denied term, only the denylist entry number, so the
output is safe to paste into a log.

Exit codes: 0 clean, 1 findings, 2 usage or setup error (e.g. --require-private with
no denylist).

Usage:
  python3 scripts/privacy-check.py [--root DIR] [--staged | --message FILE | --range A..B]
                                   [--denylist FILE] [--override DIR] [--require-private]
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

PATTERNS_FILE = 'scripts/privacy-patterns.yaml'
ALLOW_FILE = 'scripts/privacy-allow.yaml'
MAX_BYTES = 2 * 1024 * 1024
QUOTE_RE = re.compile(r'«([^«»\n]{12,400})»')
QUOTE_MIN_WORDS = 5
TEXT_SUFFIXES = {'', '.md', '.mdc', '.txt', '.yaml', '.yml', '.json', '.py', '.sh', '.html', '.toml'}


@dataclass(frozen=True)
class Finding:
    where: str
    line: int
    rule: str
    detail: str

    def render(self) -> str:
        loc = f'{self.where}:{self.line}' if self.line else self.where
        return f'ERROR {loc} [{self.rule}] {self.detail}'


@dataclass(frozen=True)
class Pattern:
    id: str
    regex: re.Pattern
    allow: tuple
    synthetic_ok: bool


def load_patterns(root: Path) -> list[Pattern]:
    data = yaml.safe_load((root / PATTERNS_FILE).read_text(encoding='utf-8')) or {}
    out = []
    for p in data.get('patterns', []):
        flags = 0 if p.get('case_sensitive') else re.IGNORECASE
        out.append(Pattern(
            id=p['id'],
            regex=re.compile(p['regex'], flags),
            allow=tuple(re.compile(a, re.IGNORECASE) for a in p.get('allow', [])),
            synthetic_ok=bool(p.get('synthetic_ok')),
        ))
    return out


def load_allowlist(root: Path) -> list[dict]:
    path = root / ALLOW_FILE
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    entries = data.get('allow', []) or []
    for e in entries:
        if not e.get('reason'):
            raise SystemExit(f'privacy-check: {ALLOW_FILE}: entry {e!r} has no reason')
    return entries


def override_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get('CLAUDE_TOOLKIT_OVERRIDE')
    if env:
        return Path(env).expanduser()
    return Path('~/.config/claude-toolkit').expanduser()


def is_text(data: bytes) -> bool:
    return b'\0' not in data[:8192]


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip().lower()


def load_private(denylist: Path | None, override: Path) -> tuple[list[tuple[int, re.Pattern]], list[str]]:
    """Return (numbered denylist regexes, normalized private quotes)."""
    terms: list[tuple[int, re.Pattern]] = []
    if denylist and denylist.is_file():
        for n, raw in enumerate(denylist.read_text(encoding='utf-8').splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('re:'):
                terms.append((n, re.compile(line[3:], re.IGNORECASE)))
            else:
                terms.append((n, re.compile(r'(?<![A-Za-z0-9])' + re.escape(line) + r'(?![A-Za-z0-9])', re.IGNORECASE)))
    quotes: set[str] = set()
    files_dir = override / 'files'
    if files_dir.is_dir():
        for path in files_dir.rglob('*'):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if len(data) > MAX_BYTES or not is_text(data):
                continue
            for m in QUOTE_RE.finditer(data.decode('utf-8', 'replace')):
                q = normalize(m.group(1))
                if len(q.split()) >= QUOTE_MIN_WORDS:
                    quotes.add(q)
    return terms, sorted(quotes)


def allowed(entries: list[dict], where: str, rule: str, text: str) -> bool:
    for e in entries:
        if not fnmatch.fnmatch(where, e.get('path', '*')):
            continue
        if e.get('pattern', '*') not in ('*', rule):
            continue
        if e.get('match') and not re.search(e['match'], text, re.IGNORECASE):
            continue
        return True
    return False


def synthetic_uuid(value: str) -> bool:
    return len(set(value.replace('-', '').lower())) <= 4


class Checker:
    def __init__(self, patterns, allow_entries, terms, quotes):
        self.patterns = patterns
        self.allow_entries = allow_entries
        self.terms = terms
        self.quotes = quotes
        self.findings: list[Finding] = []

    def check_text(self, where: str, text: str, line_offsets: list[int] | None = None) -> None:
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            lineno = line_offsets[i - 1] if line_offsets else i
            for p in self.patterns:
                for m in p.regex.finditer(line):
                    value = m.group(0)
                    if any(a.search(value) for a in p.allow):
                        continue
                    if p.synthetic_ok and synthetic_uuid(value):
                        continue
                    if allowed(self.allow_entries, where, p.id, value):
                        continue
                    self.findings.append(Finding(where, lineno, p.id, f'matches {value!r}'))
            for n, term in self.terms:
                if term.search(line) and not allowed(self.allow_entries, where, 'private', line):
                    self.findings.append(Finding(where, lineno, 'private', f'matches private denylist entry #{n}'))
        if self.quotes:
            flat = normalize(text)
            for q in self.quotes:
                if q in flat:
                    self.findings.append(Finding(where, 0, 'private-quote',
                                                 f'contains a quote kept in the private override ({len(q.split())} words)'))


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout


def scan_tree(root: Path, checker: Checker, staged: bool) -> None:
    if staged:
        names = git(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z').split('\0')
    else:
        names = git(root, 'ls-files', '-co', '--exclude-standard', '-z').split('\0')
    for name in filter(None, names):
        if staged:
            try:
                data = subprocess.run(['git', '-C', str(root), 'show', f':{name}'], check=True,
                                      capture_output=True).stdout
            except subprocess.CalledProcessError:
                continue
        else:
            path = root / name
            if not path.is_file() or path.is_symlink():
                continue
            data = path.read_bytes()
        if len(data) > MAX_BYTES or not is_text(data):
            continue
        checker.check_text(name, data.decode('utf-8', 'replace'))


def scan_range(root: Path, checker: Checker, rev_range: str) -> None:
    for sha in filter(None, git(root, 'rev-list', rev_range).split()):
        checker.check_text(f'commit {sha[:12]} message', git(root, 'log', '-1', '--format=%an%n%ae%n%B', sha))
        diff = git(root, 'show', '--format=', '--unified=0', '--no-color', sha)
        for path, added, offsets in added_lines(diff):
            checker.check_text(f'commit {sha[:12]} {path}', '\n'.join(added), offsets)


def added_lines(diff: str):
    """Yield (path, added lines, their line numbers in the new file) per file of a diff."""
    path, added, offsets, next_line = None, [], [], 0
    for raw in diff.splitlines():
        if raw.startswith('+++ '):
            if path and added:
                yield path, added, offsets
            path = raw[6:] if raw.startswith('+++ b/') else None
            added, offsets = [], []
        elif raw.startswith('@@'):
            m = re.search(r'\+(\d+)', raw)
            next_line = int(m.group(1)) if m else 0
        elif raw.startswith('+') and path:
            added.append(raw[1:])
            offsets.append(next_line)
            next_line += 1
    if path and added:
        yield path, added, offsets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--root', default=None)
    scope = ap.add_mutually_exclusive_group()
    scope.add_argument('--staged', action='store_true')
    scope.add_argument('--message', metavar='FILE')
    scope.add_argument('--range', metavar='A..B')
    ap.add_argument('--denylist', metavar='FILE')
    ap.add_argument('--override', metavar='DIR')
    ap.add_argument('--require-private', action='store_true',
                    help='exit 2 when no private denylist is available (local use before a commit)')
    args = ap.parse_args(argv)

    root = Path(args.root or Path(__file__).resolve().parent.parent).resolve()
    override = override_dir(args.override)
    denylist = Path(args.denylist).expanduser() if args.denylist else override / 'privacy-denylist.txt'
    if args.require_private and not denylist.is_file():
        print(f'privacy-check: no private denylist at {denylist}', file=sys.stderr)
        return 2
    terms, quotes = load_private(denylist, override)
    checker = Checker(load_patterns(root), load_allowlist(root), terms, quotes)

    if args.message:
        checker.check_text('commit message', Path(args.message).read_text(encoding='utf-8'))
    elif args.range:
        scan_range(root, checker, args.range)
    else:
        scan_tree(root, checker, args.staged)

    for f in checker.findings:
        print(f.render())
    layer = f'private denylist: {len(terms)} terms, {len(quotes)} quotes' if terms or quotes else 'generic patterns only'
    print(f'privacy-check: {len(checker.findings)} finding(s) ({layer})')
    return 1 if checker.findings else 0


if __name__ == '__main__':
    sys.exit(main())
