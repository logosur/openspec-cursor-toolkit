"""Execute a plan (install) or undo the last install (uninstall)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from . import SCHEMA, settings_merge
from .paths import BACKUPS_REL, MANIFEST_REL
from .plan import Plan, block_strip, read_manifest, sha

PREEXISTING = '@preexisting'


def write_atomic(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        if mode is not None:
            os.chmod(tmp, mode)
        elif path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _backup_dir(target: Path, stamp: str) -> Path:
    return target / BACKUPS_REL / f'toolkit-{stamp}'


def install(plan: Plan, toolkit_version: str) -> dict:
    target = plan.target
    stamp = time.strftime('%Y%m%d-%H%M%S')
    previous = plan.previous
    originals: dict[str, str | None] = dict(previous.get('originals', {}))
    backup_dir = _backup_dir(target, stamp)
    for action in plan.actions:
        dest, path = action.dest, target / action.dest
        if action.kind == 'create':
            originals.setdefault(dest, None)
            write_atomic(path, action.desired.content, action.desired.mode)
        elif action.kind == 'update':
            if action.backup:
                bpath = backup_dir / dest
                bpath.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, bpath)
                originals.setdefault(dest, str(bpath.relative_to(target)))
            write_atomic(path, action.desired.content, action.desired.mode)
        elif action.kind == 'chmod':
            # the content was already there before the toolkit: uninstall leaves it (and its new mode)
            originals.setdefault(dest, PREEXISTING)
            os.chmod(path, action.desired.mode)
        elif action.kind == 'unchanged':
            # identical content was already there before the toolkit: uninstall must leave it
            originals.setdefault(dest, PREEXISTING)
        elif action.kind == 'remove':
            if path.is_file():
                path.unlink()
    settings_path = target / 'settings.json'
    hooks_added = [settings_merge.key_of(r) for r in plan.hooks_to_add]
    if plan.hooks_to_add:
        settings = settings_merge.read(settings_path)
        if settings_path.exists() and 'settings.json' not in originals:
            bpath = backup_dir / 'settings.json'
            bpath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(settings_path, bpath)
            originals['settings.json'] = str(bpath.relative_to(target))
        elif not settings_path.exists():
            originals.setdefault('settings.json', None)
        settings_merge.add(settings, plan.hooks_to_add)
        write_atomic(settings_path, settings_merge.dumps(settings), 0o600 if not settings_path.exists() else None)
    manifest = {
        'schema': SCHEMA,
        'toolkit_version': toolkit_version,
        'installed_at': stamp,
        'modules': plan.modules,
        'files': {a.dest: {'sha256': sha(a.desired.content), 'source': a.desired.source,
                           'module': a.desired.module, 'merge': a.desired.merge}
                  for a in plan.actions if a.desired is not None},
        'hooks_added': [list(k) for k in previous.get('hooks_added', [])] + hooks_added,
        'originals': originals,
    }
    write_atomic(target / MANIFEST_REL, (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
    return manifest


def uninstall(target: Path, dry_run: bool = False) -> list[str]:
    """Undo the install recorded in the manifest. Returns report lines."""
    manifest = read_manifest(target)
    if not manifest:
        return ['nothing to uninstall: no toolkit manifest in ' + str(target)]
    report: list[str] = []
    originals = manifest.get('originals', {})
    for dest, info in sorted(manifest.get('files', {}).items()):
        path = target / dest
        if not path.is_file():
            report.append(f'gone      {dest}')
            continue
        current = path.read_bytes()
        if sha(current) != info['sha256']:
            report.append(f'kept      {dest} (edited after install)')
            continue
        orig = originals.get(dest)
        if orig == PREEXISTING:
            report.append(f'kept      {dest} (was already there, identical)')
            continue
        if info.get('merge') == 'block' and orig is None:
            stripped = block_strip(current)
            report.append(f'unblock   {dest}')
            if not dry_run:
                if stripped.strip():
                    write_atomic(path, stripped)
                else:
                    path.unlink()
            continue
        if orig:
            report.append(f'restore   {dest}')
            if not dry_run:
                write_atomic(path, (target / orig).read_bytes())
        else:
            report.append(f'remove    {dest}')
            if not dry_run:
                path.unlink()
                _prune_empty(path.parent, target)
    keys = [tuple(k) for k in manifest.get('hooks_added', [])]
    settings_path = target / 'settings.json'
    if keys and settings_path.exists():
        settings = settings_merge.read(settings_path)
        settings, n = settings_merge.remove(settings, keys)
        report.append(f'hooks     removed {n} of {len(keys)} toolkit entries from settings.json')
        if not dry_run:
            if not settings and originals.get('settings.json', 'x') is None:
                settings_path.unlink()
            else:
                write_atomic(settings_path, settings_merge.dumps(settings))
    if not dry_run:
        (target / MANIFEST_REL).unlink()
        _prune_empty((target / MANIFEST_REL).parent, target)
    return report


def _prune_empty(directory: Path, stop: Path) -> None:
    while directory != stop and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent
