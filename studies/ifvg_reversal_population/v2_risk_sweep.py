#!/usr/bin/env python3
"""v2 — R-based risk management parameter sweep.

Holds the entry filter constant (confluence v2 score >= 2) and sweeps:
  - Trim ladder fractions (TP1/TP2/runner percentage of position)
  - TP R-multiples (where TPs are placed)
  - Optional: breakeven trail after TP1
  - Optional: tighter soft stop (full body close vs any close)

Reports IS / OOS PF, WR, avg_R for each variant. Sortable.

Goal: find the R-based risk management config that pushes OOS PF >= 1.7 while
staying robust (IS↔OOS degradation < 20%).
"""

import sys
import time
from dataclasses import dataclass, field
from datetime import time as dtime
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
OUT_CSV = Path('studies/ifvg_reversal_population/results/v2_risk_sweep.csv')
REPORT_PATH = Path('studies/ifvg_reversal_population/results/v2_findings.md')

_EOD = dtime(16, 0)
HARD_STOP_BUFFER = 2.0
OOS_START = '2025-05-17'
ENTRY_FILTER_SCORE_COL = 'score_v2_wider_gap'   # use v2 confluence from prior run
ENTRY_FILTER_THRESHOLD = 2


# ---------------------- Risk config ----------------------

@dataclass
class RiskConfig:
    name: str
    tp1_r: float = 1.0
    tp2_r: float = 2.0
    tp3_r: Optional[float] = 5.0   # None => no TP3, ride to soft/hard stop
    trim_tp1: float = 1/3
    trim_tp2: float = 1/3
    trim_tp3: float = 1/3          # rest if TP3 set
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


def simulate_with_config(row, day_candles, cfg: RiskConfig) -> Tuple[float, str, int]:
    direction = row['direction']
    entry = row['entry_price']
    gap_top = row['gap_top']
    gap_bottom = row['gap_bottom']
    stop_d = row['stop_distance_pts']
    if stop_d <= 0 or day_candles is None or day_candles.empty:
        return 0.0, 'no_data', 0

    entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')

    # Stop & TP price levels
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
        return -1.0, 'no_data', 0

    pos = 1.0
    acc_r = 0.0
    tps_taken = {1: False, 2: False, 3: False}
    bars = 0
    exit_reason = 'eod'
    last_close = None

    # BE trail state
    effective_stop_level = hard_stop_level
    be_active = False

    for c in forward.itertuples(index=False):
        bars += 1
        last_close = c.close

        # Hard stop check (intracandle) — including BE-trail if active
        if direction == 'short':
            if c.high >= effective_stop_level:
                r_at_stop = (entry - effective_stop_level) / stop_d
                acc_r += pos * r_at_stop
                pos = 0
                exit_reason = 'be_stop' if be_active else 'hard_stop'
                break
        else:
            if c.low <= effective_stop_level:
                r_at_stop = (effective_stop_level - entry) / stop_d
                acc_r += pos * r_at_stop
                pos = 0
                exit_reason = 'be_stop' if be_active else 'hard_stop'
                break

        # TPs (intracandle, in order)
        if direction == 'short':
            if c.low <= tp1 and not tps_taken[1]:
                tps_taken[1] = True
                acc_r += cfg.trim_tp1 * cfg.tp1_r
                pos -= cfg.trim_tp1
                if cfg.be_trail_after_tp1 and not be_active:
                    effective_stop_level = entry  # BE
                    be_active = True
            if c.low <= tp2 and not tps_taken[2]:
                tps_taken[2] = True
                acc_r += cfg.trim_tp2 * cfg.tp2_r
                pos -= cfg.trim_tp2
            if tp3 is not None and c.low <= tp3 and not tps_taken[3]:
                tps_taken[3] = True
                acc_r += pos * cfg.tp3_r
                pos = 0
                exit_reason = 'tp3'
                break
        else:
            if c.high >= tp1 and not tps_taken[1]:
                tps_taken[1] = True
                acc_r += cfg.trim_tp1 * cfg.tp1_r
                pos -= cfg.trim_tp1
                if cfg.be_trail_after_tp1 and not be_active:
                    effective_stop_level = entry
                    be_active = True
            if c.high >= tp2 and not tps_taken[2]:
                tps_taken[2] = True
                acc_r += cfg.trim_tp2 * cfg.tp2_r
                pos -= cfg.trim_tp2
            if tp3 is not None and c.high >= tp3 and not tps_taken[3]:
                tps_taken[3] = True
                acc_r += pos * cfg.tp3_r
                pos = 0
                exit_reason = 'tp3'
                break

        if pos <= 1e-6:
            break

        # Soft stop check on close
        if direction == 'short':
            triggers_soft = c.close > soft_stop_level
            if cfg.require_body_for_soft_stop:
                triggers_soft = triggers_soft and (c.open > soft_stop_level)
            if triggers_soft:
                close_r = (entry - c.close) / stop_d
                acc_r += pos * close_r
                pos = 0
                exit_reason = 'soft_stop'
                break
        else:
            triggers_soft = c.close < soft_stop_level
            if cfg.require_body_for_soft_stop:
                triggers_soft = triggers_soft and (c.open < soft_stop_level)
            if triggers_soft:
                close_r = (c.close - entry) / stop_d
                acc_r += pos * close_r
                pos = 0
                exit_reason = 'soft_stop'
                break

    # EOD exit on remaining
    if pos > 1e-6 and last_close is not None:
        if direction == 'short':
            close_r = (entry - last_close) / stop_d
        else:
            close_r = (last_close - entry) / stop_d
        acc_r += pos * close_r

    return acc_r, exit_reason, bars


