"""The nine detection rules (design D5) and the candidates they produce (design D6).

Every rule works on the stored records as of `now`, every threshold is a key of the config piece, and each rule has a
firing case and a healthy case in the tests and in `self-test`. Session rules look at the last 24 hours; `pace` uses
its own windows. A candidate is a complete finding without state; `store.merge` decides whether it is new.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import config as C
from .data import Data
from .store import finding_id

try:
    from toolkit_config import load as _load_piece
except ImportError:
    def _load_piece(piece, defaults=None):
        return dict(defaults or {})

DAY = 86400
HOUR = 3600
NOTE_RULES = ('loop', 'empty-wakes', 'large-context', 'idle-rewrite', 'pace')
MODEL_RULES = ('role-model', 'expensive-automation')
CONFIG_RULES = ('expensive-subagents', 'advisor-excess')
ALL_RULES = ('loop', 'empty-wakes', 'role-model', 'expensive-subagents', 'advisor-excess', 'large-context',
             'idle-rewrite', 'pace', 'expensive-automation')
GATE_PIECE, GATE_KEY, GATE_VALUE = 'agent-model-gate', 'enabled', True


def _units(calls) -> float:
    return sum(c['units'] for c in calls)


def _locations(calls, limit=10) -> list[str]:
    return [c['loc'] for c in calls[-limit:] if c.get('loc')]


def _dominant_model(calls) -> str | None:
    by = defaultdict(float)
    for c in calls:
        by[c['model']] += c['units'] or c.get('tokens', 0) / 1e6
    return max(by, key=by.get) if by else None


class Detector:
    def __init__(self, cfg: dict, now_ts: float, data: Data | None = None):
        self.cfg = cfg
        self.now = now_ts
        self.d = data or Data(cfg, now_ts)
        self.expensive = re.compile(cfg['expensive_model_pattern'])
        self.mark = re.compile(cfg['escalation_mark_pattern'])
        self.panel = re.compile(cfg['panel_pattern'])
        self.day_start = now_ts - DAY
        self.by_session = defaultdict(lambda: defaultdict(list))   # session -> kind -> calls (last 24 h)
        for c in self.d.since(self.day_start):
            self.by_session[c['session']][c['kind']].append(c)
        self.turns = defaultdict(list)
        for t in self.d.turns.values():
            if self.day_start < t['ts'] <= now_ts:
                self.turns[t['session']].append(t)
        for ts in self.turns.values():
            ts.sort(key=lambda t: (t['ts'], t['id']))
        self.config_triggers = []   # (rule, session, figures)
        self.project_roots = {}     # project name -> main checkout, for the queue of a project-scoped finding
        for info in self.d.info.values():
            if info.get('project_root'):
                self.project_roots.setdefault(info['project'], info['project_root'])

    # ------------------------------------------------------------------ candidates
    def candidate(self, rule, scope_kind, scope_id, disc, evidence, calls, saving=None, session=None):
        info = self.d.session(session) if session else {}
        project = info.get('project') if session else (scope_id if scope_kind == 'project' else None)
        root = info.get('project_root') if session else self.project_roots.get(scope_id)
        text = self.cfg['proposals'][rule]
        proposal = {'kind': 'note', 'text': text['proposal']}
        applier = 'project-supervisor'
        target = info.get('app_id') if session else None
        if rule in MODEL_RULES and target and self.cfg['cheap_model']:
            proposal.update(kind='session-model', field='model', value=self.cfg['cheap_model'])
            applier = 'usage-role'
        return {
            'id': finding_id(rule, scope_kind, scope_id, disc), 'rule': rule,
            'scope': {'kind': scope_kind, 'id': scope_id}, 'project': project, 'project_root': root or None,
            'role': info.get('role'), 'evidence': dict(evidence, locations=_locations(calls)),
            'saving_units_per_day': round(saving if saving is not None else _units(calls), 4),
            'proposal': proposal, 'applier': applier, 'undo': text['undo'], 'target_app_id': target,
        }

    # ------------------------------------------------------------------ rules
    def loop(self, sid):
        cfg, out = self.cfg, []
        mains = self.by_session[sid]['main']
        by_turn = defaultdict(list)
        for c in mains:
            if c.get('turn'):
                by_turn[c['turn']].append(c)
        ends = []
        for t in self.turns.get(sid, []):
            texts = [c for c in by_turn.get(t['id'], []) if c.get('text')]
            ends.append((texts[-1]['text'] if texts else None, by_turn.get(t['id'], [])))
        run_text, run_calls, run_len = None, [], 0
        fired = set()

        def close():
            if run_text and run_len >= cfg['loop_same_text_min'] and run_text not in fired:
                fired.add(run_text)
                out.append(self.candidate('loop', 'session', sid, 'text:' + run_text,
                                          {'kind': 'same-text', 'turns': run_len}, run_calls, session=sid))
        for text, calls in ends:
            if text is not None and text == run_text:
                run_len += 1
                run_calls += calls
            else:
                close()
                run_text, run_calls, run_len = text, list(calls), 1 if text else 0
        close()
        stamps = defaultdict(list)
        for c in mains:
            for sig in c.get('tools') or []:
                stamps[sig].append(c)
        window = cfg['loop_window_min'] * 60
        for sig, calls in stamps.items():
            best, lo = [], 0
            for hi in range(len(calls)):
                while calls[hi]['ts'] - calls[lo]['ts'] > window:
                    lo += 1
                if hi - lo + 1 > len(best):
                    best = calls[lo:hi + 1]
            if len(best) >= cfg['loop_same_call_min']:
                out.append(self.candidate('loop', 'session', sid, 'call:' + sig,
                                          {'kind': 'same-call', 'repeats': len(best),
                                           'window_min': cfg['loop_window_min']}, best, session=sid))
        return out

    def empty_wakes(self, sid):
        cfg = self.cfg
        mains = self.by_session[sid]['main']
        empty, calls_in = 0, []
        for t in self.turns.get(sid, []):
            if not Data.is_automatic(t['origin']):
                continue
            calls = [c for c in mains if c.get('turn') == t['id']]
            if len(calls) <= cfg['empty_wake_max_calls'] and sum(c['out'] for c in calls) <= cfg['empty_wake_max_output']:
                empty += 1
                calls_in += calls
        if empty >= cfg['empty_wakes_min_per_day']:
            return [self.candidate('empty-wakes', 'session', sid, '', {'empty_turns_24h': empty}, calls_in, session=sid)]
        return []

    def role_model(self, sid):
        cfg = self.cfg
        if self.d.session(sid)['role'] not in cfg['cheap_roles']:
            return []
        mains = self.by_session[sid]['main']
        total = _units(mains)
        costly = [c for c in mains if self.expensive.search(c['model'])]
        if total <= 0 or _units(costly) / total < cfg['role_model_min_share']:
            return []
        model = _dominant_model(costly)
        return [self.candidate('role-model', 'session', sid, model,
                               {'role': self.d.session(sid)['role'], 'model': model,
                                'expensive_share': round(_units(costly) / total, 3)}, costly, session=sid)]

    def expensive_automation(self, sid):
        cfg = self.cfg
        mains = self.by_session[sid]['main']
        total = _units(mains)
        model = _dominant_model(mains)
        if total <= 0 or not model or not self.expensive.search(model):
            return []
        auto = [c for c in mains if Data.is_automatic(c['origin'])]
        share = _units(auto) / total
        if share < cfg['automation_min_share']:
            return []
        return [self.candidate('expensive-automation', 'session', sid, model,
                               {'model': model, 'automatic_share': round(share, 3)}, auto, session=sid)]

    def expensive_subagents(self, sid):
        meta = (self.d.sessions_meta.get(sid) or {}).get('agents') or {}
        by_agent = defaultdict(list)
        for c in self.by_session[sid]['subagent']:
            by_agent[c.get('agent')].append(c)
        unmarked = []
        for agent, calls in by_agent.items():
            model = _dominant_model(calls)
            info = meta.get(agent) or {}
            desc, prompt = info.get('description') or '', info.get('first_prompt') or ''
            if not model or not self.expensive.search(model) or self.panel.search(desc):
                continue
            if self.mark.search(desc) or self.mark.search(prompt):
                continue
            unmarked.append((agent, calls))
        if len(unmarked) >= self.cfg['expensive_subagents_min']:
            calls = [c for _, cs in unmarked for c in cs]
            self.config_triggers.append(('expensive-subagents', sid, {'subagents': len(unmarked)}, calls))

    def advisor_excess(self, sid):
        calls = self.by_session[sid]['advisor']
        if len(calls) > self.cfg['advisor_max_per_day']:
            self.config_triggers.append(('advisor-excess', sid, {'advisor_calls_24h': len(calls)}, calls))

    def large_context(self, sid):
        cfg = self.cfg
        run, best = [], []
        for c in self.by_session[sid]['main']:
            if c['ctx'] >= cfg['large_context_tokens']:
                run.append(c)
                if len(run) > len(best):
                    best = list(run)
            else:
                run = []
        if len(best) >= cfg['large_context_calls']:
            return [self.candidate('large-context', 'session', sid, '',
                                   {'consecutive_calls': len(best), 'min_context': min(c['ctx'] for c in best)},
                                   best, session=sid)]
        return []

    def idle_rewrite(self, sid):
        cfg = self.cfg
        prev_by_file, hits = {}, []
        for c in (c for c in self.d.calls if c['session'] == sid and c['kind'] == 'main'):
            path = (c.get('loc') or '').rsplit(':', 1)[0]
            prev = prev_by_file.get(path)
            prev_by_file[path] = c['ts']
            if prev is None or c['ts'] <= self.day_start:
                continue
            written = c['cw5'] + c['cw1h']
            if (c['ts'] - prev > cfg['idle_rewrite_gap_s'] and c['ctx'] > cfg['idle_rewrite_min_context']
                    and written >= cfg['idle_rewrite_fraction'] * c['ctx']):
                hits.append(c)
        if len(hits) >= cfg['idle_rewrite_min_count']:
            return [self.candidate('idle-rewrite', 'session', sid, '', {'rewrites_24h': len(hits)}, hits, session=sid)]
        return []

    def pace(self, scope_kind, scope_id, calls, session=None):
        cfg, now = self.cfg, self.now
        last = [c for c in calls if now - HOUR < c['ts'] <= now]
        last_units = _units(last)
        base_start = now - HOUR - cfg['pace_baseline_days'] * DAY
        buckets = defaultdict(float)
        for c in calls:
            if base_start < c['ts'] <= now - HOUR:
                buckets[int((now - c['ts']) // HOUR)] += c['units']
        active = [u for u in buckets.values() if u > 0]
        mean = sum(active) / len(active) if active else 0.0
        if active and last_units >= cfg['pace_factor'] * mean and last_units >= cfg['pace_min_units']:
            return [self.candidate('pace', scope_kind, scope_id, '',
                                   {'last_hour_units': round(last_units, 3), 'mean_active_hour': round(mean, 3),
                                    'factor': cfg['pace_factor']}, last, saving=(last_units - mean) * 24,
                                   session=session)]
        budget = cfg['weekly_budget_units']
        window_h = cfg['pace_sustainable_window_h']
        if budget > 0 and window_h > 0:
            recent = [c for c in calls if now - window_h * HOUR < c['ts'] <= now]
            limit = cfg['pace_sustainable_share'] * budget / 168 * window_h
            used = _units(recent)
            if used >= limit:
                return [self.candidate('pace', scope_kind, scope_id, '',
                                       {'window_h': window_h, 'units': round(used, 3), 'limit': round(limit, 3)},
                                       recent, saving=(used - limit) * 24 / window_h, session=session)]
        return []

    def machine_config(self):
        if not self.config_triggers:
            return []
        installed = _load_piece(GATE_PIECE, {})
        if installed.get(GATE_KEY) == GATE_VALUE:
            return []
        rules = sorted({r for r, *_ in self.config_triggers}, key=ALL_RULES.index)
        sessions = sorted({s for _, s, *_ in self.config_triggers})
        calls = sorted((c for *_, cs in self.config_triggers for c in cs), key=lambda c: c['ts'])
        text = self.cfg['proposals'][rules[0]]
        value = 'true' if GATE_VALUE is True else str(GATE_VALUE)
        return [{
            'id': finding_id('config', 'machine', f'{GATE_PIECE}|{GATE_KEY}|{value}'), 'rule': rules[0],
            'scope': {'kind': 'machine', 'id': 'machine'}, 'project': None, 'project_root': None, 'role': None,
            'evidence': {'rules': rules, 'sessions': sessions,
                         'per_session': [{'rule': r, 'session': s, **fig} for r, s, fig, _ in self.config_triggers],
                         'locations': _locations(calls)},
            'saving_units_per_day': round(_units(calls), 4),
            'proposal': {'kind': 'config', 'text': text['proposal'], 'piece': GATE_PIECE, 'key': GATE_KEY,
                         'value': GATE_VALUE},
            'applier': 'usage-role', 'undo': text['undo'], 'target_app_id': None,
        }]

    def run(self) -> list[dict]:
        out = []
        sessions = sorted(self.by_session)
        for sid in sessions:
            out += self.loop(sid)
            out += self.empty_wakes(sid)
            out += self.role_model(sid)
            self.expensive_subagents(sid)
            self.advisor_excess(sid)
            out += self.large_context(sid)
            out += self.idle_rewrite(sid)
            out += self.expensive_automation(sid)
        by_session, by_project = defaultdict(list), defaultdict(list)
        for c in self.d.calls:
            by_session[c['session']].append(c)
            by_project[self.d.session(c['session'])['project']].append(c)
        for sid in sorted(by_session):
            out += self.pace('session', sid, by_session[sid], session=sid)
        for project in sorted(by_project):
            out += self.pace('project', project, by_project[project])
        out += self.machine_config()
        return out


def detect(cfg: dict, now_ts: float) -> list[dict]:
    return Detector(cfg, now_ts).run()
