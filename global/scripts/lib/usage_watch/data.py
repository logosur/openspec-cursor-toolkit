"""Aggregates rebuilt on read from the stored records (design D2, D3).

Calls are deduplicated by id across all day files, the last record winning for the usage; the tool calls of every
record of an id are kept, and the last text. Records after `now` are ignored (a simulated clock earlier than the data).
"""
from __future__ import annotations

import glob
import json
import os
import re

from . import attribution
from . import config as C
from .collect import AUTOMATIC
from .state import read_json

TOKENS = ('in', 'cw5', 'cw1h', 'cr', 'out')


def _records(state_dir: str, sub: str):
    for path in sorted(glob.glob(os.path.join(glob.escape(state_dir), sub, '*.jsonl'))):
        try:
            with open(path, encoding='utf-8') as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and isinstance(rec.get('id'), str) and isinstance(rec.get('ts'), (int, float)):
                        yield rec
        except OSError:
            continue


def price_of(model: str, prices: dict):
    for pattern, weights in prices.items():
        if re.search(pattern, model):
            return weights
    return None


class Data:
    def __init__(self, cfg: dict, now_ts: float):
        self.cfg = cfg
        self.now = now_ts
        state_dir = C.path(cfg, 'state_dir')
        calls = {}
        for rec in _records(state_dir, 'calls'):
            if rec['ts'] > now_ts:
                continue
            old = calls.get(rec['id'])
            if old is not None:
                tools = list(old.get('tools') or [])
                tools += [t for t in rec.get('tools') or [] if t not in tools]
                rec = dict(rec, tools=tools, text=rec.get('text') or old.get('text'))
            calls[rec['id']] = rec
        self.turns = {}
        for rec in _records(state_dir, 'turns'):
            if rec['ts'] <= now_ts:
                self.turns[rec['id']] = rec
        self.sessions_meta = read_json(os.path.join(state_dir, 'sessions.json'), {})
        self.info = attribution.sessions_info(cfg, self.sessions_meta)
        for turn in self.turns.values():
            if turn.get('origin') == 'human' and self.info.get(turn['session'], {}).get('routine'):
                turn['origin'] = 'routine'
        self.unpriced = {}
        for call in calls.values():
            weights = price_of(call.get('model') or '', cfg['prices'])
            tokens = sum(int(call.get(k) or 0) for k in TOKENS)
            call['tokens'] = tokens
            if weights is None:
                call['units'] = 0.0
                self.unpriced[call['model']] = self.unpriced.get(call['model'], 0) + tokens
            else:
                call['units'] = sum(int(call.get(k) or 0) * w for k, w in zip(TOKENS, weights)) / 1e6
            if call.get('kind') == 'subagent':
                call['origin'] = 'subagent'
            else:
                turn = self.turns.get(call.get('turn')) if call.get('turn') else None
                call['origin'] = turn['origin'] if turn else 'other'
        self.calls = sorted(calls.values(), key=lambda c: (c['ts'], c['id']))
        self.last_call = {}
        for call in self.calls:
            self.last_call[call['session']] = call['ts']

    def session(self, sid: str) -> dict:
        return self.info.get(sid) or {'project': 'unknown', 'project_root': '', 'role': 'worker', 'app_id': None,
                                      'title': None, 'cwd': None, 'routine': False, 'open': False}

    def since(self, start: float, end: float | None = None):
        end = self.now if end is None else end
        return [c for c in self.calls if start < c['ts'] <= end]

    @staticmethod
    def is_automatic(origin: str) -> bool:
        return origin in AUTOMATIC
