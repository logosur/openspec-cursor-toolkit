"""Drift between the live Claude dir, the install plan and the override; pull live changes back."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from . import modules, overlay, plan as plan_mod
from .modules import DEFAULT_MODULES
from .paths import REPO_ROOT, resolve_override, resolve_target

LOCK = 'override.lock.json'
SCOPES = ('CLAUDE.md', 'rules', 'rules-detail', 'skills', 'commands', 'agents', 'scripts', 'hooks',
          'scheduled-tasks', 'docs', 'toolkit/config')
ALWAYS_EXCLUDED = ('*.bak*', '*/__pycache__/*', '*.pyc', '*/node_modules/*', 'skills/synced/*', 'skills/.trash/*')


def scope_files(root: Path, ov: overlay.Override) -> dict[str, Path]:
    import fnmatch
    out = {}
    for scope in SCOPES:
        base = root / scope
        paths = [base] if base.is_file() else (sorted(base.rglob('*')) if base.is_dir() else [])
        for path in paths:
            if path.is_dir():
                continue
            rel = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel, g) for g in ALWAYS_EXCLUDED) or ov.is_excluded(rel):
                continue
            out[rel] = path
    return out


def read_lock(ov_root: Path | None) -> dict:
    if not ov_root or not (ov_root / LOCK).is_file():
        return {}
    return json.loads((ov_root / LOCK).read_text(encoding='utf-8'))


def toolkit_sources(mods) -> dict[str, Path]:
    return {f.dest: f.src for m in mods for f in m.files}


def classify(target: Path, mods, ov) -> list[tuple[str, str]]:
    p = plan_mod.build(target, mods, ov)
    manifest = p.previous.get('files', {})
    lock = read_lock(ov.root)
    sources = toolkit_sources(mods)
    out = []
    for a in p.actions:
        if a.kind == 'unchanged':
            state = 'in-sync'
        elif a.kind == 'create':
            state = 'missing'
        elif a.kind == 'update':
            live = (target / a.dest).read_bytes()
            info = manifest.get(a.dest)
            if info and plan_mod.sha(live) == info['sha256']:
                state = 'toolkit-changed'
            else:
                state = 'live-changed'
        else:
            state = a.kind
        out.append((a.dest, state))
    for dest, base in sorted(lock.get('files', {}).items()):
        src = sources.get(dest)
        if src and src.is_file() and plan_mod.sha(src.read_bytes()) != base:
            out.append((dest, 'override-base-changed'))
    desired = set(p.desired)
    for rel in scope_files(target, ov):
        if rel not in desired:
            out.append((rel, 'untracked'))
    return out


def cmd_drift(args) -> int:
    target = resolve_target(args.target)
    ov = overlay.load(resolve_override(args.override))
    mods = modules.load_many(args.modules.split(',') if args.modules else (ov.modules or DEFAULT_MODULES))
    rows = classify(target, mods, ov)
    counts: dict[str, int] = {}
    for dest, state in rows:
        counts[state] = counts.get(state, 0) + 1
        if state != 'in-sync' and (args.verbose or state != 'untracked'):
            print(f'{state:<22} {dest}')
    print('drift: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
    return 0 if set(counts) <= {'in-sync'} else 1


def _privacy_checker():
    spec = importlib.util.spec_from_file_location('privacy_check', REPO_ROOT / 'scripts' / 'privacy-check.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['privacy_check'] = mod
    spec.loader.exec_module(mod)
    return mod


def cmd_pull(args) -> int:
    target = resolve_target(args.target)
    ov_root = resolve_override(args.override)
    ov = overlay.load(ov_root)
    mods = modules.load_many(args.modules.split(',') if args.modules else (ov.modules or DEFAULT_MODULES))
    live = target / args.dest
    if not live.is_file():
        print(f'ERROR {live} does not exist')
        return 2
    data = live.read_bytes()
    sources = toolkit_sources(mods)
    if args.to == 'toolkit':
        src = sources.get(args.dest)
        if not src:
            print(f'ERROR {args.dest} is not a toolkit file; pull it to the override instead')
            return 2
        pc = _privacy_checker()
        override_dir = ov_root or Path('~/.config/claude-toolkit').expanduser()
        terms, quotes = pc.load_private(override_dir / 'privacy-denylist.txt', override_dir)
        checker = pc.Checker(pc.load_patterns(REPO_ROOT), pc.load_allowlist(REPO_ROOT), terms, quotes)
        checker.check_text(str(src.relative_to(REPO_ROOT)), data.decode('utf-8', 'replace'))
        if checker.findings:
            for f in checker.findings:
                print(f.render())
            print('pull refused: the content is not publishable; pull it to the override instead')
            return 1
        if args.dry_run:
            print(f'would write {src.relative_to(REPO_ROOT)}')
            return 0
        src.write_bytes(data)
        print(f'wrote {src.relative_to(REPO_ROOT)} (privacy check clean)')
        return 0
    if not ov_root:
        print('ERROR no override directory (create ~/.config/claude-toolkit or pass --override)')
        return 2
    dest = ov_root / 'files' / args.dest
    if args.dry_run:
        print(f'would write {dest}')
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    dest.chmod(live.stat().st_mode & 0o777)
    lock = read_lock(ov_root)
    if args.dest in sources:
        lock.setdefault('files', {})[args.dest] = plan_mod.sha(sources[args.dest].read_bytes())
        (ov_root / LOCK).write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
    print(f'wrote {dest}')
    return 0


def register(sub, common) -> None:
    p = sub.add_parser('drift', help='compare the live Claude dir with what an install would produce')
    common(p)
    p.add_argument('-v', '--verbose', action='store_true', help='also list untracked files')
    p.set_defaults(func=cmd_drift)
    q = sub.add_parser('pull', help='bring a live file back to the override (default) or to the toolkit')
    common(q)
    q.add_argument('dest', help='path relative to the Claude dir, e.g. rules/x.md')
    q.add_argument('--to', choices=('override', 'toolkit'), default='override')
    q.add_argument('--dry-run', action='store_true')
    q.set_defaults(func=cmd_pull)
