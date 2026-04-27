#!/usr/bin/env python3
"""
NQ Morning Briefing — pre-market report for FVGC model trading.

Runs at 6:10 AM PT (9:10 ET), 20 minutes before New York open.
Reads live market data + study outputs + playbook config to produce
a structured briefing with armed edges, watch triggers, and avoid signals.

All edge numbers come from parsed study files, not from this script.
Re-running studies auto-updates the briefing.

Usage:
    python tools/morning_briefing.py              # live, today
    python tools/morning_briefing.py --offline    # skip Yahoo, use CSV
    python tools/morning_briefing.py --date 2025-08-01  # historical
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo('America/New_York')
    PT_TZ = ZoneInfo('America/Los_Angeles')
except ImportError:
    import pytz
    NY_TZ = pytz.timezone('America/New_York')
    PT_TZ = pytz.timezone('America/Los_Angeles')

# Resolve paths relative to repo root
REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / 'tools'
PLAYBOOK = REPO / 'playbook'

sys.path.insert(0, str(TOOLS))


# ======================================================================
# Data classes
# ======================================================================

@dataclass
class ComboEdge:
    rank: int
    factors: list[str]
    n: int
    wr: float
    pf: float
    p_wr: float
    fdr: bool = False
    source: str = ''  # 'top_wr', 'top_wr_robust', 'top_pf', 'avoid'


@dataclass
class FactorEdge:
    rank: int
    factor: str
    n: int
    wr: float
    lift: float
    pf: float
    p_wr: float
    sig: str = ''  # '*', '**', ''


@dataclass
class LiquidityLevel:
    group: str
    label: str
    price: float
    distance_pts: float
    direction: str   # 'above' or 'below'
    tier: str
    hit_rate_45m: float
    wr_as_magnet: float
    pf_as_magnet: float
    note: str = ''


# ======================================================================
# Parsers — combo_top_results.txt
# ======================================================================

_COMBO_RE = re.compile(
    r'^\s*(\d+)\.\s+'         # rank
    r'(.+?)\s{2,}'            # factors (space-separated by " + ")
    r'n=\s*(\d+)\s+'          # n
    r'WR=\s*([\d.]+)%\s+'     # WR
    r'PF=\s*([\d.]+)\s+'      # PF
    r'p_wr=([\d.]+)'          # p_wr
    r'(?:\s+\[FDR\])?'        # optional FDR flag
)


def parse_combo_results(path: Path) -> dict[str, list[ComboEdge]]:
    """Parse combo_top_results.txt into sections."""
    if not path.exists():
        return {}

    text = path.read_text()
    sections: dict[str, list[ComboEdge]] = {}

    section_markers = [
        ('TOP 20 BY WIN RATE (n >= 30', 'top_wr_n30'),
        ('TOP 20 BY PROFIT FACTOR', 'top_pf'),
        ('TOP 20 BY WIN RATE (n >= 50', 'top_wr_robust'),
        ('BOTTOM 20', 'avoid'),
    ]

    lines = text.splitlines()
    current_section = None
    for line in lines:
        for marker, key in section_markers:
            if marker in line:
                current_section = key
                sections[key] = []
                break

        if current_section is None:
            continue

        m = _COMBO_RE.match(line)
        if m:
            factors = [f.strip() for f in m.group(2).split(' + ')]
            sections[current_section].append(ComboEdge(
                rank=int(m.group(1)),
                factors=factors,
                n=int(m.group(3)),
                wr=float(m.group(4)),
                pf=float(m.group(5)),
                p_wr=float(m.group(6)),
                fdr='[FDR]' in line,
                source=current_section,
            ))

    return sections


# ======================================================================
# Parsers — factor_importance_report.txt
# ======================================================================

_FACTOR_WR_RE = re.compile(
    r'^\s*(\d+)\s+'           # rank
    r'(\S+)\s+'               # factor name
    r'(\d+)\s+'               # n
    r'([\d.]+)%\s+'           # WR%
    r'([+-][\d.]+)%\s+'       # lift
    r'([\d.]+)\s+'            # PF
    r'([\d.]+)\s*'            # p_wr
    r'(\*{0,2})?'             # sig
)

_FACTOR_AVOID_RE = re.compile(
    r'^\s*(\d+)\s+'
    r'(\S+)\s+'
    r'n=\s*(\d+)\s+'
    r'WR=([\d.]+)%\s+'
    r'lift=([+-]?[\d.]+)%\s+'
    r'PF=([\d.]+)\s+'
    r'p=([\d.]+)\s*'
    r'(\*{0,2})?'
)


def parse_factor_importance(path: Path) -> dict[str, list[FactorEdge]]:
    """Parse factor_importance_report.txt."""
    if not path.exists():
        return {}

    text = path.read_text()
    result: dict[str, list[FactorEdge]] = {'ranked': [], 'avoid': []}

    lines = text.splitlines()
    in_ranked = False
    in_avoid = False

    for line in lines:
        if 'RANKED BY WIN RATE LIFT' in line:
            in_ranked = True
            in_avoid = False
            continue
        if 'AVOID LIST' in line and 'Factors that HURT' in line:
            in_avoid = True
            in_ranked = False
            continue
        if 'RANKED BY PROFIT FACTOR' in line or 'BEST FACTOR PER CATEGORY' in line:
            in_ranked = False
            in_avoid = False
            continue

        if in_ranked:
            m = _FACTOR_WR_RE.match(line)
            if m:
                result['ranked'].append(FactorEdge(
                    rank=int(m.group(1)),
                    factor=m.group(2),
                    n=int(m.group(3)),
                    wr=float(m.group(4)),
                    lift=float(m.group(5)),
                    pf=float(m.group(6)),
                    p_wr=float(m.group(7)),
                    sig=m.group(8) or '',
                ))

        if in_avoid:
            m = _FACTOR_AVOID_RE.match(line)
            if m:
                result['avoid'].append(FactorEdge(
                    rank=int(m.group(1)),
                    factor=m.group(2),
                    n=int(m.group(3)),
                    wr=float(m.group(4)),
                    lift=float(m.group(5)),
                    pf=float(m.group(6)),
                    p_wr=float(m.group(7)),
                    sig=m.group(8) or '',
                ))

    return result


# ======================================================================
# Config + plays loader
# ======================================================================

def load_config(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_plays(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


# ======================================================================
# Factor determination — from live context or CSV
# ======================================================================

def load_trading_day_row(csv_path: Path, target_date: date) -> dict | None:
    """Load a single row from trading_days.csv for the given date."""
    if not csv_path.exists():
        return None
    ds = target_date.isoformat()
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('date') == ds:
                return row
    return None


def load_prior_trading_day_row(csv_path: Path, target_date: date) -> dict | None:
    """Load the most recent trading day before target_date."""
    if not csv_path.exists():
        return None
    best = None
    ds = target_date.isoformat()
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('date', '') < ds:
                best = row
    return best


def compute_percentile(csv_path: Path, column: str, percentile: float) -> float | None:
    """Compute a percentile value from the trading_days CSV."""
    if not csv_path.exists():
        return None
    vals = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            v = row.get(column, '')
            if v:
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
    if not vals:
        return None
    vals.sort()
    idx = int(len(vals) * percentile)
    idx = max(0, min(idx, len(vals) - 1))
    return vals[idx]


def _open_events_dictreader(events_path: Path):
    """csv.DictReader for events CSV, tolerating a leading blank line.
    The events file ships with a leading \\n that breaks naive DictReader
    (fieldnames become []). Returns the file handle and reader, both of
    which the caller must close/exhaust."""
    f = open(events_path)
    # Skip blank lines so DictReader picks up the real header.
    pos = f.tell()
    while True:
        line = f.readline()
        if not line:
            break
        if line.strip():
            f.seek(pos)
            break
        pos = f.tell()
    return f, csv.DictReader(f)


def load_events_for_date(events_path: Path, target_date: date) -> list[dict]:
    """Load red-folder events for a specific date."""
    if not events_path.exists():
        return []
    ds = target_date.isoformat()
    events = []
    f, reader = _open_events_dictreader(events_path)
    try:
        for row in reader:
            if row.get('date', '').strip() == ds:
                events.append(row)
    finally:
        f.close()
    return events


def is_fomc_week(events_path: Path, target_date: date) -> bool:
    """Check if target_date falls in the same ISO week as any FOMC Statement."""
    if not events_path.exists():
        return False
    target_year, target_week, _ = target_date.isocalendar()
    f, reader = _open_events_dictreader(events_path)
    try:
        for row in reader:
            if 'FOMC' in row.get('event_type', ''):
                try:
                    d = date.fromisoformat(row['date'].strip())
                    y, w, _ = d.isocalendar()
                    if y == target_year and w == target_week:
                        return True
                except ValueError:
                    pass
    finally:
        f.close()
    return False


def determine_factors_from_context(ctx, config: dict, csv_path: Path,
                                   events_path: Path, target_date: date,
                                   live_events=None) -> dict[str, bool]:
    """Determine which factors are TRUE today from a SessionContext.

    `live_events` is the list of CalendarEvent from live_calendar.fetch_for_target,
    or None to fall back to the (often stale) events CSV.
    """
    factors: dict[str, bool] = {}

    # Gap
    if ctx.gap_pts is not None:
        factors['gap_up'] = ctx.gap_pts > 0
        factors['gap_down'] = ctx.gap_pts < 0
    else:
        factors['gap_up'] = False
        factors['gap_down'] = False

    # Overnight direction
    factors['overnight_up'] = ctx.overnight_direction == 'up'
    factors['overnight_down'] = ctx.overnight_direction == 'down'

    # Overnight range percentiles
    p20 = compute_percentile(csv_path, 'overnight_range', 0.20)
    p80 = compute_percentile(csv_path, 'overnight_range', 0.80)
    if ctx.overnight_range is not None and p20 is not None and p80 is not None:
        factors['tight_overnight'] = ctx.overnight_range <= p20
        factors['wide_overnight'] = ctx.overnight_range >= p80
    else:
        factors['tight_overnight'] = False
        factors['wide_overnight'] = False

    # Prior day close position
    if ctx.prior_day_close_position is not None:
        factors['prior_day_down'] = ctx.prior_day_close_position < 0.25
        factors['prior_day_up'] = ctx.prior_day_close_position > 0.75
    else:
        factors['prior_day_down'] = False
        factors['prior_day_up'] = False

    # Calendar / news — prefer live calendar over the (often stale) CSV
    if live_events is not None:
        from live_calendar import (
            filter_us_high as _lc_us_high,
            is_fomc_week as _lc_is_fomc,
            is_pre_rth_news as _lc_pre_rth,
        )
        red = _lc_us_high(live_events, target_date)
        factors['has_red_folder'] = len(red) > 0
        factors['no_red_folder'] = len(red) == 0
        factors['has_pre_rth_news'] = _lc_pre_rth(live_events, target_date)
        factors['no_pre_rth_news'] = not factors['has_pre_rth_news']
        fomc = _lc_is_fomc(live_events, target_date)
    else:
        events = load_events_for_date(events_path, target_date)
        factors['has_red_folder'] = len(events) > 0
        factors['no_red_folder'] = len(events) == 0
        pre_rth = [e for e in events if e.get('event_type', '') in ('NFP', 'CPI', 'PPI', 'Retail Sales')]
        factors['has_pre_rth_news'] = len(pre_rth) > 0
        factors['no_pre_rth_news'] = len(pre_rth) == 0
        fomc = is_fomc_week(events_path, target_date)
    factors['is_fomc_week'] = fomc
    factors['not_fomc_week'] = not fomc

    # Day of week
    factors['monday'] = target_date.weekday() == 0
    factors['tuesday'] = target_date.weekday() == 1
    factors['wednesday'] = target_date.weekday() == 2
    factors['thursday'] = target_date.weekday() == 3
    factors['friday'] = target_date.weekday() == 4

    # entry_inside_prior_day_value_area — requires manual VP check, always False here
    # The Thursday VA play will show as 'partial' on Thursdays with a prompt to verify
    factors['entry_inside_prior_day_value_area'] = False

    # VIXY from prior trading day row
    prior_row = load_prior_trading_day_row(csv_path, target_date)
    if prior_row and prior_row.get('vixy_prior_close'):
        try:
            vixy = float(prior_row['vixy_prior_close'])
            vp25 = compute_percentile(csv_path, 'vixy_prior_close', 0.25)
            vp50 = compute_percentile(csv_path, 'vixy_prior_close', 0.50)
            if vp25 is not None and vp50 is not None:
                factors['low_vixy'] = vixy <= vp25
                factors['elevated_vixy'] = vixy > vp50
                factors['normal_vixy'] = vp25 < vixy <= vp50
            else:
                factors['low_vixy'] = False
                factors['elevated_vixy'] = False
                factors['normal_vixy'] = False
        except ValueError:
            factors['low_vixy'] = False
            factors['elevated_vixy'] = False
            factors['normal_vixy'] = False
    else:
        factors['low_vixy'] = False
        factors['elevated_vixy'] = False
        factors['normal_vixy'] = False

    return factors


def determine_factors_from_csv(csv_path: Path, events_path: Path,
                               target_date: date,
                               live_events=None) -> dict[str, bool] | None:
    """Determine factors purely from trading_days.csv (offline / historical)."""
    row = load_trading_day_row(csv_path, target_date)
    if row is None:
        return None

    factors: dict[str, bool] = {}

    # Gap
    gap = _float_or_none(row.get('gap_from_prior_close'))
    factors['gap_up'] = gap is not None and gap > 0
    factors['gap_down'] = gap is not None and gap < 0

    # Overnight
    factors['overnight_up'] = row.get('overnight_direction') == 'up'
    factors['overnight_down'] = row.get('overnight_direction') == 'down'

    on_range = _float_or_none(row.get('overnight_range'))
    p20 = compute_percentile(csv_path, 'overnight_range', 0.20)
    p80 = compute_percentile(csv_path, 'overnight_range', 0.80)
    if on_range is not None and p20 is not None and p80 is not None:
        factors['tight_overnight'] = on_range <= p20
        factors['wide_overnight'] = on_range >= p80
    else:
        factors['tight_overnight'] = False
        factors['wide_overnight'] = False

    # Prior day close position
    pcp = _float_or_none(row.get('prior_day_close_position'))
    factors['prior_day_down'] = pcp is not None and pcp < 0.25
    factors['prior_day_up'] = pcp is not None and pcp > 0.75

    # News / calendar — prefer live, fall back to CSV columns
    if live_events is not None:
        from live_calendar import (
            filter_us_high as _lc_us_high,
            is_fomc_week as _lc_is_fomc,
            is_pre_rth_news as _lc_pre_rth,
        )
        red = _lc_us_high(live_events, target_date)
        factors['has_red_folder'] = len(red) > 0
        factors['no_red_folder'] = len(red) == 0
        factors['has_pre_rth_news'] = _lc_pre_rth(live_events, target_date)
        factors['no_pre_rth_news'] = not factors['has_pre_rth_news']
        factors['is_fomc_week'] = _lc_is_fomc(live_events, target_date)
        factors['not_fomc_week'] = not factors['is_fomc_week']
    else:
        factors['has_red_folder'] = row.get('has_red_folder_news', '').lower() == 'true'
        factors['no_red_folder'] = not factors['has_red_folder']
        factors['has_pre_rth_news'] = row.get('has_pre_rth_news', '').lower() == 'true'
        factors['no_pre_rth_news'] = not factors['has_pre_rth_news']
        factors['is_fomc_week'] = row.get('is_fomc_week', '').lower() == 'true'
        factors['not_fomc_week'] = not factors['is_fomc_week']

    # Day of week (parse from timestamp or day_of_week column if available)
    dow_str = row.get('day_of_week_name', '') or row.get('day_of_week', '')
    ts_str = row.get('timestamp', '') or row.get('date', '')
    if dow_str:
        dow_str = dow_str.lower()
        factors['monday'] = dow_str == 'monday'
        factors['tuesday'] = dow_str == 'tuesday'
        factors['wednesday'] = dow_str == 'wednesday'
        factors['thursday'] = dow_str == 'thursday'
        factors['friday'] = dow_str == 'friday'
    elif ts_str:
        try:
            from datetime import datetime
            ts_date = datetime.fromisoformat(ts_str[:10]).date()
            factors['monday'] = ts_date.weekday() == 0
            factors['tuesday'] = ts_date.weekday() == 1
            factors['wednesday'] = ts_date.weekday() == 2
            factors['thursday'] = ts_date.weekday() == 3
            factors['friday'] = ts_date.weekday() == 4
        except Exception:
            for d in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday'):
                factors[d] = False
    else:
        for d in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday'):
            factors[d] = False

    # entry_inside_prior_day_value_area — requires manual VP check, always False here
    factors['entry_inside_prior_day_value_area'] = False

    # VIXY
    vixy = _float_or_none(row.get('vixy_prior_close'))
    if vixy is not None:
        vp25 = compute_percentile(csv_path, 'vixy_prior_close', 0.25)
        vp50 = compute_percentile(csv_path, 'vixy_prior_close', 0.50)
        if vp25 is not None and vp50 is not None:
            factors['low_vixy'] = vixy <= vp25
            factors['elevated_vixy'] = vixy > vp50
            factors['normal_vixy'] = vp25 < vixy <= vp50

    for key in ('low_vixy', 'elevated_vixy', 'normal_vixy'):
        factors.setdefault(key, False)

    return factors


def _float_or_none(v) -> float | None:
    if v is None or v == '':
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ======================================================================
# Combo matching — ARMED / WATCH / OFF
# ======================================================================

@dataclass
class MatchedCombo:
    combo: ComboEdge
    status: str        # 'armed', 'watch', 'off'
    pre_matched: list[str] = field(default_factory=list)
    pre_missing: list[str] = field(default_factory=list)
    post_needed: list[str] = field(default_factory=list)


def match_combos(combos: list[ComboEdge], today_factors: dict[str, bool],
                 factor_config: dict) -> list[MatchedCombo]:
    """Match each combo against today's pre-open factors."""
    results = []
    for combo in combos:
        pre_open = []
        post_open = []
        timing = []
        direction = []

        for f in combo.factors:
            kind = factor_config.get(f, {}).get('kind', 'unknown')
            if kind == 'pre_open':
                pre_open.append(f)
            elif kind == 'post_open':
                post_open.append(f)
            elif kind == 'timing':
                timing.append(f)
            elif kind == 'direction':
                direction.append(f)
            else:
                post_open.append(f)  # unknown → treat as post_open

        pre_matched = [f for f in pre_open if today_factors.get(f, False)]
        pre_missing = [f for f in pre_open if not today_factors.get(f, False)]

        if pre_missing:
            status = 'off'
        elif post_open:
            status = 'watch'
        else:
            status = 'armed'

        results.append(MatchedCombo(
            combo=combo,
            status=status,
            pre_matched=pre_matched,
            pre_missing=pre_missing,
            post_needed=post_open,
        ))

    return results


