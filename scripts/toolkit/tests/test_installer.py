"""Installer tests. Run: python3 -m unittest discover -s scripts/toolkit/tests -t .

Every test works in a throwaway HOME; nothing touches the real Claude dir.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts.toolkit import apply as apply_mod, cli, modules, plan as plan_mod, settings_merge
from scripts.toolkit.paths import REPO_ROOT, is_sandbox


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}


class Sandbox(unittest.TestCase):
    modules = ','.join(modules.available())   # every module, opt-in ones too

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='toolkit-test-'))
        self.home = self.tmp / 'home'
        self.target = self.home / '.claude'
        self.target.mkdir(parents=True)
        self.override = self.tmp / 'override'
        self._env = dict(os.environ)
        os.environ['HOME'] = str(self.home)
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
        os.environ.pop('CLAUDE_TOOLKIT_OVERRIDE', None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp)

    def run_cli(self, *args: str, override: bool = False) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = list(args)
        if argv[0] != 'uninstall':
            argv += ['--modules', self.modules, '--override', str(self.override) if override else '']
        argv += ['--target', str(self.target)]
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue() + err.getvalue()

    def write(self, rel: str, text: str, base: Path | None = None) -> Path:
        path = (base or self.target) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def settings(self) -> dict:
        return json.loads((self.target / 'settings.json').read_text())


class InstallBasics(Sandbox):
    def test_dry_run_writes_nothing(self):
        code, out = self.run_cli('install', '--dry-run')
        self.assertEqual(code, 0, out)
        self.assertIn('dry run', out)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_fresh_install_files_modes_manifest(self):
        code, out = self.run_cli('install')
        self.assertEqual(code, 0, out)
        manifest = json.loads((self.target / 'toolkit/installed.json').read_text())
        self.assertIn('skills/openspec-explore/SKILL.md', manifest['files'])     # flattened group
        self.assertNotIn('skills/README.md', manifest['files'])
        self.assertIn('docs/openspec/README.md', manifest['files'])
        gate = self.target / 'hooks/process-kill-gate'
        self.assertTrue(gate.stat().st_mode & 0o100)
        for dest, info in manifest['files'].items():
            data = (self.target / dest).read_bytes()
            self.assertEqual(plan_mod.sha(data), info['sha256'], dest)

    def test_second_install_is_a_no_op(self):
        self.run_cli('install')
        before = snapshot(self.target)
        code, out = self.run_cli('install')
        self.assertEqual(code, 0)
        self.assertIn('already installed', out)
        self.assertEqual(snapshot(self.target), before)

    def test_same_content_other_mode_is_chmodded_not_rewritten(self):
        # an existing Claude dir written with umask 002 has 0664 files: same bytes as the toolkit's 0644 copy
        self.run_cli('install')
        manifest = json.loads((self.target / 'toolkit/installed.json').read_text())
        (self.target / 'toolkit/installed.json').unlink()
        rule = next(d for d in manifest['files'] if d.startswith('rules/'))
        path = self.target / rule
        os.chmod(path, 0o664)
        os.utime(path, (1_000_000_000, 1_000_000_000))
        code, out = self.run_cli('install', '--dry-run')
        self.assertIn(f'chmod       {rule}', out)
        code, out = self.run_cli('install')
        self.assertEqual(code, 0, out)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(path.stat().st_mtime, 1_000_000_000)      # not rewritten
        manifest = json.loads((self.target / 'toolkit/installed.json').read_text())
        self.assertEqual(manifest['originals'][rule], '@preexisting')
        code, out = self.run_cli('uninstall')
        self.assertTrue(path.is_file(), out)                      # it was there before: uninstall keeps it

    def test_file_edited_in_place_is_not_overwritten_silently(self):
        # the first install already backed up what was there before; a later edit is in no backup
        rule = 'rules/worktrees-ubicacion.md'
        self.write(rule, 'before the toolkit\n')
        self.run_cli('install')
        self.write(rule, 'edited in place\n')
        code, out = self.run_cli('install', '--dry-run')
        self.assertEqual(code, 0, out)
        self.assertIn(f'update      {rule} [toolkit]  (edited in place, backup first)', out)
        self.assertIn(rule, out.split('edited in place since', 1)[1])
        before = snapshot(self.target)
        code, out = self.run_cli('install')
        self.assertEqual(code, 4, out)
        self.assertIn('install refused', out)
        self.assertEqual(snapshot(self.target), before)           # nothing written, the edit is still there
        code, out = self.run_cli('install', '--overwrite-edited')
        self.assertEqual(code, 0, out)
        self.assertNotEqual((self.target / rule).read_text(), 'edited in place\n')
        backups = sorted((self.target / 'backups').glob(f'toolkit-*/{rule}'))
        self.assertIn(b'edited in place\n', [b.read_bytes() for b in backups])
        manifest = json.loads((self.target / 'toolkit/installed.json').read_text())
        first = (self.target / manifest['originals'][rule]).read_text()
        self.assertEqual(first, 'before the toolkit\n')         # uninstall still restores the pre-toolkit file
        code, out = self.run_cli('install')
        self.assertEqual(code, 0, out)
        self.assertIn('already installed', out)

    def test_installs_in_the_same_second_get_their_own_backup_folder(self):
        first = apply_mod._backup_dir(self.target, '20260101-000000')
        first.mkdir(parents=True)
        second = apply_mod._backup_dir(self.target, '20260101-000000')
        self.assertNotEqual(first, second)
        self.assertEqual(second.name, 'toolkit-20260101-000000-2')

    def test_block_merged_file_edited_outside_the_block_installs(self):
        self.run_cli('install')
        claude_md = self.target / 'CLAUDE.md'
        claude_md.write_text('my own notes\n\n' + claude_md.read_text())
        code, out = self.run_cli('install')
        self.assertEqual(code, 0, out)
        self.assertNotIn('install refused', out)
        self.assertTrue(claude_md.read_text().startswith('my own notes\n'))

    def test_missing_required_binary_exits_2_and_writes_nothing(self):
        os.environ['PATH'] = str(self.tmp / 'empty-bin')
        code, out = self.run_cli('install')
        self.assertEqual(code, 2)
        self.assertIn("required binary 'git'", out)
        self.assertEqual(list(self.target.iterdir()), [])


class DefaultModules(Sandbox):
    """What an install gives when neither --modules nor an override chooses."""

    def test_modules_that_widen_session_autonomy_are_opt_in(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['install', '--override', '', '--target', str(self.target)]), 0)
        self.assertFalse((self.target / 'hooks' / 'start-session-bypass-gate').exists())
        self.assertNotIn('start-session-bypass-gate', json.dumps(self.settings()))
        self.assertFalse((self.target / 'hooks' / 'cross-project-message-gate').exists(), 'supervision is opt-in')

    def test_plain_reinstall_keeps_the_modules_of_the_last_install(self):
        quiet = lambda *argv: cli.main([*argv, '--override', '', '--target', str(self.target)])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(quiet('install', '--modules', 'openspec,core,devtools,heavy-jobs'), 0)
            before = snapshot(self.target)
            self.assertEqual(quiet('install'), 0)
        self.assertEqual(snapshot(self.target), before, 'a re-run without --modules dropped an opt-in module')
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(quiet('install', '--modules', 'openspec,core,devtools'), 0)
        self.assertFalse((self.target / 'hooks' / 'heavy-job-gate').exists(), 'naming the modules still drops the rest')

    def test_module_notes_are_plain_text(self):
        for name in modules.available():
            for note in modules.load_many([name])[0].notes:
                self.assertIsInstance(note, str, f'{name}: quote the note, YAML read it as a mapping')


class SettingsMerge(Sandbox):
    def test_user_keys_and_hooks_survive_and_no_duplicates(self):
        user = {'model': 'x', 'permissions': {'allow': ['Bash(ls)']},
                'hooks': {'PreToolUse': [
                    {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': '~/bin/my-hook'}]},
                    # same command as a toolkit entry, without the interpreter prefix
                    {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': f'{self.home}/.claude/hooks/process-kill-gate'}]},
                ]}}
        self.write('settings.json', json.dumps(user))
        self.assertEqual(self.run_cli('install')[0], 0)
        data = self.settings()
        self.assertEqual(data['model'], 'x')
        self.assertEqual(data['permissions'], user['permissions'])
        cmds = [h['command'] for e in data['hooks']['PreToolUse'] for h in e['hooks']]
        self.assertIn('~/bin/my-hook', cmds)
        self.assertEqual(sum('process-kill-gate' in c for c in cmds), 1)
        self.assertEqual(sum('worktree-location-gate' in c for c in cmds), 1)
        self.assertIn('WorktreeCreate', data['hooks'])

    def test_broken_settings_exit_2_nothing_written(self):
        self.write('settings.json', '{not json')
        code, out = self.run_cli('install')
        self.assertEqual(code, 2)
        self.assertIn('not valid JSON', out)
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ['settings.json'])

    def test_normalise(self):
        home = str(self.home)
        self.assertEqual(settings_merge.normalise('python3 ~/.claude/hooks/x', home), '~/.claude/hooks/x')
        self.assertEqual(settings_merge.normalise(f'{home}/.claude/hooks/x', home), '~/.claude/hooks/x')
        self.assertEqual(settings_merge.normalise('$HOME/.claude/hooks/x', home), '~/.claude/hooks/x')


class Uninstall(Sandbox):
    def test_round_trip_restores_the_original_state(self):
        self.write('rules/worktrees-ubicacion.md', 'my own rule\n')
        self.write('notes.md', 'user file\n')
        self.write('settings.json', json.dumps({'theme': 'dark'}, indent=2) + '\n')
        before = snapshot(self.target)
        self.assertEqual(self.run_cli('install')[0], 0)
        self.assertNotEqual((self.target / 'rules/worktrees-ubicacion.md').read_text(), 'my own rule\n')
        code, out = self.run_cli('uninstall')
        self.assertEqual(code, 0, out)
        after = {k: v for k, v in snapshot(self.target).items() if not k.startswith('backups/')}
        self.assertEqual(after.keys(), before.keys())
        self.assertEqual(after['rules/worktrees-ubicacion.md'], b'my own rule\n')
        self.assertEqual(json.loads(after['settings.json']), {'theme': 'dark'})

    def test_two_installs_then_uninstall_restore_the_first_original(self):
        self.write('rules/worktrees-ubicacion.md', 'original\n')
        self.run_cli('install')
        self.write('rules/worktrees-ubicacion.md', 'edited in between\n')
        self.assertEqual(self.run_cli('install', '--overwrite-edited')[0], 0)
        self.run_cli('uninstall')
        self.assertEqual((self.target / 'rules/worktrees-ubicacion.md').read_text(), 'original\n')

    def test_file_edited_after_install_is_kept(self):
        self.run_cli('install')
        self.write('rules/autoria-commits.md', 'edited by the user\n')
        code, out = self.run_cli('uninstall')
        self.assertIn('kept      rules/autoria-commits.md', out)
        self.assertEqual((self.target / 'rules/autoria-commits.md').read_text(), 'edited by the user\n')

    def test_identical_preexisting_file_is_left(self):
        src = (REPO_ROOT / 'global/rules/autoria-commits.md').read_bytes()
        (self.target / 'rules').mkdir()
        (self.target / 'rules/autoria-commits.md').write_bytes(src)
        os.chmod(self.target / 'rules/autoria-commits.md', 0o644)
        self.run_cli('install')
        self.run_cli('uninstall')
        self.assertEqual((self.target / 'rules/autoria-commits.md').read_bytes(), src)

    def test_bytecode_of_removed_files_goes_with_them(self):
        """A piece that imports an installed file (a library, or a script loaded as a module) leaves its bytecode in
        __pycache__; uninstall removes it with its source, so the folders it created go too. Runtime state the pieces
        wrote (logs, queues) is the user's and stays."""
        self.assertEqual(self.run_cli('install')[0], 0)
        caches = []
        for rel in ('scripts/lib/toolkit_config.py', 'scripts/supervisor-lock', 'scripts/heavy-job'):
            caches.append(Path(importlib.util.cache_from_source(str(self.target / rel))))
            py_compile.compile(str(self.target / rel), cfile=str(caches[-1]), doraise=True)
        foreign = self.target / 'scripts/lib/__pycache__/not-ours.cpython-312.pyc'
        foreign.write_bytes(b'')
        self.write('state/heavy-job-gate/decisions.log', 'runtime state\n')
        code, out = self.run_cli('uninstall')
        self.assertEqual(code, 0, out)
        self.assertFalse(any(c.exists() for c in caches), caches)
        self.assertFalse((self.target / 'scripts/lib/supervisor').exists())
        self.assertFalse((self.target / 'scripts/__pycache__').exists())
        self.assertTrue(foreign.exists())   # bytecode of a file the toolkit never wrote is not touched
        self.assertTrue((self.target / 'state/heavy-job-gate/decisions.log').exists())


