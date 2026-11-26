"""claude-sessions-sync: its self-test passes from the repo copy, and it never reaches past a sandbox HOME."""
import os
import subprocess
import sys
import tempfile
import unittest

from scripts.toolkit.paths import REPO_ROOT

SCRIPT = REPO_ROOT / 'global/scripts/claude-sessions-sync'


class ClaudeSessionsSync(unittest.TestCase):
    def run_script(self, *args, **env):
        with tempfile.TemporaryDirectory() as home:
            proc = subprocess.run([sys.executable, '-I', str(SCRIPT), *args], capture_output=True, text=True,
                                  timeout=60, env=dict(os.environ, HOME=home, **env), cwd=home)
            left = sorted(os.listdir(home))
        return proc, left

    def test_self_test_passes_and_leaves_home_untouched(self):
        proc, left = self.run_script('self-test')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(' 0 failures', proc.stdout)
        self.assertNotIn('FAIL:', proc.stdout)
        self.assertEqual(left, [], 'the self-test wrote into HOME')

    def test_status_without_the_app_folder(self):
        proc, _ = self.run_script('status')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('deleted (not copied again): 0', proc.stdout)


if __name__ == '__main__':
    unittest.main()