# ======================================================================
# Play matching — which Notion plays are relevant today
# ======================================================================

@dataclass
class MatchedPlay:
    play: dict
    pre_met: list[str]
    pre_missing: list[str]
    status: str  # 'active', 'partial', 'always'


def match_plays(plays: list[dict], today_factors: dict[str, bool]) -> list[MatchedPlay]:
    results = []
    for play in plays:
        pre_factors = play.get('pre_market_factors', [])
        if not pre_factors:
            results.append(MatchedPlay(
                play=play, pre_met=[], pre_missing=[], status='always'))
            continue

        met = [f for f in pre_factors if today_factors.get(f, False)]
        missing = [f for f in pre_factors if not today_factors.get(f, False)]

        if not missing:
            status = 'active'
        elif len(met) > 0:
            status = 'partial'
        else:
            continue  # no pre-market factors match — skip

        results.append(MatchedPlay(
            play=play, pre_met=met, pre_missing=missing, status=status))

    return results


# ======================================================================
# W1 confluence counter
# ======================================================================

def count_w1_confluences(today_factors: dict[str, bool], gap_pts: float | None) -> tuple[int, list[str]]:
    """Count W1 Short pre-market confluences. Returns (count, list_of_active)."""
    active = []
    if today_factors.get('gap_down'):
        active.append('gap_down')
    if gap_pts is not None and gap_pts <= -100:
        active.append('large_gap')
    if today_factors.get('overnight_down'):
        active.append('overnight_down')
    if today_factors.get('prior_day_down'):
        active.append('prior_day_down')
    return len(active), active


