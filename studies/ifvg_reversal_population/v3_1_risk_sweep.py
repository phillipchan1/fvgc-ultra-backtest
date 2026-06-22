#!/usr/bin/env python3
"""v3.1 — Risk management sweep on validated entry filter.

Holds the v3.1 entry filter constant (regime+direction-aware confluence with
anti-pattern hard skips) and sweeps:
  - Trim ladder fractions
  - TP R-multiples
  - Optional BE trail / tighter soft stop

Goal: find the trim ladder × R-target combo that pushes OOS PF higher on
v3.1 high-score subsets. Previous v2 best: 25/25/50 @ 1/4/8R → OOS PF 1.74.

Tests entry filters:
  - v3.1 SHORT score >= 4 (the validated significant tier)
  - v3.1 LONG score >= 5
  - v3.1 LONG score >= 6 (tighter)
  - v3.1 LONG score >= 7 (A+)
  - v3.1 COMBINED score >= 5

Each combo runs IS + OOS. Output: ranked grid.
"""

import sys
import time
from dataclasses import dataclass
from datetime import time as dtime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
OUT_CSV = Path('studies/ifvg_reversal_population/results/v3_1_risk_sweep.csv')

_EOD = dtime(16, 0)
HARD_STOP_BUFFER = 2.0
OOS_START = '2025-05-17'


@dataclass
class RiskConfig:
    name: str
    tp1_r: float = 1.0
    tp2_r: float = 2.0
    tp3_r: Optional[float] = 5.0
    trim_tp1: float = 1/3
    trim_tp2: float = 1/3
    trim_tp3: float = 1/3
    be_trail_after_tp1: bool = False
    require_body_for_soft_stop: bool = False

    @property
    def label(self) -> str:
        if self.tp3_r is None:
            tps = f"{self.tp1_r:g}/{self.tp2_r:g}/let"
        else:
            tps = f"{self.tp1_r:g}/{self.tp2_r:g}/{self.tp3_r:g}"
        trims = f"{int(self.trim_tp1*100)}/{int(self.trim_tp2*100)}/{int(self.trim_tp3*100)}"
        flags = []
        if self.be_trail_after_tp1: flags.append("BE")
        if self.require_body_for_soft_stop: flags.append("body")
        flag_str = "+" + "+".join(flags) if flags else ""
        return f"{trims} @ {tps}R{flag_str}"


def simulate(row, day_candles, cfg: RiskConfig):
    direction = row['direction']
    entry = row['entry_price']
    gap_top = row['gap_top']
    gap_bottom = row['gap_bottom']
    stop_d = row['stop_distance_pts']
    if stop_d <= 0 or day_candles is None or day_candles.empty:
        return 0.0

    entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')

    if direction == 'short':
        hard_stop_level = gap_top + HARD_STOP_BUFFER
        tp1 = entry - cfg.tp1_r * stop_d
        tp2 = entry - cfg.tp2_r * stop_d
        tp3 = (entry - cfg.tp3_r * stop_d) if cfg.tp3_r is not None else None
        soft_stop_level = gap_top
    else:
        hard_stop_level = gap_bottom - HARD_STOP_BUFFER
        tp1 = entry + cfg.tp1_r * stop_d
        tp2 = entry + cfg.tp2_r * stop_d
        tp3 = (entry + cfg.tp3_r * stop_d) if cfg.tp3_r is not None else None
        soft_stop_level = gap_bottom

    forward = day_candles[
        (day_candles['timestamp_ny'] > entry_ts) &
        (day_candles['timestamp_ny'].dt.time <= _EOD)
    ]
    if forward.empty:
        return -1.0

    pos = 1.0
    acc_r = 0.0
    tps_taken = {1: False, 2: False, 3: False}
    last_close = None
    effective_stop = hard_stop_level
    be_active = False

    for c in forward.itertuples(index=False):
        last_close = c.close
        if direction == 'short':
            if c.high >= effective_stop:
                r_at_stop = (entry - effective_stop) / stop_d
                acc_r += pos * r_at_stop
                pos = 0
                break
            if c.low <= tp1 and not tps_taken[1]:
                tps_taken[1] = True
                acc_r += cfg.trim_tp1 * cfg.tp1_r
                pos -= cfg.trim_tp1
                if cfg.be_trail_after_tp1 and not be_active:
                    effective_stop = entry
                    be_active = True
            if c.low <= tp2 and not tps_taken[2]:
                tps_taken[2] = True
                acc_r += cfg.trim_tp2 * cfg.tp2_r
                pos -= cfg.trim_tp2
            if tp3 is not None and c.low <= tp3 and not tps_taken[3]:
                tps_taken[3] = True
                acc_r += pos * cfg.tp3_r
                pos = 0
                break
        else:
            if c.low <= effective_stop:
                r_at_stop = (effective_stop - entry) / stop_d
                acc_r += pos * r_at_stop
                pos = 0
                break
            if c.high >= tp1 and not tps_taken[1]:
                tps_taken[1] = True
                acc_r += cfg.trim_tp1 * cfg.tp1_r
                pos -= cfg.trim_tp1
                if cfg.be_trail_after_tp1 and not be_active:
                    effective_stop = entry
                    be_active = True
            if c.high >= tp2 and not tps_taken[2]:
                tps_taken[2] = True
                acc_r += cfg.trim_tp2 * cfg.tp2_r
                pos -= cfg.trim_tp2
            if tp3 is not None and c.high >= tp3 and not tps_taken[3]:
                tps_taken[3] = True
                acc_r += pos * cfg.tp3_r
                pos = 0
                break

        if pos <= 1e-6:
            break

        # Soft stop
        if direction == 'short':
            triggers = c.close > soft_stop_level
            if cfg.require_body_for_soft_stop:
                triggers = triggers and (c.open > soft_stop_level)
            if triggers:
                close_r = (entry - c.close) / stop_d
                acc_r += pos * close_r
                pos = 0
                break
        else:
            triggers = c.close < soft_stop_level
            if cfg.require_body_for_soft_stop:
                triggers = triggers and (c.open < soft_stop_level)
            if triggers:
                close_r = (c.close - entry) / stop_d
                acc_r += pos * close_r
                pos = 0
                break

    if pos > 1e-6 and last_close is not None:
        close_r = ((entry - last_close) / stop_d) if direction == 'short' else ((last_close - entry) / stop_d)
        acc_r += pos * close_r
    return acc_r


