"""Synthetic fixtures for `mailbox self-test` and for the tests: a fake mail-client profile with mbox folders in
both observed formats. Only reserved names are used (example.com, example.org). Nothing here reads the real home,
the real mail store or the network.

Format A (older client): separator line + LF, then `X-Mozilla-Status` and `X-Mozilla-Status2` lines (LF), then the
message with CRLF lines. Format B (newer client): separator line + CRLF, CRLF everywhere, no status lines at all.
"""
from __future__ import annotations

import email.policy
from email.message import EmailMessage
from pathlib import Path

ADDRESS = 'user@example.com'
OTHER = 'other@example.org'
THIRD = 'third@example.net'
HOST = 'mail.example.com'
SEPARATOR_DATE = 'Sat Nov 07 21:46:36 2026'   # the download time: shared by many messages, never the sent date


def message(subject: str, sender: str, to: str, date: str | None, message_id: str | None, body: str = 'Hello.',
            html: str | None = None, attachments: list[tuple[str, bytes]] | None = None, in_reply_to: str | None = None,
            references: str | None = None, cc: str | None = None, extra: list[tuple[str, str]] | None = None,
            html_only: bool = False) -> bytes:
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = to
    if cc:
        msg['Cc'] = cc
    if subject is not None:
        msg['Subject'] = subject
    if date:
        msg['Date'] = date
    if message_id:
        msg['Message-ID'] = f'<{message_id}>'
    if in_reply_to:
        msg['In-Reply-To'] = f'<{in_reply_to}>'
    if references:
        msg['References'] = ' '.join(f'<{r}>' for r in references.split())
    for name, value in extra or []:
        msg[name] = value
    if html_only:
        msg.set_content(html or '<p>Hello.</p>', subtype='html')
    else:
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype='html')
    for filename, data in attachments or []:
        msg.add_attachment(data, maintype='application', subtype='octet-stream', filename=filename)
    return msg.as_bytes(policy=email.policy.SMTP)


def mbox_format_a(entries: list[tuple[bytes, int]], separator_date: str = 'Fri May  5 13:43:41 2023') -> bytes:
    """ENTRIES: (message bytes with CRLF lines, client status flags)."""
    out = b''
    for raw, status in entries:
        out += (f'From - {separator_date}\n').encode() + f'X-Mozilla-Status: {status:04x}\n'.encode()
        out += b'X-Mozilla-Status2: 00000000\n' + raw
        if not raw.endswith(b'\r\n'):
            out += b'\r\n'
        out += b'\n'
    return out


def mbox_format_b(entries: list[bytes], separator_date: str = SEPARATOR_DATE) -> bytes:
    out = b''
    for raw in entries:
        out += f'From - {separator_date}\r\n'.encode() + raw
        if not raw.endswith(b'\r\n'):
            out += b'\r\n'
        out += b'\r\n'
    return out