# ======================================================================
# Liquidity levels
# ======================================================================

def build_levels(ctx, config: dict, fvgs: list | None) -> list[LiquidityLevel]:
    """Build liquidity levels from session context and live FVGs."""
    if ctx.current_price is None:
        return []

    levels: list[LiquidityLevel] = []
    level_groups = config.get('level_groups', {})
    scope = config.get('tuning', {}).get('level_scope_pts', 100)

    def _add(group: str, label: str, price: float | None):
        if price is None:
            return
        dist = price - ctx.current_price
        if abs(dist) > scope:
            return
        grp = level_groups.get(group, {})
        levels.append(LiquidityLevel(
            group=group,
            label=label,
            price=price,
            distance_pts=dist,
            direction='above' if dist > 0 else 'below',
            tier=grp.get('tier', '?'),
            hit_rate_45m=grp.get('hit_rate_45m', 0),
            wr_as_magnet=grp.get('wr_as_magnet', 0),
            pf_as_magnet=grp.get('pf_as_magnet', 0),
            note=grp.get('note', ''),
        ))

    # Session levels
    _add('asia', 'Asia high', ctx.asia_high)
    _add('asia', 'Asia low', ctx.asia_low)
    _add('london', 'London high', ctx.london_high)
    _add('london', 'London low', ctx.london_low)
    _add('overnight', 'Overnight high', ctx.overnight_high)
    _add('overnight', 'Overnight low', ctx.overnight_low)
    _add('prev_day', 'Prev day high', ctx.prior_rth_high)
    _add('prev_day', 'Prev day low', ctx.prior_rth_low)

    # Live FVGs
    if fvgs:
        for fvg in fvgs:
            group = f'htf_fvg_{fvg.timeframe}'
            label = f'{fvg.timeframe} FVG ({fvg.direction})'
            _add(group, label, fvg.near_edge)

    # Sort by absolute distance
    levels.sort(key=lambda l: abs(l.distance_pts))
    return levels


def distance_bucket_hit_rate(dist_pts: float, config: dict) -> float:
    """Look up approximate hit rate from distance buckets."""
    buckets = config.get('distance_bucket_hit_rates', {})
    ad = abs(dist_pts)
    if ad <= 25:
        return buckets.get('0-25', 86.0)
    elif ad <= 50:
        return buckets.get('25-50', 63.0)
    elif ad <= 100:
        return buckets.get('50-100', 40.0)
    elif ad <= 200:
        return buckets.get('100-200', 17.0)
    else:
        return buckets.get('200+', 6.0)


# ======================================================================
# Report printer
# ======================================================================

