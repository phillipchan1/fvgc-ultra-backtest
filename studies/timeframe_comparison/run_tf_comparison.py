"""Compare W1 short performance across timeframes (15s/30s/1m/2m/3m/5m).
Question: does the W1 confluence stack work the same on different signal timeframes?
If yes → more trades, same edge → bigger pot."""
import pandas as pd
import datetime as dt

# Load the 30s baseline (the original validated cohort) — has all enrichment
enr30 = pd.read_csv('studies/mfe_multi_r/results/mfe_trades_enriched.csv')
enr30['timestamp'] = pd.to_datetime(enr30['timestamp'])
enr30['date'] = enr30['timestamp'].dt.normalize()
enr30['time'] = enr30['timestamp'].dt.time

# Build a per-day confluence factor table from the 30s data
per_day = enr30.drop_duplicates('date')[[
    'date','gap_from_prior_close','overnight_direction',
    'prior_day_close_position','candle_930_direction','has_red_folder_news'
]].copy()
per_day['c_gap_down']   = (per_day['gap_from_prior_close'] < -10).astype(int)
per_day['c_large_gap']  = (per_day['gap_from_prior_close'] <= -100).astype(int)
per_day['c_on_down']    = (per_day['overnight_direction']=='down').astype(int)
per_day['c_prior_weak'] = (per_day['prior_day_close_position'] <= 0.333).astype(int)
per_day['c_bear_930']   = (per_day['candle_930_direction']=='bearish').astype(int)
per_day['c_no_news']    = (~per_day['has_red_folder_news'].astype(bool)).astype(int)
per_day['confluence_count'] = per_day[['c_gap_down','c_large_gap','c_on_down','c_prior_weak','c_bear_930','c_no_news']].sum(axis=1)
conf_lookup = per_day.set_index('date')['confluence_count'].to_dict()

# 30s data — use enriched directly
def w1_shorts_with_conf(df, label):
    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.normalize()
    df['time'] = df['timestamp'].dt.time
    w1 = df[(df['direction']=='short') & (df['time']>=dt.time(9,30)) & (df['time']<dt.time(9,45))].copy()
    w1 = w1[w1['outcome'].isin(['win','loss'])].copy()
    # Exclude protected_swing per W1 lesson
    w1 = w1[w1['variant'] != 'protected_swing']
    w1['conf'] = w1['date'].map(conf_lookup)
    w1 = w1.dropna(subset=['conf'])
    w1['conf'] = w1['conf'].astype(int)
    return w1

def summarize(w1, tf_label):
    print(f"\n{'='*70}\nTIMEFRAME: {tf_label}  (W1 shorts, 9:30-9:45, no protected_swing)\n{'='*70}")
    print(f"Total trades: {len(w1)}")
    n_days = w1['date'].nunique()
    print(f"Distinct trading days: {n_days}")
    if n_days:
        print(f"Trades per active day: {len(w1)/n_days:.2f}")
    if len(w1) == 0:
        return
    # Overall
    wr = (w1['outcome']=='win').mean()*100
    print(f"\nBaseline (all confluences): WR={wr:.1f}% n={len(w1)}")
    # By tier
    print(f"\n{'Tier':<8} {'n':<6} {'WR':<8} {'PF@1R':<8}")
    for c in [(0,1,'0-1'), (2,2,'2'), (3,3,'3'), (4,7,'4+')]:
        lo, hi, lbl = c
        sub = w1[(w1['conf']>=lo) & (w1['conf']<=hi)]
        if len(sub) == 0: continue
        wins = (sub['outcome']=='win').sum()
        losses = (sub['outcome']=='loss').sum()
        wrr = wins/len(sub)*100
        pf = wins/max(losses,1)
        print(f"{lbl:<8} {len(sub):<6} {wrr:<8.1f} {pf:<8.2f}")
    return w1

# Run each timeframe
results = {}
# 30s — use enriched (has all the cols, but we filter the same way)
results['30s'] = summarize(w1_shorts_with_conf(enr30, '30s'), '30s (validated baseline)')

for tf in ['15s','1m','2m','3m','5m']:
    path = f'studies/baseline_{tf}/results/trades.csv'
    try:
        df = pd.read_csv(path)
        results[tf] = summarize(w1_shorts_with_conf(df, tf), tf)
    except FileNotFoundError:
        print(f"\n{tf}: file not found")

# Aggregate side-by-side comparison
print(f"\n{'='*70}\nSIDE-BY-SIDE: 4+ conf tier across timeframes\n{'='*70}")
print(f"{'TF':<6} {'n':<6} {'WR':<8} {'PF@1R':<8} {'trades/mo':<10}")
months = 30  # ~30 months of data
for tf, w1 in results.items():
    if w1 is None or len(w1)==0: continue
    sub = w1[w1['conf']>=4]
    if len(sub)==0: continue
    wins = (sub['outcome']=='win').sum()
    losses = (sub['outcome']=='loss').sum()
    wr = wins/len(sub)*100
    pf = wins/max(losses,1)
    fpm = len(sub)/months
    print(f"{tf:<6} {len(sub):<6} {wr:<8.1f} {pf:<8.2f} {fpm:<10.2f}")

# Also: do the SAME days produce trades on multiple timeframes?
print(f"\n{'='*70}\nOVERLAP: do timeframes produce trades on the same days?\n{'='*70}")
# Among days where 30s has a 4+ conf trade, how many also have a trade on 1m / 15s?
days_30s = set(results['30s'][results['30s']['conf']>=4]['date'].dt.date)
for tf in ['15s','1m','2m','3m','5m']:
    if tf in results and results[tf] is not None:
        days_tf = set(results[tf][results[tf]['conf']>=4]['date'].dt.date)
        overlap = days_30s & days_tf
        only_tf = days_tf - days_30s
        only_30s = days_30s - days_tf
        print(f"{tf}: 30s∩{tf}={len(overlap)}  only 30s={len(only_30s)}  only {tf}={len(only_tf)}")