def write_prefs(profile: Path, address: str = ADDRESS, host: str = HOST, directory: str | None = None,
                user: str | None = None, extra: list[str] | None = None) -> None:
    directory = directory or host
    lines = [
        '// synthetic preferences',
        'user_pref("mail.server.server1.type", "imap");',
        f'user_pref("mail.server.server1.hostname", "{host}");',
        f'user_pref("mail.server.server1.userName", "{user or address}");',
        f'user_pref("mail.server.server1.directory-rel", "[ProfD]ImapMail/{directory}");',
        f'user_pref("mail.identity.id1.useremail", "{address}");',
        'user_pref("mail.account.account1.server", "server1");',
        'user_pref("mail.account.account1.identities", "id1");',
        'user_pref("mail.server.server2.type", "none");',
        'user_pref("mail.server.server2.hostname", "Local Folders");',
        'user_pref("mail.server.server2.directory-rel", "[ProfD]Mail/Local Folders");',
        'user_pref("mail.account.account2.server", "server2");',
        *(extra or []),
    ]
    profile.mkdir(parents=True, exist_ok=True)
    (profile / 'prefs.js').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def standard_messages() -> dict[str, bytes]:
    """The synthetic correspondence, keyed by a short name."""
    return {
        'invoice': message('Invoice 2026', f'Other Person <{OTHER}>', ADDRESS, 'Sun, 01 Nov 2026 10:00:00 +0000',
                           'invoice-1@example.org', body='Please find the invoice attached.',
                           attachments=[('invoice.pdf', b'%PDF-1.4 synthetic')]),
        'html': message('Hello html', f'Other Person <{OTHER}>', ADDRESS, 'Mon, 02 Nov 2026 09:30:00 +0000',
                        'html-1@example.org', html='<html><head><style>p{}</style></head><body><p>Hi <b>there</b>'
                        '</p><p>Second paragraph</p></body></html>', html_only=True),
        'encoded': message('=?utf-8?B?Q2Fmw6kgbWVudQ==?=', f'=?utf-8?Q?Jos=C3=A9?= <{OTHER}>', f'{ADDRESS}, {THIRD}',
                           'Tue, 03 Nov 2026 12:00:00 +0100', 'cafe-1@example.org',
                           body='New menu attached below.\n\nOn Mon, 2 Nov 2026, User wrote:\n> old text\n> more old text\n'),
        'nodate': message('No date at all', OTHER, ADDRESS, None, 'nodate-1@example.org', body='No Date header here.',
                          extra=[('Received', 'from mx.example.org by mail.example.com; Wed, 04 Nov 2026 08:00:00 +0000')]),
        'broken': message('Broken date', OTHER, ADDRESS, 'not a date', 'broken-1@example.org', body='Bad date.'),
        'reply': message('Re: Invoice 2026', ADDRESS, OTHER, 'Sun, 01 Nov 2026 15:00:00 +0000', 'reply-1@example.com',
                         body='Thanks, paid.\n\nOn Sun, 1 Nov 2026, Other Person wrote:\n> Please find the invoice\n',
                         in_reply_to='invoice-1@example.org', references='invoice-1@example.org', cc=THIRD),
        'sent2': message('Lunch tomorrow', ADDRESS, THIRD, 'Thu, 05 Nov 2026 11:00:00 +0000', 'lunch-1@example.com',
                         body='Lunch at noon?'),
        'trashed': message('Deleted for good', ADDRESS, OTHER, 'Fri, 06 Nov 2026 11:00:00 +0000', 'deleted-1@example.com',
                           body='This one carries the deleted flag.'),
        'draft': message('Unfinished draft', ADDRESS, OTHER, 'Fri, 06 Nov 2026 12:00:00 +0000', 'draft-1@example.com',
                         body='To be continued.'),
    }


def list_messages() -> dict[str, bytes]:
    """Extra synthetic messages for the identifier and header-filter tests (a mailing list, a repeated header, no
    `Message-ID`, a mixed-case one, a long subject). They are not part of `standard_messages`, so no count of the
    standard fixture changes; a test writes the ones it needs into a folder."""
    return {
        'alpha1': message('Digest alpha 1', 'List <list@example.org>', ADDRESS, 'Mon, 09 Nov 2026 08:00:00 +0000',
                          'alpha-1@example.org', extra=[('List-ID', 'Alpha list <alpha.example.org>')]),
        'alpha2': message('Digest alpha 2', 'List <list@example.org>', ADDRESS, 'Tue, 10 Nov 2026 08:00:00 +0000',
                          'alpha-2@example.org', extra=[('List-ID', 'Alpha list <alpha.example.org>')]),
        'beta1': message('Digest beta 1', 'List <list@example.org>', ADDRESS, 'Wed, 11 Nov 2026 08:00:00 +0000',
                         'beta-1@example.org', extra=[('List-ID', 'Beta list <beta.example.org>')]),
        'twice': message('Two list headers', 'List <list@example.org>', ADDRESS, 'Thu, 12 Nov 2026 08:00:00 +0000',
                         'twice-1@example.org', extra=[('List-ID', '<first.example.org>'), ('List-ID', '<second.example.org>')]),
        'plain': message('Plain note', OTHER, ADDRESS, 'Fri, 13 Nov 2026 08:00:00 +0000', 'plain-1@example.org'),
        'noid': message('No identifier', OTHER, ADDRESS, 'Sat, 14 Nov 2026 08:00:00 +0000', None),
        'mixed': message('Mixed case identifier', OTHER, ADDRESS, 'Sun, 15 Nov 2026 08:00:00 +0000', 'Case.Mixed-1@example.test'),
        'long': message('L' * 300, OTHER, ADDRESS, 'Mon, 16 Nov 2026 08:00:00 +0000', 'long-1@example.org'),
    }


