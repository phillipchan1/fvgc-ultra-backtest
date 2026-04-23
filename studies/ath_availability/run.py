#!/usr/bin/env python3
"""
Study: ATH (All-Time High) Availability

When NQ's rolling ATH sits above the 9:30 open as an unswept liquidity target,
how often does price reach up and sweep it by 10:15? And does shorting into
that magnet degrade the W1 short playbook?

Logic:
  1. Compute per-day ATH context: rolling max high across all bars before
     that day's 9:30 open; distance from ATH to the 9:30 open; distance
     bucket; whether window scan swept the ATH and when.
  2. Post-sweep outcome: extension above ATH and retrace below ATH in the
     30 min after sweep -> classify continuation / reversal / fade.
  3. Segment existing trade lists (W1 shorts, FVGC longs) by ATH bucket and
     report WR / PF per bucket.

Run from repo root:
  python studies/ath_availability/run.py
"""

import sys
from pathlib import Path
from datetime import time as dtime, timedelta

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from fvgc.data import load_candles

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

CANDLES_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
W1_SHORTS_PATH = ROOT / 'studies' / 'mfe_multi_r' / 'results' / 'w1_short_setups' / '01_all_w1_shorts.csv'
FVGC_TRADES_PATH = ROOT / 'studies' / 'mfe_multi_r' / 'results' / 'mfe_trades_enriched.csv'

WINDOW_START = dtime(9, 30)
WINDOW_END = dtime(10, 15)
POST_SWEEP_END = dtime(10, 30)   # extra room for post-sweep outcome classification

BUCKETS = [
    ('already_above_ath', -1e9, -0.0001),   # open trading above ATH (ATH already swept overnight)
    ('lt_50',              0.0,   50.0),
    ('50_100',            50.0,  100.0),
    ('100_200',          100.0,  200.0),
    ('200_400',          200.0,  400.0),
    ('gt_400',           400.0,  1e9),
]

REVERSAL_PTS = 50.0
CONTINUATION_HOLD_MIN = 10


def bucket_for(dist_pts: float) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= dist_pts < hi:
            return name
    return 'unknown'


