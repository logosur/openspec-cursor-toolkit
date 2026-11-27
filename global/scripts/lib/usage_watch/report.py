"""The status line, the self-refreshing page, `show` and `list` (design D12, D7, D10). Information only: no rule or
command acts on the pace colour."""
from __future__ import annotations

import html
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import attribution
from . import config as C
from . import store
from .collect import skipped_lines
from .data import Data
from .state import ensure_dir

WEEK = 7 * 86400


def week_start(cfg: dict, now_ts: float) -> float:
    now = datetime.fromtimestamp(now_ts, timezone.utc)
    start = now.replace(hour=cfg['week_start_hour'], minute=0, second=0, microsecond=0)
    start -= timedelta(days=(now.weekday() - cfg['week_start_weekday']) % 7)
    if start > now:
        start -= timedelta(days=7)
    return start.timestamp()


def pace_of(cfg: dict, elapsed_share: float, units: float) -> tuple[str, float | None]:
    budget = cfg['weekly_budget_units']
    if budget <= 0:
        return 'unknown', None
    projected = units / max(elapsed_share, 1e-9)
    ratio = projected / budget
    if ratio <= cfg['pace_amber_ratio']:
        return 'green', ratio
    return ('amber' if ratio <= 1.0 else 'red'), ratio


def home_project_warning(cfg: dict) -> str | None:
    """The usage role's home project has no lock with a mailbox: nobody would present its questions."""
    holder = attribution.usage_role(cfg)
    if not holder or not isinstance(holder.get('home_project'), str) or not holder['home_project']:
        return None
    home = os.path.realpath(holder['home_project'])
    for lock in attribution.live_locks(cfg):
        if isinstance(lock.get('checkout'), str) and os.path.realpath(lock['checkout']) == home and lock.get('mailbox'):
            return None
    return f'the usage role home project {os.path.basename(home)} has no questions session'


def status_data(cfg: dict, now_ts: float, data: Data | None = None) -> dict:
    d = data or Data(cfg, now_ts)
    start = week_start(cfg, now_ts)
    week = d.since(start)
    week_units = sum(c['units'] for c in week)
    share = min(1.0, max(0.0, (now_ts - start) / WEEK))
    pace, ratio = pace_of(cfg, share, week_units)
    calls = defaultdict(int)
    tokens = defaultdict(int)
    for c in d.calls:
        calls[c['kind']] += 1
        for k in ('in', 'cw5', 'cw1h', 'cr', 'out'):
            tokens[k] += int(c.get(k) or 0)
    budget = cfg['weekly_budget_units']
    return {
        'now': C.iso(now_ts), 'week_start': C.iso(start), 'week_elapsed_share': round(share, 4),
        'week_units': round(week_units, 4), 'unit_label': cfg['unit_label'], 'weekly_budget_units': budget,
        'week_budget_share': round(week_units / budget, 4) if budget > 0 else None,
        'pace': pace, 'projected_ratio': round(ratio, 4) if ratio is not None else None,
        'calls': {'main': calls['main'], 'subagent': calls['subagent'], 'advisor': calls['advisor'],
                  'total': sum(calls.values())},
        'tokens': dict(tokens), 'total_units': round(sum(c['units'] for c in d.calls), 4),
        'findings': store.counts(store.read(cfg)), 'unpriced_models': dict(d.unpriced),
        'skipped_lines': skipped_lines(cfg), 'warning': home_project_warning(cfg),
    }


def status_line(s: dict) -> str:
    budget = f', {round(s["week_budget_share"] * 100)}% of budget' if s['week_budget_share'] is not None else ''
    f = s['findings']
    line = (f'usage-watch: week {round(s["week_elapsed_share"] * 100)}% elapsed, {s["week_units"]:g} {s["unit_label"]}'
            f'{budget}, pace {s["pace"]} · findings new {f["new"]}, minor {f["minor"]}, asked {f["asked"]}, authorized {f["authorized"]}'
            f' · unpriced {len(s["unpriced_models"])} · skipped {s["skipped_lines"]}')
    if s.get('warning'):
        line += f' · warning: {s["warning"]}'
    return line


def ranking(d: Data, calls) -> dict:
    out = {'session': defaultdict(float), 'project': defaultdict(float), 'model': defaultdict(float),
           'origin': defaultdict(float)}
    for c in calls:
        info = d.session(c['session'])
        out['session'][f'{c["session"][:8]} ({info["role"]})'] += c['units']
        out['project'][info['project']] += c['units']
        out['model'][c['model']] += c['units']
        out['origin'][c['origin']] += c['units']
    return {k: sorted(v.items(), key=lambda kv: -kv[1]) for k, v in out.items()}


PAGE_CSS = """
:root { --bg:#fbfbfa; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e3df; --accent:#2f5d8a; --card:#ffffff; }
@media (prefers-color-scheme: dark) { :root { --bg:#151514; --fg:#ececea; --muted:#a3a39d; --line:#2e2e2b;
  --accent:#8db4dd; --card:#1d1d1b; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.35rem; margin: 0 0 4px; } h2 { font-size: 1.05rem; margin: 24px 0 8px; }
.status { color: var(--muted); margin-bottom: 8px; overflow-wrap: anywhere; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
section.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-width: 0; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
td, th { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; overflow-wrap: anywhere; }
td.n { text-align: right; width: 7em; font-variant-numeric: tabular-nums; }
.state { color: var(--accent); font-weight: 600; } .muted { color: var(--muted); } details.minor { margin-top: 8px; color: var(--muted); }
section.card h2 { margin-top: 0; }
@media (max-width: 600px) {
  table.findings tr { display: block; padding: 6px 0; border-bottom: 1px solid var(--line); }
  table.findings td { display: block; border: 0; padding: 1px 6px; }
}
"""