def simulate_all(df, candles_by_date, cfg):
    rs = []
    for _, row in df.iterrows():
        r = simulate(row, candles_by_date.get(row['date']), cfg)
        rs.append(r)
    df = df.copy()
    df['r'] = rs
    df['pnl_pts'] = df['r'] * df['stop_distance_pts']
    return df


def summarize(df):
    w = int((df['r'] > 0).sum()); l = int((df['r'] < 0).sum())
    gw = float(df.loc[df['r'] > 0, 'pnl_pts'].sum())
    gl = float(abs(df.loc[df['r'] < 0, 'pnl_pts'].sum())) or 1e-9
    return {'n': len(df), 'wr': round(w/max(w+l,1)*100, 1), 'pf': round(gw/gl, 2),
            'avg_r': round(df['r'].mean(), 3), 'total_r': round(df['r'].sum(), 1)}


# Trim configs — copied from v2_risk_sweep with the best performers + a few new
CONFIGS = [
    RiskConfig("baseline_33_33_34_at_125",  trim_tp1=1/3, trim_tp2=1/3, trim_tp3=1/3, tp1_r=1, tp2_r=2, tp3_r=5),
    RiskConfig("runner_25_25_50_at_148",    trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=4, tp3_r=8),
    RiskConfig("runner_25_25_50_at_125",    trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=2, tp3_r=5),
    RiskConfig("runner_20_30_50_at_125",    trim_tp1=0.20, trim_tp2=0.30, trim_tp3=0.50, tp1_r=1, tp2_r=2, tp3_r=5),
    RiskConfig("agg_50_30_20_at_125",       trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=2, tp3_r=5),
    RiskConfig("tempo_30_30_40_at_125",     trim_tp1=0.30, trim_tp2=0.30, trim_tp3=0.40, tp1_r=1, tp2_r=2, tp3_r=5),
    RiskConfig("wide_33_33_34_at_138",      trim_tp1=1/3, trim_tp2=1/3, trim_tp3=1/3, tp1_r=1, tp2_r=3, tp3_r=8),
    RiskConfig("wide_50_30_20_at_135",      trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=3, tp3_r=5),
    RiskConfig("wide_25_25_50_at_15_10",    trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=5, tp3_r=10),
    RiskConfig("let_runner_33_33_34_at_12N",trim_tp1=1/3, trim_tp2=1/3, trim_tp3=1/3, tp1_r=1, tp2_r=2, tp3_r=None),
    RiskConfig("let_runner_25_25_50_at_13N",trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=3, tp3_r=None),
    RiskConfig("let_runner_25_25_50_at_14N",trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=4, tp3_r=None),
    RiskConfig("let_runner_50_30_20_at_13N",trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=3, tp3_r=None),
    # Tiered with BE
    RiskConfig("be_runner_25_25_50_at_148", trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=4, tp3_r=8, be_trail_after_tp1=True),
    RiskConfig("be_runner_25_25_50_at_125", trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=2, tp3_r=5, be_trail_after_tp1=True),
]


