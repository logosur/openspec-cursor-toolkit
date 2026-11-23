"""Module manifests: what each module installs, its hooks, configs and requirements."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .paths import REPO_ROOT

MODULES_DIR = REPO_ROOT / 'global' / 'modules'
SKIP_NAMES = {'__pycache__', '.DS_Store'}
SKIP_SUFFIXES = ('.pyc',)


class ManifestError(Exception):
    pass


# A module that widens what sessions may do unattended is never here: it is opt-in.
DEFAULT_MODULES = ['openspec', 'core', 'devtools']

@dataclass
class FileEntry:
    src: Path          # absolute source file
    dest: str          # relative to the Claude dir
    mode: int
    module: str
    merge: str = 'replace'   # replace | block (managed block inside a user file)


@dataclass
class Module:
    name: str
    summary: str
    requires: dict
    optional: dict
    files: list[FileEntry] = field(default_factory=list)
    hooks: list[Path] = field(default_factory=list)
    config: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def available() -> list[str]:
    return sorted(p.stem for p in MODULES_DIR.glob('*.yaml'))


def _expand(entry: dict, module: str) -> list[FileEntry]:
    src = REPO_ROOT / entry['src']
    dest = entry['dest']
    mode = int(str(entry.get('mode', '0644')), 8)
    merge = entry.get('merge', 'replace')
    excludes = [e.rstrip('/') for e in entry.get('exclude', [])]
    if entry['src'].endswith('/'):
        if not src.is_dir():
            raise ManifestError(f'{module}: source directory {entry["src"]} does not exist')
        out = []
        for path in sorted(src.rglob('*')):
            rel = path.relative_to(src)
            if any(part in SKIP_NAMES for part in rel.parts) or path.name.endswith(SKIP_SUFFIXES):
                continue
            if any(rel.as_posix() == e or rel.as_posix().startswith(e + '/') for e in excludes):
                continue
            if path.is_symlink():
                raise ManifestError(f'{module}: {path.relative_to(REPO_ROOT)} is a symlink; symlinks are never installed')
            if path.is_file():
                fmode = 0o755 if path.stat().st_mode & 0o111 else mode
                out.append(FileEntry(path, f'{dest.rstrip("/")}/{rel.as_posix()}', fmode, module, merge))
        return out
    if not src.is_file():
        raise ManifestError(f'{module}: source {entry["src"]} does not exist')
    return [FileEntry(src, dest, mode, module, merge)]


def load(name: str) -> Module:
    path = MODULES_DIR / f'{name}.yaml'
    if not path.is_file():
        raise ManifestError(f'unknown module {name!r} (available: {", ".join(available())})')
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if data.get('name') != name:
        raise ManifestError(f'{path.name}: name must be {name!r}')
    mod = Module(name=name, summary=data.get('summary', ''), requires=data.get('requires') or {},
                 optional=data.get('optional') or {}, config=list(data.get('config') or []),
                 depends=list(data.get('depends') or []), notes=list(data.get('notes') or []))
    for entry in data.get('files') or []:
        mod.files.extend(_expand(entry, name))
    for frag in data.get('hooks') or []:
        fpath = REPO_ROOT / frag
        if not fpath.is_file():
            raise ManifestError(f'{name}: hook fragment {frag} does not exist')
        mod.hooks.append(fpath)
    return mod


def load_many(names: list[str]) -> list[Module]:
    """Load NAMES plus their dependencies, dependencies first; reject duplicate destinations."""
    ordered: list[Module] = []
    seen: set[str] = set()

    def visit(n: str, stack: tuple = ()):
        if n in stack:
            raise ManifestError(f'module dependency cycle: {" -> ".join(stack + (n,))}')
        if n in seen:
            return
        mod = load(n)
        for dep in mod.depends:
            visit(dep, stack + (n,))
        seen.add(n)
        ordered.append(mod)

    for n in names:
        visit(n)
    owner: dict[str, str] = {}
    for mod in ordered:
        for f in mod.files:
            if f.dest in owner:
                raise ManifestError(f'destination {f.dest} is installed by both {owner[f.dest]} and {mod.name}')
            owner[f.dest] = mod.name
    return ordered
