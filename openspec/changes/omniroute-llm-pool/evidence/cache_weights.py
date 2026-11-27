#!/usr/bin/env python3
"""Estimate how much a cache-read / cache-write / output token counts toward Claude's plan usage percentage.

Question: the plan limit is shown as a percentage. Relative to one fresh input token (weight 1), what does one
cache-read token, one cache-write token and one output token weigh?

Data used, all of it already on the machine (standard library only, read-only):
  * Usage snapshots: results of the `get_usage` session tool found in the Claude Code transcripts
    (``<projects-dir>/<project>/<session>.jsonl`` and the subagent transcripts in ``<session>/subagents/``).
    A snapshot carries the plan name, the "5-hour limit", "Weekly - all models" and "Weekly - <model>" windows as
    integer percentages and the reset time of each window.
  * Token usage: every assistant message in the same transcripts (``message.usage``), counted once per ``message.id``
    (the same id is repeated on several records). Advisor sub-calls (``usage.iterations`` entries of type
    ``advisor_message``) are billed separately and are counted as extra messages of the advisor's model.

Method:
  1. Snapshots are sorted by time and given an anonymous account label (A1, A2, ...) from the plan name and the phase of
     the weekly reset time (every account has its own weekly anchor). Two adjacent snapshots (in global time order)
     of the same account, at most --max-gap-hours apart, with the same window reset time (the percentage cannot have
     been reset in between), form an interval. A 5-hour window that was inactive (no reset time) in the first snapshot
     counts as 0 %.
  2. For each interval, the tokens of every assistant message whose timestamp falls inside it are summed by class
     (fresh input of the main calls, cache read, cache write 5m+1h, output, and the input of advisor sub-calls) and by
     model family. Main-call fresh input is only a few tokens per request (under 1 % of tokens), so it acts as a request
     counter; the advisor sub-calls are the only large uncached input, so "weight relative to uncached input" is read from
     the advisor-input class.
  3. delta_percent ~ scale_account x sum_c coef_c x tokens_c, with non-negative coefficients (exact NNLS by enumerating
     the active sets) and one scale per account (plan sizes differ), fitted by alternating least squares. Fits: all
     accounts jointly, each account alone, Opus-dominated intervals, desktop-app sessions only, with a nuisance term
     proportional to elapsed time, and the Fable-only weekly window against Fable tokens. Intervals are also merged
     until they span --merge-points percentage points (less rounding error per interval). A bootstrap over intervals
     (stratified by account) gives the 5-95 % ranges of the coefficient ratios.
  4. Fixed weight schemes (all tokens equal, API price ratios, ...) are compared with the free fit by AIC, and the
     cache-read weight is profiled: it is forced to w times the cache-write weight and the likelihood-ratio statistic
     n ln(RSS/RSS_min) is reported (about 3.84 at the 95 % limit; the residuals are not independent, so this is a rough guide).

Limits, stated again in the output: percentages are rounded integers (the error of a difference is about 0.4 points,
very large next to a few points of change); usage of the same account from other machines, cloud sessions and the chat
app is invisible; an account switch with no snapshot of the other account in between is not detected; cache reads are
about 98 % of all tokens and move together with everything else.

Usage:
  cache_weights.py [--projects-dir ~/.claude/projects] [--since 2026-11-20] [--json FILE] [--cache FILE]
                   [--max-gap-hours 3] [--merge-points 5] [--bootstrap 2000] [--seed 1]

--cache FILE keeps the extracted snapshots and per-message token counts (no ids, no text) so that the analysis can be
rerun without reading the transcripts again.
"""
import argparse
import datetime
import glob
import itertools
import json
import math
import multiprocessing
import os
import random
import re
import sys

CLASSES = ["fresh", "cache_read", "cache_write", "output", "advisor_input"]
NC = len(CLASSES)
FAMILIES = ["opus", "sonnet", "haiku", "fable", "other"]
TS_RE = re.compile(r'"timestamp":"([^"]+)"')
WEEK = 7 * 86400


