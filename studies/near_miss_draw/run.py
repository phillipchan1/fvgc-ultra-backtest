#!/usr/bin/env python3
"""
Near-miss liquidity draw — backtest filter.

Core question: after price near-misses a named liquidity level and retraces,
do FVGC trades taken *toward* that same level outperform baseline?

Loads logs/baseline_trades.csv and joins near_miss_days.csv on trade date.
Produces five cohorts (all restricted to win/loss outcomes):

  Cohort 1 — "going back for it" (the main signal, causally clean):
    • near_miss_present = True
    • trade direction aligns with near-miss (up→long, down→short)
    • entry is AFTER near_miss_confirmed_time (no lookahead)
    • near_miss_level still above entry for longs / below entry for shorts
      (level is still a draw, not yet swept)

  Cohort 1b — "going back for it + stacked draw":
    • all of Cohort 1, PLUS
    • at least one other named liquidity level sits between entry price
      and the near-miss target (stacked magnetic draw, e.g. screenshot's
      6am High sitting between FVG entry and Asia High)

  Cohort 2 — "fade of near miss" (entry after confirm, opposite direction):
    • near_miss_present = True
    • trade direction OPPOSES near-miss direction
    • entry is AFTER near_miss_confirmed_time

  Cohort 3 — all near-miss + aligned (broad, includes before-confirm):
    • near_miss_present = True + aligned direction, no time/level filter
    • use to see total population size vs cohort 1

  Cohort 4 — control (no near miss on day):
    • near_miss_present = False

Run tagger.py first to generate results/near_miss_days.csv.

Run from repo root:
  python studies/near_miss_draw/run.py
"""

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Trades source. Defaults to the committed baseline log, but can be overridden via
# the NEAR_MISS_TRADES_CSV env var — e.g. point at logs/baseline_trades.csv.preserve
# (the full 8yr 2018→2026 baseline) when logs/baseline_trades.csv has been clobbered
# to a shorter range by another study. The 8yr file is the one the CANDIDATE result
# was validated on.
TRADES_PATH = Path(os.environ.get(
    'NEAR_MISS_TRADES_CSV', str(ROOT / 'logs' / 'baseline_trades.csv')))
LEVELS_PATH = ROOT / 'data' / 'levels' / 'session_levels.csv'
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
NEAR_MISS_CSV = RESULTS_DIR / 'near_miss_days.csv'
INSESSION_FVG_CSV = RESULTS_DIR / 'insession_fvgs.csv'

TRADEABLE_OUTCOMES = {'win', 'loss'}

# Level names considered as potential intermediate draws between entry and target.
# OR high/low stubs are excluded (not yet implemented in session_levels builder).
INTERMEDIATE_LEVEL_NAMES = frozenset({
    'asia_high', 'asia_low',
    '6am_high', '6am_low',
    'prev_day_high', 'prev_day_low',
    'london_high', 'london_low',
    'overnight_high', 'overnight_low',
    'nwog_high', 'nwog_low',
})

# "High quality" near-miss level types for the longs sub-cohort. These are the
# pre-market resistance highs + large in-session bearish 5m FVGs that carried the
# edge in the 8yr study; support levels and 15m FVGs did not work for longs.
HQ_LEVEL_NAMES = frozenset({'asia_high', '6am_high', 'insession_5m_bearish'})

# Distance cap (points) for the headline longs sub-cohort. The 10–15pt band was a
# kill zone in the 8yr study; ≤10pts is the sweet spot.
LONGS_DIST_CAP_PTS = 10.0


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def cohort_stats(df: pd.DataFrame) -> dict:
    sub = df[df['outcome'].isin(TRADEABLE_OUTCOMES)].copy()
    n = len(sub)
    if n == 0:
        return {
            'n': 0, 'wins': 0, 'losses': 0,
            'win_rate_pct': float('nan'),
            'profit_factor': float('nan'),
            'total_pnl': 0.0,
            'avg_pnl': float('nan'),
        }
    wins = int((sub['outcome'] == 'win').sum())
    losses = int((sub['outcome'] == 'loss').sum())
    pnl = pd.to_numeric(sub['pnl'], errors='coerce')
    gross_win = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()
    pf = (gross_win / gross_loss) if gross_loss > 0 else float('inf')
    return {
        'n': n,
        'wins': wins,
        'losses': losses,
        'win_rate_pct': wins / n * 100,
        'profit_factor': round(float(pf), 3),
        'total_pnl': round(float(pnl.sum()), 2),
        'avg_pnl': round(float(pnl.mean()), 2),
    }


