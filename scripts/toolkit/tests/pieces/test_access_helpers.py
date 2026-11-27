"""Tests of global/scripts/lib/access/output.py and settings.py (shared by `mailbox` and `stores`).

Everything runs in a temporary HOME; the real home, config and cache are never read.
"""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

LIB = str(REPO_ROOT / 'global/scripts/lib')
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from access import output, settings  # noqa: E402


def capture(function, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            function(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return out.getvalue(), err.getvalue(), code


class Output(unittest.TestCase):
    def test_exit_codes_are_the_documented_ones(self):
        self.assertEqual((output.OK, output.ERROR, output.USAGE, output.UNAVAILABLE, output.NOT_FOUND,
                          output.DELEGATED), (0, 1, 2, 3, 4, 10))

    def test_clip_collapses_whitespace_and_cuts_with_an_ellipsis(self):
        self.assertEqual(output.clip('a \n\t b   c'), 'a b c')
        text = output.clip('x' * 500)
        self.assertEqual(len(text), 160)
        self.assertTrue(text.endswith('…'))
        self.assertEqual(output.clip('abcdefghij', 5), 'abcd…')
        self.assertEqual(output.clip('abc', 160), 'abc')

    def test_clip_never_lets_a_control_character_through(self):
        self.assertNotIn('\x1b', output.clip('a\x1b[31mred\x1b[0m'))
        self.assertNotIn('\x07', output.clip('bell\x07'))

    def test_print_items_prints_header_limit_and_the_cut_note(self):
        out, _, _ = capture(output.print_items, [f'line {n}' for n in range(30)], 300, 20, 'head')
        lines = out.splitlines()
        self.assertEqual(lines[0], 'head')
        self.assertEqual(lines[1], 'line 0')
        self.assertEqual(lines[20], 'line 19')
        self.assertEqual(lines[-1], '20 of 300 shown')
        self.assertEqual(len(lines), 22)

    def test_print_items_without_a_cut_has_no_note_and_lines_are_clipped(self):
        out, _, _ = capture(output.print_items, ['y' * 400, 'b'], 2, 20)
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertLessEqual(len(lines[0]), 160)
        self.assertNotIn('shown', out)

    def test_print_json_is_one_compact_sorted_utf8_document(self):
        out, _, _ = capture(output.print_json, {'b': 1, 'a': 'café'})
        self.assertEqual(out, '{"a":"café","b":1}\n')

    def test_fail_writes_one_line_to_stderr_and_exits_with_the_code(self):
        out, err, code = capture(output.fail, 'mailbox', output.USAGE, 'unknown account')
        self.assertEqual((out, err, code), ('', 'mailbox: unknown account\n', 2))


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='access-helpers-')
        self.addCleanup(__import__('shutil').rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, 'home')
        self.cfg = os.path.join(self.tmp, 'cfg')
        os.makedirs(self.home)
        os.makedirs(self.cfg)
        patch = mock.patch.dict(os.environ, {'HOME': self.home, 'CLAUDE_TOOLKIT_CONFIG_DIR': self.cfg,
                                             'XDG_CACHE_HOME': os.path.join(self.tmp, 'cache')})
        patch.start()
        self.addCleanup(patch.stop)

    def write_config(self, text):
        Path(self.cfg, 'demo.json').write_text(text, encoding='utf-8')

    def test_load_without_a_file_gives_the_defaults(self):
        self.assertEqual(settings.load('demo', {'a': 1}), ({'a': 1}, None))

    def test_load_lays_the_file_over_the_defaults(self):
        self.write_config('{"a": 2, "extra": [1]}')
        self.assertEqual(settings.load('demo', {'a': 1, 'b': 3}), ({'a': 2, 'b': 3, 'extra': [1]}, None))

    def test_load_merges_nested_objects_and_keeps_sibling_defaults(self):
        defaults = {'defaults': {'limit': 20, 'body_chars': 1500}, 'accounts': {}, 'list': [1, 2]}
        self.write_config('{"defaults": {"limit": 5}, "accounts": {"w": {"address": "user@example.com"}}, "list": [9]}')
        cfg, problem = settings.load('demo', defaults)
        self.assertIsNone(problem)
        self.assertEqual(cfg['defaults'], {'limit': 5, 'body_chars': 1500})
        self.assertEqual(cfg['accounts'], {'w': {'address': 'user@example.com'}})
        self.assertEqual(cfg['list'], [9])
        self.assertEqual(defaults['defaults']['limit'], 20, 'the caller defaults are not modified')

    def test_load_merges_deeply(self):
        defaults = {'a': {'b': {'c': 1, 'd': 2}, 'e': 3}}
        self.write_config('{"a": {"b": {"c": 9}}}')
        self.assertEqual(settings.load('demo', defaults)[0], {'a': {'b': {'c': 9, 'd': 2}, 'e': 3}})

    def test_a_broken_file_gives_the_defaults_and_one_line_naming_the_file(self):
        for raw in ('{broken', '[]', ''):
            self.write_config(raw)
            cfg, problem = settings.load('demo', {'a': 1})
            self.assertEqual(cfg, {'a': 1})
            self.assertIn('demo.json', problem)
            self.assertNotIn('\n', problem)

    def test_lookup_returns_only_dict_entries(self):
        table = {'w': {'x': 1}, 'bad': 'text'}
        self.assertEqual(settings.lookup(table, 'w'), {'x': 1})
        self.assertIsNone(settings.lookup(table, 'bad'))
        self.assertIsNone(settings.lookup(table, 'none'))
        self.assertIsNone(settings.lookup([], 'w'))

    def test_is_private(self):
        path = os.path.join(self.tmp, 'secret.env')
        Path(path).write_text('X=1\n')
        os.chmod(path, 0o600)
        self.assertEqual(settings.is_private(path), (True, ''))
        os.chmod(path, 0o640)
        ok, reason = settings.is_private(path)
        self.assertFalse(ok)
        self.assertIn('0640', reason)
        self.assertIn('0600', reason)
        os.chmod(path, 0o604)
        self.assertFalse(settings.is_private(path)[0])
        self.assertFalse(settings.is_private(os.path.join(self.tmp, 'missing'))[0])
        self.assertFalse(settings.is_private(self.tmp)[0])

    def test_read_env_file(self):
        path = os.path.join(self.tmp, 'mail.env')
        Path(path).write_text('# comment\n\nA=plain\nexport B="quoted value"\nC=\'single\'\nD = spaced # note\n'
                              'E=pa#ss\nnot a line\nF=\n')
        self.assertEqual(settings.read_env_file(path),
                         {'A': 'plain', 'B': 'quoted value', 'C': 'single', 'D': 'spaced', 'E': 'pa#ss', 'F': ''})

    def test_read_env_file_error_never_carries_the_content(self):
        with self.assertRaises(OSError) as ctx:
            settings.read_env_file(os.path.join(self.tmp, 'absent.env'))
        self.assertNotIn('hunter2', str(ctx.exception))

    def test_cache_dir_is_private_and_follows_xdg_cache_home(self):
        path = settings.cache_dir('demo')
        self.assertEqual(path, Path(self.tmp, 'cache', 'claude-toolkit', 'demo'))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(path.parent).st_mode), 0o700)
        with self.assertRaises(ValueError):
            settings.cache_dir('../escape')

    def test_cache_dir_falls_back_to_the_home_cache(self):
        with mock.patch.dict(os.environ):
            os.environ.pop('XDG_CACHE_HOME')
            self.assertEqual(settings.cache_dir('demo'), Path(self.home, '.cache', 'claude-toolkit', 'demo'))

    def test_expand_handles_home_and_variables(self):
        with mock.patch.dict(os.environ, {'DEMO_DIR': 'sub'}):
            self.assertEqual(settings.expand('~/a/$DEMO_DIR/f'), Path(self.home, 'a', 'sub', 'f'))


if __name__ == '__main__':
    unittest.main()
