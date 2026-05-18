"""Analyze the '9:30-candle FVG' sub-edge — FVGs born in 9:29:30-9:31:00 window.
Compare across timeframes."""
import pandas as pd
import datetime as dt

# Per-day confluence lookup from enriched 30s
enr = pd.read_csv('studies/mfe_multi_r/results/mfe_trades_enriched.csv')
enr['timestamp'] = pd.to_datetime(enr['timestamp'])
enr['date'] = enr['timestamp'].dt.normalize()
per_day = enr.drop_duplicates('date')[[
    'date','gap_from_prior_close','overnight_direction',
    'prior_day_close_position','candle_930_direction','has_red_folder_news'
]].copy()
per_day['confluence_count'] = (
    (per_day['gap_from_prior_close'] < -10).astype(int)
    + (per_day['gap_from_prior_close'] <= -100).astype(int)
    + (per_day['overnight_direction']=='down').astype(int)
    + (per_day['prior_day_close_position'] <= 0.333).astype(int)
    + (per_day['candle_930_direction']=='bearish').astype(int)
    + (~per_day['has_red_folder_news'].astype(bool)).astype(int)
)
conf = per_day.set_index('date')['confluence_count'].to_dict()

# The 9:30 candle window: 9:29:30 - 9:31:00
WINDOW_START = dt.time(9, 29, 30)
WINDOW_END   = dt.time(9, 31, 0)

def w1_930_fvg(df_baseline, tf_label):
    df = df_baseline.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['fvg_created_at'] = pd.to_datetime(df['fvg_created_at'], errors='coerce')
    df['date'] = df['timestamp'].dt.normalize()
    df['time'] = df['timestamp'].dt.time
    # Strip tz from fvg_created_at to compare
    if df['fvg_created_at'].dt.tz is not None:
        df['fvg_t'] = df['fvg_created_at'].dt.tz_convert('America/New_York').dt.time
    else:
        df['fvg_t'] = df['fvg_created_at'].dt.time

    # Filter: W1 short (9:30-9:45 entry), no protected_swing, FVG born in 9:29:30-9:31:00
    w1 = df[
        (df['direction']=='short')
        & (df['time'] >= dt.time(9,30)) & (df['time'] < dt.time(9,45))
        & (df['variant'] != 'protected_swing')
        & df['outcome'].isin(['win','loss'])
    ].copy()
    n_w1 = len(w1)

    sub_930 = w1[
        (w1['fvg_t'] >= WINDOW_START) & (w1['fvg_t'] <= WINDOW_END)
    ].copy()
    n_930 = len(sub_930)

    sub_930['conf'] = sub_930['date'].map(conf).fillna(-1).astype(int)
    return w1, sub_930

print(f"{'='*70}")
print("9:30-CANDLE FVG SUB-EDGE: FVGs born in 9:29:30-9:31:00 window")
print(f"{'='*70}")

months = 30
# 30s baseline FVG/trade list: use enriched (but it's missing fvg_created_at — need baseline 30s)
# Actually enriched.csv has fvg_top/bottom but not fvg_created_at. Need baseline_30s/trades.csv.
# Since that file doesn't exist, fall back to checking timeframes we have.
sources = {}
for tf in ['15s','1m','2m','3m','5m']:
    path = f'studies/baseline_{tf}/results/trades.csv'
    try:
        sources[tf] = pd.read_csv(path)
    except FileNotFoundError:
        pass

results = {}
for tf, df in sources.items():
    w1, sub = w1_930_fvg(df, tf)
    print(f"\n--- {tf} ---")
    print(f"All W1 shorts (9:30-9:45, no PS): n={len(w1)}")
    print(f"  Of which: FVG born in 9:29:30-9:31:00 window: n={len(sub)} ({len(sub)/max(len(w1),1)*100:.0f}%)")
    if len(sub) == 0:
        results[tf] = None
        continue
    wins = (sub['outcome']=='win').sum()
    losses = (sub['outcome']=='loss').sum()
    wr = wins/len(sub)*100
    pf = wins/max(losses,1)
    print(f"  9:30-FVG sub-edge: WR={wr:.1f}% PF={pf:.2f}")
    print(f"  By conf tier:")
    print(f"  {'Tier':<8} {'n':<6} {'WR':<8} {'PF':<8}")
    for c in [(0,1,'0-1'), (2,2,'2'), (3,3,'3'), (4,7,'4+')]:
        lo, hi, lbl = c
        s = sub[(sub['conf']>=lo) & (sub['conf']<=hi)]
        if len(s)==0: continue
        sw = (s['outcome']=='win').sum()
        sl = (s['outcome']=='loss').sum()
        swr = sw/len(s)*100
        spf = sw/max(sl,1)
        print(f"  {lbl:<8} {len(s):<6} {swr:<8.1f} {spf:<8.2f}")
    results[tf] = sub

# Comparison: 9:30-FVG sub-edge vs all W1 shorts at each TF
print(f"\n{'='*70}")
print("SUB-EDGE COMPARISON: 9:30-FVG cohort vs all W1 shorts")
print(f"{'='*70}")
print(f"{'TF':<6} {'all W1 n':<10} {'all WR':<8} {'930-FVG n':<10} {'930-FVG WR':<12} {'lift':<8}")
for tf, df in sources.items():
    w1, sub = w1_930_fvg(df, tf)
    if len(w1)==0: continue
    all_wr = (w1['outcome']=='win').mean()*100 if len(w1) else 0
    if len(sub):
        sub_wr = (sub['outcome']=='win').mean()*100
        lift = sub_wr - all_wr
    else:
        sub_wr = 0
        lift = 0
    print(f"{tf:<6} {len(w1):<10} {all_wr:<8.1f} {len(sub):<10} {sub_wr:<12.1f} {lift:+.1f}pp")

# Best cell summary
print(f"\n{'='*70}")
print("BEST CELL: 9:30-FVG sub-edge, 4+ conf, across timeframes")
print(f"{'='*70}")
print(f"{'TF':<6} {'n':<6} {'WR':<8} {'PF':<8} {'trades/mo':<10}")
for tf, sub in results.items():
    if sub is None or len(sub)==0: continue
    s = sub[sub['conf']>=4]
    if len(s)==0:
        print(f"{tf:<6} 0      —        —        —")
        continue
    sw = (s['outcome']=='win').sum()
    sl = (s['outcome']=='loss').sum()
    wr = sw/len(s)*100
    pf = sw/max(sl,1)
    fpm = len(s)/months
    print(f"{tf:<6} {len(s):<6} {wr:<8.1f} {pf:<8.2f} {fpm:<10.2f}")
