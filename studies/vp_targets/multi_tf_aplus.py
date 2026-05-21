"""
Does the A+ filter (n_vp>=2 + VA-edge + variant!=PS) work on higher timeframes?

For each TF (15s, 30s, 1m, 2m, 3m, 5m):
  - Compute n_vp_targets + va_edge using same VP data (yesterday's RTH POC/VAH/VAL)
  - Filter to A+
  - Report n / WR / PF / expectancy
  - Yearly stability
  - Cross-reference with 30s A+ signals to find ADDITIONAL vs REDUNDANT signals

Question: do 1m / 2m / 3m fires give us new independent A+ trades, or are they
mostly same-day restatements of the 30s A+ trade?
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'results'

TF_DIRS = {
    '30s': 'baseline',
    '1m': 'baseline_1m',
    '2m': 'baseline_2m',
    '3m': 'baseline_3m',
    '15s': 'baseline_15s',
    '5m': 'baseline_5m',
}

vp = pl.read_csv(ROOT/'data/levels/daily_volume_profile.csv', try_parse_dates=True)


def load_tf(tf_dir: str) -> pl.DataFrame:
    """Load trades for a timeframe and tag with A+ filter columns."""
    t = (pl.read_csv(ROOT/f'studies/{tf_dir}/results/trades.csv', try_parse_dates=True)
         .filter((pl.col('outcome') != 'skip') & (pl.col('outcome') != 'ambiguous')))
    t = t.with_columns([
        pl.col('timestamp').dt.date().alias('date'),
        pl.col('timestamp').dt.year().alias('year'),
        (pl.col('timestamp').dt.year() >= 2023).alias('oos'),
    ])
    df = t.join(vp, on='date', how='left')
    sl = df['sl_dist'].to_numpy()
    il = (df['direction'].to_numpy() == 'long')
    ep = df['entry_price'].to_numpy()

    def rs(c):
        lvl = df[c].to_numpy().astype(float)
        d = lvl - ep
        return np.where(il, d, -d) / sl

    def iz(r):
        with np.errstate(invalid='ignore'):
            return (r >= 0.5) & (r <= 3.0)

    rpoc = rs('poc'); rvah = rs('vah'); rval = rs('val')
    n_vp = iz(rpoc).astype(int) + iz(rvah).astype(int) + iz(rval).astype(int)
    va_edge = np.where(il, iz(rval), iz(rvah))
    df = df.with_columns([
        pl.Series('n_vp', n_vp),
        pl.Series('va_edge', va_edge),
        pl.when(pl.col('outcome') == 'win').then(2.0).otherwise(-1.0).alias('pnl_R'),
    ])
    return df


def aplus(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter((pl.col('n_vp') >= 2) & pl.col('va_edge') & (pl.col('variant') != 'protected_swing'))


def stats(c: pl.DataFrame) -> dict:
    if c.height == 0:
        return {'n': 0}
    pnl = c['pnl_R'].to_numpy()
    pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()) if (pnl < 0).any() else float('inf')
    has_mfe = 'mfe_r' in c.columns
    has_hit2 = 'hit_2_0R' in c.columns
    return {
        'n': c.height,
        'wr_2R': round(float(c['hit_2_0R'].mean()), 3) if has_hit2 else round(float((c['outcome']=='win').mean()), 3),
        'PF_at_2R': round(pf, 2),
        'expR_at_2R': round(float(pnl.mean()), 3),
        'sumR_at_2R': round(float(pnl.sum()), 1),
        'mfe_mean': round(float(np.nanmean(c['mfe_r'].to_numpy())), 2) if has_mfe else None,
        'mfe_med': round(float(np.nanmedian(c['mfe_r'].to_numpy())), 2) if has_mfe else None,
        'sl_med': round(float(np.nanmedian(c['sl_dist'].to_numpy())), 1),
    }


# === A+ stats per TF ===
print('=' * 90)
print('A+ FILTER (n_vp>=2 & VA-edge & variant!=PS) ACROSS TIMEFRAMES')
print('=' * 90)
tf_data = {}
results = []
for tf, dir in TF_DIRS.items():
    df = load_tf(dir)
    A = aplus(df)
    tf_data[tf] = (df, A)
    n_dates_raw = df['date'].n_unique()
    n_dates_aplus = A['date'].n_unique()
    aplus_per_yr = A.height / df['year'].n_unique()
    row = {'TF': tf, 'baseline_n': df.height, 'A+_n': A.height,
           'A+_share_%': round(100*A.height/df.height, 1),
           'days_covered': n_dates_raw, 'A+_days': n_dates_aplus,
           'A+_per_yr': round(aplus_per_yr, 1)}
    row.update(stats(A))
    results.append(row)
print(pl.DataFrame(results).to_pandas().to_string(index=False))
print()

# === Yearly A+ counts per TF ===
print('=' * 90)
print('A+ SETUPS PER YEAR PER TF')
print('=' * 90)
years = sorted(tf_data['30s'][0]['year'].unique().to_list())
header = 'year   ' + '  '.join(f'{tf:>6s}' for tf in TF_DIRS.keys())
print(header)
for y in years:
    line = f'{y}  '
    for tf in TF_DIRS.keys():
        _, A = tf_data[tf]
        cnt = A.filter(pl.col('year') == y).height
        line += f'  {cnt:5d}'
    print(line)
print()

# === Same-date overlap with 30s ===
print('=' * 90)
print('SAME-DATE OVERLAP WITH 30s A+ (are additional TFs independent or redundant?)')
print('=' * 90)
_, A30 = tf_data['30s']
A30_dates = set(A30['date'].to_list())
A30_dir_dates = set((d, dirn) for d, dirn in zip(A30['date'].to_list(), A30['direction'].to_list()))

print(f'30s A+: {A30.height} trades on {len(A30_dates)} unique dates')
print()
overlap_rows = []
for tf in ['1m', '2m', '3m']:
    _, A = tf_data[tf]
    if A.height == 0: continue
    tf_dates = A['date'].to_list()
    tf_dirs = A['direction'].to_list()
    tf_dir_dates = list(zip(tf_dates, tf_dirs))
    # Match date+direction (correlated to 30s on that day)
    same_date_same_dir = sum(1 for dd in tf_dir_dates if dd in A30_dir_dates)
    same_date_only = sum(1 for d in tf_dates if d in A30_dates) - same_date_same_dir
    unique_dates = sum(1 for d in tf_dates if d not in A30_dates)
    overlap_rows.append({
        'TF': tf,
        'A+_total': A.height,
        'same_date_same_dir_as_30s': same_date_same_dir,
        'same_date_diff_dir': same_date_only,
        'INDEPENDENT_new_dates': unique_dates,
        'indep_rate_%': round(100*unique_dates/A.height, 1),
    })
print(pl.DataFrame(overlap_rows).to_pandas().to_string(index=False))
print()

# === If we combined all TFs and deduplicated by date+direction, what do we get? ===
print('=' * 90)
print('UNION OF ALL TFs A+ SIGNALS, DEDUPED BY (DATE, DIRECTION)')
print('=' * 90)
all_signals = []
for tf in ['30s', '1m', '2m', '3m']:
    _, A = tf_data[tf]
    for r in A.iter_rows(named=True):
        all_signals.append({'date': r['date'], 'direction': r['direction'], 'tf': tf,
                            'timestamp': r['timestamp'], 'pnl_R': r['pnl_R'],
                            'hit_2_0R': r.get('hit_2_0R', r['outcome']=='win'),
                            'mfe_r': r.get('mfe_r', None),
                            'sl_dist': r['sl_dist'], 'oos': r['oos'], 'year': r['year']})
all_df = pl.DataFrame(all_signals)
# Keep only the EARLIEST fire per (date, direction)
dedup = all_df.sort('timestamp').group_by(['date', 'direction']).agg(pl.all().first())
print(f'Union: {all_df.height} signals; dedup by (date, direction) = {dedup.height} distinct setups')
print(f'30s alone: {tf_data["30s"][1].height}')
print(f'Net new from higher TFs: {dedup.height - tf_data["30s"][1].height}')
print()
print('TF-source of the first-fire winner:')
print(dedup.group_by('tf').agg(pl.len()).sort('len', descending=True).to_pandas().to_string(index=False))
print()
print('Pooled stats on dedup set:')
pnl = dedup['pnl_R'].to_numpy()
pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum())
print(f'  n={dedup.height}  PF={pf:.2f}  expR={pnl.mean():+.3f}R  WR={float((pnl>0).mean())*100:.1f}%')
oos = dedup.filter(pl.col('oos'))
pnl_o = oos['pnl_R'].to_numpy()
pf_o = pnl_o[pnl_o > 0].sum() / abs(pnl_o[pnl_o < 0].sum()) if (pnl_o<0).any() else float('inf')
print(f'  OOS n={oos.height}  PF={pf_o:.2f}  expR={pnl_o.mean():+.3f}R  WR={float((pnl_o>0).mean())*100:.1f}%')

# Save
all_df.write_csv(OUT / 'multi_tf_aplus_all.csv')
dedup.write_csv(OUT / 'multi_tf_aplus_dedup.csv')
pl.DataFrame(results).write_csv(OUT / 'multi_tf_aplus_per_tf.csv')
print()
print('Saved: multi_tf_aplus_per_tf.csv, multi_tf_aplus_all.csv, multi_tf_aplus_dedup.csv')