def fmt_price(v: float | None) -> str:
    if v is None:
        return '—'
    return f'{v:.2f}'


def fmt_pct(v: float | None) -> str:
    if v is None:
        return '—'
    return f'{v:+.2f}%'


# ======================================================================
# Data freshness audit
# ======================================================================

def _last_date_in_csv(path: Path, date_col: str = 'date') -> date | None:
    """Walk a CSV, return the largest YYYY-MM-DD value in `date_col` (or
    a column whose name contains 'date'/'ts'). None if unreadable.
    """
    if not path.exists():
        return None
    try:
        with path.open() as f:
            reader = csv.reader(f)
            # Skip blank lines until we find the header row.
            header = None
            for row in reader:
                if row and any(c.strip() for c in row):
                    header = row
                    break
            if not header:
                return None
            # Pick the date column.
            if date_col in header:
                idx = header.index(date_col)
            else:
                idx = next(
                    (i for i, h in enumerate(header)
                     if 'date' in h.lower() or h.lower().startswith('ts')),
                    None,
                )
            if idx is None:
                return None
            latest: date | None = None
            for row in reader:
                if idx >= len(row):
                    continue
                cell = row[idx][:10]
                try:
                    d = date.fromisoformat(cell)
                except ValueError:
                    continue
                if latest is None or d > latest:
                    latest = d
            return latest
    except Exception:
        return None


def audit_data_freshness(config: dict, target_date: date) -> list[dict]:
    """Return one dict per critical data source with last_date / days_stale /
    impact. Caller prints a freshness banner.
    """
    # All data the briefing actually uses is now live:
    #   - calendar / FOMC / red folder → live_calendar.py (Forex Factory)
    #   - session levels (Asia/London/Overnight/PrevDay) → live_market.py
    #   - HTF FVGs → find_unfilled_fvgs on live 1m bars
    #   - VIX features + ATR_N + NR4/7 + pdr_pctile → live overrides
    # trading_days.csv is now used only for *calibration percentiles*
    # (overnight_range p20/p80, vixy p25/p50). Those are stable across
    # months — staleness is harmless. Skip the audit entirely.
    return []


def print_freshness_banner(audit: list[dict]) -> None:
    stale = [a for a in audit if a['is_stale']]
    if not stale:
        return
    print('⚠ DATA FRESHNESS WARNING')
    for a in stale:
        last = a['last_date'].isoformat() if a['last_date'] else 'unreadable'
        days = f'{a["days_stale"]}d back' if a['days_stale'] is not None else '?'
        print(f'    {a["label"]:22s}  last={last:12s}  ({days}) — {a["impact"]}')
    print('    → Pre-open factors may use stale ATR/NR4-7/VIX; calendar is live.')
    print('    → Re-run studies/or_width_predictor/run.py to refresh slow features.')
    print()


# ======================================================================
# OR-width forecast (studies/or_width_predictor)
# ======================================================================

def fetch_daily_features_live(target_date: date) -> dict | None:
    """Compute live atr_5d/10d/20d, atr_ratio_5_20, nr4/nr7_flag,
    pdr_pctile_20d from RTH daily ranges fetched off Yahoo.

    These mirror the formulas in studies/or_width_predictor/features.py
    (add_rolling_atr + add_compression_flags) but operate on the most
    recent N RTH days *before* target_date — exactly what the cold-start
    forecast at 9:29 ET sees.

    Returns None on any failure — caller falls back to features.csv.
    """
    try:
        from live_market import fetch_rth_daily_ranges
    except ImportError:
        return None
    try:
        days = fetch_rth_daily_ranges(symbol='NQ=F', range_='60d', interval='5m')
    except Exception:
        return None
    # Use only days strictly before target_date.
    prior = [d for d in days if d['date'] < target_date]
    if len(prior) < 20:
        return None

    # prior_day_range series: today's "prior_day_range" feature value is
    # yesterday's RTH range. So the feature value FOR target_date equals
    # prior[-1]['range']. ATR_N at target_date = mean of last N pdr values
    # (i.e., the last N daily ranges ending yesterday).
    ranges = [d['range'] for d in prior]
    today_pdr = ranges[-1]

    def mean(xs): return sum(xs) / len(xs)

    atr_5 = mean(ranges[-5:])
    atr_10 = mean(ranges[-10:])
    atr_20 = mean(ranges[-20:])
    atr_ratio = atr_5 / atr_20 if atr_20 > 0 else 1.0

    last4 = ranges[-4:]
    last7 = ranges[-7:]
    last20 = ranges[-20:]
    nr4 = 1.0 if today_pdr == min(last4) else 0.0
    nr7 = 1.0 if today_pdr == min(last7) else 0.0
    # pct rank (pandas-style) within last 20
    sorted_20 = sorted(last20)
    rank = sum(1 for v in sorted_20 if v <= today_pdr)
    pdr_pctile_20d = rank / len(sorted_20)

    return {
        'atr_5d': atr_5,
        'atr_10d': atr_10,
        'atr_20d': atr_20,
        'atr_ratio_5_20': atr_ratio,
        'nr4_flag': nr4,
        'nr7_flag': nr7,
        'pdr_pctile_20d': pdr_pctile_20d,
    }


def fetch_vix_features_live() -> dict | None:
    """Fetch VIXY daily closes from Yahoo and compute the 4 VIX features
    used by the cold-start OR model. Returns None on any failure — caller
    should fall back to features.csv.

    trading_days.csv has been gappy on VIXY since Dec 2025; this lets the
    pre-bell forecast still resolve.
    """
    try:
        from live_market import fetch_yahoo_1m
    except ImportError:
        return None
    try:
        # 3 months daily covers the 20d z-score lookback comfortably.
        bars = fetch_yahoo_1m(symbol='VIXY', range_='3mo', interval='1d')
    except Exception:
        return None
    closes = [b['close'] for b in bars if b.get('close') is not None]
    if len(closes) < 21:
        return None
    import statistics
    prior_close = closes[-1]
    chg_1d = closes[-1] - closes[-2]
    chg_5d = closes[-1] - closes[-6] if len(closes) >= 6 else None
    window = closes[-21:-1]  # 20d, excluding current
    mu = statistics.fmean(window)
    sigma = statistics.pstdev(window) or 1.0
    z = (closes[-1] - mu) / sigma
    return {
        'vixy_prior_close': prior_close,
        'vix_1d_chg': chg_1d,
        'vix_5d_chg': chg_5d,
        'vix_zscore_20d': z,
    }


