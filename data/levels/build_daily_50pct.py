#!/usr/bin/env python3
"""Build daily_50pct level per RTH date.

User trades from a TradingView "Dynamic Customizable 50% Line" indicator with
1-day timeframe. This is the midpoint of the prior CLOSED CME daily candle
(18:00 NY two days ago → 17:00 NY prior day). Static for the trading session.

Verified against 5/21/2026:
  prior CME day = 5/19 18:00 → 5/20 17:00, H=29397.50 L=28797.25 mid=29097.38 ✓

Output:
  data/levels/daily_50pct.csv with columns:
    date, daily_high, daily_low, daily_50pct
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from fvgc.data import load_candles

OUT = Path('data/levels/daily_50pct.csv')


def main():
    print("Loading 30s candles...")
    candles = load_candles('data/consolidated/nq-front-month.ohlcv-30s.csv')
    # Make tz-naive NY-time for easy CME-session windowing
    candles['ts'] = candles['timestamp_ny'].dt.tz_localize(None)
    candles = candles[['ts', 'high', 'low']].sort_values('ts').reset_index(drop=True)

    # All distinct NY dates with candles. The trading-day D's
    # "prior CME daily candle" runs from (D-1)@18:00 → (D-1 next bizday placeholder)...
    # Simpler: for each NY date D, prior CME daily = the most recent completed daily that
    # ended at 17:00 on the most recent trading day strictly before D. That's the daily
    # candle for the *prior trading day* (call it P), which runs P-1 @ 18:00 → P @ 17:00.
    candles['date_ny'] = candles['ts'].dt.date.astype(str)
    all_dates = sorted(candles['date_ny'].unique())
    print(f"  {len(all_dates)} dates from {all_dates[0]} to {all_dates[-1]}")

    rows = []
    for i, d in enumerate(all_dates):
        # We need the prior trading day P. We treat P as the previous date in all_dates.
        if i == 0:
            continue
        p = all_dates[i - 1]
        # CME daily for P: (P-1) @ 18:00 → P @ 17:00
        p_ts = pd.Timestamp(p)
        start = p_ts - pd.Timedelta(days=1) + pd.Timedelta(hours=18)
        end   = p_ts + pd.Timedelta(hours=17)
        seg = candles[(candles['ts'] >= start) & (candles['ts'] < end)]
        if seg.empty:
            continue
        h = float(seg['high'].max())
        l = float(seg['low'].min())
        rows.append({
            'date': d,
            'prior_cme_day': p,
            'daily_high': h,
            'daily_low': l,
            'daily_50pct': (h + l) / 2.0,
        })

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"\nWrote {len(out)} rows to {OUT}")
    print("\nSanity checks:")
    for chk in ['2026-05-21', '2026-05-20', '2026-05-13']:
        row = out[out['date'] == chk]
        if not row.empty:
            r = row.iloc[0]
            print(f"  {chk}: prior_cme={r['prior_cme_day']}  H={r['daily_high']:.2f}  L={r['daily_low']:.2f}  mid={r['daily_50pct']:.2f}")


if __name__ == '__main__':
    main()
