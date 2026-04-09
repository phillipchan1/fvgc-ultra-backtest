#!/usr/bin/env python3
"""
Summarize trades_with_levels.csv — WR, PF, verification export.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from data.levels.level_registry import groups_in_order  # noqa: E402

NY_TZ = pytz.timezone('America/New_York')

INPUT_PATH = ROOT / 'data' / 'levels' / 'trades_with_levels.csv'
LIQUIDITY_PATH = ROOT / 'data' / 'levels' / 'liquidity_levels.csv'
TRADING_DAYS_PATH = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
RESULTS_DIR = ROOT / 'data' / 'levels' / 'results'


def macro_window_from_ts(ts: pd.Timestamp) -> int:
    t = ts.timetz().replace(tzinfo=None) if hasattr(ts, 'timetz') else ts.time()
    m = (t.hour - 9) * 60 + (t.minute - 30) + t.second / 60.0
    if m < 15:
        return 1
    if m < 30:
        return 2
    if m < 45:
        return 3
    if m < 60:
        return 4
    return 5


def profit_factor(pnl: pd.Series) -> float:
    gw = pnl[pnl > 0].sum()
    gl = pnl[pnl < 0].sum()
    if gl == 0:
        return float('inf') if gw > 0 else float('nan')
    return float(gw / abs(gl))


def summarize_subset(df: pd.DataFrame, label: str) -> dict[str, Any]:
    sub = df[df['outcome'].isin(['win', 'loss'])]
    n = len(sub)
    wins = int((sub['outcome'] == 'win').sum())
    losses = int((sub['outcome'] == 'loss').sum())
    wr = 100.0 * wins / n if n else float('nan')
    pf = profit_factor(sub['pnl'])
    return {
        'bucket': label,
        'n': n,
        'wins': wins,
        'losses': losses,
        'win_rate_pct': wr,
        'profit_factor': pf,
    }


def fmt_val(v: Any) -> str:
    if isinstance(v, float):
        if math.isnan(v):
            return ''
        if math.isinf(v):
            return 'inf'
        return str(round(v, 4))
    return str(v)


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print('(empty)')
        return
    cols = list(rows[0].keys())
    print('\t'.join(str(c) for c in cols))
    for r in rows:
        print('\t'.join(fmt_val(r[c]) for c in cols))


def _fmt_pf_display(pf: float) -> str:
    if math.isnan(pf):
        return '  nan'
    if math.isinf(pf) and pf > 0:
        return '   inf'
    return f'{pf:6.2f}'


def print_wr_pf_table(title: str, rows: list[dict[str, Any]], bucket_width: int = 28) -> None:
    """Readable WR/PF table (bucket, n, wins, losses, WR%, PF)."""
    print()
    print(f'=== {title} ===')
    bw = max(22, min(bucket_width, 56))
    hdr = f'{"bucket":<{bw}} {"n":>6} {"wins":>7} {"losses":>8} {"WR%":>8} {"PF":>8}'
    print(hdr)
    print('-' * len(hdr))
    for r in rows:
        b = str(r.get('bucket', ''))[:bw]
        n = int(r.get('n', 0))
        wins = int(r.get('wins', 0))
        losses = int(r.get('losses', 0))
        wr = r.get('win_rate_pct', float('nan'))
        pf = r.get('profit_factor', float('nan'))
        wr_s = f'{wr:6.1f}' if not (isinstance(wr, float) and math.isnan(wr)) else '   nan'
        print(f'{b:<{bw}} {n:6d} {wins:7d} {losses:8d} {wr_s:>8} {_fmt_pf_display(float(pf))}')


def rows_plus_baseline(bucket_rows: list[dict[str, Any]], dfx: pd.DataFrame) -> list[dict[str, Any]]:
    base = summarize_subset(dfx, 'baseline')
    return bucket_rows + [base]


def build_cluster_alc_crosstab(dfx: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Short trades only. Same masks as cluster study:
    - short_macro_w1: macro_window == 1
    - short_prior_close_low: prior_day_close_position notna and < 0.25
    Cross ALC buckets 0, 1, 2, 3+; plus either_cluster / neither_cluster.
    """
    if 'available_level_count' not in dfx.columns:
        return []

    shorts = dfx[dfx['direction'].astype(str).str.lower() == 'short'].copy()
    if shorts.empty:
        return []

    def subset_alc(frame: pd.DataFrame, lab: str) -> pd.DataFrame:
        ac = frame['available_level_count']
        if lab == '0':
            return frame[ac == 0]
        if lab == '1':
            return frame[ac == 1]
        if lab == '2':
            return frame[ac == 2]
        return frame[ac >= 3]

    mask_mw = shorts['macro_window'] == 1
    mask_pcl = shorts['prior_day_close_position'].notna() & (shorts['prior_day_close_position'] < 0.25)
    mask_either = mask_mw | mask_pcl
    mask_neither = ~mask_either

    specs: list[tuple[str, pd.Series]] = [
        ('short_macro_w1', mask_mw),
        ('short_prior_close_low', mask_pcl),
        ('either_cluster', mask_either),
        ('neither_cluster', mask_neither),
    ]

    rows_out: list[dict[str, Any]] = []
    for cl_name, m in specs:
        sub = shorts[m]
        for alc_lab in ('0', '1', '2', '3+'):
            cell = subset_alc(sub, alc_lab)
            s = summarize_subset(cell, f'{cl_name}|alc_{alc_lab}')
            rows_out.append({
                'cluster': cl_name,
                'alc_bucket': alc_lab,
                'n': s['n'],
                'wins': s['wins'],
                'losses': s['losses'],
                'win_rate_pct': s['win_rate_pct'],
                'profit_factor': s['profit_factor'],
            })
    return rows_out


