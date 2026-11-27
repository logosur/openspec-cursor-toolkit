"""The `usage-watch` config piece: generic defaults, shape checks and the clock.

Top-level keys go through `toolkit_config.load_checked` (a value of the wrong shape keeps the default). It checks only
the top-level type, so the nested values are checked here entry by entry (design § Configuration).
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone

try:
    from toolkit_config import load_checked as _load_checked
except ImportError:  # no helper, or one older than load_checked: the code's defaults
    def _load_checked(piece, defaults):
        return dict(defaults)

PIECE = 'usage-watch'

DEFAULT_PROPOSALS = {
    'loop': {'proposal': 'Look at why this session repeats itself and stop the loop.',
             'undo': 'Nothing to undo: the session is only looked at.'},
    'empty-wakes': {'proposal': 'Make the watcher of this session wake it less often, or only when there is work.',
                    'undo': 'Restore the previous wake-up rule.'},
    'role-model': {'proposal': 'Run this session on the cheaper model its role calls for.',
                   'undo': 'Set the session back to its previous model.'},
    'expensive-subagents': {'proposal': 'Turn on agent-model-gate, so subagents need an explicit cheaper model or a reason.',
                            'undo': 'Set agent-model-gate enabled back to false.'},
    'advisor-excess': {'proposal': 'Turn on agent-model-gate, which caps advisor calls per day.',
                       'undo': 'Set agent-model-gate enabled back to false.'},
    'large-context': {'proposal': 'Compact or restart this session: it keeps a large context for many calls.',
                      'undo': 'Nothing to undo.'},
    'idle-rewrite': {'proposal': 'Keep this session busy or let it end: each wake-up after a long pause rewrites its cache.',
                     'undo': 'Restore the previous schedule.'},
    'pace': {'proposal': 'Look at why usage here is far above its own normal pace.',
             'undo': 'Nothing to undo: the scope is only looked at.'},
    'expensive-automation': {'proposal': 'Run this session, which mostly answers automatic notices, on the cheaper model.',
                             'undo': 'Set the session back to its previous model.'},
}

DEFAULT_LABELS = {
    'title': 'Usage watch',
    'by_session': 'By session',
    'by_project': 'By project',
    'by_model': 'By model',
    'by_origin': 'By origin',
    'findings': 'Findings',
    'units': 'units',
    'none': 'Nothing to show.',
    'unpriced': 'Models with no price',
    'change': 'Change made if you authorise it',
}

# Every value is provisional and generic: none is a figure observed on a particular machine.
DEFAULTS = {
    'projects_dir': '~/.claude/projects',
    'app_sessions_dir': '~/.config/Claude/claude-code-sessions',
    'supervisor_home': '~/.claude/supervisor',
    'state_dir': '~/.claude/state/usage-watch',
    'page_path': '~/.claude/state/usage-watch/usage.html',
    'page_refresh_s': 300,
    'retention_days': 15,
    # model-id regex -> weights per million tokens: input, cache write 5 min, cache write 1 h, cache read, output.
    # One generic entry, relative weights only, until the override sets real ones.
    'prices': {'.': [1, 1.25, 2, 0.1, 5]},
    'unit_label': 'units',
    'expensive_model_pattern': 'opus|fable',
    'escalation_mark_pattern': r'\[opus: [^\]]+\]',
    'panel_pattern': '^Panel',
    'cheap_roles': ['questions', 'closer', 'usage', 'routine'],
    'cheap_model': 'sonnet',
    'origin_text_prefixes': {'<task-notification>': 'task'},
    'loop_same_text_min': 5,
    'loop_same_call_min': 6,
    'loop_window_min': 30,
    'empty_wakes_min_per_day': 24,
    'empty_wake_max_calls': 1,
    'empty_wake_max_output': 300,
    'role_model_min_share': 0.5,
    'expensive_subagents_min': 2,
    'advisor_max_per_day': 4,
    'large_context_calls': 20,
    'large_context_tokens': 150000,
    'idle_rewrite_gap_s': 3600,
    'idle_rewrite_min_context': 50000,
    'idle_rewrite_fraction': 0.5,
    'idle_rewrite_min_count': 3,
    'pace_factor': 3,
    'pace_min_units': 20,
    'pace_baseline_days': 7,
    'pace_sustainable_window_h': 6,
    'pace_sustainable_share': 1.5,
    'automation_min_share': 0.6,
    'measure_window_h': 24,
    'weekly_budget_units': 0,
    'week_start_weekday': 0,
    'week_start_hour': 0,
    'pace_amber_ratio': 0.8,
    'timer_interval_min': 15,
    'order_text': '',
    'no_default': 'Leave it as it is',
    'authorize_answers': ['apply'],
    'authorize_hint': 'Answer "apply" to authorise this change; any other answer leaves it as it is.',
    'ticket_ttl_s': 900,
    'proposals': DEFAULT_PROPOSALS,
    'labels': DEFAULT_LABELS,
}

PATTERN_KEYS = ('expensive_model_pattern', 'escalation_mark_pattern', 'panel_pattern')


def _compiles(text) -> bool:
    try:
        re.compile(text)
        return True
    except (re.error, TypeError):
        return False


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def clean_prices(value) -> dict:
    """Valid entries only; the default table when none is valid."""
    out = {}
    if isinstance(value, dict):
        for pattern, weights in value.items():
            if (isinstance(pattern, str) and _compiles(pattern) and isinstance(weights, list) and len(weights) == 5
                    and all(_number(w) for w in weights)):
                out[pattern] = [float(w) for w in weights]
    return out or {k: [float(w) for w in v] for k, v in DEFAULTS['prices'].items()}


def _clean_texts(value, defaults, nested_keys=None) -> dict:
    out = {}
    for key, default in defaults.items():
        entry = value.get(key) if isinstance(value, dict) else None
        if nested_keys:
            ok = (isinstance(entry, dict) and all(isinstance(entry.get(k), str) and entry[k].strip() for k in nested_keys))
            out[key] = {k: entry[k] for k in nested_keys} if ok else dict(default)
        else:
            out[key] = entry if isinstance(entry, str) and entry.strip() else default
    return out


def load() -> dict:
    cfg = _load_checked(PIECE, DEFAULTS)
    cfg['prices'] = clean_prices(cfg.get('prices'))
    for key in PATTERN_KEYS:
        if not _compiles(cfg[key]):
            cfg[key] = DEFAULTS[key]
    cfg['proposals'] = _clean_texts(cfg.get('proposals'), DEFAULT_PROPOSALS, ('proposal', 'undo'))
    cfg['labels'] = _clean_texts(cfg.get('labels'), DEFAULT_LABELS)
    prefixes = cfg.get('origin_text_prefixes')
    cfg['origin_text_prefixes'] = ({k: v for k, v in prefixes.items() if isinstance(k, str) and k and isinstance(v, str)}
                                   if isinstance(prefixes, dict) else dict(DEFAULTS['origin_text_prefixes']))
    if not (isinstance(cfg['week_start_weekday'], int) and 0 <= cfg['week_start_weekday'] <= 6):
        cfg['week_start_weekday'] = DEFAULTS['week_start_weekday']
    if not (isinstance(cfg['week_start_hour'], int) and 0 <= cfg['week_start_hour'] <= 23):
        cfg['week_start_hour'] = DEFAULTS['week_start_hour']
    return cfg


def path(cfg: dict, key: str) -> str:
    return os.path.expanduser(cfg[key])


def supervisor_home(cfg: dict) -> str:
    return os.path.expanduser(os.environ.get('SUPERVISOR_LOCK_HOME') or cfg['supervisor_home'])


def parse_time(value) -> float | None:
    """Epoch seconds from an ISO-8601 string (Z or offset; naive = UTC) or a number; None when unreadable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        stamp = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def now(explicit=None) -> float:
    """--now, else USAGE_WATCH_NOW, else the clock."""
    for value in (explicit, os.environ.get('USAGE_WATCH_NOW')):
        if value:
            parsed = parse_time(value)
            if parsed is not None:
                return parsed
    return time.time()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
