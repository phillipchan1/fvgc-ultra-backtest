#!/usr/bin/env python3
"""
Broad regime-confluence scan for the OR H/L play (30s, magnet-aligned).

Tests many candidate factors that could split direction × regime more
cleanly than 20d return alone. Each factor is tested for:
  - PF lift (factor TRUE vs FALSE)
  - IS/OOS robustness
  - Direction-specific lift (does it help longs more than shorts?)
  - Combined ranked summary

Factor families:
  A. Multi-window momentum: 5d, 10d, 20d, 60d NQ return
  B. ATR-normalized momentum (return / 20d ATR)
  C. Gap factors: gap_up, gap_down, gap size buckets
  D. Prior-day factors: close position (top/mid/bot), type, range/ATR
  E. 9:30 candle factors: direction, body size (intraday, knowable by 9:31)
  F. 5min FVG counts (intraday, knowable by 9:35)
  G. Calendar: dow, FOMC, opex, news flags
  H. VIX regime
  I. (later) Number of structural targets within 100pt — needs trades_with_levels
"""

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
IS_START = date(2023, 10, 1); IS_END = date(2025, 10, 31)


def load_trades_with_factors() -> pd.DataFrame:
    df = pd.read_csv(RESULTS_DIR / 'magnet_aligned_30s.csv')
    df = df[df['magnet']=='aligned']
    df = df[df['or_range']<=150]
    df = df[df['variant']!='ifvg']
    df = df[df['outcome'].isin(['win','loss','eod'])]
    df['date'] = pd.to_datetime(df['date']).dt.date
    df['pnl_r'] = df['outcome_2r'].map({'WIN': 2.0, 'LOSS': -1.0, 'PARTIAL': 0.0})

    # 1m candles for daily closes (for multi-window returns + ATR)
    cand = pd.read_parquet(ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-1m.parquet',
                            columns=['timestamp_ny','close','high','low'])
    cand['date'] = cand['timestamp_ny'].dt.date
    daily = cand.groupby('date').agg(close=('close','last'), high=('high','max'),
                                       low=('low','min')).sort_index()
    daily['tr'] = pd.concat([
        daily['high'] - daily['low'],
        (daily['high'] - daily['close'].shift()).abs(),
        (daily['low']  - daily['close'].shift()).abs(),
    ], axis=1).max(axis=1)
    daily['atr20'] = daily['tr'].rolling(20).mean()

    daily['ret_5d']  = daily['close'].pct_change(5) * 100
    daily['ret_10d'] = daily['close'].pct_change(10) * 100
    daily['ret_20d'] = daily['close'].pct_change(20) * 100
    daily['ret_60d'] = daily['close'].pct_change(60) * 100
    daily['ret_20d_atr_norm'] = daily['ret_20d'] / (daily['atr20'] / daily['close'] * 100)
    # distance from 20d high/low
    daily['pct_from_20d_high'] = (daily['close'] - daily['close'].rolling(20).max()) / daily['close'] * 100
    daily['pct_from_20d_low']  = (daily['close'] - daily['close'].rolling(20).min()) / daily['close'] * 100

    for col in ['ret_5d', 'ret_10d', 'ret_20d', 'ret_60d', 'ret_20d_atr_norm',
                 'pct_from_20d_high', 'pct_from_20d_low', 'atr20']:
        df[col] = df['date'].map(daily[col].to_dict())

    # trading_days.csv pre-open factors
    td = pd.read_csv(ROOT / 'data' / 'trading_days' / 'trading_days.csv')
    td['date'] = pd.to_datetime(td['date']).dt.date
    # join key columns
    keep_cols = ['date', 'gap_from_prior_close_pct', 'prior_day_close_position',
                  'prior_day_type', 'prior_day_range_atr_ratio',
                  'candle_930_direction', 'candle_930_body',
                  'fvgs_first_5min', 'fvgs_first_5min_bullish', 'fvgs_first_5min_bearish',
                  'vixy_regime', 'has_pre_rth_news', 'has_red_folder_news',
                  'is_fomc_week', 'is_opex_week',
                  'overnight_direction',
                  'day_of_week_name']
    keep_cols = [c for c in keep_cols if c in td.columns]
    df = df.merge(td[keep_cols], on='date', how='left')
    return df


