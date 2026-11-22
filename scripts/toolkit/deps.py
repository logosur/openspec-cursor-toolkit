"""Check the binaries and Python version the enabled modules need."""
from __future__ import annotations

import platform
import shutil
import sys

from .modules import Module


def check(mods: list[Module]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors, warnings = [], []
    for mod in mods:
        req = mod.requires or {}
        want = str(req.get('python', '3.10'))
        major, minor = (int(x) for x in want.split('.')[:2])
        if sys.version_info < (major, minor):
            errors.append(f'{mod.name}: needs Python >= {want} (running {platform.python_version()})')
        osname = req.get('os')
        if osname and platform.system().lower() != osname:
            errors.append(f'{mod.name}: needs {osname} (this is {platform.system()})')
        for binary in req.get('binaries') or []:
            if not shutil.which(binary):
                errors.append(f'{mod.name}: required binary {binary!r} not found on PATH')
        for binary, why in _optional(mod.optional).items():
            if not shutil.which(binary):
                warnings.append(f'{mod.name}: optional binary {binary!r} not found; {why}')
    return errors, warnings


def _optional(spec) -> dict[str, str]:
    binaries = (spec or {}).get('binaries') or {}
    if isinstance(binaries, list):
        return {b: 'the pieces that use it will not work' for b in binaries}
    return dict(binaries)
