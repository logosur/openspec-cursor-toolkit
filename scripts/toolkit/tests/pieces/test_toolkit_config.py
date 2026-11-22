"""load_checked: a wrong value in a config piece never replaces the code's default."""
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

from scripts.toolkit.paths import REPO_ROOT

spec = importlib.util.spec_from_file_location('toolkit_config', REPO_ROOT / 'global/scripts/lib/toolkit_config.py')
toolkit_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolkit_config)
DEFAULTS = {'marker': '[resume]', 'window_s': 60, 'allowed': [], 'on': False}


class LoadChecked(unittest.TestCase):
    def load(self, raw):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'p.json'), 'w') as fh:
                fh.write(raw)
            with mock.patch.dict(os.environ, {'CLAUDE_TOOLKIT_CONFIG_DIR': tmp}):
                return toolkit_config.load_checked('p', DEFAULTS)

    def test_valid_values_replace_the_defaults(self):
        new = {'marker': '[go]', 'window_s': 5.5, 'allowed': ['a'], 'on': True}
        self.assertEqual(self.load(json.dumps(new)), new)

    def test_a_wrong_value_keeps_the_default(self):
        for key, bad in (('marker', ''), ('marker', ' '), ('marker', 3), ('window_s', -1), ('window_s', True),
                         ('window_s', '60'), ('allowed', 'a'), ('allowed', [1]), ('allowed', ['']), ('on', 'yes')):
            self.assertEqual(self.load(json.dumps({key: bad}))[key], DEFAULTS[key], (key, bad))

    def test_unknown_keys_and_a_corrupt_file_give_the_defaults(self):
        for raw in ('{broken', '[]', '{"other": 1}', ''):
            self.assertEqual(self.load(raw), DEFAULTS, raw)
