#!/usr/bin/env python3
"""v1 candidate validation — scaled exits × refined confluence × IS/OOS.

A. Adds scaled-exit (TP1@1R / TP2@2R / Runner@5R) simulation per trade.
B. Tests three confluence variants:
     v1 — original (gap 10-12, body 0.7-0.9, PDH, pd 0.5-0.6, prior_cascade=1)
     v2 — widened gap to 8-12 (8-10 had similar MFE, more frequent)
     v3 — v2 + sweep_penetration_pts <= 2 (highest pct_to_2R across penetration buckets)

Then for each variant × {fixed_1r, scaled} × {IS, OOS}, reports N/WR/PF/avg_R
per confluence score threshold. Final summary picks the best combination.

Runtime: ~30-60s on 1438-trade population.
"""

import sys
import time
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from fvgc.data import load_candles

POP_PATH = Path('studies/ifvg_reversal_population/results/population_enriched.csv')
DATA_PATH = Path('data/consolidated/nq-front-month.ohlcv-30s.csv')
OUT_DIR = Path('studies/ifvg_reversal_population/results/lift')
OUT_DIR.mkdir(exist_ok=True, parents=True)
REPORT_PATH = Path('studies/ifvg_reversal_population/results/v1_summary.md')

_EOD = dtime(16, 0)
HARD_STOP_BUFFER = 2.0
OOS_START = '2025-05-17'


# ---------------------- A. Scaled exit simulator ----------------------

def simulate_scaled(row, day_candles):
    """TP1@1R(33%) + TP2@2R(33%) + Runner@5R(34%), hard_stop + soft_stop fallbacks."""
    direction = row['direction']
    entry = row['entry_price']
    gap_top = row['gap_top']
    gap_bottom = row['gap_bottom']
    stop_d = row['stop_distance_pts']
    if stop_d <= 0:
        return 0.0, 'no_data', 0

    entry_ts = pd.to_datetime(row['entry_ts'], utc=True, format='mixed')

    if direction == 'short':
        hard_stop_level = gap_top + HARD_STOP_BUFFER
        tp1 = entry - 1.0 * stop_d
        tp2 = entry - 2.0 * stop_d
        tp3 = entry - 5.0 * stop_d
        soft_stop_level = gap_top
    else:
        hard_stop_level = gap_bottom - HARD_STOP_BUFFER
        tp1 = entry + 1.0 * stop_d
        tp2 = entry + 2.0 * stop_d
        tp3 = entry + 5.0 * stop_d
        soft_stop_level = gap_bottom

    if day_candles is None or day_candles.empty:
        return -1.0, 'no_data', 0

    forward = day_candles[
        (day_candles['timestamp_ny'] > entry_ts) &
        (day_candles['timestamp_ny'].dt.time <= _EOD)
    ]
    if forward.empty:
        return -1.0, 'no_data', 0

    pos = 1.0
    trim_size = 1.0 / 3.0
    acc_r = 0.0
    tps_taken = {1: False, 2: False, 3: False}
    bars = 0
    exit_reason = 'eod'
    last_close = None

    for c in forward.itertuples(index=False):
        bars += 1
        last_close = c.close

        # Hard stop (intracandle) — closes any remaining
        if direction == 'short':
            if c.high >= hard_stop_level:
                acc_r += pos * -1.0
                pos = 0
                exit_reason = 'hard_stop'
                break
        else:
            if c.low <= hard_stop_level:
                acc_r += pos * -1.0
                pos = 0
                exit_reason = 'hard_stop'
                break

        # TPs (intracandle). Take all that wick through this bar in order.
        if direction == 'short':
            if c.low <= tp1 and not tps_taken[1]:
                tps_taken[1] = True
                acc_r += trim_size * 1.0
                pos -= trim_size
            if c.low <= tp2 and not tps_taken[2]:
                tps_taken[2] = True
                acc_r += trim_size * 2.0
                pos -= trim_size
            if c.low <= tp3 and not tps_taken[3]:
                tps_taken[3] = True
                acc_r += pos * 5.0  # remainder all at 5R
                pos = 0
                exit_reason = 'tp3'
                break
        else:
            if c.high >= tp1 and not tps_taken[1]:
                tps_taken[1] = True
                acc_r += trim_size * 1.0
                pos -= trim_size
            if c.high >= tp2 and not tps_taken[2]:
                tps_taken[2] = True
                acc_r += trim_size * 2.0
                pos -= trim_size
            if c.high >= tp3 and not tps_taken[3]:
                tps_taken[3] = True
                acc_r += pos * 5.0
                pos = 0
                exit_reason = 'tp3'
                break

        if pos <= 1e-6:
            break  # all closed

        # Soft stop on close (only fires on remaining position)
        if direction == 'short' and c.close > soft_stop_level:
            close_r = (entry - c.close) / stop_d
            acc_r += pos * close_r
            pos = 0
            exit_reason = 'soft_stop'
            break
        if direction == 'long' and c.close < soft_stop_level:
            close_r = (c.close - entry) / stop_d
            acc_r += pos * close_r
            pos = 0
            exit_reason = 'soft_stop'
            break

    # Any remaining at EOD: exit at last close
    if pos > 1e-6 and last_close is not None:
        if direction == 'short':
            close_r = (entry - last_close) / stop_d
        else:
            close_r = (last_close - entry) / stop_d
        acc_r += pos * close_r

    return acc_r, exit_reason, bars


