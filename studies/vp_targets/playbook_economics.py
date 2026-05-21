"""
Follow-up: turn the n_vp_targets signal into a play.

Computes:
  - PF, expectancy(R), win rate at 1R/2R, R distribution for each bucket
  - MFE distribution per bucket (where do winners actually peak?)
  - Frequency / cadence (gap between qualifying setups)
  - Fixed-TP sweep: 1R, 1.5R, 2R, 2.5R, 3R — which TP maximises expectancy?
  - Confluence stacks on top of n_vp>=2 (direction-matched VA, variant, gap)
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'results'

trades = pl.read_csv(ROOT / 'studies/baseline/results/trades.csv', try_parse_dates=True).filter(pl.col('outcome') != 'skip')
vp = pl.read_csv(ROOT / 'data/levels/daily_volume_profile.csv', try_parse_dates=True)
fm_v1 = pl.read_parquet(ROOT / 'studies/discovery_2R_hits/results/feature_matrix.parquet')

trades = trades.with_columns([
    pl.col('timestamp').dt.date().alias('date'),
    pl.col('timestamp').dt.year().alias('year'),
    (pl.col('timestamp').dt.year() <= 2022).alias('is_in_is'),
    (pl.col('timestamp').dt.year() >= 2023).alias('is_in_oos'),
])
df = trades.join(vp, on='date', how='left').join(
    fm_v1.select(['timestamp', 'macro_window', 'vixy_regime', 'gap_bucket', 'range_regime']),
    on='timestamp', how='left',
)

sl = df['sl_dist'].to_numpy()
is_long = (df['direction'].to_numpy() == 'long')
ep = df['entry_price'].to_numpy()


def r_signed(level_col):
    lvl = df[level_col].to_numpy().astype(float)
    diff = lvl - ep
    return np.where(is_long, diff, -diff) / sl


r_poc = r_signed('poc'); r_vah = r_signed('vah'); r_val = r_signed('val')


def in_zone(rs):
    with np.errstate(invalid='ignore'):
        return (rs >= 0.5) & (rs <= 3.0)


poc_in, vah_in, val_in = in_zone(r_poc), in_zone(r_vah), in_zone(r_val)
n_vp = poc_in.astype(int) + vah_in.astype(int) + val_in.astype(int)

# Direction-matched VA edge: VAL for long, VAH for short, within 0.5-3R
va_edge = np.where(is_long, val_in, vah_in)

df = df.with_columns([
    pl.Series('n_vp_targets', n_vp),
    pl.Series('va_edge', va_edge),
    pl.Series('r_poc', r_poc), pl.Series('r_vah', r_vah), pl.Series('r_val', r_val),
])

# --- R-per-trade under the fixed 1R/2R baseline ---
# baseline rule: stop = -1R, TP = +2R, hit whichever first.
# pnl_R: +2 for outcome=='win', -1 for 'loss', exclude 'ambiguous' (n=6)
df = df.filter(pl.col('outcome') != 'ambiguous')
df = df.with_columns(
    pl.when(pl.col('outcome') == 'win').then(2.0).otherwise(-1.0).alias('pnl_R'),
)


def cohort_stats(frame: pl.DataFrame, label: str, era_col: str | None = None) -> dict:
    if era_col is not None:
        frame = frame.filter(pl.col(era_col))
    n = frame.height
    if n == 0:
        return {'cohort': label, 'era': era_col or 'pooled', 'n': 0}
    wins = frame.filter(pl.col('pnl_R') > 0)['pnl_R'].sum()
    losses = frame.filter(pl.col('pnl_R') < 0)['pnl_R'].sum()  # negative
    pf = (wins / abs(losses)) if losses != 0 else float('inf')
    expectancy = frame['pnl_R'].mean()
    win_rate_2R = frame['hit_2_0R'].mean()
    win_rate_1R = frame['hit_1_0R'].mean()
    mfe_med = float(np.nanmedian(frame['mfe_r'].to_numpy()))
    mfe_p75 = float(np.nanpercentile(frame['mfe_r'].to_numpy(), 75))
    mfe_p25 = float(np.nanpercentile(frame['mfe_r'].to_numpy(), 25))
    return {
        'cohort': label,
        'era': era_col or 'pooled',
        'n': n,
        'PF': round(pf, 2),
        'expectancy_R': round(expectancy, 3),
        'wr_1R': round(win_rate_1R, 3),
        'wr_2R': round(win_rate_2R, 3),
        'mfe_p25': round(mfe_p25, 2),
        'mfe_med': round(mfe_med, 2),
        'mfe_p75': round(mfe_p75, 2),
    }


print('=' * 80)
print('PLAY ECONOMICS — n_vp_targets cohort breakdown')
print('=' * 80)

cohorts = [
    ('all (sanity)',           df),
    ('n_vp==0',                df.filter(pl.col('n_vp_targets') == 0)),
    ('n_vp==1',                df.filter(pl.col('n_vp_targets') == 1)),
    ('n_vp==2',                df.filter(pl.col('n_vp_targets') == 2)),
    ('n_vp>=2',                df.filter(pl.col('n_vp_targets') >= 2)),
    ('n_vp>=2 & variant!=PS',  df.filter((pl.col('n_vp_targets') >= 2) & (pl.col('variant') != 'protected_swing'))),
    ('n_vp>=2 & VA-edge',      df.filter((pl.col('n_vp_targets') >= 2) & pl.col('va_edge'))),
    ('n_vp>=2 & VA-edge & variant!=PS', df.filter((pl.col('n_vp_targets') >= 2) & pl.col('va_edge') & (pl.col('variant') != 'protected_swing'))),
    ('VA-edge only',           df.filter(pl.col('va_edge'))),
    ('skip rule applied (drop n_vp==0 if variant!=PS)',
                                df.filter(~((pl.col('n_vp_targets') == 0) & (pl.col('variant') != 'protected_swing')))),
]

rows = []
for label, frame in cohorts:
    rows.append(cohort_stats(frame, label, 'is_in_is'))
    rows.append(cohort_stats(frame, label, 'is_in_oos'))
    rows.append(cohort_stats(frame, label))

econ = pl.DataFrame(rows)
econ.write_csv(OUT / 'play_economics.csv')
print(econ.to_pandas().to_string(index=False))
print()

# --- Fixed-TP sweep on the n_vp>=2 (& variant!=PS) cohort ---
print('=' * 80)
print('FIXED-TP SWEEP — n_vp>=2 & variant != protected_swing (IS+OOS pooled)')
print('=' * 80)
cohort = df.filter((pl.col('n_vp_targets') >= 2) & (pl.col('variant') != 'protected_swing'))
print(f'cohort n = {cohort.height}')
sweep_rows = []
for tp in (1.0, 1.5, 2.0, 2.5, 3.0):
    hit_col = f'hit_{tp:.1f}R'.replace('.0', '_0').replace('.5', '_5')
    # The trades CSV has hit_1_0R, hit_1_5R etc — convert tp to that style
    col_name = f'hit_{int(tp)}_{int((tp - int(tp))*10)}R'
    if col_name not in cohort.columns:
        continue
    hits = cohort[col_name].to_numpy()
    # Assume stop at -1R always; win = +tp, loss = -1
    pnl = np.where(hits, tp, -1.0)
    pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()) if (pnl < 0).any() else float('inf')
    sweep_rows.append({
        'TP_R': tp,
        'win_rate': float(hits.mean()),
        'expectancy_R': float(pnl.mean()),
        'PF': round(pf, 2),
        'n': cohort.height,
    })
sweep = pl.DataFrame(sweep_rows)
print(sweep.to_pandas().to_string(index=False))
sweep.write_csv(OUT / 'fixed_tp_sweep.csv')
print()

# Same sweep on the baseline (all trades) for comparison
print('FIXED-TP SWEEP — baseline (all non-skip non-ambiguous trades) for comparison')
base_rows = []
for tp in (1.0, 1.5, 2.0, 2.5, 3.0):
    col_name = f'hit_{int(tp)}_{int((tp - int(tp))*10)}R'
    hits = df[col_name].to_numpy()
    pnl = np.where(hits, tp, -1.0)
    pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()) if (pnl < 0).any() else float('inf')
    base_rows.append({
        'TP_R': tp,
        'win_rate': float(hits.mean()),
        'expectancy_R': float(pnl.mean()),
        'PF': round(pf, 2),
        'n': df.height,
    })
print(pl.DataFrame(base_rows).to_pandas().to_string(index=False))
print()

# --- Frequency / cadence ---
print('=' * 80)
print('FREQUENCY — n_vp>=2 setups by year')
print('=' * 80)
cohort_freq = df.filter(pl.col('n_vp_targets') >= 2)
freq = cohort_freq.group_by('year').agg(pl.len().alias('n_setups')).sort('year')
print(freq.to_pandas().to_string(index=False))
print(f'\nTotal {cohort_freq.height} setups over {df["year"].n_unique()} years '
      f'-> {cohort_freq.height / df["year"].n_unique():.1f} per year (~{cohort_freq.height / (df["year"].n_unique() * 50):.1f}/week)')

# Cadence: distribution of trading-day gaps between n_vp>=2 setups
print('\nGaps between n_vp>=2 setups (trading days):')
dates_sorted = sorted(cohort_freq['date'].unique().to_list())
gaps = np.diff([d.toordinal() for d in dates_sorted])
print(f'  median gap = {np.median(gaps):.1f} days')
print(f'  p75 gap    = {np.percentile(gaps, 75):.1f} days')
print(f'  p95 gap    = {np.percentile(gaps, 95):.1f} days')
print(f'  max gap    = {gaps.max()} days')
print()

# --- Worst streaks (consecutive losers) on the A+ cohort ---
print('=' * 80)
print('WORST CONSECUTIVE LOSER STREAKS — n_vp>=2 & variant!=PS')
print('=' * 80)
seq = cohort.sort('timestamp')['pnl_R'].to_numpy()
streak = max_streak = 0
for r in seq:
    if r < 0:
        streak += 1
        max_streak = max(streak, max_streak)
    else:
        streak = 0
print(f'Longest consecutive-loser streak: {max_streak}')
print(f'Hit rate at 2R for this cohort: {(seq > 0).mean()*100:.1f}%')
print(f'(With {(seq > 0).mean()*100:.0f}% win rate at 2R, expected max streak in '
      f'{len(seq)} trades is ~{int(np.log(len(seq)) / -np.log(1 - (seq > 0).mean()))} losers)')
print()

# --- Confluence stacks ---
print('=' * 80)
print('CONFLUENCE STACKING — what stacks on top of n_vp>=2?')
print('=' * 80)
base_cohort = df.filter((pl.col('n_vp_targets') >= 2) & (pl.col('variant') != 'protected_swing'))
stack_rows = []
stacks = [
    ('base: n_vp>=2 & variant!=PS', base_cohort),
    ('+ VA-edge (direction-matched VA)', base_cohort.filter(pl.col('va_edge'))),
    ('+ gap_bucket==large_up & long',   base_cohort.filter((pl.col('gap_bucket') == 'large_up') & (pl.col('direction') == 'long'))),
    ('+ gap_bucket==large_dn & short',  base_cohort.filter((pl.col('gap_bucket') == 'large_dn') & (pl.col('direction') == 'short'))),
    ('+ range_regime!=contraction',     base_cohort.filter(pl.col('range_regime') != 'contraction')),
    ('+ variant==bos',                  base_cohort.filter(pl.col('variant') == 'bos')),
    ('+ macro_window in M1/M2',         base_cohort.filter(pl.col('macro_window').is_in(['M1', 'M2']))),
    ('+ VA-edge & variant==bos',        base_cohort.filter(pl.col('va_edge') & (pl.col('variant') == 'bos'))),
    ('+ VA-edge & range!=contraction',  base_cohort.filter(pl.col('va_edge') & (pl.col('range_regime') != 'contraction'))),
]
for label, c in stacks:
    if c.height == 0:
        stack_rows.append({'stack': label, 'n': 0})
        continue
    pnl = c['pnl_R'].to_numpy()
    pf = pnl[pnl > 0].sum() / abs(pnl[pnl < 0].sum()) if (pnl < 0).any() else float('inf')
    stack_rows.append({
        'stack': label,
        'n': c.height,
        'wr_2R': round(c['hit_2_0R'].mean(), 3),
        'expectancy_R': round(c['pnl_R'].mean(), 3),
        'PF': round(pf, 2),
        'oos_n': c.filter(pl.col('is_in_oos')).height,
        'oos_wr_2R': round(c.filter(pl.col('is_in_oos'))['hit_2_0R'].mean(), 3) if c.filter(pl.col('is_in_oos')).height else None,
        'oos_expectancy_R': round(c.filter(pl.col('is_in_oos'))['pnl_R'].mean(), 3) if c.filter(pl.col('is_in_oos')).height else None,
    })
stacks_df = pl.DataFrame(stack_rows)
print(stacks_df.to_pandas().to_string(index=False))
stacks_df.write_csv(OUT / 'confluence_stacks.csv')
print()

# --- MFE distribution by bucket (for dynamic TP design) ---
print('=' * 80)
print('MFE DISTRIBUTION — winners only')
print('=' * 80)
mfe_rows = []
for label, expr in [('n_vp==0', pl.col('n_vp_targets') == 0),
                    ('n_vp==1', pl.col('n_vp_targets') == 1),
                    ('n_vp==2', pl.col('n_vp_targets') == 2),
                    ('n_vp>=2 & variant!=PS', (pl.col('n_vp_targets') >= 2) & (pl.col('variant') != 'protected_swing'))]:
    sub = df.filter(expr & pl.col('hit_2_0R'))
    if sub.height == 0:
        continue
    mfe = sub['mfe_r'].to_numpy()
    mfe_rows.append({
        'cohort': label,
        'n_winners': sub.height,
        'mfe_p25': round(float(np.nanpercentile(mfe, 25)), 2),
        'mfe_p50': round(float(np.nanpercentile(mfe, 50)), 2),
        'mfe_p75': round(float(np.nanpercentile(mfe, 75)), 2),
        'mfe_p90': round(float(np.nanpercentile(mfe, 90)), 2),
        'pct_winners_to_2_5R': round(float((sub['hit_2_5R'].mean())), 3),
        'pct_winners_to_3R':   round(float((sub['hit_3_0R'].mean())), 3),
        'pct_winners_to_4R':   round(float((sub['hit_4_0R'].mean())), 3),
    })
mfe_dist = pl.DataFrame(mfe_rows)
print(mfe_dist.to_pandas().to_string(index=False))
mfe_dist.write_csv(OUT / 'mfe_distribution.csv')
print('\nDone.')
