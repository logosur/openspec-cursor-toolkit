"""Equivalence check: toolkit + override installed into a temporary HOME versus a live Claude dir.

Every managed path gets exactly one class:
  identical        same bytes, from the toolkit
  override         same bytes, from the override (files/ or toolkit+append)
  toolkit-newer    differs, and the live file equals a historical version of its repo source
                   (the live tree has an older copy of the same piece)
  neutral-text     Python file whose AST without docstrings is equal (comments and docs differ)
  declared         differs, and override.yaml `equivalence:` declares why (class, reason, test)
  added            only in the install (a new piece the live tree does not have)
  excluded         only live, matched by override.yaml `excluded:` (state, third-party, app-managed)
  unexplained      anything else -> the check fails
Hooks in settings.json are compared by identity (event, matcher, normalised command).
Nothing is executed: pieces are only compared as files.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import apply as apply_mod, modules, overlay, plan as plan_mod, settings_merge
from .drift import scope_files
from .paths import REPO_ROOT, resolve_override


def git_blob_id(data: bytes) -> str:
    return subprocess.run(['git', 'hash-object', '--stdin'], input=data, capture_output=True,
                          check=True).stdout.decode().strip()


def historical_blobs(rel: str) -> set[str]:
    paths = {rel}
    if rel.startswith('.claude/'):
        paths.add('.cursor/' + rel[len('.claude/'):])
    out = subprocess.run(['git', '-C', str(REPO_ROOT), 'log', '--all', '--pretty=format:', '--raw', '--no-abbrev',
                          '--', *sorted(paths)], capture_output=True, text=True).stdout
    blobs = set()
    for line in out.splitlines():
        parts = line.split()
        if line.startswith(':') and len(parts) >= 4:
            blobs.update(p for p in parts[2:4] if p.strip('0'))
    return blobs


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], 'value', None), ast.Constant) and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return tree


def is_python(path_rel: str, data: bytes) -> bool:
    return path_rel.endswith('.py') or (data.startswith(b'#!') and b'python' in data.split(b'\n', 1)[0])


def same_ast(a: bytes, b: bytes) -> bool:
    try:
        ta = _strip_docstrings(ast.parse(a.decode('utf-8')))
        tb = _strip_docstrings(ast.parse(b.decode('utf-8')))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return False
    return ast.dump(ta) == ast.dump(tb)


def declared(ov: overlay.Override, rel: str) -> dict | None:
    for entry in ov.equivalence:
        if fnmatch.fnmatch(rel, entry.get('path', '')):
            if not entry.get('reason'):
                raise overlay.OverrideError(f'override.yaml equivalence entry {entry!r} has no reason')
            return entry
    return None


def compare(live: Path, mods, ov) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix='toolkit-equivalence-'))
    try:
        target = tmp / '.claude'
        target.mkdir()
        p = plan_mod.build(target, mods, ov)
        apply_mod.install(p, 'equivalence')
        installed = scope_files(target, overlay.Override(root=None))
        live_files = scope_files(live, overlay.Override(root=None))
        sources = {d: v for d, v in p.desired.items()}
        rows = []
        for rel in sorted(set(installed) | set(live_files)):
            inst, lv = installed.get(rel), live_files.get(rel)
            if inst and lv:
                a, b = inst.read_bytes(), lv.read_bytes()
                src = sources.get(rel)
                if a == b:
                    cls = 'override' if src and src.source.startswith(('override', 'toolkit+append')) else 'identical'
                    rows.append((rel, cls, ''))
                    continue
                if src and src.source == 'toolkit' and src.src_path:
                    rel_src = str(Path(src.src_path).relative_to(REPO_ROOT))
                    if git_blob_id(b) in historical_blobs(rel_src):
                        rows.append((rel, 'toolkit-newer', f'live = an earlier version of {rel_src}'))
                        continue
                if is_python(rel, a) and same_ast(a, b):
                    rows.append((rel, 'neutral-text', 'same AST without docstrings'))
                    continue
                d = declared(ov, rel)
                if d:
                    rows.append((rel, 'declared', f'{d.get("class", "declared")}: {d["reason"]}'
                                 + (f' (proved by {d["test"]})' if d.get('test') else '')))
                    continue
                rows.append((rel, 'unexplained', f'differs ({len(a)} vs {len(b)} bytes)'))
            elif inst:
                rows.append((rel, 'added', sources[rel].source if rel in sources else ''))
            else:
                if ov.is_excluded(rel):
                    rows.append((rel, 'excluded', ''))
                    continue
                d = declared(ov, rel)
                if d:
                    rows.append((rel, 'declared', f'{d.get("class", "declared")}: {d["reason"]}'))
                else:
                    rows.append((rel, 'unexplained', 'only in the live tree'))
        hooks_rows = compare_hooks(live, target, ov)
        return {'rows': rows, 'hooks': hooks_rows, 'sources': {d: v.source for d, v in sources.items()}}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def compare_hooks(live: Path, target: Path, ov) -> list[tuple[str, str, str]]:
    home_live = str(live.parent)
    home_tmp = str(target.parent)
    live_ids = {tuple(k) for k in (settings_merge.normalise_identity(i, home_live)
                                   for i in settings_merge.identities(settings_merge.read(live / 'settings.json').get('hooks') or {}))}
    inst_ids = {tuple(k) for k in (settings_merge.normalise_identity(i, home_tmp)
                                   for i in settings_merge.identities(settings_merge.read(target / 'settings.json').get('hooks') or {}))}
    rows = []
    for ident in sorted(live_ids | inst_ids):
        label = ' '.join(ident)
        if ident in live_ids and ident in inst_ids:
            rows.append((label, 'identical', ''))
        elif ident in inst_ids:
            rows.append((label, 'added', ''))
        else:
            rows.append((label, 'unexplained', 'hook only in the live settings'))
    return rows


def summarise(result: dict) -> dict:
    counts: dict[str, int] = {}
    for _, cls, _ in result['rows']:
        counts[cls] = counts.get(cls, 0) + 1
    hooks: dict[str, int] = {}
    for _, cls, _ in result['hooks']:
        hooks[cls] = hooks.get(cls, 0) + 1
    srcs = result['sources']
    managed = [r for r, c, _ in result['rows'] if c not in ('excluded',) and r in srcs]
    from_override = sum(1 for r in managed if srcs[r].startswith('override') or srcs[r] == 'toolkit+append')
    from_toolkit = sum(1 for r in managed if srcs[r] in ('toolkit', 'config'))
    return {'files': counts, 'hooks': hooks, 'installed_from_toolkit': from_toolkit,
            'installed_from_override': from_override}


def cmd_equivalence(args) -> int:
    live = Path(args.live).expanduser().resolve()
    ov = overlay.load(resolve_override(args.override))
    mods = modules.load_many(args.modules.split(',') if args.modules else (ov.modules or ['openspec', 'core']))
    result = compare(live, mods, ov)
    summary = summarise(result)
    for rel, cls, why in result['rows'] + [(f'[hook] {h}', c, w) for h, c, w in result['hooks']]:
        if cls in ('identical', 'override') and not args.verbose:
            continue
        if cls == 'excluded' and not args.verbose:
            continue
        print(f'{cls:<13} {rel}  {why}'.rstrip())
    print('files:  ' + ', '.join(f'{k} {v}' for k, v in sorted(summary['files'].items())))
    print('hooks:  ' + ', '.join(f'{k} {v}' for k, v in sorted(summary['hooks'].items())))
    print(f'installed from toolkit {summary["installed_from_toolkit"]}, from override {summary["installed_from_override"]}')
    if args.json:
        Path(args.json).write_text(json.dumps({'summary': summary, **result}, indent=2) + '\n')
    unexplained = summary['files'].get('unexplained', 0) + summary['hooks'].get('unexplained', 0)
    print(f'equivalence: {"OK" if not unexplained else f"{unexplained} unexplained difference(s)"}')
    return 1 if unexplained else 0


def register(sub, common) -> None:
    p = sub.add_parser('equivalence', help='install toolkit + override into a temp HOME and compare with a live dir')
    common(p)
    p.add_argument('--live', required=True, help='live Claude dir to compare with (read only)')
    p.add_argument('--json', help='write the full result to this file')
    p.add_argument('-v', '--verbose', action='store_true')
    p.set_defaults(func=cmd_equivalence)