def add_scaled_columns(df: pd.DataFrame, candles_by_date: dict) -> pd.DataFrame:
    rs, reasons, bars_list = [], [], []
    for _, row in df.iterrows():
        day = candles_by_date.get(row['date'])
        r, reason, bars = simulate_scaled(row, day)
        rs.append(r); reasons.append(reason); bars_list.append(bars)
    df['scaled_r'] = rs
    df['scaled_exit_reason'] = reasons
    df['scaled_bars'] = bars_list
    df['scaled_pnl_pts'] = df['scaled_r'] * df['stop_distance_pts']
    return df


# ---------------------- B. Confluence variants ----------------------

CONFLUENCE_VARIANTS = {
    'v1_original': [
        ('prior_cascade',  lambda r: r['prior_same_dir_sweep_count'] == 1),
        ('pd_just_past',   lambda r: 0.50 < r['pd_position'] <= 0.60),
        ('strong_body',    lambda r: 0.70 < r['inversion_body_fraction'] <= 0.90),
        ('pdh_sweep',      lambda r: r['sweep_level'] == 'prev_day_high'),
        ('gap_10_12',      lambda r: 10 < r['gap_size_pts'] <= 12),
    ],
    'v2_wider_gap': [
        ('prior_cascade',  lambda r: r['prior_same_dir_sweep_count'] == 1),
        ('pd_just_past',   lambda r: 0.50 < r['pd_position'] <= 0.60),
        ('strong_body',    lambda r: 0.70 < r['inversion_body_fraction'] <= 0.90),
        ('pdh_sweep',      lambda r: r['sweep_level'] == 'prev_day_high'),
        ('gap_8_12',       lambda r: 8 < r['gap_size_pts'] <= 12),
    ],
    'v3_add_pen_le2': [
        ('prior_cascade',  lambda r: r['prior_same_dir_sweep_count'] == 1),
        ('pd_just_past',   lambda r: 0.50 < r['pd_position'] <= 0.60),
        ('strong_body',    lambda r: 0.70 < r['inversion_body_fraction'] <= 0.90),
        ('pdh_sweep',      lambda r: r['sweep_level'] == 'prev_day_high'),
        ('gap_8_12',       lambda r: 8 < r['gap_size_pts'] <= 12),
        ('shallow_sweep',  lambda r: r['sweep_penetration_pts'] <= 2.0),
    ],
}

ANTI_PATTERNS = [
    ('body_too_extreme',  lambda r: r['inversion_body_fraction'] > 0.90),
    ('gap_dead_zone',     lambda r: 12 < r['gap_size_pts'] <= 15),
    ('pdl_long',          lambda r: r['sweep_level'] == 'prev_day_low'),
]


def score_variant(df: pd.DataFrame, variant_name: str) -> pd.Series:
    factors = CONFLUENCE_VARIANTS[variant_name]
    s = pd.Series(0, index=df.index)
    for _, fn in factors:
        s += df.apply(fn, axis=1).astype(int)
    return s


def hits_anti(df: pd.DataFrame) -> pd.Series:
    s = pd.Series(False, index=df.index)
    for _, fn in ANTI_PATTERNS:
        s |= df.apply(fn, axis=1)
    return s


# ---------------------- Summaries ----------------------