def build_thunderbird(root: Path, address: str = ADDRESS, host: str = HOST, *, old_defines: bool = True,
                      new_defines: bool = True, directory: str | None = None, extra_prefs: list[str] | None = None) -> dict:
    """A profile root with an old profile (empty `INBOX`, one old message) and the default one (live `INBOX-1`,
    `Sent`, `Drafts`), the way a machine looks after the client switched profile and renamed its inbox."""
    msgs = standard_messages()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'profiles.ini').write_text(
        '[Profile1]\nName=default-release\nIsRelative=1\nPath=new5678.default-release\n\n'
        '[Profile0]\nName=default\nIsRelative=1\nPath=old1234.default\nDefault=1\n\n[General]\nStartWithLastProfile=1\n',
        encoding='utf-8')
    (root / 'installs.ini').write_text('[0123456789ABCDEF]\nDefault=new5678.default-release\nLocked=1\n', encoding='utf-8')
    old, new = root / 'old1234.default', root / 'new5678.default-release'
    layout = {'old': old, 'new': new}
    for profile, defines in ((old, old_defines), (new, new_defines)):
        profile.mkdir(parents=True, exist_ok=True)
        if defines:
            write_prefs(profile, address, host, directory, extra=extra_prefs)
        else:
            (profile / 'prefs.js').write_text('// no mail account here\n', encoding='utf-8')
    base = directory or host
    old_dir = old / 'ImapMail' / base
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / 'INBOX').write_bytes(b'')
    (old_dir / 'INBOX.msf').write_bytes(b'client index, ignored')
    new_dir = new / 'ImapMail' / base
    new_dir.mkdir(parents=True, exist_ok=True)
    inbox = mbox_format_b([msgs['invoice'], msgs['html'], msgs['encoded'], msgs['nodate'], msgs['broken'],
                           msgs['invoice']])
    (new_dir / 'INBOX-1').write_bytes(inbox)
    (new_dir / 'INBOX-1.msf').write_bytes(b'client index, ignored')
    sent = mbox_format_a([(msgs['reply'], 0x0001), (msgs['sent2'], 0x0001), (msgs['trashed'], 0x0009)])
    (new_dir / 'Sent').write_bytes(sent)
    (new_dir / 'Drafts').write_bytes(mbox_format_b([msgs['draft']]))
    layout.update(root=root, account_dir=new_dir, old_dir=old_dir, inbox=new_dir / 'INBOX-1', sent=new_dir / 'Sent',
                  drafts=new_dir / 'Drafts', old_inbox=old_dir / 'INBOX')
    return layout


def account_config(root: Path, **extra) -> dict:
    """The `mailbox` config piece for the synthetic profile, with only the `local` backend."""
    account = {'address': ADDRESS, 'aliases': [], 'backends': ['local'],
               'local': {'profile_roots': [str(root)], 'folders': {'inbox': '', 'sent': '', 'drafts': ''}}}
    account.update(extra)
    return {'accounts': {'work': account}}


# ---------------------------------------------------------------- `mailbox self-test`

