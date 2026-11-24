"""Build the desired state (files, configs, hooks) and the actions that reach it."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config as config_mod
from . import settings_merge
from .modules import Module
from .overlay import Override
from .paths import CONFIG_REL, MANIFEST_REL

BLOCK_BEGIN = '<!-- claude-toolkit:begin (managed block, edit through the toolkit or its override) -->'
BLOCK_END = '<!-- claude-toolkit:end -->'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Desired:
    dest: str
    content: bytes
    mode: int
    source: str           # toolkit | toolkit+append | override | override-extra | config
    module: str
    merge: str = 'replace'
    src_path: str = ''


@dataclass
class Action:
    kind: str             # create | update | chmod | unchanged | remove | keep-edited
    dest: str
    desired: Desired | None = None
    backup: bool = False


@dataclass
class Plan:
    target: Path
    modules: list[str]
    desired: dict[str, Desired]
    actions: list[Action]
    hook_records: list[dict]
    hooks_to_add: list[dict]
    previous: dict
    configs: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.actions:
            out[a.kind] = out.get(a.kind, 0) + 1
        out['hooks-add'] = len(self.hooks_to_add)
        return out

    def changes(self) -> bool:
        return any(a.kind in ('create', 'update', 'chmod', 'remove') for a in self.actions) or bool(self.hooks_to_add)


def read_manifest(target: Path) -> dict:
    path = target / MANIFEST_REL
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def block_merge(existing: bytes | None, block: bytes) -> bytes:
    body = block.decode('utf-8').rstrip('\n')
    managed = f'{BLOCK_BEGIN}\n{body}\n{BLOCK_END}\n'
    if existing is None:
        return managed.encode('utf-8')
    text = existing.decode('utf-8')
    if BLOCK_BEGIN in text and BLOCK_END in text:
        head, rest = text.split(BLOCK_BEGIN, 1)
        _, tail = rest.split(BLOCK_END, 1)
        return (head + managed.rstrip('\n') + tail).encode('utf-8')
    sep = '' if text.endswith('\n\n') else ('\n' if text.endswith('\n') else '\n\n')
    return (text + sep + managed).encode('utf-8')


def block_strip(content: bytes) -> bytes:
    text = content.decode('utf-8')
    if BLOCK_BEGIN not in text:
        return content
    head, rest = text.split(BLOCK_BEGIN, 1)
    _, tail = rest.split(BLOCK_END, 1)
    return (head.rstrip('\n') + ('\n' if head.strip() else '') + tail.lstrip('\n')).encode('utf-8')


def desired_files(mods: list[Module], ov: Override) -> tuple[dict[str, Desired], dict[str, dict]]:
    out: dict[str, Desired] = {}
    for mod in mods:
        for f in mod.files:
            if ov.removed(f.dest):
                continue
            data = f.src.read_bytes()
            source, merge = 'toolkit', f.merge
            if f.dest in ov.files:
                data, source, merge = ov.files[f.dest].read_bytes(), 'override', 'replace'
            elif f.dest in ov.appends:
                extra = ov.appends[f.dest].read_bytes()
                data = data.rstrip(b'\n') + b'\n\n' + extra
                source = 'toolkit+append'
            out[f.dest] = Desired(f.dest, data, f.mode, source, mod.name, merge, str(f.src))
    for dest, path in ov.files.items():
        if dest not in out and not ov.removed(dest):
            mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            out[dest] = Desired(dest, path.read_bytes(), mode, 'override-extra', 'override', 'replace', str(path))
    pieces = [p for m in mods for p in m.config]
    configs = config_mod.resolve(pieces, ov.configs)
    for piece, values in configs.items():
        dest = f'{CONFIG_REL}/{piece}.json'
        out[dest] = Desired(dest, config_mod.render(values), 0o644, 'config', 'config')
    return out, configs


def hook_records(mods: list[Module], ov: Override, target: Path) -> list[dict]:
    records = []
    for frag_path in [h for m in mods for h in m.hooks] + list(ov.hooks):
        fragment = json.loads(frag_path.read_text(encoding='utf-8'))
        for rec in settings_merge.fragment_entries(fragment, target):
            cmd = settings_merge.normalise(rec['hook']['command'])
            if any(ov.removed(r) and r.rstrip('/') in cmd for r in ov.remove):
                continue
            rec['fragment'] = frag_path.name
            records.append(rec)
    return records


def build(target: Path, mods: list[Module], ov: Override) -> Plan:
    desired, configs = desired_files(mods, ov)
    previous = read_manifest(target)
    prev_files = previous.get('files', {})
    actions: list[Action] = []
    for dest, d in sorted(desired.items()):
        path = target / dest
        current = path.read_bytes() if path.is_file() else None
        if d.merge == 'block':
            d.content = block_merge(current, d.content)
        if current is None:
            actions.append(Action('create', dest, d))
        elif current == d.content and (path.stat().st_mode & 0o777) == d.mode:
            actions.append(Action('unchanged', dest, d))
        elif current == d.content:
            # same bytes, other permission bits: fix the mode only. Rewriting would bump the mtime, and running
            # sessions read a newer mtime as a changed skill or hook.
            actions.append(Action('chmod', dest, d))
        else:
            ours = dest in prev_files and sha(current) == prev_files[dest]['sha256']
            needs_backup = not ours and dest not in previous.get('originals', {})
            actions.append(Action('update', dest, d, backup=needs_backup and current != d.content))
    for dest, info in sorted(prev_files.items()):
        if dest in desired:
            continue
        path = target / dest
        if path.is_file() and sha(path.read_bytes()) != info['sha256']:
            actions.append(Action('keep-edited', dest))
        else:
            actions.append(Action('remove', dest))
    records = hook_records(mods, ov, target)
    settings = settings_merge.read(target / 'settings.json')
    to_add = settings_merge.plan_add(settings, records)
    notes = [n for m in mods for n in m.notes]
    return Plan(target, [m.name for m in mods], desired, actions, records, to_add, previous, configs, notes)
