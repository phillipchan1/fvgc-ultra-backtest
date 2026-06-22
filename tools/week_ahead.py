#!/usr/bin/env python3
"""
NQ Week-Ahead Report — Sunday-afternoon prep for the upcoming trading week.

Companion to tools/morning_briefing.py. Where the morning briefing is a deep
same-day report (full OR-width forecast, armed edges, live levels), this is a
forward-looking 5-day planner answering three questions Phil asks every Sunday:

  1. What red-folder (USD High-impact) events hit, and WHEN — in PST, so an
     8:30 ET CPI print shows as "5:30 AM PST · wake-up" at a glance.
  2. The historical average RTH / opening-range for each weekday.
  3. An expected-range estimate from live ATR, nudged by an event multiplier
     learned from history (CPI/NFP/FOMC days run wider than quiet days).

Honest limitation: the SHARP same-morning OR-width forecast needs that day's
gap + overnight range, which don't exist days ahead. So Tue-Fri range numbers
here are ATR/seasonal/event-conditioned BASELINES, not the 9:35/9:45 forecast.

Outputs tools/briefing/week_ahead.json + week_ahead.js (window.WEEK_AHEAD),
deployed by the same GitHub Pages pipeline as the daily briefing.

Usage:
    python tools/week_ahead.py --export                 # next trading week
    python tools/week_ahead.py --export --gen-date 2026-06-21
    python tools/week_ahead.py                          # print, no write
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo('America/New_York')
    PT_TZ = ZoneInfo('America/Los_Angeles')
except ImportError:  # pragma: no cover
    import pytz
    NY_TZ = pytz.timezone('America/New_York')
    PT_TZ = pytz.timezone('America/Los_Angeles')

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / 'tools'
BRIEFING_DIR = TOOLS / 'briefing'
TRADING_DAYS_CSV = REPO / 'data' / 'trading_days' / 'trading_days.csv'

sys.path.insert(0, str(TOOLS))

RTH_OPEN_ET = dtime(9, 30)
OR45_END_ET = dtime(10, 15)    # first 45 min — the opening range Phil trades
WINDOW_END_ET = dtime(11, 0)   # first ~90 min (9:30-11:00 ET)
RTH_CLOSE_ET = dtime(16, 0)

# The three windows the report estimates, in priority order. Phil's core is
# the first 45 min; 90 min is his extended window; "rest" is context.
RANGE_BUCKETS = ('or45', 'f90', 'rest', 'full')
_BUCKET_LABEL = {'or45': 'first 45 min', 'f90': 'first 90 min',
                 'rest': 'rest (11:00-close)', 'full': 'full session'}


# ======================================================================
# Trading-week calendar
# ======================================================================

def upcoming_trading_week(gen_date: date) -> list[date]:
    """Return the Mon-Fri of the trading week to plan for.

    Run on a weekend (the intended Sunday-12pm cadence) → the week that
    starts the very next Monday. Run mid-week → the CURRENT week's Mon-Fri
    so a manual re-run still shows the week you're in.
    """
    wd = gen_date.weekday()  # Mon=0 .. Sun=6
    if wd >= 5:              # Sat/Sun → next Monday
        monday = gen_date + timedelta(days=(7 - wd))
    else:                    # weekday → this week's Monday
        monday = gen_date - timedelta(days=wd)
    return [monday + timedelta(days=i) for i in range(5)]


def is_quad_witching(d: date) -> bool:
    """Triple/quad witching = 3rd Friday of Mar/Jun/Sep/Dec."""
    if d.month not in (3, 6, 9, 12) or d.weekday() != 4:
        return False
    # 3rd Friday → day-of-month between 15 and 21
    return 15 <= d.day <= 21


# ======================================================================
# Historical range baselines (from trading_days.csv)
# ======================================================================

def _read_history(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    rows: list[dict] = []
    with open(csv_path, newline='') as f:
        for row in csv.DictReader(f):
            d = (row.get('date') or '').strip()
            if not d:
                continue
            rows.append(row)
    return rows


def _f(row: dict, key: str):
    """Parse a float cell, None if blank/unparseable."""
    v = (row.get(key) or '').strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _mean(xs: list[float]):
    return sum(xs) / len(xs) if xs else None


def weekday_range_stats(rows: list[dict], lookback_days: int = 180) -> dict[int, dict]:
    """Average RTH range + 45-min OR range per weekday, recent window.

    Keyed by Python weekday (Mon=0). NQ point-ranges scale with the index
    level, so a multi-year average understates today's regime. Default to a
    ~6-month window (~25 samples/weekday) so the "average range" is
    comparable to the live ATR. Falls back to all-history per weekday if a
    weekday has too few recent samples.
    """
    if not rows:
        return {}
    last_date = max(date.fromisoformat(r['date']) for r in rows)
    cutoff = last_date - timedelta(days=lookback_days)

    recent = defaultdict(lambda: {'rth': [], 'or45': []})
    alltime = defaultdict(lambda: {'rth': [], 'or45': []})
    for r in rows:
        d = date.fromisoformat(r['date'])
        wd = d.weekday()
        rth = _f(r, 'rth_range')
        or45 = _f(r, 'or_45min_range')
        if rth is not None:
            alltime[wd]['rth'].append(rth)
            if d >= cutoff:
                recent[wd]['rth'].append(rth)
        if or45 is not None:
            alltime[wd]['or45'].append(or45)
            if d >= cutoff:
                recent[wd]['or45'].append(or45)

    out: dict[int, dict] = {}
    for wd in range(5):
        rec, allt = recent[wd], alltime[wd]
        use_rth = rec['rth'] if len(rec['rth']) >= 20 else allt['rth']
        use_or = rec['or45'] if len(rec['or45']) >= 20 else allt['or45']
        out[wd] = {
            'avg_rth_range': _mean(use_rth),
            'avg_or45_range': _mean(use_or),
            'n': len(use_rth),
        }
    return out


def event_range_multipliers(rows: list[dict]) -> dict[str, dict]:
    """How much wider does the RTH range run on event days vs the baseline?

    Returns {tag: {'mult': x, 'avg': pts, 'n': k}} for red-folder, FOMC,
    CPI, NFP, PPI. `mult` is avg-range-on-tag-days / avg-range-all-days, so
    it scales the live ATR baseline. Quiet (no red folder) days are the
    natural comparison the multiplier rides on top of.
    """
    all_ranges = [v for r in rows if (v := _f(r, 'rth_range')) is not None]
    base = _mean(all_ranges)
    if not base:
        return {}

    buckets: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        rth = _f(r, 'rth_range')
        if rth is None:
            continue
        names = (r.get('red_folder_event_names') or '').upper()
        red = (r.get('has_red_folder_news') or '').strip().lower() == 'true'
        fomc = (r.get('is_fomc_week') or '').strip().lower() == 'true'
        if red:
            buckets['red_folder'].append(rth)
        else:
            buckets['quiet'].append(rth)
        if fomc:
            buckets['fomc'].append(rth)
        if 'CPI' in names:
            buckets['CPI'].append(rth)
        if 'NON-FARM' in names or 'NONFARM' in names or 'NFP' in names or 'PAYROLL' in names:
            buckets['NFP'].append(rth)
        if 'PPI' in names:
            buckets['PPI'].append(rth)

    out: dict[str, dict] = {'_base_avg': {'avg': base, 'n': len(all_ranges)}}
    for tag, vals in buckets.items():
        if len(vals) < 10:
            continue
        avg = _mean(vals)
        out[tag] = {'mult': avg / base, 'avg': avg, 'n': len(vals)}
    return out


# ======================================================================
# Event tagging / range estimate
# ======================================================================

# Order matters — first match wins for the headline multiplier.
_EVENT_MULT_KEYS = ['FOMC', 'CPI', 'NFP', 'PPI']


def _event_mult_tag(event_type: str, title: str) -> str | None:
    t = (event_type + ' ' + title).upper()
    if 'FOMC' in t or 'FEDERAL FUNDS' in t:
        return 'FOMC'
    if 'CPI' in t or 'CONSUMER PRICE' in t:
        return 'CPI'
    if 'NON-FARM' in t or 'NONFARM' in t or 'NFP' in t or 'PAYROLL' in t:
        return 'NFP'
    if 'PPI' in t or 'PRODUCER PRICE' in t:
        return 'PPI'
    return None


def _event_mult(day_events: list[dict], multipliers: dict[str, dict]) -> tuple[float, str | None]:
    """Pick the strongest event multiplier present that day (FOMC > CPI >
    NFP > PPI > generic red-folder). Returns (mult, tag)."""
    chosen_tag = None
    mult = 1.0
    for ev in day_events:
        tag = _event_mult_tag(ev.get('event_type', ''), ev.get('event', ''))
        key = tag if tag and tag in multipliers else None
        if key is None and ev.get('event_type'):
            key = 'red_folder' if 'red_folder' in multipliers else None
            tag = tag or 'red_folder'
        if key and multipliers[key]['mult'] > mult:
            mult = multipliers[key]['mult']
            chosen_tag = tag
    return mult, chosen_tag


def estimate_buckets(anchors: dict | None, day_events: list[dict],
                     multipliers: dict[str, dict],
                     weekday_or45: float | None,
                     weekday_full: float | None) -> dict:
    """Expected range per window (or45 / f90 / rest / full).

    Each bucket anchors on the live recent-median for that window, scaled by
    the day's event multiplier. The multiplier is derived from full-session
    history (events expand the whole day), applied uniformly as a baseline.
    Falls back to historical weekday averages for or45/full when the live
    intraday fetch is unavailable; f90/rest have no CSV history so go null.
    """
    mult, tag = _event_mult(day_events, multipliers)

    base = dict(anchors) if anchors else {}
    src = 'live median20'
    if not base:
        # No live intraday — fall back to weekday history where we have it.
        base = {'or45': weekday_or45, 'full': weekday_full}
        src = 'weekday avg (no live)'

    out = {'mult': round(mult, 2), 'event_tag': tag,
           'method': f'{src} × {mult:.2f}' + (f' [{tag}]' if tag else '')}
    for key in RANGE_BUCKETS:
        b = base.get(key)
        if b:
            point = b * mult
            out[key] = {'point': round(point), 'lo': round(point * 0.75),
                        'hi': round(point * 1.25)}
        else:
            out[key] = {'point': None, 'lo': None, 'hi': None}
    return out


# ======================================================================
# Live calendar + ATR
# ======================================================================

def _fetch_week_events() -> tuple[list, bool]:
    """All CalendarEvent for this+next ISO week. Returns (events, ok)."""
    try:
        from live_calendar import fetch_week
    except ImportError:
        return [], False
    events = []
    ok = False
    for w in ('thisweek', 'nextweek'):
        try:
            events.extend(fetch_week(w))
            ok = True
        except Exception as e:  # CalendarError or network
            print(f'  [warn] calendar fetch {w} failed: {e}', file=sys.stderr)
    return events, ok


def _us_high_for_day(all_events: list, day: date) -> list[dict]:
    """Red-folder rows for `day`, sorted by ET time, with PST added."""
    try:
        from live_calendar import filter_us_high
    except ImportError:
        return []
    out = []
    for e in filter_us_high(all_events, day):
        row = e.to_briefing_row()  # date, event_type, event, time_et, impact
        if e.time_et is not None:
            pt = e.time_et.astimezone(PT_TZ)
            et_t = e.time_et.time()
            row['time_pt'] = pt.strftime('%-I:%M %p').lower()
            row['time_et_fmt'] = e.time_et.strftime('%-I:%M %p').lower()
            row['pt_minutes'] = pt.hour * 60 + pt.minute
            row['pre_rth'] = et_t < RTH_OPEN_ET
            # In-window = lands DURING the first 90 min (e.g. 10:00 ET ISM /
            # JOLTS / Consumer Sentiment) — more disruptive to an open trade
            # than 8:30 data already digested by the open.
            row['in_window'] = RTH_OPEN_ET <= et_t < WINDOW_END_ET
        else:
            row['time_pt'] = 'tentative'
            row['time_et_fmt'] = 'tentative'
            row['pt_minutes'] = None
            row['pre_rth'] = False
            row['in_window'] = False
        out.append(row)
    out.sort(key=lambda r: (r['pt_minutes'] is None, r.get('pt_minutes') or 0))
    return out


_VOL_REGIME_BANDS = [
    (0.33, 'low',      'Quiet — expect compression; dump-capture unlikely, fade extremes'),
    (0.66, 'normal',   'Normal range regime — standard matrix plays'),
    (0.90, 'elevated', 'Elevated vol — dump-capture armed, wider stops, size up on A+'),
    (1.01, 'high',     'High vol — big OR width likely; dump-capture sweet spot but choppy'),
]


def _pctile(sorted_vals: list[float], x: float) -> float:
    if not sorted_vals:
        return 0.5
    return sum(1 for v in sorted_vals if v <= x) / len(sorted_vals)


def _intraday_day_records(lookback: str = '60d') -> list[dict]:
    """Per-RTH-day records bucketed into Phil's trading windows.

    Each record: {date, or45, f90, rest, full, high, low, close} where the
    bucket values are the high-low range within that ET window. Built from
    5-minute Yahoo bars (capped at ~60d). Empty list on fetch failure.
    """
    try:
        from live_market import fetch_yahoo_1m
    except ImportError:
        return []
    try:
        bars = fetch_yahoo_1m(symbol='NQ=F', range_=lookback, interval='5m')
    except Exception:
        return []
    by_date: dict[date, list[dict]] = defaultdict(list)
    for b in bars:
        t = b['ts_ny'].time()
        if RTH_OPEN_ET <= t < RTH_CLOSE_ET:
            by_date[b['ts_ny'].date()].append(b)

    def _rng(day_bars, lo_t, hi_t):
        ws = [x for x in day_bars if lo_t <= x['ts_ny'].time() < hi_t]
        if not ws:
            return None
        return max(x['high'] for x in ws) - min(x['low'] for x in ws)

    recs = []
    for d in sorted(by_date):
        db = by_date[d]
        last_bar = max(db, key=lambda x: x['ts_ny'])
        recs.append({
            'date': d,
            'or45': _rng(db, RTH_OPEN_ET, OR45_END_ET),
            'f90': _rng(db, RTH_OPEN_ET, WINDOW_END_ET),
            'rest': _rng(db, WINDOW_END_ET, RTH_CLOSE_ET),
            'full': max(x['high'] for x in db) - min(x['low'] for x in db),
            'high': max(x['high'] for x in db),
            'low': min(x['low'] for x in db),
            'close': last_bar['close'],
        })
    return recs


def _live_market_context(target_date: date, n: int = 20) -> dict | None:
    """One 5m fetch → per-window range anchors, vol regime, and key
    price-structure levels (draws for the first 90 min).

    Anchors are the MEDIAN of the last `n` sessions per window (or45 / f90 /
    rest / full), not the mean: NQ spike days (saw 1600pt) inflate a 20-day
    mean above a typical session. Vol regime = percentile of the full-session
    median within the last ~60 sessions. Levels are robust structure
    (prior-week H/L, 20-day H/L, ATH) — NOT naked POCs (naked-VP study killed
    those). Returns None on fetch failure.
    """
    try:
        from live_market import fetch_yahoo_1m
    except ImportError:
        return None
    recs = _intraday_day_records('60d')
    prior = [r for r in recs if r['date'] < target_date]
    if len(prior) < n:
        return None

    import statistics

    def _bucket_median(key):
        vals = [r[key] for r in prior[-n:] if r[key] is not None]
        return statistics.median(vals) if vals else None

    anchors = {k: _bucket_median(k) for k in RANGE_BUCKETS}
    full_ranges = [r['full'] for r in prior if r['full'] is not None]
    window_full = full_ranges[-n:]
    median = statistics.median(window_full)

    # Vol regime: where the full-session median sits within the last ~60
    # sessions — a "vs last quarter" read.
    hist = sorted(full_ranges)
    vol_pct = _pctile(hist, median)
    regime, regime_note = 'normal', ''
    for thresh, label, note in _VOL_REGIME_BANDS:
        if vol_pct <= thresh:
            regime, regime_note = label, note
            break

    # ---- price-structure levels (draws) ----
    last = prior[-1]
    ref = last['close']
    last20 = prior[-20:]
    hi20 = max(d['high'] for d in last20)
    lo20 = min(d['low'] for d in last20)
    # Prior completed Mon-Fri week relative to target_date's week.
    tmonday = target_date - timedelta(days=target_date.weekday())
    pw_lo = tmonday - timedelta(days=7)
    pw_days = [d for d in prior if pw_lo <= d['date'] < tmonday]
    pw_high = max((d['high'] for d in pw_days), default=None)
    pw_low = min((d['low'] for d in pw_days), default=None)

    # ATH — best-effort daily fetch (5y). NQ's all-time high may predate the
    # 60d intraday window, so use a long daily series; fall back to the 60d
    # high if the fetch fails.
    ath = max(d['high'] for d in prior)
    ath_label = 'Recent high (60d)'
    try:
        daily = fetch_yahoo_1m(symbol='NQ=F', range_='5y', interval='1d')
        dmax = max(b['high'] for b in daily)
        if dmax >= ath:
            ath, ath_label = dmax, 'All-time high'
    except Exception:
        pass

    def _lvl(name, price):
        if price is None:
            return None
        return {'name': name, 'price': round(price, 1),
                'dist': round(price - ref, 1), 'dist_abs': round(abs(price - ref))}

    # Candidates in priority order (most significant label wins on ties).
    candidates = [lv for lv in [
        _lvl(ath_label, ath),
        _lvl('Prior-week high', pw_high),
        _lvl('20-day high', hi20),
        _lvl('Prior-week low', pw_low),
        _lvl('20-day low', lo20),
    ] if lv]
    # Dedupe by price — when the recent high IS the prior-week / 20-day high,
    # show it once under the strongest label rather than three identical rows.
    seen_prices = set()
    levels = []
    for lv in candidates:
        if lv['price'] in seen_prices:
            continue
        seen_prices.add(lv['price'])
        levels.append(lv)
    # Sort by absolute distance — nearest draws first.
    levels.sort(key=lambda lv: lv['dist_abs'])
    # ATH magnet only real within ~100pts (ATH-availability study).
    ath_near = abs(ath - ref) <= 100

    return {
        'anchors': anchors,
        'median': median, 'mean': statistics.mean(window_full),
        'max': max(window_full), 'n': len(window_full),
        'vol_pct': round(vol_pct, 2), 'regime': regime, 'regime_note': regime_note,
        'ref_close': round(ref, 1), 'ref_date': last['date'].isoformat(),
        'levels': levels, 'ath_near': ath_near,
        'ath_dist': round(ath - ref, 1),
    }


# ======================================================================
# Build
# ======================================================================

DOW_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

_DUMP_EVENTS = ('CPI', 'NFP', 'PCE', 'PPI')


def day_play_notes(day: dict, events: list[dict], regime: str,
                   is_fomc_day_week: bool, weekday_idx: int) -> list[dict]:
    """Map the day's conditions to Phil's validated plays. Each note is
    {tag, text} — grounded in the studies, not generic TA. Order = priority.
    """
    notes = []
    pre = [e for e in events if e.get('pre_rth')]
    inwin = [e for e in events if e.get('in_window')]
    names = ' '.join((e.get('event_type', '') + ' ' + e.get('event', ''))
                     for e in events).upper()

    # FOMC decision day — chop until 2pm ET; first 90 min often range-bound.
    if day.get('fomc_decision'):
        notes.append({'tag': 'AVOID', 'text':
            'FOMC decision 2pm ET — expect compression/chop through the morning; '
            'reduce size, the move comes after your window.'})

    # Quad witching / OPEX — pinning + heavy volume, trend plays less reliable.
    if day.get('quad_witching'):
        notes.append({'tag': 'CAUTION', 'text':
            'Quad witching — pinning to large strikes + elevated volume; '
            'mean-reversion over trend, fade extensions into round numbers.'})

    # Pre-RTH market-mover → dump-capture / opening-FVG short conditions.
    if pre and any(k in names for k in _DUMP_EVENTS):
        notes.append({'tag': 'ARMED', 'text':
            'Pre-RTH market-mover — dump-capture watch (WR scales with dump '
            'size) + opening-FVG short tier-2 more likely. Wait for the 9:30 '
            'reaction, don\'t pre-position.'})
    elif pre:
        notes.append({'tag': 'NEWS', 'text':
            'Pre-RTH red folder — opening impulse likely; let the first FVG '
            'form before committing.'})

    # In-window event (10:00 ET data) — second impulse mid-session.
    if inwin:
        t = inwin[0].get('time_et_fmt', '10:00 am')
        notes.append({'tag': 'MID', 'text':
            f'{t} ET data lands INSIDE your window — expect a second impulse; '
            'a clean 9:30-10:00 trend can reverse on the print.'})

    # Vol-regime-driven default play set (only when no override above dominates).
    if regime in ('elevated', 'high'):
        notes.append({'tag': 'PLAY', 'text':
            'Vol elevated — dump-capture armed, wider OR expected; '
            'favor momentum continuation over fades.'})
    elif regime == 'low' and not pre and not day.get('fomc_decision'):
        notes.append({'tag': 'PLAY', 'text':
            'Quiet regime — expect a tight OR; OR-H/L sweep + reversion plays '
            'over breakouts, M1 short on weak opens.'})

    # Monday post-weekend expansion tendency.
    if weekday_idx == 0 and not pre:
        notes.append({'tag': 'NOTE', 'text':
            'Monday — weekend gap + range-expansion tendency; respect the '
            'opening drive direction.'})

    if not notes:
        notes.append({'tag': 'PLAY', 'text':
            'Standard matrix — M1 short / OR-H/L / opening-FVG geometry on a '
            'clean open.'})
    return notes


def build_week_ahead(gen_date: date) -> dict:
    week = upcoming_trading_week(gen_date)
    rows = _read_history(TRADING_DAYS_CSV)
    wd_stats = weekday_range_stats(rows)
    mults = event_range_multipliers(rows)
    all_events, cal_ok = _fetch_week_events()
    ctx = _live_market_context(week[0])
    anchors = ctx['anchors'] if ctx else None
    regime = ctx['regime'] if ctx else 'normal'

    try:
        from live_calendar import is_fomc_week
        week_is_fomc = is_fomc_week(all_events, week[2]) if cal_ok else None
    except ImportError:
        week_is_fomc = None

    days = []
    total_red = 0
    earliest_wake = None  # (pt_minutes, day_idx, label)
    for i, d in enumerate(week):
        events = _us_high_for_day(all_events, d) if cal_ok else []
        total_red += len(events)
        pre_rth = [e for e in events if e.get('pre_rth')]
        wake = pre_rth[0] if pre_rth else None
        if wake and wake['pt_minutes'] is not None:
            if earliest_wake is None or wake['pt_minutes'] < earliest_wake[0]:
                earliest_wake = (wake['pt_minutes'], i, wake['time_pt'])

        wd = wd_stats.get(d.weekday()) or {}
        wd_or45 = wd.get('avg_or45_range')
        wd_full = wd.get('avg_rth_range')
        est = estimate_buckets(anchors, events, mults, wd_or45, wd_full)
        quad = is_quad_witching(d)
        fomc_decision = any(
            e.country == 'USD' and any(kw in e.title for kw in (
                'FOMC Statement', 'Federal Funds Rate', 'FOMC Press Conference'))
            for e in all_events if e.date == d
        ) if cal_ok else False

        day = {
            'date': d.isoformat(),
            'day_of_week': DOW_NAMES[i],
            'events': events,
            'n_red_folder': len(events),
            'wake_up_pt': wake['time_pt'] if wake else None,
            'in_window_event': any(e.get('in_window') for e in events),
            'quad_witching': quad,
            'fomc_decision': fomc_decision,
            'hist_avg_rth_range': round(wd_full) if wd_full else None,
            'hist_avg_or45_range': round(wd_or45) if wd_or45 else None,
            'range_estimate': est,
        }
        day['play_notes'] = day_play_notes(day, events, regime, bool(week_is_fomc), i)
        days.append(day)

    return {
        'schema_version': 1,
        'meta': {
            'generated_at_pt': datetime.now(PT_TZ).strftime('%Y-%m-%d %I:%M %p PT'),
            'week_start': week[0].isoformat(),
            'week_end': week[-1].isoformat(),
            'gen_date': gen_date.isoformat(),
        },
        'summary': {
            'is_fomc_week': week_is_fomc,
            'total_red_folder': total_red,
            'has_quad_witching': any(dd['quad_witching'] for dd in days),
            'earliest_wake_pt': earliest_wake[2] if earliest_wake else None,
            'earliest_wake_day': DOW_NAMES[earliest_wake[1]] if earliest_wake else None,
            'recent_median_or45_pts': (
                round(ctx['anchors']['or45']) if ctx and ctx['anchors'].get('or45') else None),
            'recent_median_f90_pts': (
                round(ctx['anchors']['f90']) if ctx and ctx['anchors'].get('f90') else None),
            'recent_median_range_pts': round(ctx['median']) if ctx else None,
            'recent_mean_range_pts': round(ctx['mean']) if ctx else None,
            'recent_max_range_pts': round(ctx['max']) if ctx else None,
            'vol_spike_recent': bool(ctx and ctx['max'] > 2 * ctx['median']),
            'vol_regime': ctx['regime'] if ctx else None,
            'calendar_ok': cal_ok,
        },
        'market': ({
            'regime': ctx['regime'],
            'regime_note': ctx['regime_note'],
            'vol_pct': ctx['vol_pct'],
            'anchors': {k: (round(v) if v else None) for k, v in ctx['anchors'].items()},
            'median_range_pts': round(ctx['median']),
            'ref_close': ctx['ref_close'],
            'ref_date': ctx['ref_date'],
            'levels': ctx['levels'],
            'ath_near': ctx['ath_near'],
            'ath_dist': ctx['ath_dist'],
        } if ctx else None),
        'days': days,
        'baselines': {
            'event_multipliers': {
                k: {'mult': round(v['mult'], 2), 'n': v['n']}
                for k, v in mults.items() if k.startswith('_') is False and 'mult' in v
            },
            'base_avg_range': round(mults['_base_avg']['avg']) if '_base_avg' in mults else None,
        },
        'notes': [
            'Times shown in PST/PDT (America/Los_Angeles). 8:30 AM ET = 5:30 AM PST.',
            'Range estimates are split by window — first 45 min (your opening range), '
            'first 90 min, and the rest (11:00-close) — each the recent-median range for '
            'that window scaled by the event multiplier.',
            'These are event-conditioned BASELINES, not the same-morning OR-width forecast '
            '(which needs that day\'s gap + overnight range).',
        ],
    }


def export_week_ahead(data: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / 'week_ahead.json'
    js_path = out_dir / 'week_ahead.js'
    json_str = json.dumps(data, indent=2)
    json_path.write_text(json_str + '\n')
    js_path.write_text(
        '// Auto-generated by tools/week_ahead.py --export.\n'
        f'window.WEEK_AHEAD = {json_str};\n'
    )
    return json_path, js_path


# ======================================================================
# CLI / pretty-print
# ======================================================================

def _print_report(data: dict) -> None:
    m, s = data['meta'], data['summary']
    print(f"\n  WEEK AHEAD — {m['week_start']} → {m['week_end']}")
    print(f"  generated {m['generated_at_pt']}")
    flags = []
    if s['is_fomc_week']:
        flags.append('FOMC WEEK')
    if s['has_quad_witching']:
        flags.append('QUAD WITCHING')
    if s.get('recent_median_or45_pts'):
        flags.append(f"OR45 med {s['recent_median_or45_pts']}pt")
    print(f"  {s['total_red_folder']} red-folder events" +
          (f" · {' · '.join(flags)}" if flags else ''))
    if s.get('vol_spike_recent'):
        print(f"  ⚠ recent vol spike: max {s['recent_max_range_pts']}pt vs "
              f"median {s['recent_median_range_pts']}pt — estimates use the median")
    if s['earliest_wake_pt']:
        print(f"  earliest wake-up: {s['earliest_wake_pt']} PT ({s['earliest_wake_day']})")
    if not s['calendar_ok']:
        print('  [warn] calendar feed unavailable — events incomplete')
    mk = data.get('market')
    if mk:
        print(f"  vol regime: {mk['regime'].upper()} ({int(mk['vol_pct']*100)}th pctile) "
              f"— {mk['regime_note']}")
        print(f"  ref close {mk['ref_close']} ({mk['ref_date']})"
              + (f"  ·  ATH ~{mk['ath_dist']:+.0f}pt [NEAR]" if mk['ath_near'] else ''))
        for lv in mk['levels']:
            print(f"        {lv['dist']:+8.1f}pt  {lv['name']}  @ {lv['price']}")
    print('  ' + '-' * 64)
    for d in data['days']:
        est = d['range_estimate']
        def _b(key):
            b = est.get(key) or {}
            return f"{b['lo']}-{b['hi']}" if b.get('point') else 'n/a'
        line = (f"  {d['day_of_week']:9s} {d['date']}  "
                f"OR45 {_b('or45')}  90m {_b('f90')}  rest {_b('rest')} pt")
        if d['hist_avg_or45_range']:
            line += f"  (OR45 hist~{d['hist_avg_or45_range']})"
        if d['quad_witching']:
            line += '  [QUAD WITCH]'
        if d.get('fomc_decision'):
            line += '  [FOMC]'
        print(line)
        for e in d['events']:
            if e.get('pre_rth'):
                tag = '  ⏰ WAKE-UP'
            elif e.get('in_window'):
                tag = '  ◀ IN-WINDOW'
            else:
                tag = ''
            print(f"        {e['time_pt']:>9s} PT ({e['time_et_fmt']} ET)  "
                  f"{e['event']}{tag}")
        if not d['events']:
            print('        (no red-folder events)')
        for nt in d.get('play_notes', []):
            print(f"        » [{nt['tag']}] {nt['text']}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description='NQ week-ahead report')
    ap.add_argument('--export', action='store_true',
                    help='write week_ahead.json + week_ahead.js to tools/briefing/')
    ap.add_argument('--out-dir', default=str(BRIEFING_DIR))
    ap.add_argument('--gen-date', default=None,
                    help='YYYY-MM-DD generation date (default: today)')
    args = ap.parse_args()

    gen = date.fromisoformat(args.gen_date) if args.gen_date else date.today()
    data = build_week_ahead(gen)
    _print_report(data)
    if args.export:
        jp, js = export_week_ahead(data, Path(args.out_dir))
        print(f'  wrote {jp}')
        print(f'  wrote {js}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