def load_or_forecast(target_date: date, ctx=None) -> dict | None:
    """Load the cold-start OR-width forecast for target_date.

    Reads model_cold_start.json + features.csv. Live-backfills VIX
    features (vixy_prior_close, vix_1d_chg, vix_5d_chg, vix_zscore_20d)
    from Yahoo when the most recent features.csv row is missing them —
    trading_days.csv has had VIXY gaps since late 2025.

    If `ctx` is supplied with live observables, overrides the ctx-derivable
    features (overnight_range, gap_abs, gap_atr_ratio, prior_day_range,
    prior_day_close_position) so today's forecast reflects today's
    overnight session, not the most recent stale row.

    Returns dict with point / lo80 / hi80 / quintile / drivers /
    feature_date / overrides (list of feature names that were
    live-backfilled). None if model files are missing.
    """
    pred_dir = REPO / 'studies' / 'or_width_predictor' / 'results'
    model_path = pred_dir / 'model_cold_start.json'
    feat_path = pred_dir / 'features.csv'
    if not model_path.exists() or not feat_path.exists():
        return None

    import math
    model = json.loads(model_path.read_text())
    feats = model['feature_names']
    coef = model['coef']
    mu = model['feat_mean']
    sd = model['feat_std']
    intercept = model['intercept']
    train_resid = sorted(model['train_residuals'])

    # Pull row for target_date or most recent prior row.
    rows = []
    with feat_path.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            d = r.get('date', '')
            try:
                rd = date.fromisoformat(d[:10])
            except ValueError:
                continue
            if rd <= target_date:
                rows.append((rd, r))
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    feat_date, row = rows[-1]

    # Build live-override map. Anything in here wins over features.csv.
    overrides: dict[str, float] = {}

    # Live VIX backfill if any VIX feature is missing on the chosen row.
    vix_keys = ('vixy_prior_close', 'vix_1d_chg', 'vix_5d_chg', 'vix_zscore_20d')
    if any(row.get(k, '') in ('', None) for k in vix_keys):
        vix_live = fetch_vix_features_live()
        if vix_live:
            for k, v in vix_live.items():
                if v is not None:
                    overrides[k] = float(v)


    # Today's pre-open observables from ctx — these are more accurate than
    # whatever features.csv has stamped on the stale row.
    if ctx is not None:
        on_range = getattr(ctx, 'overnight_range', None)
        if on_range is not None:
            overrides['overnight_range'] = float(on_range)
        gap = getattr(ctx, 'gap_pts', None)
        if gap is not None:
            gap_abs_live = abs(float(gap))
            overrides['gap_abs'] = gap_abs_live
            # gap_atr_ratio = gap_abs / atr_20d — recompute with live gap
            atr_20d_csv = row.get('atr_20d', '')
            try:
                atr20 = float(atr_20d_csv)
                if atr20 > 0:
                    overrides['gap_atr_ratio'] = gap_abs_live / atr20
            except (ValueError, TypeError):
                pass
        # prior_day_close_position (0–1): rank of close inside prior RTH range
        pdcp = getattr(ctx, 'prior_day_close_position', None)
        if pdcp is not None:
            overrides['prior_day_close_position'] = float(pdcp)
        # prior_day_range from ctx prior RTH H/L if available
        pr_h = getattr(ctx, 'prior_rth_high', None)
        pr_l = getattr(ctx, 'prior_rth_low', None)
        if pr_h is not None and pr_l is not None:
            overrides['prior_day_range'] = float(pr_h) - float(pr_l)

    # Live daily-feature backfill if features.csv is stale — atr_Nd /
    # atr_ratio / nr4-7 / pdr_pctile_20d. Runs *after* ctx so we can
    # recompute gap_atr_ratio with the live atr_20d.
    if feat_date < target_date:
        daily_live = fetch_daily_features_live(target_date)
        if daily_live:
            for k, v in daily_live.items():
                if v is not None:
                    overrides[k] = float(v)
            if 'atr_20d' in overrides and 'gap_abs' in overrides and overrides['atr_20d'] > 0:
                overrides['gap_atr_ratio'] = overrides['gap_abs'] / overrides['atr_20d']

    # Build feature vector. If any required feature is missing/NaN, bail.
    x = []
    used_overrides = []
    for f in feats:
        if f in overrides:
            x.append(overrides[f])
            used_overrides.append(f)
            continue
        v = row.get(f, '')
        if v == '' or v is None:
            return {'error': f'missing feature: {f}', 'feature_date': feat_date,
                    'overrides': used_overrides}
        # Coerce booleans (NR4/NR7/FOMC/OPEX flags arrive as 'True'/'False').
        if isinstance(v, str) and v.strip().lower() in ('true', 'false'):
            v = 1.0 if v.strip().lower() == 'true' else 0.0
        try:
            v = float(v)
        except ValueError:
            return {'error': f'non-numeric feature: {f}', 'feature_date': feat_date,
                    'overrides': used_overrides}
        if math.isnan(v):
            return {'error': f'NaN feature: {f}', 'feature_date': feat_date,
                    'overrides': used_overrides}
        x.append(v)

    # Standardize, predict log, exponentiate.
    z = []
    log_contrib = []
    for xi, mui, sdi, ci in zip(x, mu, sd, coef):
        sd_safe = sdi if sdi != 0 else 1.0
        zi = (xi - mui) / sd_safe
        z.append(zi)
        log_contrib.append(zi * ci)
    log_pred = intercept + sum(log_contrib)
    point = math.exp(log_pred)

    # 80% interval from training residual quantiles.
    n = len(train_resid)
    q10 = train_resid[max(0, int(0.10 * n) - 1)]
    q90 = train_resid[min(n - 1, int(0.90 * n))]
    lo80 = math.exp(log_pred + q10)
    hi80 = math.exp(log_pred + q90)

    # Quintile vs last 60 trading days of actuals.
    actuals = []
    with feat_path.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            v = r.get('or_45min_range', '')
            if v not in ('', None):
                try:
                    actuals.append(float(v))
                except ValueError:
                    pass
    recent = actuals[-60:] if len(actuals) >= 10 else actuals
    if recent:
        pct = sum(1 for a in recent if a < point) / len(recent) * 100
        if pct < 20:    q_label = f'Q1 TIGHT ({pct:.0f}th pct)'
        elif pct < 40:  q_label = f'Q2 ({pct:.0f}th pct)'
        elif pct < 60:  q_label = f'Q3 typical ({pct:.0f}th pct)'
        elif pct < 80:  q_label = f'Q4 ({pct:.0f}th pct)'
        else:           q_label = f'Q5 WIDE ({pct:.0f}th pct)'
    else:
        q_label = 'n/a'

    # Top drivers in pts.
    baseline = math.exp(intercept)
    drivers = []
    for f, val, zi, lc in zip(feats, x, z, log_contrib):
        delta = math.exp(intercept + lc) - baseline
        drivers.append((f, val, zi, delta))
    drivers.sort(key=lambda d: abs(d[3]), reverse=True)

    # Sizing tier — translate quintile to action.
    q_letter = q_label.split(' ', 1)[0] if q_label != 'n/a' else 'Q?'
    if q_letter == 'Q1':
        tier = 'STAND DOWN / minimum size — tight OR kills FVGC WR'
    elif q_letter == 'Q2':
        tier = 'Below-normal — tighten filters, smaller size'
    elif q_letter == 'Q3':
        tier = 'Normal day — trade per playbook'
    elif q_letter == 'Q4':
        tier = 'Wide — favor full size on confluence setups'
    elif q_letter == 'Q5':
        tier = 'Q5 wide — best size-up regime, target multi-R runners'
    else:
        tier = '—'

    # Read walk-forward perf for confidence labelling.
    perf_path = pred_dir / 'walkforward_performance.csv'
    perf = {}
    if perf_path.exists():
        with perf_path.open() as f:
            for r in csv.DictReader(f):
                perf[r['model']] = r

    return {
        'feature_date': feat_date,
        'is_stale': feat_date < target_date,
        'point': point,
        'lo80': lo80,
        'hi80': hi80,
        'baseline': baseline,
        'quintile': q_label,
        'tier': tier,
        'drivers': drivers,
        'perf': perf.get('cold_start', {}),
        'overrides': used_overrides,
    }


