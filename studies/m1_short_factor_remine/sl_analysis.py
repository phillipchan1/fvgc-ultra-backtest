"""SL distribution + SL-bucket hit-rate analysis for M1 short (8-year)."""
import pandas as pd
from pathlib import Path

ROOT = Path('/Users/philchan/Work/fvgc-backtest')

tagged = pd.read_csv(ROOT/'studies/m1_short_factor_remine/results/trades_tagged.csv')
tagged['timestamp'] = pd.to_datetime(tagged['timestamp'])
baseline = pd.read_csv(ROOT/'studies/baseline/results/trades.csv',
    usecols=['timestamp','sl_dist','entry_price','mfe_pts','fvg_created_at'])
baseline['timestamp'] = pd.to_datetime(baseline['timestamp'])
df = tagged.merge(baseline, on='timestamp', how='left')

print(f"=== SL DISTRIBUTION (n={len(df)}) ===")
print(f"  median: {df['sl_dist'].median():.0f} pts")
print(f"  mean:   {df['sl_dist'].mean():.1f} pts")
print(f"  range:  {df['sl_dist'].min():.0f} - {df['sl_dist'].max():.0f}")
print(f"  p25/p75/p90: {df['sl_dist'].quantile(0.25):.0f} / {df['sl_dist'].quantile(0.75):.0f} / {df['sl_dist'].quantile(0.90):.0f}")

buckets = [(0,25,'<=25 tight'),(25,35,'25-35'),(35,50,'35-50'),(50,200,'>50 wide')]
print(f"\n=== EV by SL bucket × target ===")
for lo, hi, lbl in buckets:
    sub = df[(df['sl_dist']>=lo) & (df['sl_dist']<hi)]
    if len(sub)==0: continue
    avg_sl = sub['sl_dist'].mean()
    print(f"\n{lbl} (n={len(sub)}, avg SL={avg_sl:.0f}pts):")
    for tp_r, hit_col in [(1,'hit_1_0R'),(2,'hit_2_0R'),(3,'hit_3_0R'),(5,'hit_5_0R')]:
        h = sub[hit_col].mean()
        ev = h*tp_r - (1-h)
        pf = (h*tp_r)/max(1-h,1e-9)
        print(f"  TP@{tp_r}R ({avg_sl*tp_r:.0f}pts):  hit {h*100:.0f}%  EV {ev:+.2f}R  PF {pf:.2f}")