def diagnose_no_valid_sample(
    trades_df: pd.DataFrame,
    liquidity_df: pd.DataFrame,
    n: int = 10,
    *,
    random_state: int = 42,
) -> None:
    """
    Sample trades with no_valid_levels=True and show nearest raw liquidity (swept_pre_rth=False, price set)
    vs entry to see if levels exist beyond 3R or data is sparse.
    """
    if 'no_valid_levels' not in trades_df.columns:
        print('\n=== Diagnostic: no_valid_levels sample (skipped — column missing) ===\n')
        return

    nv = trades_df['no_valid_levels']
    if nv.dtype == object:
        mask = nv.astype(str).str.strip().str.lower().isin(('true', '1', 'yes'))
    else:
        mask = nv.fillna(False).astype(bool)

    pool = trades_df[mask]
    if pool.empty:
        print('\n=== Diagnostic: no_valid_levels sample ===\n(no trades with no_valid_levels=True)\n')
        return

    k = min(n, len(pool))
    sample = pool.sample(k, random_state=random_state)

    liqu = liquidity_df.copy()
    if 'date' not in liqu.columns:
        print('\n=== Diagnostic: liquidity_levels.csv missing date column ===\n')
        return
    liqu['date'] = pd.to_datetime(liqu['date']).dt.date

    print()
    print('=== Diagnostic: random no_valid_levels trades vs raw liquidity pool ===')
    print(
        '(Pool per date: swept_pre_rth=False, price not null — same pre-RTH gate as enrichment filter; '
        'distances are in trade direction: long = levels above entry, short = below.)',
    )
    print()

    for _, tr in sample.iterrows():
        d = tr['_date']
        entry = float(tr['entry_price'])
        direction = str(tr['direction']).lower()
        sl_raw = tr.get('sl_dist')
        try:
            sl_f = float(sl_raw) if sl_raw is not None and not pd.isna(sl_raw) else None
        except (TypeError, ValueError):
            sl_f = None
        if sl_f is not None and sl_f <= 0:
            sl_f = None

        day = liqu[liqu['date'] == d]
        spr = day['swept_pre_rth']
        spr_ok = spr.eq(False) | (spr.astype(str).str.strip().str.lower() == 'false')
        day = day[spr_ok & day['price'].notna()]

        cand: list[tuple[float, float, str, str]] = []
        for _, row in day.iterrows():
            p = float(row['price'])
            g = str(row.get('group', ''))
            ln = str(row.get('level_name', ''))
            if direction == 'long':
                if p > entry:
                    cand.append((p - entry, p, ln, g))
            else:
                if p < entry:
                    cand.append((entry - p, p, ln, g))

        cand.sort(key=lambda x: x[0])
        top3 = cand[:3]

        print(f"date={d}  direction={direction}  entry={entry:.2f}  sl_dist={sl_f if sl_f is not None else 'n/a'}")
        print(f"  raw pool size (swept_pre_rth=False, price ok): {len(day)}  in-direction candidates: {len(cand)}")
        if not top3:
            print('  (no levels in trade direction above/below entry)')
        else:
            for i, (pts, price, ln, g) in enumerate(top3, 1):
                r_str = f'{pts / sl_f:.2f}R' if sl_f else 'n/a'
                print(f'  #{i}  {ln[:40]:<40}  group={g:<14}  pts={pts:8.2f}  R={r_str}')
        print()


