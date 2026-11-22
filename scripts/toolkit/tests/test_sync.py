"""Contract, drift, pull and equivalence tests. Every test works in a throwaway HOME."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from scripts.toolkit import contracts, drift, equivalence, modules, overlay
from scripts.toolkit.tests.test_installer import Sandbox


class Contracts(Sandbox):
    def verify(self, target: Path | None = None) -> tuple[int, str]:
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from scripts.toolkit import cli
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = cli.main(['verify', '--target', str(target or self.target)])
        return code, out.getvalue()

    def test_every_contract_names_an_installed_piece(self):
        dests = {f.dest for m in modules.load_many(modules.DEFAULT_MODULES) for f in m.files}
        for c in contracts.load_all():
            self.assertIn(c['dest'], dests, c['piece'])
            self.assertTrue(c['probes'], c['piece'])

    def test_verify_passes_in_the_sandbox(self):
        self.assertEqual(self.run_cli('install')[0], 0)
        code, out = self.verify()
        self.assertEqual(code, 0, out)
        self.assertIn('0 failure(s)', out)

    def test_verify_refuses_outside_a_sandbox(self):
        code, out = self.verify(self.tmp / 'elsewhere' / '.claude')
        self.assertEqual(code, 2, out)
        self.assertIn('refusing to execute pieces', out)

    def test_override_piece_that_breaks_its_contract_blocks_install(self):
        broken = '#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n'
        self.write('files/hooks/process-kill-gate', broken, base=self.override)
        os.chmod(self.override / 'files/hooks/process-kill-gate', 0o755)
        code, out = self.run_cli('install', override=True)
        self.assertEqual(code, 3, out)
        self.assertIn('process-kill-gate', out)
        self.assertFalse((self.target / 'hooks/process-kill-gate').exists())
        code, out = self.run_cli('install', '--allow-contract-failures', override=True)
        self.assertEqual(code, 0, out)

    def test_corrupt_config_makes_the_gate_fail_open(self):
        self.assertEqual(self.run_cli('install')[0], 0)
        (self.target / 'toolkit/config/worktree-location.json').write_text('{broken')
        code, out = self.verify()
        self.assertEqual(code, 0, out)


class Drift(Sandbox):
    def rows(self, override: bool = False) -> dict[str, str]:
        ov = overlay.load(self.override if override else None)
        return dict(drift.classify(self.target, modules.load_many(modules.DEFAULT_MODULES), ov))

    def test_states(self):
        self.assertEqual(self.run_cli('install')[0], 0)
        self.assertEqual(set(self.rows().values()), {'in-sync'})
        self.write('rules/autoria-commits.md', 'edited live\n')
        self.write('rules/my-own.md', 'mine\n')
        (self.target / 'rules/worktrees-ubicacion.md').unlink()
        rows = self.rows()
        self.assertEqual(rows['rules/autoria-commits.md'], 'live-changed')
        self.assertEqual(rows['rules/my-own.md'], 'untracked')
        self.assertEqual(rows['rules/worktrees-ubicacion.md'], 'missing')
        code, out = self.run_cli('drift')
        self.assertEqual(code, 1)
        self.assertIn('live-changed', out)

    def test_pull_to_override_records_the_base_and_detects_upstream_change(self):
        self.override.mkdir()
        self.assertEqual(self.run_cli('install', override=True)[0], 0)
        self.write('rules/autoria-commits.md', 'my version\n')
        code, out = self.run_cli('pull', 'rules/autoria-commits.md', override=True)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.override / 'files/rules/autoria-commits.md').read_text(), 'my version\n')
        lock = json.loads((self.override / drift.LOCK).read_text())
        self.assertIn('rules/autoria-commits.md', lock['files'])
        lock['files']['rules/autoria-commits.md'] = '0' * 64      # pretend the toolkit moved on
        (self.override / drift.LOCK).write_text(json.dumps(lock))
        self.assertEqual(self.rows(override=True)['rules/autoria-commits.md'], 'override-base-changed')

    def test_pull_to_toolkit_refuses_private_content(self):
        self.override.mkdir()
        (self.override / 'privacy-denylist.txt').write_text('zorbqux\n')
        self.assertEqual(self.run_cli('install', override=True)[0], 0)
        self.write('rules/autoria-commits.md', 'mentions zorbqux here\n')
        code, out = self.run_cli('pull', 'rules/autoria-commits.md', '--to', 'toolkit', '--dry-run', override=True)
        self.assertEqual(code, 1, out)
        self.assertIn('pull refused', out)
        self.assertNotIn('zorbqux', out)


class Equivalence(Sandbox):
    def live_copy(self) -> Path:
        self.assertEqual(self.run_cli('install')[0], 0)
        return self.target

    def summary(self, live: Path, override: bool = False) -> dict:
        ov = overlay.load(self.override if override else None)
        return equivalence.summarise(equivalence.compare(live, modules.load_many(modules.DEFAULT_MODULES), ov))

    def test_fresh_install_is_equivalent(self):
        s = self.summary(self.live_copy())
        self.assertEqual(set(s['files']), {'identical'})
        self.assertNotIn('unexplained', s['hooks'])

    def test_live_only_file_is_unexplained_until_excluded_or_declared(self):
        live = self.live_copy()
        self.write('rules/private.md', 'x\n')
        self.write('scripts/tool.py', '"""doc"""\nx = 1\n')
        self.assertEqual(self.summary(live)['files'].get('unexplained'), 2)
        self.write('override.yaml', 'schema: 1\nexcluded: [rules/private.md]\n'
                   'equivalence:\n  - {path: scripts/tool.py, class: managed-elsewhere, reason: kept by hand}\n',
                   base=self.override)
        s = self.summary(live, override=True)
        self.assertNotIn('unexplained', s['files'])
        self.assertEqual(s['files']['excluded'], 1)
        self.assertEqual(s['files']['declared'], 1)

    def test_docstring_only_difference_is_neutral(self):
        live = self.live_copy()
        path = self.target / 'scripts/worktree-location'
        text = path.read_text()
        first = text.index('"""')
        end = text.index('"""', first + 3)
        path.write_text(text[:first] + '"""Another docstring."""' + text[end + 3:])
        s = self.summary(live)
        self.assertEqual(s['files'].get('neutral-text'), 1)

    def test_live_hook_not_in_toolkit_is_unexplained(self):
        live = self.live_copy()
        data = json.loads((live / 'settings.json').read_text())
        data['hooks'].setdefault('Stop', []).append({'hooks': [{'type': 'command', 'command': '~/bin/x'}]})
        (live / 'settings.json').write_text(json.dumps(data))
        self.assertEqual(self.summary(live)['hooks'].get('unexplained'), 1)


if __name__ == '__main__':
    unittest.main()
