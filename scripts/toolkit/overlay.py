"""The override layer: override.yaml, files/, append/, config/, hooks/, removals.

Precedence for a destination (highest first): override files/<dest>; toolkit file followed
by override append/<dest>; toolkit file. `remove:` drops a toolkit destination.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SKIP_NAMES = {'__pycache__', '.DS_Store', '.git'}


class OverrideError(Exception):
    pass


@dataclass
class Override:
    root: Path | None
    modules: list[str] | None = None
    remove: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    equivalence: list[dict] = field(default_factory=list)
    files: dict[str, Path] = field(default_factory=dict)
    appends: dict[str, Path] = field(default_factory=dict)
    configs: dict[str, dict] = field(default_factory=dict)
    hooks: list[Path] = field(default_factory=list)

    def removed(self, dest: str) -> bool:
        return any(dest == r.rstrip('/') or dest.startswith(r.rstrip('/') + '/') or fnmatch.fnmatch(dest, r)
                   for r in self.remove)

    def is_excluded(self, dest: str) -> bool:
        return any(fnmatch.fnmatch(dest, g) or dest.startswith(g.rstrip('*').rstrip('/') + '/')
                   if g.endswith('/**') else fnmatch.fnmatch(dest, g) for g in self.excluded)


def _tree(base: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not base.is_dir():
        return out
    for path in sorted(base.rglob('*')):
        rel = path.relative_to(base)
        if any(p in SKIP_NAMES for p in rel.parts) or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise OverrideError(f'{path}: symlinks are never installed; copy the file instead')
        if path.is_file():
            out[rel.as_posix()] = path
    return out


def load(root: Path | None) -> Override:
    if root is None:
        return Override(root=None)
    meta_path = root / 'override.yaml'
    meta = yaml.safe_load(meta_path.read_text(encoding='utf-8')) if meta_path.is_file() else {}
    meta = meta or {}
    if meta.get('schema', 1) != 1:
        raise OverrideError(f'{meta_path}: unsupported schema {meta.get("schema")!r}')
    ov = Override(root=root, modules=meta.get('modules'), remove=list(meta.get('remove') or []),
                  excluded=list(meta.get('excluded') or []), equivalence=list(meta.get('equivalence') or []))
    ov.files = _tree(root / 'files')
    ov.appends = _tree(root / 'append')
    for path in sorted((root / 'config').glob('*.json')) if (root / 'config').is_dir() else []:
        try:
            ov.configs[path.stem] = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise OverrideError(f'{path}: invalid JSON ({exc})') from exc
    ov.hooks = sorted((root / 'hooks').glob('*.json')) if (root / 'hooks').is_dir() else []
    return ov
