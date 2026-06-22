#!/usr/bin/env python3
"""
Re-mine confluences for M1 SHORT on the full 8yr ES baseline.

Cohort: short, entry 9:30-9:45 ET, variant != protected_swing, win/loss only.
  n=577 (IS=378 pre-2024, OOS=199 from 2024-01-01)

Goal: find a factor stack that hits WR ≥60% + PF ≥2.0 at fixed 1R TP, OOS.

Methodology:
  1. Build candidate factor universe — pre-market + 9:30:30 + per-trade.
     All factors causally observable BEFORE trade entry.
  2. Compute per-factor IS stats: WR/PF on vs off, Fisher exact p-value.
  3. FDR-BH correct at q=0.10. Keep significant factors with WR-lift |Δ| ≥ 5pp.
  4. Build composite score (positive lift = +1, negative lift = -1).
  5. Find best score threshold on IS.
  6. Validate on OOS WITHOUT re-tuning (no peeking).
  7. Year-by-year breakdown for stability.

Run from repo root:
  python studies/fvgc_plays_off_930_candle/run_m1_factor_mine.py
"""

import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TRADES_PATH = ROOT / 'logs' / 'baseline_trades.csv'
DAYS_PATH   = ROOT / 'data' / 'trading_days' / 'trading_days.csv'

IS_END  = pd.Timestamp('2024-01-01')   # IS:  < 2024-01-01,  OOS: >=


# -----------------------------------------------------------------------------
# Stats helpers
# -----------------------------------------------------------------------------

def trade_stats(s: pd.DataFrame) -> dict:
    if len(s) == 0:
        return dict(n=0, wr=float('nan'), pf=float('nan'), exp_r=float('nan'))
    w = (s['outcome']=='win').sum(); l = (s['outcome']=='loss').sum()
    pnl = pd.to_numeric(s['pnl'], errors='coerce'); sl = pd.to_numeric(s['sl_dist'], errors='coerce')
    r = pnl/sl
    gw = pnl[pnl>0].sum(); gl = -pnl[pnl<0].sum()
    pf = (gw/gl) if gl>0 else float('inf')
    return dict(n=len(s), wins=int(w), losses=int(l),
                wr=w/(w+l)*100 if (w+l) else float('nan'),
                pf=pf, exp_r=float(r.mean()))


def fmt(label, s):
    if s['n']==0:
        return f'  {label:55s}  n=0'
    return (f'  {label:55s}  n={s["n"]:4d}  W={s["wins"]:3d} L={s["losses"]:3d}  '
            f'WR={s["wr"]:5.1f}%  PF={s["pf"]:5.2f}  exp={s["exp_r"]:+.3f}R')


def fdr_bh(pvals: np.ndarray, q: float = 0.10) -> np.ndarray:
    """Benjamini-Hochberg FDR. Returns boolean array of survivors."""
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    thresh = q * np.arange(1, n+1) / n
    below = ranked <= thresh
    if not below.any():
        return np.zeros(n, dtype=bool)
    k = np.where(below)[0].max()
    cutoff = ranked[k]
    return pvals <= cutoff


# -----------------------------------------------------------------------------
# Compute per-day factor table (binarized, all causally observable pre-entry)
# -----------------------------------------------------------------------------

