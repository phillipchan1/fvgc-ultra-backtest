#!/usr/bin/env python3
"""Compare v0.3.2 (sweep-wick stop) vs v0.3.3 (gap-edge stop) populations.

Both populations were emitted under the same loose-default Step 1 config, so
the SET of trades should be (close to) identical — only stop_distance, target,
exit_reason, r_multiple, and pnl_pts should differ between runs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

HERE = Path(__file__).resolve().parent / 'results'

VERSIONS = {
    'v0.3.2 sweep-wick stop':       HERE / 'population_v0.3.2_sweep_stop.csv',
    'v0.3.3 gap-edge stop':         HERE / 'population_v0.3.3_gap_stop.csv',
    'v0.3.4 + running 50% sweeps':  HERE / 'population.csv',
}


def summary(df: pd.DataFrame, label: str) -> dict:
    wins = (df['r_multiple'] > 0).sum()
    losses = (df['r_multiple'] < 0).sum()
    flat = (df['r_multiple'] == 0).sum()
    wr = wins / (wins + losses) * 100 if (wins + losses) else 0
    gw = df.loc[df['r_multiple'] > 0, 'pnl_pts'].sum()
    gl = abs(df.loc[df['r_multiple'] < 0, 'pnl_pts'].sum()) or 1e-9
    return {
        'label': label,
        'n': len(df),
        'w': int(wins), 'l': int(losses), 'flat': int(flat),
        'wr': wr, 'pf': gw / gl,
        'avg_r': df['r_multiple'].mean(),
        'pnl': df['pnl_pts'].sum(),
        'avg_stop_pts': df['stop_distance_pts'].mean(),
        'median_stop_pts': df['stop_distance_pts'].median(),
        'max_stop_pts': df['stop_distance_pts'].max(),
    }


def print_summary(s: dict) -> None:
    print(f"  {s['label']:<35} N={s['n']:<4} "
          f"W/L/F={s['w']}/{s['l']}/{s['flat']:<3} "
          f"WR={s['wr']:5.1f}%  PF={s['pf']:5.2f}  "
          f"avgR={s['avg_r']:+.2f}  P&L={s['pnl']:+7.1f}pt  "
          f"stop med/max={s['median_stop_pts']:.0f}/{s['max_stop_pts']:.0f}pt")


def main():
    dfs = {label: pd.read_csv(p) for label, p in VERSIONS.items() if p.exists()}

    print("--- Overall ---")
    for label, df in dfs.items():
        print_summary(summary(df, label))

    # Pair-wise diff: v0.3.3 vs v0.3.4 (same stop logic, only difference is +50%).
    if 'v0.3.3 gap-edge stop' in dfs and 'v0.3.4 + running 50% sweeps' in dfs:
        v33 = dfs['v0.3.3 gap-edge stop']
        v34 = dfs['v0.3.4 + running 50% sweeps']
        added = len(v34) - len(v33)
        print(f"\n--- v0.3.3 -> v0.3.4: +{added} trades from running-50% sweeps ---")
        eq_only = v34[v34['sweep_level'].str.startswith('running_50pct')]
        print_summary(summary(eq_only, "  running-50% sweeps only"))

    if len(dfs) < 2:
        return
    # Per-trade match across the two stop-logic versions (cosmetic legacy comparison).
    if 'v0.3.2 sweep-wick stop' not in dfs or 'v0.3.4 + running 50% sweeps' not in dfs:
        return
    old = dfs['v0.3.2 sweep-wick stop']
    new = dfs['v0.3.4 + running 50% sweeps']
    print("\n--- Per-trade match (v0.3.2 vs v0.3.4) ---")
    merged = old.merge(
        new, on=['entry_ts', 'direction'], how='outer',
        suffixes=('_old', '_new'), indicator=True,
    )
    print(f"  matched: {(merged['_merge']=='both').sum()}")
    print(f"  only in v0.3.2: {(merged['_merge']=='left_only').sum()}")
    print(f"  only in v0.3.3: {(merged['_merge']=='right_only').sum()}")

    both = merged[merged['_merge'] == 'both'].copy()
    both['stop_delta'] = both['stop_distance_pts_new'] - both['stop_distance_pts_old']
    both['r_delta'] = both['r_multiple_new'] - both['r_multiple_old']

    print(f"\n  stop_distance: avg shrink = {-both['stop_delta'].mean():+.1f}pt "
          f"(median {-both['stop_delta'].median():+.1f}pt)")

    # Outcome flips
    def cls(r):
        if r > 0: return 'W'
        if r < 0: return 'L'
        return 'F'
    both['cls_old'] = both['r_multiple_old'].apply(cls)
    both['cls_new'] = both['r_multiple_new'].apply(cls)
    flip = both[both['cls_old'] != both['cls_new']]
    print(f"\n  Outcome changes: {len(flip)}/{len(both)}")
    print("    transitions:", flip.groupby(['cls_old', 'cls_new']).size().to_dict())

    # Exit-reason migrations
    print("\n  Exit reason shifts:")
    er = both.groupby(['exit_reason_old', 'exit_reason_new']).size().reset_index(name='n')
    er = er.sort_values('n', ascending=False)
    for _, r in er.iterrows():
        print(f"    {r['exit_reason_old']:<12} -> {r['exit_reason_new']:<12}  {r['n']}")


if __name__ == '__main__':
    main()
