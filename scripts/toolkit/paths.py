"""Where things live: repository root, target Claude dir, override dir, sandbox rules."""
from __future__ import annotations

import os
import pwd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_REL = 'toolkit/installed.json'
CONFIG_REL = 'toolkit/config'
BACKUPS_REL = 'backups'


def resolve_target(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get('CLAUDE_CONFIG_DIR')
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / '.claude').resolve()


def resolve_override(explicit: str | None) -> Path | None:
    """The override dir, or None when there is none (the toolkit works without one)."""
    if explicit is not None:
        if explicit == '':
            return None
        path = Path(explicit).expanduser().resolve()
        return path if path.is_dir() else None
    env = os.environ.get('CLAUDE_TOOLKIT_OVERRIDE')
    path = Path(env).expanduser() if env else Path('~/.config/claude-toolkit').expanduser()
    return path.resolve() if path.is_dir() else None


def real_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


def is_sandbox(target: Path) -> bool:
    """True when pieces installed at TARGET may be executed safely.

    Pieces resolve ~/.claude through HOME, so --target alone never isolates: executing a
    piece is safe only when HOME is not the real home and TARGET is $HOME/.claude.
    """
    home = Path(os.environ.get('HOME', '')).resolve()
    return home != real_home() and target == home / '.claude'