class OverrideLayer(Sandbox):
    def test_no_override_uses_defaults(self):
        self.run_cli('install')
        cfg = json.loads((self.target / 'toolkit/config/worktree-location.json').read_text())
        self.assertEqual(cfg, {'root': '~/worktrees'})

    def test_replace_append_extra_and_config(self):
        self.write('files/rules/autoria-commits.md', 'replaced\n', base=self.override)
        self.write('append/rules/worktrees-ubicacion.md', 'appendix line\n', base=self.override)
        self.write('files/skills/my-skill/SKILL.md', '---\nname: my-skill\ndescription: x\n---\n', base=self.override)
        self.write('config/worktree-location.json', json.dumps({'root': str(self.tmp / 'wt')}), base=self.override)
        self.assertEqual(self.run_cli('install', override=True)[0], 0)
        self.assertEqual((self.target / 'rules/autoria-commits.md').read_text(), 'replaced\n')
        self.assertTrue((self.target / 'rules/worktrees-ubicacion.md').read_text().endswith('appendix line\n'))
        self.assertTrue((self.target / 'skills/my-skill/SKILL.md').is_file())
        repo = self.tmp / 'proj'
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        out = subprocess.run([sys.executable, str(self.target / 'scripts/worktree-location'), 'where', '--repo', str(repo)],
                             capture_output=True, text=True, env=dict(os.environ)).stdout.strip()
        self.assertEqual(out, str(self.tmp / 'wt' / 'proj'))

    def test_remove_drops_file_and_its_hooks(self):
        self.write('override.yaml', 'schema: 1\nremove: [hooks/process-kill-gate]\n', base=self.override)
        self.assertEqual(self.run_cli('install', override=True)[0], 0)
        self.assertFalse((self.target / 'hooks/process-kill-gate').exists())
        cmds = [h['command'] for e in self.settings()['hooks']['PreToolUse'] for h in e['hooks']]
        self.assertFalse(any('process-kill-gate' in c for c in cmds))

    def test_example_override_installs(self):
        self.override = REPO_ROOT / 'examples/override'
        code, out = self.run_cli('install', override=True)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.target / 'rules/my-team-conventions.md').is_file())
        self.assertIn('Local addition', (self.target / 'rules/worktrees-ubicacion.md').read_text())
        cfg = json.loads((self.target / 'toolkit/config/worktree-location.json').read_text())
        self.assertEqual(cfg, {'root': '~/code/worktrees'})
        cmds = [h['command'] for e in self.settings()['hooks'].get('Stop', []) for h in e['hooks']]
        self.assertTrue(any('my-stop-notifier' in c for c in cmds), cmds)

    def test_full_example_override_turns_everything_on(self):
        """examples/override-full/ is the way to try all of the toolkit from zero: it must name every module and
        every message exception the toolkit has, so a new one breaks this test instead of leaving the example
        behind, and its install must pass every contract probe with its own values."""
        example = REPO_ROOT / 'examples/override-full'
        text = (example / 'override.yaml').read_text()
        listed = next(line for line in text.splitlines() if line.startswith('modules:'))
        self.assertEqual(sorted(m.strip() for m in listed.split('[', 1)[1].rstrip(']').split(',')),
                         sorted(modules.available()))
        gate = (REPO_ROOT / 'global/hooks/cross-project-message-gate').read_text()
        known = set(re.findall(r'enabled\("(\w+)"\)', gate))
        self.assertEqual(len(known), 4, known)
        example_cfg = json.loads((example / 'config/supervision.json').read_text())
        self.assertEqual(set(example_cfg['message_exceptions']), known)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):   # no --modules: the example's own choice
            code = cli.main(['install', '--override', str(example), '--target', str(self.target)])
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())
        self.assertEqual(sorted(plan_mod.read_manifest(self.target)['modules']), sorted(modules.available()))
        supervision = json.loads((self.target / 'toolkit/config/supervision.json').read_text())
        self.assertEqual(set(supervision['message_exceptions']), known)
        self.assertEqual(supervision['presence_min'], 20)   # keys the example leaves out keep their defaults
        self.assertFalse(supervision['deploy_preauthorised'] or supervision['archive_preauthorised'])
        self.assertEqual(json.loads((self.target / 'toolkit/config/heavy-job.json').read_text())['default_slots'], 2)
        commands = ' '.join(h['command'] for entries in self.settings()['hooks'].values() for e in entries
                            for h in e['hooks'])
        for hook in ('commit-authorship-gate', 'start-session-bypass-gate', 'cross-project-message-gate',
                     'supervisor-stop-gate', 'heavy-job-gate', 'my-stop-notifier'):
            self.assertIn(hook, commands)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = cli.main(['verify', '--target', str(self.target)])
        self.assertEqual(code, 0, out.getvalue())

    def test_symlink_in_override_is_refused(self):
        self.override.mkdir()
        (self.override / 'files').mkdir()
        (self.override / 'files' / 'x.md').symlink_to('/etc/hostname')
        code, out = self.run_cli('install', override=True)
        self.assertEqual(code, 2)
        self.assertIn('symlinks are never installed', out)