def stat(d):
    n=len(d)
    if n==0: return None
    w=(d['outcome_2r']=='WIN').sum();l=(d['outcome_2r']=='LOSS').sum()
    p=(d['outcome_2r']=='PARTIAL').sum()
    pf = w*2/l if l else float('inf')
    ev = d['pnl_r'].sum()/n
    return {'n':n, 'w':int(w), 'l':int(l), 'pf':pf, 'ev':ev}


def fmt(s):
    if s is None: return "n=0"
    pf = f"{s['pf']:5.2f}" if s['pf'] != float('inf') else "  inf"
    return f"n={s['n']:4d}  PF={pf}  EV={s['ev']:+.3f}R"


def report_factor(df: pd.DataFrame, label: str, mask: pd.Series, also_split_direction: bool = True):
    """Print PF inside/outside, IS/OOS, and direction split."""
    is_m = (df['date'] >= IS_START) & (df['date'] <= IS_END)
    inside  = df[mask]
    outside = df[~mask]
    s_in_all  = stat(inside);  s_out_all = stat(outside)
    s_in_is   = stat(inside[is_m.reindex(inside.index, fill_value=False)])
    s_in_oos  = stat(inside[~is_m.reindex(inside.index, fill_value=False)])
    s_out_is  = stat(outside[is_m.reindex(outside.index, fill_value=False)])
    s_out_oos = stat(outside[~is_m.reindex(outside.index, fill_value=False)])

    if not s_in_all or not s_out_all: return None
    if s_in_all['n'] < 40 or s_out_all['n'] < 40: return None

    lift = (s_in_all['pf'] - s_out_all['pf']) if (s_in_all['pf'] != float('inf') and s_out_all['pf'] != float('inf')) else 0

    # IS/OOS lift consistency check
    is_lift  = (s_in_is['pf']  - s_out_is['pf'])  if s_in_is  and s_out_is  and s_in_is['pf']!=float('inf')  and s_out_is['pf']!=float('inf')  else 0
    oos_lift = (s_in_oos['pf'] - s_out_oos['pf']) if s_in_oos and s_out_oos and s_in_oos['pf']!=float('inf') and s_out_oos['pf']!=float('inf') else 0

    robust = is_lift > 0.1 and oos_lift > 0.1
    flag = "★★★ ROBUST" if robust and lift > 0.3 else ("✓ HELPS" if lift > 0.2 else ("≈ flat" if abs(lift) <= 0.2 else "✗ HURTS"))

    print(f"\n  {label}")
    print(f"    IN:  {fmt(s_in_all)}    IS: {fmt(s_in_is)}    OOS: {fmt(s_in_oos)}")
    print(f"    OUT: {fmt(s_out_all)}    IS: {fmt(s_out_is)}    OOS: {fmt(s_out_oos)}")
    print(f"    LIFT (ALL/IS/OOS): {lift:+.2f} / {is_lift:+.2f} / {oos_lift:+.2f}    {flag}")

    # Direction interaction
    if also_split_direction:
        for dirn in ('long', 'short'):
            sub_in = inside[inside['direction']==dirn]
            sub_out = outside[outside['direction']==dirn]
            if len(sub_in) >= 25 and len(sub_out) >= 25:
                si = stat(sub_in); so = stat(sub_out)
                dlift = si['pf'] - so['pf'] if si and so and si['pf']!=float('inf') and so['pf']!=float('inf') else 0
                print(f"      {dirn:5s} IN: {fmt(si):40s}  OUT: {fmt(so):40s}  Δ {dlift:+.2f}")

    return {'label': label, 'lift_all': lift, 'lift_is': is_lift, 'lift_oos': oos_lift,
            'n_in': s_in_all['n'], 'robust': robust, 'pf_in': s_in_all['pf'],
            'pf_out': s_out_all['pf'], 'oos_pf_in': s_in_oos['pf'] if s_in_oos else None}