def main() -> None:
    print('Loading trades...')
    df = pd.read_csv(INPUT_PATH)
    print('Loading liquidity_levels...')
    liquidity_df = pd.read_csv(LIQUIDITY_PATH)

    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date

    df = df.copy()
    df['_ts'] = pd.to_datetime(df['timestamp'])
    if df['_ts'].dt.tz is None:
        df['_ts'] = df['_ts'].dt.tz_localize(NY_TZ, ambiguous='infer', nonexistent='shift_forward')
    else:
        df['_ts'] = df['_ts'].dt.tz_convert(NY_TZ)
    df['_date'] = df['_ts'].dt.date
    df['macro_window'] = df['_ts'].apply(macro_window_from_ts)

    pos = td.set_index('date')['prior_day_close_position']
    df['prior_day_close_position'] = df['_date'].map(pos)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    n_all = len(df)
    print('=' * 60)
    print('Level context (full dataset)')
    print('=' * 60)
    print(f'Total trades analyzed: {n_all}')
    if 'available_level_count' in df.columns:
        alc = df['available_level_count']
        avg_alc = float(alc.mean()) if alc.notna().any() else float('nan')
        print(f'Average available_level_count (per trade): {avg_alc:.4f}')
    else:
        print('Average available_level_count: (column missing)')
    if 'no_valid_levels' in df.columns:
        nv = df['no_valid_levels']
        if nv.dtype == object:
            nv_true = nv.astype(str).str.strip().str.lower().isin(('true', '1', 'yes'))
        else:
            nv_true = nv.fillna(False).astype(bool)
        pct_nv = 100.0 * float(nv_true.sum()) / float(n_all) if n_all else 0.0
        print(f'% of trades with no_valid_levels = True: {pct_nv:.2f}%')
    else:
        print('% no_valid_levels: (column missing)')
    if 'available_level_count' in df.columns:
        a = df['available_level_count'].dropna()
        print('Distribution of available_level_count (trades per bucket):')
        for i in range(5):
            c = int((a == i).sum())
            print(f'  {i}: {c}')
        c5 = int((a >= 5).sum())
        print(f'  5+: {c5}')
        n_na = int(df['available_level_count'].isna().sum())
        if n_na:
            print(f'  (missing available_level_count: {n_na})')
    print('=' * 60)

    dfx = df[df['outcome'].isin(['win', 'loss'])].copy()

    # --- magnet R buckets (CSV + store rows for stdout) ---
    rows_mag: list[dict] = []
    nv = dfx[dfx['no_valid_levels'] == True]  # noqa: E712
    row_no_valid = summarize_subset(nv, 'no_valid_levels') if len(nv) else None
    mvalid = dfx[dfx['no_valid_levels'] == False]  # noqa: E712
    for lo, hi, lab in [(0, 1, '[0-1)'), (1, 2, '[1-2)'), (2, 3, '[2-3)'), (3, float('inf'), '[3+]')]:
        m = mvalid[mvalid['nearest_magnet_R'].notna()]
        m = m[(m['nearest_magnet_R'] >= lo) & (m['nearest_magnet_R'] < hi)]
        if len(m):
            rows_mag.append(summarize_subset(m, lab))
    if row_no_valid is not None:
        rows_mag.append(row_no_valid)

    pd.DataFrame(rows_mag).to_csv(RESULTS_DIR / 'summary_by_magnet_R_bucket.csv', index=False)

    # --- path_clear ---
    pc_rows = []
    for v, lab in [(True, 'path_clear_True'), (False, 'path_clear_False')]:
        m = dfx[dfx['path_clear'] == v]
        if len(m):
            pc_rows.append(summarize_subset(m, lab))
    pd.DataFrame(pc_rows).to_csv(RESULTS_DIR / 'summary_by_path_clear.csv', index=False)

    # --- obstruction_count ---
    ob_rows = []
    for lab, cond in [('0', dfx['obstruction_count'] == 0), ('1', dfx['obstruction_count'] == 1), ('2+', dfx['obstruction_count'] >= 2)]:
        m = dfx[cond]
        if len(m):
            ob_rows.append(summarize_subset(m, f'obstruction_{lab}'))
    pd.DataFrame(ob_rows).to_csv(RESULTS_DIR / 'summary_by_obstruction_count.csv', index=False)

    # --- magnet group (valid ≤3R only — the actionable subset for a continuation model) ---
    # magnet_valid=True means the nearest level in trade direction is within 3R.
    # This is the correct lens: "when I had a reachable draw, which level type led to
    # the best outcome?" Trades where the level was >3R away are excluded because
    # targeting a level 4-8R away is not how this model operates.
    dfx_valid = dfx[dfx['magnet_valid'] == True]
    mg_rows = []
    for g in sorted(dfx_valid['nearest_magnet_group'].dropna().unique()):
        m = dfx_valid[dfx_valid['nearest_magnet_group'] == g]
        if len(m):
            mg_rows.append(summarize_subset(m, str(g)))
    pd.DataFrame(mg_rows).to_csv(RESULTS_DIR / 'summary_by_magnet_group.csv', index=False)

    # Also produce unfiltered version for reference
    mg_rows_all = []
    for g in sorted(dfx['nearest_magnet_group'].dropna().unique()):
        m = dfx[dfx['nearest_magnet_group'] == g]
        if len(m):
            mg_rows_all.append(summarize_subset(m, str(g)))
    pd.DataFrame(mg_rows_all).to_csv(RESULTS_DIR / 'summary_by_magnet_group_all.csv', index=False)

    # --- macro_window × nearest_magnet_group (magnet_valid=True only) ---
    WINDOW_LABELS = {1: '9:30-9:45', 2: '9:45-10:00', 3: '10:00-10:15'}
    macro_mag_rows: list[dict] = []
    for w in sorted(WINDOW_LABELS.keys()):
        wdf = dfx_valid[dfx_valid['macro_window'] == w]
        wlabel = WINDOW_LABELS[w]
        for g in sorted(dfx_valid['nearest_magnet_group'].dropna().unique()):
            m = wdf[wdf['nearest_magnet_group'] == g]
            if len(m) >= 5:  # min sample to be meaningful
                r = summarize_subset(m, f'{wlabel} | {g}')
                r['macro_window'] = wlabel
                r['magnet_group'] = g
                macro_mag_rows.append(r)
        # Window baseline (all magnet_valid=True trades in this window)
        if len(wdf):
            base_r = summarize_subset(wdf, f'{wlabel} | baseline')
            base_r['macro_window'] = wlabel
            base_r['magnet_group'] = 'baseline'
            macro_mag_rows.append(base_r)
    pd.DataFrame(macro_mag_rows).to_csv(RESULTS_DIR / 'summary_by_macro_x_magnet.csv', index=False)

    # Also: standalone WR by macro_window (all directions, magnet_valid=True)
    mw_rows: list[dict] = []
    for w in sorted(WINDOW_LABELS.keys()):
        m = dfx_valid[dfx_valid['macro_window'] == w]
        if len(m):
            mw_rows.append(summarize_subset(m, WINDOW_LABELS[w]))
    pd.DataFrame(mw_rows).to_csv(RESULTS_DIR / 'summary_by_macro_window.csv', index=False)

    # --- confluence ---
    cf_rows = []
    for lab, lo, hi in [('1', 1, 1), ('2', 2, 2), ('3+', 3, None)]:
        if hi is None:
            m = dfx[dfx['level_confluence_count'] >= lo]
        else:
            m = dfx[(dfx['level_confluence_count'] >= lo) & (dfx['level_confluence_count'] <= hi)]
        if len(m):
            cf_rows.append(summarize_subset(m, f'confluence_{lab}'))
    pd.DataFrame(cf_rows).to_csv(RESULTS_DIR / 'summary_by_confluence.csv', index=False)

    # --- available_level_count ---
    alc_rows = []
    if 'available_level_count' in dfx.columns:
        for lab, lo, hi in [('0', 0, 0), ('1', 1, 1), ('2', 2, 2), ('3+', 3, None)]:
            if hi is None:
                m = dfx[dfx['available_level_count'] >= 3]
            else:
                m = dfx[dfx['available_level_count'] == lo]
            if len(m):
                alc_rows.append(summarize_subset(m, f'alc_{lab}'))
    pd.DataFrame(alc_rows).to_csv(RESULTS_DIR / 'summary_by_available_level_count.csv', index=False)

    # --- cluster × available_level_count (shorts only; same masks as cluster grids) ---
    cl_alc_rows = build_cluster_alc_crosstab(dfx)
    if cl_alc_rows:
        pd.DataFrame(cl_alc_rows).to_csv(RESULTS_DIR / 'summary_by_cluster_and_alc.csv', index=False)

    # --- existing clusters ---
    cl_flat: list[dict] = []
    base = dfx

    def add_cluster_grid(cluster_name: str, ins_mask: pd.Series) -> None:
        ins = base[ins_mask & (base['direction'] == 'short')]
        outs = base[(~ins_mask) & (base['direction'] == 'short')]
        for cohort_name, cohort_df in [('in_cluster', ins), ('out_cluster', outs)]:
            for mv in [True, False]:
                for pc in [True, False]:
                    m = cohort_df[(cohort_df['magnet_valid'] == mv) & (cohort_df['path_clear'] == pc)]
                    if len(m):
                        r = summarize_subset(m, f'{cluster_name}_{cohort_name}')
                        r['cluster'] = cluster_name
                        r['cohort'] = cohort_name
                        r['magnet_valid'] = mv
                        r['path_clear'] = pc
                        cl_flat.append(r)
            for pc in [True, False]:
                m = cohort_df[cohort_df['magnet_valid'].isna() & (cohort_df['path_clear'] == pc)]
                if len(m):
                    r = summarize_subset(m, f'{cluster_name}_{cohort_name}_mv_na')
                    r['cluster'] = cluster_name
                    r['cohort'] = cohort_name
                    r['magnet_valid'] = 'null'
                    r['path_clear'] = pc
                    cl_flat.append(r)

    mask_a = dfx['macro_window'] == 1
    add_cluster_grid('short_macro_w1', mask_a)
    mask_b = dfx['prior_day_close_position'].notna() & (dfx['prior_day_close_position'] < 0.25)
    add_cluster_grid('short_prior_close_low', mask_b)

    pd.DataFrame(cl_flat).to_csv(RESULTS_DIR / 'summary_by_existing_clusters.csv', index=False)

    # --- trades_verified ---
    groups = groups_in_order()
    g_index = {g: i for i, g in enumerate(groups)}

    def sort_key(col: str) -> tuple:
        base = col.replace('_nearest_price', '')
        return (g_index.get(base, 999), col)

    price_cols = sorted(
        [c for c in df.columns if c.endswith('_nearest_price') and not c.startswith('nearest_')],
        key=sort_key,
    )

    ver_cols = [
        'timestamp', 'direction', 'entry_price', 'sl', 'tp', 'sl_dist', 'outcome', 'pnl',
        'nearest_magnet_pts', 'nearest_magnet_R', 'nearest_magnet_group', 'magnet_valid',
        'obstruction_count', 'path_clear', 'level_swept_before_entry',
    ] + price_cols + [c.replace('_nearest_price', '_nearest_pts') for c in price_cols]

    ver = df.copy()
    ver = ver.sort_values(['_date', '_ts'])
    ver = ver[[c for c in ver_cols if c in ver.columns]]
    ver.to_csv(RESULTS_DIR / 'trades_verified.csv', index=False)

    print('\nWrote summary CSVs and trades_verified.csv to', RESULTS_DIR)

    # --- Diagnostic (after CSV writes, before formatted WR/PF tables) ---
    diagnose_no_valid_sample(df, liquidity_df, n=10)

    # --- Formatted WR/PF tables (baseline = all win/loss trades) ---
    print_wr_pf_table('WR by nearest_magnet_R bucket', rows_plus_baseline(rows_mag, dfx))
    print_wr_pf_table('WR by path_clear', rows_plus_baseline(pc_rows, dfx))
    print_wr_pf_table('WR by obstruction_count', rows_plus_baseline(ob_rows, dfx))
    print_wr_pf_table('WR by nearest_magnet_group (magnet_valid=True, ≤3R)', rows_plus_baseline(mg_rows, dfx_valid))
    print_wr_pf_table('WR by nearest_magnet_group (ALL distances, reference)', rows_plus_baseline(mg_rows_all, dfx))

    if macro_mag_rows:
        print_wr_pf_table(
            'WR by macro_window × nearest_magnet_group (magnet_valid=True)',
            macro_mag_rows,
            bucket_width=40,
        )
        print_wr_pf_table('WR by macro_window only (magnet_valid=True)', rows_plus_baseline(mw_rows, dfx_valid))
    print_wr_pf_table('WR by level_confluence_count', rows_plus_baseline(cf_rows, dfx))
    print_wr_pf_table('WR by available_level_count', rows_plus_baseline(alc_rows, dfx))

    if cl_alc_rows:
        shorts_dfx = dfx[dfx['direction'].astype(str).str.lower() == 'short']
        cl_alc_print = [
            {
                'bucket': f"{r['cluster']} | alc_{r['alc_bucket']}",
                'n': r['n'],
                'wins': r['wins'],
                'losses': r['losses'],
                'win_rate_pct': r['win_rate_pct'],
                'profit_factor': r['profit_factor'],
            }
            for r in cl_alc_rows
        ]
        print_wr_pf_table(
            'WR cluster × available_level_count (shorts; baseline = all shorts win/loss)',
            rows_plus_baseline(cl_alc_print, shorts_dfx),
            bucket_width=48,
        )

    # Cluster table: compact label + same WR/PF columns
    cl_print: list[dict[str, Any]] = []
    for r in cl_flat:
        lab = f"{r.get('cluster')}_{r.get('cohort')}_mv{r.get('magnet_valid')}_pc{r.get('path_clear')}"
        cl_print.append({
            'bucket': lab,
            'n': r['n'],
            'wins': r['wins'],
            'losses': r['losses'],
            'win_rate_pct': r['win_rate_pct'],
            'profit_factor': r['profit_factor'],
        })
    print_wr_pf_table(
        'WR by existing clusters (short cohorts)',
        rows_plus_baseline(cl_print, dfx),
        bucket_width=52,
    )

    print(f'\nDone. trades_verified: {len(ver)} rows.')


if __name__ == '__main__':
    main()