def _table(rows, empty) -> str:
    if not rows:
        return f'<p class="muted">{html.escape(empty)}</p>'
    body = ''.join(f'<tr><td>{html.escape(str(k))}</td><td class="n">{v:.2f}</td></tr>' for k, v in rows[:20])
    return f'<table>{body}</table>'


def render_page(cfg: dict, now_ts: float) -> str:
    d = Data(cfg, now_ts)
    s = status_data(cfg, now_ts, d)
    labels = cfg['labels']
    rank = ranking(d, d.since(week_start(cfg, now_ts)))
    cards = ''.join(
        f'<section class="card"><h2>{html.escape(labels[key])}</h2>{_table(rank[dim], labels["none"])}</section>'
        for key, dim in (('by_session', 'session'), ('by_project', 'project'), ('by_model', 'model'),
                         ('by_origin', 'origin')))
    stored = store.read(cfg).values()
    findings = sorted((f for f in stored if f.get('state') != 'minor'), key=lambda f: f.get('last_seen') or '',
                      reverse=True)
    minor = [f for f in stored if f.get('state') == 'minor']
    rows = ''.join(
        f'<tr><td>{html.escape(f["id"])}</td><td class="state">{html.escape(str(f.get("state")))}</td>'
        f'<td>{html.escape(str((f.get("scope") or {}).get("kind")))}: {html.escape(str(f.get("project") or ""))}</td>'
        f'<td>{html.escape(str((f.get("proposal") or {}).get("text") or ""))}</td></tr>' for f in findings)
    findings_html = f'<table class="findings">{rows}</table>' if rows else f'<p class="muted">{html.escape(labels["none"])}</p>'
    if minor:   # one collapsed block: how many and how much, never a row each
        total = sum(f.get('saving_units_per_day') or 0 for f in minor if not f.get('folded_into'))
        findings_html += (f'<details class="minor"><summary>{html.escape(labels["minor"])}: {len(minor)} '
                          f'({total:.2f} {html.escape(labels["saving"])})</summary></details>')
    unpriced = ''
    if s['unpriced_models']:
        items = ''.join(f'<tr><td>{html.escape(m)}</td><td class="n">{n}</td></tr>' for m, n in s['unpriced_models'].items())
        unpriced = f'<section class="card"><h2>{html.escape(labels["unpriced"])}</h2><table>{items}</table></section>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="{int(cfg["page_refresh_s"])}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f'<title>{html.escape(labels["title"])}</title><style>{PAGE_CSS}</style></head><body><main>'
        f'<h1>{html.escape(labels["title"])}</h1><p class="status">{html.escape(status_line(s))}</p>'
        f'<div class="grid">{cards}{unpriced}</div>'
        f'<h2>{html.escape(labels["findings"])}</h2><section class="card">{findings_html}</section>'
        '</main></body></html>\n')


def write_page(cfg: dict, now_ts: float) -> str:
    path = C.path(cfg, 'page_path')
    ensure_dir(os.path.dirname(path))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(render_page(cfg, now_ts))
    os.replace(tmp, path)
    return path


def matches(f: dict, project=None, state=None, applier=None) -> bool:
    if state and f.get('state') != state:
        return False
    if applier and f.get('applier') != applier:
        return False
    if project:
        want = os.path.basename(os.path.realpath(project).rstrip('/')) if os.sep in project else project
        if f.get('project') not in (project, want):
            return False
    return True


def list_findings(cfg: dict, project=None, state=None, applier=None) -> list[dict]:
    found = [f for _, f in sorted(store.read(cfg).items()) if matches(f, project, state, applier)]
    if state == 'new':   # the largest saving first: what is worth asking about comes first
        found.sort(key=lambda f: -(f.get('saving_units_per_day') or 0))
    return found


def list_line(f: dict) -> str:
    return (f'{f["id"]}\t{f.get("state")}\t{f.get("rule")}\t{(f.get("scope") or {}).get("kind")}\t'
            f'{f.get("project") or "-"}\t{f.get("applier")}\t{(f.get("proposal") or {}).get("text") or ""}')


def show_text(f: dict) -> str:
    lines = [f'{f["id"]}  {f.get("rule")}  state {f.get("state")}',
             f'scope: {(f.get("scope") or {}).get("kind")} {(f.get("scope") or {}).get("id")}',
             f'project: {f.get("project") or "-"}  role: {f.get("role") or "-"}  applier: {f.get("applier")}',
             f'saving per day: {f.get("saving_units_per_day")}',
             f'proposal ({(f.get("proposal") or {}).get("kind")}): {(f.get("proposal") or {}).get("text")}',
             f'undo: {f.get("undo")}']
    evidence = {k: v for k, v in (f.get('evidence') or {}).items() if k != 'locations'}
    lines.append('evidence: ' + json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    lines.append('transcript locations:')
    lines += [f'  {loc}' for loc in (f.get('evidence') or {}).get('locations') or []] or ['  (none)']
    lines.append('history:')
    lines += [f'  {h.get("at")} {h.get("state")} by {h.get("by")}' for h in f.get('history') or []]
    return '\n'.join(lines)
