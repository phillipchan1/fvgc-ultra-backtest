#!/usr/bin/env python3
"""Compute trade-cadence stats for each play with a trade list.

Reports median calendar-gap days, mean gap, trades/yr, trades/month.
Output is a JSON blob saved to playbook/cadence_cache.json plus
human-readable summary to stdout.
"""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PLAYS_JSON = ROOT / 'playbook' / 'plays.json'
OUT_JSON = ROOT / 'playbook' / 'cadence_cache.json'

# Per-play trade-list overrides (some plays use embedded paths under different keys)
# Each entry: (csv_path, optional tier filter, optional column for the tier filter)
EXTRA = {
    'OR H/L base (1m)': (
        ROOT / 'studies' / 'or_hl_play_8yr_validation' / 'results' / 'confluence_annotated_1m.csv',
        lambda df: df[(~df['vetoed']) & (df['conf_count'].isin([0, 1, 2]))],
    ),
    'OR H/L Tier A (1m)': (
        ROOT / 'studies' / 'or_hl_play_8yr_validation' / 'results' / 'confluence_annotated_1m.csv',
        lambda df: df[(~df['vetoed']) & (df['conf_count'] == 3)],
    ),
}


def gap_stats(df: pd.DataFrame, ts_col: str = 'timestamp') -> dict:
    if len(df) == 0:
        return {'n': 0}
    ts = pd.to_datetime(df[ts_col], utc=True, format='mixed').dt.tz_convert('America/New_York')
    s = ts.dt.normalize().sort_values()
    gaps = s.diff().dt.days.dropna()
    yr_span = (s.max() - s.min()).days / 365.25 if len(s) > 1 else 1.0
    trades_per_yr = len(df) / max(yr_span, 0.5)
    return {
        'n': int(len(df)),
        'date_min': str(s.min().date()),
        'date_max': str(s.max().date()),
        'span_yrs': round(yr_span, 1),
        'trades_per_yr': round(trades_per_yr, 1),
        'trades_per_month': round(trades_per_yr / 12, 2),
        'median_gap_days': float(gaps.median()) if len(gaps) else None,
        'mean_gap_days': round(float(gaps.mean()), 1) if len(gaps) else None,
        'p90_gap_days': float(gaps.quantile(0.9)) if len(gaps) else None,
        'max_gap_days': int(gaps.max()) if len(gaps) else None,
    }


def cadence_phrase(s: dict) -> str:
    if s.get('n', 0) == 0:
        return "no trade list available"
    med = s.get('median_gap_days')
    tpy = s.get('trades_per_yr')
    p90 = s.get('p90_gap_days')
    parts = [f"~{tpy:.0f}/yr"]
    if med is not None:
        if med < 7:
            parts.append(f"median {med:.0f}d between trades")
        elif med < 14:
            parts.append(f"~1 every {med:.0f} days (median)")
        elif med < 31:
            parts.append(f"~1 every {med:.0f} days (~{med/7:.1f} wk median)")
        else:
            parts.append(f"~1 every {med:.0f} days (~{med/30:.1f} mo median)")
    if p90 and p90 > 30:
        parts.append(f"can wait up to {p90:.0f}d (90th pct)")
    return ", ".join(parts)


def main():
    plays = json.load(open(PLAYS_JSON))
    out = {}
    for p in plays:
        name = p['name']
        tl = p.get('trade_lists', {}) or {}
        # Pick a canonical trade list per play
        # Priority order: 'all_trades', 'all_trades_30s', first available
        path_str = None
        for k in ('all_trades', 'all_trades_30s', 'aplus_trades',
                   'playbook_cell_annotated', 'playbook_cell_raw'):
            if tl.get(k):
                path_str = tl[k]; break
        if not path_str and tl:
            path_str = next(iter(tl.values()))
        if not path_str:
            print(f"  {name:60s}  (no trade_lists)")
            continue
        path = ROOT / path_str
        if not path.exists():
            print(f"  {name:60s}  MISSING {path_str}")
            continue
        try:
            df = pd.read_csv(path)
        except Exception as e:
            print(f"  {name:60s}  ERR {e}")
            continue
        # detect timestamp col
        ts_col = next((c for c in ['timestamp', 'entry_time', 'date', 'entry_date'] if c in df.columns), None)
        if not ts_col:
            print(f"  {name:60s}  no timestamp column")
            continue
        s = gap_stats(df, ts_col=ts_col)
        out[name] = s
        print(f"  {name:60s}  {cadence_phrase(s)}")

    # Extras (OR H/L breakdown)
    for label, (path, fn) in EXTRA.items():
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df = fn(df) if fn else df
        s = gap_stats(df, ts_col='timestamp')
        out[label] = s
        print(f"  [extra] {label:50s}  {cadence_phrase(s)}")

    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {OUT_JSON}")


if __name__ == '__main__':
    main()