class ManagedBlock(unittest.TestCase):
    def test_block_merge_keeps_user_text_and_strips_back(self):
        user = b'# My notes\nkeep me\n'
        merged = plan_mod.block_merge(user, b'toolkit text\n')
        self.assertTrue(merged.startswith(user))
        self.assertIn(b'toolkit text', merged)
        again = plan_mod.block_merge(merged, b'new toolkit text\n')
        self.assertEqual(again.count(plan_mod.BLOCK_BEGIN.encode()), 1)
        self.assertIn(b'new toolkit text', again)
        self.assertEqual(plan_mod.block_strip(again), user)


class PiecesInSandbox(Sandbox):
    """Run pieces' own self-tests from the installed copy, only inside the sandbox HOME."""

    def test_sandbox_rule(self):
        self.assertTrue(is_sandbox(self.target))
        self.assertFalse(is_sandbox(self.tmp / 'elsewhere'))

    def test_process_kill_gate_self_test(self):
        if not shutil.which('pgrep') or not shutil.which('setsid'):
            self.skipTest('pgrep/setsid not available')
        self.run_cli('install')
        # The self-test expects foreign processes that a desktop always has (a volume monitor whose name
        # starts with gvfs). A CI runner has none, so start one: the Python interpreter run through a symlink
        # with that name (the process name comes from the path executed; a renamed coreutils binary may
        # refuse to run), detached with setsid and carrying another session id, killed by PID afterwards.
        fake = self.tmp / 'bin' / 'gvfs-udisks2-volume-monitor'
        fake.parent.mkdir()
        fake.symlink_to(os.path.realpath(sys.executable))
        env = dict(os.environ, CLAUDE_CODE_SESSION_ID='toolkit-test-foreign-session')
        subprocess.run(['setsid', '-f', str(fake), '-c', 'import time; time.sleep(300)'], env=env, check=True)
        pattern = f'^{fake} -c'
        found = []
        for _ in range(20):
            found = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True).stdout.split()
            if found:
                break
            time.sleep(0.1)
        try:
            r = subprocess.run([sys.executable, str(self.target / 'hooks/process-kill-gate'), '--self-test'],
                               capture_output=True, text=True, env=dict(os.environ), timeout=120)
        finally:
            for pid in subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True).stdout.split():
                os.kill(int(pid), 15)
        self.assertTrue(found, 'the fake foreign process did not start')
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
