"""The findings store (design D6): stable ids, never-repeat rule, exclusive lock, corrupt file moved aside."""
from __future__ import annotations

import hashlib
import os

from . import config as C
from .state import Locked, read_json, write_json

STATES = ('new', 'asked', 'authorized', 'rejected', 'applied', 'measured')


def finding_id(rule: str, scope_kind: str, scope_id: str, discriminator: str = '') -> str:
    digest = hashlib.sha1(f'{rule}|{scope_kind}|{scope_id}|{discriminator}'.encode('utf-8')).hexdigest()[:10]
    return f'{rule}-{digest}'


def store_path(cfg: dict) -> str:
    return os.path.join(C.path(cfg, 'state_dir'), 'findings.json')


def read(cfg: dict) -> dict:
    """id -> finding. A corrupt store is moved aside and an empty one used (never raised)."""
    data = read_json(store_path(cfg), {}, aside=True)
    findings = data.get('findings') if isinstance(data.get('findings'), dict) else {}
    return {k: v for k, v in findings.items() if isinstance(v, dict)}


def write(cfg: dict, findings: dict) -> None:
    write_json(store_path(cfg), {'findings': findings})


def locked(cfg: dict) -> Locked:
    return Locked(store_path(cfg))


def merge(cfg: dict, candidates: list[dict], now_ts: float) -> tuple[list[str], list[str]]:
    """Add each candidate whose id is not stored, whatever the stored state; refresh evidence only while `new`."""
    added, refreshed = [], []
    with locked(cfg):
        findings = read(cfg)
        stamp = C.iso(now_ts)
        for cand in candidates:
            old = findings.get(cand['id'])
            if old is None:
                findings[cand['id']] = dict(cand, state='new', first_seen=stamp, last_seen=stamp,
                                            history=[{'state': 'new', 'at': stamp, 'by': 'detect', 'ref': None}])
                added.append(cand['id'])
            elif old.get('state') == 'new':
                old.update(last_seen=stamp, evidence=cand['evidence'],
                           saving_units_per_day=cand['saving_units_per_day'])
                refreshed.append(cand['id'])
        write(cfg, findings)
    return added, refreshed


def counts(findings: dict) -> dict:
    out = {s: 0 for s in STATES}
    for f in findings.values():
        if f.get('state') in out:
            out[f['state']] += 1
    return out