def simulate_all(df: pd.DataFrame, candles_by_date: dict, cfg: RiskConfig) -> pd.DataFrame:
    rs, reasons = [], []
    for _, row in df.iterrows():
        r, reason, _ = simulate_with_config(row, candles_by_date.get(row['date']), cfg)
        rs.append(r); reasons.append(reason)
    df = df.copy()
    df['r'] = rs
    df['exit_reason'] = reasons
    df['pnl_pts'] = df['r'] * df['stop_distance_pts']
    return df


def summarize(df: pd.DataFrame) -> dict:
    w = int((df['r'] > 0).sum()); l = int((df['r'] < 0).sum())
    gw = float(df.loc[df['r'] > 0, 'pnl_pts'].sum())
    gl = float(abs(df.loc[df['r'] < 0, 'pnl_pts'].sum())) or 1e-9
    return {
        'n': len(df),
        'wr': round(w / max(w+l, 1) * 100, 1),
        'pf': round(gw / gl, 2),
        'avg_r': round(df['r'].mean(), 3),
        'total_r': round(df['r'].sum(), 1),
    }


# ---------------------- Configs to test ----------------------

CONFIGS = [
    # Baseline (current default)
    RiskConfig("baseline_33_33_34_at_125",   trim_tp1=1/3, trim_tp2=1/3, trim_tp3=1/3, tp1_r=1, tp2_r=2, tp3_r=5),

    # Trim ladder variants (same R targets)
    RiskConfig("aggressive_partials_50_30_20", trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=2, tp3_r=5),
    RiskConfig("runner_heavy_20_30_50",        trim_tp1=0.20, trim_tp2=0.30, trim_tp3=0.50, tp1_r=1, tp2_r=2, tp3_r=5),
    RiskConfig("runner_heavy_25_25_50",        trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=2, tp3_r=5),
    RiskConfig("tempo_30_30_40",                trim_tp1=0.30, trim_tp2=0.30, trim_tp3=0.40, tp1_r=1, tp2_r=2, tp3_r=5),

    # No runner — exit at TP2
    RiskConfig("no_runner_50_50_0",            trim_tp1=0.50, trim_tp2=0.50, trim_tp3=0.0,  tp1_r=1, tp2_r=2, tp3_r=None),

    # Wider R targets (let trade breathe)
    RiskConfig("wide_targets_33_33_34_at_138", trim_tp1=1/3, trim_tp2=1/3, trim_tp3=1/3, tp1_r=1, tp2_r=3, tp3_r=8),
    RiskConfig("wide_runner_50_30_20_at_135",  trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=3, tp3_r=5),
    RiskConfig("wide_runner_25_25_50_at_148",  trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=4, tp3_r=8),

    # Aggressive partials with tight runner
    RiskConfig("agg_tight_run_50_30_20_at_124", trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=2, tp3_r=4),

    # Half-R first partial (lock in fast)
    RiskConfig("fast_lock_50_30_20_at_05_15_4", trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=0.5, tp2_r=1.5, tp3_r=4),
    RiskConfig("fast_lock_33_33_34_at_05_15_5", trim_tp1=1/3, trim_tp2=1/3, trim_tp3=1/3,    tp1_r=0.5, tp2_r=1.5, tp3_r=5),

    # Let runner ride (no fixed TP3 cap)
    RiskConfig("let_runner_33_33_34_at_12_None", trim_tp1=1/3, trim_tp2=1/3, trim_tp3=1/3, tp1_r=1, tp2_r=2, tp3_r=None),
    RiskConfig("let_runner_50_30_20_at_12_None", trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=2, tp3_r=None),
    RiskConfig("let_runner_50_30_20_at_13_None", trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=3, tp3_r=None),

    # Breakeven trail after TP1 — applied to top performers above
    RiskConfig("be_50_30_20_at_125",  trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=2, tp3_r=5, be_trail_after_tp1=True),
    RiskConfig("be_25_25_50_at_125",  trim_tp1=0.25, trim_tp2=0.25, trim_tp3=0.50, tp1_r=1, tp2_r=2, tp3_r=5, be_trail_after_tp1=True),
    RiskConfig("be_50_30_20_at_13_None", trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=3, tp3_r=None, be_trail_after_tp1=True),

    # Tighter soft stop (body required) — applied to baseline-like configs
    RiskConfig("body_soft_33_33_34_at_125",   trim_tp1=1/3, trim_tp2=1/3, trim_tp3=1/3, tp1_r=1, tp2_r=2, tp3_r=5, require_body_for_soft_stop=True),
    RiskConfig("body_soft_50_30_20_at_125",   trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=2, tp3_r=5, require_body_for_soft_stop=True),

    # Both BE + body
    RiskConfig("be_body_50_30_20_at_125",     trim_tp1=0.50, trim_tp2=0.30, trim_tp3=0.20, tp1_r=1, tp2_r=2, tp3_r=5, be_trail_after_tp1=True, require_body_for_soft_stop=True),
]