def build_day_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values('date').reset_index(drop=True).copy()
    # Rolling baselines (90d) so quartiles are causal
    d['vixy_q25_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.25)
    d['vixy_q75_90'] = d['vixy_prior_close'].rolling(90, min_periods=30).quantile(0.75)
    d['c930_body_q75_90']  = d['candle_930_body'].rolling(90, min_periods=30).quantile(0.75)
    d['c930_range_q75_90'] = d['candle_930_range'].rolling(90, min_periods=30).quantile(0.75)
    d['on_range_q75_90']   = d['overnight_range'].rolling(90, min_periods=30).quantile(0.75)
    d['on_range_q25_90']   = d['overnight_range'].rolling(90, min_periods=30).quantile(0.25)
    d['pd_atr_q75_90']     = d['prior_day_range_atr_ratio'].rolling(90, min_periods=30).quantile(0.75)
    d['pd_dchg_q75_90']    = d['prior_day_directional_changes'].rolling(90, min_periods=30).quantile(0.75)

    feats = {}
    # ---- Pre-market / overnight (known by 9:25) ----
    feats['gap_large_down']      = (d['gap_from_prior_close'] <= -100).astype(int)
    feats['gap_med_down']        = ((d['gap_from_prior_close'] <= -30) & (d['gap_from_prior_close'] > -100)).astype(int)
    feats['gap_up']              = (d['gap_from_prior_close'] >= 30).astype(int)
    feats['gap_large_up']        = (d['gap_from_prior_close'] >= 100).astype(int)
    feats['prior_day_weak']      = (d['prior_day_close_position'] <= 0.333).astype(int)
    feats['prior_day_strong']    = (d['prior_day_close_position'] >= 0.667).astype(int)
    feats['prior_day_down']      = (d['prior_day_close_vs_open_pct'] < 0).astype(int)
    feats['prior_day_atr_high']  = (d['prior_day_range_atr_ratio'] >= d['pd_atr_q75_90']).astype(int)
    feats['prior_day_choppy']    = (d['prior_day_directional_changes'] >= d['pd_dchg_q75_90']).astype(int)
    feats['on_range_high']       = (d['overnight_range'] >= d['on_range_q75_90']).astype(int)
    feats['on_range_low']        = (d['overnight_range'] <= d['on_range_q25_90']).astype(int)
    feats['on_down']             = (d['overnight_direction'] == 'down').astype(int)
    feats['on_up']               = (d['overnight_direction'] == 'up').astype(int)
    feats['vixy_high']           = (d['vixy_prior_close'] >= d['vixy_q75_90']).astype(int)
    feats['vixy_low']            = (d['vixy_prior_close'] <= d['vixy_q25_90']).astype(int)
    feats['is_fomc_week']        = d['is_fomc_week'].astype(int)
    feats['is_opex_week']        = d['is_opex_week'].astype(int)
    feats['is_quad_witching']    = d['is_quad_witching'].astype(int)
    feats['has_pre_rth_news']    = d['has_pre_rth_news'].fillna(0).astype(int) if 'has_pre_rth_news' in d else 0
    feats['dow_monday']          = (d['day_of_week_name'] == 'Monday').astype(int)
    feats['dow_tuesday']         = (d['day_of_week_name'] == 'Tuesday').astype(int)
    feats['dow_wednesday']       = (d['day_of_week_name'] == 'Wednesday').astype(int)
    feats['dow_thursday']        = (d['day_of_week_name'] == 'Thursday').astype(int)
    feats['dow_friday']          = (d['day_of_week_name'] == 'Friday').astype(int)
    feats['is_month_start']      = d['is_month_start'].astype(int)
    feats['is_month_end']        = d['is_month_end'].astype(int)
    # Prior-day-type categorical
    for ptype in ['trend_up','trend_down','range','double_distribution','reversal']:
        col = f'prior_day_type_{ptype}'
        feats[col] = (d['prior_day_type'] == ptype).astype(int)

    # ---- 9:30:30 (causal for all our M1 entries) ----
    feats['bear_930']            = (d['candle_930_direction'] == 'bearish').astype(int)
    feats['bull_930']            = (d['candle_930_direction'] == 'bullish').astype(int)
    feats['c930_body_top_q']     = (d['candle_930_body'] >= d['c930_body_q75_90']).astype(int)
    feats['c930_range_top_q']    = (d['candle_930_range'] >= d['c930_range_q75_90']).astype(int)

    fdf = pd.DataFrame(feats)
    fdf['date'] = d['date']
    return fdf


# -----------------------------------------------------------------------------
# Per-trade features (variant, sl_dist, entry-time bucket)
# -----------------------------------------------------------------------------

def add_trade_features(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t['var_no_fvg']  = (t['variant']=='no_fvg').astype(int)
    t['var_bos']     = (t['variant']=='bos').astype(int)
    t['var_ifvg']    = (t['variant']=='ifvg').astype(int)
    # SL distance buckets (rolling causality-safe? sl_dist is per-trade so known at entry)
    t['sl_tight']    = (t['sl_dist'] <= 20).astype(int)
    t['sl_medium']   = ((t['sl_dist'] > 20) & (t['sl_dist'] <= 35)).astype(int)
    t['sl_wide']     = (t['sl_dist'] > 35).astype(int)
    # Entry-time buckets
    et = t['timestamp'].dt.time
    t['et_3035'] = ((et >= dtime(9,30,30)) & (et < dtime(9,35))).astype(int)
    t['et_3540'] = ((et >= dtime(9,35)) & (et < dtime(9,40))).astype(int)
    t['et_4045'] = ((et >= dtime(9,40)) & (et < dtime(9,45))).astype(int)
    return t


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    print('='*100)
    print('M1 SHORT factor re-mine (8yr ES) — IS<2024 / OOS≥2024-01-01')
    print('='*100)

    # Load trades
    t = pd.read_csv(TRADES_PATH)
    t['timestamp'] = pd.to_datetime(t['timestamp'])
    t['date'] = t['timestamp'].dt.normalize()
    t['entry_time'] = t['timestamp'].dt.time

    m1 = t[(t['direction']=='short')
           & (t['entry_time']>=dtime(9,30)) & (t['entry_time']<dtime(9,45))
           & (t['variant']!='protected_swing')
           & t['outcome'].isin(['win','loss'])].copy()
    m1 = add_trade_features(m1)

    # Day features
    days = pd.read_csv(DAYS_PATH)
    days['date'] = pd.to_datetime(days['date'])
    dfeats = build_day_features(days)
    m1 = m1.merge(dfeats, on='date', how='left')

    is_ = m1[m1['timestamp'] < IS_END].copy()
    oos = m1[m1['timestamp'] >= IS_END].copy()
    print(f'\nIS  (<{IS_END.date()}): n={len(is_)}')
    print(f'OOS (>={IS_END.date()}): n={len(oos)}')
    print(fmt('IS baseline', trade_stats(is_)))
    print(fmt('OOS baseline', trade_stats(oos)))

    # ---- Factor list (everything binary in the dfeats + trade features) ----
    factor_cols = [
        # gap
        'gap_large_down','gap_med_down','gap_up','gap_large_up',
        # prior day
        'prior_day_weak','prior_day_strong','prior_day_down',
        'prior_day_atr_high','prior_day_choppy',
        'prior_day_type_trend_up','prior_day_type_trend_down','prior_day_type_range',
        'prior_day_type_double_distribution','prior_day_type_reversal',
        # overnight
        'on_range_high','on_range_low','on_down','on_up',
        # vix / calendar
        'vixy_high','vixy_low',
        'is_fomc_week','is_opex_week','is_quad_witching',
        'dow_monday','dow_tuesday','dow_wednesday','dow_thursday','dow_friday',
        'is_month_start','is_month_end',
        'has_pre_rth_news',
        # 9:30 candle
        'bear_930','bull_930','c930_body_top_q','c930_range_top_q',
        # per-trade
        'var_no_fvg','var_bos','var_ifvg',
        'sl_tight','sl_medium','sl_wide',
        'et_3035','et_3540','et_4045',
    ]

    # ---- Mine on IS ----
    print('\n' + '='*100)
    print('IS factor lifts (Fisher exact p, FDR-BH q=0.10)')
    print('='*100)
    rows = []
    for f in factor_cols:
        on  = is_[is_[f]==1]
        off = is_[is_[f]==0]
        if len(on) < 20 or len(off) < 20:   # tiny cells unreliable
            continue
        s_on, s_off = trade_stats(on), trade_stats(off)
        # Fisher 2x2: rows=on/off, cols=win/loss
        try:
            _, pval = fisher_exact(
                [[s_on['wins'], s_on['losses']],
                 [s_off['wins'], s_off['losses']]],
                alternative='two-sided'
            )
        except Exception:
            pval = 1.0
        rows.append({
            'factor': f,
            'n_on': s_on['n'], 'wr_on': s_on['wr'], 'pf_on': s_on['pf'], 'exp_on': s_on['exp_r'],
            'n_off': s_off['n'],'wr_off': s_off['wr'],'pf_off': s_off['pf'],
            'lift_wr': s_on['wr'] - s_off['wr'],
            'lift_pf': s_on['pf'] - s_off['pf'],
            'p_value': pval,
        })
    lift_df = pd.DataFrame(rows).sort_values('lift_wr', ascending=False)
    lift_df['fdr_survives'] = fdr_bh(lift_df['p_value'].values, q=0.10)

    with pd.option_context('display.width', 220, 'display.max_columns', 20,
                            'display.max_rows', 80, 'display.float_format', '{:.2f}'.format):
        print(lift_df[['factor','n_on','wr_on','pf_on','n_off','wr_off','pf_off',
                       'lift_wr','lift_pf','p_value','fdr_survives']].to_string(index=False))

    # ---- Pick survivors: FDR-survives AND |lift_wr| >= 5 ----
    survivors = lift_df[(lift_df['fdr_survives']) & (lift_df['lift_wr'].abs() >= 5.0)].copy()
    survivors['sign'] = np.where(survivors['lift_wr'] > 0, +1, -1)
    print('\n--- Survivors (FDR q=0.10 + |lift_wr| >= 5pp) ---')
    print(survivors[['factor','sign','lift_wr','lift_pf','n_on','wr_on','wr_off','p_value']]
            .to_string(index=False))

    if len(survivors) == 0:
        print('\nNo factors survive. Stack model = baseline. Stopping.')
        return

    # ---- Build composite score on IS, find best threshold ----
    def score_row(row, survivors):
        s = 0
        for _, fr in survivors.iterrows():
            if row[fr['factor']] == 1:
                s += int(fr['sign'])
        return s

    is_['score']  = is_.apply(lambda r: score_row(r, survivors), axis=1)
    oos['score']  = oos.apply(lambda r: score_row(r, survivors), axis=1)

    print('\n--- IS WR/PF by composite score ---')
    for s in sorted(is_['score'].unique()):
        sub = is_[is_['score']==s]
        print(fmt(f'score={s:+d}', trade_stats(sub)))

    print('\n--- IS WR/PF by score threshold (score >= X) ---')
    best_thr, best_pf, best_n = None, 0, 0
    for thr in sorted(is_['score'].unique()):
        sub = is_[is_['score']>=thr]
        st = trade_stats(sub)
        marker = ''
        if st['n'] >= 50 and st['wr'] >= 60 and st['pf'] >= 2.0:
            marker = ' ✓ meets criteria'
            if st['pf'] > best_pf:
                best_thr, best_pf, best_n = thr, st['pf'], st['n']
        print(fmt(f'  score >= {thr:+d}', st) + marker)

    if best_thr is None:
        # fallback: pick highest threshold with n>=50
        for thr in sorted(is_['score'].unique(), reverse=True):
            sub = is_[is_['score']>=thr]
            if len(sub) >= 50:
                best_thr = thr
                break

    print(f'\nSelected IS threshold: score >= {best_thr}')

    # ---- Validate OOS at chosen threshold (no peeking) ----
    print('\n' + '='*100)
    print(f'OOS VALIDATION at score >= {best_thr}')
    print('='*100)
    oos_sub = oos[oos['score']>=best_thr]
    print(fmt('OOS at chosen threshold', trade_stats(oos_sub)))
    print(fmt('OOS baseline (all)',     trade_stats(oos)))

    print('\n--- OOS WR/PF by score (for transparency) ---')
    for s in sorted(oos['score'].unique()):
        sub = oos[oos['score']==s]
        print(fmt(f'score={s:+d}', trade_stats(sub)))

    print('\n--- OOS by score threshold ---')
    for thr in sorted(oos['score'].unique()):
        sub = oos[oos['score']>=thr]
        print(fmt(f'  score >= {thr:+d}', trade_stats(sub)))

    # ---- Year-by-year on FULL sample at chosen threshold ----
    print('\n' + '='*100)
    print(f'Year-by-year (full sample) at score >= {best_thr}')
    print('='*100)
    full = pd.concat([is_, oos]).copy()
    full['year'] = full['timestamp'].dt.year
    for y, g in full.groupby('year'):
        sub = g[g['score']>=best_thr]
        if len(sub)==0:
            print(f'  {y}: n=0')
            continue
        st = trade_stats(sub)
        print(fmt(f'  {y}', st))

    # Save outputs
    OUT = Path(__file__).resolve().parent / 'results'
    OUT.mkdir(exist_ok=True)
    lift_df.to_csv(OUT/'m1_factor_lifts.csv', index=False)
    survivors.to_csv(OUT/'m1_factor_survivors.csv', index=False)
    full[['timestamp','date','variant','sl_dist','outcome','pnl','score','year'] + list(survivors['factor'])
         ].to_csv(OUT/'m1_trades_scored.csv', index=False)
    print('\nWrote:')
    print(f'  {OUT/"m1_factor_lifts.csv"}')
    print(f'  {OUT/"m1_factor_survivors.csv"}')
    print(f'  {OUT/"m1_trades_scored.csv"}')


if __name__ == '__main__':
    main()
