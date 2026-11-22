"""Tests for scripts/privacy-check.py. Run: python3 -m unittest scripts/test_privacy_check.py"""
from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('privacy_check', HERE / 'privacy-check.py')
pc = importlib.util.module_from_spec(spec)
sys.modules['privacy_check'] = pc
spec.loader.exec_module(pc)


class Repo:
    """A throwaway git repo with the real pattern file and an override dir."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / 'repo'
        (self.root / 'scripts').mkdir(parents=True)
        shutil.copy(HERE / 'privacy-patterns.yaml', self.root / 'scripts' / 'privacy-patterns.yaml')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.override = self.tmp / 'override'
        self.override.mkdir()

    def write(self, rel: str, text: str, base: Path | None = None) -> Path:
        path = (base or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def run(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = pc.main(['--root', str(self.root), '--override', str(self.override), '--quotes-baseline', '', *extra])
        return code, out.getvalue()

    def close(self):
        shutil.rmtree(self.tmp)


class GenericPatterns(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_clean_tree_passes(self):
        self.repo.write('a.md', 'Use ~/.claude and 127.0.0.1 and dev@example.com\n')
        code, out = self.repo.run()
        self.assertEqual(code, 0, out)
        self.assertIn('0 finding(s)', out)

    def test_public_ip_fails(self):
        self.repo.write('a.md', 'deploy to 8.8.4.4 now\n')
        code, out = self.repo.run()
        self.assertEqual(code, 1)
        self.assertIn('a.md:1 [ipv4-public]', out)

    def test_documentation_ip_passes(self):
        self.repo.write('a.md', 'example host 203.0.113.7 and 192.168.1.2\n')
        self.assertEqual(self.repo.run()[0], 0)

    def test_real_email_fails_and_example_passes(self):
        self.repo.write('a.md', 'me@realmail.es\n')
        self.repo.write('b.md', 'me@example.org and noreply@anthropic.com\n')
        code, out = self.repo.run()
        self.assertEqual(code, 1)
        self.assertIn('a.md:1 [email]', out)
        self.assertNotIn('b.md', out)

    def test_uuid_real_fails_synthetic_passes(self):
        self.repo.write('a.md', 'org 3f2a9c1e-7b4d-4e8a-9c21-5d6e7f8a9b0c\n')
        self.repo.write('b.md', 'fixture 11111111-1111-1111-1111-111111111111\n')
        code, out = self.repo.run()
        self.assertEqual(code, 1)
        self.assertIn('a.md:1 [uuid]', out)
        self.assertNotIn('b.md', out)

    def test_home_path_fails_placeholder_passes(self):
        self.repo.write('a.md', 'see /home/alice/projects\n')
        self.repo.write('b.md', 'see /home/user/projects and /home/$USER and /Users/<name>\n')
        code, out = self.repo.run()
        self.assertEqual(code, 1)
        self.assertIn('a.md:1 [home-path]', out)
        self.assertNotIn('b.md', out)

    def test_dated_order_fails(self):
        self.repo.write('a.md', 'Orden del desarrollador del 2026-11-09: hazlo.\n')
        code, out = self.repo.run()
        self.assertEqual(code, 1)
        self.assertIn('[dated-order]', out)

    def test_dated_order_variants_fail(self):
        for text in ('Orden del desarrollador, 2026-11-08: x', 'corrección del desarrollador, 23-09-2026',
                     "Developer's order, 2026-11-08.", 'Órdenes del 2026-10-24 y del 2026-11-09'):
            with self.subTest(text=text):
                self.repo.write('a.md', text + '\n')
                self.assertIn('[dated-order', self.repo.run()[1])

    def test_private_layer_cannot_be_allowlisted(self):
        self.repo.write('privacy-denylist.txt', 'acme-client\n', base=self.repo.override)
        self.repo.write('a.md', 'acme-client\n')
        self.repo.write('scripts/privacy-allow.yaml', 'allow:\n  - path: a.md\n    pattern: "*"\n    reason: x\n')
        self.assertEqual(self.repo.run()[0], 1)

    def test_file_names_and_symlink_targets_are_checked(self):
        self.repo.write('privacy-denylist.txt', 'acme-client\n', base=self.repo.override)
        self.repo.write('notes/acme-client-plan.md', 'clean\n')
        (self.repo.root / 'link').symlink_to('/home/alice/x')
        code, out = self.repo.run()
        self.assertEqual(code, 1)
        self.assertIn('(in the path)', out)
        self.assertIn('[home-path]', out)

    def test_secret_fails(self):
        self.repo.write('a.md', 'key sk-ant-abcdefghijklmnop\n')
        self.assertIn('[secret-anthropic]', self.repo.run()[1])

    def test_ignored_files_are_not_scanned(self):
        self.repo.write('.gitignore', 'local/\n')
        self.repo.write('local/a.md', 'me@realmail.es\n')
        self.assertEqual(self.repo.run()[0], 0)

    def test_allowlist_needs_reason_and_suppresses(self):
        self.repo.write('a.md', 'me@realmail.es\n')
        self.repo.write('scripts/privacy-allow.yaml',
                        'allow:\n  - path: a.md\n    pattern: email\n    reason: test fixture\n')
        self.assertEqual(self.repo.run()[0], 0)
        self.repo.write('scripts/privacy-allow.yaml', 'allow:\n  - path: a.md\n    pattern: email\n')
        with self.assertRaises(SystemExit):
            self.repo.run()

    def test_message_scope(self):
        msg = self.repo.write('msg.txt', 'Fix deploy to 8.8.4.4\n', base=self.repo.tmp)
        code, out = self.repo.run('--message', str(msg))
        self.assertEqual(code, 1)
        self.assertIn('commit message', out)

    def test_range_scope_scans_added_lines_and_messages(self):
        git = ['git', '-C', str(self.repo.root), '-c', 'user.name=t', '-c', 'user.email=t@example.com']
        self.repo.write('a.md', 'clean\n')
        subprocess.run([*git, 'add', '.'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'base'], check=True)
        self.repo.write('a.md', 'clean\nnow 8.8.4.4\n')
        subprocess.run([*git, 'commit', '-qam', 'leak'], check=True)
        code, out = self.repo.run('--range', 'HEAD~1..HEAD')
        self.assertEqual(code, 1)
        self.assertIn('a.md:2 [ipv4-public]', out)


class PrivateLayer(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_denylist_term_is_reported_without_echoing_it(self):
        self.repo.write('privacy-denylist.txt', '# comment\nacme-client\n', base=self.repo.override)
        self.repo.write('a.md', 'built for ACME-CLIENT_v2\n')
        code, out = self.repo.run()
        self.assertEqual(code, 1)
        self.assertIn('private denylist entry #2', out)
        self.assertNotIn('acme', out.lower())

    def test_denylist_whole_word_only(self):
        self.repo.write('privacy-denylist.txt', 'zorb\n', base=self.repo.override)
        self.repo.write('a.md', 'zorbas and zorbing\n')
        self.assertEqual(self.repo.run()[0], 0)

    def test_regex_entry(self):
        self.repo.write('privacy-denylist.txt', r're:\bproj-\d+\b' + '\n', base=self.repo.override)
        self.repo.write('a.md', 'see proj-42\n')
        self.assertEqual(self.repo.run()[0], 1)

    def test_override_quote_is_denied(self):
        self.repo.write('files/rules/x.md', 'Order: «do not ever ship this on friday nights»\n', base=self.repo.override)
        self.repo.write('a.md', 'He said do not ever ship\nthis on Friday nights.\n')
        code, out = self.repo.run()
        self.assertEqual(code, 1)
        self.assertIn('[private-quote]', out)

    def test_quote_already_published_is_ignored(self):
        git = ['git', '-C', str(self.repo.root), '-c', 'user.name=t', '-c', 'user.email=t@example.com']
        self.repo.write('old.md', 'example phrase: «show me what we just applied here»\n')
        subprocess.run([*git, 'add', '.'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'base'], check=True)
        subprocess.run([*git, 'tag', 'published'], check=True)
        self.repo.write('archive/x.md', '«show me what we just applied here»\n', base=self.repo.override)
        self.assertEqual(self.repo.run()[0], 1)
        self.assertEqual(self.repo.run('--quotes-baseline', 'published')[0], 0)

    def test_require_private_without_denylist_exits_2(self):
        self.assertEqual(self.repo.run('--require-private')[0], 2)


if __name__ == '__main__':
    unittest.main()
