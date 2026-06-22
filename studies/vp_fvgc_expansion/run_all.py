"""
Master driver — runs E0..E12 on the FVGC baseline corpus under strictly
causal features (lag-1 VP + available_time-gated session levels).

Writes per-experiment CSVs to results/ and a JSON summary for the rollup.

USAGE
-----
$ python studies/vp_fvgc_expansion/run_all.py [E0 E1 ... | --all]

If no experiment IDs are given, runs all of E0..E12.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _shared import (  # noqa: E402
    load_trades, with_lagged_vp, with_session_levels,
    signed_r_to_level, in_zone, coincides,
    walk_forward, print_verdict, yearly_stability,
    PRE_IS_YEAR, IS_MAX_YEAR, OOS_MIN_YEAR,
)

OUT = HERE / 'results'
OUT.mkdir(exist_ok=True)


# -----------------------------------------------------------------------------
# Base data: trades + lag-1 VP + session levels + derived columns
# -----------------------------------------------------------------------------

def base_frame() -> pl.DataFrame:
    t = load_trades()
    t = with_lagged_vp(t)
    t = with_session_levels(t)  # adds prev_day_high/low, overnight_high/low, etc.

    # Pre-compute signed R-distances for every magnet candidate
    cols_to_add = {}
    for c in ['poc_lag1', 'vah_lag1', 'val_lag1',
              'prev_day_high', 'prev_day_low',
              'overnight_high', 'overnight_low',
              'london_high', 'london_low',
              'asia_high', 'asia_low',
              '6am_high', '6am_low',
              'nwog_high', 'nwog_low',
              'bsl_level', 'ssl_level']:
        if c in t.columns:
            cols_to_add[f'r_{c}'] = signed_r_to_level(t, c)

    t = t.with_columns([pl.Series(k, v) for k, v in cols_to_add.items()])

    # Pre-compute "ahead in 0.5-3R" flags for each level
    flags = {}
    for k in list(cols_to_add.keys()):
        flags[k.replace('r_', 'ahead_')] = in_zone(cols_to_add[k])
    t = t.with_columns([pl.Series(k, v) for k, v in flags.items()])

    # Common window flag (matches A+ 9:30-10:15)
    mod = t['mod'].to_numpy()
    t = t.with_columns(pl.Series('in_window', (mod >= 570) & (mod <= 615)))
    t = t.with_columns(pl.Series('variant_ok',
                                 t['variant'].to_numpy() != 'protected_swing'))
    t = t.with_columns(pl.Series('is_long', t['direction'].to_numpy() == 'long'))
    return t


# -----------------------------------------------------------------------------
# Experiments
# -----------------------------------------------------------------------------

def E0_aplus_lag1(t: pl.DataFrame) -> dict:
    """SANITY CHECK — original A+ play under lag-1 VP. Expected: collapse."""
    n_vp = (t['ahead_poc_lag1'].to_numpy().astype(int)
            + t['ahead_vah_lag1'].to_numpy().astype(int)
            + t['ahead_val_lag1'].to_numpy().astype(int))
    is_long = t['is_long'].to_numpy()
    val_in = t['ahead_val_lag1'].to_numpy()
    vah_in = t['ahead_vah_lag1'].to_numpy()
    va_edge_dir = (is_long & val_in) | ((~is_long) & vah_in)
    mask = (
        (n_vp >= 2) & va_edge_dir
        & t['variant_ok'].to_numpy()
        & t['in_window'].to_numpy()
    )
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E0  A+ replication under LAG-1 VP', wf)


def E1_clean_shot(t: pl.DataFrame) -> dict:
    """Single direction-matched VA-edge magnet within 0.5-1.5R (tight)."""
    is_long = t['is_long'].to_numpy()
    r_val = t['r_val_lag1'].to_numpy()
    r_vah = t['r_vah_lag1'].to_numpy()
    # Tight zone 0.5-1.5R
    val_tight = (r_val >= 0.5) & (r_val <= 1.5)
    vah_tight = (r_vah >= 0.5) & (r_vah <= 1.5)
    va_edge_tight = (is_long & val_tight) | ((~is_long) & vah_tight)
    # And only one VP magnet total (the "clean shot")
    n_vp = (t['ahead_poc_lag1'].to_numpy().astype(int)
            + t['ahead_vah_lag1'].to_numpy().astype(int)
            + t['ahead_val_lag1'].to_numpy().astype(int))
    mask = va_edge_tight & (n_vp == 1) & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E1  Single-magnet clean shot (VA-edge, 0.5-1.5R)', wf)


def E2_aged_naked_vp(t: pl.DataFrame) -> dict:
    """Aged-naked VP: lag-1 POC/VAH/VAL that *never traded* in today's session before entry.

    Approximation: prior-day POC sits OUTSIDE today's range-so-far at entry. Since we
    only have aggregated columns, we approximate "naked" as: |gap_from_prior_close|
    > distance to that level (level not yet visited at open). Combined with A+
    structure.

    NOTE: this is a coarse proxy. A proper test would walk bars to confirm
    no-touch. Kept here as a directional check.
    """
    is_long = t['is_long'].to_numpy()
    # "Naked" approximation: lag-1 POC sits AHEAD of entry AT THE OPEN.
    # If lag-1 POC is on the same side as direction (ahead in trade direction),
    # AND the overnight session didn't reach it (gap exists), it's naked-ish.
    poc_ahead = t['ahead_poc_lag1'].to_numpy()
    on_high = t['overnight_high'].to_numpy()
    on_low = t['overnight_low'].to_numpy()
    poc = t['poc_lag1'].to_numpy()
    # POC naked if overnight never reached it
    naked_poc = np.where(
        is_long,
        on_high < poc,  # for longs, overnight high stayed below POC
        on_low > poc,   # for shorts, overnight low stayed above POC
    )
    naked_poc = np.where(np.isnan(poc) | np.isnan(on_high) | np.isnan(on_low),
                         False, naked_poc)
    mask = (
        poc_ahead & naked_poc
        & t['variant_ok'].to_numpy()
        & t['in_window'].to_numpy()
    )
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E2  Aged-naked VP POC magnet', wf)


def E3_cluster_persistence(t: pl.DataFrame) -> dict:
    """VP cluster persistence — POC stable within ±3pts for 3+ consecutive prior days.

    Built off the lag-1 VP joined frame: we recompute a 3-day-stable-POC flag
    per date, then attach it.
    """
    # Build the stable-POC flag from the daily VP file directly (LAG-1 only)
    from tools.causal_features import DAILY_VP_CSV
    vp = pl.read_csv(DAILY_VP_CSV, try_parse_dates=True).sort('date')
    poc = vp['poc'].to_numpy()
    dates = vp['date'].to_list()
    stable = np.zeros(len(poc), dtype=bool)
    # NQ median day-to-day POC drift is ~89pts; ±3pts was effectively never true.
    # "Stable" = 3 prior days' POCs clustered within ±50pts (about half the
    # median drift — meaningful but produces ~10-15% of days).
    STABLE_TOL_PTS = 50.0
    for i in range(3, len(poc)):
        window = poc[i-3:i]
        if (window.max() - window.min()) <= STABLE_TOL_PTS:
            stable[i] = True
    # 'stable[i]' is the flag for date[i] derived from prior days. To get
    # the flag CAUSALLY available at date d, we use stable[i-1] for date[i].
    # So pair date[i] (for i>=1) with stable[i-1].
    stab_df = pl.DataFrame({
        'date': [dates[i] for i in range(1, len(dates))],
        'stable_poc_lag1': stable[:-1].tolist(),
    }).with_columns(pl.col('date').cast(pl.Date))
    t2 = t.join(stab_df, on='date', how='left').with_columns(
        pl.col('stable_poc_lag1').fill_null(False)
    )

    # A+ structure + stable POC condition
    n_vp = (t2['ahead_poc_lag1'].to_numpy().astype(int)
            + t2['ahead_vah_lag1'].to_numpy().astype(int)
            + t2['ahead_val_lag1'].to_numpy().astype(int))
    is_long = t2['is_long'].to_numpy()
    va_edge_dir = (is_long & t2['ahead_val_lag1'].to_numpy()) | (
        (~is_long) & t2['ahead_vah_lag1'].to_numpy())
    mask = (
        (n_vp >= 2) & va_edge_dir
        & t2['variant_ok'].to_numpy()
        & t2['in_window'].to_numpy()
        & t2['stable_poc_lag1'].to_numpy()
    )
    t3 = t2.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t3, pl.col('mask'))
    return print_verdict('E3  A+ × stable-POC (3+ consecutive days)', wf)


def E4_htf_weekly_vp(t: pl.DataFrame) -> dict:
    """HTF weekly VP — prior-week aggregated POC/VAH/VAL from daily VP.

    Approximation: weekly POC = volume-weighted median of the prior 5 daily POCs.
    VAH = max of prior 5 days' VAHs; VAL = min of prior 5 days' VALs. Crude but
    causally safe (uses only prior-week data).
    """
    from tools.causal_features import DAILY_VP_CSV
    vp = pl.read_csv(DAILY_VP_CSV, try_parse_dates=True).sort('date')
    poc = vp['poc'].to_numpy()
    vah = vp['vah'].to_numpy()
    val = vp['val'].to_numpy()
    vol = vp['rth_volume'].to_numpy()
    n = len(poc)
    wk_poc = np.full(n, np.nan)
    wk_vah = np.full(n, np.nan)
    wk_val = np.full(n, np.nan)
    for i in range(5, n):
        w = vol[i-5:i]
        p = poc[i-5:i]
        if w.sum() > 0:
            wk_poc[i] = (p * w).sum() / w.sum()
        wk_vah[i] = vah[i-5:i].max()
        wk_val[i] = val[i-5:i].min()
    # Shift so weekly applies to NEXT day (causal)
    wk = pl.DataFrame({
        'date': vp['date'].shift(-1),
        'wk_poc': wk_poc, 'wk_vah': wk_vah, 'wk_val': wk_val,
    }).filter(pl.col('date').is_not_null())

    t2 = t.join(wk, on='date', how='left')

    r_wk_poc = signed_r_to_level(t2, 'wk_poc')
    r_wk_vah = signed_r_to_level(t2, 'wk_vah')
    r_wk_val = signed_r_to_level(t2, 'wk_val')
    # Wider band for HTF (0.5-5R)
    poc_in = (r_wk_poc >= 0.5) & (r_wk_poc <= 5.0)
    vah_in = (r_wk_vah >= 0.5) & (r_wk_vah <= 5.0)
    val_in = (r_wk_val >= 0.5) & (r_wk_val <= 5.0)
    n_wk = poc_in.astype(int) + vah_in.astype(int) + val_in.astype(int)
    is_long = t2['is_long'].to_numpy()
    va_edge = (is_long & val_in) | ((~is_long) & vah_in)
    mask = (n_wk >= 2) & va_edge & t2['variant_ok'].to_numpy() & t2['in_window'].to_numpy()
    t3 = t2.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t3, pl.col('mask'))
    return print_verdict('E4  HTF weekly VP magnet stack (≥2 + VA-edge, 0.5-5R)', wf)


def E5_vp_sweep_pivot(t: pl.DataFrame) -> dict:
    """VP-sweep-then-FVGC: entry crossed a lag-1 VP level recently.

    Approximation: at entry, the trade direction is AWAY from a lag-1 VP level
    that price has just swept (overnight high/low or open vs prior level).
    Coarse proxy: long entries where overnight_low < val_lag1 < rth_open (price
    spiked through and recovered); short entries mirror.
    """
    is_long = t['is_long'].to_numpy()
    val = t['val_lag1'].to_numpy()
    vah = t['vah_lag1'].to_numpy()
    on_low = t['overnight_low'].to_numpy()
    on_high = t['overnight_high'].to_numpy()
    ep = t['entry_price'].to_numpy()
    # LONG: overnight or current entry is above VAL but a sweep happened below
    swept_long = (on_low < val) & (ep > val)
    swept_short = (on_high > vah) & (ep < vah)
    swept_long = np.where(np.isnan(on_low) | np.isnan(val), False, swept_long)
    swept_short = np.where(np.isnan(on_high) | np.isnan(vah), False, swept_short)
    swept = (is_long & swept_long) | ((~is_long) & swept_short)
    mask = swept & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E5  VP-sweep then FVGC (pivot mechanism)', wf)


def E6_level_launched(t: pl.DataFrame) -> dict:
    """Level-launched FVGC: the FVG itself (fvg_top or fvg_bottom) coincides with
    a lag-1 VP level within ±3pts."""
    top = t['fvg_top'].to_numpy()
    bot = t['fvg_bottom'].to_numpy()
    for lvl_col in ('poc_lag1', 'vah_lag1', 'val_lag1'):
        pass  # iterate below
    poc = t['poc_lag1'].to_numpy()
    vah = t['vah_lag1'].to_numpy()
    val = t['val_lag1'].to_numpy()
    launched = (
        coincides(top, poc) | coincides(bot, poc)
        | coincides(top, vah) | coincides(bot, vah)
        | coincides(top, val) | coincides(bot, val)
    )
    mask = launched & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E6  Level-launched FVGC (FVG edge ±3pts of VP)', wf)


def _liquidity_ahead_counts(t: pl.DataFrame, lo: float = 0.5, hi: float = 3.0):
    """Helper: returns (n_liq_ahead, key_edge_dir_mask) for the liquidity bucket."""
    is_long = t['is_long'].to_numpy()
    # Resistance-side levels (for longs they are ahead and good targets)
    high_levels = ['prev_day_high', 'overnight_high', 'asia_high',
                   'london_high', '6am_high']
    low_levels = ['prev_day_low', 'overnight_low', 'asia_low',
                  'london_low', '6am_low']
    # For longs, "ahead" levels are HIGHS above entry; for shorts, LOWS below entry.
    high_ahead_cols = [c for c in high_levels if c in t.columns]
    low_ahead_cols = [c for c in low_levels if c in t.columns]

    n_high_ahead = np.zeros(t.height, dtype=int)
    for c in high_ahead_cols:
        r = signed_r_to_level(t, c)
        in_z = (r >= lo) & (r <= hi)
        # for longs, this is "ahead"; for shorts, "behind"
        n_high_ahead = n_high_ahead + (in_z & is_long).astype(int)

    n_low_ahead = np.zeros(t.height, dtype=int)
    for c in low_ahead_cols:
        r = signed_r_to_level(t, c)
        in_z = (r >= lo) & (r <= hi)
        n_low_ahead = n_low_ahead + (in_z & (~is_long)).astype(int)

    n_liq = n_high_ahead + n_low_ahead

    # "Key edge" for liquidity = the nearest of {prev_day, overnight} in direction
    key_long = (
        ((signed_r_to_level(t, 'prev_day_high') >= lo)
         & (signed_r_to_level(t, 'prev_day_high') <= hi))
        | ((signed_r_to_level(t, 'overnight_high') >= lo)
           & (signed_r_to_level(t, 'overnight_high') <= hi))
    ) if 'prev_day_high' in t.columns else np.zeros(t.height, dtype=bool)
    key_short = (
        ((signed_r_to_level(t, 'prev_day_low') >= lo)
         & (signed_r_to_level(t, 'prev_day_low') <= hi))
        | ((signed_r_to_level(t, 'overnight_low') >= lo)
           & (signed_r_to_level(t, 'overnight_low') <= hi))
    ) if 'prev_day_low' in t.columns else np.zeros(t.height, dtype=bool)
    key_edge_dir = (is_long & key_long) | ((~is_long) & key_short)
    return n_liq, key_edge_dir


def E7_cross_framework(t: pl.DataFrame) -> dict:
    """Cross-framework magnet stack: pool VP + liquidity for the ≥2 count."""
    n_vp = (t['ahead_poc_lag1'].to_numpy().astype(int)
            + t['ahead_vah_lag1'].to_numpy().astype(int)
            + t['ahead_val_lag1'].to_numpy().astype(int))
    n_liq, key_liq = _liquidity_ahead_counts(t)
    n_total = n_vp + n_liq
    # Require direction-matched "key edge" from EITHER framework
    is_long = t['is_long'].to_numpy()
    va_edge_dir = (is_long & t['ahead_val_lag1'].to_numpy()) | (
        (~is_long) & t['ahead_vah_lag1'].to_numpy())
    key_edge = va_edge_dir | key_liq
    mask = (n_total >= 2) & key_edge & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E7  Cross-framework magnet stack (VP+Liq ≥2 + key edge)', wf)


def E8_confluent_zone(t: pl.DataFrame) -> dict:
    """Confluent-zone magnet: VP level coincides with a liquidity level within ±3pts."""
    poc = t['poc_lag1'].to_numpy()
    vah = t['vah_lag1'].to_numpy()
    val = t['val_lag1'].to_numpy()
    pdh = t['prev_day_high'].to_numpy()
    pdl = t['prev_day_low'].to_numpy()
    onh = t['overnight_high'].to_numpy()
    onl = t['overnight_low'].to_numpy()
    # Any VP confluence with prev_day or overnight key edges
    is_long = t['is_long'].to_numpy()
    long_conf = (
        coincides(vah, pdh) | coincides(vah, onh)
        | coincides(poc, pdh) | coincides(poc, onh)
    )
    short_conf = (
        coincides(val, pdl) | coincides(val, onl)
        | coincides(poc, pdl) | coincides(poc, onl)
    )
    # Confluence has to be AHEAD of entry in the trade direction
    r_pdh = signed_r_to_level(t, 'prev_day_high')
    r_pdl = signed_r_to_level(t, 'prev_day_low')
    r_onh = signed_r_to_level(t, 'overnight_high')
    r_onl = signed_r_to_level(t, 'overnight_low')
    long_ahead = in_zone(r_pdh) | in_zone(r_onh)
    short_ahead = in_zone(r_pdl) | in_zone(r_onl)
    mask = (
        ((is_long & long_conf & long_ahead) | ((~is_long) & short_conf & short_ahead))
        & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    )
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E8  Confluent-zone magnet (VP±3pts of PDH/PDL/ONH/ONL)', wf)


def E9_nwog_x_vp(t: pl.DataFrame) -> dict:
    """NWOG (Monday-only) × VP: NWOG high/low coincides with VAH/VAL."""
    is_mon = t['timestamp'].dt.weekday().to_numpy() == 1  # polars: Monday=1
    nwog_h = t['nwog_high'].to_numpy() if 'nwog_high' in t.columns else np.full(t.height, np.nan)
    nwog_l = t['nwog_low'].to_numpy() if 'nwog_low' in t.columns else np.full(t.height, np.nan)
    vah = t['vah_lag1'].to_numpy()
    val = t['val_lag1'].to_numpy()
    is_long = t['is_long'].to_numpy()
    conf_long = coincides(nwog_h, vah) | coincides(nwog_h, val)
    conf_short = coincides(nwog_l, vah) | coincides(nwog_l, val)
    # And ahead
    r_nwog_h = signed_r_to_level(t, 'nwog_high') if 'nwog_high' in t.columns else np.full(t.height, np.nan)
    r_nwog_l = signed_r_to_level(t, 'nwog_low') if 'nwog_low' in t.columns else np.full(t.height, np.nan)
    long_ahead = (r_nwog_h >= 0.5) & (r_nwog_h <= 3.0)
    short_ahead = (r_nwog_l >= 0.5) & (r_nwog_l <= 3.0)
    mask = (
        is_mon
        & ((is_long & conf_long & long_ahead) | ((~is_long) & conf_short & short_ahead))
        & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    )
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E9  NWOG × VP confluence (Monday only)', wf)


def E10_liquidity_only(t: pl.DataFrame) -> dict:
    """Liquidity-only mirror: ≥2 liquidity magnets ahead + direction-matched key edge."""
    n_liq, key_liq = _liquidity_ahead_counts(t)
    mask = (n_liq >= 2) & key_liq & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E10 Liquidity-only mirror (≥2 liq ahead + PDH/PDL or ONH/ONL key)', wf)


def E11_equal_hl_cluster(t: pl.DataFrame) -> dict:
    """Equal-H/L cluster + FVGC reversal — approximated by BSL/SSL level proximity.

    The session_levels.csv 'bsl_level' / 'ssl_level' columns ARE swing
    structural levels (Bullish/Bearish Strength Levels). Reversal play: FVGC
    fires going AWAY from a recently-broken bsl/ssl level (price swept it and
    reverses).
    """
    bsl = t['bsl_level'].to_numpy() if 'bsl_level' in t.columns else np.full(t.height, np.nan)
    ssl = t['ssl_level'].to_numpy() if 'ssl_level' in t.columns else np.full(t.height, np.nan)
    ep = t['entry_price'].to_numpy()
    sl = t['sl_dist'].to_numpy()
    is_long = t['is_long'].to_numpy()
    # Reversal: long entry just above an ssl level that was recently swept
    # (sweep proxy: ssl level within 0.5R of entry, BELOW for longs)
    d_ssl = (ep - ssl) / sl  # positive = entry is above ssl
    d_bsl = (bsl - ep) / sl  # positive = entry is below bsl
    long_setup = (d_ssl > 0) & (d_ssl < 0.5)
    short_setup = (d_bsl > 0) & (d_bsl < 0.5)
    long_setup = np.where(np.isnan(d_ssl), False, long_setup)
    short_setup = np.where(np.isnan(d_bsl), False, short_setup)
    mask = (
        ((is_long & long_setup) | ((~is_long) & short_setup))
        & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    )
    t2 = t.with_columns(pl.Series('mask', mask))
    wf = walk_forward(t2, pl.col('mask'))
    return print_verdict('E11 BSL/SSL sweep + FVGC reversal (cluster proxy)', wf)


def E12_dynamic_tp(t: pl.DataFrame) -> dict:
    """Dynamic TP at first magnet — on the A+ (lag-1) cohort, compare fixed +3R
    vs scale-50%-at-first-magnet + runner +3R using available hit columns.

    Approximation: 'first magnet' = the closest direction-matched VP level
    within (0.5R, 3R). We then use the nearest interpolated hit checkpoint
    (1.0/1.5/2.0/2.5/3.0R) as the partial-take point.
    """
    n_vp = (t['ahead_poc_lag1'].to_numpy().astype(int)
            + t['ahead_vah_lag1'].to_numpy().astype(int)
            + t['ahead_val_lag1'].to_numpy().astype(int))
    is_long = t['is_long'].to_numpy()
    va_edge_dir = (is_long & t['ahead_val_lag1'].to_numpy()) | (
        (~is_long) & t['ahead_vah_lag1'].to_numpy())
    aplus = (n_vp >= 2) & va_edge_dir & t['variant_ok'].to_numpy() & t['in_window'].to_numpy()
    sub = t.filter(pl.Series('m', aplus))
    n = sub.height
    if n == 0:
        print('\n=== E12 Dynamic TP — A+ cohort empty under lag-1 VP, skipping ===')
        return {'name': 'E12 dynamic_tp', 'verdict': 'SKIP', 'reasons': ['A+ cohort empty under lag-1']}

    # For each trade compute "first magnet R-distance" = min positive R among VP levels
    rs = np.stack([
        sub['r_poc_lag1'].to_numpy(),
        sub['r_vah_lag1'].to_numpy(),
        sub['r_val_lag1'].to_numpy(),
    ], axis=1)
    rs_ahead = np.where((rs >= 0.5) & (rs <= 3.0), rs, np.inf)
    first_mag_r = rs_ahead.min(axis=1)
    # Round to nearest checkpoint (1.0, 1.5, 2.0, 2.5)
    ckpts = np.array([1.0, 1.5, 2.0, 2.5])
    nearest_ckpt = ckpts[np.argmin(np.abs(ckpts[None, :] - first_mag_r[:, None]), axis=1)]

    # Outcome at partial: hit_{ckpt}R; at runner: hit_3_0R
    def hit_for(ck):
        col = {1.0: 'hit_1_0R', 1.5: 'hit_1_5R', 2.0: 'hit_2_0R', 2.5: 'hit_2_5R'}[ck]
        return sub[col].cast(pl.Boolean).to_numpy()

    partial_hit = np.zeros(n, dtype=bool)
    for ck in ckpts:
        mask_ck = nearest_ckpt == ck
        if mask_ck.any():
            partial_hit[mask_ck] = hit_for(ck)[mask_ck]
    runner_hit = sub['hit_3_0R'].cast(pl.Boolean).to_numpy()

    # Strategy A: fixed +3R (current A+)
    # win = +3R, loss = -1R
    fixed_wr = runner_hit.mean()
    fixed_exp = 3 * fixed_wr - 1 * (1 - fixed_wr)
    # Strategy B: split 50/50 — partial at nearest_ckpt, runner to +3R
    # If partial_hit: take 0.5 * ckpt
    # If runner_hit:  take 0.5 * 3R additionally
    # If neither (i.e., didn't reach partial): -1R on full size
    partial_r = nearest_ckpt
    splitB = np.zeros(n)
    for i in range(n):
        if not partial_hit[i]:
            splitB[i] = -1.0
        else:
            splitB[i] = 0.5 * partial_r[i] + (0.5 * 3.0 if runner_hit[i] else 0.5 * -1.0)
    # Actually if partial hits but runner reverses to SL after partial, runner half loses -1R from new entry
    # That's already what the else branch reflects.

    splitB_exp = splitB.mean()
    print(f'\n=== E12 Dynamic TP on A+ cohort (n={n}, lag-1 VP) ===')
    print(f'  Fixed +3R:   WR={fixed_wr*100:.1f}%  exp={fixed_exp:+.3f}R')
    print(f'  Split 50/50 @ first magnet + runner: exp={splitB_exp:+.3f}R')
    print(f'  Delta: {splitB_exp - fixed_exp:+.3f}R per trade')
    delta = splitB_exp - fixed_exp
    return {
        'name': 'E12 dynamic_tp',
        'verdict': 'BETTER' if delta > 0 else 'WORSE',
        'reasons': [f'delta exp = {delta:+.3f}R per trade'],
        'oos_n': n, 'oos_exp_r': splitB_exp,
    }


EXPERIMENTS = {
    'E0': E0_aplus_lag1,
    'E1': E1_clean_shot,
    'E2': E2_aged_naked_vp,
    'E3': E3_cluster_persistence,
    'E4': E4_htf_weekly_vp,
    'E5': E5_vp_sweep_pivot,
    'E6': E6_level_launched,
    'E7': E7_cross_framework,
    'E8': E8_confluent_zone,
    'E9': E9_nwog_x_vp,
    'E10': E10_liquidity_only,
    'E11': E11_equal_hl_cluster,
    'E12': E12_dynamic_tp,
}


def main(argv):
    ids = argv[1:] if len(argv) > 1 else list(EXPERIMENTS.keys())
    print('Loading base frame (trades + lag-1 VP + session levels)...')
    t = base_frame()
    print(f'  trades: {t.height}')
    print(f'  cols: {len(t.columns)}\n')

    summaries = []
    for eid in ids:
        if eid not in EXPERIMENTS:
            print(f'Unknown experiment: {eid}')
            continue
        try:
            s = EXPERIMENTS[eid](t)
            s['id'] = eid
            summaries.append(s)
        except Exception as e:
            print(f'\n!! {eid} CRASHED: {type(e).__name__}: {e}')
            import traceback
            traceback.print_exc()
            summaries.append({'id': eid, 'verdict': 'ERROR', 'reasons': [str(e)]})

    # Write JSON rollup
    def _clean(d):
        return {k: (None if isinstance(v, float) and (np.isnan(v) or np.isinf(v))
                    else v) for k, v in d.items()}
    out_summaries = [_clean(s) for s in summaries]
    (OUT / 'summary.json').write_text(json.dumps(out_summaries, indent=2,
                                                  default=str))

    # Print final table
    print('\n\n' + '=' * 75)
    print(f'{"ID":<5}{"VERDICT":<10}{"OOS n":<8}{"OOS PF":<10}{"OOS WR":<10}{"exp R":<10}')
    print('-' * 75)
    for s in summaries:
        pf = s.get('oos_pf')
        wr = s.get('oos_wr')
        ex = s.get('oos_exp_r')
        pf_s = (f'{pf:.2f}' if pf and pf != float('inf') else
                'INF' if pf == float('inf') else '-')
        wr_s = f'{wr*100:.1f}%' if wr is not None else '-'
        ex_s = f'{ex:+.2f}' if ex is not None else '-'
        print(f'{s.get("id",""):<5}{s.get("verdict",""):<10}'
              f'{str(s.get("oos_n","-")):<8}{pf_s:<10}{wr_s:<10}{ex_s:<10}')
    print('=' * 75)


if __name__ == '__main__':
    main(sys.argv)