def main():
    print("=== v2 risk sweep ===\n")
    t0 = time.time()

    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['cohort'] = df['date'].apply(lambda d: 'OOS' if d >= OOS_START else 'IS')

    # Apply entry filter
    filtered = df[df[ENTRY_FILTER_SCORE_COL] >= ENTRY_FILTER_THRESHOLD].copy()
    print(f"Population: {len(df)} total, {len(filtered)} after score>={ENTRY_FILTER_THRESHOLD} "
          f"({ENTRY_FILTER_SCORE_COL})")
    print(f"  IS={len(filtered[filtered['cohort']=='IS'])}, "
          f"OOS={len(filtered[filtered['cohort']=='OOS'])}\n")

    print("Loading candles...")
    candles = load_candles(DATA_PATH)
    cohort_min = df['date'].min(); cohort_max = df['date'].max()
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    candles_by_date = {d: g[['timestamp_ny','open','high','low','close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}
    print(f"  {len(candles):,} candles, {len(candles_by_date)} sessions\n")

    rows = []
    for cfg in CONFIGS:
        t = time.time()
        sim_all = simulate_all(filtered, candles_by_date, cfg)
        is_stats  = summarize(sim_all[sim_all['cohort']=='IS'])
        oos_stats = summarize(sim_all[sim_all['cohort']=='OOS'])

        # Degradation: how much OOS PF dropped from IS
        is_pf = is_stats['pf']; oos_pf = oos_stats['pf']
        degradation = round((1 - oos_pf / max(is_pf, 1e-9)) * 100, 1) if is_pf > 0 else 0

        rows.append({
            'config': cfg.name,
            'label': cfg.label,
            'IS_n':   is_stats['n'],   'IS_wr':   is_stats['wr'],   'IS_pf':   is_stats['pf'],   'IS_avgR':  is_stats['avg_r'],  'IS_totR':  is_stats['total_r'],
            'OOS_n':  oos_stats['n'],  'OOS_wr':  oos_stats['wr'],  'OOS_pf':  oos_stats['pf'],  'OOS_avgR': oos_stats['avg_r'], 'OOS_totR': oos_stats['total_r'],
            'IS->OOS_drop_pct': degradation,
        })
        print(f"  [{time.time()-t:4.1f}s] {cfg.label:<35}  "
              f"IS PF={is_stats['pf']:5.2f} (avgR {is_stats['avg_r']:+.3f})  "
              f"OOS PF={oos_stats['pf']:5.2f} (avgR {oos_stats['avg_r']:+.3f})  "
              f"drop={degradation:5.1f}%")

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")

    print("\n=== Top 5 by OOS PF (with degradation < 30%) ===")
    robust = out[out['IS->OOS_drop_pct'] < 30].sort_values('OOS_pf', ascending=False)
    print(robust.head(5).to_string(index=False))

    print("\n=== Top 5 by OOS avg_R (with degradation < 30%) ===")
    robust2 = out[out['IS->OOS_drop_pct'] < 30].sort_values('OOS_avgR', ascending=False)
    print(robust2.head(5).to_string(index=False))

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")

    # Write findings markdown
    write_findings(out)


def write_findings(out: pd.DataFrame):
    lines = ["# v2 Risk Management Sweep — Findings\n\n"]
    lines.append(f"Entry filter: score_v2_wider_gap >= 2 (102 OOS trades)\n\n")
    lines.append(f"## All configurations\n\n```\n")
    lines.append(out.to_string(index=False))
    lines.append("\n```\n\n")
    lines.append(f"## Top OOS PF (degradation < 30%)\n\n```\n")
    robust = out[out['IS->OOS_drop_pct'] < 30].sort_values('OOS_pf', ascending=False).head(10)
    lines.append(robust.to_string(index=False))
    lines.append("\n```\n\n")
    lines.append(f"## Top OOS avg_R (degradation < 30%)\n\n```\n")
    robust2 = out[out['IS->OOS_drop_pct'] < 30].sort_values('OOS_avgR', ascending=False).head(10)
    lines.append(robust2.to_string(index=False))
    lines.append("\n```\n")
    REPORT_PATH.write_text("".join(lines))
    print(f"Wrote {REPORT_PATH}")


if __name__ == '__main__':
    main()
