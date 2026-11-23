"""Contracts for replaceable pieces (Liskov): probes run against the installed file.

global/contracts/<piece>.yaml:
  piece: heavy-job-gate
  dest: hooks/heavy-job-gate
  config: supervision          # config piece it reads, when not named like the piece
  kind: hook | cli
  probes:
    - name: unrelated command passes
      args: []                 # extra argv (cli)
      stdin: {...}             # JSON written to stdin (hooks)
      stdin_raw: "text"        # or raw text written to stdin
      env: {KEY: value}        # extra environment
      corrupt_config: true     # point CLAUDE_TOOLKIT_CONFIG_DIR at a corrupt config
      exit: [0]
      stdout: empty | json | empty-or-json | any
      contains: text           # optional substring of stdout

Pieces are executed only inside a sandbox HOME (paths.is_sandbox): they resolve ~/.claude
through HOME, so running them against a real HOME would touch real state.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from .paths import REPO_ROOT, is_sandbox

CONTRACTS_DIR = REPO_ROOT / 'global' / 'contracts'


@dataclass
class Failure:
    piece: str
    probe: str
    detail: str

    def render(self) -> str:
        return f'FAIL {self.piece}: {self.probe}: {self.detail}'


def load_all() -> list[dict]:
    out = []
    for path in sorted(CONTRACTS_DIR.glob('*.yaml')):
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        data['_file'] = path.name
        out.append(data)
    return out


def _argv(path: Path) -> list[str]:
    head = path.read_bytes()[:128]
    if head.startswith(b'#!') and b'python' in head.split(b'\n', 1)[0]:
        return [sys.executable, str(path)]
    if head.startswith(b'#!'):
        return [str(path)]
    return [sys.executable, str(path)] if path.suffix in ('', '.py') else ['bash', str(path)]


def _stdout_ok(kind: str, out: str) -> bool:
    text = out.strip()
    if kind == 'any':
        return True
    if kind == 'empty':
        return text == ''
    if text == '':
        return kind == 'empty-or-json'
    try:
        json.loads(text)
        return kind in ('json', 'empty-or-json')
    except ValueError:
        return False


def run_probes(target: Path, only_sources: set[str] | None = None, manifest: dict | None = None) -> tuple[int, list[Failure]]:
    if not is_sandbox(target):
        raise RuntimeError(f'refusing to execute pieces: HOME is not a sandbox or {target} is not $HOME/.claude')
    files = (manifest or {}).get('files', {})
    failures, ran = [], 0
    corrupt = Path(tempfile.mkdtemp(prefix='toolkit-corrupt-config-'))
    try:
        for contract in load_all():
            dest = contract['dest']
            if only_sources is not None and files.get(dest, {}).get('source') not in only_sources:
                continue
            path = target / dest
            if not path.is_file():
                continue
            for name in os.listdir(corrupt):
                os.unlink(corrupt / name)
            (corrupt / f'{contract.get("config", contract["piece"])}.json').write_text('{not json')
            for probe in contract.get('probes') or []:
                ran += 1
                env = dict(os.environ, **{k: str(v) for k, v in (probe.get('env') or {}).items()})
                if probe.get('corrupt_config'):
                    env['CLAUDE_TOOLKIT_CONFIG_DIR'] = str(corrupt)
                stdin = probe['stdin_raw'] if 'stdin_raw' in probe else (json.dumps(probe['stdin']) if 'stdin' in probe else '')
                try:
                    r = subprocess.run(_argv(path) + [str(a) for a in probe.get('args') or []], input=stdin,
                                       capture_output=True, text=True, env=env, timeout=probe.get('timeout', 30),
                                       cwd=str(Path(env['HOME'])))
                except subprocess.TimeoutExpired:
                    failures.append(Failure(contract['piece'], probe['name'], 'timed out'))
                    continue
                if r.returncode not in probe.get('exit', [0]):
                    failures.append(Failure(contract['piece'], probe['name'],
                                            f'exit {r.returncode} not in {probe.get("exit", [0])}; {r.stderr.strip()[:200]}'))
                elif not _stdout_ok(probe.get('stdout', 'any'), r.stdout):
                    failures.append(Failure(contract['piece'], probe['name'], f'stdout is not {probe.get("stdout")}: {r.stdout.strip()[:200]!r}'))
                elif probe.get('contains') and probe['contains'] not in r.stdout:
                    failures.append(Failure(contract['piece'], probe['name'], f'stdout lacks {probe["contains"]!r}'))
    finally:
        shutil.rmtree(corrupt, ignore_errors=True)
    return ran, failures


def check_plan_in_sandbox(plan, only_sources: set[str]) -> tuple[int, list[Failure]]:
    """Install PLAN's desired files into a throwaway HOME and probe the pieces from ONLY_SOURCES."""
    from .apply import write_atomic
    tmp = Path(tempfile.mkdtemp(prefix='toolkit-contracts-'))
    old_home = os.environ.get('HOME')
    try:
        target = tmp / '.claude'
        for dest, d in plan.desired.items():
            write_atomic(target / dest, d.content, d.mode)
        manifest = {'files': {dest: {'source': d.source} for dest, d in plan.desired.items()}}
        os.environ['HOME'] = str(tmp)
        return run_probes(target, only_sources, manifest)
    finally:
        if old_home is not None:
            os.environ['HOME'] = old_home
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_verify(args) -> int:
    from .paths import resolve_target
    from .plan import read_manifest
    target = resolve_target(args.target)
    try:
        ran, failures = run_probes(target, None, read_manifest(target))
    except RuntimeError as exc:
        print(f'ERROR {exc}')
        return 2
    for f in failures:
        print(f.render())
    print(f'verify: {ran} probe(s), {len(failures)} failure(s)')
    return 1 if failures else 0


def register(sub, common) -> None:
    p = sub.add_parser('verify', help='run the contract probes of installed pieces (sandbox HOME only)')
    p.add_argument('--target')
    p.set_defaults(func=cmd_verify)