def run(main) -> int:
    """Exercise MAIN (the entry script's main function) in-process on a synthetic profile in a temporary directory.
    HOME, the configuration directory and the cache directory are redirected there for the duration; the real ones are
    never read, and nothing touches the network. One line per check, then `self-test: ok` or a failure count."""
    import contextlib
    import hashlib
    import io
    import json
    import os
    import re
    import shutil
    import tempfile
    import time

    tmp = Path(tempfile.mkdtemp(prefix='mailbox-selftest-'))
    saved = dict(os.environ)
    failures = []

    def invoke(*args):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(list(args))
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
            except Exception as exc:  # noqa: BLE001 - a crash is a failed check, not a crashed self-test
                code = 1
                err.write(f'crashed: {type(exc).__name__}')
        return code, out.getvalue(), err.getvalue()

    def check(name, condition, detail=''):
        print(f'{"ok  " if condition else "FAIL"} {name}' + (f' ({detail})' if detail and not condition else ''))
        if not condition:
            failures.append(name)

    def snapshot(layout):
        return [(p.name, hashlib.sha1(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in sorted(layout['account_dir'].iterdir()) if p.is_file()]

    try:
        os.environ.update(HOME=str(tmp / 'home'), CLAUDE_TOOLKIT_CONFIG_DIR=str(tmp / 'config'),
                          XDG_CACHE_HOME=str(tmp / 'cache'), TZ='UTC')
        time.tzset()
        (tmp / 'home').mkdir()
        (tmp / 'config').mkdir()
        layout = build_thunderbird(tmp / 'profiles')
        listed = list_messages()                       # a folder of no role: only a search that names it reads it
        (layout['account_dir'] / 'Lists').write_bytes(mbox_format_b([listed['alpha1'], listed['plain']]))
        document = account_config(tmp / 'profiles')
        document['accounts']['remote'] = {'address': ADDRESS, 'backends': ['imap'],
                                          'imap': {'host': HOST, 'credentials_file': str(tmp / 'absent.env')}}
        document['accounts']['hosted'] = {'address': ADDRESS, 'connector': {}}
        document['accounts']['hosted-small'] = {'address': ADDRESS, 'connector': {'search_view': 'THREAD_VIEW_IDS_ONLY',
                                                                                 'read_format': 'FULL_CONTENT',
                                                                                 'page_size_max': 10}}
        document['accounts']['hosted-bad'] = {'address': ADDRESS, 'connector': {'read_format': 'plain_text'}}
        (tmp / 'config' / 'mailbox.json').write_text(json.dumps(document), encoding='utf-8')
        before = snapshot(layout)

        code, out, _ = invoke('accounts')
        check('accounts lists the configured accounts', code == 0 and 'work' in out and 'connector' in out, out)
        code, out, _ = invoke('where', 'work', 'inbox')
        check('resolution finds the inbox of the default profile', code == 0 and out.strip().endswith('INBOX-1')
              and out.strip().startswith(str(tmp)), out)
        code, out, _ = invoke('search', 'work', '--json')
        found = json.loads(out) if code == 0 else {}
        check('indexing and search read both store formats', found.get('total') == 7 and found.get('backend') == 'local',
              str(found.get('total')))
        check('a deleted message is not listed', 'Deleted for good' not in out)
        by_subject = {item.get('subject'): item.get('message_id', 'missing') for item in found.get('items', [])}
        check('every item carries its normalised Message-ID', by_subject.get('Lunch tomorrow') == 'lunch-1@example.com'
              and by_subject.get('Invoice 2026') == 'invoice-1@example.org', str(by_subject))
        check('an undated message is listed last', found.get('items', [{}])[-1].get('subject') == 'Broken date')
        check('the no-status note is given for the newer format',
              any('deleted or moved' in n for n in found.get('notes', [])))
        ids = {item['subject']: item['id'] for item in found.get('items', [])}
        header = ('search', 'work', '--folder', 'Lists', '--header', 'List-ID: alpha', '--json')
        first, again = invoke(*header), invoke(*header)
        listing = [json.loads(out).get('items') if code == 0 else None for code, out, _ in (first, again)]
        check('a repeated header search answers the same from the header index', listing[0] == listing[1]
              and [item['subject'] for item in listing[0] or []] == ['Digest alpha 1']
              and 'building the index of Lists' in first[2] and again[2] == '', str(listing) + again[2])
        code, out, _ = invoke('search', 'work', '--from', 'other@', '--subject', 'invoice', '--folder', 'inbox')
        check('filters combine', code == 0 and out.count('\nl:') == 1, out)
        code, out, _ = invoke('search', 'work', '--text', 'paid')
        check('a body text search scans the messages', code == 0 and 'Re: Invoice 2026' in out, out)
        code, out, _ = invoke('show', 'work', ids.get('Hello html', 'none'))
        check('show reduces an HTML-only message to text', code == 0 and 'Hi there' in out and '<p>' not in out, out)
        code, out, _ = invoke('show', 'work', ids.get('Re: Invoice 2026', 'none'), '--no-quote')
        check('show --no-quote drops the quoted reply', code == 0 and 'Thanks, paid.' in out
              and 'Please find the invoice' not in out, out)
        code, out, _ = invoke('thread', 'work', ids.get('Invoice 2026', 'none'))
        check('thread joins received and sent mail', code == 0 and 'Re: Invoice 2026' in out and out.count('\nl:') == 2, out)
        saved_to = tmp / 'saved'
        code, out, _ = invoke('save', 'work', ids.get('Invoice 2026', 'none'), '--out', str(saved_to))
        check('save writes the attachment', code == 0 and (saved_to / 'invoice.pdf').is_file(), out)
        code, _, err = invoke('show', 'work', 'l:INBOX-1:000000000000')
        check('a stale id exits 4', code == 4, err)
        code, _, err = invoke('search', 'nobody')
        check('an unknown account exits 2', code == 2, err)
        code, out, _ = invoke('search', 'hosted', '--from', 'other@example.org', '--since', '2026-11-01')
        delegated = json.loads(out) if out.strip().startswith('{') else {}
        check('a connector account is delegated with exit 10', code == 10 and delegated.get('delegate') == 'connector'
              and 'from:other@example.org' in delegated.get('arguments', {}).get('query', ''), out)
        arguments = delegated.get('arguments', {})
        check('a connector search carries the bounded default view and the page size',
              arguments.get('view') == 'THREAD_VIEW_SUMMARY' and arguments.get('pageSize') == 20
              and set(arguments) == {'query', 'pageSize', 'view'}, str(arguments))
        code, out, _ = invoke('search', 'hosted', '--limit', '200')
        capped = json.loads(out) if out.strip().startswith('{') else {}
        check('a limit above the connector maximum is cut and says so outside the arguments',
              code == 10 and capped.get('arguments', {}).get('pageSize') == 50 and 'paging' not in capped.get('arguments', {})
              and capped.get('paging', {}).get('capped') is True and capped['paging'].get('continue_with') == 'pageToken'
              and 'narrow the search' in capped['paging'].get('how', '') and 'pageToken' in capped['paging']['how'],
              out)
        code, out, _ = invoke('search', 'hosted-small', '--limit', '25')
        small = json.loads(out) if out.strip().startswith('{') else {}
        check('the per-account view and page-size maximum are used',
              code == 10 and small.get('arguments', {}).get('view') == 'THREAD_VIEW_IDS_ONLY'
              and small['arguments'].get('pageSize') == 10 and small['paging'].get('requested') == 25, out)
        code, out, _ = invoke('show', 'hosted', '18f3A_c-9')
        read = json.loads(out) if out.strip().startswith('{') else {}
        check('a connector read carries the id as typed and the plain-text format',
              code == 10 and read.get('arguments') == {'threadId': '18f3A_c-9', 'messageFormat': 'PLAIN_TEXT'}, out)
        code, out, _ = invoke('thread', 'hosted', 'abc', '--full-content')
        check('the HTML body is read only when asked for', code == 10
              and json.loads(out).get('arguments', {}).get('messageFormat') == 'FULL_CONTENT', out)
        code, out, _ = invoke('thread', 'hosted-small', 'abc')
        check('the per-account read format is used', code == 10
              and json.loads(out).get('arguments', {}).get('messageFormat') == 'FULL_CONTENT', out)
        code, out, _ = invoke('whoami', 'hosted-small')
        first = json.loads(out.split('\n', 1)[0]) if out.strip().startswith('{') else {}
        check('the identity check asks for metadata only, whatever the search view is', code == 0
              and first.get('arguments') == {'query': 'in:sent', 'pageSize': 1, 'view': 'THREAD_VIEW_METADATA_ONLY'}, out)
        code, out, err = invoke('show', 'hosted-bad', 'abc')
        check('an invalid connector setting makes the account unusable', code == 2 and out == ''
              and 'connector.read_format' in err, err)
        code, out, _ = invoke('search', 'hosted', '--header', 'X-Thing: 1')
        check('a header filter is refused on a connector account', code == 2 and out == '')
        code, out, _ = invoke('show', 'work', ids.get('Hello html', 'none'), '--full-content')
        check('--full-content is refused on an account that is not a connector account', code == 2 and out == '')
        shown = ''
        for args in (('search', 'hosted'), ('show', 'hosted', 'abc'), ('whoami', 'hosted'), ('doctor', 'hosted'),
                     ('accounts',)):
            _, out, err = invoke(*args)
            shown += out + err
        check('no connector server identifier is printed',
              'mcp__' not in shown and not re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}', shown))
        code, _, _ = invoke('whoami', 'hosted', '--sender', OTHER)
        check('a connector of another mailbox exits 3', code == 3)
        code, _, _ = invoke('whoami', 'hosted', '--sender', ADDRESS.upper())
        check('the identity check is case-insensitive', code == 0)
        code, out, _ = invoke('doctor', 'remote')
        check('an imap account without credentials is unavailable and nothing connects', code == 3
              and 'imap: unavailable' in out, out)
        check('the store was only read', snapshot(layout) == before)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        time.tzset()
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print(f'self-test: {len(failures)} failure(s)')
        return 1
    print('self-test: ok')
    return 0
