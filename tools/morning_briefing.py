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


def load_events_for_date(events_path: Path, target_date: date) -> list[dict]:
    """Load red-folder events for a specific date."""
    if not events_path.exists():
        return []
    ds = target_date.isoformat()
    events = []
    with open(events_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('date', '').strip() == ds:
                events.append(row)
    return events


def is_fomc_week(events_path: Path, target_date: date) -> bool:
    """Check if target_date falls in the same ISO week as any FOMC Statement."""
    if not events_path.exists():
        return False
    target_year, target_week, _ = target_date.isocalendar()
    with open(events_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if 'FOMC' in row.get('event_type', ''):
                try:
                    d = date.fromisoformat(row['date'].strip())
                    y, w, _ = d.isocalendar()
                    if y == target_year and w == target_week:
                        return True
                except ValueError:
                    pass
    return False


def determine_factors_from_context(ctx, config: dict, csv_path: Path,
                                   events_path: Path, target_date: date) -> dict[str, bool]:
    """Determine which factors are TRUE today from a SessionContext."""
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

    # Calendar / news
    events = load_events_for_date(events_path, target_date)
    factors['has_red_folder'] = len(events) > 0
    factors['no_red_folder'] = len(events) == 0
    pre_rth = [e for e in events if e.get('event_type', '') in ('NFP', 'CPI', 'PPI', 'Retail Sales')]
    factors['has_pre_rth_news'] = len(pre_rth) > 0
    factors['no_pre_rth_news'] = len(pre_rth) == 0

    fomc = is_fomc_week(events_path, target_date)
    factors['is_fomc_week'] = fomc
    factors['not_fomc_week'] = not fomc

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
                               target_date: date) -> dict[str, bool] | None:
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

    # News / calendar from CSV columns
    factors['has_red_folder'] = row.get('has_red_folder_news', '').lower() == 'true'
    factors['no_red_folder'] = not factors['has_red_folder']
    factors['has_pre_rth_news'] = row.get('has_pre_rth_news', '').lower() == 'true'
    factors['no_pre_rth_news'] = not factors['has_pre_rth_news']
    factors['is_fomc_week'] = row.get('is_fomc_week', '').lower() == 'true'
    factors['not_fomc_week'] = not factors['is_fomc_week']

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

    # [1] CALENDAR
    print(f'[1] CALENDAR')
    dow_notes = config.get('day_of_week_notes', {})
    dow_note = dow_notes.get(dow, '')
    print(f'    Day of week: {dow} — "{dow_note}"')

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
    active_f = sorted([f for f, v in today_factors.items() if v])
    inactive_f = sorted([f for f, v in today_factors.items() if not v])
    print(f'    Active today: {", ".join(active_f) if active_f else "none"}')
    print(f'    Not active: {", ".join(inactive_f) if inactive_f else "none"}')
    print()

    # [5] ARMED EDGES
    factor_config = config.get('factors', {})

    # Use the robust sample (n>=50) for armed/watch
    top_combos = combo_sections.get('top_wr_robust', [])
    avoid_combos = combo_sections.get('avoid', [])

    matched_top = match_combos(top_combos, today_factors, factor_config)
    matched_avoid = match_combos(avoid_combos, today_factors, factor_config)

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

    # Determine today's factors
    if not args.offline and not is_historical and hasattr(ctx, 'symbol'):
        today_factors = determine_factors_from_context(
            ctx, config, csv_path, events_path, target_date)
    else:
        csv_factors = determine_factors_from_csv(csv_path, events_path, target_date)
        if csv_factors:
            today_factors = csv_factors
        else:
            # Derive what we can from the context
            today_factors = determine_factors_from_context(
                ctx, config, csv_path, events_path, target_date)

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

    # Events for display
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
    )


if __name__ == '__main__':
    main()
