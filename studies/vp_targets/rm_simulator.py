"""
Risk-management simulator on the A-grade cohort.

Walks each trade forward from entry_idx through 30s bars and simulates
different stop/TP rules. Outputs PF + expectancy + WR for each rule.

Pessimistic convention: if a single bar's range covers both stop and
TP, assume stop hits first (more conservative).
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'results'

WINDOW_BARS = 540  # 30s × 540 = 4.5 hrs — covers full RTH

# --- Load ---
trades = (
    pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True)
    .filter((pl.col('outcome') != 'skip') & (pl.col('outcome') != 'ambiguous'))
)
vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)
bars = pl.read_parquet(ROOT / 'data/consolidated/nq-front-month.ohlcv-30s.parquet')

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
    (pl.col('timestamp').dt.year() >= 2023).alias('is_oos'),
])
df = trades.join(vp, on='date', how='left')

# Compute n_vp_targets + va_edge
sl_arr = df['sl_dist'].to_numpy()
is_long_arr = (df['direction'].to_numpy() == 'long')
ep_arr = df['entry_price'].to_numpy()


def rs(c):
    lvl = df[c].to_numpy().astype(float)
    diff = lvl - ep_arr
    return np.where(is_long_arr, diff, -diff) / sl_arr


def iz(r):
    with np.errstate(invalid='ignore'):
        return (r >= 0.5) & (r <= 3.0)


r_poc = rs('poc'); r_vah = rs('vah'); r_val = rs('val')
n_vp = iz(r_poc).astype(int) + iz(r_vah).astype(int) + iz(r_val).astype(int)
va_edge = np.where(is_long_arr, iz(r_val), iz(r_vah))

df = df.with_columns([pl.Series('n_vp', n_vp), pl.Series('va_edge', va_edge)])

# Filter to A-grade (n_vp>=2 + variant!=PS)
A = df.filter((pl.col('n_vp') >= 2) & (pl.col('variant') != 'protected_swing'))
A_plus = df.filter((pl.col('n_vp') >= 2) & pl.col('va_edge') & (pl.col('variant') != 'protected_swing'))
B = df.filter(pl.col('n_vp') == 1)
print(f'A-grade  cohort n = {A.height} (OOS n={A.filter(pl.col("is_oos")).height})')
print(f'A+ cell  cohort n = {A_plus.height} (OOS n={A_plus.filter(pl.col("is_oos")).height})')
print(f'B-grade  cohort n = {B.height} (OOS n={B.filter(pl.col("is_oos")).height})')

bar_high_full = bars['high'].to_numpy()
bar_low_full = bars['low'].to_numpy()
n_bars_total = len(bar_high_full)


def simulate(cohort: pl.DataFrame, rule: dict) -> dict:
    """
    rule keys:
      stop_R: initial stop in R (positive number, applied as -stop_R)
      tp_R:   single TP target (None for trail-only)
      be_trigger_R: when MFE reaches this R, move stop to 0 (None to disable)
      be_stop_R: where to move the stop after BE trigger (default 0)
      scale1_R: first scale level in R (closes scale1_size of position)
      scale1_size: fraction to close at scale1 (e.g., 0.5)
      scale1_be:   if True, move remaining stop to BE on scale1 hit
      trail_R:    if not None, runner trails this many R below the MFE peak
    """
    pnl = np.zeros(cohort.height)
    exited = np.zeros(cohort.height, dtype=bool)

    entry_idx_arr = cohort['entry_idx'].to_numpy()
    entry_px_arr  = cohort['entry_price'].to_numpy()
    sl_d          = cohort['sl_dist'].to_numpy()
    long_arr      = (cohort['direction'].to_numpy() == 'long')

    stop_R0       = rule.get('stop_R', 1.0)
    tp_R          = rule.get('tp_R', None)
    be_trig       = rule.get('be_trigger_R', None)
    be_stop_R     = rule.get('be_stop_R', 0.0)
    s1_R          = rule.get('scale1_R', None)
    s1_sz         = rule.get('scale1_size', 0.0)
    s1_be         = rule.get('scale1_be', False)
    trail_R       = rule.get('trail_R', None)

    for i in range(cohort.height):
        ei = int(entry_idx_arr[i])
        if ei + WINDOW_BARS > n_bars_total:
            end = n_bars_total
        else:
            end = ei + WINDOW_BARS
        ep = entry_px_arr[i]
        sd = sl_d[i]
        long_i = long_arr[i]

        # Convert R-levels to prices
        if long_i:
            stop_px = ep - stop_R0 * sd
            tp_px   = ep + tp_R * sd if tp_R is not None else None
        else:
            stop_px = ep + stop_R0 * sd
            tp_px   = ep - tp_R * sd if tp_R is not None else None

        # Scale state
        scaled = False
        scale_pnl_partial = 0.0
        remaining_size = 1.0

        # MFE peak for trail
        peak_R = 0.0

        for k in range(ei, end):
            h = bar_high_full[k]
            l = bar_low_full[k]

            # R-units of this bar's high and low
            if long_i:
                bar_mfe_R = (h - ep) / sd
                bar_mae_R = (ep - l) / sd  # positive means moved against
                # stop is BELOW entry by some R; check if low <= stop_px
                stop_hit = l <= stop_px
                tp_hit = (tp_px is not None) and (h >= tp_px)
                s1_hit = (s1_R is not None) and (not scaled) and (bar_mfe_R >= s1_R)
            else:
                bar_mfe_R = (ep - l) / sd
                bar_mae_R = (h - ep) / sd
                stop_hit = h >= stop_px
                tp_hit = (tp_px is not None) and (l <= tp_px)
                s1_hit = (s1_R is not None) and (not scaled) and (bar_mfe_R >= s1_R)

            # Pessimistic: stop wins same-bar collision
            if stop_hit:
                stop_R_eff = (ep - stop_px) / sd if long_i else (stop_px - ep) / sd
                pnl[i] = scale_pnl_partial + remaining_size * (-stop_R_eff)
                exited[i] = True
                break

            if tp_hit:
                pnl[i] = scale_pnl_partial + remaining_size * tp_R
                exited[i] = True
                break

            # Scale at s1: close scale1_size at s1_R, optionally move stop to BE
            if s1_hit:
                scale_pnl_partial += s1_sz * s1_R
                remaining_size = 1.0 - s1_sz
                scaled = True
                if s1_be:
                    if long_i:
                        stop_px = max(stop_px, ep)
                    else:
                        stop_px = min(stop_px, ep)

            # BE trigger
            if be_trig is not None and bar_mfe_R >= be_trig:
                if long_i:
                    new_stop = ep + be_stop_R * sd
                    stop_px = max(stop_px, new_stop)
                else:
                    new_stop = ep - be_stop_R * sd
                    stop_px = min(stop_px, new_stop)

            # Trail
            if trail_R is not None:
                peak_R = max(peak_R, bar_mfe_R)
                if peak_R >= 1.0:  # only start trailing once we're up
                    if long_i:
                        new_stop = ep + (peak_R - trail_R) * sd
                        stop_px = max(stop_px, new_stop)
                    else:
                        new_stop = ep - (peak_R - trail_R) * sd
                        stop_px = min(stop_px, new_stop)

        if not exited[i]:
            # End-of-window: exit at the close of last bar
            last_bar = end - 1
            last_close = bars['close'][last_bar]
            if long_i:
                exit_R = (last_close - ep) / sd
            else:
                exit_R = (ep - last_close) / sd
            pnl[i] = scale_pnl_partial + remaining_size * exit_R

    pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()) if (pnl < 0).any() else float('inf')
    wr = float((pnl > 0).mean())
    return {
        'n': cohort.height,
        'PF': round(pf, 2),
        'exp_R': round(float(pnl.mean()), 3),
        'WR': round(wr, 3),
        'med_R': round(float(np.median(pnl)), 3),
        'p25_R': round(float(np.percentile(pnl, 25)), 3),
        'p75_R': round(float(np.percentile(pnl, 75)), 3),
        'max_dd_R': round(_running_dd(pnl), 2),
        'max_loser_streak': _max_loser_streak(pnl),
    }


def _running_dd(pnl):
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    return float((peak - cum).max())


def _max_loser_streak(pnl):
    s = m = 0
    for r in pnl:
        if r < 0:
            s += 1
            m = max(s, m)
        else:
            s = 0
    return m


# --- Rule library ---
rules = {
    'A: -1R / +2R fixed (baseline)':           {'stop_R': 1.0, 'tp_R': 2.0},
    'B: -1R / +2.5R fixed':                    {'stop_R': 1.0, 'tp_R': 2.5},
    'C: -1R / +3R fixed':                      {'stop_R': 1.0, 'tp_R': 3.0},
    'D: -1R, BE@+1R, TP +2R':                  {'stop_R': 1.0, 'tp_R': 2.0, 'be_trigger_R': 1.0},
    'E: -1R, BE@+1R, TP +2.5R':                {'stop_R': 1.0, 'tp_R': 2.5, 'be_trigger_R': 1.0},
    'F: -1R, BE@+1R, TP +3R':                  {'stop_R': 1.0, 'tp_R': 3.0, 'be_trigger_R': 1.0},
    'G: -1R, BE@+1.5R, TP +2.5R':              {'stop_R': 1.0, 'tp_R': 2.5, 'be_trigger_R': 1.5},
    'H: -1R, scale50%@+1R+BE, TP runner +2.5R':{'stop_R': 1.0, 'tp_R': 2.5, 'scale1_R': 1.0, 'scale1_size': 0.5, 'scale1_be': True},
    'I: -1R, scale50%@+2R+BE, TP runner +3R':  {'stop_R': 1.0, 'tp_R': 3.0, 'scale1_R': 2.0, 'scale1_size': 0.5, 'scale1_be': True},
    'J: -1R, trail-1R from peak (BE@1R first)':{'stop_R': 1.0, 'tp_R': None, 'be_trigger_R': 1.0, 'trail_R': 1.0},
    'K: -1R, trail-0.5R from peak (BE@1R)':    {'stop_R': 1.0, 'tp_R': None, 'be_trigger_R': 1.0, 'trail_R': 0.5},
    'L: -1R, scale75%@+2R+BE, runner +4R':     {'stop_R': 1.0, 'tp_R': 4.0, 'scale1_R': 2.0, 'scale1_size': 0.75, 'scale1_be': True},
}

print('\n' + '=' * 100)
print('A-GRADE COHORT (n_vp>=2 & variant!=PS)  — all eras pooled')
print('=' * 100)
results_a = []
for label, rule in rules.items():
    res = simulate(A, rule)
    res['rule'] = label
    results_a.append(res)
ra = pl.DataFrame(results_a).select(['rule', 'n', 'PF', 'exp_R', 'WR', 'med_R', 'p25_R', 'p75_R', 'max_dd_R', 'max_loser_streak']).sort('exp_R', descending=True)
print(ra.to_pandas().to_string(index=False))
ra.write_csv(OUT / 'rm_sim_A.csv')

print('\n' + '=' * 100)
print('A-GRADE COHORT — OOS ONLY (2023-2026)')
print('=' * 100)
A_oos = A.filter(pl.col('is_oos'))
results_a_oos = []
for label, rule in rules.items():
    res = simulate(A_oos, rule)
    res['rule'] = label
    results_a_oos.append(res)
print(pl.DataFrame(results_a_oos).select(['rule', 'n', 'PF', 'exp_R', 'WR', 'med_R', 'p25_R', 'p75_R', 'max_dd_R', 'max_loser_streak']).sort('exp_R', descending=True).to_pandas().to_string(index=False))

print('\n' + '=' * 100)
print('A+ CELL (n_vp>=2 & VA-edge & variant!=PS)')
print('=' * 100)
results_aplus = []
for label, rule in rules.items():
    res = simulate(A_plus, rule)
    res['rule'] = label
    results_aplus.append(res)
print(pl.DataFrame(results_aplus).select(['rule', 'n', 'PF', 'exp_R', 'WR', 'med_R', 'p25_R', 'p75_R', 'max_dd_R', 'max_loser_streak']).sort('exp_R', descending=True).to_pandas().to_string(index=False))

print('\n' + '=' * 100)
print('B-GRADE COHORT (n_vp==1)')
print('=' * 100)
results_b = []
for label, rule in rules.items():
    res = simulate(B, rule)
    res['rule'] = label
    results_b.append(res)
print(pl.DataFrame(results_b).select(['rule', 'n', 'PF', 'exp_R', 'WR', 'med_R', 'p25_R', 'p75_R', 'max_dd_R', 'max_loser_streak']).sort('exp_R', descending=True).to_pandas().to_string(index=False))

print('\nDone.')