def print_or_forecast(forecast: dict | None, target_date: date) -> None:
    """Print the OR-width forecast section. Top of briefing — sets sizing
    context for everything below. Silently skipped if model not available.
    """
    if forecast is None:
        return
    print(f'[0] OR-WIDTH FORECAST (cold-start, 9:29 ET)')
    if 'error' in forecast:
        print(f'    Forecast unavailable: {forecast["error"]}')
        print(f'    Re-run: python studies/or_width_predictor/run.py')
        print()
        return

    if forecast.get('overrides'):
        print(f'    Live overrides: {", ".join(forecast["overrides"])}')
    if forecast['is_stale']:
        days_back = (target_date - forecast['feature_date']).days
        print(f'    (model trained on data through {forecast["feature_date"]}, '
              f'{days_back}d back — coefficients fixed; run.py to retrain)')

    pt, lo, hi = forecast['point'], forecast['lo80'], forecast['hi80']
    print(f'    Predicted 45-min OR:  {pt:.0f} pts  '
          f'(80% range: {lo:.0f}–{hi:.0f} pts)')
    print(f'    Quintile vs last 60d: {forecast["quintile"]}')
    print(f'    → SIZING TIER: {forecast["tier"]}')

    perf = forecast['perf']
    if perf:
        try:
            mae = float(perf.get('mae_pts', 0))
            rho = float(perf.get('spearman_rho', 0))
            r2 = float(perf.get('r2', 0))
            print(f'    Model: cold_start  MAE {mae:.0f} pts  '
                  f'rho {rho:.2f}  R² {r2:.2f}  '
                  f'(updates at 9:35 / 9:45 — see predict_today.py)')
        except (ValueError, TypeError):
            pass

    print(f'    Top drivers vs baseline ({forecast["baseline"]:.0f} pts):')
    for f, val, zi, delta in forecast['drivers'][:5]:
        sign = '+' if delta >= 0 else '-'
        print(f'      {sign} {f:24s}  value={val:>8.2f}  z={zi:+.2f}  '
              f'→ {delta:+6.1f} pts')
    print()