def summary_at_threshold(d: pd.DataFrame, score_col: str, r_col: str, pnl_col: str):
    rows = []
    for thresh in range(0, 7):
        sub = d[d[score_col] >= thresh]
        if len(sub) == 0:
            continue
        w = int((sub[r_col] > 0).sum())
        l = int((sub[r_col] < 0).sum())
        gw = float(sub.loc[sub[r_col] > 0, pnl_col].sum())
        gl = float(abs(sub.loc[sub[r_col] < 0, pnl_col].sum())) or 1e-9
        rows.append({
            'threshold': thresh,
            'n': len(sub),
            'wr_pct': round(w/max(w+l,1)*100, 1),
            'pf': round(gw/gl, 2),
            'avg_r': round(sub[r_col].mean(), 3),
            'total_r': round(sub[r_col].sum(), 1),
            'total_pnl': round(sub[pnl_col].sum(), 1),
        })
    return pd.DataFrame(rows)


# ---------------------- Main ----------------------

def main():
    print("=== v1 candidate validation ===\n")
    t0 = time.time()

    df = pd.read_csv(POP_PATH)
    df['date'] = pd.to_datetime(df['entry_ts'], utc=True, format='mixed').dt.date.astype(str)
    df['cohort'] = df['date'].apply(lambda d: 'OOS' if d >= OOS_START else 'IS')
    print(f"Population: N={len(df)}, IS={len(df[df['cohort']=='IS'])}, OOS={len(df[df['cohort']=='OOS'])}")

    print("\nLoading candles for scaled simulation...")
    candles = load_candles(DATA_PATH)
    cohort_min = df['date'].min(); cohort_max = df['date'].max()
    candles = candles[
        (candles['timestamp_ny'].dt.tz_localize(None) >= pd.Timestamp(cohort_min)) &
        (candles['timestamp_ny'].dt.tz_localize(None) <= pd.Timestamp(cohort_max) + pd.Timedelta(days=1))
    ].copy()
    candles['date_ny'] = candles['timestamp_ny'].dt.date.astype(str)
    candles_by_date = {d: g[['timestamp_ny','open','high','low','close']].reset_index(drop=True)
                       for d, g in candles.groupby('date_ny', sort=False)}
    print(f"  {len(candles):,} candles indexed across {len(candles_by_date)} sessions")

    print("\nSimulating scaled exits per trade...")
    t = time.time()
    df = add_scaled_columns(df, candles_by_date)
    print(f"  done in {time.time()-t:.1f}s")
    print(f"  scaled exit reasons: {df['scaled_exit_reason'].value_counts().to_dict()}")

    # Compute confluence variants + anti-pattern hits
    print("\nComputing confluence variants...")
    df['anti_hit'] = hits_anti(df)
    for vname in CONFLUENCE_VARIANTS:
        df[f'score_{vname}'] = score_variant(df, vname)

    # ------------- Per-variant analysis -------------
    report_lines = ["# v1 Validation Summary\n"]
    report_lines.append(f"Cohort: {cohort_min} → {cohort_max} (N={len(df)} trades)\n")
    report_lines.append(f"IS: {len(df[df['cohort']=='IS'])}, OOS: {len(df[df['cohort']=='OOS'])}\n")
    report_lines.append(f"\n## Overall comparison: fixed_1r vs scaled exit (no filter)\n")
    print("\n" + "="*78)
    print("OVERALL: fixed_1r vs scaled (no confluence filter, no anti-pattern filter)")
    print("="*78)
    for cohort_name in ('IS', 'OOS'):
        sub = df[df['cohort'] == cohort_name]
        for mode, r_col, pnl_col in (('fixed_1r', 'r_multiple', 'pnl_pts'),
                                      ('scaled',   'scaled_r',   'scaled_pnl_pts')):
            w = int((sub[r_col]>0).sum()); l = int((sub[r_col]<0).sum())
            gw = float(sub.loc[sub[r_col]>0, pnl_col].sum())
            gl = float(abs(sub.loc[sub[r_col]<0, pnl_col].sum())) or 1e-9
            line = (f"  {cohort_name:>3} {mode:<10}  N={len(sub):<4}  "
                    f"WR={w/max(w+l,1)*100:5.1f}%  PF={gw/gl:5.2f}  "
                    f"avg_R={sub[r_col].mean():+.3f}  total_R={sub[r_col].sum():+.1f}")
            print(line); report_lines.append(line + "\n")
    report_lines.append("\n")

    # ------------- Per-variant, threshold sweep -------------
    for vname in CONFLUENCE_VARIANTS:
        score_col = f'score_{vname}'
        print("\n" + "="*78)
        print(f"VARIANT: {vname}  (factors: {[name for name,_ in CONFLUENCE_VARIANTS[vname]]})")
        print("="*78)
        report_lines.append(f"\n## Variant {vname}\n")
        report_lines.append(f"Factors: {[name for name,_ in CONFLUENCE_VARIANTS[vname]]}\n\n")

        for cohort_name in ('IS', 'OOS'):
            sub = df[df['cohort'] == cohort_name]
            print(f"\n-- {cohort_name} cohort --")
            for mode, r_col, pnl_col in (('fixed_1r', 'r_multiple', 'pnl_pts'),
                                          ('scaled',   'scaled_r',   'scaled_pnl_pts')):
                tbl = summary_at_threshold(sub, score_col, r_col, pnl_col)
                print(f"\n  {cohort_name} {mode}:")
                print(tbl.to_string(index=False))
                report_lines.append(f"### {cohort_name} {mode}\n\n```\n")
                report_lines.append(tbl.to_string(index=False) + "\n```\n\n")
                tbl['cohort'] = cohort_name; tbl['mode'] = mode; tbl['variant'] = vname
                out_csv = OUT_DIR / f'{vname}_{cohort_name}_{mode}.csv'
                tbl.to_csv(out_csv, index=False)

        # Anti-pattern filtered version
        survivors = df[~df['anti_hit']]
        for cohort_name in ('IS', 'OOS'):
            sub = survivors[survivors['cohort'] == cohort_name]
            if len(sub) == 0:
                continue
            print(f"\n-- {cohort_name} (anti-pattern-filtered) --")
            report_lines.append(f"### {cohort_name} anti-pattern-filtered\n\n")
            for mode, r_col, pnl_col in (('fixed_1r', 'r_multiple', 'pnl_pts'),
                                          ('scaled',   'scaled_r',   'scaled_pnl_pts')):
                tbl = summary_at_threshold(sub, score_col, r_col, pnl_col)
                print(f"\n  {cohort_name} {mode} (anti-filtered):")
                print(tbl.to_string(index=False))
                report_lines.append(f"#### {mode}\n\n```\n")
                report_lines.append(tbl.to_string(index=False) + "\n```\n\n")

    # ------------- Best-cell summary -------------
    print("\n" + "="*78)
    print("BEST CELLS — score >= 2 and >= 3, across variants/modes, OOS focus")
    print("="*78)
    report_lines.append("\n## Best cells (OOS focus, score >= 2 and >= 3)\n\n")
    summary_rows = []
    for vname in CONFLUENCE_VARIANTS:
        score_col = f'score_{vname}'
        for cohort_name in ('IS', 'OOS'):
            sub = df[df['cohort'] == cohort_name]
            for mode, r_col, pnl_col in (('fixed_1r', 'r_multiple', 'pnl_pts'),
                                          ('scaled',   'scaled_r',   'scaled_pnl_pts')):
                for thresh in (2, 3):
                    s = sub[sub[score_col] >= thresh]
                    if len(s) < 5:
                        continue
                    w = (s[r_col]>0).sum(); l = (s[r_col]<0).sum()
                    gw = s.loc[s[r_col]>0, pnl_col].sum()
                    gl = abs(s.loc[s[r_col]<0, pnl_col].sum()) or 1e-9
                    summary_rows.append({
                        'variant': vname, 'cohort': cohort_name, 'mode': mode,
                        'thresh': thresh, 'n': len(s),
                        'wr': round(w/max(w+l,1)*100,1),
                        'pf': round(gw/gl, 2),
                        'avg_r': round(s[r_col].mean(),3),
                        'total_r': round(s[r_col].sum(),1),
                    })
    summary_df = pd.DataFrame(summary_rows).sort_values(['mode','thresh','cohort','variant'])
    print(summary_df.to_string(index=False))
    summary_df.to_csv(OUT_DIR / 'v1_summary_grid.csv', index=False)
    report_lines.append("```\n" + summary_df.to_string(index=False) + "\n```\n")

    # ------------- Save scored CSV + report -------------
    df.to_csv(POP_PATH.with_name('population_scored.csv'), index=False)
    with open(REPORT_PATH, 'w') as f:
        f.writelines(report_lines)
    print(f"\n\nWrote {REPORT_PATH}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
