#!/usr/bin/env python3
"""
Prior-Day 50% Level Study

Tests whether the prior-day midpoint acts as a meaningful liquidity zone
for FVGC trade outcomes. Four sub-studies:
  A — Rejection / directional asymmetry
  B — Target magnet (reach rate by distance bucket)
  C — Rejection + first-FVGC-in-reversal-direction
  D — POC ↔ 50% confluence overlay

Two candidate mid definitions are tested side-by-side:
  pd_hl_mid = (prev_day_high + prev_day_low) / 2
  pd_va_mid = (prior_vp_vah + prior_vp_val) / 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from analysis.permutation_test import run_permutation_test  # noqa: E402
from studies.pd_50pct_level.rejection_events import (  # noqa: E402
    tag_trades_with_rejections,
    PRIMARY_LOOKBACK_BARS,
    PRIMARY_TAU,
)

ROOT = Path(__file__).resolve().parent.parent.parent
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
HISTOGRAMS_DIR = RESULTS_DIR / 'histograms'

TRADES_PATH = ROOT / 'data' / 'levels' / 'trades_with_pd_mid.csv'

MIDS = ('pd_hl_mid', 'pd_va_mid')
PRIMARY_THRESHOLD = 15  # pts
DIST_R_BUCKETS = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, np.inf)]


# =============================================================================
# Core utilities
# =============================================================================

def compute_segment_stats(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n == 0:
        return {
            'label': label, 'n': 0, 'wins': 0, 'losses': 0,
            'wr': None, 'pf': None,
            'med_mfe_r': None, 'med_mae_r': None,
            'avg_pnl': None, 'total_pnl': None,
        }
    wins = int((df['outcome'] == 'win').sum())
    losses = int((df['outcome'] == 'loss').sum())
    pnl = pd.to_numeric(df['pnl'], errors='coerce')
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl < 0].sum())
    pf = gp / gl if gl > 0 else (np.inf if gp > 0 else np.nan)
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else None
    mfe_r = pd.to_numeric(df.get('mfe_r'), errors='coerce')
    mae_r = pd.to_numeric(df.get('mae_r'), errors='coerce')
    return {
        'label': label,
        'n': n,
        'wins': wins,
        'losses': losses,
        'wr': round(wr, 1) if wr is not None else None,
        'pf': round(pf, 2) if not np.isinf(pf) and not np.isnan(pf) else pf,
        'med_mfe_r': round(float(mfe_r.median()), 2) if len(mfe_r.dropna()) else None,
        'med_mae_r': round(float(mae_r.median()), 2) if len(mae_r.dropna()) else None,
        'avg_pnl': round(float(pnl.mean()), 2),
        'total_pnl': round(float(pnl.sum()), 2),
    }


def bootstrap_wr_ci(df: pd.DataFrame, n_boot: int = 5000,
                    seed: int = 42) -> tuple[float, float, float]:
    outcomes = (df['outcome'] == 'win').astype(int).values
    n = len(outcomes)
    if n == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    wr_point = outcomes.mean() * 100
    samples = rng.choice(outcomes, size=(n_boot, n), replace=True)
    wrs = samples.mean(axis=1) * 100
    lo, hi = np.percentile(wrs, [2.5, 97.5])
    return (float(wr_point), float(lo), float(hi))


# =============================================================================
# Loading
# =============================================================================

def load_data() -> pd.DataFrame:
    print('Loading trades_with_pd_mid.csv ...')
    df = pd.read_csv(TRADES_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.date
    tradeable = df[df['outcome'].isin(['win', 'loss'])].copy()
    print(f'  {len(tradeable)} tradeable trades (of {len(df)} total)')
    return tradeable


# =============================================================================
# Sub-study A — Rejection / directional asymmetry
# =============================================================================

def run_substudy_a(df: pd.DataFrame) -> pd.DataFrame:
    """For each mid variant, segment tradeable trades into 4 cells:
    {long, short} × {trading_into, trading_away}, filtered to near_{mid}_15pt.
    Also report the unsegmented baseline.
    """
    print('\n=== Sub-study A: Rejection / directional asymmetry ===')
    rows = []
    baseline = compute_segment_stats(df, 'ALL tradeable (baseline)')
    baseline['mid'] = '—'
    baseline['direction'] = 'all'
    baseline['facing'] = 'all'
    baseline['threshold_pt'] = '—'
    rows.append(baseline)

    for mid in MIDS:
        near_col = f'near_{mid}_{PRIMARY_THRESHOLD}pt'
        into_col = f'trading_into_{mid}'
        away_col = f'trading_away_{mid}'
        sub = df[df[mid].notna() & df[near_col]]
        for direction in ('long', 'short'):
            for facing, mask in (('trading_into', sub[into_col]),
                                 ('trading_away', sub[away_col])):
                cell = sub[(sub['direction'] == direction) & mask]
                row = compute_segment_stats(
                    cell,
                    f'{mid} | {direction} | {facing} | near {PRIMARY_THRESHOLD}pt',
                )
                row['mid'] = mid
                row['direction'] = direction
                row['facing'] = facing
                row['threshold_pt'] = PRIMARY_THRESHOLD
                rows.append(row)
        # Unsegmented near-mid cohort
        row = compute_segment_stats(
            sub, f'{mid} | near {PRIMARY_THRESHOLD}pt | all directions')
        row['mid'] = mid
        row['direction'] = 'all'
        row['facing'] = 'all'
        row['threshold_pt'] = PRIMARY_THRESHOLD
        rows.append(row)

    # Robustness: other proximity thresholds, all cells
    for mid in MIDS:
        for th in (5, 10, 20):
            near_col = f'near_{mid}_{th}pt'
            into_col = f'trading_into_{mid}'
            sub = df[df[mid].notna() & df[near_col]]
            for direction in ('long', 'short'):
                cell = sub[(sub['direction'] == direction) & sub[into_col]]
                row = compute_segment_stats(
                    cell,
                    f'{mid} | {direction} | trading_into | near {th}pt',
                )
                row['mid'] = mid
                row['direction'] = direction
                row['facing'] = 'trading_into'
                row['threshold_pt'] = th
                rows.append(row)

    # VP-redundancy-controlled variant: edge excluding rows that are also near VAH/VAL
    for mid in MIDS:
        near_mid = df[f'near_{mid}_{PRIMARY_THRESHOLD}pt']
        near_vah = df.get('near_vah_15pt', pd.Series([False] * len(df)))
        near_val = df.get('near_val_15pt', pd.Series([False] * len(df)))
        into = df[f'trading_into_{mid}']
        mask = near_mid & ~(near_vah | near_val)
        for direction in ('long', 'short'):
            cell = df[mask & (df['direction'] == direction) & into]
            row = compute_segment_stats(
                cell,
                f'{mid} | {direction} | trading_into | near 15pt & NOT near VAH/VAL',
            )
            row['mid'] = mid
            row['direction'] = direction
            row['facing'] = 'trading_into'
            row['threshold_pt'] = '15 (incremental vs VP)'
            rows.append(row)

    return pd.DataFrame(rows)


# =============================================================================
# Sub-study B — Target magnet (reach rate by distance bucket)
# =============================================================================

def run_substudy_b(df: pd.DataFrame) -> pd.DataFrame:
    print('\n=== Sub-study B: Target magnet (reach rate) ===')
    rows = []
    for mid in MIDS:
        mid_col = mid
        direction = df['direction']
        entry = df['entry_price']
        mid_val = df[mid_col]
        # Mid must lie beyond entry in trade direction
        mid_in_dir = (
            ((direction == 'long') & (mid_val > entry)) |
            ((direction == 'short') & (mid_val < entry))
        )
        sub = df[df[mid_col].notna() & mid_in_dir].copy()
        dist_pts = (entry - mid_val).abs()
        sub['_dist_pts'] = dist_pts[mid_in_dir]
        sub['_dist_r'] = sub[f'dist_to_{mid}_R']
        mfe = pd.to_numeric(sub['mfe_pts'], errors='coerce')
        sub['_reached'] = mfe >= sub['_dist_pts']

        for lo, hi in DIST_R_BUCKETS:
            bucket_label = f'{lo:.1f}-{hi:.1f}R' if np.isfinite(hi) else f'{lo:.1f}R+'
            bucket = sub[(sub['_dist_r'] >= lo) & (sub['_dist_r'] < hi)]
            for direction_label in ('all', 'long', 'short'):
                if direction_label == 'all':
                    cell = bucket
                else:
                    cell = bucket[bucket['direction'] == direction_label]
                if len(cell) == 0:
                    continue
                reached = int(cell['_reached'].sum())
                n = len(cell)
                rows.append({
                    'mid': mid,
                    'direction': direction_label,
                    'dist_R_bucket': bucket_label,
                    'n': n,
                    'reached': reached,
                    'reach_rate': round(reached / n * 100, 1),
                    'med_mfe_r': round(float(
                        pd.to_numeric(cell['mfe_r'], errors='coerce').median()
                    ), 2),
                })
    return pd.DataFrame(rows)


# =============================================================================
# Sub-study C — Rejection + first-FVGC-reversal
# =============================================================================

def run_substudy_c(df: pd.DataFrame, enriched: pd.DataFrame) -> dict:
    print('\n=== Sub-study C: Rejection + first-FVGC-reversal ===')
    # `enriched` has rejection flags merged in. Filter to tradeable-and-enriched rows.
    e = enriched[enriched['outcome'].isin(['win', 'loss'])].copy()

    rows = []
    spot_check_blobs = []
    # All tau/lookback combos for sensitivity
    combos = [
        (mid, tau, lb)
        for mid in MIDS
        for tau in (1, 3)
        for lb in (10, 20, 40)
    ]
    baseline = compute_segment_stats(e, 'BASELINE (all tradeable)')
    baseline.update({'mid': '—', 'tau': '—', 'lookback_bars': '—',
                     'flag': 'baseline', 'wr_ci_lo': None, 'wr_ci_hi': None})
    rows.append(baseline)

    for mid, tau, lb in combos:
        rej_col = f'rej_{mid}_tau{tau}_lb{lb}'
        sub = e[e[rej_col]]
        stats = compute_segment_stats(sub, f'{rej_col}')
        wr_point, ci_lo, ci_hi = bootstrap_wr_ci(sub)
        stats.update({
            'mid': mid, 'tau': tau, 'lookback_bars': lb,
            'flag': 'rejection',
            'wr_ci_lo': round(ci_lo, 1) if not np.isnan(ci_lo) else None,
            'wr_ci_hi': round(ci_hi, 1) if not np.isnan(ci_hi) else None,
        })
        rows.append(stats)

    # Primary flag: first FVGC in reversal direction (primary combo only)
    for mid in MIDS:
        col = f'first_fvgc_{mid}_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}'
        if col not in e.columns:
            continue
        sub = e[e[col]]
        stats = compute_segment_stats(sub, f'{col}')
        wr_point, ci_lo, ci_hi = bootstrap_wr_ci(sub)
        stats.update({
            'mid': mid,
            'tau': int(PRIMARY_TAU),
            'lookback_bars': PRIMARY_LOOKBACK_BARS,
            'flag': 'first_fvgc_reversal',
            'wr_ci_lo': round(ci_lo, 1) if not np.isnan(ci_lo) else None,
            'wr_ci_hi': round(ci_hi, 1) if not np.isnan(ci_hi) else None,
        })
        rows.append(stats)

        # Spot-check: first 5 qualifying trades, OHLC dump of pre-entry window
        qualifying = sub.sort_values('timestamp').head(5)
        for _, trow in qualifying.iterrows():
            spot_check_blobs.append({
                'mid': mid,
                'timestamp': str(trow['timestamp']),
                'direction': trow['direction'],
                'entry_price': float(trow['entry_price']),
                f'{mid}_value': float(trow[mid]) if pd.notna(trow[mid]) else None,
                f'dist_to_{mid}_pts': float(trow[f'dist_to_{mid}_pts']),
                'outcome': trow['outcome'],
                'mfe_r': float(trow['mfe_r']) if pd.notna(trow['mfe_r']) else None,
                'mae_r': float(trow['mae_r']) if pd.notna(trow['mae_r']) else None,
                'variant': trow.get('variant', '—'),
            })

    return {
        'table': pd.DataFrame(rows),
        'spot_checks': spot_check_blobs,
    }


# =============================================================================
# Sub-study D — POC ↔ 50% confluence
# =============================================================================

def run_substudy_d(df: pd.DataFrame) -> pd.DataFrame:
    print('\n=== Sub-study D: POC confluence ===')
    rows = []
    for mid in MIDS:
        # Descriptive: day-level coincidence frequency (dedupe on prior_vp_date)
        daily = df.drop_duplicates('prior_vp_date').dropna(
            subset=[mid, 'prior_vp_poc']
        )
        for th in (5, 10, 15):
            col = f'poc_coincides_{mid}_{th}pt'
            pct = daily[col].mean() * 100 if len(daily) > 0 else np.nan
            rows.append({
                'mid': mid,
                'analysis': 'descriptive_coincidence',
                'threshold_pt': th,
                'n_days': len(daily),
                'coincide_pct': round(pct, 1),
                'label': f'POC within {th}pt of {mid} — day-level',
            })

        # Additive edge within near-mid subset
        near_mid = df[f'near_{mid}_{PRIMARY_THRESHOLD}pt']
        into = df[f'trading_into_{mid}']
        coincide = df[f'poc_coincides_{mid}_10pt']
        base_subset = df[near_mid & into]
        for direction in ('long', 'short'):
            dir_base = base_subset[base_subset['direction'] == direction]
            for coincidence_flag in (True, False):
                sub = dir_base[coincide.reindex(dir_base.index, fill_value=False)
                               == coincidence_flag]
                stats = compute_segment_stats(
                    sub,
                    f'{mid} | {direction} | trading_into | '
                    f'POC_coincide={"yes" if coincidence_flag else "no"}',
                )
                stats.update({
                    'mid': mid,
                    'analysis': 'additive_with_poc',
                    'threshold_pt': PRIMARY_THRESHOLD,
                    'direction': direction,
                    'poc_coincides_10pt': coincidence_flag,
                })
                rows.append(stats)
    return pd.DataFrame(rows)


# =============================================================================
# Permutation testing (primary pre-registered tests)
# =============================================================================

def run_primary_permutation_tests(
    df: pd.DataFrame, enriched: pd.DataFrame, n_perms: int
) -> pd.DataFrame:
    print(f'\n=== Primary permutation tests ({n_perms} perms, Bonferroni α=0.0125) ===')
    rng = np.random.default_rng(42)
    tests = []

    for mid in MIDS:
        near_col = f'near_{mid}_{PRIMARY_THRESHOLD}pt'
        into_col = f'trading_into_{mid}'

        def fn_into_short(d, mid=mid, near_col=near_col, into_col=into_col):
            return d[(d['direction'] == 'short') & d[near_col] & d[into_col]]

        def fn_into_long(d, mid=mid, near_col=near_col, into_col=into_col):
            return d[(d['direction'] == 'long') & d[near_col] & d[into_col]]

        tests.append((
            f'A | shorts | trading_into | near {PRIMARY_THRESHOLD}pt | {mid}',
            fn_into_short, df, 'primary',
        ))
        tests.append((
            f'A | longs | trading_into | near {PRIMARY_THRESHOLD}pt | {mid}',
            fn_into_long, df, 'primary',
        ))

    # Sub-study C primary: first_fvgc on each mid (primary combo)
    for mid in MIDS:
        col = f'first_fvgc_{mid}_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}'
        if col not in enriched.columns:
            continue

        def fn_c(d, col=col):
            return d[d[col]]

        tests.append((
            f'C | first_fvgc_reversal | {mid} | tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}',
            fn_c,
            enriched[enriched['outcome'].isin(['win', 'loss'])].copy(),
            'primary',
        ))

    # Sub-study D additive POC edge (shorts only — test on tradeable df)
    for mid in MIDS:
        near_col = f'near_{mid}_{PRIMARY_THRESHOLD}pt'
        into_col = f'trading_into_{mid}'
        coin_col = f'poc_coincides_{mid}_10pt'

        def fn_d(d, near_col=near_col, into_col=into_col, coin_col=coin_col):
            return d[(d['direction'] == 'short') & d[near_col]
                     & d[into_col] & d[coin_col]]

        tests.append((
            f'D | shorts | trading_into + POC_coincide 10pt | {mid}',
            fn_d, df, 'primary',
        ))

    results = []
    for name, fn, base_df, tier in tests:
        for metric in ('win_rate', 'profit_factor'):
            res = run_permutation_test(base_df, fn, metric, n_perms=n_perms, rng=rng)
            sig_bonf = res['p_value'] is not None and res['p_value'] < 0.0125
            results.append({
                'test': name,
                'metric': metric,
                'tier': tier,
                'n': res['n'],
                'actual': res['actual'],
                'baseline': res.get('baseline'),
                'mean_perm': res['mean_perm'],
                'p_value': res['p_value'],
                'p_bonferroni_4': (res['p_value'] * 4) if res['p_value'] is not None else None,
                'significant_bonferroni': sig_bonf,
                'significant_05': res.get('significant_05', False),
            })
            p_str = f'{res["p_value"]:.4f}' if res['p_value'] is not None else 'N/A'
            actual_str = f'{res["actual"]:.2f}' if res['actual'] is not None else 'N/A'
            marker = ' ***BONF***' if sig_bonf else (' *' if res.get('significant_05') else '')
            print(f'  {name[:60]:60s}  {metric:14s}  n={res["n"]:4d}  '
                  f'actual={actual_str:>6s}  p={p_str}{marker}')
    return pd.DataFrame(results)


# =============================================================================
# Special check: 2026-04-23 failed short
# =============================================================================

def check_2026_04_23(df: pd.DataFrame) -> str:
    target = pd.Timestamp('2026-04-23')
    rows = df[df['timestamp'].dt.date == target.date()]
    if rows.empty:
        return f'No trades found on {target.date()}.'
    lines = [f'Trades on {target.date()}:']
    for _, r in rows.iterrows():
        lines.append(
            f"  {r['timestamp']} | {r['direction']} @ {r['entry_price']} | "
            f"outcome={r['outcome']} | "
            f"pd_hl_mid={r.get('pd_hl_mid')} dist={r.get('dist_to_pd_hl_mid_pts'):.2f}pt | "
            f"pd_va_mid={r.get('pd_va_mid')} dist={r.get('dist_to_pd_va_mid_pts'):.2f}pt | "
            f"trading_into_hl={r['trading_into_pd_hl_mid']} "
            f"trading_into_va={r['trading_into_pd_va_mid']}"
        )
    return '\n'.join(lines)


# =============================================================================
# Output helpers
# =============================================================================

def print_table(title: str, df: pd.DataFrame):
    print(f'\n{"=" * 78}\n  {title}\n{"=" * 78}')
    if df is None or df.empty:
        print('  (no data)')
        return
    with pd.option_context('display.max_rows', 200,
                           'display.max_columns', None,
                           'display.width', 200):
        print(df.to_string(index=False))


def write_spot_check_md(spot_checks: list[dict], path: Path):
    lines = ['# Sub-study C spot checks (first 5 qualifying trades per mid)', '']
    lines.append('Manually verify each row against TradingView. The rejection wick '
                 'should sit in the 10-min window BEFORE entry, within 3pt of the '
                 'mid, with close on the away side of the approach direction.\n')
    if not spot_checks:
        lines.append('_No qualifying trades to spot-check._')
    else:
        current_mid = None
        for sc in spot_checks:
            if sc['mid'] != current_mid:
                current_mid = sc['mid']
                lines.append(f'\n## {current_mid}\n')
            lines.append(f"- **{sc['timestamp']}** | {sc['direction']} @ "
                         f"{sc['entry_price']} | {sc['mid']}="
                         f"{sc[f'{current_mid}_value']:.2f} | "
                         f"dist={sc[f'dist_to_{current_mid}_pts']:.2f}pt | "
                         f"outcome={sc['outcome']} | MFE={sc['mfe_r']}R "
                         f"MAE={sc['mae_r']}R | variant={sc['variant']}")
    path.write_text('\n'.join(lines))


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Prior-Day 50% Level Study')
    parser.add_argument('--perms', type=int, default=10_000, help='Primary perm count')
    parser.add_argument('--skip-c', action='store_true',
                        help='Skip Sub-study C (slow — scans 30s bars)')
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    HISTOGRAMS_DIR.mkdir(parents=True, exist_ok=True)

    print('=' * 78)
    print('  PRIOR-DAY 50% LEVEL STUDY')
    print('=' * 78)

    df = load_data()

    # Sub-study A
    a = run_substudy_a(df)
    print_table('SUB-STUDY A — REJECTION / DIRECTIONAL ASYMMETRY', a)
    a.to_csv(RESULTS_DIR / 'A_rejection_segmentation.csv', index=False)

    # Sub-study B
    b = run_substudy_b(df)
    print_table('SUB-STUDY B — TARGET MAGNET (reach rate)', b)
    b.to_csv(RESULTS_DIR / 'B_target_magnet.csv', index=False)

    # Sub-study C (requires scanning 30s bars)
    enriched = None
    if not args.skip_c:
        print('\nTagging trades with rejection events (this takes a minute)...')
        all_trades = pd.read_csv(TRADES_PATH)
        all_trades['timestamp'] = pd.to_datetime(all_trades['timestamp'])
        enriched = tag_trades_with_rejections(all_trades)
        enriched_tradeable = enriched[enriched['outcome'].isin(['win', 'loss'])]
        enriched_tradeable.to_csv(
            RESULTS_DIR / 'trades_with_rejection_flags.csv', index=False
        )
        c = run_substudy_c(df, enriched)
        print_table('SUB-STUDY C — REJECTION + FIRST-FVGC-REVERSAL', c['table'])
        c['table'].to_csv(RESULTS_DIR / 'C_rejection_fvgc.csv', index=False)
        write_spot_check_md(c['spot_checks'], RESULTS_DIR / 'C_spot_check.md')

    # Sub-study D
    d = run_substudy_d(df)
    print_table('SUB-STUDY D — POC CONFLUENCE', d)
    d.to_csv(RESULTS_DIR / 'D_poc_confluence.csv', index=False)

    # Primary permutation tests (Bonferroni-corrected)
    perm = run_primary_permutation_tests(
        df,
        enriched if enriched is not None else df.assign(
            **{f'first_fvgc_{m}_tau{int(PRIMARY_TAU)}_lb{PRIMARY_LOOKBACK_BARS}': False
               for m in MIDS}
        ),
        n_perms=args.perms,
    )
    perm.to_csv(RESULTS_DIR / 'permutation_results.csv', index=False)

    # 2026-04-23 special check
    check_txt = check_2026_04_23(df)
    print(f'\n{"=" * 78}\n  2026-04-23 SANITY CHECK\n{"=" * 78}\n{check_txt}')
    (RESULTS_DIR / '2026-04-23_check.txt').write_text(check_txt)

    print(f'\n\nAll results written to {RESULTS_DIR}/')
    print('Done.')


if __name__ == '__main__':
    main()