def iso_epoch(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def family(model):
    m = (model or "").lower()
    for f in FAMILIES[:-1]:
        if f in m:
            return f
    return "other"


# ----------------------------------------------------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------------------------------------------------

def merge_msg(msgs, mid, rec):
    """Same message id on several records or files: earliest time, largest counts."""
    old = msgs.get(mid)
    if old is None:
        msgs[mid] = rec
        return
    old[0] = min(old[0], rec[0])
    for i in range(3, 3 + NC):
        old[i] = max(old[i], rec[i])


def extract_file(args):
    """Return (snapshots, messages) of one transcript. Messages: id -> [ts, family, entrypoint, fresh, cr, cw, out]."""
    path, since_iso = args
    snaps, msgs, pend = [], {}, {}
    try:
        fh = open(path, errors="replace")
    except OSError:
        return snaps, msgs
    with fh:
        for line in fh:
            has_tokens = '"output_tokens"' in line and '"usage"' in line
            has_snap = "get_usage" in line
            if not (has_tokens or has_snap or pend):
                continue
            m = TS_RE.search(line)
            if m and m.group(1) < since_iso and not pend:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue
            if has_tokens and d.get("type") == "assistant":
                u = msg.get("usage") or {}
                mid = msg.get("id")
                ts = iso_epoch(d.get("timestamp"))
                if not mid or ts is None or msg.get("model") == "<synthetic>":
                    continue
                entry = d.get("entrypoint") or ""
                main = [u.get("input_tokens") or 0, u.get("cache_read_input_tokens") or 0,
                        u.get("cache_creation_input_tokens") or 0, u.get("output_tokens") or 0, 0]
                merge_msg(msgs, mid, [ts, family(msg.get("model")), entry] + main)
                # advisor sub-calls are billed to another model and are not part of the top-level usage
                n = 0
                for it in u.get("iterations") or []:
                    if isinstance(it, dict) and it.get("type") == "advisor_message":
                        merge_msg(msgs, "%s#adv%d" % (mid, n),
                                  [ts, family(it.get("model")), entry, 0,
                                   it.get("cache_read_input_tokens") or 0, it.get("cache_creation_input_tokens") or 0,
                                   it.get("output_tokens") or 0, it.get("input_tokens") or 0])
                        n += 1
            if not has_snap and not pend:
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and str(b.get("name", "")).endswith("get_usage"):
                    pend[b.get("id")] = True
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in pend:
                    pend.pop(b.get("tool_use_id"))
                    cont = b.get("content")
                    if isinstance(cont, list):
                        cont = "".join(x.get("text", "") for x in cont if isinstance(x, dict))
                    try:
                        plan = json.loads(cont).get("plan") or {}
                    except (ValueError, AttributeError, TypeError):
                        continue
                    ts = iso_epoch(d.get("timestamp"))
                    if ts is not None and plan.get("status") == "ok":
                        snaps.append({"ts": ts, "plan": plan.get("plan"), "windows": plan.get("windows") or []})
    return snaps, msgs


def extract(projects_dir, since_iso, since_epoch):
    files = []
    for root, _dirs, names in os.walk(projects_dir):
        for n in names:
            if n.endswith(".jsonl"):
                p = os.path.join(root, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_mtime >= since_epoch:
                    files.append((st.st_size, p))
    files.sort(reverse=True)
    snaps, msgs = [], {}
    with multiprocessing.Pool(min(8, os.cpu_count() or 2)) as pool:
        for s, m in pool.imap_unordered(extract_file, [(p, since_iso) for _, p in files], chunksize=1):
            snaps.extend(s)
            for mid, rec in m.items():
                merge_msg(msgs, mid, rec)
    seen, uniq = set(), []
    for s in sorted(snaps, key=lambda s: s["ts"]):
        if s["ts"] < since_epoch:
            continue
        k = (s["ts"], json.dumps(s["windows"], sort_keys=True))
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    msg_list = sorted(msgs.values(), key=lambda r: r[0])
    return uniq, msg_list, len(files)


# ----------------------------------------------------------------------------------------------------------------
# Snapshot series and intervals
# ----------------------------------------------------------------------------------------------------------------

WINDOW_NAMES = {"five_hour": "5-hour limit", "weekly_all": "all models", "weekly_fable": "Fable"}


def window_of(snap, name):
    for w in snap["windows"]:
        label = w.get("label") or ""
        if name == "five_hour" and label.startswith("5-hour"):
            return w
        if name == "weekly_all" and label.startswith("Weekly") and label.endswith("all models"):
            return w
        if name == "weekly_fable" and label.startswith("Weekly") and label.endswith("Fable"):
            return w
    return None


def label_accounts(snaps):
    """Anonymous account label from (plan, phase of the weekly reset time mod one week, rounded to 10 minutes)."""
    keys, labels = {}, {}
    for s in snaps:
        w = window_of(s, "weekly_all")
        reset = iso_epoch(w.get("resetsAt")) if w else None
        s["account"] = None
        if reset is None:
            continue
        key = (s["plan"], int(round((reset % WEEK) / 600.0)) % (WEEK // 600))
        if key not in keys:
            keys[key] = "A%d" % (len(keys) + 1)
        s["account"] = keys[key]
        labels[keys[key]] = s["plan"]
    return labels


def build_intervals(snaps, window, max_gap, reset_tol=120.0):
    """Adjacent snapshots of the same account with the same window reset time -> (t0, t1, p0, p1, account)."""
    out = []
    for a, b in zip(snaps, snaps[1:]):
        if a["account"] is None or a["account"] != b["account"]:
            continue
        if b["ts"] - a["ts"] > max_gap:
            continue
        wa, wb = window_of(a, window), window_of(b, window)
        if wa is None or wb is None or wb.get("percentUsed") is None or wa.get("percentUsed") is None:
            continue
        ra, rb = iso_epoch(wa.get("resetsAt")), iso_epoch(wb.get("resetsAt"))
        p0, p1 = float(wa["percentUsed"]), float(wb["percentUsed"])
        if rb is None:
            continue
        if ra is None:
            # window inactive at the first snapshot: it started afterwards, so it began from 0 %
            span = 5 * 3600 if window == "five_hour" else WEEK
            if p0 != 0 or rb - span < a["ts"] - 60:
                continue
        elif abs(ra - rb) > reset_tol:
            continue
        if p1 < p0:
            continue
        out.append({"t0": a["ts"], "t1": b["ts"], "p0": p0, "p1": p1, "account": a["account"], "reset": rb})
    return out


def merge_intervals(ivs, min_points):
    """Chain consecutive intervals (same account and window) until they span at least min_points of percentage."""
    out, cur = [], None
    for iv in ivs:
        if cur is not None and iv["t0"] == cur["t1"] and iv["account"] == cur["account"] and iv["reset"] == cur["reset"]:
            cur["t1"], cur["p1"] = iv["t1"], iv["p1"]
        else:
            if cur is not None and cur["p1"] - cur["p0"] >= min_points:
                out.append(cur)
            cur = dict(iv)
        if cur["p1"] - cur["p0"] >= min_points:
            out.append(cur)
            cur = None
    return out


def add_tokens(ivs, msgs, entry_filter=None):
    """Fill iv['tok'][family][class] (tokens) from the messages with t0 < ts <= t1 (messages are sorted by time)."""
    times = [m[0] for m in msgs]
    import bisect
    for iv in ivs:
        tok = {f: [0] * NC for f in FAMILIES}
        lo, hi = bisect.bisect_right(times, iv["t0"]), bisect.bisect_right(times, iv["t1"])
        for m in msgs[lo:hi]:
            if entry_filter and not entry_filter(m[2]):
                continue
            t = tok[m[1]]
            for i in range(NC):
                t[i] += m[3 + i]
        iv["tok"] = tok
    return ivs


# ----------------------------------------------------------------------------------------------------------------
# Least squares
# ----------------------------------------------------------------------------------------------------------------

def solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-14:
            return None
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def nnls(X, y):
    """Exact non-negative least squares for few columns: best feasible solution over all active sets."""
    p = len(X[0])
    G = [[sum(r[i] * r[j] for r in X) for j in range(p)] for i in range(p)]
    b = [sum(r[i] * v for r, v in zip(X, y)) for i in range(p)]
    yy = sum(v * v for v in y)
    best = (yy, [0.0] * p)
    for r in range(1, p + 1):
        for S in itertools.combinations(range(p), r):
            coef = solve([[G[i][j] for j in S] for i in S], [b[i] for i in S])
            if coef is None or any(c < 0 for c in coef):
                continue
            sse = yy - 2 * sum(c * b[i] for c, i in zip(coef, S)) + sum(
                coef[a] * coef[c] * G[S[a]][S[c]] for a in range(r) for c in range(r))
            if sse < best[0] - 1e-12:
                full = [0.0] * p
                for i, c in zip(S, coef):
                    full[i] = c
                best = (sse, full)
    return best[1], max(best[0], 0.0)


PRICE = [1.0, 0.1, 1.25, 5.0, 1.0]  # fresh, cache read, cache write, output, advisor input (API-like)


def scales_for(X, y, acc, z_of):
    """Per-account scale k_a minimising sum (y - k_a z)^2 for z = z_of(row)."""
    num, den = {}, {}
    for r, v, a in zip(X, y, acc):
        z = z_of(r)
        num[a] = num.get(a, 0.0) + v * z
        den[a] = den.get(a, 0.0) + z * z
    return {a: (num[a] / den[a] if den[a] > 0 else 0.0) for a in num}


def fit_core(X, y, acc):
    """Shared class coefficients, one scale per account (plan sizes differ). Alternating least squares.
    Returns (coef, scales, sse); scales are relative to the account with the most intervals, whose %/Mtok the coef are."""
    accs = sorted(set(acc))
    if len(accs) == 1:
        c, sse = nnls(X, y)
        return c, {accs[0]: 1.0}, sse
    p = len(X[0])
    ref = max(accs, key=lambda a: acc.count(a))
    s = scales_for(X, y, acc, lambda r: sum(v * w for v, w in zip(r, PRICE + [0.0] * (p - NC))))
    s = {a: (v if v > 0 else 1.0) for a, v in s.items()}
    last = None
    c, sse = [0.0] * p, float("inf")
    for _ in range(25):
        Xs = [[v * s[a] for v in r] for r, a in zip(X, acc)]
        c, sse = nnls(Xs, y)
        s_new = scales_for(X, y, acc, lambda r: sum(v * w for v, w in zip(r, c)))
        # z uses the unscaled rows and c fitted on scaled rows: refit scale around the new c, then renormalise
        s = {a: (s_new[a] if s_new[a] > 0 else s[a]) for a in s}
        norm = s[ref]
        s = {a: v / norm for a, v in s.items()}
        if last is not None and abs(last - sse) < 1e-9 * max(1.0, sse):
            break
        last = sse
    Xs = [[v * s[a] for v in r] for r, a in zip(X, acc)]
    c, sse = nnls(Xs, y)
    return c, s, sse


def design(ivs, fams, per_hour=False):
    X, y, acc = [], [], []
    for iv in ivs:
        row = [sum(iv["tok"][f][c] for f in fams) / 1e6 for c in range(NC)]
        if per_hour:
            row.append((iv["t1"] - iv["t0"]) / 3600.0)
        X.append(row)
        y.append(iv["p1"] - iv["p0"])
        acc.append(iv["account"])
    return X, y, acc


def pct(vals, q):
    vals = sorted(vals)
    if not vals:
        return None
    i = (len(vals) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return vals[lo] + (vals[hi] - vals[lo]) * (i - lo)


def rng3(vals):
    return [pct(vals, 0.05), pct(vals, 0.5), pct(vals, 0.95)] if vals else None


SCHEMES = {   # weights of (fresh, cache read, cache write, output, advisor input)
    "all tokens equal": [1, 1, 1, 1, 1],
    "API prices (read 0.1, write 1.25, out 5)": [1, 0.1, 1.25, 5, 1],
    "cache read free": [1, 0.0, 1.25, 5, 1],
    "read 0.1, write 1, out 5": [1, 0.1, 1.0, 5, 1],
    "read 0.02, write 1, out 5": [1, 0.02, 1.0, 5, 1],
    "read 0.5, write 1, out 5": [1, 0.5, 1.0, 5, 1],
}


def aic(n, sse, p):
    return n * math.log(max(sse, 1e-9) / n) + 2 * p


def ratios_of(cf):
    r = {}
    if cf[4] > 1e-12:   # advisor input = the only plainly uncached input
        for c in (1, 2, 3):
            r["%s / advisor_input" % CLASSES[c]] = cf[c] / cf[4]
    if cf[2] > 1e-12:
        r["cache_read / cache_write"] = cf[1] / cf[2]
        r["output / cache_write"] = cf[3] / cf[2]
        r["advisor_input / cache_write"] = cf[4] / cf[2]
        r["fresh / cache_write"] = cf[0] / cf[2]
    return r


def analyse(ivs, fams, boot, rnd, per_hour=False, profile=True):
    n = len(ivs)
    accs = sorted(set(iv["account"] for iv in ivs))
    res = {"intervals": n, "accounts": {a: sum(1 for iv in ivs if iv["account"] == a) for a in accs}}
    if n < 12:
        res["note"] = "too few intervals"
        return res
    X, y, acc = design(ivs, fams, per_hour)
    coef, scales, sse = fit_core(X, y, acc)
    tot = [sum(r[c] for r in X) for c in range(NC)]
    ybar = sum(y) / n
    res.update({
        "token_share": {CLASSES[c]: tot[c] / max(sum(tot), 1e-9) for c in range(NC)},
        "total_percent": sum(y),
        "coef_percent_per_mtok": {CLASSES[c]: coef[c] for c in range(NC)},
        "scales_vs_reference": scales if len(accs) > 1 else None,
        "residual_rms_points": math.sqrt(sse / n),
        "r2_through_origin": 1 - sse / sum(v * v for v in y),
        "r2_centered": 1 - sse / sum((v - ybar) ** 2 for v in y),
        "zero_coefficients": [CLASSES[c] for c in range(NC) if coef[c] <= 1e-12],
    })
    if per_hour:
        res["coef_percent_per_hour"] = coef[NC]
    res["ratios"] = ratios_of(coef)
    by_acc = {a: [i for i in range(n) if acc[i] == a] for a in accs}
    samples, cs = {}, {c: [] for c in CLASSES}
    for _ in range(boot):
        idx = [i for a in accs for i in (rnd.choice(by_acc[a]) for _ in by_acc[a])]
        cb, _s, _e = fit_core([X[i] for i in idx], [y[i] for i in idx], [acc[i] for i in idx])
        for c in range(NC):
            cs[CLASSES[c]].append(cb[c])
        for k, v in ratios_of(cb).items():
            samples.setdefault(k, []).append(v)
    res["bootstrap_coef_5_50_95"] = {c: rng3(v) for c, v in cs.items()}
    res["bootstrap_zero_share"] = {c: sum(1 for v in cs[c] if v <= 1e-12) / boot for c in CLASSES}
    res["bootstrap_ratio_5_50_95"] = {k: {"range": rng3(v), "defined_in_share": len(v) / boot} for k, v in samples.items()}
    # fixed weight schemes: one shared shape, one scale per account
    free_aic = aic(n, sse, sum(1 for c in coef[:NC] if c > 1e-12) + len(accs) - 1)
    sch = {}
    for name, w in SCHEMES.items():
        ks = scales_for(X, y, acc, lambda r, w=w: sum(a * b for a, b in zip(r, w)))
        s = sum((v - ks[a] * sum(q * b for q, b in zip(r, w))) ** 2 for r, v, a in zip(X, y, acc))
        sch[name] = {"residual_rms_points": math.sqrt(s / n), "delta_aic_vs_free": aic(n, s, len(accs)) - free_aic}
    res["fixed_schemes"] = sch
    if profile:
        # Force the cache-read coefficient to be w times the cache-write coefficient (the cache reads are folded into
        # the cache-write column) and refit everything else.
        grid = (0, 0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 1)
        out = []
        for wcr in grid:
            Xm = []
            for r in X:
                r2 = r[:NC]
                r2[2] += wcr * r2[1]
                Xm.append([r2[0], r2[2], r2[3], r2[4]])
            _c, _s, sm = fit_core(Xm, y, acc)
            out.append({"weight": wcr, "rss": sm})
        best = min(o["rss"] for o in out)
        for o in out:
            o["lr_stat"] = n * math.log(max(o["rss"], 1e-9) / max(best, 1e-9))
        ok = [o["weight"] for o in out if o["lr_stat"] <= 3.84]
        res["profile_cache_read_in_cache_write_units"] = out
        res["cache_read_over_cache_write_profile_95"] = [min(ok), max(ok)] if ok else None
    return res


def family_profile(ivs):
    """Profile of the cache-read weight when every model family has its own cache-write, output and advisor-input
    coefficient (pooling families at equal weight could push the cache-read weight to zero). Within each family the
    cache-read coefficient is w times the cache-write coefficient; the grid is shared by the families."""
    groups = {"opus": ["opus"], "fable": ["fable"], "sonnet+haiku+other": ["sonnet", "haiku", "other"]}
    acc = [iv["account"] for iv in ivs]
    y = [iv["p1"] - iv["p0"] for iv in ivs]
    n = len(ivs)
    out = {"intervals": n, "families": list(groups)}
    if n < 12:
        out["note"] = "too few intervals"
        return out
    grid = (0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.2, 0.5, 1)
    prof = []
    for w in grid:
        cols = []
        for fams in groups.values():
            def col(c, w=w, fams=fams):
                return [sum(iv["tok"][f][c] + (w * iv["tok"][f][1] if c == 2 else 0) for f in fams) / 1e6 for iv in ivs]
            for c in (2, 3, 4):
                v = col(c)
                if sum(v) > 0:
                    cols.append(v)
        X = [list(r) for r in zip(*cols)]
        _c, _s, sse = fit_core(X, y, acc)
        prof.append({"weight": w, "rss": sse})
    best = min(o["rss"] for o in prof)
    for o in prof:
        o["lr_stat"] = n * math.log(max(o["rss"], 1e-9) / max(best, 1e-9))
    ok = [o["weight"] for o in prof if o["lr_stat"] <= 3.84]
    out["profile"] = prof
    out["cache_read_over_cache_write_profile_95"] = [min(ok), max(ok)] if ok else None
    return out


# ----------------------------------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------------------------------

def f3(v):
    if v is None:
        return "-"
    return "%.3g" % v


def rr(block, key):
    b = (block.get("bootstrap_ratio_5_50_95") or {}).get(key)
    if not b or b["range"] is None or key not in block["ratios"]:
        return "-"
    return "%s [%s..%s]%s" % (f3(block["ratios"][key]), f3(b["range"][0]), f3(b["range"][2]),
                              "" if b["defined_in_share"] > 0.95 else " (%d%%)" % round(100 * b["defined_in_share"]))


def summary_md(result):
    L = ["# Cache/output token weights vs plan usage percentage", ""]
    L.append("Snapshots %s to %s UTC; %d transcripts, %d messages counted once (%s)."
             % (result["data_from"], result["data_to"], result["transcripts"], result["messages"],
                ", ".join("%s %.0f M" % (k.replace("_", " "), v) for k, v in result["message_tokens_million"].items())))
    L.append("Accounts (anonymous): " + "; ".join(
        "%s %s: %d snapshots, intervals 5h/weekly/Fable %d/%d/%d" % (
            a, i["plan"], i["snapshots"], i["intervals"]["five_hour"], i["intervals"]["weekly_all"],
            i["intervals"]["weekly_fable"]) for a, i in result["accounts"].items()))
    L += ["", "Ranges are bootstrap 5-95 %; a percentage in brackets is the share of resamples in which the ratio exists "
          "(its denominator coefficient was above zero).", ""]
    L.append("| fit | n | RMS (pts) | R2 | read/write | output/write | advisor-in/write | read/advisor-in | write/advisor-in | output/advisor-in | zero in free fit |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, b in result["fits"].items():
        if "note" in b:
            L.append("| %s | %d | too few | | | | | | | | |" % (name, b["intervals"]))
            continue
        L.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            name, b["intervals"], f3(b["residual_rms_points"]), f3(b["r2_through_origin"]),
            rr(b, "cache_read / cache_write"), rr(b, "output / cache_write"), rr(b, "advisor_input / cache_write"),
            rr(b, "cache_read / advisor_input"), rr(b, "cache_write / advisor_input"), rr(b, "output / advisor_input"),
            ", ".join(b["zero_coefficients"]) or "none"))
    L += ["", "## Fixed weight schemes (delta AIC vs the free fit; below zero would beat it, large means rejected)", ""]
    names = list(SCHEMES)
    L.append("| fit | " + " | ".join(names) + " |")
    L.append("|---|" + "---|" * len(names))
    for name, b in result["fits"].items():
        if "note" in b or "joint" not in name:
            continue
        L.append("| %s | " % name + " | ".join(f3(b["fixed_schemes"][s]["delta_aic_vs_free"]) for s in names) + " |")
    L += ["", "## Cache read as a share of cache write, profile over the weight w (cache-read coefficient = w x cache-write "
          "coefficient; LR = n ln(RSS/RSS_min), about 3.84 at the 95 % limit)", ""]
    for name, b in result["fits"].items():
        if "note" in b or "profile_cache_read_in_cache_write_units" not in b:
            continue
        pr = b["profile_cache_read_in_cache_write_units"]
        L.append("- %s: 95 %% set w in [%s, %s]; LR at w = 0 / 0.02 / 0.05 / 0.1 / 0.5: %s" % (
            name, f3(b["cache_read_over_cache_write_profile_95"][0]), f3(b["cache_read_over_cache_write_profile_95"][1]),
            " / ".join(f3(next(o["lr_stat"] for o in pr if o["weight"] == w)) for w in (0, 0.02, 0.05, 0.1, 0.5))))
    L += ["", "## Same profile with one coefficient set per model family group (opus / fable / sonnet+haiku+other)", ""]
    for name, b in result["family_scaled_profiles"].items():
        if "note" in b:
            continue
        pr = b["profile"]
        L.append("- %s: 95 %% set w in [%s, %s]; LR at w = 0 / 0.02 / 0.05 / 0.1 / 0.5: %s" % (
            name, f3(b["cache_read_over_cache_write_profile_95"][0]), f3(b["cache_read_over_cache_write_profile_95"][1]),
            " / ".join(f3(next(o["lr_stat"] for o in pr if o["weight"] == w)) for w in (0, 0.02, 0.05, 0.1, 0.5))))
    L += ["", "## Limits", ""] + ["- " + t for t in result["limits"]]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--projects-dir", default="~/.claude/projects")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (UTC); default: 7 days ago")
    ap.add_argument("--json", default=None, help="write the full result as JSON to this file")
    ap.add_argument("--cache", default=None, help="keep/reuse the extracted snapshots and token counts in this file")
    ap.add_argument("--max-gap-hours", type=float, default=3.0)
    ap.add_argument("--merge-points", type=float, default=4.0)
    ap.add_argument("--bootstrap", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    utc = datetime.timezone.utc
    since = args.since or (datetime.datetime.now(utc) - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    since_epoch = datetime.datetime.fromisoformat(since).replace(tzinfo=utc).timestamp()
    since_iso = since + "T00:00:00"
    if args.cache and os.path.exists(args.cache):
        c = json.load(open(args.cache))
        snaps, msgs, nfiles = c["snaps"], c["msgs"], c["files"]
        if c.get("since", "9") > since:
            sys.exit("the cache was built with --since %s, later than %s" % (c.get("since"), since))
        snaps = [s for s in snaps if s["ts"] >= since_epoch]
    else:
        snaps, msgs, nfiles = extract(os.path.expanduser(args.projects_dir), since_iso, since_epoch)
        if args.cache:
            json.dump({"snaps": snaps, "msgs": msgs, "files": nfiles, "since": since}, open(args.cache, "w"))
    msgs = [m for m in msgs if m[0] >= since_epoch]
    labels = label_accounts(snaps)
    rnd = random.Random(args.seed)
    gap = args.max_gap_hours * 3600
    iso = lambda t: datetime.datetime.fromtimestamp(t, utc).strftime("%Y-%m-%d %H:%M")

    accounts = {a: {"plan": p, "snapshots": sum(1 for s in snaps if s["account"] == a), "intervals": {}}
                for a, p in labels.items()}
    fits, raw_ivs, family_profiles = {}, {}, {}
    windows = {"five_hour": "5h", "weekly_all": "weekly-all", "weekly_fable": "weekly-Fable"}
    for win, wname in windows.items():
        base = build_intervals(snaps, win, gap)
        for a in accounts:
            accounts[a]["intervals"][win] = sum(1 for iv in base if iv["account"] == a)
        fams = ["fable"] if win == "weekly_fable" else FAMILIES
        scope = "Fable tokens" if win == "weekly_fable" else "all models"
        merged = merge_intervals(base, args.merge_points if win == "five_hour" else max(2.0, args.merge_points / 2))
        for variant, ivs in (("adjacent", base), ("merged", merged)):
            ivs = add_tokens([dict(iv) for iv in ivs], msgs)
            ivs = [iv for iv in ivs if sum(sum(iv["tok"][f]) for f in fams) > 0]
            key = "%s %s, %s, joint" % (wname, variant, scope)
            fits[key] = analyse(ivs, fams, args.bootstrap, rnd)
            raw_ivs[key] = [{"t0": iso(iv["t0"]), "t1": iso(iv["t1"]), "account": iv["account"],
                             "delta": iv["p1"] - iv["p0"], "tokens_by_family": iv["tok"]} for iv in ivs]
            if variant == "adjacent":
                for a in accounts:
                    sub = [iv for iv in ivs if iv["account"] == a]
                    if len(sub) >= 15:
                        fits["%s %s, %s, %s alone" % (wname, variant, scope, a)] = analyse(sub, fams, args.bootstrap, rnd, profile=False)
                        if win == "five_hour":
                            fits["%s %s, %s, %s alone + hours term" % (wname, variant, scope, a)] = analyse(
                                sub, fams, args.bootstrap, rnd, per_hour=True, profile=False)
                if win != "weekly_fable":
                    only = [iv for iv in ivs if sum(iv["tok"]["opus"]) >= 0.9 * sum(sum(t) for t in iv["tok"].values())]
                    rest = [iv for iv in ivs if iv not in only]
                    fits["%s %s, Opus-dominated intervals, joint" % (wname, variant)] = analyse(
                        only, ["opus"], args.bootstrap, rnd)
                    fits["%s %s, other intervals (Opus < 90 %% of tokens), joint" % (wname, variant)] = analyse(
                        rest, FAMILIES, args.bootstrap, rnd)
                    family_profiles["%s %s, all models, one coefficient set per family group" % (wname, variant)] = family_profile(ivs)
                    # entry-point sensitivity: only messages of the desktop app
                    d_ivs = add_tokens([dict(iv) for iv in base], [m for m in msgs if m[2] == "claude-desktop"])
                    d_ivs = [iv for iv in d_ivs if sum(sum(t) for t in iv["tok"].values()) > 0]
                    fits["%s %s, desktop-app sessions only, joint" % (wname, variant)] = analyse(
                        d_ivs, FAMILIES, args.bootstrap, rnd, profile=False)
    times = [s["ts"] for s in snaps]
    result = {
        "data_from": iso(min(times)) if times else None, "data_to": iso(max(times)) if times else None,
        "transcripts": nfiles, "messages": len(msgs), "snapshots": len(snaps),
        "message_tokens_million": {CLASSES[c]: round(sum(m[3 + c] for m in msgs) / 1e6, 2) for c in range(NC)},
        "entrypoints": {e: sum(1 for m in msgs if m[2] == e) for e in sorted(set(m[2] for m in msgs))},
        "accounts": accounts, "fits": fits, "family_scaled_profiles": family_profiles, "intervals": raw_ivs,
        "parameters": {"since": since, "max_gap_hours": args.max_gap_hours, "merge_points": args.merge_points,
                       "bootstrap": args.bootstrap, "seed": args.seed},
        "limits": [
            "Percentages are rounded integers: a difference of two of them is off by about 0.4 points (RMS) and by up to 1.",
            "Usage of the same account from other machines, cloud sessions and the chat app is invisible here: noise, "
            "or bias where it correlates with activity here.",
            "An account switch with no snapshot of the other account in between is not detected; two accounts with the "
            "same plan and weekly reset time would be merged.",
            "A message is placed at the start of its response, usage is booked when it ends, and a snapshot can lag the server.",
            "Cache reads are about 96-98 % of all tokens and move with the other classes. Next-turn cache writes contain "
            "the previous turn's output, so cache write and output are nearly collinear: the output weight is the least "
            "reliable number. Main-call fresh input is a few tokens per request (under 0.01 % of tokens): it only counts requests, so it is not used as a reference; the advisor input is the only large uncached input.",
            "5-minute and 1-hour cache writes are pooled. Model families are pooled except where stated.",
            "Plan sizes differ per account, so each account gets its own scale; weights are shared in the joint fits.",
        ],
    }
    print(summary_md(result))
    if args.json:
        json.dump(result, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