def fmt_stats(label: str, s: dict) -> str:
    if s['n'] == 0:
        return f'  {label:56s}  n=0'
    return (
        f'  {label:56s}  n={s["n"]:5d}  '
        f'W={s["wins"]:4d} L={s["losses"]:4d}  '
        f'WR={s["win_rate_pct"]:5.1f}%  '
        f'PF={s["profit_factor"]:5.2f}  '
        f'avgPnL={s["avg_pnl"]:+7.2f}  '
        f'totPnL={s["total_pnl"]:+9.1f}'
    )


# ---------------------------------------------------------------------------
# Intermediate-level helper
# ---------------------------------------------------------------------------

def build_intermediate_flag(
    merged: pd.DataFrame,
    levels_df: pd.DataFrame,
    insession_fvgs_df: pd.DataFrame,
) -> pd.Series:
    """
    For each row, return True if there is at least one named liquidity level
    (pre-market OR large in-session FVG) that sits BETWEEN the trade entry price
    and the near-miss target price — a stacked draw between entry and the missed level.

    Only meaningful for rows already in Cohort 1.
    """
    # Pre-market levels (non-swept, with price)
    levels_clean = levels_df[
        levels_df['level_name'].isin(INTERMEDIATE_LEVEL_NAMES) &
        levels_df['price'].notna() &
        (levels_df['swept_pre_rth'] != True)  # noqa: E712
    ].copy()
    pm_by_date = {d: g for d, g in levels_clean.groupby('date')}

    # In-session FVGs (already filtered to ≥15pts in tagger)
    is_by_date: dict = {}
    if not insession_fvgs_df.empty:
        insession_fvgs_df = insession_fvgs_df.copy()
        insession_fvgs_df['price'] = pd.to_numeric(insession_fvgs_df['price'], errors='coerce')
        is_by_date = {d: g for d, g in insession_fvgs_df.groupby('date')}

    flags = []
    for _, row in merged.iterrows():
        nm_price = row.get('near_miss_level_price')
        entry = pd.to_numeric(row.get('entry_price'), errors='coerce')
        d = row.get('trade_date')
        direction = row.get('direction')

        if pd.isna(nm_price) or pd.isna(entry) or direction not in ('long', 'short'):
            flags.append(False)
            continue

        nm_price = float(nm_price)
        entry = float(entry)

        found = False

        # Check pre-market levels
        if d in pm_by_date:
            day_lv = pm_by_date[d]
            if direction == 'long':
                between = day_lv[
                    (day_lv['side'] == 'resistance') &
                    (day_lv['price'] > entry) &
                    (day_lv['price'] < nm_price)
                ]
            else:
                between = day_lv[
                    (day_lv['side'] == 'support') &
                    (day_lv['price'] < entry) &
                    (day_lv['price'] > nm_price)
                ]
            if len(between) > 0:
                found = True

        # Check in-session FVGs
        if not found and d in is_by_date:
            day_is = is_by_date[d]
            if direction == 'long':
                # Bearish in-session FVG (resistance) between entry and nm_price
                between = day_is[
                    (day_is['side'] == 'resistance') &
                    (day_is['price'] > entry) &
                    (day_is['price'] < nm_price)
                ]
            else:
                # Bullish in-session FVG (support) between nm_price and entry
                between = day_is[
                    (day_is['side'] == 'support') &
                    (day_is['price'] < entry) &
                    (day_is['price'] > nm_price)
                ]
            if len(between) > 0:
                found = True

        flags.append(found)

    return pd.Series(flags, index=merged.index)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not NEAR_MISS_CSV.exists():
        print(f'ERROR: {NEAR_MISS_CSV} not found — run tagger.py first.')
        sys.exit(1)

    print('Loading baseline trades...')
    trades = pd.read_csv(TRADES_PATH)
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['trade_date'] = trades['timestamp'].dt.date
    trades['entry_price'] = pd.to_numeric(trades['entry_price'], errors='coerce')

    print('Loading near-miss days...')
    nm = pd.read_csv(NEAR_MISS_CSV)
    nm['date'] = pd.to_datetime(nm['date']).dt.date
    nm['near_miss_present'] = (
        nm['near_miss_present'].astype(str).str.strip().str.lower() == 'true'
    )
    nm['near_miss_confirmed_time'] = pd.to_datetime(
        nm['near_miss_confirmed_time'], errors='coerce'
    )
    nm['near_miss_level_price'] = pd.to_numeric(nm['near_miss_level_price'], errors='coerce')

    print('Loading session levels for intermediate-draw check...')
    levels_df = pd.read_csv(LEVELS_PATH, low_memory=False)
    levels_df['date'] = pd.to_datetime(levels_df['date']).dt.date
    levels_df['price'] = pd.to_numeric(levels_df['price'], errors='coerce')

    print('Loading in-session FVGs...')
    if INSESSION_FVG_CSV.exists():
        insession_fvgs_df = pd.read_csv(INSESSION_FVG_CSV)
        insession_fvgs_df['date'] = pd.to_datetime(insession_fvgs_df['date']).dt.date
        insession_fvgs_df['price'] = pd.to_numeric(insession_fvgs_df['price'], errors='coerce')
    else:
        print(f'  WARNING: {INSESSION_FVG_CSV} not found — stacked-draw check will use pre-market levels only.')
        insession_fvgs_df = pd.DataFrame(columns=['date', 'level_name', 'side', 'price'])

    # Join trades with near-miss tags on date
    merged = trades.merge(
        nm[[
            'date', 'near_miss_present', 'near_miss_direction',
            'near_miss_level_type', 'near_miss_level_price',
            'near_miss_distance_pts', 'near_miss_gap_count',
            'near_miss_confirmed_time',
        ]],
        left_on='trade_date',
        right_on='date',
        how='left',
    )
    merged['near_miss_present'] = merged['near_miss_present'].fillna(False)

    # -----------------------------------------------------------------------
    # Derived boolean flags
    # -----------------------------------------------------------------------

    nm_present = merged['near_miss_present'] == True  # noqa: E712

    aligned = (
        ((merged['near_miss_direction'] == 'up') & (merged['direction'] == 'long')) |
        ((merged['near_miss_direction'] == 'down') & (merged['direction'] == 'short'))
    )

    opposite = nm_present & merged['near_miss_direction'].notna() & ~aligned

    # Entry is strictly AFTER near-miss confirmation (causally clean)
    entry_after_confirm = (
        merged['timestamp'] > merged['near_miss_confirmed_time']
    ).fillna(False)

    # Near-miss level is still a draw at entry: above entry for longs, below for shorts
    level_still_open = (
        ((merged['direction'] == 'long') &
         (merged['entry_price'] < merged['near_miss_level_price'])) |
        ((merged['direction'] == 'short') &
         (merged['entry_price'] > merged['near_miss_level_price']))
    ).fillna(False)

    # -----------------------------------------------------------------------
    # Cohort masks
    # -----------------------------------------------------------------------

    c1_mask = nm_present & aligned & entry_after_confirm & level_still_open
    c2_mask = opposite & entry_after_confirm
    c3_mask = nm_present & aligned          # broad (includes before-confirm)
    c4_mask = ~nm_present

    cohort1 = merged[c1_mask].copy()
    cohort2 = merged[c2_mask].copy()
    cohort3 = merged[c3_mask].copy()
    cohort4 = merged[c4_mask].copy()

    # Cohort 1b: Cohort 1 + stacked intermediate draw
    print('Computing intermediate-level flags (cohort 1b)...')
    c1b_intermediate = build_intermediate_flag(cohort1, levels_df, insession_fvgs_df)
    cohort1b = cohort1[c1b_intermediate].copy()

    # Longs sub-cohorts of Cohort 1 — the 8yr edge concentrates entirely in longs.
    c1_longs = cohort1[cohort1['direction'] == 'long'].copy()
    c1_longs_dist_le10 = c1_longs[
        pd.to_numeric(c1_longs['near_miss_distance_pts'], errors='coerce') <= LONGS_DIST_CAP_PTS
    ].copy()
    c1_longs_hq_levels = c1_longs[
        c1_longs['near_miss_level_type'].isin(HQ_LEVEL_NAMES)
    ].copy()

    # Baseline = every trade in the joined log (no near-miss filter), for reference.
    baseline = merged.copy()

    # Diagnostic
    n_before_confirm = int((nm_present & aligned & ~entry_after_confirm).sum())
    n_level_swept = int((nm_present & aligned & entry_after_confirm & ~level_still_open).sum())
    print(f'  Dropped from aligned+after_confirm: '
          f'{n_before_confirm} entered before confirmation, '
          f'{n_level_swept} had near-miss level already swept at entry')

    # -----------------------------------------------------------------------
    # Print summary
    # -----------------------------------------------------------------------

    print()
    print(f'Trades source: {TRADES_PATH}')
    print('=' * 100)
    print('NEAR-MISS LIQUIDITY DRAW — COHORT SUMMARY')
    print('=' * 100)
    print(fmt_stats('Baseline  all trades (no near-miss filter)',                 cohort_stats(baseline)))
    print(fmt_stats('C1  going back for it (clean: after confirm + level open)', cohort_stats(cohort1)))
    print(fmt_stats('C1  longs only, distance <=10pts (headline)',                cohort_stats(c1_longs_dist_le10)))
    print(fmt_stats('C1  longs only, high-quality level types',                   cohort_stats(c1_longs_hq_levels)))
    print(fmt_stats('C1b going back for it + stacked intermediate draw',         cohort_stats(cohort1b)))
    print(fmt_stats('C2  fade of near miss (opposite direction, after confirm)',  cohort_stats(cohort2)))
    print(fmt_stats('C3  aligned + near miss, all (incl. before confirm)',        cohort_stats(cohort3)))
    print(fmt_stats('C4  no near miss on day (control)',                          cohort_stats(cohort4)))
    print('=' * 100)

    # -----------------------------------------------------------------------
    # Outputs
    # -----------------------------------------------------------------------

    summary_rows = []
    for label, df in [
        ('baseline',                baseline),
        ('c4_control',              cohort4),
        ('c3_aligned_all',          cohort3),
        ('c1_going_back_clean',     cohort1),
        ('c1b_going_back_stacked',  cohort1b),
        ('c1_longs_dist_le10',      c1_longs_dist_le10),
        ('c1_longs_hq_levels',      c1_longs_hq_levels),
        ('c2_fade',                 cohort2),
    ]:
        s = cohort_stats(df)
        summary_rows.append({'cohort': label, **s})

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULTS_DIR / 'cohort_summary.csv'
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)
    print(f'\nWrote {summary_path}')

    for label, df in [
        ('c1_going_back_clean',    cohort1),
        ('c1b_going_back_stacked', cohort1b),
        ('c1_longs_dist_le10',     c1_longs_dist_le10),
        ('c1_longs_hq_levels',     c1_longs_hq_levels),
        ('c2_fade',                cohort2),
        ('c3_aligned_all',         cohort3),
        ('c4_control',             cohort4),
    ]:
        out = df[df['outcome'].isin(TRADEABLE_OUTCOMES)].copy()
        out_path = RESULTS_DIR / f'trades_{label}.csv'
        out.to_csv(out_path, index=False)


if __name__ == '__main__':
    main()