def main():
    df = load_trades_with_factors()
    print(f"Universe: 30s magnet-aligned with kill switches = {len(df)} trades")
    print(f"IS: {((df['date']>=IS_START)&(df['date']<=IS_END)).sum()}    OOS: {((df['date']<IS_START)|(df['date']>IS_END)).sum()}")

    rows = []

    # ── A. Multi-window momentum ──
    print(f"\n\n{'='*80}\n  A. MULTI-WINDOW MOMENTUM (return direction × magnitude)\n{'='*80}")
    for col, thresh, label in [
        ('ret_5d',  1.0, '5d return > +1%'),
        ('ret_5d', -1.0, '5d return < -1%'),
        ('ret_10d', 2.0, '10d return > +2%'),
        ('ret_10d',-2.0, '10d return < -2%'),
        ('ret_20d', 2.0, '20d return > +2% (Bull20)'),
        ('ret_20d',-2.0, '20d return < -2% (Bear20)'),
        ('ret_60d', 5.0, '60d return > +5%'),
        ('ret_60d',-5.0, '60d return < -5%'),
        ('ret_20d_atr_norm', 1.0, '20d return > +1.0 ATR (strong bull move)'),
        ('ret_20d_atr_norm',-1.0, '20d return < -1.0 ATR (strong bear move)'),
        ('pct_from_20d_high', -1.0, 'Within 1% of 20d high'),
        ('pct_from_20d_low', 1.0, 'Within 1% of 20d low'),
    ]:
        if thresh > 0:
            if 'low' in label.lower() or 'within' in label.lower() and '20d low' in label.lower():
                mask = df[col] <= thresh
            else:
                mask = df[col] > thresh
        else:
            if 'high' in label.lower():
                mask = df[col] >= thresh
            else:
                mask = df[col] < thresh
        r = report_factor(df, label, mask)
        if r: rows.append(r)

    # ── C. Gap factors ──
    print(f"\n\n{'='*80}\n  C. GAP FACTORS (pre-open)\n{'='*80}")
    for thresh, label in [
        (0.3, 'Gap > +0.3% (gap up)'),
        (-0.3, 'Gap < -0.3% (gap down)'),
        (0.5, 'Gap > +0.5% (large gap up)'),
        (-0.5, 'Gap < -0.5% (large gap down)'),
    ]:
        if thresh > 0:
            mask = df['gap_from_prior_close_pct'] > thresh
        else:
            mask = df['gap_from_prior_close_pct'] < thresh
        r = report_factor(df, label, mask)
        if r: rows.append(r)

    # ── D. Prior-day factors ──
    print(f"\n\n{'='*80}\n  D. PRIOR-DAY FACTORS\n{'='*80}")
    if 'prior_day_close_position' in df.columns:
        for pos, label in [('top','Prior day close in TOP third'),
                            ('middle','Prior day close in MIDDLE third'),
                            ('bottom','Prior day close in BOTTOM third')]:
            mask = df['prior_day_close_position'] == pos
            r = report_factor(df, label, mask)
            if r: rows.append(r)
    if 'prior_day_type' in df.columns:
        for typ in df['prior_day_type'].dropna().unique()[:6]:
            mask = df['prior_day_type'] == typ
            r = report_factor(df, f'Prior day type = {typ}', mask)
            if r: rows.append(r)

    # ── E. 9:30 candle (intraday, knowable by 9:31) ──
    print(f"\n\n{'='*80}\n  E. 9:30 CANDLE (intraday, knowable by 9:31)\n{'='*80}")
    if 'candle_930_direction' in df.columns:
        for dirn in ('bullish','bearish'):
            mask = df['candle_930_direction'] == dirn
            r = report_factor(df, f'9:30 candle = {dirn}', mask)
            if r: rows.append(r)

    # ── F. 5min FVGs (intraday, knowable by 9:35) ──
    print(f"\n\n{'='*80}\n  F. 5min FVG COUNT (intraday, knowable by 9:35)\n{'='*80}")
    if 'fvgs_first_5min' in df.columns:
        for op, val, label in [
            ('==', 0, 'NO FVGs in first 5min'),
            ('>=', 1, '≥1 FVG in first 5min'),
            ('>=', 2, '≥2 FVGs in first 5min'),
            ('>=', 3, '≥3 FVGs in first 5min'),
        ]:
            mask = df['fvgs_first_5min'] == val if op == '==' else df['fvgs_first_5min'] >= val
            r = report_factor(df, label, mask)
            if r: rows.append(r)
    if 'fvgs_first_5min_bullish' in df.columns:
        r = report_factor(df, '≥1 BULLISH FVG in first 5min', df['fvgs_first_5min_bullish'] >= 1)
        if r: rows.append(r)
        r = report_factor(df, '≥1 BEARISH FVG in first 5min', df['fvgs_first_5min_bearish'] >= 1)
        if r: rows.append(r)

    # ── G. Calendar ──
    print(f"\n\n{'='*80}\n  G. CALENDAR\n{'='*80}")
    if 'day_of_week_name' in df.columns:
        for dow in ['Monday','Tuesday','Wednesday','Thursday','Friday']:
            mask = df['day_of_week_name'] == dow
            r = report_factor(df, f'Day = {dow}', mask, also_split_direction=False)
            if r: rows.append(r)
    if 'is_fomc_week' in df.columns:
        r = report_factor(df, 'FOMC week', df['is_fomc_week']==True)
        if r: rows.append(r)
    if 'is_opex_week' in df.columns:
        r = report_factor(df, 'OpEx week', df['is_opex_week']==True)
        if r: rows.append(r)
    if 'has_pre_rth_news' in df.columns:
        r = report_factor(df, 'has_pre_rth_news', df['has_pre_rth_news']==True)
        if r: rows.append(r)

    # ── H. VIX regime ──
    print(f"\n\n{'='*80}\n  H. VIX REGIME\n{'='*80}")
    if 'vixy_regime' in df.columns:
        for reg in df['vixy_regime'].dropna().unique():
            mask = df['vixy_regime'] == reg
            r = report_factor(df, f'VIX regime = {reg}', mask)
            if r: rows.append(r)

    # ── I. Overnight direction ──
    if 'overnight_direction' in df.columns:
        print(f"\n\n{'='*80}\n  I. OVERNIGHT DIRECTION\n{'='*80}")
        for dirn in df['overnight_direction'].dropna().unique():
            mask = df['overnight_direction'] == dirn
            r = report_factor(df, f'Overnight = {dirn}', mask)
            if r: rows.append(r)

    # ── Final ranked summary ──
    print(f"\n\n{'='*80}\n  RANKED SUMMARY — robust factors only (IS lift > +0.1 AND OOS lift > +0.1)\n{'='*80}")
    rows_df = pd.DataFrame(rows).sort_values('lift_all', ascending=False)
    robust = rows_df[rows_df['robust']]
    print(f"\n  Found {len(robust)} robust factors out of {len(rows_df)} tested.\n")
    print(f"  {'Factor':<45s} {'PF_IN':>8s} {'OOS PF':>8s} {'LIFT':>8s} {'n':>5s}")
    print(f"  {'─'*85}")
    for _, r in robust.iterrows():
        pf_in_s = f"{r['pf_in']:.2f}" if r['pf_in'] != float('inf') else "inf"
        oos_s = f"{r['oos_pf_in']:.2f}" if r['oos_pf_in'] is not None and r['oos_pf_in'] != float('inf') else "—"
        print(f"  {r['label'][:44]:<45s} {pf_in_s:>8s} {oos_s:>8s} {r['lift_all']:+8.2f} {r['n_in']:>5d}")

    rows_df.to_csv(RESULTS_DIR / 'regime_confluence_scan.csv', index=False)
    print(f"\n  Wrote results/regime_confluence_scan.csv")


if __name__ == '__main__':
    main()