def print_briefing(
    target_date: date,
    now_et: datetime | None,
    ctx,
    today_factors: dict[str, bool],
    config: dict,
    combo_sections: dict[str, list[ComboEdge]],
    factor_data: dict[str, list[FactorEdge]],
    plays: list[dict],
    levels: list[LiquidityLevel],
    gap_pts: float | None,
    events: list[dict],
    cal_unknown: bool = False,
):
    W = 70
    dow = target_date.strftime('%A')
    date_str = target_date.strftime('%A %Y-%m-%d')

    if now_et:
        et_str = now_et.strftime('%H:%M ET')
        pt_str = now_et.astimezone(PT_TZ).strftime('%H:%M PT')
        time_str = f'{et_str} / {pt_str}'
    else:
        time_str = 'offline'

    print('=' * W)
    print(f'NQ MORNING BRIEFING — {date_str} ({time_str})')
    print('=' * W)
    print()

    # Freshness audit — print at the top so the trader knows which sections
    # are reading from stale CSVs.
    audit = audit_data_freshness(config, target_date)
    print_freshness_banner(audit)
    audit_by_label = {a['label']: a for a in audit}

    # [0] OR-WIDTH FORECAST — sizing tier (drives every other read below)
    forecast = load_or_forecast(target_date, ctx=ctx)
    print_or_forecast(forecast, target_date)

    # [1] CALENDAR
    print(f'[1] CALENDAR')
    dow_notes = config.get('day_of_week_notes', {})
    dow_note = dow_notes.get(dow, '')
    print(f'    Day of week: {dow} — "{dow_note}"')

    if cal_unknown:
        print(f'    ⚠ Live calendar fetch failed and CSV is stale — '
              f'red folder / FOMC flags below are UNKNOWN, not confirmed False.')
        print(f'    Red folder events: UNKNOWN (no calendar data)')
        print(f'    FOMC week: UNKNOWN (no calendar data)')
    else:
        if events:
            event_names = [e.get('event', e.get('event_type', '?')) for e in events]
            print(f'    Red folder events: {", ".join(event_names)}')
        else:
            print(f'    Red folder events: None')
        print(f'    FOMC week: {"Yes" if today_factors.get("is_fomc_week") else "No"}')
    print()

    # [2] PRE-OPEN STATE
    print(f'[2] PRE-OPEN STATE')
    if ctx.prior_rth_close is not None:
        pcp = ctx.prior_day_close_position
        pcp_str = f'{pcp*100:.0f}%' if pcp is not None else '?'
        pcp_label = ''
        if pcp is not None:
            if pcp < 0.25:
                pcp_label = ' → prior_day_down'
            elif pcp > 0.75:
                pcp_label = ' → prior_day_up'
        print(f'    Prior RTH close: {fmt_price(ctx.prior_rth_close)} '
              f'(closed in {pcp_str} of range{pcp_label})')
    if ctx.overnight_high is not None:
        print(f'    Overnight: H {fmt_price(ctx.overnight_high)} / '
              f'L {fmt_price(ctx.overnight_low)} — '
              f'range {fmt_price(ctx.overnight_range)} pts — '
              f'direction: {ctx.overnight_direction or "?"}')
        if today_factors.get('tight_overnight'):
            print(f'               ↳ TIGHT overnight (bottom 20%)')
        if today_factors.get('wide_overnight'):
            print(f'               ↳ WIDE overnight (top 20%)')
    if ctx.asia_high is not None:
        print(f'    Asia: H {fmt_price(ctx.asia_high)} / L {fmt_price(ctx.asia_low)}')
    if ctx.london_high is not None:
        print(f'    London: H {fmt_price(ctx.london_high)} / L {fmt_price(ctx.london_low)}')
    if ctx.gap_pts is not None:
        gap_dir = 'gap_down' if ctx.gap_pts < 0 else 'gap_up'
        print(f'    Gap vs close: {ctx.gap_pts:+.2f} pts ({ctx.gap_pct:+.2f}%) → {gap_dir}')
    if ctx.current_price is not None:
        ts_str = ctx.current_ts.strftime('%H:%M ET') if ctx.current_ts else ''
        print(f'    Current price: {fmt_price(ctx.current_price)} (as of {ts_str})')
    print()

    # [3] LIQUIDITY LEVELS
    print(f'[3] LIQUIDITY LEVELS (within {config.get("tuning", {}).get("level_scope_pts", 100)} pts of current price)')
    if not levels:
        print('    No levels available (no live data)')
    else:
        below = [l for l in levels if l.direction == 'below']
        above = [l for l in levels if l.direction == 'above']

        if below:
            print(f'    Draw levels in SHORT direction (below):')
            for l in below:
                dist_hr = distance_bucket_hit_rate(l.distance_pts, config)
                wr_note = ''
                if l.wr_as_magnet < 51.5:
                    wr_note = ' (below baseline — caution)'
                print(f'      {l.label} {fmt_price(l.price)} '
                      f'({l.distance_pts:+.1f} pts) '
                      f'hit rate: ~{dist_hr:.0f}% at this distance | '
                      f'WR as magnet: {l.wr_as_magnet:.0f}%{wr_note}')

        if above:
            print(f'    Draw levels in LONG direction (above):')
            for l in above:
                dist_hr = distance_bucket_hit_rate(l.distance_pts, config)
                wr_note = ''
                if l.wr_as_magnet < 51.5:
                    wr_note = ' (below baseline — caution)'
                print(f'      {l.label} {fmt_price(l.price)} '
                      f'({l.distance_pts:+.1f} pts) '
                      f'hit rate: ~{dist_hr:.0f}% at this distance | '
                      f'WR as magnet: {l.wr_as_magnet:.0f}%{wr_note}')

        print()
        print(f'    Level guidance:')
        print(f'    - 1-2 available levels in your trade direction = sweet spot (55% WR, PF 1.30)')
        print(f'    - 1 obstruction between entry and target = positive signal (58.5% WR)')
        print(f'    - 3+ levels stacked = contested zone, reduce size')
    print()

    # [4] FACTOR SNAPSHOT
    print(f'[4] FACTOR SNAPSHOT')
    # When the events file is stale, suppress the calendar-derived "absent"
    # factors so we don't emit false negatives (no_red_folder, no_pre_rth_news,
    # not_fomc_week) that propagate into [5] ARMED EDGES.
    cal_unknown_factors = set()
    if cal_unknown:
        cal_unknown_factors = {
            'no_red_folder', 'has_red_folder',
            'no_pre_rth_news', 'has_pre_rth_news',
            'not_fomc_week', 'is_fomc_week',
        }
    visible_factors = {f: v for f, v in today_factors.items()
                       if f not in cal_unknown_factors}
    active_f = sorted([f for f, v in visible_factors.items() if v])
    inactive_f = sorted([f for f, v in visible_factors.items() if not v])
    print(f'    Active today: {", ".join(active_f) if active_f else "none"}')
    print(f'    Not active: {", ".join(inactive_f) if inactive_f else "none"}')
    if cal_unknown_factors:
        print(f'    UNKNOWN (stale calendar): {", ".join(sorted(cal_unknown_factors))}')
    print()

    # [5] ARMED EDGES
    factor_config = config.get('factors', {})

    # If the calendar is stale, strip the calendar-derived factors from the
    # match input so we don't falsely arm setups that require no_red_folder
    # / no_pre_rth_news / not_fomc_week. Those combos will appear in WATCH
    # (still need confirmation) rather than ARMED.
    if cal_unknown_factors:
        match_factors = {f: v for f, v in today_factors.items()
                         if f not in cal_unknown_factors}
    else:
        match_factors = today_factors

    # Use the robust sample (n>=50) for armed/watch
    top_combos = combo_sections.get('top_wr_robust', [])
    avoid_combos = combo_sections.get('avoid', [])

    matched_top = match_combos(top_combos, match_factors, factor_config)
    matched_avoid = match_combos(avoid_combos, match_factors, factor_config)

    armed = [m for m in matched_top if m.status == 'armed']
    watch = [m for m in matched_top if m.status == 'watch']

    max_show = config.get('tuning', {}).get('top_watches_to_show', 8)

    print(f'[5] ARMED EDGES (all pre-open factors confirmed now)')
    if armed:
        for m in armed:
            stars = '★★★' if m.combo.wr >= 75 else '★★' if m.combo.wr >= 65 else '★'
            factors_str = ' + '.join(m.combo.factors)
            print(f'    {stars} {factors_str}')
            print(f'        n={m.combo.n}, WR {m.combo.wr:.1f}%, PF {m.combo.pf:.2f}')
    else:
        print(f'    No combos fully armed from study outputs.')
    print()

    # [5b] W1 CONFLUENCE CHECK
    w1_count, w1_active = count_w1_confluences(today_factors, gap_pts)
    w1_play = next((p for p in plays if 'W1 Short' in p.get('name', '')), None)
    if w1_play and w1_count > 0:
        cm = w1_play.get('confluence_model', {})
        tiers = cm.get('tiers', []) if cm else []
        tier = next((t for t in tiers if t['min'] <= w1_count <= t['max']), None)
        print(f'    W1 SHORT CONFLUENCE: {w1_count} pre-market ({", ".join(w1_active)})')
        if tier:
            print(f'        Tier: {tier["action"]} — WR {tier["wr"]}, '
                  f'PF {tier.get("pf_1r", "?")}, target {tier.get("target", "?")}')
        print(f'        → At 9:30:30: if bearish candle, add +1 → final tier')
        print()

    # [6] WATCH LIST
    print(f'[6] WATCH LIST (need 9:30 confirmation)')
    if watch:
        for m in watch[:max_show]:
            stars = '★★★' if m.combo.wr >= 75 else '★★' if m.combo.wr >= 65 else '★'
            factors_str = ' + '.join(m.combo.factors)
            print(f'    {stars} {factors_str} → n={m.combo.n}, '
                  f'WR {m.combo.wr:.1f}%, PF {m.combo.pf:.2f}')
            matched_str = ', '.join(f'{f} ✓' for f in m.pre_matched)
            needed_str = ', '.join(m.post_needed)
            print(f'        armed: {matched_str} | confirm: {needed_str}')
            # Generate action hint for key post-open factors
            for pf in m.post_needed:
                desc = factor_config.get(pf, {}).get('desc', '')
                if desc:
                    print(f'        → {pf}: {desc}')
    else:
        print(f'    No watch combos today.')
    print()

    # [7] AVOID / STAND-DOWN
    print(f'[7] AVOID / STAND-DOWN SIGNALS')
    avoid_matched = [m for m in matched_avoid if m.status in ('armed', 'watch')]
    avoid_max = config.get('tuning', {}).get('avoid_to_show', 6)

    # Factor-level avoid signals
    factor_avoid = factor_data.get('avoid', [])
    for fa in factor_avoid:
        if today_factors.get(fa.factor, False):
            print(f'    ⚠ {fa.factor} is ACTIVE: WR {fa.wr:.1f}%, '
                  f'lift {fa.lift:+.1f}%, PF {fa.pf:.2f} (p={fa.p_wr:.4f})')

    # Combo-level avoid signals
    for m in avoid_matched[:avoid_max]:
        factors_str = ' + '.join(m.combo.factors)
        if m.status == 'armed':
            print(f'    ⚠ AVOID: {factors_str} — n={m.combo.n}, '
                  f'WR {m.combo.wr:.1f}%, PF {m.combo.pf:.2f} (factors all match!)')
        else:
            needed = ', '.join(m.post_needed)
            print(f'    ⚠ WATCH-AVOID: {factors_str} — WR {m.combo.wr:.1f}% '
                  f'if confirmed ({needed})')

    if not avoid_matched and not any(today_factors.get(fa.factor, False) for fa in factor_avoid):
        print(f'    No major avoid signals today.')
    print()

    # [8] PLAYBOOK PLAYS
    matched_plays = match_plays(plays, today_factors)
    active_plays = [mp for mp in matched_plays if mp.status in ('active', 'always')]
    partial_plays = [mp for mp in matched_plays if mp.status == 'partial']
    if active_plays:
        print(f'[8] ACTIVE PLAYS FROM PLAYBOOK')
        for mp in active_plays:
            p = mp.play
            status_icon = '🟢' if p.get('status') == 'verified' else '🟡'
            print(f'    {status_icon} {p["name"]} [{p.get("direction", "?")}] '
                  f'— WR {p.get("wr_base", "?")} (n={p.get("sample_size", "?")})')
            if p.get('action_plan'):
                # Wrap action plan text
                plan = p['action_plan']
                print(f'        {plan}')
        print()
    if partial_plays:
        print(f'    --- VERIFY BEFORE USING ---')
        for mp in partial_plays:
            p = mp.play
            missing = ', '.join(mp.pre_missing)
            print(f'    🔍 {p["name"]} [{p.get("direction", "?")}] '
                  f'— WR {p.get("wr_base", "?")} (n={p.get("sample_size", "?")}) '
                  f'| needs manual check: {missing}')
        print()

    # [9] TODAY'S GAME PLAN
    print(f'[{"9" if active_plays else "8"}] TODAY\'S GAME PLAN')

    # Print matching manual one-liners
    one_liners = config.get('manual_one_liners', [])
    printed_plan = False
    for ol in one_liners:
        when_all = ol.get('when_all', [])
        if when_all and all(today_factors.get(f, False) for f in when_all):
            print(f'    "{ol["say"]}"')
            printed_plan = True

    if not printed_plan:
        if armed or watch:
            print(f'    Review the armed edges and watch list above.')
            print(f'    Key confirmations to watch at 9:30:')
        else:
            print(f'    No strong pre-open edges today. Stay selective.')

    # 9:30 checklist
    print()
    print(f'    Key 9:30 checklist:')
    print(f'    [ ] 9:30 candle direction — bearish confirms most high-edge combos')
    print(f'    [ ] Watch 45-min OR width by 10:15 — WIDE = green light, TIGHT = stand down')

    # Best draw targets
    if levels:
        below_levels = [l for l in levels if l.direction == 'below'][:2]
        above_levels = [l for l in levels if l.direction == 'above'][:2]
        targets = []
        for l in below_levels:
            targets.append(f'{l.label} at {fmt_price(l.price)} ({l.distance_pts:+.1f} pts)')
        for l in above_levels:
            targets.append(f'{l.label} at {fmt_price(l.price)} ({l.distance_pts:+.1f} pts)')
        if targets:
            print(f'    [ ] Best draw targets: {"; ".join(targets)}')

    print()
    print('=' * W)


