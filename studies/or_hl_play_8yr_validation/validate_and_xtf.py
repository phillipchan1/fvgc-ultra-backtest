#!/usr/bin/env python3
"""
Steps 1 + 2 from the algo trader plan:

  1. Bootstrap + permutation tests on the 1m core play.
     - Bootstrap 10k resamples for 95% CI on PF and EV/trade.
     - Permutation null: compare core-play (neither swept) vs the full
       post-9:45 entry universe to test whether the OR-state filter adds edge.

  2. Cross-TF stability: run the same core play (entry >= 9:45, neither OR
     side swept yet) on 15s, 30s, 1m, 2m, 3m. Report PF, WR, EV/trade,
     IS/OOS split, plus stability score (|IS-OOS| / IS_EV).

Run from repo root:
  python studies/or_hl_play_8yr_validation/validate_and_xtf.py
"""

import sys
from pathlib import Path
from datetime import time as dtime, date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from fvgc.constants import NY_TZ

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

TIMEFRAMES = {
    '15s': {
        'trades':  ROOT / 'studies' / 'baseline_15s' / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-15s.parquet',
    },
    '30s': {
        'trades':  ROOT / 'studies' / 'baseline'    / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.parquet',
    },
    '1m': {
        'trades':  ROOT / 'studies' / 'baseline_1m' / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.parquet',
    },
    '2m': {
        'trades':  ROOT / 'studies' / 'baseline_2m' / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-2m.parquet',
    },
    '3m': {
        'trades':  ROOT / 'studies' / 'baseline_3m' / 'results' / 'trades.csv',
        'candles': ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-3m.parquet',
    },
}

OR_START = dtime(9, 30)
OR_END   = dtime(9, 45)
ENTRY_AFTER = dtime(9, 45)
SWEEP_WINDOW_END = dtime(11, 0)

IS_START = date(2023, 10, 1)
IS_END   = date(2025, 10, 31)


def load_candles(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=['timestamp_ny', 'open', 'high', 'low', 'close'])
    if df['timestamp_ny'].dt.tz is None:
        df['timestamp_ny'] = df['timestamp_ny'].dt.tz_localize(NY_TZ)
    return df.sort_values('timestamp_ny').reset_index(drop=True)


def compute_or_table(candles: pd.DataFrame) -> pd.DataFrame:
    df = candles.copy()
    df['date'] = df['timestamp_ny'].dt.date
    df['t']    = df['timestamp_ny'].dt.time
    or_m  = (df['t'] >= OR_START) & (df['t'] < OR_END)
    post_m = (df['t'] >= OR_END) & (df['t'] < SWEEP_WINDOW_END)
    post_grp = {d: g for d, g in df[post_m].groupby('date')}
    rows = []
    for d, or_bars in df[or_m].groupby('date'):
        orh = or_bars['high'].max()
        orl = or_bars['low'].min()
        if orh - orl <= 0: continue
        post = post_grp.get(d)
        h_t = l_t = None
        if post is not None and len(post):
            hs = post[post['high'] > orh]
            ls = post[post['low']  < orl]
            if len(hs): h_t = hs['timestamp_ny'].iloc[0]
            if len(ls): l_t = ls['timestamp_ny'].iloc[0]
        rows.append({'date': d, 'or_high': orh, 'or_low': orl,
                     'h_sweep_at': h_t, 'l_sweep_at': l_t})
    return pd.DataFrame(rows)


def prep_trades(trades_path: Path, or_df: pd.DataFrame) -> pd.DataFrame:
    trades = pd.read_csv(trades_path)
    if 'mfe_r' not in trades.columns:
        # Some baseline CSVs (15s) were written without MFE — skip silently.
        raise KeyError('mfe_r missing — re-run baseline to get MFE columns')
    trades['timestamp'] = pd.to_datetime(trades['timestamp'], utc=False)
    # baseline CSVs are written without tz; treat as NY-naive
    if trades['timestamp'].dt.tz is None:
        trades['timestamp'] = trades['timestamp'].dt.tz_localize(
            NY_TZ, ambiguous='infer', nonexistent='shift_forward')
    trades['date'] = trades['timestamp'].dt.date
    trades = trades[trades['outcome'].isin(['win', 'loss', 'eod'])]
    trades = trades[trades['timestamp'].dt.time >= ENTRY_AFTER]
    trades = trades[trades['sl_dist'].notna() & (trades['sl_dist'] > 0)]
    trades['mfe_r'] = trades['mfe_r'].fillna(0)
    trades = trades.merge(or_df, on='date', how='inner')

    long_ok  = (trades['direction'] == 'long')  & (trades['entry_price'] < trades['or_high'])
    short_ok = (trades['direction'] == 'short') & (trades['entry_price'] > trades['or_low'])
    trades = trades[long_ok | short_ok].copy()

    # 2R outcome from MFE — 1R win means MFE may or may not have reached 2R
    def _2r(row):
        if row['outcome'] == 'loss': return 'LOSS'
        if row['mfe_r'] >= 2.0:      return 'WIN'
        return 'PARTIAL'
    trades['outcome_2r'] = trades.apply(_2r, axis=1)
    trades['pnl_r_2r'] = trades['outcome_2r'].map({'WIN': 2.0, 'LOSS': -1.0, 'PARTIAL': 0.0})

    h_not = trades['h_sweep_at'].isna() | (trades['h_sweep_at'] > trades['timestamp'])
    l_not = trades['l_sweep_at'].isna() | (trades['l_sweep_at'] > trades['timestamp'])
    trades['core_play'] = h_not & l_not
    return trades.reset_index(drop=True)