def compute_daily_ath_context(candles: pd.DataFrame, trading_days: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day with ATH context + sweep outcome."""
    candles = candles.sort_values('timestamp_ny').reset_index(drop=True)
    candles['date'] = candles['timestamp_ny'].dt.date
    candles['time'] = candles['timestamp_ny'].dt.time
    candles['cummax_high'] = candles['high'].cummax()

    # Index the 9:30 bar per date for O(1) lookup
    bars_930 = candles[candles['time'] == WINDOW_START]
    bars_930_by_date = {row['date']: (idx, row) for idx, row in bars_930.iterrows()}

    rows = []
    for date_str in trading_days['date']:
        date = pd.to_datetime(date_str).date()
        if date not in bars_930_by_date:
            continue
        idx_930, row_930 = bars_930_by_date[date]
        if idx_930 == 0:
            continue  # no prior history
        ath_prior = candles.loc[idx_930 - 1, 'cummax_high']
        open_930 = row_930['open']
        dist_pts = ath_prior - open_930

        # Window scan 9:30 - 10:15 (inclusive of 10:15 open)
        window_end_idx = idx_930
        while (window_end_idx + 1 < len(candles)
               and candles.loc[window_end_idx + 1, 'date'] == date
               and candles.loc[window_end_idx + 1, 'time'] <= WINDOW_END):
            window_end_idx += 1
        window = candles.iloc[idx_930:window_end_idx + 1]

        # Post-sweep window extends to 10:30
        post_end_idx = window_end_idx
        while (post_end_idx + 1 < len(candles)
               and candles.loc[post_end_idx + 1, 'date'] == date
               and candles.loc[post_end_idx + 1, 'time'] <= POST_SWEEP_END):
            post_end_idx += 1
        post_window = candles.iloc[idx_930:post_end_idx + 1]

        swept_bars = window[window['high'] >= ath_prior]
        if not swept_bars.empty:
            sweep_bar = swept_bars.iloc[0]
            sweep_time = sweep_bar['timestamp_ny']
            time_to_sweep_min = (sweep_time - row_930['timestamp_ny']).total_seconds() / 60.0
            swept = True

            # Post-sweep classification (through 10:30)
            after = post_window[post_window['timestamp_ny'] >= sweep_time]
            max_high_after = after['high'].max()
            min_low_after = after['low'].min()
            max_ext_above = max_high_after - ath_prior
            max_retrace_below = ath_prior - min_low_after
            close_at_end = post_window.iloc[-1]['close']
            close_above_end = close_at_end >= ath_prior

            # Continuation hold: 10 min after sweep, price still >= ATH
            hold_cutoff = sweep_time + timedelta(minutes=CONTINUATION_HOLD_MIN)
            hold_bar = after[after['timestamp_ny'] >= hold_cutoff]
            if not hold_bar.empty:
                sweep_hold_10m = hold_bar.iloc[0]['close'] >= ath_prior
            else:
                sweep_hold_10m = close_above_end  # ran out of data -> use end-of-window

            # Reversal: dropped 50+ pts below ATH within 30 min of sweep
            reversal_window = after[after['timestamp_ny'] <= sweep_time + timedelta(minutes=30)]
            sweep_reverse_50pts = (ath_prior - reversal_window['low'].min()) >= REVERSAL_PTS

            if sweep_reverse_50pts:
                post_sweep_class = 'reversal'
            elif close_above_end and max_ext_above >= 20:
                post_sweep_class = 'continuation'
            elif close_above_end:
                post_sweep_class = 'sweep_and_hold'
            else:
                post_sweep_class = 'fade'
        else:
            swept = False
            sweep_time = pd.NaT
            time_to_sweep_min = np.nan
            max_ext_above = np.nan
            max_retrace_below = np.nan
            close_above_end = False
            sweep_hold_10m = False
            sweep_reverse_50pts = False
            post_sweep_class = 'not_swept'

        rows.append({
            'date': date,
            'ath_prior': round(ath_prior, 2),
            'open_930': round(open_930, 2),
            'dist_pts': round(dist_pts, 2),
            'bucket': bucket_for(dist_pts),
            'window_high': round(window['high'].max(), 2),
            'window_low': round(window['low'].min(), 2),
            'swept_by_1015': swept,
            'time_to_sweep_min': round(time_to_sweep_min, 1) if swept else '',
            'sweep_time': sweep_time if swept else '',
            'max_ext_above_ath_pts': round(max_ext_above, 2) if swept else '',
            'max_retrace_below_ath_pts': round(max_retrace_below, 2) if swept else '',
            'sweep_hold_10m': sweep_hold_10m,
            'sweep_reverse_50pts': sweep_reverse_50pts,
            'post_sweep_class': post_sweep_class,
        })

    return pd.DataFrame(rows)


def summarize_base_rates(daily: pd.DataFrame) -> pd.DataFrame:
    n_total = len(daily)
    rows = []
    for name, _, _ in BUCKETS:
        sub = daily[daily['bucket'] == name]
        if len(sub) == 0:
            rows.append({
                'bucket': name, 'n_days': 0, 'pct_of_dataset': 0.0,
                'p_swept_by_1015': None, 'p_continuation': None,
                'p_reversal': None, 'p_fade': None, 'p_sweep_and_hold': None,
                'median_time_to_sweep_min': None,
            })
            continue
        swept = sub[sub['swept_by_1015']]
        rows.append({
            'bucket': name,
            'n_days': len(sub),
            'pct_of_dataset': round(len(sub) / n_total * 100, 1),
            'p_swept_by_1015': round(len(swept) / len(sub) * 100, 1),
            'p_continuation': round((sub['post_sweep_class'] == 'continuation').sum() / len(sub) * 100, 1),
            'p_sweep_and_hold': round((sub['post_sweep_class'] == 'sweep_and_hold').sum() / len(sub) * 100, 1),
            'p_reversal': round((sub['post_sweep_class'] == 'reversal').sum() / len(sub) * 100, 1),
            'p_fade': round((sub['post_sweep_class'] == 'fade').sum() / len(sub) * 100, 1),
            'median_time_to_sweep_min': round(swept['time_to_sweep_min'].astype(float).median(), 1) if len(swept) else None,
        })
    return pd.DataFrame(rows)


def segment_trades_by_ath(trades: pd.DataFrame, daily: pd.DataFrame, label: str) -> pd.DataFrame:
    """Tag trades with ATH context and return per-bucket WR stats."""
    if 'date' not in trades.columns:
        trades = trades.copy()
        trades['date'] = pd.to_datetime(trades['timestamp']).dt.date
    else:
        trades = trades.copy()
        trades['date'] = pd.to_datetime(trades['date']).dt.date

    daily_cols = ['date', 'ath_prior', 'open_930', 'dist_pts', 'bucket',
                  'swept_by_1015', 'post_sweep_class']
    merged = trades.merge(daily[daily_cols], on='date', how='left')
    return merged


def wr_stats_per_bucket(tagged: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    # overall
    rows.append(_wr_row(tagged, 'ALL', label))
    for name, _, _ in BUCKETS:
        sub = tagged[tagged['bucket'] == name]
        rows.append(_wr_row(sub, name, label))
    # composite: any ATH overhead within 200 pts
    within200 = tagged[tagged['bucket'].isin(['lt_50', '50_100', '100_200'])]
    rows.append(_wr_row(within200, 'overhead_lt_200', label))
    within400 = tagged[tagged['bucket'].isin(['lt_50', '50_100', '100_200', '200_400'])]
    rows.append(_wr_row(within400, 'overhead_lt_400', label))
    return pd.DataFrame(rows)


def _wr_row(df: pd.DataFrame, label_bucket: str, label: str) -> dict:
    if len(df) == 0:
        return {'label': label, 'bucket': label_bucket, 'n_trades': 0,
                'wins': 0, 'losses': 0, 'eod': 0, 'wr_pct': None,
                'pf': None, 'mean_mfe_r': None, 'mean_mae_r': None,
                'mfe_ge_2r_pct': None, 'mfe_ge_3r_pct': None}
    wins = (df['outcome'] == 'win').sum()
    losses = (df['outcome'] == 'loss').sum()
    eod = (df['outcome'] == 'eod').sum()
    decided = wins + losses
    wr = wins / decided * 100 if decided else None
    # PF using mfe_pts/sl_dist for wins isn't ideal; use 1R normalization:
    pf = (wins * 1.0) / (losses * 1.0) if losses else float('inf')
    mean_mfe = df['mfe_r'].mean() if 'mfe_r' in df.columns else None
    mean_mae = df['mae_r'].mean() if 'mae_r' in df.columns else None
    mfe_ge_2r = (df['mfe_r'] >= 2.0).sum() / len(df) * 100 if 'mfe_r' in df.columns else None
    mfe_ge_3r = (df['mfe_r'] >= 3.0).sum() / len(df) * 100 if 'mfe_r' in df.columns else None
    return {
        'label': label,
        'bucket': label_bucket,
        'n_trades': len(df),
        'wins': int(wins),
        'losses': int(losses),
        'eod': int(eod),
        'wr_pct': round(wr, 1) if wr is not None else None,
        'pf': round(pf, 2) if pf not in (None, float('inf')) else pf,
        'mean_mfe_r': round(mean_mfe, 2) if mean_mfe is not None else None,
        'mean_mae_r': round(mean_mae, 2) if mean_mae is not None else None,
        'mfe_ge_2r_pct': round(mfe_ge_2r, 1) if mfe_ge_2r is not None else None,
        'mfe_ge_3r_pct': round(mfe_ge_3r, 1) if mfe_ge_3r is not None else None,
    }


def post_sweep_detail(daily: pd.DataFrame) -> pd.DataFrame:
    swept = daily[daily['swept_by_1015']].copy()
    cols = ['date', 'bucket', 'ath_prior', 'open_930', 'dist_pts',
            'time_to_sweep_min', 'max_ext_above_ath_pts', 'max_retrace_below_ath_pts',
            'sweep_hold_10m', 'sweep_reverse_50pts', 'post_sweep_class']
    return swept[cols]


def print_base_rates(df: pd.DataFrame, daily: pd.DataFrame):
    print("\n" + "=" * 78)
    print("  BASE RATES — P(sweep ATH by 10:15) by distance bucket")
    print("=" * 78)
    print(f"  Total trading days analyzed: {len(daily)}")
    in_play = daily[~daily['bucket'].isin(['already_above_ath', 'gt_400'])]
    print(f"  Days with ATH in play (0-400 pts overhead): {len(in_play)} "
          f"({len(in_play)/len(daily)*100:.1f}%)")
    print(f"  {'bucket':<22s} {'n':>4s} {'pct':>6s} {'p_sweep':>8s} "
          f"{'p_cont':>7s} {'p_hold':>7s} {'p_rev':>7s} {'p_fade':>7s} {'med_min':>8s}")
    print("  " + "-" * 76)
    for _, r in df.iterrows():
        print(f"  {r['bucket']:<22s} {r['n_days']:>4d} {r['pct_of_dataset']:>5.1f}% "
              f"{_fmt_pct(r['p_swept_by_1015']):>8s} "
              f"{_fmt_pct(r['p_continuation']):>7s} "
              f"{_fmt_pct(r['p_sweep_and_hold']):>7s} "
              f"{_fmt_pct(r['p_reversal']):>7s} "
              f"{_fmt_pct(r['p_fade']):>7s} "
              f"{_fmt_num(r['median_time_to_sweep_min']):>8s}")


def _fmt_pct(v):
    return f"{v:.1f}%" if v is not None and not pd.isna(v) else '—'


def _fmt_num(v):
    return f"{v:.1f}" if v is not None and not pd.isna(v) else '—'


def print_wr_table(stats: pd.DataFrame, title: str):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)
    print(f"  {'bucket':<22s} {'n':>5s} {'W':>4s} {'L':>4s} {'EOD':>4s} "
          f"{'WR':>7s} {'mean_MFE_R':>11s} {'MFE>=2R':>8s} {'MFE>=3R':>8s}")
    print("  " + "-" * 76)
    for _, r in stats.iterrows():
        print(f"  {r['bucket']:<22s} {r['n_trades']:>5d} {r['wins']:>4d} "
              f"{r['losses']:>4d} {r['eod']:>4d} "
              f"{_fmt_pct(r['wr_pct']):>7s} "
              f"{_fmt_num(r['mean_mfe_r']):>11s} "
              f"{_fmt_pct(r['mfe_ge_2r_pct']):>8s} "
              f"{_fmt_pct(r['mfe_ge_3r_pct']):>8s}")


def main():
    print("=" * 78)
    print("  ATH AVAILABILITY STUDY")
    print("=" * 78)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n  Loading 1m candles from {CANDLES_PATH.name} ...")
    candles = load_candles(CANDLES_PATH)
    print(f"  Range: {candles['timestamp_ny'].min()} -> {candles['timestamp_ny'].max()}")

    trading_days = pd.read_csv(TRADING_DAYS_PATH)
    print(f"  {len(trading_days)} trading days in master list")

    print("\n  Computing daily ATH context ...")
    daily = compute_daily_ath_context(candles, trading_days)
    print(f"  {len(daily)} days with 1m coverage")

    daily_path = RESULTS_DIR / 'daily_ath_context.csv'
    daily.to_csv(daily_path, index=False)
    print(f"  Wrote {daily_path.name} ({len(daily)} rows)")

    base_rates = summarize_base_rates(daily)
    base_path = RESULTS_DIR / 'base_rates.csv'
    base_rates.to_csv(base_path, index=False)
    print(f"  Wrote {base_path.name}")
    print_base_rates(base_rates, daily)

    # Post-sweep detail
    post = post_sweep_detail(daily)
    post_path = RESULTS_DIR / 'post_sweep_outcomes.csv'
    post.to_csv(post_path, index=False)
    print(f"\n  Wrote {post_path.name} ({len(post)} sweep days)")
    print(f"  post_sweep_class distribution:")
    print(post['post_sweep_class'].value_counts().to_string())

    # W1 short segmentation
    print("\n  Segmenting W1 shorts by ATH context ...")
    w1 = pd.read_csv(W1_SHORTS_PATH)
    w1_tagged = segment_trades_by_ath(w1, daily, 'w1_short')
    w1_stats = wr_stats_per_bucket(w1_tagged, 'w1_short')
    w1_tagged_path = RESULTS_DIR / 'w1_shorts_by_ath.csv'
    w1_tagged.to_csv(w1_tagged_path, index=False)
    w1_stats_path = RESULTS_DIR / 'w1_shorts_stats.csv'
    w1_stats.to_csv(w1_stats_path, index=False)
    print(f"  Wrote {w1_tagged_path.name} ({len(w1_tagged)} trades), "
          f"{w1_stats_path.name}")
    print_wr_table(w1_stats, "W1 SHORTS by ATH bucket")

    # FVGC longs + shorts from mfe_trades_enriched
    print("\n  Segmenting FVGC trades by ATH context ...")
    fvgc = pd.read_csv(FVGC_TRADES_PATH)
    fvgc_tagged = segment_trades_by_ath(fvgc, daily, 'fvgc')

    longs = fvgc_tagged[fvgc_tagged['direction'] == 'long']
    shorts = fvgc_tagged[fvgc_tagged['direction'] == 'short']
    long_stats = wr_stats_per_bucket(longs, 'fvgc_long')
    short_stats = wr_stats_per_bucket(shorts, 'fvgc_short')

    fvgc_long_path = RESULTS_DIR / 'fvgc_longs_by_ath.csv'
    fvgc_short_path = RESULTS_DIR / 'fvgc_shorts_by_ath.csv'
    longs.to_csv(fvgc_long_path, index=False)
    shorts.to_csv(fvgc_short_path, index=False)
    long_stats.to_csv(RESULTS_DIR / 'fvgc_longs_stats.csv', index=False)
    short_stats.to_csv(RESULTS_DIR / 'fvgc_shorts_stats.csv', index=False)
    print(f"  Wrote fvgc_longs_by_ath.csv ({len(longs)}), fvgc_shorts_by_ath.csv ({len(shorts)})")
    print_wr_table(long_stats, "FVGC LONGS by ATH bucket")
    print_wr_table(short_stats, "FVGC SHORTS by ATH bucket")

    print("\nDone.")


if __name__ == '__main__':
    main()