# ======================================================================
# Main
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description='NQ Morning Briefing — pre-market report for FVGC model trading')
    parser.add_argument('--offline', action='store_true',
                        help='Skip Yahoo fetch, use only CSV data')
    parser.add_argument('--date', type=str, default=None,
                        help='Run for a historical date (YYYY-MM-DD)')
    parser.add_argument('--json', action='store_true',
                        help='Output raw factor data as JSON (for debugging)')
    args = parser.parse_args()

    # Determine target date
    now_ny = datetime.now(tz=NY_TZ)
    if args.date:
        target_date = date.fromisoformat(args.date)
        asof_ny = datetime.combine(target_date, dtime(9, 15), tzinfo=NY_TZ)
        is_historical = True
    else:
        target_date = now_ny.date()
        asof_ny = now_ny
        is_historical = False

    # Load config
    config = load_config(PLAYBOOK / 'briefing_config.json')
    plays = load_plays(PLAYBOOK / 'plays.json')

    # Paths
    csv_path = REPO / config['sources']['trading_days_csv']
    events_path = REPO / config['sources']['events_csv']
    combo_path = REPO / config['sources']['combo_results']
    factor_path = REPO / config['sources']['factor_importance']

    # Parse study outputs
    combo_sections = parse_combo_results(combo_path)
    factor_data = parse_factor_importance(factor_path)

    # Fetch live data or use CSV
    ctx = None
    fvgs = []
    gap_pts = None

    if not args.offline and not is_historical:
        try:
            from live_market import (
                fetch_yahoo_1m, derive_session_context,
                find_unfilled_fvgs, LiveDataError
            )
            live_cfg = config.get('live_data', {})
            bars = fetch_yahoo_1m(
                symbol=live_cfg.get('symbol', 'NQ=F'),
                range_=live_cfg.get('range', '2d'),
                interval=live_cfg.get('interval', '1m'),
            )
            ctx = derive_session_context(bars, asof_ny)
            fvgs_15m = find_unfilled_fvgs(bars, 15, current_price=ctx.current_price)
            fvgs_1h = find_unfilled_fvgs(bars, 60, current_price=ctx.current_price)
            fvgs = fvgs_15m + fvgs_1h
            gap_pts = ctx.gap_pts
            print(f'[live] Fetched {len(bars)} bars from Yahoo Finance')
            if ctx.notes:
                for n in ctx.notes:
                    print(f'[live] note: {n}')
        except Exception as e:
            print(f'[live] Yahoo fetch failed: {e}')
            print(f'[live] Falling back to CSV data...')
            ctx = None

    # Build a minimal context from CSV if no live data
    if ctx is None:
        from types import SimpleNamespace
        row = load_trading_day_row(csv_path, target_date)
        prior_row = load_prior_trading_day_row(csv_path, target_date)
        ctx = SimpleNamespace(
            asof=asof_ny,
            prior_rth_date=None,
            prior_rth_open=None,
            prior_rth_high=None,
            prior_rth_low=None,
            prior_rth_close=None,
            prior_day_close_position=None,
            overnight_high=None, overnight_low=None,
            overnight_range=None, overnight_direction=None,
            asia_high=None, asia_low=None,
            london_high=None, london_low=None,
            sixam_high=None, sixam_low=None,
            current_price=None, current_ts=None,
            gap_pts=None, gap_pct=None,
            notes=[],
        )
        if row:
            ctx.prior_rth_close = _float_or_none(row.get('rth_close'))
            ctx.prior_rth_high = _float_or_none(row.get('rth_high'))
            ctx.prior_rth_low = _float_or_none(row.get('rth_low'))
            ctx.prior_rth_open = _float_or_none(row.get('rth_open'))
            ctx.prior_day_close_position = _float_or_none(row.get('prior_day_close_position'))
            ctx.overnight_high = _float_or_none(row.get('overnight_high'))
            ctx.overnight_low = _float_or_none(row.get('overnight_low'))
            on_range = _float_or_none(row.get('overnight_range'))
            ctx.overnight_range = on_range
            ctx.overnight_direction = row.get('overnight_direction', '')
            ctx.gap_pts = _float_or_none(row.get('gap_from_prior_close'))
            gap_pct = _float_or_none(row.get('gap_from_prior_close_pct'))
            if gap_pct:
                ctx.gap_pct = gap_pct
            ctx.current_price = ctx.prior_rth_open  # best proxy in offline mode
            gap_pts = ctx.gap_pts
        elif prior_row:
            ctx.prior_rth_close = _float_or_none(prior_row.get('rth_close'))
            ctx.prior_rth_high = _float_or_none(prior_row.get('rth_high'))
            ctx.prior_rth_low = _float_or_none(prior_row.get('rth_low'))
            ctx.prior_rth_open = _float_or_none(prior_row.get('rth_open'))
            ctx.prior_day_close_position = _float_or_none(prior_row.get('prior_day_close_position'))
            ctx.notes.append('using prior day as proxy — no row for target date')
        else:
            ctx.notes.append('no CSV data available for this date')

    # Live calendar (Forex Factory) — replaces the static events CSV.
    live_events = None
    cal_unknown = False
    if not args.offline:
        try:
            from live_calendar import fetch_for_target, CalendarError
            live_events = fetch_for_target(target_date)
            print(f'[live] Calendar: {len(live_events)} events from Forex Factory')
        except Exception as e:
            print(f'[live] Calendar fetch failed: {e}')
            print(f'[live] Falling back to events CSV (may be stale)')
            live_events = None
    if live_events is None:
        # CSV fallback — flag UNKNOWN when CSV is itself stale.
        last = _last_date_in_csv(events_path)
        if last is None or (target_date - last).days > 1:
            cal_unknown = True

    # Determine today's factors
    if not args.offline and not is_historical and hasattr(ctx, 'symbol'):
        today_factors = determine_factors_from_context(
            ctx, config, csv_path, events_path, target_date,
            live_events=live_events)
    else:
        csv_factors = determine_factors_from_csv(
            csv_path, events_path, target_date, live_events=live_events)
        if csv_factors:
            today_factors = csv_factors
        else:
            today_factors = determine_factors_from_context(
                ctx, config, csv_path, events_path, target_date,
                live_events=live_events)

    if gap_pts is None:
        gap_pts = ctx.gap_pts

    # JSON debug output
    if args.json:
        import json as _json
        print(_json.dumps({
            'date': target_date.isoformat(),
            'factors': today_factors,
            'gap_pts': gap_pts,
        }, indent=2, default=str))
        return

    # Events for display — prefer live calendar.
    if live_events is not None:
        from live_calendar import filter_us_high
        # Show all USD high-impact + Medium events for context
        events = [e.to_briefing_row() for e in live_events
                  if e.date == target_date and e.country == 'USD'
                  and e.impact in ('High', 'Medium')]
    else:
        events = load_events_for_date(events_path, target_date)

    # Build levels
    levels = build_levels(ctx, config, fvgs)

    # Print the briefing
    now_et = asof_ny if not is_historical else None
    print_briefing(
        target_date=target_date,
        now_et=now_et if not is_historical else None,
        ctx=ctx,
        today_factors=today_factors,
        config=config,
        combo_sections=combo_sections,
        factor_data=factor_data,
        plays=plays,
        levels=levels,
        gap_pts=gap_pts,
        events=events,
        cal_unknown=cal_unknown,
    )


if __name__ == '__main__':
    main()
