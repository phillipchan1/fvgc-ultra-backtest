"""Answer three questions:
1. Trade count per month (M1 short, 8-year, post-veto, by confluence tier)
2. Do 1m/2m/3m timeframes hold up on 8-year data?
3. The 9:30-candle FVG sub-edge — performance on 8-year 30s data"""

import pandas as pd
import datetime as dt
from pathlib import Path

ROOT = Path('/Users/philchan/Work/fvgc-backtest')

# ============================================================
# Load + filter helpers
# ============================================================

def load_30s_trades_tagged():
    """Use the already-tagged trades from the re-mine study."""
    df = pd.read_csv(ROOT / 'studies/m1_short_factor_remine/results/trades_tagged.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.normalize()
    df['year_month'] = df['timestamp'].dt.to_period('M')
    return df


def filter_m1_short_basic(trades, days):
    """Apply M1 short filter + hard vetoes to any timeframe's baseline trades.csv."""
    trades = trades.copy()
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    trades['date'] = trades['timestamp'].dt.normalize()
    trades['time'] = trades['timestamp'].dt.time

    w1 = trades[
        (trades['direction'] == 'short')
        & (trades['time'] >= dt.time(9, 30, 0))
        & (trades['time'] < dt.time(9, 45, 0))
        & (trades['variant'] != 'protected_swing')
        & trades['outcome'].isin(['win', 'loss'])
    ].copy()

    # Apply vetoes: need vixy_low + dow_monday lookup from days
    days = days.copy()
    days['date'] = pd.to_datetime(days['date'])
    days = days.sort_values('date').reset_index(drop=True)
    days['vixy_q25_90'] = days['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.25)
    days['v_vixy_low'] = (days['vixy_prior_close'] <= days['vixy_q25_90']).astype(int)
    days['v_dow_monday'] = (days['day_of_week_name'] == 'Monday').astype(int)
    days['veto_any'] = ((days['v_vixy_low'] + days['v_dow_monday']) > 0).astype(int)

    w1 = w1.merge(days[['date', 'veto_any']], on='date', how='left')
    w1_clean = w1[w1['veto_any'] == 0].copy()
    return w1_clean


# ============================================================
# Question 1: Trade count per month
# ============================================================

def q1_monthly_cadence():
    df = load_30s_trades_tagged()
    print("=" * 72)
    print("Q1: TRADE COUNT PER MONTH (8-year, 30s, M1 short, post-veto)")
    print("=" * 72)

    # Overall
    n_total = len(df)
    months_total = df['year_month'].nunique()
    print(f"\nALL post-veto trades:")
    print(f"  Total trades: {n_total}")
    print(f"  Months covered: {months_total}")
    print(f"  Avg trades/month: {n_total/months_total:.2f}")

    # By conf tier
    print(f"\nBY CONFLUENCE TIER (new 4-factor stack):")
    print(f"  {'Tier':<8} {'Trades':<8} {'Trades/mo':<10}")
    for c_min, c_max, lbl in [(0,1,'0-1'), (2,2,'2'), (3,3,'3'), (4,7,'4+'), (2,7,'2+')]:
        sub = df[(df['conf_count']>=c_min) & (df['conf_count']<=c_max)]
        n = len(sub)
        per_mo = n / months_total
        print(f"  {lbl:<8} {n:<8} {per_mo:<10.2f}")

    # By year (year-by-year trade count)
    print(f"\nBY YEAR (post-veto):")
    df['year'] = df['timestamp'].dt.year
    yr = df.groupby('year').size().to_dict()
    months_per_year = df.groupby('year')['year_month'].nunique().to_dict()
    print(f"  {'Year':<6} {'Trades':<8} {'Months':<8} {'Trades/mo':<10}")
    for y in sorted(yr.keys()):
        n = yr[y]
        m = months_per_year[y]
        per_mo = n/m if m else 0
        print(f"  {y:<6} {n:<8} {m:<8} {per_mo:<10.2f}")


# ============================================================
# Question 2: Cross-timeframe on 8-year data
# ============================================================

def q2_cross_timeframe():
    print("\n" + "=" * 72)
    print("Q2: DO 1m / 2m / 3m TIMEFRAMES HOLD UP ON 8-YEAR DATA?")
    print("=" * 72)

    days = pd.read_csv(ROOT / 'data/trading_days/trading_days.csv')
    days['date'] = pd.to_datetime(days['date'])

    # Compute factor count per day (same 4-factor stack)
    days = days.sort_values('date').reset_index(drop=True)
    # The new 4-factor stack: prior_3d_neg, prior_day_weak, near_20d_low, made_new_5d_low_yday
    # We need rth_close history for prior_3d
    days['close'] = days['rth_close']
    days['prior_3d_close'] = days['close'].shift(3)
    days['prior_3d_neg'] = (days['close'].shift(1) < days['prior_3d_close']).astype(int)
    days['prior_day_weak'] = (days['prior_day_close_position'] <= 0.333).astype(int)
    # Near 20d low: today's open within 2% of 20-day low
    days['low_20d'] = days['rth_low'].shift(1).rolling(20, min_periods=10).min()
    # Use rth_open as proxy for today's open (close enough)
    days['near_20d_low'] = ((days['rth_open'] - days['low_20d']) / days['low_20d'] <= 0.02).astype(int)
    # Made new 5d low yesterday
    days['low_5d_prev'] = days['rth_low'].shift(2).rolling(5, min_periods=3).min()
    days['made_new_5d_low_yday'] = (days['rth_low'].shift(1) <= days['low_5d_prev']).astype(int)
    days['conf_count'] = days[['prior_3d_neg','prior_day_weak','near_20d_low','made_new_5d_low_yday']].sum(axis=1)

    # Frequency comparison
    months = 30 * 12 * 8 / 12  # ~8 years
    print(f"\n{'TF':<5} {'n_total':<8} {'n_post_veto':<12} {'WR':<8} {'2+_n':<8} {'2+_WR':<8} {'Tot/mo':<8}")
    for tf in ['30s', '1m', '2m', '3m']:
        if tf == '30s':
            # Use baseline/results (the canonical 30s)
            path = ROOT / 'studies/baseline/results/trades.csv'
        else:
            path = ROOT / f'studies/baseline_{tf}/results/trades.csv'
        if not path.exists():
            print(f"  {tf:<5} (no data)")
            continue
        raw = pd.read_csv(path)
        # Get date range first
        raw['timestamp'] = pd.to_datetime(raw['timestamp'])
        n_total = len(raw)
        # Filter
        clean = filter_m1_short_basic(raw, days)
        # Re-compute confluence count by joining with days
        clean = clean.merge(days[['date', 'conf_count']], on='date', how='left')
        clean['conf_count'] = clean['conf_count'].fillna(0).astype(int)
        n_post_veto = len(clean)
        n_months_data = clean['timestamp'].dt.to_period('M').nunique() if n_post_veto > 0 else 0
        wr = (clean['outcome']=='win').mean()*100 if n_post_veto else 0
        sub2 = clean[clean['conf_count']>=2]
        n_2plus = len(sub2)
        wr_2plus = (sub2['outcome']=='win').mean()*100 if n_2plus else 0
        per_mo = n_post_veto / max(n_months_data, 1)
        print(f"  {tf:<5} {n_total:<8} {n_post_veto:<12} {wr:<8.1f} {n_2plus:<8} {wr_2plus:<8.1f} {per_mo:<8.2f}")

    # Day overlap analysis: how many days does each TF fire that 30s doesn't?
    print(f"\nDAY OVERLAP (post-veto only):")
    tf_days = {}
    for tf in ['30s', '1m', '2m', '3m']:
        if tf == '30s':
            path = ROOT / 'studies/baseline/results/trades.csv'
        else:
            path = ROOT / f'studies/baseline_{tf}/results/trades.csv'
        if not path.exists(): continue
        raw = pd.read_csv(path)
        clean = filter_m1_short_basic(raw, days)
        tf_days[tf] = set(clean['date'].dt.date.unique())

    if '30s' in tf_days:
        d_30s = tf_days['30s']
        print(f"  30s day count: {len(d_30s)}")
        for tf in ['1m', '2m', '3m']:
            if tf not in tf_days: continue
            d_tf = tf_days[tf]
            overlap = d_30s & d_tf
            only_30s = d_30s - d_tf
            only_tf = d_tf - d_30s
            print(f"  {tf}: overlap={len(overlap)}  only 30s={len(only_30s)}  only {tf}={len(only_tf)}")


# ============================================================
# Question 3: 9:30-candle FVG sub-edge on 8-year 30s data
# ============================================================

def q3_930_fvg_subedge():
    print("\n" + "=" * 72)
    print("Q3: 9:30-CANDLE FVG SUB-EDGE (8-year 30s)")
    print("=" * 72)

    # Load full 30s baseline (has fvg_created_at column)
    raw = pd.read_csv(ROOT / 'studies/baseline/results/trades.csv')
    raw['timestamp'] = pd.to_datetime(raw['timestamp'])
    raw['fvg_created_at'] = pd.to_datetime(raw['fvg_created_at'], errors='coerce')
    raw['date'] = raw['timestamp'].dt.normalize()
    raw['time'] = raw['timestamp'].dt.time
    raw['fvg_time'] = raw['fvg_created_at'].dt.time

    # Filter to M1 short cohort
    days = pd.read_csv(ROOT / 'data/trading_days/trading_days.csv')
    days['date'] = pd.to_datetime(days['date'])
    clean = filter_m1_short_basic(raw, days)
    # Need fvg_time back
    clean = clean.merge(raw[['timestamp','fvg_time','fvg_created_at']], on='timestamp', how='left')

    n_total = len(clean)
    print(f"\nTotal post-veto M1 shorts (8-year): {n_total}")

    # 9:30 candle window: 9:29:30 to 9:31:00 (the 9:30 1m candle)
    WIN_START = dt.time(9, 29, 30)
    WIN_END = dt.time(9, 31, 0)
    sub_930 = clean[(clean['fvg_time'] >= WIN_START) & (clean['fvg_time'] <= WIN_END)].copy()
    n_930 = len(sub_930)
    print(f"Of which: FVG born in 9:29:30 - 9:31:00 window: {n_930} ({n_930/n_total*100:.0f}%)")

    if n_930 > 0:
        wr = (sub_930['outcome']=='win').mean()*100
        h1 = sub_930['hit_1_0R'].mean()*100
        h2 = sub_930['hit_2_0R'].mean()*100
        h3 = sub_930['hit_3_0R'].mean()*100
        h5 = sub_930['hit_5_0R'].mean()*100
        print(f"\n9:30-FVG sub-edge stats:")
        print(f"  WR: {wr:.1f}%  Hit 1R: {h1:.0f}%  Hit 2R: {h2:.0f}%  Hit 3R: {h3:.0f}%  Hit 5R: {h5:.0f}%")

        # EV math for TP@5R
        ev_5r = (h5/100) * 5 - (1-h5/100)*1
        pf_5r = (h5/100)*5 / max(1-h5/100, 1e-9)
        ev_1r = wr/100 - (1-wr/100)
        print(f"\n  EV strategies:")
        print(f"  TP@1R hard:    EV {ev_1r:+.2f}R, PF {wr/(100-wr):.2f}")
        print(f"  TP@5R no BE:   EV {ev_5r:+.2f}R, PF {pf_5r:.2f}")

        # By year
        sub_930['year'] = sub_930['timestamp'].dt.year
        print(f"\n  By year:")
        for y in sorted(sub_930['year'].unique()):
            yr_sub = sub_930[sub_930['year']==y]
            if len(yr_sub) < 3: continue
            yr_wr = (yr_sub['outcome']=='win').mean()*100
            yr_h5 = yr_sub['hit_5_0R'].mean()*100
            print(f"    {int(y)}: n={len(yr_sub):3d}  WR={yr_wr:.1f}%  Hit 5R={yr_h5:.0f}%")

        # Trades per month
        sub_930['ym'] = sub_930['timestamp'].dt.to_period('M')
        months_active = sub_930['ym'].nunique()
        print(f"\n  Frequency: {len(sub_930)} trades / {months_active} active months = {len(sub_930)/months_active:.2f}/month (when occurs)")
        # Distinct months across the 8-year period
        total_months = clean['timestamp'].dt.to_period('M').nunique()
        print(f"  Across full 8yr: {len(sub_930)/total_months:.2f}/month average")

    # Compare 9:30-FVG vs all-other-FVG
    print(f"\n  COMPARISON (9:30-FVG vs other-FVG):")
    other = clean[~clean.index.isin(sub_930.index)] if n_930 else clean
    for label, sub in [('9:30-FVG', sub_930), ('other-FVG', other)]:
        if len(sub) == 0: continue
        wr = (sub['outcome']=='win').mean()*100
        h2 = sub['hit_2_0R'].mean()*100 if 'hit_2_0R' in sub.columns else 0
        h5 = sub['hit_5_0R'].mean()*100 if 'hit_5_0R' in sub.columns else 0
        ev_5r = (h5/100) * 5 - (1-h5/100)*1
        print(f"    {label:<12}: n={len(sub):3d}  WR={wr:5.1f}%  Hit 2R={h2:5.1f}%  Hit 5R={h5:5.1f}%  EV@TP5R={ev_5r:+.2f}R")


if __name__ == '__main__':
    q1_monthly_cadence()
    q2_cross_timeframe()
    q3_930_fvg_subedge()
