"""Tests of global/scripts/mailbox and its modules in global/scripts/lib/access (mail_*.py).

Every fixture is synthetic and lives in a temporary directory: a fake mail-client profile with mbox folders in both
observed formats, a recording fake IMAP class, an HOME, config directory and cache directory of its own. Nothing
reads the developer's real mail, credentials or network.
"""
import contextlib
import datetime
import hashlib
import imaplib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

LIB = str(REPO_ROOT / 'global/scripts/lib')
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from access import mail_imap, mail_index, mail_local, mail_message, mail_selftest as fx  # noqa: E402
from access.mail_message import Unavailable  # noqa: E402

SCRIPT = str(REPO_ROOT / 'global/scripts/mailbox')
dt_date = datetime.date


class Base(unittest.TestCase):
    """A temporary home with its own config, cache and profile root."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='mailbox-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = Path(self.tmp, 'home')
        self.cfg = Path(self.tmp, 'cfg')
        self.cache = Path(self.tmp, 'cache')
        self.root = Path(self.tmp, 'profiles')
        for path in (self.home, self.cfg):
            path.mkdir()
        self.env = {'HOME': str(self.home), 'CLAUDE_TOOLKIT_CONFIG_DIR': str(self.cfg), 'XDG_CACHE_HOME': str(self.cache),
                    'TZ': 'UTC', 'LC_ALL': 'C.UTF-8'}
        self.addCleanup(time.tzset)      # registered first, so it runs after the environment is restored
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)
        time.tzset()

    def account(self, **extra):
        return fx.account_config(self.root, **extra)['accounts']['work']


class Resolver(Base):
    """Task 2.1."""

    def test_only_the_default_profile_defines_the_account(self):
        lay = fx.build_thunderbird(self.root, old_defines=False)
        store = mail_local.resolve(self.account())
        self.assertEqual(store.profile, lay['new'])
        self.assertEqual(store.account_dir, lay['account_dir'])

    def test_the_installation_default_wins_over_a_newer_old_profile(self):
        lay = fx.build_thunderbird(self.root)
        os.utime(lay['old'] / 'prefs.js', (time.time() + 1000, time.time() + 1000))
        self.assertEqual(mail_local.resolve(self.account()).profile, lay['new'])

    def test_without_a_default_the_profile_whose_preferences_changed_last_wins(self):
        lay = fx.build_thunderbird(self.root)
        (self.root / 'installs.ini').unlink()
        (self.root / 'profiles.ini').write_text('[Profile0]\nName=a\nIsRelative=1\nPath=old1234.default\n\n'
                                                '[Profile1]\nName=b\nIsRelative=1\nPath=new5678.default-release\n')
        os.utime(lay['old'] / 'prefs.js', (time.time() + 1000, time.time() + 1000))
        self.assertEqual(mail_local.resolve(self.account()).profile, lay['old'])

    def test_a_mail_directory_named_differently_from_the_host_is_followed(self):
        lay = fx.build_thunderbird(self.root, directory='imap.example.org-1')
        store = mail_local.resolve(self.account())
        self.assertEqual(store.account_dir.name, 'imap.example.org-1')
        self.assertEqual(store.roles['inbox'], ['INBOX-1'])
        self.assertTrue(lay['inbox'].samefile(store.folders['INBOX-1']))

    def test_the_account_can_be_matched_by_an_alias(self):
        fx.build_thunderbird(self.root, address='alias@example.com')
        self.assertIn('INBOX-1', mail_local.resolve(self.account(aliases=['Alias@Example.com'])).folders)

    def test_renamed_inbox_next_to_an_empty_old_one(self):
        lay = fx.build_thunderbird(self.root)
        (lay['account_dir'] / 'INBOX').write_bytes(b'')
        os.utime(lay['account_dir'] / 'INBOX', (time.time() + 500, time.time() + 500))   # even newer, but empty
        store = mail_local.resolve(self.account())
        self.assertEqual(store.roles['inbox'], ['INBOX-1'])
        self.assertEqual(set(store.roles), {'inbox', 'sent', 'drafts'})

    def test_two_non_empty_folders_of_one_role_are_both_kept_newest_first(self):
        lay = fx.build_thunderbird(self.root)
        old = lay['account_dir'] / 'INBOX'
        old.write_bytes(lay['inbox'].read_bytes())
        os.utime(old, (1, 1))
        self.assertEqual(mail_local.resolve(self.account()).roles['inbox'], ['INBOX-1', 'INBOX'])

    def test_localised_names_and_subfolders_resolve_to_roles(self):
        lay = fx.build_thunderbird(self.root)
        account_dir = lay['account_dir']
        (account_dir / 'Sent').unlink()
        (account_dir / 'INBOX.sbd').mkdir()
        (account_dir / 'INBOX.sbd' / 'Elementos enviados').write_bytes(lay['inbox'].read_bytes())
        (account_dir / 'Borradores').write_bytes(lay['inbox'].read_bytes())
        (account_dir / 'Drafts').unlink()
        store = mail_local.resolve(self.account())
        self.assertEqual(store.roles['sent'], ['INBOX/Elementos enviados'])
        self.assertEqual(store.roles['drafts'], ['Borradores'])
        self.assertNotIn('INBOX-1.msf', store.folders)

    def test_a_pinned_role_overrides_the_derivation(self):
        fx.build_thunderbird(self.root)
        account = self.account()
        account['local']['folders']['inbox'] = 'Drafts'
        self.assertEqual(mail_local.resolve(account).roles['inbox'], ['Drafts'])
        account['local']['folders']['inbox'] = ['Drafts', 'Sent']
        self.assertEqual(mail_local.resolve(account).roles['inbox'], ['Drafts', 'Sent'])
        account['local']['folders']['inbox'] = 'No such folder'
        self.assertEqual(mail_local.resolve(account).roles['inbox'], ['INBOX-1'])

    def test_account_absent_from_every_profile(self):
        fx.build_thunderbird(self.root, address='someone@example.org')
        with self.assertRaises(Unavailable) as ctx:
            mail_local.resolve(self.account())
        self.assertIn('no profile defines this account', str(ctx.exception))

    def test_no_client_installed(self):
        with self.assertRaises(Unavailable) as ctx:
            mail_local.resolve(self.account())
        self.assertIn('no mail client profile directory', str(ctx.exception))

    def test_the_identity_sent_and_drafts_folder_names_are_known_names(self):
        extra = ['user_pref("mail.identity.id1.fcc_folder", "imap://user%40example.com@mail.example.com/Mis%20enviados");',
                 'user_pref("mail.identity.id1.draft_folder", "imap://user%40example.com@mail.example.com/Entw&APw-rfe-neu");']
        lay = fx.build_thunderbird(self.root, extra_prefs=extra)
        account_dir = lay['account_dir']
        (account_dir / 'Mis enviados-1').write_bytes(lay['sent'].read_bytes())
        (account_dir / 'Entw&APw-rfe-neu').write_bytes(lay['sent'].read_bytes())
        store = mail_local.resolve(self.account())
        self.assertIn('Mis enviados-1', store.roles['sent'])
        self.assertIn('Sent', store.roles['sent'])
        self.assertIn('Entwürfe-neu', store.roles['drafts'])

    def test_every_non_empty_folder_of_a_role_counts_and_an_empty_one_is_ignored(self):
        lay = fx.build_thunderbird(self.root)
        account_dir = lay['account_dir']
        (account_dir / 'Sent-1').write_bytes(lay['sent'].read_bytes())
        (account_dir / 'Enviados').write_bytes(b'')
        os.utime(account_dir / 'Sent-1', (time.time() + 100, time.time() + 100))
        roles = mail_local.resolve(self.account()).roles
        self.assertEqual(roles['sent'], ['Sent-1', 'Sent'])

    def test_folder_names_are_decoded_and_both_forms_are_accepted(self):
        lay = fx.build_thunderbird(self.root)
        (lay['account_dir'] / 'Rese&APE-as').write_bytes(lay['sent'].read_bytes())
        store = mail_local.resolve(self.account())
        self.assertIn('Reseñas', store.folders)
        self.assertEqual(store.find('Rese&APE-as'), 'Reseñas')
        self.assertEqual(store.find('RESEÑAS'), 'Reseñas')
        self.assertIsNone(store.find('nothing'))
        self.assertEqual(mail_message.mutf7_decode('Entw&APw-rfe &- co'), 'Entwürfe & co')
        self.assertEqual(mail_message.mutf7_encode('Reseñas & €'), 'Rese&APE-as &- &IKw-')
        self.assertEqual(mail_message.mutf7_decode(mail_message.mutf7_encode('日本語/Ünï')), '日本語/Ünï')

    def test_roots_are_tried_in_order(self):
        second = Path(self.tmp, 'second-root')
        fx.build_thunderbird(second)
        account = self.account()
        account['local']['profile_roots'] = [str(self.root), str(second)]
        self.root.mkdir()
        self.assertTrue(mail_local.resolve(account).account_dir.is_relative_to(second))

    def test_default_roots_come_from_the_home_directory(self):
        fx.build_thunderbird(self.home / '.thunderbird')
        account = self.account()
        del account['local']['profile_roots']
        self.assertTrue(mail_local.resolve(account).account_dir.is_relative_to(self.home))

    def test_the_folder_listing_reports_role_size_and_change_time(self):
        lay = fx.build_thunderbird(self.root)
        store = mail_local.resolve(self.account())
        info = {name: mail_local.folder_info(name, path, store.roles) for name, path in store.folders.items()}
        self.assertEqual(info['INBOX-1']['role'], 'inbox')
        self.assertEqual(info['INBOX-1']['size'], lay['inbox'].stat().st_size)
        self.assertEqual(info['Sent']['role'], 'sent')
        self.assertGreater(info['Sent']['mtime'], 0)


class Index(Base):
    """Task 2.2."""

    def setUp(self):
        super().setUp()
        self.lay = fx.build_thunderbird(self.root)
        self.index_dir = Path(self.tmp, 'index')

    def index(self, name='inbox'):
        index = mail_index.FolderIndex(self.lay[name], self.index_dir)
        self.addCleanup(index.close)
        return index

    def rows(self, index, **filters):
        return index.live(index.select(mail_message.Filters(**filters)))

    def subjects(self, index, **filters):
        return [row['subject'] for row in self.rows(index, **filters)]

    def touch_later(self, path, seconds=30):
        stamp = time.time() + seconds
        os.utime(path, (stamp, stamp))

    def test_both_store_formats_are_indexed_with_the_messages_they_contain(self):
        inbox, sent = self.index('inbox'), self.index('sent')
        inbox.refresh()
        sent.refresh()
        self.assertEqual(inbox.count(), 6)           # five messages, one stored twice
        self.assertEqual(sent.count(), 2)            # three stored, one carries the deleted flag
        self.assertEqual(inbox.without_status(), 6)  # format B: no status lines at all
        self.assertEqual(sent.without_status(), 0)   # format A: status lines everywhere

    def test_the_date_comes_from_the_header_not_from_the_separator(self):
        index = self.index()
        index.refresh()
        by_subject = {row['subject']: row for row in self.rows(index)}
        self.assertEqual(by_subject['Invoice 2026']['date'], 1793527200.0)       # 2026-11-01 10:00 UTC
        self.assertEqual(by_subject['Café menu']['date'], 1793703600.0)          # +0100 honoured
        self.assertEqual(by_subject['No date at all']['date'], 1793779200.0)     # newest Received header
        self.assertIsNone(by_subject['Broken date']['date'])

    def test_a_message_without_a_usable_date_sorts_last(self):
        index = self.index()
        index.refresh()
        self.assertEqual(self.subjects(index)[-1], 'Broken date')

    def test_a_duplicate_message_id_is_listed_once(self):
        index = self.index()
        index.refresh()
        self.assertEqual(self.subjects(index).count('Invoice 2026'), 1)
        self.assertEqual(len(self.rows(index)), 5)

    def test_encoded_headers_are_decoded(self):
        index = self.index()
        index.refresh()
        row = next(r for r in self.rows(index) if r['subject'] == 'Café menu')
        self.assertEqual(row['from_party'], 'José')
        self.assertIn(fx.THIRD, row['rcpt'])

    def test_warm_run_does_not_open_the_file(self):
        index = self.index()
        self.assertTrue(index.refresh().opened)
        again = mail_index.FolderIndex(self.lay['inbox'], self.index_dir)
        self.addCleanup(again.close)
        stats = again.refresh()
        self.assertEqual((stats.opened, stats.rebuilt, stats.bytes_scanned), (False, False, 0))

    def test_appended_mail_parses_only_the_new_bytes(self):
        index = self.index()
        index.refresh()
        first_ids = {r['idh'] for r in self.rows(index)}
        before = self.lay['inbox'].stat().st_size
        last_start = int(index.meta()['last_start'])
        extra = fx.message('Late arrival', fx.OTHER, fx.ADDRESS, 'Sat, 07 Nov 2026 20:00:00 +0000', 'late-1@example.org')
        with open(self.lay['inbox'], 'ab') as handle:
            handle.write(fx.mbox_format_b([extra]))
        stats = index.refresh()
        self.assertFalse(stats.rebuilt)
        self.assertEqual(stats.bytes_scanned, self.lay['inbox'].stat().st_size - last_start)
        self.assertLess(stats.bytes_scanned, before)
        self.assertEqual(stats.messages, 2)          # the last known message is parsed again, plus the new one
        self.assertEqual(index.count(), 7)
        self.assertEqual(self.subjects(index)[0], 'Late arrival')
        self.assertLessEqual(first_ids, {r['idh'] for r in self.rows(index)})   # ids survive an incremental refresh

    def test_a_message_cut_short_by_a_running_client_is_reparsed_when_it_is_completed(self):
        extra = fx.message('Growing', fx.OTHER, fx.ADDRESS, 'Sat, 07 Nov 2026 20:00:00 +0000', 'grow-1@example.org',
                           body='x' * 600)
        full = fx.mbox_format_b([extra])
        with open(self.lay['inbox'], 'ab') as handle:
            handle.write(full[:60])                  # only the separator line and the start of the first header
        index = self.index()
        index.refresh()
        with open(self.lay['inbox'], 'ab') as handle:
            handle.write(full[60:])
        index.refresh()
        self.assertEqual(index.count(), 7)
        self.assertEqual(self.subjects(index)[0], 'Growing')

    def test_a_compacted_folder_is_rebuilt(self):
        index = self.index()
        index.refresh()
        msgs = fx.standard_messages()
        self.lay['inbox'].write_bytes(fx.mbox_format_b([msgs['html'], msgs['encoded']]))    # first and last gone: smaller
        stats = index.refresh()
        self.assertTrue(stats.rebuilt)
        self.assertEqual(sorted(self.subjects(index)), ['Café menu', 'Hello html'])

    def test_a_rewritten_folder_that_grew_is_rebuilt_when_the_last_message_moved(self):
        index = self.index()
        index.refresh()
        msgs = fx.standard_messages()
        bigger = fx.message('Big', fx.OTHER, fx.ADDRESS, 'Sat, 07 Nov 2026 20:00:00 +0000', 'big-1@example.org', body='y' * 9000)
        self.lay['inbox'].write_bytes(fx.mbox_format_b([bigger, msgs['html'], msgs['encoded'], msgs['nodate'], msgs['broken'],
                                                        msgs['invoice'], msgs['invoice']]))
        self.assertGreater(self.lay['inbox'].stat().st_size, int(index.meta()['size']))
        self.assertTrue(index.refresh().rebuilt)
        self.assertIn('Big', self.subjects(index))

    def test_a_flag_set_in_place_hides_the_message_without_a_reparse(self):
        index = self.index('sent')
        index.refresh()
        self.assertEqual(sorted(self.subjects(index)), ['Lunch tomorrow', 'Re: Invoice 2026'])
        data = self.lay['sent'].read_bytes()
        at = data.index(b'Lunch tomorrow')
        status = data.rindex(b'X-Mozilla-Status: 0001', 0, at)
        with open(self.lay['sent'], 'r+b') as handle:       # what the client does: rewrite the line in place
            handle.seek(status + len(b'X-Mozilla-Status: '))
            handle.write(b'0009')
        self.touch_later(self.lay['sent'])
        self.assertEqual(self.lay['sent'].stat().st_size, len(data))
        stats = index.refresh()
        self.assertEqual((stats.rebuilt, stats.bytes_scanned), (False, 0))
        self.assertEqual(self.subjects(index), ['Re: Invoice 2026'])

    def test_a_flag_set_before_indexing_is_skipped(self):
        index = self.index('sent')
        stats = index.refresh()
        self.assertEqual(stats.deleted_skipped, 1)
        self.assertNotIn('Deleted for good', self.subjects(index))

    def test_a_flag_on_the_first_message_does_not_force_a_rebuild(self):
        index = self.index('sent')
        index.refresh()
        data = self.lay['sent'].read_bytes()
        with open(self.lay['sent'], 'r+b') as handle:
            handle.seek(data.index(b'X-Mozilla-Status: 0001') + len(b'X-Mozilla-Status: '))
            handle.write(b'0009')
        self.touch_later(self.lay['sent'])
        self.assertFalse(index.refresh().rebuilt)

    def test_smaller_chunks_give_the_same_index(self):
        reference = self.index('inbox')
        reference.refresh()
        wanted = [(r['start'], r['idh'], r['subject']) for r in reference.select(mail_message.Filters())]
        for chunk in (16, 64, 100):
            other = mail_index.FolderIndex(self.lay['inbox'], Path(self.tmp, f'index-{chunk}'))
            self.addCleanup(other.close)
            other.refresh(chunk=chunk)
            self.assertEqual([(r['start'], r['idh'], r['subject']) for r in other.select(mail_message.Filters())],
                             wanted, chunk)

    def test_a_from_line_inside_a_body_is_not_a_separator(self):
        body = 'First paragraph.\nFrom - Sat Nov 07 21:46:36 2026\nFrom nobody Sat Nov 07 21:46:36 2026\n\nEnd.'
        tricky = fx.message('Tricky', fx.OTHER, fx.ADDRESS, 'Sat, 07 Nov 2026 20:00:00 +0000', 'tricky-1@example.org', body=body)
        self.lay['inbox'].write_bytes(fx.mbox_format_b([tricky, fx.standard_messages()['html']]))
        index = self.index()
        index.refresh()
        self.assertEqual(index.count(), 2)

    def test_separator_style_is_strict_about_the_date(self):
        broken = b'From - nonsense\r\nSubject: x\r\n\r\nbody\r\n\r\n'
        self.lay['inbox'].write_bytes(fx.mbox_format_b([fx.standard_messages()['html']]) + broken)
        index = self.index()
        index.refresh()
        self.assertEqual(index.count(), 1)

    def test_an_empty_folder_and_a_missing_one(self):
        empty = mail_index.FolderIndex(self.lay['old_inbox'], self.index_dir)
        self.addCleanup(empty.close)
        self.assertEqual(empty.refresh().messages, 0)
        self.assertEqual(self.rows(empty), [])
        missing = mail_index.FolderIndex(self.lay['account_dir'] / 'Nope', self.index_dir)
        self.addCleanup(missing.close)
        with self.assertRaises(Unavailable):
            missing.refresh()

    def test_index_modes_and_location(self):
        index = self.index()
        index.refresh()
        self.assertEqual(stat.S_IMODE(os.stat(self.index_dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(index.db_path).st_mode), 0o600)
        self.assertFalse(str(index.db_path).startswith(str(REPO_ROOT)))

    def test_the_store_is_left_untouched_and_unlocked(self):
        index = self.index()
        before = (self.lay['inbox'].stat().st_size, self.lay['inbox'].stat().st_mtime_ns,
                  hashlib.sha1(self.lay['inbox'].read_bytes()).hexdigest(), sorted(os.listdir(self.lay['account_dir'])))
        index.refresh()
        self.rows(index)
        index.raw(self.rows(index)[0])
        after = (self.lay['inbox'].stat().st_size, self.lay['inbox'].stat().st_mtime_ns,
                 hashlib.sha1(self.lay['inbox'].read_bytes()).hexdigest(), sorted(os.listdir(self.lay['account_dir'])))
        self.assertEqual(before, after)

    def test_filters_are_case_insensitive_substrings(self):
        index = self.index()
        index.refresh()
        self.assertEqual(self.subjects(index, subject='INVOICE'), ['Invoice 2026'])
        self.assertEqual(self.subjects(index, from_='JOSÉ'), ['Café menu'])
        self.assertEqual(self.subjects(index, to=fx.THIRD.upper()), ['Café menu'])
        self.assertEqual(self.subjects(index, has_attachment=True), ['Invoice 2026'])
        self.assertEqual(self.subjects(index, subject='['), [])


class MessageReading(Base):
    """Task 2.3."""

    def render(self, raw, **kwargs):
        return mail_message.render_message(raw, kwargs.pop('body_chars', 1500), **kwargs)

    def test_encoded_headers_are_decoded(self):
        doc = self.render(fx.standard_messages()['encoded'])
        self.assertEqual(doc['headers']['Subject'], 'Café menu')
        self.assertIn('José', doc['headers']['From'])
        self.assertIn(fx.THIRD, doc['headers']['To'])

    def test_unknown_charsets_and_broken_words_never_raise(self):
        self.assertEqual(mail_message.decode_words('=?x-no-such-charset?Q?abc?='), 'abc')
        self.assertIsInstance(mail_message.decode_words('=?utf-8?B?%%%not base64?='), str)
        self.assertEqual(mail_message.decode_words(b'plain'), 'plain')
        self.assertEqual(mail_message.parse_addresses('=?utf-8?Q?Jos=C3=A9?= <a@example.org>, b@example.org'),
                         [('José', 'a@example.org'), ('', 'b@example.org')])
        self.assertEqual(mail_message.parse_addresses(None), [])

    def test_plain_body(self):
        doc = self.render(fx.standard_messages()['invoice'])
        self.assertIn('Please find the invoice attached.', doc['body'])

    def test_html_only_message_is_reduced_to_text(self):
        doc = self.render(fx.standard_messages()['html'])
        self.assertIn('Hi there', doc['body'])
        self.assertIn('Second paragraph', doc['body'])
        self.assertNotIn('<', doc['body'])
        self.assertNotIn('p{}', doc['body'])

    def test_multipart_alternative_prefers_the_plain_part(self):
        raw = fx.message('Both', fx.OTHER, fx.ADDRESS, 'Sat, 07 Nov 2026 20:00:00 +0000', 'both-1@example.org',
                         body='the plain text', html='<p>the html text</p>')
        self.assertEqual(self.render(raw)['body'], 'the plain text')

    def test_quoted_reply_is_dropped_with_no_quote(self):
        raw = fx.standard_messages()['reply']
        self.assertIn('Please find the invoice', self.render(raw)['body'])
        self.assertEqual(self.render(raw, no_quote=True)['body'], 'Thanks, paid.')
        text = 'New.\n> quoted\nMiddle\n\n-----Original Message-----\nFrom: a\nOld stuff'
        self.assertEqual(mail_message.strip_quotes(text), 'New.\nMiddle')
        outlook = 'Answer\n\nFrom: A B <a@example.org>\nSent: Monday\nTo: x\nSubject: y\n\nold'
        self.assertEqual(mail_message.strip_quotes(outlook), 'Answer')
        self.assertEqual(mail_message.strip_quotes('El lunes, Ana escribió:\n> hola'), '')

    def test_body_is_cut_and_the_rest_is_counted(self):
        raw = fx.message('Long', fx.OTHER, fx.ADDRESS, 'Sat, 07 Nov 2026 20:00:00 +0000', 'long-1@example.org',
                         body='z' * 10000)
        doc = self.render(raw)
        self.assertEqual(len(doc['body']), 1500)
        self.assertEqual(doc['left_out'], doc['body_chars'] - 1500)
        self.assertGreaterEqual(doc['left_out'], 8500)
        self.assertEqual(self.render(raw, body_chars=0)['body'], '')

    def test_attachments_are_listed(self):
        doc = self.render(fx.standard_messages()['invoice'])
        self.assertEqual([(a['name'], a['type']) for a in doc['attachments']],
                         [('invoice.pdf', 'application/octet-stream')])
        self.assertEqual(doc['attachments'][0]['size'], len(b'%PDF-1.4 synthetic'))
        self.assertEqual(self.render(fx.standard_messages()['html'])['attachments'], [])

    def test_attachments_are_saved_without_overwriting(self):
        out = Path(self.tmp, 'out')
        msg = mail_message.parse_message(fx.standard_messages()['invoice'])
        first = mail_message.save_attachments(msg, out)
        second = mail_message.save_attachments(msg, out)
        self.assertEqual([p.name for p in first], ['invoice.pdf'])
        self.assertEqual([p.name for p in second], ['invoice-1.pdf'])
        self.assertEqual(first[0].read_bytes(), b'%PDF-1.4 synthetic')
        self.assertEqual(stat.S_IMODE(first[0].stat().st_mode), 0o600)
        third = mail_message.save_attachments(msg, out)
        self.assertEqual([p.name for p in third], ['invoice-2.pdf'])

    def test_an_existing_file_is_never_overwritten_even_through_a_symlink(self):
        out = Path(self.tmp, 'out')
        out.mkdir()
        victim = Path(self.tmp, 'victim.txt')
        victim.write_text('keep me')
        (out / 'invoice.pdf').symlink_to(victim)
        written = mail_message.save_attachments(mail_message.parse_message(fx.standard_messages()['invoice']), out)
        self.assertEqual(victim.read_text(), 'keep me')
        self.assertEqual([p.name for p in written], ['invoice-1.pdf'])

    def test_unsafe_names_are_reduced_to_a_safe_base_name_inside_the_directory(self):
        out = Path(self.tmp, 'out')
        names = ['../../escape.txt', '/etc/passwd', '.hidden', '..\\win\\evil.exe', 'a/b/c.txt', '...', 'sp ace (1).txt']
        raw = fx.message('Names', fx.OTHER, fx.ADDRESS, 'Sat, 07 Nov 2026 20:00:00 +0000', 'names-1@example.org',
                         attachments=[(name, b'data') for name in names])
        written = mail_message.save_attachments(mail_message.parse_message(raw), out)
        self.assertEqual(len(written), len(names))
        for path in written:
            self.assertEqual(path.parent, out)
            self.assertFalse(path.name.startswith('.'))
            self.assertNotIn('/', path.name)
        self.assertEqual({p.name for p in out.iterdir()}, {p.name for p in written})
        self.assertFalse(Path(self.tmp, 'escape.txt').exists())
        self.assertIn('escape.txt', {p.name for p in written})
        self.assertIn('hidden', {p.name for p in written})
        self.assertEqual(mail_message.safe_filename(None), 'attachment')
        self.assertLessEqual(len(mail_message.safe_filename('n' * 400 + '.pdf')), 120)

    def test_dates_are_timezone_aware_and_garbage_never_raises(self):
        self.assertEqual(mail_message.parse_date('Tue, 03 Nov 2026 12:00:00 +0100'), 1793703600.0)
        self.assertEqual(mail_message.parse_date('Tue, 03 Nov 2026 11:00:00 -0000'), 1793703600.0)
        for bad in (None, '', 'not a date', 'Mon, 99 Foo 2026 99:99:99 +9999', '0000-00-00', b'\xff\xfe'):
            self.assertIsNone(mail_message.parse_date(bad), bad)

    def test_a_message_that_is_not_mime_at_all_still_renders(self):
        doc = self.render(b'Subject: raw\r\n\r\njust text without any mime headers\r\n')
        self.assertEqual(doc['body'], 'just text without any mime headers')
        self.assertEqual(self.render(b'')['body'], '')


class CliBase(Base):
    """Runs the real entry script as a subprocess, in the temporary home."""

    def setUp(self):
        super().setUp()
        self.lay = fx.build_thunderbird(self.root)
        self.write_config(fx.account_config(self.root))

    def write_config(self, document):
        Path(self.cfg, 'mailbox.json').write_text(json.dumps(document), encoding='utf-8')

    def run_cli(self, *args, env=None):
        full = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_', 'MAILBOX'))}
        full.update(self.env)
        full.update(env or {})
        result = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=full, cwd=self.home)
        return result.returncode, result.stdout, result.stderr

    def search(self, *args):
        code, out, err = self.run_cli('search', 'work', *args)
        self.assertEqual(code, 0, err)
        return out

    def ids(self, out):
        return [line.split()[0] for line in out.splitlines() if line.startswith('l:')]

    def lines(self, out):
        return [line for line in out.splitlines() if line.startswith('l:')]

    def id_of(self, subject, *args):
        for line in self.lines(self.search(*args)):
            if line.endswith('| ' + subject):
                return line.split()[0]
        self.fail(f'{subject!r} not found')


class Accounts(CliBase):
    def test_no_account_configured(self):
        Path(self.cfg, 'mailbox.json').unlink()
        code, out, err = self.run_cli('accounts')
        self.assertEqual(code, 0)
        self.assertIn('no account configured', out)
        self.assertIn('mailbox.json', out)

    def test_shipped_defaults_have_no_account(self):
        shipped = json.loads(Path(REPO_ROOT, 'global/config/mailbox.json').read_text())
        self.assertEqual(shipped['accounts'], {})
        self.write_config(shipped)
        code, out, _ = self.run_cli('accounts')
        self.assertEqual((code, 'no account configured' in out), (0, True))

    def test_unknown_account_names_the_configured_ones(self):
        code, out, err = self.run_cli('search', 'nope')
        self.assertEqual(code, 2)
        self.assertIn("unknown account 'nope'", err)
        self.assertIn('work', err)
        self.assertEqual(err.count('\n'), 1)

    def test_unreadable_configuration_is_one_line_and_no_traceback(self):
        Path(self.cfg, 'mailbox.json').write_text('{not json')
        code, out, err = self.run_cli('accounts')
        self.assertEqual(code, 0)
        self.assertIn('no account configured', out)
        self.assertIn('mailbox.json', err)
        self.assertNotIn('Traceback', err)
        self.assertEqual(err.count('\n'), 1)
        code, _, err = self.run_cli('search', 'work')
        self.assertEqual(code, 2)
        self.assertNotIn('Traceback', err)

    def test_a_minimal_account_entry_works(self):
        self.write_config({'accounts': {'work': {'address': fx.ADDRESS, 'local': {'profile_roots': [str(self.root)]}}}})
        code, out, _ = self.run_cli('accounts', '--json')
        document = json.loads(out)
        self.assertEqual(document['accounts'][0]['backends'], ['local'])
        self.assertEqual(self.run_cli('search', 'work')[0], 0)

    def test_an_invalid_account_is_reported_not_crashed(self):
        self.write_config({'accounts': {'bad': {'address': fx.ADDRESS, 'backends': ['imap', 'connector']},
                                        'worse': 'text', 'none': {}}})
        code, out, _ = self.run_cli('accounts')
        self.assertEqual(code, 0)
        self.assertEqual(out.count('UNUSABLE'), 3)
        code, _, err = self.run_cli('search', 'bad')
        self.assertEqual(code, 2)

    def test_a_mistyped_setting_is_a_one_line_usage_error_never_a_traceback(self):
        base = {'address': fx.ADDRESS, 'backends': ['imap']}
        cases = {'port_text': ({'imap': {'host': 'mail.example.com', 'port': 'abc'}}, 'imap.port'),
                 'port_range': ({'imap': {'host': 'mail.example.com', 'port': 70000}}, 'imap.port'),
                 'port_flag': ({'imap': {'host': 'mail.example.com', 'port': True}}, 'imap.port'),
                 'folders': ({'backends': ['local'], 'local': {'folders': 5}}, 'local.folders')}
        self.write_config({'accounts': {name: dict(base, **extra) for name, (extra, _) in cases.items()}})
        for name, (_, setting) in cases.items():
            for command in (('search', name), ('doctor', name), ('folders', name)):
                code, out, err = self.run_cli(*command)
                self.assertNotIn('Traceback', err, (name, command))
                self.assertEqual(code, 2, (name, command, err))
                self.assertIn(setting, err + out, (name, command))
        self.assertEqual(self.run_cli('accounts')[1].count('UNUSABLE'), len(cases))
        # the usual spellings stay valid: a port as text, no `folders` at all, a section that is not an object
        self.write_config({'accounts': {'ok': dict(base, imap={'host': 'mail.example.com', 'port': '993'}),
                                        'odd': dict(base, backends=['local'], local='text'),
                                        'nulls': dict(base, backends=['local'], local={'folders': None})}})
        self.assertEqual(self.run_cli('accounts')[1].count('UNUSABLE'), 0)

    def test_help_is_the_module_docstring(self):
        code, out, _ = self.run_cli('--help')
        self.assertEqual(code, 0)
        self.assertIn('mailbox search ACCOUNT', out)
        self.assertIn('Exit codes', out)


class LocalCommands(CliBase):
    """Task 2.4: the subcommands on the local backend."""

    def test_search_lists_both_folders_newest_first_with_a_status_line(self):
        out = self.search()
        first = out.splitlines()[0]
        self.assertTrue(first.startswith('work | local | 7 matches | '), first)
        self.assertIn('2 folders, last change 20', first)
        subjects = [line.split(' | ', 1)[1] for line in self.lines(out)]
        self.assertEqual(subjects, ['Lunch tomorrow', 'No date at all', 'Café menu', 'Hello html', 'Re: Invoice 2026',
                                   'Invoice 2026', 'Broken date'])

    def test_the_text_scan_of_the_local_backend_is_capped_and_says_so(self):
        for cap in (2, 1000):
            config = fx.account_config(self.root)
            config['defaults'] = {'text_scan_max': cap}
            self.write_config(config)
            out = self.search('--text', 'e')                 # a letter every body has: only the cap can cut the scan
            first = out.splitlines()[:6]
            note = [line for line in first if line.startswith('note: --text scanned the newest')]
            if cap == 2:
                self.assertEqual(len(note), 1, out)
                self.assertIn(f'newest {cap} of ', note[0])
                self.assertLessEqual(len(self.lines(out)), cap)
            else:
                self.assertEqual(note, [], out)
                self.assertGreater(len(self.lines(out)), 2)

    def test_a_result_line_has_id_date_direction_party_subject_and_attachment_mark(self):
        lines = {line.split(' | ', 1)[1]: line for line in self.lines(self.search())}
        invoice = lines['Invoice 2026'].split()
        self.assertTrue(invoice[0].startswith('l:INBOX-1:'))
        self.assertEqual(invoice[1:3], ['2026-11-01', '10:00'])
        self.assertEqual(invoice[3], '<@')
        self.assertIn('Other Person', lines['Invoice 2026'])
        sent = lines['Lunch tomorrow'].split()
        self.assertEqual((sent[1:3], sent[3]), (['2026-11-05', '11:00'], '>'))
        self.assertIn(fx.THIRD, lines['Lunch tomorrow'])
        self.assertNotIn(' ', lines['Lunch tomorrow'].split()[0])

    def test_filters(self):
        self.assertEqual(len(self.lines(self.search('--from', 'OTHER@EXAMPLE'))), 5)
        self.assertEqual(len(self.lines(self.search('--subject', 'invoice'))), 2)
        self.assertEqual(len(self.lines(self.search('--to', fx.THIRD))), 3)         # To and Cc both count
        self.assertEqual(len(self.lines(self.search('--has-attachment'))), 1)
        self.assertEqual(len(self.lines(self.search('--folder', 'sent'))), 2)
        self.assertEqual(len(self.lines(self.search('--folder', 'inbox'))), 5)
        self.assertEqual(len(self.lines(self.search('--folder', 'sent', '--from', 'other@'))), 0)
        self.assertEqual(len(self.lines(self.search('--since', '2026-11-03'))), 3)
        self.assertEqual(len(self.lines(self.search('--until', '2026-11-01'))), 2)
        self.assertEqual(len(self.lines(self.search('--since', '2026-11-02', '--until', '2026-11-03'))), 2)
        self.assertEqual(len(self.lines(self.search('--header', 'Message-ID: lunch-1'))), 1)
        self.assertEqual(len(self.lines(self.search('--text', 'PAID'))), 1)
        self.assertEqual(len(self.lines(self.search('--text', 'no such words anywhere'))), 0)

    def test_text_filters_are_substrings_not_regular_expressions(self):
        self.assertEqual(len(self.lines(self.search('--subject', 'Invoice.*'))), 0)
        self.assertEqual(len(self.lines(self.search('--subject', 'nvoice 20'))), 2)

    def test_both_directions_are_searched_with_to_or_from(self):
        out = self.search('--to', fx.OTHER)
        self.assertIn('Re: Invoice 2026', out)                                  # sent by the account
        self.assertEqual(len(self.lines(self.search('--from', fx.ADDRESS))), 2)  # inbox mail was To the account

    def test_relative_since(self):
        self.assertEqual(len(self.lines(self.search('--since', '1d'))), 0)
        self.assertEqual(len(self.lines(self.search('--since', '30000d'))), 6)   # the undated message has no date to compare
        self.assertEqual(self.run_cli('search', 'work', '--since', 'yesterday')[0], 2)
        self.assertEqual(self.run_cli('search', 'work', '--until', '3d')[0], 2)
        self.assertEqual(self.run_cli('search', 'work', '--header', 'no colon')[0], 2)

    def test_default_bounds_and_the_total(self):
        many = [fx.message(f'Bulk {n:03d}', fx.OTHER, fx.ADDRESS, f'Mon, 02 Nov 2026 {n // 60:02d}:{n % 60:02d}:00 +0000',
                           f'bulk-{n}@example.org', body='b' * 300) for n in range(300)]
        self.lay['inbox'].write_bytes(fx.mbox_format_b(many))
        out = self.search('--folder', 'inbox')
        lines = out.splitlines()
        self.assertIn('300 matches', lines[0])
        self.assertEqual(len(self.lines(out)), 20)
        self.assertEqual(lines[-1], '20 of 300 shown')
        self.assertTrue(all(len(line) <= 160 for line in lines))
        self.assertEqual(len(self.lines(self.search('--folder', 'inbox', '--limit', '5'))), 5)
        document = json.loads(self.run_cli('search', 'work', '--folder', 'inbox', '--json')[1])
        self.assertEqual((document['total'], document['shown'], len(document['items'])), (300, 20, 20))

    def test_a_long_subject_is_clipped_to_a_line(self):
        long = fx.message('S' * 400, fx.OTHER, fx.ADDRESS, 'Mon, 02 Nov 2026 10:00:00 +0000', 'long-s@example.org')
        self.lay['inbox'].write_bytes(fx.mbox_format_b([long]))
        self.assertTrue(all(len(line) <= 160 for line in self.search().splitlines()))

    def test_a_message_without_a_date_is_listed_last_and_does_not_fail(self):
        out = self.search('--folder', 'inbox')
        self.assertTrue(self.lines(out)[-1].endswith('| Broken date'))
        self.assertIn('----------- --:--', self.lines(out)[-1])
        self.assertIn('No date at all', out)

    def test_machine_output(self):
        code, out, _ = self.run_cli('search', 'work', '--json')
        document = json.loads(out)
        self.assertEqual((document['backend'], document['total'], document['account']), ('local', 7, 'work'))
        self.assertIn('local copy', document['freshness'])
        self.assertEqual({'id', 'date', 'direction', 'party', 'subject', 'attachment'} <= set(document['items'][0]), True)

    def test_the_no_status_note_appears_only_when_the_folder_has_no_status_lines(self):
        self.assertIn('may hold mail deleted or moved', self.search('--folder', 'inbox'))
        self.assertNotIn('may hold mail deleted or moved', self.search('--folder', 'sent'))

    def test_deleted_messages_never_appear(self):
        self.assertNotIn('Deleted for good', self.search())
        self.assertEqual(len(self.lines(self.search('--subject', 'Deleted for good'))), 0)

    def test_the_duplicate_is_listed_once(self):
        self.assertEqual(len(self.lines(self.search('--folder', 'inbox', '--subject', 'Invoice 2026'))), 1)

    def test_show_html_only_message(self):
        code, out, _ = self.run_cli('show', 'work', self.id_of('Hello html'))
        self.assertEqual(code, 0)
        self.assertIn('Hi there', out)
        self.assertNotIn('<p>', out)
        self.assertIn('Subject: Hello html', out)
        self.assertIn('From: Other Person <other@example.org>', out)

    def test_show_no_quote_and_attachments(self):
        reply = self.id_of('Re: Invoice 2026')
        self.assertIn('Please find the invoice', self.run_cli('show', 'work', reply)[1])
        out = self.run_cli('show', 'work', reply, '--no-quote')[1]
        self.assertIn('Thanks, paid.', out)
        self.assertNotIn('Please find the invoice', out)
        out = self.run_cli('show', 'work', self.id_of('Invoice 2026'))[1]
        self.assertIn('Attachments: invoice.pdf', out)
        out = self.run_cli('show', 'work', reply, '--headers')[1]
        self.assertIn('In-Reply-To: <invoice-1@example.org>', out)

    def test_show_body_default_length_and_override(self):
        long = fx.message('Long one', fx.OTHER, fx.ADDRESS, 'Mon, 02 Nov 2026 10:00:00 +0000', 'long-b@example.org',
                          body='w' * 10000)
        self.lay['inbox'].write_bytes(fx.mbox_format_b([long]))
        item = self.id_of('Long one')
        out = self.run_cli('show', 'work', item)[1]
        self.assertIn('w' * 1500, out)
        self.assertNotIn('w' * 1501, out)
        self.assertRegex(out, r'\[8\d\d\d more characters not shown')
        shorter = self.run_cli('show', 'work', item, '--body-chars', '20')[1]
        self.assertIn('w' * 20, shorter)
        self.assertNotIn('w' * 21, shorter)
        document = json.loads(self.run_cli('show', 'work', item, '--json')[1])
        self.assertEqual((len(document['body']), document['left_out'] > 8000), (1500, True))

    def test_stale_and_foreign_ids_exit_4(self):
        for bad in ('l:INBOX-1:000000000000', 'l:Gone:abc', 'whatever', 'l:INBOX-1'):
            code, _, err = self.run_cli('show', 'work', bad)
            self.assertEqual(code, 4, bad)
            self.assertIn('search', err)

    def test_an_id_survives_an_index_rebuild_and_a_cache_wipe(self):
        item = self.id_of('Invoice 2026')
        shutil.rmtree(self.cache)
        self.assertEqual(self.id_of('Invoice 2026'), item)
        self.assertEqual(self.run_cli('show', 'work', item)[0], 0)

    def test_thread_across_folders_oldest_first(self):
        out = self.run_cli('thread', 'work', self.id_of('Invoice 2026'))[1]
        subjects = [line.split(' | ', 1)[1] for line in self.lines(out)]
        self.assertEqual(subjects, ['Invoice 2026', 'Re: Invoice 2026'])
        self.assertIn('2 messages, oldest first', out)
        again = self.run_cli('thread', 'work', self.id_of('Re: Invoice 2026'))[1]
        self.assertEqual([line.split(' | ', 1)[1] for line in self.lines(again)], subjects)
        alone = self.run_cli('thread', 'work', self.id_of('Lunch tomorrow'))[1]
        self.assertEqual(len(self.lines(alone)), 1)
        self.assertEqual(self.run_cli('thread', 'work', 'l:Sent:ffffffffffff')[0], 4)

    def test_save_writes_attachments_and_never_overwrites(self):
        out_dir = Path(self.tmp, 'saved')
        item = self.id_of('Invoice 2026')
        code, out, _ = self.run_cli('save', 'work', item, '--out', str(out_dir))
        self.assertEqual(code, 0)
        self.assertEqual((out_dir / 'invoice.pdf').read_bytes(), b'%PDF-1.4 synthetic')
        self.run_cli('save', 'work', item, '--out', str(out_dir))
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()), ['invoice-1.pdf', 'invoice.pdf'])
        none = self.run_cli('save', 'work', self.id_of('Hello html'), '--out', str(out_dir))[1]
        self.assertIn('no attachments', none)

    def test_where_prints_only_the_path(self):
        code, out, _ = self.run_cli('where', 'work', 'inbox')
        self.assertEqual((code, out), (0, str(self.lay['inbox'].resolve()) + '\n'))
        self.assertEqual(self.run_cli('where', 'work')[1], out)
        self.assertEqual(self.run_cli('where', 'work', 'sent')[1], str(self.lay['sent'].resolve()) + '\n')
        self.assertEqual(self.run_cli('where', 'work', 'Drafts')[1], str(self.lay['drafts'].resolve()) + '\n')
        code, out, err = self.run_cli('where', 'work', 'nonexistent')
        self.assertEqual((code, out), (3, ''))

    def test_folders(self):
        code, out, _ = self.run_cli('folders', 'work')
        self.assertEqual(code, 0)
        self.assertRegex(out, r'INBOX-1 \| inbox \| \d+ bytes')
        self.assertIn('Sent | sent', out)
        document = json.loads(self.run_cli('folders', 'work', '--json')[1])
        self.assertEqual({f['name'] for f in document['folders']}, {'INBOX-1', 'Sent', 'Drafts'})

    def second_sent(self, copy_messages=True):
        data = self.lay['sent'].read_bytes()
        extra = fx.message('Only in the copy', fx.ADDRESS, fx.THIRD, 'Fri, 06 Nov 2026 18:00:00 +0000', 'copy-1@example.com')
        (self.lay['account_dir'] / 'Sent-1').write_bytes((data if copy_messages else b'') + fx.mbox_format_b([extra]))
        os.utime(self.lay['account_dir'] / 'Sent-1', (time.time() + 100, time.time() + 100))

    def test_two_non_empty_sent_folders_are_both_searched_and_a_shared_message_is_listed_once(self):
        self.second_sent()
        out = self.search('--folder', 'sent')
        subjects = [line.split(' | ', 1)[1] for line in self.lines(out)]
        self.assertEqual(sorted(subjects), ['Lunch tomorrow', 'Only in the copy', 'Re: Invoice 2026'])
        self.assertIn('| 3 matches |', out)
        self.assertIn('2 folders', out.splitlines()[0])
        self.assertEqual(len(self.lines(self.search())), 8)      # all: inbox 5 + sent 3, shared messages once

    def test_an_empty_old_sent_folder_is_ignored(self):
        (self.lay['account_dir'] / 'Enviados').write_bytes(b'')
        out = self.search('--folder', 'sent')
        self.assertIn('1 folder,', out.splitlines()[0])
        self.assertEqual(len(self.lines(out)), 2)

    def test_where_prints_one_path_per_folder_most_recent_first(self):
        self.second_sent()
        code, out, _ = self.run_cli('where', 'work', 'sent')
        self.assertEqual(out.splitlines(), [str((self.lay['account_dir'] / 'Sent-1').resolve()), str(self.lay['sent'].resolve())])

    def test_a_pinned_list_replaces_the_heuristic(self):
        self.second_sent()
        account = fx.account_config(self.root)
        account['accounts']['work']['local']['folders']['sent'] = ['Sent']
        self.write_config(account)
        self.assertEqual(len(self.lines(self.search('--folder', 'sent'))), 2)

    def test_a_folder_with_an_encoded_name_is_searched_by_either_name(self):
        data = fx.mbox_format_b([fx.message('Medical', fx.OTHER, fx.ADDRESS, 'Mon, 02 Nov 2026 10:00:00 +0000', 'med-1@example.org')])
        (self.lay['account_dir'] / 'Rese&APE-as').write_bytes(data)
        for name in ('Reseñas', 'Rese&APE-as'):
            self.assertEqual(len(self.lines(self.search('--folder', name))), 1, name)
        item = self.lines(self.search('--folder', 'Reseñas'))[0].split()[0]
        self.assertIn('Medical', self.run_cli('show', 'work', item)[1])
        self.assertIn('Rese', self.run_cli('folders', 'work')[1])

    def test_folders_are_bounded_role_folders_first_then_the_most_recent(self):
        for number in range(30):
            path = self.lay['account_dir'] / f'Archive {number:02d}'
            path.write_bytes(fx.mbox_format_b([fx.standard_messages()['html']]))
            os.utime(path, (1_700_000_000 + number, 1_700_000_000 + number))
        code, out, _ = self.run_cli('folders', 'work')
        names = [line.split(' | ')[0] for line in out.splitlines()[1:] if ' | ' in line]
        self.assertEqual(set(names[:3]), {'INBOX-1', 'Sent', 'Drafts'})
        self.assertEqual(names[3], 'Archive 29')
        self.assertEqual(len(names), 20)
        self.assertIn('33 folders', out)
        self.assertEqual(out.splitlines()[-1], '20 of 33 shown')
        code, out, _ = self.run_cli('folders', 'work', '--limit', '5')
        self.assertEqual(len([l for l in out.splitlines() if ' | ' in l]) - 1, 5)
        document = json.loads(self.run_cli('folders', 'work', '--json')[1])
        self.assertEqual((document['total'], document['shown']), (33, 20))

    def test_forced_backend_that_is_unavailable_exits_3_with_the_reason(self):
        self.write_config({'accounts': {'work': {'address': 'nobody@example.org', 'backends': ['local'],
                                                 'local': {'profile_roots': [str(self.root)]}}}})
        code, out, err = self.run_cli('search', 'work', '--backend', 'local')
        self.assertEqual(code, 3)
        self.assertIn('no profile defines this account', err)
        self.assertIn('mailbox doctor', err)

    def test_the_store_is_untouched_by_every_command(self):
        def snapshot():
            files = sorted(p for p in self.lay['account_dir'].rglob('*') if p.is_file())
            return [(p.name, p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha1(p.read_bytes()).hexdigest()) for p in files]
        before = snapshot()
        item = self.id_of('Invoice 2026')
        for args in (('search', 'work', '--text', 'paid'), ('show', 'work', item), ('thread', 'work', item),
                     ('save', 'work', item, '--out', str(Path(self.tmp, 'o'))), ('where', 'work'), ('folders', 'work'),
                     ('doctor', 'work')):
            self.run_cli(*args)
        self.assertEqual(snapshot(), before)
        self.assertEqual(sorted(os.listdir(self.lay['account_dir'])), sorted(p.name for p in self.lay['account_dir'].iterdir()))

    def test_doctor_describes_the_local_backend_and_prints_no_path_of_the_user(self):
        code, out, _ = self.run_cli('doctor', 'work')
        self.assertEqual(code, 0)
        self.assertIn('local: available; profile new5678.default-release; inbox=INBOX-1, sent=Sent, drafts=Drafts', out)

    def test_doctor_reports_an_unavailable_store_with_exit_3(self):
        self.write_config({'accounts': {'work': {'address': 'nobody@example.org', 'local': {'profile_roots': [str(self.root)]}}}})
        code, out, _ = self.run_cli('doctor')
        self.assertEqual(code, 3)
        self.assertIn('local: unavailable: no profile defines this account', out)

    def test_every_command_is_listed_in_the_help_and_none_writes(self):
        script = Path(SCRIPT).read_text()
        for verb in ('send', 'reply', 'draft', 'delete', 'move', 'flag'):
            self.assertNotRegex(script, rf"add\('{verb}'")

    def test_an_unusable_index_file_is_one_line_and_exit_1_not_a_traceback(self):
        self.search()
        indexes = list(Path(self.cache, 'claude-toolkit', 'mailbox', 'index').glob('index-*.sqlite'))
        self.assertTrue(indexes)
        for path in indexes:
            path.write_bytes(b'this is not a database file, ' * 400)
        code, out, err = self.run_cli('search', 'work')
        self.assertEqual(code, 1)
        self.assertNotIn('Traceback', err)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertIn('local index could not be used', err)

    def test_terminal_escape_sequences_in_a_subject_never_reach_the_output(self):
        evil = fx.message('Alert \x1b]0;pwned\x07 done', fx.OTHER, fx.ADDRESS, 'Mon, 02 Nov 2026 10:00:00 +0000',
                          'evil@example.org', body='body \x1b[31m red \x9b31m c1 \x8d next')
        self.lay['inbox'].write_bytes(fx.mbox_format_b([evil]))
        out = self.search()
        self.assertNotIn('\x1b', out)
        item = self.ids(self.search('--subject', 'Alert'))[0]
        shown = self.run_cli('show', 'work', item)[1]
        self.assertNotIn('\x1b', shown)
        self.assertEqual([c for c in shown if 0x7f <= ord(c) < 0xa0], [], 'C1 control characters are replaced too')
        self.assertIn('body ?[31m red ?31m c1 ? next', shown)


PASSWORD = 'synthetic-pass-0001'


class FakeServer:
    """A recording fake of an IMAP server and of the imaplib class. Any method that is not one of the read-only
    ones the backend may use raises AssertionError, so a STORE, COPY, APPEND, CLOSE... would fail the test."""

    def __init__(self):
        msgs = fx.standard_messages()
        self.folders = [   # (raw name as listed, flags, {uid: raw message})
            ('INBOX', '\\HasNoChildren', {11: msgs['invoice'], 12: msgs['html'], 13: msgs['encoded'],
                                          14: msgs['nodate'], 15: msgs['broken']}),
            ('Sent Items', '\\HasNoChildren \\Sent', {21: msgs['reply'], 22: msgs['sent2']}),
            ('Enviados', '\\HasNoChildren', {31: msgs['sent2']}),
            ('Entw&APw-rfe', '\\HasNoChildren \\Drafts', {41: msgs['draft']}),
            ('Rese&APE-as', '\\HasNoChildren', {51: msgs['html']}),
            ('Trash', '\\HasNoChildren \\Trash', {}),
            ('[Gmail]', '\\Noselect \\HasChildren', {}),
        ]
        self.validity = 7001
        self.log = []                 # (verb, detail) of every command, passwords never recorded
        self.connections = 0
        self.login_error = None       # None, 'reject', 'abort' or an exception instance
        self.search_error = None      # an exception raised by every UID SEARCH from now on (a server that stops answering)
        self.max_or = None            # a search with more OR keys than this is refused, as a real server refuses a long chain
        self.connect_error = None
        self.password = PASSWORD
        self.current = None

    def factory(self, host, port, timeout):
        self.log.append(('CONNECT', (host, port, timeout)))
        self.connections += 1
        if self.connect_error:
            raise self.connect_error
        return FakeConn(self)


class FakeConn:
    def __init__(self, server):
        self.server = server

    def __getattr__(self, name):
        raise AssertionError(f'the backend called imaplib method {name!r}, which is not part of the read-only set')

    def login(self, user, password):
        server = self.server
        server.log.append(('LOGIN', user))
        if server.login_error == 'abort':
            raise imaplib.IMAP4.abort('socket error: EOF')
        if isinstance(server.login_error, Exception):
            raise server.login_error
        if server.login_error == 'reject' or password != server.password:
            raise imaplib.IMAP4.error('[AUTHENTICATIONFAILED] Authentication failed.')
        return 'OK', [b'Logged in']

    def list(self):
        self.server.log.append(('LIST', ''))
        lines = []
        for raw, flags, _ in self.server.folders:
            if ' ' in raw:
                lines.append(f'({flags}) "/" "{raw}"'.encode())
            else:
                lines.append(f'({flags}) "/" {raw}'.encode())
        return 'OK', lines

    def select(self, mailbox, readonly=False):
        self.server.log.append(('SELECT', (mailbox, readonly)))
        name = mailbox[1:-1] if mailbox.startswith('"') else mailbox
        for raw, _, _ in self.server.folders:
            if raw == name:
                self.server.current = raw
                return 'OK', [str(len(self._messages())).encode()]
        return 'NO', [b'no such folder']

    def response(self, code):
        self.server.log.append(('RESPONSE', code))
        return code, [str(self.server.validity).encode()]

    def _messages(self):
        for raw, _, messages in self.server.folders:
            if raw == self.server.current:
                return messages
        return {}

    def uid(self, command, *args):
        self.server.log.append(('UID ' + command, args))
        if command == 'SEARCH':
            if self.server.search_error is not None:
                raise self.server.search_error
            if self.server.max_or is not None and list(args).count('OR') > self.server.max_or:
                raise imaplib.IMAP4.error('UID command error: BAD [b\'Command Argument Error. 12\']')
            tree, _ = self._parse(list(args), 0, [])
            hits = [u for u, raw in sorted(self._messages().items()) if self._eval(tree, raw)]
            return 'OK', [' '.join(map(str, hits)).encode()]
        if command == 'FETCH':
            wanted = [int(x) for x in args[0].split(',')]
            spec = args[1]
            out = []
            for uid in wanted:
                raw = self._messages().get(uid)
                if raw is None:
                    continue
                if 'HEADER.FIELDS' in spec:
                    body = raw.split(b'\r\n\r\n', 1)[0] + b'\r\n\r\n'
                    out.append((f'1 (UID {uid} BODY[HEADER.FIELDS (...)] {{{len(body)}}}'.encode(), body))
                else:
                    out.append((f'1 (UID {uid} BODY[] {{{len(raw)}}}'.encode(), raw))
                out.append(b')')
            return 'OK', out or [None]
        raise AssertionError(f'unexpected UID command {command}')

    def logout(self):
        self.server.log.append(('LOGOUT', ''))
        return 'BYE', [b'bye']

    # a tiny evaluator of the search keys the backend sends
    def _parse(self, tokens, pos, nodes):
        keys = ('FROM', 'TO', 'CC', 'BCC', 'SUBJECT', 'TEXT', 'SINCE', 'BEFORE')
        while pos < len(tokens):
            token = tokens[pos]
            if token == 'ALL':
                pos += 1
            elif token == 'OR':
                left, pos = self._parse_one(tokens, pos + 1)
                right, pos = self._parse_one(tokens, pos)
                nodes.append(('or', left, right))
            else:
                node, pos = self._parse_one(tokens, pos)
                nodes.append(node)
        return ('and', nodes), pos

    def _parse_one(self, tokens, pos):
        token = tokens[pos]
        if token == 'OR':
            left, pos = self._parse_one(tokens, pos + 1)
            right, pos = self._parse_one(tokens, pos)
            return ('or', left, right), pos
        if token == 'HEADER':
            return ('header', tokens[pos + 1].lower(), tokens[pos + 2].strip('"')), pos + 3
        return (token, tokens[pos + 1].strip('"')), pos + 2

    def _eval(self, node, raw):
        if node[0] == 'and':
            return all(self._eval(n, raw) for n in node[1])
        if node[0] == 'or':
            return self._eval(node[1], raw) or self._eval(node[2], raw)
        msg = mail_message.parse_message(raw)
        if node[0] == 'header':
            return node[2].lower() in str(msg[node[1]] or '').lower()
        if node[0] in ('FROM', 'TO', 'CC', 'BCC', 'SUBJECT'):
            return node[1].lower() in str(msg[node[0].title()] or '').lower()
        if node[0] == 'TEXT':
            return node[1].lower() in raw.decode('utf-8', 'replace').lower()
        return True     # SINCE, BEFORE: the backend filters dates again itself


def load_cli():
    loader = importlib.machinery.SourceFileLoader('mailbox_cli_under_test', SCRIPT)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ImapBase(Base):
    """In-process runs of the entry script with the connection factory replaced by the recording fake."""

    def setUp(self):
        super().setUp()
        self.cli = load_cli()
        self.server = FakeServer()
        self.creds = Path(self.tmp, 'mail.env')
        self.creds.write_text(f'MAIL_PASSWORD={PASSWORD}\n')
        os.chmod(self.creds, 0o600)
        patch = mock.patch.object(mail_imap, 'factory', self.server.factory)
        patch.start()
        self.addCleanup(patch.stop)
        self.lay = fx.build_thunderbird(self.root)
        self.configure()

    def configure(self, backends=('imap',), **imap):
        account = {'address': fx.ADDRESS, 'backends': list(backends),
                   'imap': {'host': fx.HOST, 'port': 993, 'user': '', 'credentials_file': str(self.creds),
                            'password_var': 'MAIL_PASSWORD', **imap},
                   'local': {'profile_roots': [str(self.root)]}}
        Path(self.cfg, 'mailbox.json').write_text(json.dumps({'accounts': {'work': account}}))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.cli.main(list(args))
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def lines(self, out, prefix='i:'):
        return [line for line in out.splitlines() if line.startswith(prefix)]

    def subjects(self, out, prefix='i:'):
        return [line.split(' | ', 1)[1] for line in self.lines(out, prefix)]


class ImapReadOnly(ImapBase):
    """Task 3.1."""

    ALLOWED = {'CONNECT', 'LOGIN', 'LIST', 'SELECT', 'RESPONSE', 'UID SEARCH', 'UID FETCH', 'LOGOUT'}
    FORBIDDEN = ('STORE', 'COPY', 'MOVE', 'APPEND', 'EXPUNGE', 'CREATE', 'DELETE', 'RENAME', 'SUBSCRIBE', 'CLOSE')

    def assert_read_only(self):
        verbs = {verb for verb, _ in self.server.log}
        self.assertLessEqual(verbs, self.ALLOWED)
        for verb, detail in self.server.log:
            if verb == 'SELECT':
                self.assertIs(detail[1], True, 'every folder is opened read-only (EXAMINE)')
            if verb == 'UID FETCH':
                self.assertTrue(detail[1].startswith('(BODY.PEEK['), detail)
                self.assertNotRegex(detail[1].replace('BODY.PEEK[', ''), r'BODY\[|RFC822')
            self.assertNotIn(verb.split()[-1], self.FORBIDDEN)

    def test_a_search_then_a_fetch_issue_only_read_only_commands(self):
        code, out, err = self.run_cli('search', 'work')
        self.assertEqual(code, 0, err)
        item = self.lines(out)[0].split()[0]
        self.assertEqual(self.run_cli('show', 'work', item)[0], 0)
        self.assertEqual(self.run_cli('thread', 'work', item)[0], 0)
        self.assertEqual(self.run_cli('folders', 'work')[0], 0)
        self.assert_read_only()
        self.assertGreater(len([v for v, _ in self.server.log if v == 'UID FETCH']), 2)

    def test_the_module_text_has_no_writing_command(self):
        text = Path(REPO_ROOT, 'global/scripts/lib/access/mail_imap.py').read_text()
        code = re.sub(r'""".*?"""', '', text, flags=re.S)
        code = '\n'.join(line for line in code.splitlines() if not line.lstrip().startswith('#'))
        for method in ('store', 'copy', 'move', 'append', 'expunge', 'create', 'delete', 'rename', 'subscribe', 'close',
                       'unsubscribe', 'noop', 'idle', 'partial', 'setacl', 'xatom'):
            self.assertNotRegex(code, rf'\bconn\.{method}\b', method)
        for verb in ('STORE', 'COPY', 'APPEND', 'EXPUNGE', 'RENAME', 'SUBSCRIBE'):
            self.assertNotRegex(code, rf"['\"]{verb}['\"]", verb)
        self.assertNotRegex(code, r'BODY\[(?!.*PEEK)')
        self.assertIn('readonly=True', code)

    def test_folder_roles_come_from_the_special_use_flags_and_the_known_names(self):
        code, out, _ = self.run_cli('folders', 'work')
        self.assertEqual(code, 0)
        self.assertIn('Sent Items | sent', out)
        self.assertIn('Enviados | sent', out)
        self.assertIn('Entwürfe | drafts', out)
        self.assertIn('INBOX | inbox', out)
        self.assertNotIn('[Gmail]', out)
        self.assertIn('Reseñas | -', out)

    def test_folder_names_with_spaces_and_accents_are_quoted_and_encoded(self):
        self.assertEqual(self.run_cli('search', 'work', '--folder', 'Sent Items')[0], 0)
        self.assertEqual(self.run_cli('search', 'work', '--folder', 'entwürfe')[0], 0)
        self.assertEqual(self.run_cli('search', 'work', '--folder', 'Reseñas')[0], 0)
        self.assertEqual(self.run_cli('search', 'work', '--folder', 'Rese&APE-as')[0], 0)
        selects = [detail[0] for verb, detail in self.server.log if verb == 'SELECT']
        self.assertEqual(selects, ['"Sent Items"', '"Entw&APw-rfe"', '"Rese&APE-as"', '"Rese&APE-as"'])
        self.assertEqual(self.run_cli('search', 'work', '--folder', 'Nope')[0], 3)

    def test_search_default_covers_inbox_and_every_sent_folder_with_one_listing_per_message(self):
        code, out, _ = self.run_cli('search', 'work')
        self.assertEqual(code, 0)
        self.assertIn('| imap | 7 matches | live', out.splitlines()[0])
        self.assertEqual(self.subjects(out).count('Lunch tomorrow'), 1)      # the same message in two sent folders
        self.assertEqual(len(self.lines(out)), 7)
        first = self.lines(out)[0].split()
        self.assertRegex(first[0], r'^i:INBOX:7001:\d+$|^i:Sent%20Items:7001:\d+$|^i:Enviados:7001:\d+$')

    def test_the_server_search_is_used_and_filters_are_reapplied(self):
        code, out, _ = self.run_cli('search', 'work', '--from', 'OTHER@', '--subject', 'invoice', '--folder', 'inbox')
        self.assertEqual(self.subjects(out), ['Invoice 2026'])
        searches = [detail for verb, detail in self.server.log if verb == 'UID SEARCH']
        self.assertEqual(searches[-1], ('FROM', '"OTHER@"', 'SUBJECT', '"invoice"'))

    def test_to_searches_to_cc_and_bcc(self):
        self.run_cli('search', 'work', '--to', fx.THIRD, '--folder', 'all')
        searches = [detail for verb, detail in self.server.log if verb == 'UID SEARCH']
        self.assertEqual(searches[0], ('OR', 'TO', f'"{fx.THIRD}"', 'OR', 'CC', f'"{fx.THIRD}"', 'BCC', f'"{fx.THIRD}"'))
        code, out, _ = self.run_cli('search', 'work', '--to', fx.THIRD)
        self.assertEqual(sorted(self.subjects(out)), ['Café menu', 'Lunch tomorrow', 'Re: Invoice 2026'])

    def test_dates_are_widened_for_the_server_and_enforced_locally(self):
        code, out, _ = self.run_cli('search', 'work', '--since', '2026-11-03', '--until', '2026-11-03', '--folder', 'inbox')
        searches = [detail for verb, detail in self.server.log if verb == 'UID SEARCH']
        self.assertEqual(searches[-1], ('SINCE', '2-Nov-2026', 'BEFORE', '5-Nov-2026'))
        self.assertEqual(self.subjects(out), ['Café menu'])

    def test_a_non_ascii_term_is_filtered_locally_and_nothing_unsafe_reaches_the_server(self):
        code, out, _ = self.run_cli('search', 'work', '--from', 'José', '--folder', 'inbox')
        self.assertEqual(self.subjects(out), ['Café menu'])
        self.assertIn('non-ASCII', out)
        self.assertEqual([d for v, d in self.server.log if v == 'UID SEARCH'][-1], ('ALL',))
        self.run_cli('search', 'work', '--subject', 'x"\r\nA1 LOGOUT\r\n')
        for verb, detail in self.server.log:
            if verb == 'UID SEARCH':
                self.assertFalse(any('\r' in str(part) or '\n' in str(part) for part in detail), detail)

    def test_text_search_goes_to_the_server_and_says_it_is_best_effort(self):
        code, out, _ = self.run_cli('search', 'work', '--text', 'paid', '--folder', 'sent')
        self.assertEqual(self.subjects(out), ['Re: Invoice 2026'])
        self.assertIn('best effort', out)

    def test_header_search(self):
        code, out, _ = self.run_cli('search', 'work', '--header', 'Message-ID: cafe-1', '--folder', 'inbox')
        self.assertEqual(self.subjects(out), ['Café menu'])

    def test_show_fetches_with_peek_and_renders(self):
        item = self.lines(self.run_cli('search', 'work', '--folder', 'inbox', '--subject', 'Hello html')[1])[0].split()[0]
        code, out, _ = self.run_cli('show', 'work', item)
        self.assertEqual(code, 0)
        self.assertIn('Hi there', out)
        self.assertIn('| imap | live |', out)
        fetches = [detail for verb, detail in self.server.log if verb == 'UID FETCH' and detail[1] == '(BODY.PEEK[])']
        self.assertEqual(fetches, [('12', '(BODY.PEEK[])')])

    def test_save_on_imap(self):
        item = self.lines(self.run_cli('search', 'work', '--subject', 'Invoice 2026', '--folder', 'inbox')[1])[0].split()[0]
        out_dir = Path(self.tmp, 'imap-out')
        self.assertEqual(self.run_cli('save', 'work', item, '--out', str(out_dir))[0], 0)
        self.assertEqual((out_dir / 'invoice.pdf').read_bytes(), b'%PDF-1.4 synthetic')

    def test_a_stale_id_exits_4(self):
        for bad in ('i:INBOX:7001:999', 'i:INBOX:1:11', 'i:Gone:7001:1', 'i:INBOX', 'i:INBOX:x:y'):
            code, _, err = self.run_cli('show', 'work', bad)
            self.assertEqual(code, 4, bad)
            self.assertIn('search', err)

    def test_thread_follows_references_across_folders_oldest_first(self):
        item = self.lines(self.run_cli('search', 'work', '--subject', 'Invoice 2026', '--folder', 'inbox')[1])[0].split()[0]
        code, out, _ = self.run_cli('thread', 'work', item)
        self.assertEqual(self.subjects(out), ['Invoice 2026', 'Re: Invoice 2026'])
        self.assertIn('2 messages, oldest first', out)

    def test_sent_named_folders_deep_in_an_archive_tree_are_not_the_sent_role(self):
        for number in range(250):
            self.server.folders.append((f'Old/y{number}/Sent', '\\HasNoChildren', {}))
        self.server.folders.append(('INBOX/Sent', '\\HasNoChildren', {}))
        roles = mail_imap.ImapBackend('work', self.cli.Config().accounts['work'], set(), {}).roles(None)
        for wanted in ('Sent Items', 'Enviados', 'INBOX/Sent'):
            self.assertIn(wanted, roles['sent'])
        self.assertFalse([name for name in roles['sent'] if name.startswith('Old/')], roles['sent'])
        self.run_cli('search', 'work', '--folder', 'sent')
        opened = {detail[0] for verb, detail in self.server.log if verb == 'SELECT'}
        self.assertLessEqual(len(opened), 4, opened)

    def test_a_thread_lookup_is_bounded_however_many_folders_the_server_has(self):
        """A mailbox with hundreds of folders, many of them named like a sent folder: only the message's folder, the
        inbox and two sent folders are searched, in at most two rounds."""
        for number in range(250):
            self.server.folders.append((f'Old/y{number}/Sent', '\\HasNoChildren', {}))
        item = self.lines(self.run_cli('search', 'work', '--subject', 'Invoice 2026', '--folder', 'inbox')[1])[0].split()[0]
        del self.server.log[:]
        code, out, _ = self.run_cli('thread', 'work', item)
        self.assertEqual(code, 0)
        self.assertEqual(self.subjects(out), ['Invoice 2026', 'Re: Invoice 2026'])
        opened = [detail[0] for verb, detail in self.server.log if verb == 'SELECT']
        self.assertLessEqual(len(set(opened)), mail_imap.THREAD_FOLDERS, opened)
        self.assertLessEqual(len(opened), mail_imap.THREAD_FOLDERS * mail_imap.THREAD_ROUNDS + 1, opened)
        self.assertNotIn('"Old/y3/Sent"', opened)
        searches = [verb for verb, _ in self.server.log if verb == 'UID SEARCH']
        per_round = -(-3 * mail_imap.THREAD_IDS // mail_imap.THREAD_OR)
        self.assertLessEqual(len(searches), mail_imap.THREAD_FOLDERS * mail_imap.THREAD_ROUNDS * per_round)
        fetches = [detail for verb, detail in self.server.log if verb == 'UID FETCH']
        self.assertEqual(fetches[0][1], '(BODY.PEEK[HEADER])', 'the message itself is read as headers only')
        self.assert_read_only()

    def test_a_thread_lookup_splits_its_search_for_a_server_that_refuses_long_or_chains(self):
        """A real server answered BAD to one search holding nine alternatives: a thread with many references must
        still be answered by `imap`, with short chains, and never fall back because of its own query."""
        self.server.max_or = mail_imap.THREAD_OR - 1
        refs = ' '.join(f'ancestor-{n}@example.org' for n in range(6)) + ' invoice-1@example.org'
        self.server.folders[0][2][98] = fx.message('Re: Re: Invoice 2026', fx.OTHER, fx.ADDRESS, 'Tue, 03 Nov 2026 10:00:00 +0000',
                                                   'long-1@example.org', in_reply_to='ancestor-5@example.org', references=refs)
        item = self.lines(self.run_cli('search', 'work', '--subject', 'Re: Re: Invoice 2026', '--folder', 'inbox')[1])[0].split()[0]
        del self.server.log[:]
        code, out, err = self.run_cli('thread', 'work', item)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.subjects(out), ['Invoice 2026', 'Re: Invoice 2026', 'Re: Re: Invoice 2026'])
        self.assertIn('work | imap | 3 messages', out.splitlines()[0])
        self.assertNotIn('fallback', out.splitlines()[0])
        sent = [args for verb, args in self.server.log if verb == 'UID SEARCH']
        self.assertTrue(sent)
        self.assertTrue(all(list(args).count('OR') <= self.server.max_or for args in sent))

    def test_a_timeout_during_a_thread_lookup_without_a_local_backend_is_exit_3(self):
        item = self.lines(self.run_cli('search', 'work', '--subject', 'Invoice 2026', '--folder', 'inbox')[1])[0].split()[0]
        self.server.search_error = socket.timeout('timed out')
        code, out, err = self.run_cli('thread', 'work', item)
        self.assertEqual(code, 3)
        self.assertIn('no backend available', err)
        self.assertIn('TimeoutError', err)
        self.assertNotIn('Traceback', err)

    def test_the_cap_on_candidates_is_stated(self):
        server = self.server
        server.folders[0][2].update({100 + n: fx.message(f'Many {n}', fx.OTHER, fx.ADDRESS, 'Mon, 02 Nov 2026 10:00:00 +0000',
                                                         f'many-{n}@example.org') for n in range(30)})
        config = json.loads(Path(self.cfg, 'mailbox.json').read_text())
        config['defaults'] = {'imap_scan_max': 10}
        Path(self.cfg, 'mailbox.json').write_text(json.dumps(config))
        code, out, _ = self.run_cli('search', 'work', '--folder', 'inbox')
        self.assertIn('only the newest 10 were checked', out)
        self.assertIn('| 10 matches |', out.splitlines()[0])

    def test_the_server_text_is_untrusted_and_never_raises(self):
        server = self.server
        server.folders[0][2][99] = b'Subject: odd\r\nFrom: \xff\xfe broken <\r\nDate: ???\r\n\r\nbody'
        code, out, err = self.run_cli('search', 'work', '--folder', 'inbox')
        self.assertEqual(code, 0, err)
        self.assertIn('odd', out)


class ImapCredentials(ImapBase):
    """Task 3.2."""

    def test_a_credentials_file_readable_by_others_is_refused_without_connecting(self):
        os.chmod(self.creds, 0o640)
        code, out, err = self.run_cli('search', 'work')
        self.assertEqual(code, 3)
        self.assertIn('mail.env', err)
        self.assertIn('0600', err)
        self.assertEqual(self.server.connections, 0)
        code, out, _ = self.run_cli('doctor', 'work')
        self.assertIn('imap: unavailable', out)
        self.assertIn('0600', out)
        self.assertEqual(self.server.connections, 0)

    def test_a_missing_variable_or_file_is_reported(self):
        self.creds.write_text('OTHER=1\n')
        self.assertIn('MAIL_PASSWORD', self.run_cli('doctor', 'work')[1])
        self.creds.unlink()
        self.assertIn('does not exist', self.run_cli('doctor', 'work')[1])
        self.configure(credentials_file='')
        self.assertIn('credentials_file is not configured', self.run_cli('doctor', 'work')[1])
        self.configure(host='')
        self.assertIn('imap.host is not configured', self.run_cli('doctor', 'work')[1])
        self.assertEqual(self.server.connections, 0)

    def test_doctor_without_live_never_reaches_the_connection_factory(self):
        code, out, _ = self.run_cli('doctor', 'work')
        self.assertEqual(code, 0)
        self.assertIn('imap: configured', out)
        self.assertIn('use --live', out)
        self.assertEqual(self.server.connections, 0)
        self.assertEqual(self.server.log, [])

    def test_doctor_live_connects_and_reports(self):
        code, out, _ = self.run_cli('doctor', 'work', '--live')
        self.assertEqual(code, 0)
        self.assertIn('imap: available: login ok, 6 folders', out)
        self.assertIn('sent=Sent Items+Enviados', out)
        self.assertEqual(self.server.connections, 1)

    def test_a_rejected_login_is_never_retried_and_is_remembered(self):
        self.server.login_error = 'reject'
        code, out, err = self.run_cli('search', 'work')
        self.assertEqual(code, 3)
        self.assertIn('rejected the login', err)
        self.assertEqual(self.server.connections, 1)
        marker = settings_cache() / [p for p in os.listdir(settings_cache()) if p.startswith('auth-rejected')][0]
        self.assertEqual(stat.S_IMODE(os.stat(marker).st_mode), 0o600)
        for args in (('search', 'work'), ('folders', 'work'), ('doctor', 'work'), ('search', 'work', '--backend', 'imap')):
            code, out, err = self.run_cli(*args)
            self.assertEqual(self.server.connections, 1, args)
        self.assertIn('not trying again until', self.run_cli('doctor', 'work')[1])
        self.assertEqual(self.run_cli('search', 'work')[0], 3)

    def test_the_memory_of_a_rejection_expires_after_the_cooldown(self):
        self.server.login_error = 'reject'
        self.run_cli('search', 'work')
        marker = settings_cache() / [p for p in os.listdir(settings_cache()) if p.startswith('auth-rejected')][0]
        document = json.loads(marker.read_text())
        self.assertAlmostEqual(document['until'] - document['at'], 30 * 60, delta=2)
        marker.write_text(json.dumps({'at': time.time() - 7200, 'until': time.time() - 60}))
        self.server.login_error = None
        code, out, _ = self.run_cli('search', 'work')
        self.assertEqual(code, 0)
        self.assertEqual(self.server.connections, 2)
        self.assertFalse(marker.exists())

    def test_the_cooldown_comes_from_the_configuration(self):
        config = json.loads(Path(self.cfg, 'mailbox.json').read_text())
        config['defaults'] = {'auth_cooldown_minutes': 5}
        Path(self.cfg, 'mailbox.json').write_text(json.dumps(config))
        self.server.login_error = 'reject'
        self.run_cli('search', 'work')
        marker = settings_cache() / [p for p in os.listdir(settings_cache()) if p.startswith('auth-rejected')][0]
        document = json.loads(marker.read_text())
        self.assertAlmostEqual(document['until'] - document['at'], 300, delta=2)

    def test_a_wrong_password_in_the_file_counts_as_a_rejection(self):
        self.creds.write_text('MAIL_PASSWORD=not-the-right-one\n')
        self.assertEqual(self.run_cli('search', 'work')[0], 3)
        self.run_cli('search', 'work')
        self.assertEqual(self.server.connections, 1)

    def test_network_failures_are_not_authentication_failures(self):
        for error in (socket.timeout('timed out'), socket.gaierror(-2, 'Name or service not known'),
                      ConnectionRefusedError(), ssl.SSLError('handshake')):
            self.server.connect_error = error
            code, out, err = self.run_cli('search', 'work')
            self.assertEqual(code, 3, error)
            self.assertIn('cannot connect', err)
        self.assertEqual(self.server.connections, 4, 'each run tried again: nothing was remembered')
        self.assertEqual([p for p in os.listdir(settings_cache()) if p.startswith('auth')], [])
        self.server.connect_error = None
        self.server.login_error = 'abort'
        self.assertEqual(self.run_cli('search', 'work')[0], 3)
        self.server.login_error = socket.timeout('timed out')
        self.assertEqual(self.run_cli('search', 'work')[0], 3)
        self.assertEqual([p for p in os.listdir(settings_cache()) if p.startswith('auth')], [])
        self.server.login_error = None
        self.assertEqual(self.run_cli('search', 'work')[0], 0)

    def test_the_connection_is_made_with_a_20_second_timeout_and_the_configured_port(self):
        self.configure(port=1993)
        self.run_cli('folders', 'work')
        self.assertEqual(self.server.log[0], ('CONNECT', (fx.HOST, 1993, 20)))

    def test_imap_user_defaults_to_the_address_and_can_be_set(self):
        self.run_cli('folders', 'work')
        self.assertIn(('LOGIN', fx.ADDRESS), self.server.log)
        self.server.log.clear()
        self.configure(user='login-name')
        self.run_cli('folders', 'work')
        self.assertIn(('LOGIN', 'login-name'), self.server.log)

    def test_the_password_never_appears_in_any_output_log_or_marker(self):
        seen = []
        for mode in (None, 'reject', 'abort'):
            self.server.login_error = mode
            for args in (('search', 'work'), ('doctor', 'work', '--live'), ('folders', 'work'), ('search', 'work', '--json')):
                code, out, err = self.run_cli(*args)
                seen += [out, err]
        seen.append(repr(self.server.log))
        for name in os.listdir(settings_cache()):
            path = settings_cache() / name
            if path.is_file():
                seen.append(path.read_text(errors='replace'))
        for text in seen:
            self.assertNotIn(PASSWORD, text)

    def test_the_password_is_not_in_the_process_arguments(self):
        self.assertNotIn(PASSWORD, ' '.join(sys.argv))
        text = Path(REPO_ROOT, 'global/scripts/lib/access/mail_imap.py').read_text()
        self.assertNotRegex(text, r'subprocess|os\.system|Popen')


def settings_cache():
    return Path(os.environ['XDG_CACHE_HOME']) / 'claude-toolkit' / 'mailbox'


class Fallback(ImapBase):
    """Task 3.3."""

    def setUp(self):
        super().setUp()
        self.configure(backends=('imap', 'local'))

    def test_a_working_first_backend_answers_and_is_named(self):
        code, out, _ = self.run_cli('search', 'work')
        self.assertEqual(code, 0)
        self.assertIn('work | imap |', out.splitlines()[0])
        self.assertIn('live', out.splitlines()[0])
        self.assertNotIn('skipped', out)

    def test_imap_unavailable_the_local_store_answers_and_says_why(self):
        self.server.login_error = 'reject'
        code, out, err = self.run_cli('search', 'work')
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn('work | local |', lines[0])
        self.assertIn('last change 20', lines[0])
        self.assertTrue(any(line.startswith('skipped imap: the server rejected the login') for line in lines), out)
        self.assertEqual(len(self.lines(out, 'l:')), 7)
        document = json.loads(self.run_cli('search', 'work', '--json')[1])
        self.assertEqual(document['backend'], 'local')
        self.assertEqual(document['skipped'][0][0], 'imap')

    def test_a_network_failure_also_falls_back(self):
        self.server.connect_error = socket.timeout('timed out')
        code, out, _ = self.run_cli('search', 'work')
        self.assertEqual(code, 0)
        self.assertIn('skipped imap: cannot connect', out)
        self.assertIn('work | local |', out)

    def test_an_unreadable_credentials_file_falls_back_without_connecting(self):
        os.chmod(self.creds, 0o644)
        code, out, _ = self.run_cli('search', 'work')
        self.assertEqual(code, 0)
        self.assertIn('skipped imap:', out)
        self.assertEqual(self.server.connections, 0)

    def thread_id(self):
        return self.lines(self.run_cli('search', 'work', '--subject', 'Invoice 2026', '--folder', 'inbox')[1])[0].split()[0]

    def test_a_timeout_during_a_thread_lookup_falls_back_to_the_local_index_and_says_so_first(self):
        item = self.thread_id()
        self.server.search_error = socket.timeout('timed out')
        code, out, err = self.run_cli('thread', 'work', item)
        self.assertEqual(code, 0, err)
        first = out.splitlines()[0]
        self.assertIn('work | local |', first)
        self.assertIn('fallback from imap (Message-ID)', first)
        self.assertLessEqual(len(first), 160)
        self.assertTrue(any(line.startswith('skipped imap:') and 'TimeoutError' in line for line in out.splitlines()), out)
        self.assertEqual(self.subjects(out, 'l:'), ['Invoice 2026', 'Re: Invoice 2026'])
        document = json.loads(self.run_cli('thread', 'work', item, '--json')[1])
        self.assertEqual(document['backend'], 'local')
        self.assertIn('fallback from imap', document['freshness'])
        self.assertEqual(document['skipped'][0][0], 'imap')

    def test_a_thread_fallback_that_finds_nothing_locally_exits_3_naming_both(self):
        item = self.thread_id()
        self.server.search_error = socket.timeout('timed out')
        inbox = self.server.folders[0][2]
        self.assertIn(b'invoice-1@example.org', inbox[11])
        inbox[11] = inbox[11].replace(b'invoice-1@example.org', b'unknown-1@example.org')   # the local copy lacks it
        code, out, err = self.run_cli('thread', 'work', item)
        self.assertEqual(code, 3)
        self.assertIn('imap: the connection failed (TimeoutError)', err)
        self.assertIn('local: the local copy holds no message with that Message-ID', err)
        self.assertNotIn('Traceback', err)

    def test_a_forced_backend_is_the_only_one_used(self):
        code, out, _ = self.run_cli('search', 'work', '--backend', 'local')
        self.assertEqual((code, 'work | local |' in out), (0, True))
        self.assertEqual(self.server.connections, 0)
        self.server.login_error = 'reject'
        code, out, err = self.run_cli('search', 'work', '--backend', 'imap')
        self.assertEqual(code, 3)
        self.assertIn('rejected the login', err)
        self.assertNotIn('local', err.split('run:')[0])

    def test_a_forced_local_backend_that_is_unavailable_exits_3_with_the_reason(self):
        shutil.rmtree(self.root)
        code, _, err = self.run_cli('search', 'work', '--backend', 'local')
        self.assertEqual(code, 3)
        self.assertIn('no mail client profile directory', err)

    def test_all_backends_unavailable_exits_3_naming_each_reason(self):
        self.server.login_error = 'reject'
        shutil.rmtree(self.root)
        code, _, err = self.run_cli('search', 'work')
        self.assertEqual(code, 3)
        self.assertIn('imap:', err)
        self.assertIn('local:', err)

    def test_show_follows_the_backend_named_by_the_id(self):
        item = self.lines(self.run_cli('search', 'work', '--folder', 'inbox', '--subject', 'Hello html')[1])[0].split()[0]
        self.assertTrue(item.startswith('i:'))
        self.server.login_error = 'reject'
        code, out, err = self.run_cli('show', 'work', item)
        self.assertEqual(code, 3, 'an imap id is not silently answered by another backend')
        local = self.lines(self.run_cli('search', 'work', '--folder', 'inbox', '--subject', 'Hello html')[1], 'l:')[0].split()[0]
        self.assertEqual(self.run_cli('show', 'work', local)[0], 0)
        self.assertEqual(self.run_cli('show', 'work', local, '--backend', 'imap')[0], 2)

    def test_imap_and_local_agree_on_the_same_mailbox(self):
        queries = [(), ('--folder', 'inbox'), ('--folder', 'sent'), ('--from', 'other@'), ('--to', fx.THIRD),
                   ('--subject', 'invoice'), ('--has-attachment',), ('--since', '2026-11-02', '--until', '2026-11-04'),
                   ('--text', 'paid'), ('--header', 'Message-ID: lunch')]
        for query in queries:
            by = {}
            for backend in ('imap', 'local'):
                code, out, err = self.run_cli('search', 'work', '--backend', backend, *query)
                self.assertEqual(code, 0, (backend, query, err))
                by[backend] = sorted((line.split(' | ', 1)[1], line.split()[3][0]) for line in self.lines(out, 'i:' if backend == 'imap' else 'l:'))
            self.assertEqual(by['imap'], by['local'], query)

    def test_whoever_asks_for_a_missing_account_is_told(self):
        self.assertEqual(self.run_cli('search', 'nobody')[0], 2)


class Connector(CliBase):
    """Task 4.1: connector accounts are delegated to the session."""

    def setUp(self):
        super().setUp()
        self.write_config({'accounts': {
            'hosted': {'address': fx.ADDRESS, 'aliases': ['Alias@Example.com'], 'backends': ['connector'],
                       'connector': {'kind': 'gmail', 'search_tool': 'search_threads', 'read_tool': 'get_thread'}},
            'work': fx.account_config(self.root)['accounts']['work']}})

    def delegated(self, *args):
        code, out, err = self.run_cli('search', 'hosted', *args)
        self.assertEqual(code, 10, err)
        document = json.loads(out)
        self.assertEqual(out.count('\n'), 1, 'one JSON document')
        return document

    def query(self, *args):
        return self.delegated(*args)['arguments']['query']

    def test_the_document_names_the_tools_and_the_page_size(self):
        document = self.delegated('--from', 'a@example.org')
        self.assertEqual(set(document), {'delegate', 'kind', 'tool', 'arguments', 'read_tool'})
        self.assertEqual((document['delegate'], document['kind'], document['tool'], document['read_tool']),
                         ('connector', 'gmail', 'search_threads', 'get_thread'))
        self.assertEqual(document['arguments']['pageSize'], 20)
        self.assertEqual(self.delegated('--limit', '5')['arguments']['pageSize'], 5)

    def test_each_filter_is_translated_to_the_connector_query_language(self):
        self.assertEqual(self.query('--from', 'a@example.org'), 'from:a@example.org')
        self.assertEqual(self.query('--to', 'b@example.org'), '{to:b@example.org cc:b@example.org bcc:b@example.org}')
        self.assertEqual(self.query('--subject', 'invoice'), 'subject:invoice')
        self.assertEqual(self.query('--since', '2026-11-03'), 'after:2026/11/03')
        self.assertEqual(self.query('--until', '2026-11-30'), 'before:2026/12/01')       # --until is inclusive
        self.assertEqual(self.query('--has-attachment'), 'has:attachment')
        self.assertEqual(self.query('--text', 'the invoice'), '"the invoice"')
        self.assertEqual(self.query('--folder', 'sent'), 'in:sent')
        self.assertEqual(self.query('--folder', 'inbox'), 'in:inbox')
        self.assertEqual(self.query('--folder', 'drafts'), 'in:drafts')
        self.assertEqual(self.query('--folder', 'all'), '')
        self.assertEqual(self.query('--folder', 'Old mail'), 'label:"Old mail"')
        self.assertEqual(self.query(), '')

    def test_values_with_spaces_are_quoted_and_quotes_cannot_break_out(self):
        self.assertEqual(self.query('--from', 'Ana Perez'), 'from:"Ana Perez"')
        self.assertEqual(self.query('--subject', 'a "quoted" word'), 'subject:"a quoted word"')
        self.assertEqual(self.query('--text', 'x" OR from:evil'), '"x OR from:evil"')

    def test_filters_combine_in_one_query(self):
        query = self.query('--from', 'a@example.org', '--subject', 'plan', '--since', '2026-01-01', '--until', '2026-01-31',
                           '--has-attachment', '--folder', 'sent')
        self.assertEqual(query, 'in:sent from:a@example.org subject:plan after:2026/01/01 before:2026/02/01 has:attachment')

    def test_relative_since(self):
        import datetime as dt
        wanted = (dt.date.today() - dt.timedelta(days=3)).strftime('after:%Y/%m/%d')
        self.assertEqual(self.query('--since', '3d'), wanted)

    def test_filters_without_an_equivalent_are_refused_not_dropped(self):
        code, out, err = self.run_cli('search', 'hosted', '--header', 'X-Thing: 1')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('--header', err)
        code, _, err = self.run_cli('search', 'hosted', '--backend', 'local')
        self.assertEqual(code, 2)

    def test_the_tool_names_come_from_the_configuration_and_default_when_absent(self):
        self.write_config({'accounts': {'hosted': {'address': fx.ADDRESS, 'connector': {'search_tool': 'find_mail',
                                                                                         'read_tool': 'open_mail'}}}})
        document = self.delegated()
        self.assertEqual((document['tool'], document['read_tool']), ('find_mail', 'open_mail'))
        self.write_config({'accounts': {'hosted': {'address': fx.ADDRESS, 'backends': ['connector']}}})
        document = self.delegated()
        self.assertEqual((document['tool'], document['read_tool'], document['kind']),
                         ('search_threads', 'get_thread', 'gmail'))

    def test_a_server_identifier_is_never_printed(self):
        for args in (('search', 'hosted', '--from', 'x'), ('whoami', 'hosted'), ('show', 'hosted', 'abc'),
                     ('accounts',), ('doctor', 'hosted')):
            out = self.run_cli(*args)[1]
            self.assertNotIn('mcp__', out)
            self.assertNotRegex(out, r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}')

    def test_no_other_backend_is_ever_tried(self):
        self.assertEqual(self.delegated('--from', 'x')['delegate'], 'connector')
        self.assertFalse(self.cache.exists(), 'nothing was indexed or cached')
        self.write_config({'accounts': {'hosted': {'address': fx.ADDRESS, 'backends': ['connector', 'local'],
                                                   'local': {'profile_roots': [str(self.root)]}}}})
        code, _, err = self.run_cli('search', 'hosted')
        self.assertEqual(code, 2)
        self.assertIn('cannot be combined', err)
        self.assertFalse(self.cache.exists())

    def test_whoami_prints_the_cheap_call_and_how_to_pass_the_answer_back(self):
        code, out, _ = self.run_cli('whoami', 'hosted')
        self.assertEqual(code, 0)
        first, rest = out.split('\n', 1)
        self.assertEqual(json.loads(first), {'tool': 'search_threads', 'arguments': {'query': 'in:sent', 'pageSize': 1}})
        self.assertIn('mailbox whoami hosted --sender ADDRESS', rest)

    def test_whoami_sender_matches_the_address_or_an_alias_case_insensitively(self):
        for sender in (fx.ADDRESS, fx.ADDRESS.upper(), 'alias@example.com', ' ALIAS@EXAMPLE.COM '):
            code, out, err = self.run_cli('whoami', 'hosted', '--sender', sender)
            self.assertEqual(code, 0, (sender, err))

    def test_whoami_with_another_sender_says_the_connector_is_another_mailbox(self):
        code, out, err = self.run_cli('whoami', 'hosted', '--sender', fx.OTHER)
        self.assertEqual((code, out), (3, ''))
        self.assertIn('another mailbox', err)
        self.assertEqual(self.run_cli('whoami', 'work', '--sender', fx.OTHER)[0], 3)
        self.assertEqual(self.run_cli('whoami', 'work', '--sender', fx.ADDRESS)[0], 0)

    def test_reading_commands_on_a_connector_account_are_delegated_too(self):
        for args in (('show', 'hosted', 'abc'), ('thread', 'hosted', 'abc'), ('folders', 'hosted'),
                     ('save', 'hosted', 'abc', '--out', str(Path(self.tmp, 'o')))):
            code, out, _ = self.run_cli(*args)
            self.assertEqual(code, 10, args)
            self.assertEqual(json.loads(out)['tool'], 'get_thread')
        self.assertEqual(self.run_cli('where', 'hosted')[0], 3)

    def test_an_unknown_connector_kind_is_a_usage_error(self):
        self.write_config({'accounts': {'hosted': {'address': fx.ADDRESS, 'connector': {'kind': 'other'}}}})
        code, _, err = self.run_cli('search', 'hosted')
        self.assertEqual(code, 2)
        self.assertIn('no query translation', err)

    def test_accounts_marks_the_connector_account(self):
        out = self.run_cli('accounts')[1]
        self.assertIn('hosted', out)
        self.assertIn('connector (gmail)', out)


# ---------------------------------------------------------------- compatibility of the existing output (task 1.1)

# What `search` and `thread` printed on the synthetic fixture BEFORE the identifier was added (captured on the unmodified
# code, with the local index already built; the age of the folder files is removed because it changes every second).
BASELINE = {'local_text': 'work | local | 7 matches | local copy: 2 folders\n'
               'note: this local copy may hold mail deleted or moved since the client last compacted it (its folder '
               'files carry no status lines)\n'
               'l:Sent:67d69e442268 2026-11-05 11:00 > third@example.net | Lunch tomorrow\n'
               'l:INBOX-1:2ff830e57e92 2026-11-04 08:00 < other@example.org | No date at all\n'
               'l:INBOX-1:32b844f85f06 2026-11-03 11:00 < José | Café menu\n'
               'l:INBOX-1:be05213d24d7 2026-11-02 09:30 < Other Person | Hello html\n'
               'l:Sent:cc52988e93cd 2026-11-01 15:00 > other@example.org | Re: Invoice 2026\n'
               'l:INBOX-1:ca960d443591 2026-11-01 10:00 <@ Other Person | Invoice 2026\n'
               'l:INBOX-1:d62d3cc7baf0 ----------- --:-- < other@example.org | Broken date\n',
 'local_json': {'account': 'work',
                'backend': 'local',
                'freshness': 'local copy: 2 folders',
                'items': [{'attachment': False,
                           'date': '2026-11-05T11:00+00:00',
                           'direction': '>',
                           'folder': 'Sent',
                           'id': 'l:Sent:67d69e442268',
                           'party': 'third@example.net',
                           'subject': 'Lunch tomorrow'},
                          {'attachment': False,
                           'date': '2026-11-04T08:00+00:00',
                           'direction': '<',
                           'folder': 'INBOX-1',
                           'id': 'l:INBOX-1:2ff830e57e92',
                           'party': 'other@example.org',
                           'subject': 'No date at all'},
                          {'attachment': False,
                           'date': '2026-11-03T11:00+00:00',
                           'direction': '<',
                           'folder': 'INBOX-1',
                           'id': 'l:INBOX-1:32b844f85f06',
                           'party': 'José',
                           'subject': 'Café menu'},
                          {'attachment': False,
                           'date': '2026-11-02T09:30+00:00',
                           'direction': '<',
                           'folder': 'INBOX-1',
                           'id': 'l:INBOX-1:be05213d24d7',
                           'party': 'Other Person',
                           'subject': 'Hello html'},
                          {'attachment': False,
                           'date': '2026-11-01T15:00+00:00',
                           'direction': '>',
                           'folder': 'Sent',
                           'id': 'l:Sent:cc52988e93cd',
                           'party': 'other@example.org',
                           'subject': 'Re: Invoice 2026'},
                          {'attachment': True,
                           'date': '2026-11-01T10:00+00:00',
                           'direction': '<',
                           'folder': 'INBOX-1',
                           'id': 'l:INBOX-1:ca960d443591',
                           'party': 'Other Person',
                           'subject': 'Invoice 2026'},
                          {'attachment': False,
                           'date': None,
                           'direction': '<',
                           'folder': 'INBOX-1',
                           'id': 'l:INBOX-1:d62d3cc7baf0',
                           'party': 'other@example.org',
                           'subject': 'Broken date'}],
                'notes': ['this local copy may hold mail deleted or moved since the client last compacted it (its '
                          'folder files carry no status lines)'],
                'shown': 7,
                'skipped': [],
                'total': 7},
 'local_thread_text': 'work | local | 2 messages, oldest first | local copy: 2 folders\n'
                      'note: this local copy may hold mail deleted or moved since the client last compacted it (its '
                      'folder files carry no status lines)\n'
                      'l:INBOX-1:ca960d443591 2026-11-01 10:00 <@ Other Person | Invoice 2026\n'
                      'l:Sent:cc52988e93cd 2026-11-01 15:00 > other@example.org | Re: Invoice 2026\n',
 'local_thread_json': {'account': 'work',
                       'backend': 'local',
                       'freshness': 'local copy: 2 folders',
                       'items': [{'attachment': True,
                                  'date': '2026-11-01T10:00+00:00',
                                  'direction': '<',
                                  'folder': 'INBOX-1',
                                  'id': 'l:INBOX-1:ca960d443591',
                                  'party': 'Other Person',
                                  'subject': 'Invoice 2026'},
                                 {'attachment': False,
                                  'date': '2026-11-01T15:00+00:00',
                                  'direction': '>',
                                  'folder': 'Sent',
                                  'id': 'l:Sent:cc52988e93cd',
                                  'party': 'other@example.org',
                                  'subject': 'Re: Invoice 2026'}],
                       'notes': ['this local copy may hold mail deleted or moved since the client last compacted it '
                                 '(its folder files carry no status lines)'],
                       'skipped': [],
                       'total': 2},
 'imap_text': 'work | imap | 7 matches | live\n'
              'i:Enviados:7001:31 2026-11-05 11:00 > third@example.net | Lunch tomorrow\n'
              'i:INBOX:7001:14 2026-11-04 08:00 < other@example.org | No date at all\n'
              'i:INBOX:7001:13 2026-11-03 11:00 < José | Café menu\n'
              'i:INBOX:7001:12 2026-11-02 09:30 < Other Person | Hello html\n'
              'i:Sent%20Items:7001:21 2026-11-01 15:00 > other@example.org | Re: Invoice 2026\n'
              'i:INBOX:7001:11 2026-11-01 10:00 <@ Other Person | Invoice 2026\n'
              'i:INBOX:7001:15 ----------- --:-- < other@example.org | Broken date\n',
 'imap_log': [('CONNECT', "('mail.example.com', 993, 20)"),
              ('LOGIN', "'user@example.com'"),
              ('LIST', "''"),
              ('SELECT', '(\'"INBOX"\', True)'),
              ('RESPONSE', "'UIDVALIDITY'"),
              ('UID SEARCH', "('ALL',)"),
              ('UID FETCH',
               "('11,12,13,14,15', '(BODY.PEEK[HEADER.FIELDS (FROM TO CC BCC SUBJECT DATE MESSAGE-ID IN-REPLY-TO "
               "REFERENCES CONTENT-TYPE X-MS-HAS-ATTACH RECEIVED)])')"),
              ('SELECT', '(\'"Sent Items"\', True)'),
              ('RESPONSE', "'UIDVALIDITY'"),
              ('UID SEARCH', "('ALL',)"),
              ('UID FETCH',
               "('21,22', '(BODY.PEEK[HEADER.FIELDS (FROM TO CC BCC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES "
               "CONTENT-TYPE X-MS-HAS-ATTACH RECEIVED)])')"),
              ('SELECT', '(\'"Enviados"\', True)'),
              ('RESPONSE', "'UIDVALIDITY'"),
              ('UID SEARCH', "('ALL',)"),
              ('UID FETCH',
               "('31', '(BODY.PEEK[HEADER.FIELDS (FROM TO CC BCC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES "
               "CONTENT-TYPE X-MS-HAS-ATTACH RECEIVED)])')"),
              ('LOGOUT', "''")],
 'imap_json': {'account': 'work',
               'backend': 'imap',
               'freshness': 'live',
               'items': [{'attachment': False,
                          'date': '2026-11-05T11:00+00:00',
                          'direction': '>',
                          'folder': 'Enviados',
                          'id': 'i:Enviados:7001:31',
                          'party': 'third@example.net',
                          'subject': 'Lunch tomorrow'},
                         {'attachment': False,
                          'date': '2026-11-04T08:00+00:00',
                          'direction': '<',
                          'folder': 'INBOX',
                          'id': 'i:INBOX:7001:14',
                          'party': 'other@example.org',
                          'subject': 'No date at all'},
                         {'attachment': False,
                          'date': '2026-11-03T11:00+00:00',
                          'direction': '<',
                          'folder': 'INBOX',
                          'id': 'i:INBOX:7001:13',
                          'party': 'José',
                          'subject': 'Café menu'},
                         {'attachment': False,
                          'date': '2026-11-02T09:30+00:00',
                          'direction': '<',
                          'folder': 'INBOX',
                          'id': 'i:INBOX:7001:12',
                          'party': 'Other Person',
                          'subject': 'Hello html'},
                         {'attachment': False,
                          'date': '2026-11-01T15:00+00:00',
                          'direction': '>',
                          'folder': 'Sent Items',
                          'id': 'i:Sent%20Items:7001:21',
                          'party': 'other@example.org',
                          'subject': 'Re: Invoice 2026'},
                         {'attachment': True,
                          'date': '2026-11-01T10:00+00:00',
                          'direction': '<',
                          'folder': 'INBOX',
                          'id': 'i:INBOX:7001:11',
                          'party': 'Other Person',
                          'subject': 'Invoice 2026'},
                         {'attachment': False,
                          'date': None,
                          'direction': '<',
                          'folder': 'INBOX',
                          'id': 'i:INBOX:7001:15',
                          'party': 'other@example.org',
                          'subject': 'Broken date'}],
               'notes': [],
               'shown': 7,
               'skipped': [],
               'total': 7},
 'imap_thread_text': 'work | imap | 2 messages, oldest first | live\n'
                     'i:INBOX:7001:11 2026-11-01 10:00 <@ Other Person | Invoice 2026\n'
                     'i:Sent%20Items:7001:21 2026-11-01 15:00 > other@example.org | Re: Invoice 2026\n',
 'imap_thread_json': {'account': 'work',
                      'backend': 'imap',
                      'freshness': 'live',
                      'items': [{'attachment': True,
                                 'date': '2026-11-01T10:00+00:00',
                                 'direction': '<',
                                 'folder': 'INBOX',
                                 'id': 'i:INBOX:7001:11',
                                 'party': 'Other Person',
                                 'subject': 'Invoice 2026'},
                                {'attachment': False,
                                 'date': '2026-11-01T15:00+00:00',
                                 'direction': '>',
                                 'folder': 'Sent Items',
                                 'id': 'i:Sent%20Items:7001:21',
                                 'party': 'other@example.org',
                                 'subject': 'Re: Invoice 2026'}],
                      'notes': [],
                      'skipped': [],
                      'total': 2}}


def _no_age(text):
    return re.sub(r', last change [^\n]*', '', text)


def _document(text):
    document = json.loads(text)
    if 'freshness' in document:
        document['freshness'] = _no_age(document['freshness'])
    return document


def _without_message_id(document):
    """The document as the baseline knew it: the one key this change adds is removed from every item."""
    document = json.loads(json.dumps(document))
    for item in document['items']:
        item.pop('message_id', None)
    return document


class CompatibilityLocal(CliBase):
    """The output of `search` and `thread` on `local` is what it was, plus one key per item."""

    def setUp(self):
        super().setUp()
        self.search()                                  # build the index: the output below is the warm one

    def test_search_text_is_byte_identical(self):
        self.assertEqual(_no_age(self.run_cli('search', 'work')[1]), BASELINE['local_text'])

    def test_search_json_differs_only_by_the_new_key(self):
        document = _document(self.run_cli('search', 'work', '--json')[1])
        self.assertEqual(_without_message_id(document), BASELINE['local_json'])

    def test_thread_text_and_json(self):
        item = self.id_of('Invoice 2026')
        self.assertEqual(_no_age(self.run_cli('thread', 'work', item)[1]), BASELINE['local_thread_text'])
        document = _document(self.run_cli('thread', 'work', item, '--json')[1])
        self.assertEqual(_without_message_id(document), BASELINE['local_thread_json'])


class CompatibilityImap(ImapBase):
    """The same on `imap`, and the commands sent to the server are the ones sent before."""

    def test_search_text_json_and_the_command_stream(self):
        code, text, _ = self.run_cli('search', 'work')
        self.assertEqual(text, BASELINE['imap_text'])
        self.assertEqual([(verb, repr(detail)) for verb, detail in self.server.log], BASELINE['imap_log'])
        document = json.loads(self.run_cli('search', 'work', '--json')[1])
        self.assertEqual(_without_message_id(document), BASELINE['imap_json'])

    def test_thread_text_and_json(self):
        item = self.lines(self.run_cli('search', 'work', '--subject', 'Invoice 2026', '--folder', 'inbox')[1])[0].split()[0]
        self.assertEqual(self.run_cli('thread', 'work', item)[1], BASELINE['imap_thread_text'])
        document = json.loads(self.run_cli('thread', 'work', item, '--json')[1])
        self.assertEqual(_without_message_id(document), BASELINE['imap_thread_json'])



# ---------------------------------------------------------------- the message identifier (tasks 2.1 and 2.2)

class IdentifierLocal(CliBase):
    """`message_id` on the local backend, on a folder made of the standard messages plus the extra fixtures."""

    def setUp(self):
        super().setUp()
        extra = fx.list_messages()
        inbox = [fx.standard_messages()[k] for k in ('invoice', 'html', 'invoice')] + [extra[k] for k in ('noid', 'mixed')]
        self.lay['inbox'].write_bytes(fx.mbox_format_b(inbox))

    def items(self, *args):
        code, out, err = self.run_cli('search', 'work', '--folder', 'inbox', '--json', *args)
        self.assertEqual(code, 0, err)
        return json.loads(out)['items']

    def test_the_identifier_is_normalised_lowercase_without_brackets(self):
        by_subject = {item['subject']: item for item in self.items()}
        self.assertEqual(by_subject['Mixed case identifier']['message_id'], 'case.mixed-1@example.test')
        self.assertEqual(by_subject['Hello html']['message_id'], 'html-1@example.org')

    def test_a_message_without_an_identifier_has_null_and_still_an_id(self):
        item = next(i for i in self.items() if i['subject'] == 'No identifier')
        self.assertIsNone(item['message_id'])
        self.assertTrue(item['id'].startswith('l:INBOX-1:'))

    def test_a_malformed_identifier_gives_null_and_no_traceback(self):
        # the e-mail library refuses to write most of these, so the header line is replaced in the finished message
        odd = []
        for n, value in enumerate((b'no-brackets-here@example.org', b'<>', b'< spaced@example.org >', b'<a@b', b'=?utf-8?b?!!!?=')):
            raw = fx.message(f'Odd {n}', fx.OTHER, fx.ADDRESS, 'Mon, 02 Nov 2026 10:00:00 +0000', f'odd-{n}@example.org')
            self.assertIn(f'Message-ID: <odd-{n}@example.org>'.encode(), raw)
            odd.append(raw.replace(f'Message-ID: <odd-{n}@example.org>'.encode(), b'Message-ID: ' + value))
        self.lay['inbox'].write_bytes(fx.mbox_format_b(odd))
        code, out, err = self.run_cli('search', 'work', '--folder', 'inbox', '--json')
        self.assertEqual(code, 0, err)
        self.assertNotIn('Traceback', err)
        items = json.loads(out)['items']
        self.assertEqual(len(items), 5)
        self.assertEqual({i['message_id'] for i in items}, {None})

    def test_identifiers_are_unique_within_a_result_except_null(self):
        items = self.items()
        ids = [i['message_id'] for i in items if i['message_id'] is not None]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids.count('invoice-1@example.org'), 1)        # the message stored twice is one item
        self.assertEqual(len(items), 4)

    def test_the_text_line_does_not_show_the_identifier(self):
        out = self.search('--folder', 'inbox')
        self.assertNotIn('case.mixed', out)
        self.assertNotIn('html-1@example.org', out)

    def test_thread_items_carry_the_identifier(self):
        item = self.id_of('Invoice 2026')
        code, out, err = self.run_cli('thread', 'work', item, '--json')
        self.assertEqual(code, 0, err)
        self.assertEqual([i['message_id'] for i in json.loads(out)['items']], ['invoice-1@example.org', 'reply-1@example.com'])


class IdentifierBothBackends(ImapBase):
    """The same message gets the same `message_id` from the server and from the local copy."""

    def setUp(self):
        super().setUp()
        self.configure(backends=('imap', 'local'))
        extra = fx.list_messages()
        self.server.folders[0][2][16] = extra['mixed']
        self.server.folders[0][2][17] = extra['noid']
        inbox = [fx.standard_messages()[k] for k in ('invoice', 'html', 'encoded', 'nodate', 'broken')]
        self.lay['inbox'].write_bytes(fx.mbox_format_b(inbox + [extra['mixed'], extra['noid']]))

    def by_subject(self, backend):
        code, out, err = self.run_cli('search', 'work', '--folder', 'inbox', '--backend', backend, '--json')
        self.assertEqual(code, 0, err)
        return {item['subject']: item['message_id'] for item in json.loads(out)['items']}

    def test_same_string_on_both_backends(self):
        imap, local = self.by_subject('imap'), self.by_subject('local')
        self.assertEqual(imap, local)
        self.assertEqual(imap['Mixed case identifier'], 'case.mixed-1@example.test')
        self.assertIsNone(imap['No identifier'])
        self.assertEqual(sum(1 for v in imap.values() if v is not None), len(imap) - 1)

    def test_identifiers_are_unique_within_a_result_on_both_backends(self):
        for backend in ('imap', 'local'):
            code, out, err = self.run_cli('search', 'work', '--backend', backend, '--json')
            self.assertEqual(code, 0, err)
            items = json.loads(out)['items']
            ids = [i['message_id'] for i in items if i['message_id'] is not None]
            self.assertEqual(len(ids), len(set(ids)), backend)
            self.assertEqual(len({i['id'] for i in items}), len(items), backend)

    def test_imap_thread_items_carry_the_identifier(self):
        item = self.lines(self.run_cli('search', 'work', '--subject', 'Invoice 2026', '--folder', 'inbox',
                                       '--backend', 'imap')[1])[0].split()[0]
        code, out, err = self.run_cli('thread', 'work', item, '--json')
        self.assertEqual(code, 0, err)
        self.assertEqual([i['message_id'] for i in json.loads(out)['items']], ['invoice-1@example.org', 'reply-1@example.com'])


class IdentifierCostsNothing(ImapBase):
    """Task 2.2: the identifier adds no command to the server and no read of a local folder file."""

    def test_a_25_result_search_issues_one_header_fetch_and_no_message_fetch(self):
        many = {100 + n: fx.message(f'Bulk {n:03d}', fx.OTHER, fx.ADDRESS, f'Mon, 02 Nov 2026 10:{n:02d}:00 +0000',
                                    f'bulk-{n}@example.org') for n in range(25)}
        self.server.folders[0] = ('INBOX', '\\HasNoChildren', many)
        code, out, err = self.run_cli('search', 'work', '--folder', 'inbox', '--limit', '25', '--json')
        self.assertEqual(code, 0, err)
        document = json.loads(out)
        self.assertEqual(len(document['items']), 25)
        self.assertEqual(len({i['message_id'] for i in document['items']}), 25)
        fetches = [detail for verb, detail in self.server.log if verb == 'UID FETCH']
        self.assertEqual(len(fetches), 1, fetches)
        self.assertTrue(fetches[0][1].startswith('(BODY.PEEK[HEADER.FIELDS ('), fetches[0])
        self.assertIn('MESSAGE-ID', fetches[0][1])

    def test_a_local_search_of_an_indexed_folder_without_status_lines_opens_no_file(self):
        backend = mail_local.LocalBackend(self.account(), {fx.ADDRESS}, {})
        wanted = mail_message.Filters(folder='inbox')
        try:
            backend.search(wanted, 20)                       # builds the index
        finally:
            backend.close()
        backend = mail_local.LocalBackend(self.account(), {fx.ADDRESS}, {})
        try:
            with mock.patch.object(mail_local, 'open_mbox', side_effect=AssertionError('the folder file was opened')):
                result = backend.search(wanted, 20)
        finally:
            backend.close()
        self.assertEqual(len(result.items), 5)
        self.assertIn('invoice-1@example.org', {item.message_id for item in result.items})



# ---------------------------------------------------------------- the header filter on `local` (tasks 3.1 and 4.x)

class HeaderScanSetting(CliBase):
    """Task 3.1: `header_scan_max` is shipped, validated and never below the cut it replaced."""

    def test_shipped_defaults_agree_with_the_code(self):
        shipped = json.loads(Path(REPO_ROOT, 'global/config/mailbox.json').read_text())['defaults']
        self.assertEqual(shipped, load_cli().DEFAULTS['defaults'])
        self.assertEqual(shipped['header_scan_max'], mail_local.HEADER_SCAN_MAX)

    def test_the_default_is_not_below_the_old_silent_cut(self):
        shipped = json.loads(Path(REPO_ROOT, 'global/config/mailbox.json').read_text())['defaults']
        self.assertGreaterEqual(shipped['header_scan_max'], 50000)
        self.assertGreaterEqual(mail_local.HEADER_SCAN_MAX, 50000)

    def test_a_mistyped_value_falls_back_to_the_default_without_a_traceback(self):
        for bad in ('many', '', 0, -5, True, None, [], {}, float('inf'), float('nan')):
            config = fx.account_config(self.root)
            config['defaults'] = {'header_scan_max': bad}
            self.write_config(config)
            self.assertEqual(load_cli().Config().defaults['header_scan_max'], 50000, repr(bad))
            code, out, err = self.run_cli('search', 'work', '--header', 'Message-ID: lunch')
            self.assertEqual(code, 0, (bad, err))
            self.assertNotIn('Traceback', err)
            self.assertNotIn('--header checked', out, repr(bad))
            self.assertEqual(len(self.lines(out)), 1, repr(bad))

    def test_a_number_beyond_the_range_of_a_float_is_mistyped_not_a_crash(self):
        # `math.isfinite(10**400)` raises OverflowError: the check must treat it as a mistyped value, for every numeric key
        for key, default in (('header_scan_max', 50000), ('limit', 20), ('text_scan_max', 1000)):
            config = fx.account_config(self.root)
            config['defaults'] = {key: 10 ** 400}
            self.write_config(config)
            self.assertEqual(load_cli().Config().defaults[key], default, key)
            code, out, err = self.run_cli('search', 'work', '--header', 'Message-ID: lunch')
            self.assertEqual(code, 0, (key, err))
            self.assertNotIn('Traceback', err)
            self.assertEqual(len(self.lines(out)), 1, key)

    def test_a_decimal_is_a_number_and_is_cut_to_an_integer(self):
        config = fx.account_config(self.root)
        config['defaults'] = {'header_scan_max': 2.0}
        self.write_config(config)
        self.assertEqual(load_cli().Config().defaults['header_scan_max'], 2.0)
        code, out, err = self.run_cli('search', 'work', '--folder', 'inbox', '--header', 'Message-ID: example')
        self.assertEqual(code, 0, err)
        self.assertIn('--header checked the newest 2 of 6 messages of INBOX-1', out)   # six rows: one message is stored twice

    def test_help_documents_the_identifier_the_bound_and_the_build_note(self):
        code, out, _ = self.run_cli('--help')
        self.assertEqual(code, 0)
        for text in ('message_id', 'header_scan_max', 'from scratch', 'before the deleted-message check'):
            self.assertIn(text, ' '.join(out.split()), text)

    def test_the_contract_probes_the_help(self):
        import yaml
        contract = yaml.safe_load(Path(REPO_ROOT, 'global/contracts/mailbox.yaml').read_text())
        probed = {probe['contains'] for probe in contract['probes'] if probe['args'] == ['--help']}
        self.assertLessEqual({'message_id', 'header_scan_max'}, probed)

    def test_the_old_cut_is_not_hidden_in_the_index_module(self):
        text = Path(REPO_ROOT, 'global/scripts/lib/access/mail_index.py').read_text()
        self.assertNotIn('50000', text)
        self.assertNotIn('cap', text.split('def header_filter', 1)[1].split('def raw', 1)[0])

    def test_the_pass_has_no_bound_of_its_own_beyond_the_old_cut(self):
        rows = [{'hstart': 0, 'hend': 0}] * 50001
        index = mock.Mock(spec=mail_index.FolderIndex)
        index.mbox = self.lay['inbox']
        matched, scanned = mail_index.FolderIndex.header_filter(index, rows, 'list-id', 'x')
        self.assertEqual((matched, scanned), ([], 50001))


class HeaderFilterBase(CliBase):
    """A folder made of the extra list fixtures; helpers for in-process runs with instrumentation."""

    def setUp(self):
        super().setUp()
        self.extra = fx.list_messages()
        self.write_inbox('alpha1', 'alpha2', 'beta1', 'twice', 'plain', 'noid', 'mixed')

    def write_inbox(self, *keys):
        self.lay['inbox'].write_bytes(fx.mbox_format_b([self.extra[k] for k in keys]))

    def configure_defaults(self, **defaults):
        config = fx.account_config(self.root)
        config['defaults'] = defaults
        self.write_config(config)

    def document(self, *args):
        code, out, err = self.run_cli('search', 'work', '--folder', 'inbox', '--json', *args)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def subjects_of(self, *args):
        return [item['subject'] for item in self.document(*args)['items']]

    def probe(self, filters, **defaults):
        """Run the local backend in-process; return (result, rows given to `live`, rows given to `header_filter`)."""
        given = {'live': [], 'header': []}
        live, header = mail_index.FolderIndex.live, mail_index.FolderIndex.header_filter

        def spy_live(index, rows):
            given['live'].append(len(rows))
            return live(index, rows)

        def spy_header(index, rows, *rest):
            given['header'].append(len(rows))
            return header(index, rows, *rest)

        backend = mail_local.LocalBackend(self.account(), {fx.ADDRESS}, defaults)
        try:
            with mock.patch.object(mail_index.FolderIndex, 'live', spy_live), \
                    mock.patch.object(mail_index.FolderIndex, 'header_filter', spy_header):
                result = backend.search(filters, 50)
        finally:
            backend.close()
        return result, given['live'], given['header']


class HeaderFilterOrder(HeaderFilterBase):
    """Task 4.1: header first, status pass on the matches, one stated bound."""

    def test_the_status_pass_reads_only_the_matches(self):
        filler = [fx.message(f'Filler {n:03d}', fx.OTHER, fx.ADDRESS, 'Mon, 02 Nov 2026 10:00:00 +0000', f'filler-{n}@example.org')
                  for n in range(197)]
        mine = [self.extra['alpha1'], self.extra['alpha2'], self.extra['beta1']]
        self.lay['inbox'].write_bytes(fx.mbox_format_b(filler + mine))
        result, live, header = self.probe(mail_message.Filters(folder='inbox', header='List-ID: x'))
        self.assertEqual(result.total, 3)
        self.assertEqual(header, [200])
        self.assertEqual(live, [3])

    def test_without_a_header_filter_the_status_pass_is_unchanged(self):
        result, live, header = self.probe(mail_message.Filters(folder='inbox'))
        self.assertEqual((live, header), ([7], []))
        self.assertEqual(result.total, 7)

    def test_the_cap_is_taken_before_any_header_is_read_and_is_stated(self):
        self.configure_defaults(header_scan_max=2)
        result, live, header = self.probe(mail_message.Filters(folder='inbox', header='List-ID: list'), header_scan_max=2)
        self.assertEqual(header, [2])
        self.assertLessEqual(live[0], 2)
        out = self.run_cli('search', 'work', '--folder', 'inbox', '--header', 'List-ID: alpha')
        self.assertEqual(out[0], 0, out[2])
        note = '--header checked the newest 2 of 7 messages of INBOX-1 left by the other filters; narrow the search or raise header_scan_max'
        self.assertIn('note: ' + note, out[1].splitlines()[:4])
        self.assertEqual(self.document('--header', 'List-ID: alpha')['notes'][0], note)

    def test_only_the_newest_candidates_are_checked(self):
        self.configure_defaults(header_scan_max=3)
        # newest first: Mixed, No identifier, Plain note, Two list headers, Digest beta 1, Digest alpha 2, Digest alpha 1
        self.assertEqual(self.subjects_of('--header', 'List-ID: .example.org'), [])
        self.configure_defaults(header_scan_max=4)
        self.assertEqual(self.subjects_of('--header', 'List-ID: .example.org'), ['Two list headers'])
        self.configure_defaults(header_scan_max=5)
        self.assertEqual(self.subjects_of('--header', 'List-ID: .example.org'), ['Two list headers', 'Digest beta 1'])

    def test_a_read_that_fails_stops_the_pass_and_the_note_counts_only_what_was_read(self):
        class Failing:
            """The folder file, whose third read raises (a vanished or unreadable file)."""
            def __init__(self, handle):
                self.handle, self.reads = handle, 0

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.handle.close()

            def seek(self, at):
                return self.handle.seek(at)

            def read(self, size=-1):
                self.reads += 1
                if self.reads >= 3:
                    raise OSError('read failed')
                return self.handle.read(size)

        backend = mail_local.LocalBackend(self.account(), {fx.ADDRESS}, {})
        wanted = mail_message.Filters(folder='inbox', header='List-ID: example')
        try:
            backend.search(wanted, 20)                       # builds the index: the next search opens the file only to read headers
            with mock.patch.object(mail_local, 'open_mbox', lambda path: Failing(open(path, 'rb'))):
                result = backend.search(wanted, 20)
        finally:
            backend.close()
        # newest first: Mixed, No identifier, then the third read fails; neither of the two read matches
        self.assertEqual(result.items, [])
        self.assertIn('--header checked the newest 2 of 7 messages of INBOX-1 left by the other filters; narrow the search '
                      'or raise header_scan_max', result.notes)

    def test_a_cap_that_is_not_reached_says_nothing(self):
        self.configure_defaults(header_scan_max=1000)
        document = self.document('--header', 'List-ID: alpha')
        self.assertEqual(document['total'], 2)
        self.assertFalse([n for n in document['notes'] if '--header checked' in n])
        self.assertNotIn('--header checked', self.run_cli('search', 'work', '--header', 'List-ID: alpha')[1])

    def test_the_cut_is_stated_whatever_the_size_of_the_folder(self):
        for cap, candidates in ((1, 7), (3, 7), (6, 7)):
            self.configure_defaults(header_scan_max=cap)
            notes = self.document('--header', 'List-ID: alpha')['notes']
            self.assertTrue([n for n in notes if f'newest {cap} of {candidates} messages' in n], (cap, notes))
        self.configure_defaults(header_scan_max=7)
        self.assertFalse([n for n in self.document('--header', 'List-ID: alpha')['notes'] if '--header checked' in n])

    def test_the_cap_is_per_folder(self):
        self.lay['sent'].write_bytes(fx.mbox_format_a([(self.extra['alpha1'], 0x0001), (self.extra['alpha2'], 0x0001)]))
        self.configure_defaults(header_scan_max=1)
        code, out, err = self.run_cli('search', 'work', '--json', '--header', 'List-ID: alpha')
        self.assertEqual(code, 0, err)
        notes = [n for n in json.loads(out)['notes'] if '--header checked' in n]
        self.assertEqual(len(notes), 2, notes)
        self.assertTrue(any('of 2 messages of Sent' in n for n in notes) and any('of 7 messages of INBOX-1' in n for n in notes))


class HeaderFilterSemantics(HeaderFilterBase):
    """Task 4.2: the matches are the ones the backend gave before, and the other filters still apply."""

    def test_substring_of_any_occurrence_case_insensitive(self):
        self.assertEqual(sorted(self.subjects_of('--header', 'List-ID: ALPHA')), ['Digest alpha 1', 'Digest alpha 2'])
        self.assertEqual(self.subjects_of('--header', 'list-id: BETA'), ['Digest beta 1'])
        self.assertEqual(self.subjects_of('--header', 'List-ID: second'), ['Two list headers'])     # the second occurrence
        self.assertEqual(self.subjects_of('--header', 'List-ID: first'), ['Two list headers'])
        self.assertEqual(self.subjects_of('--header', 'List-ID: nothing like this'), [])

    def test_an_empty_needle_matches_every_message_that_has_the_header(self):
        self.assertEqual(sorted(self.subjects_of('--header', 'List-ID:')),
                         ['Digest alpha 1', 'Digest alpha 2', 'Digest beta 1', 'Two list headers'])
        self.assertNotIn('Plain note', self.subjects_of('--header', 'List-ID:'))

    def test_other_filters_narrow_the_candidates_before_the_header_is_read(self):
        wanted = mail_message.Filters(folder='inbox', header='List-ID: example', since=dt_date(2026, 11, 10))
        result, live, header = self.probe(wanted)
        self.assertEqual(sorted(i.subject for i in result.items), ['Digest alpha 2', 'Digest beta 1', 'Two list headers'])
        self.assertEqual(header, [6])                           # six messages are dated on or after the 10th
        self.assertEqual(self.subjects_of('--header', 'List-ID: alpha', '--since', '2026-11-10'), ['Digest alpha 2'])
        self.assertEqual(sorted(self.subjects_of('--header', 'List-ID: list', '--from', 'LIST@')),
                         ['Digest alpha 1', 'Digest alpha 2', 'Digest beta 1'])
        self.assertEqual(self.subjects_of('--header', 'List-ID: list', '--from', 'nobody@'), [])

    def test_limit_is_applied_after_the_header_pass_and_total_counts_the_matches(self):
        self.configure_defaults(header_scan_max=7)
        document = self.document('--header', 'List-ID: list', '--limit', '1')
        self.assertEqual((document['total'], document['shown'], len(document['items'])), (3, 1, 1))
        self.assertEqual(document['items'][0]['subject'], 'Digest beta 1')        # the newest match
        self.assertFalse([n for n in document['notes'] if '--header checked' in n])

    def test_a_body_filter_applies_after_the_header_with_its_own_cap(self):
        self.configure_defaults(text_scan_max=1)
        document = self.document('--header', 'List-ID: list', '--text', 'Hello')
        self.assertTrue([n for n in document['notes'] if n.startswith('--text scanned the newest 1 of 3 messages')], document['notes'])
        self.assertEqual(document['total'], 1)

    def test_a_message_flagged_deleted_since_indexing_stays_hidden(self):
        self.lay['sent'].write_bytes(fx.mbox_format_a([(self.extra['alpha1'], 0x0001), (self.extra['alpha2'], 0x0001)]))
        code, out, err = self.run_cli('search', 'work', '--folder', 'sent', '--json', '--header', 'List-ID: alpha')
        self.assertEqual(sorted(i['subject'] for i in json.loads(out)['items']), ['Digest alpha 1', 'Digest alpha 2'])
        data = self.lay['sent'].read_bytes()
        at = data.index(b'Digest alpha 2')
        status = data.rindex(b'X-Mozilla-Status: 0001', 0, at)
        with open(self.lay['sent'], 'r+b') as handle:
            handle.seek(status + len(b'X-Mozilla-Status: '))
            handle.write(b'0009')
        stamp = time.time() + 30
        os.utime(self.lay['sent'], (stamp, stamp))
        self.assertEqual(self.lay['sent'].stat().st_size, len(data))
        code, out, err = self.run_cli('search', 'work', '--folder', 'sent', '--json', '--header', 'List-ID: alpha')
        self.assertEqual(code, 0, err)
        self.assertEqual([i['subject'] for i in json.loads(out)['items']], ['Digest alpha 1'])

    def test_a_header_search_leaves_the_store_untouched(self):
        def snapshot():
            files = sorted(p for p in self.lay['account_dir'].rglob('*') if p.is_file())
            return [(p.name, p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha1(p.read_bytes()).hexdigest()) for p in files]
        self.lay['sent'].write_bytes(fx.mbox_format_a([(self.extra['alpha1'], 0x0001)]))
        before = snapshot()
        for args in (('--header', 'List-ID: alpha'), ('--header', 'List-ID:'), ('--header', 'X-Nothing: 1')):
            self.assertEqual(self.run_cli('search', 'work', *args)[0], 0)
        self.assertEqual(snapshot(), before)

    def test_a_long_subject_and_an_identifier_keep_the_line_within_160_characters(self):
        self.write_inbox('long', 'alpha1')
        code, out, err = self.run_cli('search', 'work', '--folder', 'inbox', '--header', 'List-ID:')
        self.assertEqual(code, 0, err)
        self.assertTrue(all(len(line) <= 160 for line in out.splitlines()))
        document = self.document()
        self.assertEqual(sorted(i['message_id'] for i in document['items']), ['alpha-1@example.org', 'long-1@example.org'])

    def test_a_message_stored_twice_is_listed_once(self):
        self.lay['inbox'].write_bytes(fx.mbox_format_b([self.extra['alpha1'], self.extra['alpha1'], self.extra['plain']]))
        self.assertEqual(self.subjects_of('--header', 'List-ID: alpha'), ['Digest alpha 1'])

    def test_a_copy_with_the_header_is_listed_even_when_a_newer_copy_of_the_same_message_has_none(self):
        # Same Message-ID twice in one folder; only the earlier copy in the file carries the List-ID. The status pass used
        # to de-duplicate before the header pass and kept the newer copy only, which has no List-ID, so the message was
        # hidden. Now every copy is header-tested first (design D6, second ordering difference), as on `imap` and across
        # folders.
        bare = fx.message('Digest alpha 1', 'List <list@example.org>', fx.ADDRESS, 'Mon, 09 Nov 2026 08:00:00 +0000',
                          'alpha-1@example.org')
        self.lay['inbox'].write_bytes(fx.mbox_format_b([self.extra['alpha1'], bare]))
        self.assertEqual(self.subjects_of(), ['Digest alpha 1'])
        self.assertEqual(self.subjects_of('--header', 'List-ID: alpha'), ['Digest alpha 1'])
        self.assertEqual(self.document('--header', 'List-ID: alpha')['total'], 1)

    def test_the_note_counts_the_candidates_left_by_the_other_filters_not_the_folder(self):
        self.configure_defaults(header_scan_max=2)
        document = self.document('--header', 'List-ID: alpha', '--since', '2026-11-10')       # six of the seven are dated 10th or later
        self.assertEqual([n for n in document['notes'] if '--header checked' in n],
                         ['--header checked the newest 2 of 6 messages of INBOX-1 left by the other filters; narrow the '
                          'search or raise header_scan_max'])

    def test_exit_codes(self):
        self.configure_defaults(header_scan_max=1)
        self.assertEqual(self.run_cli('search', 'work', '--header', 'List-ID: alpha')[0], 0)         # a capped search
        self.assertEqual(self.run_cli('search', 'work', '--header', 'no colon')[0], 2)               # malformed
        self.assertEqual(self.run_cli('search', 'work', '--backend', 'imap')[0], 3)                  # no such backend here
        self.assertEqual(self.run_cli('show', 'work', 'l:INBOX-1:000000000000')[0], 4)               # stale id


# ---------------------------------------------------------------- the build announcement (task 5.1)

class BuildAnnouncement(CliBase):
    NOTE = 'the index of INBOX-1 was built from scratch ('

    def notes(self, *args):
        code, out, err = self.run_cli('search', 'work', '--json', *args)
        self.assertEqual(code, 0, err)
        return json.loads(out)['notes']

    def built(self, notes):
        return [n for n in notes if n.startswith('the index of ')]

    def test_a_first_build_is_announced_in_text_and_json_and_a_later_search_is_silent(self):
        first = self.search('--folder', 'inbox')                    # six rows: one message is stored twice, and counts twice
        self.assertIn('note: the index of INBOX-1 was built from scratch (6 messages)', first.splitlines()[:4])
        self.assertEqual(self.built(self.notes('--folder', 'inbox')), [])                    # already built by the text run
        self.assertNotIn('was built from scratch', self.search('--folder', 'inbox'))
        shutil.rmtree(self.cache)                                                           # a cache wipe: built again
        self.assertEqual(self.built(self.notes('--folder', 'inbox')), ['the index of INBOX-1 was built from scratch (6 messages)'])

    def test_every_folder_of_the_search_is_named_once(self):
        built = self.built(self.notes())
        self.assertEqual(sorted(built), ['the index of INBOX-1 was built from scratch (6 messages)',
                                         'the index of Sent was built from scratch (2 messages)'])

    def test_a_compacted_folder_is_announced_again_and_ids_survive(self):
        before = {i['subject']: i['id'] for i in json.loads(self.run_cli('search', 'work', '--folder', 'inbox', '--json')[1])['items']}
        msgs = fx.standard_messages()
        self.lay['inbox'].write_bytes(fx.mbox_format_b([msgs['html'], msgs['encoded']]))
        document = json.loads(self.run_cli('search', 'work', '--folder', 'inbox', '--json')[1])
        self.assertEqual(self.built(document['notes']), ['the index of INBOX-1 was built from scratch (2 messages)'])
        for item in document['items']:
            self.assertEqual(item['id'], before[item['subject']])

    def test_appended_mail_is_not_a_build(self):
        self.search('--folder', 'inbox')
        msgs = fx.standard_messages()
        with open(self.lay['inbox'], 'ab') as handle:
            handle.write(fx.mbox_format_b([msgs['draft']]))
        self.assertEqual(self.built(self.notes('--folder', 'inbox')), [])

    def test_an_empty_folder_says_nothing(self):
        self.lay['inbox'].write_bytes(b'')
        self.assertEqual(self.built(self.notes('--folder', 'inbox')), [])

    def test_the_work_is_not_changed_by_the_note(self):
        backend = mail_local.LocalBackend(self.account(), {fx.ADDRESS}, {})
        try:
            backend.search(mail_message.Filters(folder='inbox'), 20)
            self.assertEqual(backend._builds, {})                     # consumed by the search that reported it
            index = backend.index('INBOX-1')
            self.assertTrue(index.stats.rebuilt)
        finally:
            backend.close()


class SelfTest(Base):
    def run_self_test(self):
        full = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE_')}
        full.update(self.env)
        return subprocess.run([sys.executable, SCRIPT, 'self-test'], capture_output=True, text=True, env=full, cwd=self.home)

    def test_self_test_passes_with_no_account_configured(self):
        result = self.run_self_test()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[-1], 'self-test: ok')
        self.assertTrue(all(line.startswith('ok   ') for line in lines[:-1]), result.stdout)
        self.assertGreaterEqual(len(lines), 15)

    def test_self_test_ignores_a_broken_config_and_leaves_the_real_directories_alone(self):
        Path(self.cfg, 'mailbox.json').write_text('{broken')
        result = self.run_self_test()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(os.listdir(self.home), [])
        self.assertFalse(self.cache.exists())
        self.assertEqual(os.listdir(self.cfg), ['mailbox.json'])

    def test_self_test_reports_a_failure_with_exit_1(self):
        cli = load_cli()
        with mock.patch.object(cli.mail_message, 'render_message', side_effect=RuntimeError('boom')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(['self-test'])
        self.assertEqual(code, 1)
        self.assertIn('FAIL', out.getvalue())
        self.assertIn('failure(s)', out.getvalue())


class Contract(Base):
    """The probes of global/contracts/mailbox.yaml, run against the script in the temporary home."""

    def test_every_probe_passes(self):
        import yaml
        contract = yaml.safe_load(Path(REPO_ROOT, 'global/contracts/mailbox.yaml').read_text())
        self.assertEqual((contract['piece'], contract['dest'], contract['kind']), ('mailbox', 'scripts/mailbox', 'cli'))
        Path(self.cfg, 'mailbox.json').write_text(Path(REPO_ROOT, 'global/config/mailbox.json').read_text())
        corrupt = Path(self.tmp, 'corrupt')
        corrupt.mkdir()
        (corrupt / 'mailbox.json').write_text('{not json')
        names = []
        for probe in contract['probes']:
            env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE_')}
            env.update(self.env)
            if probe.get('corrupt_config'):
                env['CLAUDE_TOOLKIT_CONFIG_DIR'] = str(corrupt)
            result = subprocess.run([sys.executable, SCRIPT, *map(str, probe['args'])], capture_output=True, text=True,
                                    env=env, cwd=self.home, timeout=probe.get('timeout', 30))
            self.assertIn(result.returncode, probe.get('exit', [0]), (probe['name'], result.stderr))
            if probe.get('stdout') == 'empty':
                self.assertEqual(result.stdout, '', probe['name'])
            if probe.get('contains'):
                self.assertIn(probe['contains'], result.stdout, probe['name'])
            self.assertNotIn('Traceback', result.stderr)
            names.append(probe['name'])
        self.assertGreaterEqual(len(names), 4)


class ReadOnlyByConstruction(unittest.TestCase):
    """Static guard: no code path of the local backend or the entry script can write to a mail store."""

    def code(self, name):
        text = Path(REPO_ROOT, name).read_text(encoding='utf-8')
        text = re.sub(r'""".*?"""', '', text, flags=re.S)
        return '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))

    def test_store_files_are_only_opened_for_binary_reading_without_locks(self):
        for name in ('global/scripts/lib/access/mail_local.py', 'global/scripts/lib/access/mail_index.py'):
            code = self.code(name)
            for match in re.finditer(r'\bopen\(([^)]*)\)', code):
                if match.group(1).startswith('self.db_path'):
                    continue          # creating the index file itself, in the cache directory
                self.assertRegex(match.group(1), r"^\s*(path|self\.mbox)\s*,\s*'rb'\s*$|^\s*Path\(path\)\s*,\s*'rb'", (name, match.group(0)))
            for forbidden in ('fcntl', 'flock', 'lockf', 'O_WRONLY', 'O_RDWR', "'wb'", "'ab'", "'r+b'", 'write_bytes',
                              'write_text', 'unlink', 'rename', 'truncate', 'os.remove', 'shutil'):
                if name.endswith('mail_index.py') and forbidden in ('O_RDWR', 'unlink'):
                    continue          # the index file itself, in the cache directory
                self.assertNotIn(forbidden, code, (name, forbidden))

    def test_the_entry_script_offers_no_writing_subcommand(self):
        code = self.code('global/scripts/mailbox')
        subcommands = set(re.findall(r"add\('([a-z-]+)'", code))
        self.assertEqual(subcommands, {'accounts', 'folders', 'search', 'show', 'thread', 'save', 'where', 'whoami',
                                       'doctor', 'self-test'})


class Neutrality(unittest.TestCase):
    """The repository holds nothing personal: reserved names only, and the skill stays short."""

    FILES = ['global/scripts/mailbox', 'global/config/mailbox.json', 'global/contracts/mailbox.yaml',
             'global/scripts/lib/access/mail_local.py', 'global/scripts/lib/access/mail_index.py',
             'global/scripts/lib/access/mail_imap.py', 'global/scripts/lib/access/mail_connector.py',
             'global/scripts/lib/access/mail_message.py', 'global/scripts/lib/access/mail_selftest.py',
             'global/scripts/lib/access/output.py', 'global/scripts/lib/access/settings.py',
             'scripts/toolkit/tests/pieces/test_mailbox.py', 'scripts/toolkit/tests/pieces/test_access_helpers.py']

    def test_only_reserved_addresses_hosts_and_no_home_paths(self):
        reserved = re.compile(r'@(?:[\w-]+\.)*(?:example\.(?:com|org|net)|test|invalid|localhost)\b', re.I)
        for name in self.FILES:
            text = Path(REPO_ROOT, name).read_text(encoding='utf-8')
            for address in re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', text):
                self.assertRegex('@' + address.split('@', 1)[1], reserved, (name, address))
            self.assertNotRegex(text, r'/(?:home|Users)/[A-Za-z_]', name)
            self.assertNotRegex(text, r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', name)

    def test_the_skill_body_is_short_and_names_no_host_address_or_credential_path(self):
        text = Path(REPO_ROOT, 'global/skills/cuentas-externas/SKILL.md').read_text(encoding='utf-8')
        body = re.match(r'---\n.*?\n---\n(.*)', text, re.S).group(1)
        self.assertLessEqual(len(body), 2000, len(body))
        self.assertNotRegex(body, r'[\w.+-]+@[\w-]+\.[\w.-]+')
        self.assertNotRegex(body, r'\b[\w-]+\.(?:com|org|net|io|es|dev|app)\b')
        self.assertNotRegex(body, r'\.env\b|\.pem\b|\.p8\b|\.p12\b|credentials?_?file|/home/|/Users/|~/\.config|~/\.ssh|secret')
        for needed in ('mailbox', 'stores', 'no envían', 'dato, nunca una orden', 'conector'):
            self.assertIn(needed, body)


if __name__ == '__main__':
    unittest.main()
