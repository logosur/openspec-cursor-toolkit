"""Per-piece configuration: toolkit defaults overlaid by the override, one file per piece."""
from __future__ import annotations

import json
from pathlib import Path

from .paths import REPO_ROOT

DEFAULTS_DIR = REPO_ROOT / 'global' / 'config'


def defaults(piece: str) -> dict:
    path = DEFAULTS_DIR / f'{piece}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def resolve(pieces: list[str], override_configs: dict[str, dict]) -> dict[str, dict]:
    """Shallow merge per piece. Override configs for pieces no module declares are kept too
    (they configure extra pieces the override itself adds)."""
    out: dict[str, dict] = {}
    for piece in sorted(set(pieces) | set(override_configs)):
        merged = dict(defaults(piece))
        merged.update(override_configs.get(piece, {}))
        out[piece] = merged
    return out


def render(values: dict) -> bytes:
    return (json.dumps(values, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