# Entry filter cohorts
ENTRY_FILTERS = {
    'v3_1_SHORT_s>=3':   lambda d: (d['direction'] == 'short') & (~d['v3_1_anti_hit']) & (d['v3_1_score_short'] >= 3),
    'v3_1_SHORT_s>=4':   lambda d: (d['direction'] == 'short') & (~d['v3_1_anti_hit']) & (d['v3_1_score_short'] >= 4),
    'v3_1_LONG_s>=5':    lambda d: (d['direction'] == 'long')  & (~d['v3_1_anti_hit']) & (d['v3_1_score_long'] >= 5),
    'v3_1_LONG_s>=6':    lambda d: (d['direction'] == 'long')  & (~d['v3_1_anti_hit']) & (d['v3_1_score_long'] >= 6),
    'v3_1_LONG_s>=7':    lambda d: (d['direction'] == 'long')  & (~d['v3_1_anti_hit']) & (d['v3_1_score_long'] >= 7),
    'v3_1_COMBINED_>=5': lambda d: (~d['v3_1_anti_hit']) & (d['v3_1_score'] >= 5),
    'v3_1_COMBINED_>=6': lambda d: (~d['v3_1_anti_hit']) & (d['v3_1_score'] >= 6),
}


def main():
    print("=== v3.1 RISK SWEEP ===\n")
    t0 = time.time()

    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['cohort'] = df['date'].apply(lambda d: 'OOS' if d >= OOS_START else 'IS')
    print(f"Population: {len(df)} rows")

    candles = load_candles(DATA_PATH)
    cohort_min = df['date'].min(); cohort_max = df['date'].max()
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    candles_by_date = {d: g[['timestamp_ny','open','high','low','close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}
    print(f"  candles {len(candles):,}, {len(candles_by_date)} sessions, "
          f"loaded in {time.time()-t0:.1f}s\n")

    # MFE distribution preview at high score tiers (informational)
    print("=== MFE distribution at v3.1 high-score tiers (no exit applied yet) ===")
    for name, filt in ENTRY_FILTERS.items():
        sub = df[filt(df)]
        if len(sub) == 0 or 'mfe_r' not in df.columns:
            continue
        print(f"  {name:24} N={len(sub):4} "
              f"avg_MFE={sub['mfe_r'].mean():.2f}  "
              f"med={sub['mfe_r'].median():.2f}  "
              f"p75={sub['mfe_r'].quantile(0.75):.2f}  "
              f"p90={sub['mfe_r'].quantile(0.9):.2f}  "
              f"pct_to_3R={(sub['mfe_r']>=3).mean()*100:.0f}%  "
              f"pct_to_5R={(sub['mfe_r']>=5).mean()*100:.0f}%")
    print()

    rows = []
    for filter_name, filt in ENTRY_FILTERS.items():
        cohort_df = df[filt(df)]
        is_df = cohort_df[cohort_df['cohort'] == 'IS']
        oos_df = cohort_df[cohort_df['cohort'] == 'OOS']
        if len(is_df) < 20 or len(oos_df) < 10:
            print(f"  skipping {filter_name} (N too small)")
            continue
        print(f"\n--- Filter: {filter_name} (IS N={len(is_df)}, OOS N={len(oos_df)}) ---")
        for cfg in CONFIGS:
            sim_is = simulate_all(is_df, candles_by_date, cfg)
            sim_oos = simulate_all(oos_df, candles_by_date, cfg)
            s_is = summarize(sim_is)
            s_oos = summarize(sim_oos)
            rows.append({
                'filter': filter_name,
                'config': cfg.label,
                'IS_n':  s_is['n'],  'IS_pf':  s_is['pf'],  'IS_wr':  s_is['wr'],  'IS_avgR':  s_is['avg_r'],
                'OOS_n': s_oos['n'], 'OOS_pf': s_oos['pf'], 'OOS_wr': s_oos['wr'], 'OOS_avgR': s_oos['avg_r'],
                'IS_totR': s_is['total_r'], 'OOS_totR': s_oos['total_r'],
            })
            print(f"  {cfg.label:34} IS PF={s_is['pf']:5.2f} (avgR {s_is['avg_r']:+.2f})  "
                  f"OOS PF={s_oos['pf']:5.2f} (avgR {s_oos['avg_r']:+.2f}, totR {s_oos['total_r']:+.1f})")

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")

    print("\n=== TOP 10 by OOS PF (any filter) ===")
    print(out.sort_values('OOS_pf', ascending=False).head(10).to_string(index=False))

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
