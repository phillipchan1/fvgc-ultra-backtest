#!/usr/bin/env python3
"""Sweep-then-FVGC confluence study.

For each entered FVGC trade, look back from entry time to 09:30 ET.
Detect whether the BSL (London swing high) was swept (bar high > price) or the
SSL (London swing low) was swept (bar low < price) within {5,10,15} minutes
prior to entry. Direction-aligned sweep:
  - SHORT trade after BSL sweep
  - LONG  trade after SSL sweep
Compute hit_2R lift IS (2018-2022) vs OOS (2023-2026) and year-by-year.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TRADES = ROOT / 'studies' / 'baseline' / 'results' / 'trades.csv'
LIQUIDITY = ROOT / 'data' / 'levels' / 'liquidity_levels.csv'
BARS = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.parquet'
RESULTS = Path(__file__).resolve().parent / 'results'
RESULTS.mkdir(parents=True, exist_ok=True)


def load_trades() -> pd.DataFrame:
    df = pd.read_csv(TRADES, parse_dates=['timestamp', 'exit_time', 'fvg_created_at'])
    df = df[df['outcome'].isin(['win', 'loss', 'ambiguous'])].copy()
    df['date'] = df['timestamp'].dt.date.astype(str)
    df['year'] = df['timestamp'].dt.year
    return df


def load_bsl_ssl() -> pd.DataFrame:
    liq = pd.read_csv(LIQUIDITY, usecols=['date', 'level_name', 'group', 'price'])
    bs = liq[liq['group'] == 'bsl_ssl'].dropna(subset=['price'])
    wide = bs.pivot_table(index='date', columns='level_name', values='price', aggfunc='first').reset_index()
    wide.columns.name = None
    return wide[['date', 'bsl_level', 'ssl_level']]


def load_bars() -> pd.DataFrame:
    bars = pd.read_parquet(BARS, columns=['timestamp_ny', 'high', 'low'])
    bars['date'] = bars['timestamp_ny'].dt.date.astype(str)
    bars['minute_of_day'] = bars['timestamp_ny'].dt.hour * 60 + bars['timestamp_ny'].dt.minute
    return bars


def compute_sweep_flags(trades: pd.DataFrame, bsl_ssl: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """For each trade, compute minutes-since-sweep for BSL & SSL. NaN if never swept since 9:30."""
    # join in BSL/SSL prices per date
    trades = trades.merge(bsl_ssl, on='date', how='left')

    # Group bars by date for fast lookup. Pre-filter to 9:30-12:00 NY (entries are mostly first 45 min, but allow buffer).
    bars_rth = bars[(bars['minute_of_day'] >= 9 * 60 + 30) & (bars['minute_of_day'] < 12 * 60)].copy()
    bars_rth['ts_naive'] = bars_rth['timestamp_ny'].dt.tz_localize(None)

    out_bsl_min = np.full(len(trades), np.nan)
    out_ssl_min = np.full(len(trades), np.nan)

    # group_by date
    grouped = bars_rth.groupby('date', sort=False)
    bars_by_date = {d: g for d, g in grouped}

    entry_ts = trades['timestamp'].dt.tz_localize(None) if trades['timestamp'].dt.tz is not None else trades['timestamp']
    trades['entry_naive'] = entry_ts

    for i, row in enumerate(trades.itertuples(index=False)):
        d = row.date
        if d not in bars_by_date:
            continue
        g = bars_by_date[d]
        entry = row.entry_naive
        # window: bars strictly before entry timestamp
        win = g[g['ts_naive'] < entry]
        if win.empty:
            continue
        # BSL sweep: high > bsl_level
        bsl = row.bsl_level
        ssl = row.ssl_level
        if pd.notna(bsl):
            mask = win['high'] > bsl
            if mask.any():
                last_ts = win.loc[mask, 'ts_naive'].iloc[-1]
                mins = (entry - last_ts).total_seconds() / 60.0
                out_bsl_min[i] = mins
        if pd.notna(ssl):
            mask = win['low'] < ssl
            if mask.any():
                last_ts = win.loc[mask, 'ts_naive'].iloc[-1]
                mins = (entry - last_ts).total_seconds() / 60.0
                out_ssl_min[i] = mins

    trades['bsl_swept_min_ago'] = out_bsl_min
    trades['ssl_swept_min_ago'] = out_ssl_min
    return trades.drop(columns=['entry_naive'])


def summarize_cell(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n == 0:
        return {'cell': label, 'n': 0, 'wr_2R': np.nan, 'wr_overall': np.nan}
    hits = df['hit_2_0R'].fillna(False).astype(bool).sum()
    wins = (df['outcome'] == 'win').sum()
    return {
        'cell': label,
        'n': int(n),
        'wr_2R': round(hits / n * 100, 2),
        'wr_overall': round(wins / n * 100, 2),
    }


def main():
    print('Loading data...')
    trades = load_trades()
    print(f'  entered trades: {len(trades):,}')
    bsl_ssl = load_bsl_ssl()
    print(f'  BSL/SSL rows: {len(bsl_ssl):,}')
    bars = load_bars()
    print(f'  30s bars: {len(bars):,}')

    print('Computing sweep flags...')
    trades = compute_sweep_flags(trades, bsl_ssl, bars)

    # Direction-aligned sweep windows
    for w in (5, 10, 15, 30):
        bsl_recent = (trades['bsl_swept_min_ago'] >= 0) & (trades['bsl_swept_min_ago'] <= w)
        ssl_recent = (trades['ssl_swept_min_ago'] >= 0) & (trades['ssl_swept_min_ago'] <= w)
        trades[f'bsl_swept_{w}m'] = bsl_recent
        trades[f'ssl_swept_{w}m'] = ssl_recent
        trades[f'sweep_aligned_{w}m'] = (
            ((trades['direction'] == 'short') & bsl_recent) |
            ((trades['direction'] == 'long') & ssl_recent)
        )

    trades.to_csv(RESULTS / 'trades_with_sweep.csv', index=False)

    # ---- Cell summaries ----
    rows = []
    overall = summarize_cell(trades, 'all_entered')
    rows.append(overall)
    for direction in ('long', 'short'):
        d = trades[trades['direction'] == direction]
        rows.append(summarize_cell(d, f'all_{direction}'))

    # Per-window sweep cells
    for w in (5, 10, 15, 30):
        col = f'sweep_aligned_{w}m'
        rows.append(summarize_cell(trades[trades[col]], f'sweep_aligned_{w}m'))
        rows.append(summarize_cell(trades[~trades[col]], f'NOT_sweep_aligned_{w}m'))
        for direction in ('long', 'short'):
            sub = trades[(trades['direction'] == direction) & trades[col]]
            rows.append(summarize_cell(sub, f'{direction}_sweep_aligned_{w}m'))
            sub2 = trades[(trades['direction'] == direction) & ~trades[col]]
            rows.append(summarize_cell(sub2, f'{direction}_NOT_sweep_aligned_{w}m'))

    overall_df = pd.DataFrame(rows)
    overall_df.to_csv(RESULTS / 'cells_overall.csv', index=False)
    print('\n--- Overall cells ---')
    print(overall_df.to_string(index=False))

    # ---- IS/OOS split ----
    is_mask = trades['year'].between(2018, 2022)
    oos_mask = trades['year'].between(2023, 2026)
    rows_split = []
    for split_name, mask in (('IS_2018_2022', is_mask), ('OOS_2023_2026', oos_mask)):
        sub = trades[mask]
        rows_split.append({'split': split_name, **summarize_cell(sub, 'all')})
        for w in (5, 10, 15, 30):
            col = f'sweep_aligned_{w}m'
            rows_split.append({'split': split_name, **summarize_cell(sub[sub[col]], f'sweep_aligned_{w}m')})
            rows_split.append({'split': split_name, **summarize_cell(sub[~sub[col]], f'NOT_sweep_aligned_{w}m')})
            for direction in ('long', 'short'):
                d_sub = sub[sub['direction'] == direction]
                rows_split.append({'split': split_name, **summarize_cell(d_sub[d_sub[col]], f'{direction}_sweep_aligned_{w}m')})
                rows_split.append({'split': split_name, **summarize_cell(d_sub[~d_sub[col]], f'{direction}_NOT_sweep_aligned_{w}m')})
    split_df = pd.DataFrame(rows_split)
    split_df.to_csv(RESULTS / 'cells_is_oos.csv', index=False)
    print('\n--- IS/OOS cells (selected) ---')
    print(split_df[split_df['cell'].str.contains('sweep_aligned')].to_string(index=False))

    # ---- Yearly stability for the best window (default 10m, evaluated post-hoc on IS) ----
    yearly_rows = []
    for w in (5, 10, 15, 30):
        col = f'sweep_aligned_{w}m'
        for y in sorted(trades['year'].unique()):
            sub = trades[trades['year'] == y]
            for direction in ('long', 'short'):
                d_sub = sub[sub['direction'] == direction]
                aligned = d_sub[d_sub[col]]
                base = d_sub
                if len(aligned) >= 5 and len(base) >= 5:
                    yearly_rows.append({
                        'year': y, 'window_min': w, 'direction': direction,
                        'n_aligned': len(aligned),
                        'wr_2R_aligned': round(aligned['hit_2_0R'].fillna(False).mean() * 100, 2),
                        'n_base': len(base),
                        'wr_2R_base': round(base['hit_2_0R'].fillna(False).mean() * 100, 2),
                        'lift_pp': round((aligned['hit_2_0R'].fillna(False).mean() - base['hit_2_0R'].fillna(False).mean()) * 100, 2),
                    })
    yearly_df = pd.DataFrame(yearly_rows)
    yearly_df.to_csv(RESULTS / 'yearly_stability.csv', index=False)

    # ---- n_vp_targets stacking (sweep_aligned_10m × n_vp_targets >= 1) ----
    vp_path = ROOT / 'data' / 'levels' / 'daily_volume_profile.csv'
    if vp_path.exists():
        vp = pd.read_csv(vp_path, parse_dates=['date'])
        vp['date'] = vp['date'].dt.date.astype(str)
        df_vp = trades.merge(vp[['date', 'poc', 'vah', 'val']], on='date', how='left')
        is_long_arr = (df_vp['direction'].to_numpy() == 'long')
        ep = df_vp['entry_price'].to_numpy()
        sl_dist = df_vp['sl_dist'].to_numpy()
        def _signed_R(level):
            diff = level - ep
            return np.where(is_long_arr, diff, -diff) / sl_dist
        def _in_zone(r):
            with np.errstate(invalid='ignore'):
                return (r >= 0.5) & (r <= 3.0)
        poc_in = _in_zone(_signed_R(df_vp['poc'].to_numpy(dtype=float)))
        vah_in = _in_zone(_signed_R(df_vp['vah'].to_numpy(dtype=float)))
        val_in = _in_zone(_signed_R(df_vp['val'].to_numpy(dtype=float)))
        df_vp['n_vp_targets'] = poc_in.astype(int) + vah_in.astype(int) + val_in.astype(int)
        df_vp['has_vp'] = df_vp['n_vp_targets'] >= 1

        stack_rows = []
        for split_name, mask in (
            ('all', pd.Series(True, index=df_vp.index)),
            ('IS_2018_2022', df_vp['year'].between(2018, 2022)),
            ('OOS_2023_2026', df_vp['year'].between(2023, 2026)),
        ):
            sub = df_vp[mask]
            for direction in ('long', 'short'):
                for sweep in (False, True):
                    for vp_flag in (False, True):
                        d = sub[(sub['direction'] == direction)
                                & (sub['sweep_aligned_10m'] == sweep)
                                & (sub['has_vp'] == vp_flag)]
                        if len(d) == 0:
                            continue
                        stack_rows.append({
                            'split': split_name, 'direction': direction,
                            'sweep_aligned_10m': sweep, 'has_vp': vp_flag,
                            'n': len(d),
                            'wr_2R': round(d['hit_2_0R'].fillna(False).mean() * 100, 2),
                        })
        stack_df = pd.DataFrame(stack_rows)
        stack_df.to_csv(RESULTS / 'sweep_x_vp.csv', index=False)
        print('\n--- sweep_aligned_10m × has_vp (n_vp_targets >= 1) ---')
        print(stack_df.to_string(index=False))

    # ---- Variant breakdown ----
    variant_rows = []
    for w in (10,):
        col = f'sweep_aligned_{w}m'
        for variant in trades['variant'].unique():
            for direction in ('long', 'short'):
                sub = trades[(trades['variant'] == variant) & (trades['direction'] == direction)]
                aligned = sub[sub[col]]
                if len(sub) == 0:
                    continue
                variant_rows.append({
                    'window_min': w, 'variant': variant, 'direction': direction,
                    'n_aligned': len(aligned),
                    'wr_2R_aligned': round(aligned['hit_2_0R'].fillna(False).mean() * 100, 2) if len(aligned) > 0 else np.nan,
                    'n_total': len(sub),
                    'wr_2R_total': round(sub['hit_2_0R'].fillna(False).mean() * 100, 2),
                    'lift_pp': round((aligned['hit_2_0R'].fillna(False).mean() - sub['hit_2_0R'].fillna(False).mean()) * 100, 2) if len(aligned) > 0 else np.nan,
                })
    variant_df = pd.DataFrame(variant_rows)
    variant_df.to_csv(RESULTS / 'variant_breakdown.csv', index=False)
    print('\n--- Variant breakdown (10m window) ---')
    print(variant_df.to_string(index=False))

    print('\nDone. Artifacts in', RESULTS)


if __name__ == '__main__':
    main()