def stats_2r_arr(pnl: np.ndarray) -> dict:
    n = len(pnl)
    if n == 0: return None
    wins   = int((pnl == 2.0).sum())
    losses = int((pnl == -1.0).sum())
    part   = int((pnl == 0.0).sum())
    dec = wins + losses
    wr  = wins / dec * 100 if dec else float('nan')
    pf  = (wins * 2.0 / losses) if losses else float('inf')
    ev  = pnl.sum() / n
    return {'n': n, 'wins': wins, 'losses': losses, 'partial': part,
            'wr': wr, 'pf': pf, 'ev': ev, 'sum_r': pnl.sum()}


def fmt(s):
    if s is None: return "n=0"
    pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return (f"n={s['n']:4d}  W={s['wins']:3d} L={s['losses']:3d} P={s['partial']:3d}  "
            f"WR={s['wr']:5.1f}%  PF={pf}  EV={s['ev']:+.3f}R")


# ========================================================
#  Step 1 — bootstrap + permutation tests on 1m core play
# ========================================================

def bootstrap_ci(pnl: np.ndarray, n_iter: int = 10000, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    n = len(pnl)
    pfs, evs = [], []
    for _ in range(n_iter):
        sample = rng.choice(pnl, size=n, replace=True)
        wins   = (sample == 2.0).sum()
        losses = (sample == -1.0).sum()
        pf = (wins * 2.0 / losses) if losses else float('inf')
        pfs.append(pf)
        evs.append(sample.mean())
    pfs = np.array([p for p in pfs if np.isfinite(p)])
    evs = np.array(evs)
    return {
        'pf_lo': np.quantile(pfs, 0.025), 'pf_hi': np.quantile(pfs, 0.975),
        'pf_med': np.median(pfs),
        'ev_lo': np.quantile(evs, 0.025), 'ev_hi': np.quantile(evs, 0.975),
        'ev_med': np.median(evs),
        'p_ev_le_0': (evs <= 0).mean(),
        'p_pf_le_1': (pfs <= 1.0).mean(),
    }


def permutation_vs_full(core_pnl: np.ndarray, full_pnl: np.ndarray,
                         n_iter: int = 10000, seed: int = 7) -> dict:
    """Test whether the OR-state filter adds edge above the full post-9:45
    universe.  Under H0 (filter is noise), drawing |core_pnl| samples from
    full_pnl should produce EV >= observed core EV with non-trivial probability.
    """
    rng = np.random.default_rng(seed)
    n = len(core_pnl)
    obs_ev = core_pnl.mean()
    obs_pf_num = (core_pnl == 2.0).sum() * 2.0
    obs_pf_den = (core_pnl == -1.0).sum()
    obs_pf = obs_pf_num / obs_pf_den if obs_pf_den else float('inf')

    evs_null = []
    pfs_null = []
    for _ in range(n_iter):
        s = rng.choice(full_pnl, size=n, replace=False)
        evs_null.append(s.mean())
        wins = (s == 2.0).sum()
        losses = (s == -1.0).sum()
        pf = (wins * 2.0 / losses) if losses else float('inf')
        pfs_null.append(pf)
    evs_null = np.array(evs_null)
    pfs_null = np.array([p for p in pfs_null if np.isfinite(p)])
    return {
        'obs_ev': obs_ev, 'obs_pf': obs_pf,
        'p_ev_ge_obs': (evs_null >= obs_ev).mean(),
        'p_pf_ge_obs': (pfs_null >= obs_pf).mean(),
        'null_ev_mean': evs_null.mean(),
        'null_pf_med': np.median(pfs_null),
    }


def run_step1_validation(prepped: dict):
    print(f"\n{'='*84}")
    print("  STEP 1 — Bootstrap + permutation validation (1m core play)")
    print(f"{'='*84}")
    t = prepped['1m']
    core = t[t['core_play']].copy()
    full = t.copy()
    core_pnl = core['pnl_r_2r'].to_numpy()
    full_pnl = full['pnl_r_2r'].to_numpy()

    s_core = stats_2r_arr(core_pnl)
    s_full = stats_2r_arr(full_pnl)
    print(f"\n  Core play (neither swept):  {fmt(s_core)}")
    print(f"  Full universe (post-9:45):  {fmt(s_full)}")

    print("\n  Bootstrap 10,000 resamples on core play ...")
    b = bootstrap_ci(core_pnl, n_iter=10000)
    print(f"\n  PF 95% CI: [{b['pf_lo']:.2f}, {b['pf_hi']:.2f}]  median={b['pf_med']:.2f}")
    print(f"  EV 95% CI: [{b['ev_lo']:+.3f}, {b['ev_hi']:+.3f}]R  median={b['ev_med']:+.3f}R")
    print(f"  P(EV <= 0): {b['p_ev_le_0']:.4f}    P(PF <= 1): {b['p_pf_le_1']:.4f}")

    print("\n  Permutation null vs full post-9:45 universe ...")
    p = permutation_vs_full(core_pnl, full_pnl, n_iter=10000)
    print(f"\n  Observed core EV={p['obs_ev']:+.3f}R  PF={p['obs_pf']:.2f}")
    print(f"  Null EV (mean)  ={p['null_ev_mean']:+.3f}R  null median PF={p['null_pf_med']:.2f}")
    print(f"  P(null EV >= observed) = {p['p_ev_ge_obs']:.4f}")
    print(f"  P(null PF >= observed) = {p['p_pf_ge_obs']:.4f}")

    verdict_boot = "REAL EDGE" if b['p_ev_le_0'] < 0.05 and b['pf_lo'] > 1.0 else "NOT SIGNIFICANT"
    verdict_perm = "FILTER ADDS EDGE" if p['p_ev_ge_obs'] < 0.05 else "FILTER ≈ NOISE"
    print(f"\n  Bootstrap verdict:    {verdict_boot}")
    print(f"  Permutation verdict:  {verdict_perm}")


# ========================================================
#  Step 2 — cross-TF stability
# ========================================================

def run_step2_xtf(prepped: dict):
    print(f"\n{'='*84}")
    print("  STEP 2 — Cross-timeframe stability of the core play (2R)")
    print(f"{'='*84}")
    print(f"\n  {'TF':>4s}  {'ALL':<50s}  {'IS':<50s}  {'OOS':<50s}")
    print(f"  {'─'*180}")

    summary = []
    for tf in ('15s', '30s', '1m', '2m', '3m'):
        t = prepped.get(tf)
        if t is None: continue
        core = t[t['core_play']].copy()
        if not len(core):
            print(f"  {tf:>4s}  n=0"); continue
        all_s = stats_2r_arr(core['pnl_r_2r'].to_numpy())
        is_m = (core['date'] >= IS_START) & (core['date'] <= IS_END)
        is_s = stats_2r_arr(core.loc[is_m, 'pnl_r_2r'].to_numpy())
        oos_s = stats_2r_arr(core.loc[~is_m, 'pnl_r_2r'].to_numpy())
        print(f"  {tf:>4s}  {fmt(all_s):<50s}  {fmt(is_s):<50s}  {fmt(oos_s):<50s}")

        # Stability score: smaller |IS-OOS| / max(|IS|, eps) is better
        if is_s and oos_s and is_s['ev'] != 0:
            drift = abs(is_s['ev'] - oos_s['ev']) / abs(is_s['ev'])
        else:
            drift = float('nan')
        summary.append({
            'tf': tf, 'n_all': all_s['n'],
            'pf_all': all_s['pf'], 'ev_all': all_s['ev'],
            'pf_is': is_s['pf'] if is_s else None,
            'ev_is': is_s['ev'] if is_s else None,
            'pf_oos': oos_s['pf'] if oos_s else None,
            'ev_oos': oos_s['ev'] if oos_s else None,
            'ev_drift': drift,
        })

    print(f"\n  ── Ranking by OOS PF (filter: n_oos >= 30) ──")
    print(f"  {'TF':>4s}  {'PF_OOS':>7s}  {'EV_OOS':>8s}  {'EV_ALL':>8s}  "
          f"{'drift |Δev|/|ev_is|':>20s}")
    for s in sorted(summary, key=lambda x: -(x['pf_oos'] or 0)):
        print(f"  {s['tf']:>4s}  {(s['pf_oos'] or 0):7.2f}  "
              f"{(s['ev_oos'] or 0):+8.3f}  {(s['ev_all'] or 0):+8.3f}  "
              f"{s['ev_drift']:>20.2f}")

    pd.DataFrame(summary).to_csv(RESULTS_DIR / 'xtf_stability.csv', index=False)


def main():
    print("=" * 84)
    print("  Steps 1 + 2 — Validate base play + cross-TF stability")
    print(f"  IS: {IS_START} .. {IS_END}")
    print("=" * 84)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    prepped = {}
    for tf, paths in TIMEFRAMES.items():
        if not paths['trades'].exists() or not paths['candles'].exists():
            print(f"  Skipping {tf}"); continue
        print(f"  Loading {tf} ...")
        cand = load_candles(paths['candles'])
        or_df = compute_or_table(cand)
        try:
            prepped[tf] = prep_trades(paths['trades'], or_df)
        except KeyError as e:
            print(f"    SKIP {tf}: {e}")
            del cand
            continue
        del cand
        print(f"    {len(prepped[tf]):,} post-9:45 trades  "
              f"({prepped[tf]['core_play'].sum()} core-play)")

    run_step1_validation(prepped)
    run_step2_xtf(prepped)
    print("\nDone.")


if __name__ == '__main__':
    main()
