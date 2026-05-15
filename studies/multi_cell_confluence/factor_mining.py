"""Phase C: Univariate WR-lift per factor per cell (IS only, protected_swing excluded).

For each (window, direction) cell and each candidate factor:
- Compute n_active, n_inactive, wr_active, wr_inactive
- Lift = wr_active - wr_inactive (in pp)
- Keep factors with |lift| >= MIN_LIFT and both buckets >= MIN_N

Factor universe is built from columns already present in the analysis frame
(no new derivations). Quantile cutoffs are fit on IS data only.

Output: results/factor_lift_per_cell.csv (long format)
        results/factor_definitions.csv (for reference)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from studies.multi_cell_confluence.utils import (  # noqa: E402
    DIRECTIONS,
    RESULTS_DIR,
    WINDOWS,
    cell_filter,
    load_analysis_frame,
)

MIN_LIFT_PP = 5.0
MIN_BUCKET_N = 20


# ===================================================================
# Look-ahead-safe factor allow-list per cell
# ===================================================================
#
# Each macro window has entries spread across its 15-minute span. A factor is
# "safe" for a cell only if it's knowable at the LATEST possible entry time
# within that window (conservative).
#
# - M1 (9:30-9:44): only candle_930 is complete (1-min bar). or_5min and
#   fvgs_first_5min require >=9:35 (29% of M1 entries are before 9:35).
# - M2 (9:45-9:59): or_5min, or_15min, fvgs_first_5min, fvgs_first_15min,
#   macro_1 (9:30-9:45) all complete. or_45min (9:30-10:15) NOT complete.
# - M3 (10:00-10:14): same as M2 plus macro_2 (9:45-10:00) complete.
# - M4 (10:15+): all in-session features complete except macro_4 (current).
#
# Pre-market factors (gap, overnight, prior_day, news, calendar, vixy, regime)
# are always safe. variant_* is the engine's entry classification at trigger
# time, also safe.

ALWAYS_SAFE_PREFIXES = (
    'gap_', 'overnight_direction', 'overnight_range_',
    'prior_day_', 'no_red_folder', 'has_red_folder',
    'no_pre_rth_news', 'has_pre_rth_news', 'no_during_session_news',
    'is_fomc_week', 'not_fomc_week', 'is_opex_week', 'is_quad_witching',
    'dow_', 'vixy_', 'regime_', 'variant_',
)


def factor_safe_for_cell(factor_id: str, window: str) -> bool:
    """Return True if this factor is knowable at entry time for any trade in `window`.

    Conservative: if the factor needs information from a time after the latest
    possible entry in `window`, it's unsafe (excluded for that cell).
    """
    # Always-safe factors (pre-market + calendar + entry-quality)
    for pre in ALWAYS_SAFE_PREFIXES:
        if factor_id.startswith(pre):
            return True

    # candle_930 (9:30-9:31): safe for all windows (earliest M1 entry is 9:31)
    if factor_id in ('bull_930', 'bear_930') or factor_id.startswith('c930_'):
        return True

    # or_5min / fvgs_first_5min (9:30-9:35): unsafe for M1, safe M2+
    if factor_id.startswith('or_5m_') or factor_id.startswith('has_5m_') or factor_id.startswith('no_5m_'):
        return window in ('M2', 'M3', 'M4')

    # or_15min / fvgs_first_15min (9:30-9:45): unsafe for M1, safe M2+
    if factor_id.startswith('or_15m_') or factor_id.startswith('has_15m_'):
        return window in ('M2', 'M3', 'M4')

    # or_45min (9:30-10:15): unsafe for M1/M2/M3, safe only M4
    if factor_id.startswith('or_45m_'):
        return window == 'M4'

    # macro_X_*: factor on window X is safe only when window X is fully historical
    # (i.e., current cell is strictly LATER than X). For M4 we allow macro_3
    # because it just completed at 10:15 sharp.
    for X in (1, 2, 3, 4):
        if factor_id.startswith(f'macro_{X}_'):
            window_order = {'M1': 1, 'M2': 2, 'M3': 3, 'M4': 4}
            return window_order.get(window, 0) > X

    # Unknown factor — be conservative
    return False


# ===================================================================
# Factor definitions
# ===================================================================

def build_factor_masks(df: pd.DataFrame, quantiles: dict) -> dict[str, pd.Series]:
    """Return dict of factor_id -> boolean mask (True = factor present).

    Quantile-based factors use cutoffs from `quantiles` (IS-fit).
    """
    masks: dict[str, pd.Series] = {}

    # --- Gap factors ---
    masks['gap_large_down'] = df['gap_from_prior_close'] < -100
    masks['gap_down'] = df['gap_from_prior_close'] < -10
    masks['gap_flat'] = df['gap_from_prior_close'].between(-10, 10, inclusive='both')
    masks['gap_up'] = df['gap_from_prior_close'] > 10
    masks['gap_large_up'] = df['gap_from_prior_close'] > 100

    # --- Overnight ---
    masks['overnight_down'] = df['overnight_direction'] == 'down'
    masks['overnight_up'] = df['overnight_direction'] == 'up'
    masks['overnight_range_top_q'] = df['overnight_range'] >= quantiles['overnight_range_q75']
    masks['overnight_range_bot_q'] = df['overnight_range'] <= quantiles['overnight_range_q25']

    # --- Prior day ---
    masks['prior_day_weak'] = df['prior_day_close_position'] < 0.33
    masks['prior_day_strong'] = df['prior_day_close_position'] > 0.67
    masks['prior_day_mid'] = df['prior_day_close_position'].between(0.33, 0.67, inclusive='both')

    # --- News / calendar ---
    masks['no_red_folder'] = df['has_red_folder_news'] == False
    masks['has_red_folder'] = df['has_red_folder_news'] == True
    masks['no_pre_rth_news'] = df['has_pre_rth_news'] == False
    masks['has_pre_rth_news'] = df['has_pre_rth_news'] == True
    masks['no_during_session_news'] = df['has_during_session_news'] == False
    masks['is_fomc_week'] = df['is_fomc_week'] == True
    masks['not_fomc_week'] = df['is_fomc_week'] == False
    masks['is_opex_week'] = df['is_opex_week'] == True
    masks['is_quad_witching'] = df['is_quad_witching'] == True

    # Day-of-week
    for dow in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        masks[f'dow_{dow.lower()}'] = df['day_of_week_name'] == dow

    # --- Vol regime ---
    masks['vixy_low'] = df['vixy_regime'] == 'low'
    masks['vixy_normal'] = df['vixy_regime'] == 'normal'
    masks['vixy_elevated'] = df['vixy_regime'] == 'elevated'
    masks['vixy_high'] = df['vixy_regime'] == 'high'

    # --- 9:30 candle ---
    masks['bull_930'] = df['candle_930_direction'] == 'bullish'
    masks['bear_930'] = df['candle_930_direction'] == 'bearish'
    masks['c930_range_top_q'] = df['candle_930_range'] >= quantiles['candle_930_range_q75']
    masks['c930_range_bot_q'] = df['candle_930_range'] <= quantiles['candle_930_range_q25']
    masks['c930_body_top_q'] = df['candle_930_body'] >= quantiles['candle_930_body_q75']

    # --- First 5m / 15m FVG counts ---
    masks['has_5m_bull_fvg'] = df['fvgs_first_5min_bullish'].fillna(0) >= 1
    masks['has_5m_bear_fvg'] = df['fvgs_first_5min_bearish'].fillna(0) >= 1
    masks['no_5m_bull_fvg'] = df['fvgs_first_5min_bullish'].fillna(0) == 0
    masks['no_5m_bear_fvg'] = df['fvgs_first_5min_bearish'].fillna(0) == 0
    masks['has_15m_bull_fvg'] = df['fvgs_first_15min_bullish'].fillna(0) >= 1
    masks['has_15m_bear_fvg'] = df['fvgs_first_15min_bearish'].fillna(0) >= 1

    # --- Open range ---
    masks['or_5m_top_q'] = df['or_5min_range'] >= quantiles['or_5min_range_q75']
    masks['or_5m_bot_q'] = df['or_5min_range'] <= quantiles['or_5min_range_q25']
    masks['or_15m_top_q'] = df['or_15min_range'] >= quantiles['or_15min_range_q75']
    masks['or_15m_bot_q'] = df['or_15min_range'] <= quantiles['or_15min_range_q25']
    masks['or_45m_top_q'] = df['or_45min_range'] >= quantiles['or_45min_range_q75']
    masks['or_45m_bot_q'] = df['or_45min_range'] <= quantiles['or_45min_range_q25']

    # --- Macro-window FVG counts (in-window only at time of entry) ---
    # macro_X_num_fvgs is the count *for that window*. Use the one matching the
    # entry's window for "active during entry" semantics.
    for i in range(1, 5):
        masks[f'macro_{i}_has_fvg'] = df[f'macro_{i}_num_fvgs'].fillna(0) >= 1
        masks[f'macro_{i}_2plus_fvgs'] = df[f'macro_{i}_num_fvgs'].fillna(0) >= 2

    # --- Variant (entry quality signal) ---
    masks['variant_bos'] = df['variant'] == 'bos'
    masks['variant_ifvg'] = df['variant'] == 'ifvg'
    masks['variant_no_fvg'] = df['variant'] == 'no_fvg'

    # --- Regime (this is a label, not a filter target, but exposing it helps audit) ---
    masks['regime_bull'] = df['regime_60d'] == 'bull'
    masks['regime_bear'] = df['regime_60d'] == 'bear'
    masks['regime_neutral'] = df['regime_60d'] == 'neutral'

    return masks


def fit_quantiles(is_df: pd.DataFrame) -> dict:
    """Compute IS-only quantile cutoffs for continuous factors."""
    q = {}
    for col in ['overnight_range', 'candle_930_range', 'candle_930_body',
                'or_5min_range', 'or_15min_range', 'or_45min_range']:
        s = pd.to_numeric(is_df[col], errors='coerce').dropna()
        if len(s):
            q[f'{col}_q25'] = float(s.quantile(0.25))
            q[f'{col}_q75'] = float(s.quantile(0.75))
        else:
            q[f'{col}_q25'] = float('nan')
            q[f'{col}_q75'] = float('nan')
    return q


# ===================================================================
# Lift computation
# ===================================================================

def compute_lift(sub: pd.DataFrame, mask: pd.Series) -> dict:
    """Compute univariate WR lift for a factor mask within a slice of trades."""
    mask = mask.reindex(sub.index).fillna(False)
    active = sub[mask]
    inactive = sub[~mask]

    n_a = len(active)
    n_i = len(inactive)

    def _wr(s: pd.DataFrame) -> float:
        if len(s) == 0:
            return float('nan')
        w = (s['outcome'] == 'win').sum()
        return 100.0 * w / len(s)

    wr_a = _wr(active)
    wr_i = _wr(inactive)
    lift = wr_a - wr_i if pd.notna(wr_a) and pd.notna(wr_i) else float('nan')

    return {
        'n_active': n_a,
        'n_inactive': n_i,
        'wr_active': round(wr_a, 1) if pd.notna(wr_a) else float('nan'),
        'wr_inactive': round(wr_i, 1) if pd.notna(wr_i) else float('nan'),
        'lift_pp': round(lift, 1) if pd.notna(lift) else float('nan'),
    }


# ===================================================================
# Main
# ===================================================================

def main():
    df = load_analysis_frame()
    is_df = df[df['split'] == 'IS'].copy()
    is_excl = is_df[is_df['variant'] != 'protected_swing'].copy()

    print(f'Fitting quantiles on {len(is_excl)} IS trades (protected_swing excluded)...')
    quantiles = fit_quantiles(is_excl)

    print('\nQuantile cutoffs:')
    for k, v in quantiles.items():
        print(f'  {k}: {v:.2f}')

    # Save quantiles for reuse in OOS phase
    with open(RESULTS_DIR / 'is_quantiles.json', 'w') as f:
        json.dump(quantiles, f, indent=2)

    print('\nBuilding factor masks across full analysis frame...')
    masks = build_factor_masks(df, quantiles)
    print(f'  {len(masks)} factors defined.')

    rows = []
    summary_per_cell = {}

    for window in WINDOWS:
        for direction in DIRECTIONS:
            cell = f'{window}_{direction}'
            sub = cell_filter(df, window, direction,
                              exclude_protected_swing=True, is_only=True)
            if len(sub) < MIN_BUCKET_N * 2:
                # Skip cells too thin even to test (M4)
                continue

            cell_factors = []
            for factor_id, full_mask in masks.items():
                if not factor_safe_for_cell(factor_id, window):
                    continue
                stats = compute_lift(sub, full_mask)
                # Filter: both buckets must have at least MIN_BUCKET_N
                if stats['n_active'] < MIN_BUCKET_N or stats['n_inactive'] < MIN_BUCKET_N:
                    continue
                rows.append({
                    'cell': cell,
                    'macro_window': window,
                    'direction': direction,
                    'factor_id': factor_id,
                    **stats,
                })
                if pd.notna(stats['lift_pp']) and abs(stats['lift_pp']) >= MIN_LIFT_PP:
                    cell_factors.append((factor_id, stats['lift_pp'], stats['n_active']))

            cell_factors.sort(key=lambda x: -abs(x[1]))
            summary_per_cell[cell] = cell_factors

    out = pd.DataFrame(rows)
    out_path = RESULTS_DIR / 'factor_lift_per_cell.csv'
    out.to_csv(out_path, index=False)
    print(f'\nWrote {out_path}  ({len(out)} cell-factor rows)')

    print('\n' + '=' * 78)
    print('  TOP FACTORS PER CELL (|lift| >= 5pp, both buckets n >= 20)')
    print('=' * 78)
    for cell, factors in summary_per_cell.items():
        print(f'\n--- {cell} ---  (n_total = {(out["cell"] == cell).any() and out[out["cell"] == cell].iloc[0]["n_active"] + out[out["cell"] == cell].iloc[0]["n_inactive"] or 0})')
        if not factors:
            print('  (no factors meet the threshold)')
            continue
        for factor_id, lift, n_a in factors[:15]:
            sign = '+' if lift > 0 else ''
            print(f'  {sign}{lift:>5.1f}pp  {factor_id:30s}  (n_active={n_a})')

    # Save the per-cell shortlist (lift >= MIN_LIFT_PP)
    shortlist_rows = []
    for cell, factors in summary_per_cell.items():
        for factor_id, lift, n_a in factors:
            shortlist_rows.append({'cell': cell, 'factor_id': factor_id,
                                   'lift_pp': lift, 'n_active': n_a})
    shortlist = pd.DataFrame(shortlist_rows)
    shortlist_path = RESULTS_DIR / 'factor_shortlist_per_cell.csv'
    shortlist.to_csv(shortlist_path, index=False)
    print(f'\nWrote {shortlist_path}  ({len(shortlist)} shortlisted cell-factor rows)')


if __name__ == '__main__':
    main()
