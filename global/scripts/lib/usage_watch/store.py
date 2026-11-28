"""The findings store (design D6): stable ids, never-repeat rule, exclusive lock, corrupt file moved aside."""
from __future__ import annotations

import hashlib
import os

from . import config as C
from .state import Locked, read_json, write_json

STATES = ('new', 'minor', 'asked', 'authorized', 'rejected', 'applied', 'measured')


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


def _move(f: dict, state: str, stamp: str, **extra) -> None:
    f['state'] = state
    f.setdefault('history', []).append({'state': state, 'at': stamp, 'by': 'detect', 'ref': None, **extra})


def merge(cfg: dict, candidates: list[dict], now_ts: float, floor: float = 0.0, retire=None) -> tuple[list[str], list[str]]:
    """Add each candidate whose id is not stored, whatever the stored state; refresh evidence, saving and the proposal
    and undo texts (which follow the configuration) only while `new` or `minor`.

    A finding whose saving is under `floor` is stored as `minor` (never reported, never asked); each run re-evaluates it:
    a `minor` one at or over the floor becomes `new`, a `new` one under it becomes `minor`. Any other state is never
    touched. `retire(finding)` (the detector's) names the stored `new` findings this run no longer raises that should
    stop being one (folded into a group, session no longer live, duplicate): they become `minor` too.
    Returns the ids that are `new` for the first time (or again) and the ids refreshed.
    """
    added, refreshed = [], []
    with locked(cfg):
        findings = read(cfg)
        stamp = C.iso(now_ts)
        seen = set()
        for cand in candidates:
            seen.add(cand['id'])
            below = cand['saving_units_per_day'] < floor
            old = findings.get(cand['id'])
            if old is None:
                state = 'minor' if below else 'new'
                findings[cand['id']] = dict(cand, state=state, first_seen=stamp, last_seen=stamp,
                                            history=[{'state': state, 'at': stamp, 'by': 'detect', 'ref': None}])
                if state == 'new':
                    added.append(cand['id'])
            elif old.get('state') in ('new', 'minor'):
                # the texts follow the configuration until the finding is asked about; after that they stay as asked
                old.update(last_seen=stamp, evidence=cand['evidence'], saving_units_per_day=cand['saving_units_per_day'],
                           proposal=cand.get('proposal', old.get('proposal')), undo=cand.get('undo', old.get('undo')))
                if old['state'] == 'new' and below:
                    _move(old, 'minor', stamp)
                elif old['state'] == 'minor' and not below:
                    _move(old, 'new', stamp)
                    added.append(cand['id'])
                else:
                    refreshed.append(cand['id'])
        if retire is not None:
            for fid, f in findings.items():
                if f.get('state') == 'new' and fid not in seen:
                    why = retire(dict(f, id=fid))
                    if why:
                        _move(f, 'minor', stamp, reason=why[0])
                        if why[1]:
                            f['folded_into'] = why[1]
        write(cfg, findings)
    return added, refreshed


def counts(findings: dict) -> dict:
    out = {s: 0 for s in STATES}
    for f in findings.values():
        if f.get('state') in out:
            out[f['state']] += 1
    return out
