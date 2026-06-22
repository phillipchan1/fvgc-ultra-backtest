"""
Shared helpers for the VP × FVGC × Liquidity expansion menu.

Every experiment under studies/vp_fvgc_expansion/ should use these loaders
so we get a single, audited path to baseline trades + causally-safe levels.

NO raw `daily_volume_profile.csv` joins on `date` allowed.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.causal_features import (  # noqa: E402
    load_lagged_vp,
    load_session_levels,
    add_trade_level_features,
)

BASELINE_TRADES = ROOT / 'studies/baseline/results/trades.csv'

# Standard walk-forward split (matches the Phase A vp_targets convention)
IS_MAX_YEAR = 2022
OOS_MIN_YEAR = 2023
PRE_IS_YEAR = 2018  # tiny sanity check year (smallest sample)

# A+ play exit rule
TP_R = 3.0
SL_R = 1.0


def load_trades() -> pl.DataFrame:
    """Load baseline FVGC trades, drop skips, add year/date helpers."""
    df = (
        pl.read_csv(BASELINE_TRADES, try_parse_dates=True)
        .filter(pl.col('outcome') != 'skip')
        .with_columns([
            pl.col('timestamp').dt.date().alias('date'),
            pl.col('timestamp').dt.year().alias('year'),
            (pl.col('timestamp').dt.hour().cast(pl.Int32) * 60
             + pl.col('timestamp').dt.minute().cast(pl.Int32)).alias('mod'),
        ])
    )
    df = df.with_columns([
        (pl.col('year') <= IS_MAX_YEAR).alias('is_in_is'),
        (pl.col('year') >= OOS_MIN_YEAR).alias('is_in_oos'),
    ])
    return df


def with_lagged_vp(trades: pl.DataFrame) -> pl.DataFrame:
    """Causal: adds poc_lag1, vah_lag1, val_lag1, va_width_lag1."""
    return load_lagged_vp(trades)


def with_session_levels(trades: pl.DataFrame, names=None) -> pl.DataFrame:
    """Causal: adds named columns from session_levels.csv with availability gating."""
    return load_session_levels(trades, names=names)


def signed_r_to_level(trades: pl.DataFrame, level_col: str) -> np.ndarray:
    """Signed R-distance from entry to a level, positive = ahead in trade direction.

    Returns NaN when the level is NaN.
    """
    lvl = trades[level_col].to_numpy().astype(float)
    ep = trades['entry_price'].to_numpy()
    sl = trades['sl_dist'].to_numpy()
    is_long = (trades['direction'].to_numpy() == 'long')
    diff = lvl - ep
    return np.where(is_long, diff, -diff) / sl


def in_zone(rs: np.ndarray, lo: float = 0.5, hi: float = 3.0) -> np.ndarray:
    """Bool array: level lies AHEAD (positive R) within [lo, hi] of entry."""
    with np.errstate(invalid='ignore'):
        return (rs >= lo) & (rs <= hi)


def coincides(p1: np.ndarray, p2: np.ndarray, tol_pts: float = 3.0) -> np.ndarray:
    """Bool array: |p1 - p2| <= tol_pts, NaN-safe (NaN -> False)."""
    d = np.abs(p1 - p2)
    return np.where(np.isnan(d), False, d <= tol_pts)


# -----------------------------------------------------------------------------
# Play economics — fixed +3R TP / -1R SL
# -----------------------------------------------------------------------------

def play_economics(trades: pl.DataFrame, hit_col: str = 'hit_3_0R',
                   sl_col_hit: str | None = None) -> dict:
    """Compute WR, PF, expectancy at fixed +TP_R / -SL_R using a hit column.

    Convention: a trade where hit_3_0R is True wins +3R; else loses -1R.
    (This matches the A+ exit rule: fixed TP, fixed SL, no scaling.)

    Returns dict with: n, wr, pf, exp_r, sum_r.
    """
    n = trades.height
    if n == 0:
        return {'n': 0, 'wr': None, 'pf': None, 'exp_r': None, 'sum_r': None}
    wins = trades.filter(pl.col(hit_col).cast(pl.Boolean)).height
    losses = n - wins
    wr = wins / n if n else None
    gross_win = wins * TP_R
    gross_loss = losses * SL_R
    pf = (gross_win / gross_loss) if gross_loss > 0 else float('inf')
    exp_r = TP_R * wr - SL_R * (1 - wr)
    sum_r = gross_win - gross_loss
    return {'n': n, 'wr': wr, 'pf': pf, 'exp_r': exp_r, 'sum_r': sum_r}


def lift_stats(trades: pl.DataFrame, base_rate: float | None = None,
               target: str = 'hit_2_0R') -> dict:
    """Hit-rate lift vs base (for comparison with parent vp_targets study)."""
    n = trades.height
    if n == 0:
        return {'n': 0, 'rate': None, 'lift_pp': None}
    rate = trades[target].mean()
    return {
        'n': n,
        'rate': rate,
        'lift_pp': ((rate - base_rate) * 100) if base_rate is not None else None,
    }


def walk_forward(trades_all: pl.DataFrame, mask, target: str = 'hit_2_0R',
                 hit_col: str = 'hit_3_0R') -> dict:
    """Run pre-IS (2018), IS (2018-22), OOS (2023-26) split for a boolean mask.

    Returns dict of dicts with lift + economics per cohort, plus the OOS lift
    relative to the OOS base rate.
    """
    sub = trades_all.filter(mask)
    is_base = trades_all.filter(pl.col('is_in_is'))[target].mean()
    oos_base = trades_all.filter(pl.col('is_in_oos'))[target].mean()
    pre_is = trades_all.filter(pl.col('year') == PRE_IS_YEAR)
    pre_is_base = pre_is[target].mean() if pre_is.height else None

    out = {
        'all': {**lift_stats(sub, None, target=target),
                **play_economics(sub, hit_col=hit_col)},
        'is': {**lift_stats(sub.filter(pl.col('is_in_is')), is_base, target=target),
               **play_economics(sub.filter(pl.col('is_in_is')), hit_col=hit_col)},
        'oos': {**lift_stats(sub.filter(pl.col('is_in_oos')), oos_base, target=target),
                **play_economics(sub.filter(pl.col('is_in_oos')), hit_col=hit_col)},
        'pre_is': {**lift_stats(sub.filter(pl.col('year') == PRE_IS_YEAR),
                                pre_is_base, target=target),
                   **play_economics(sub.filter(pl.col('year') == PRE_IS_YEAR),
                                    hit_col=hit_col)},
        'base_rates': {
            'is': is_base, 'oos': oos_base, 'pre_is': pre_is_base,
        },
    }
    return out


def yearly_stability(trades_all: pl.DataFrame, mask,
                     hit_col: str = 'hit_3_0R') -> pl.DataFrame:
    """Yearly economics for the masked cohort."""
    sub = trades_all.filter(mask)
    rows = []
    for y in sorted(trades_all['year'].unique().to_list()):
        f = sub.filter(pl.col('year') == y)
        econ = play_economics(f, hit_col=hit_col)
        rows.append({'year': y, **econ})
    return pl.DataFrame(rows)


def format_econ(e: dict) -> str:
    """Pretty-print economics dict."""
    if e['n'] == 0:
        return f"n=0"
    wr = e['wr'] * 100 if e['wr'] is not None else float('nan')
    pf = e['pf']
    pf_str = f"{pf:.2f}" if pf != float('inf') else "INF"
    exp = e['exp_r']
    return (f"n={e['n']:>3}  WR={wr:.1f}%  PF={pf_str:>5}  "
            f"exp={exp:+.2f}R  sumR={e['sum_r']:+.1f}")


def print_verdict(name: str, wf: dict, kill_oos_lift_pp: float = 5.0,
                  kill_oos_pf: float = 1.5, kill_min_n_oos: int = 20) -> dict:
    """Print verdict and return a structured summary."""
    oos = wf['oos']
    pre = wf['pre_is']
    is_ = wf['is']

    print(f"\n=== {name} ===")
    print(f"  pre-IS (2018):   {format_econ(pre)}  lift_2R={pre.get('lift_pp')}")
    print(f"  IS  (2018-22):   {format_econ(is_)}  lift_2R={is_.get('lift_pp')}")
    print(f"  OOS (2023-26):   {format_econ(oos)}  lift_2R={oos.get('lift_pp')}")

    verdict = 'PASS'
    reasons = []
    if oos['n'] < kill_min_n_oos:
        verdict = 'SMALL_N'
        reasons.append(f"OOS n={oos['n']} < {kill_min_n_oos}")
    elif oos.get('lift_pp') is not None and oos['lift_pp'] < kill_oos_lift_pp:
        verdict = 'FAIL'
        reasons.append(f"OOS lift {oos['lift_pp']:+.2f}pp < {kill_oos_lift_pp}pp")
    elif oos['pf'] is not None and oos['pf'] != float('inf') and oos['pf'] < kill_oos_pf:
        verdict = 'FAIL'
        reasons.append(f"OOS PF {oos['pf']:.2f} < {kill_oos_pf}")
    print(f"  VERDICT: {verdict}  {' | '.join(reasons) if reasons else ''}")
    return {
        'name': name,
        'verdict': verdict,
        'reasons': reasons,
        'pre_is_n': pre['n'], 'pre_is_pf': pre['pf'], 'pre_is_wr': pre['wr'],
        'is_n': is_['n'], 'is_pf': is_['pf'], 'is_wr': is_['wr'],
        'oos_n': oos['n'], 'oos_pf': oos['pf'], 'oos_wr': oos['wr'],
        'oos_exp_r': oos['exp_r'], 'oos_lift_pp': oos.get('lift_pp'),
    }
