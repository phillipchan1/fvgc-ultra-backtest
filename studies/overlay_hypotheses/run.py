#!/usr/bin/env python3
"""
Pre-registered overlay-hypothesis tests on the FROZEN FVGC v2.0.5 model.

Universe: logs/baseline_trades.csv.preserve  (real 8yr baseline, 2018-2026;
the live logs/baseline_trades.csv is a clobbered 2024-26 slice and CANNOT
support the pre-2023 IS split the protocol requires).

Model is fixed 1R:1R (RR_RATIO=1.0). Every win=+1.0R, loss=-1.0R, so
  expectancy(R) = 2*WR - 1   and   base PF = WR/(1-WR).
The promotion bar (>=65% WR AND >=2.0 PF) collapses to WR>=66.7% for the
base 1R target. PF decouples from WR only for reconstructed >1R targets.

IS  = 2018-2023 (develop/lock)
OOS = 2024-2025 (gate)
TAIL= 2026 partial (reported, NOT part of the gate)

Statistical protocol:
  - within-era label permutation (null = era base rate)
  - ONE combined family -> Benjamini-Hochberg FDR at q=0.10
  - min n=30 per cell
  - positive control (null calibration + power)
  - expectancy in R + PF reported alongside WR

NO modification to fvgc/model.py.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
TRADES = ROOT / 'logs' / 'baseline_trades.csv.preserve'
TD = ROOT / 'data' / 'trading_days' / 'trading_days.csv'
MORNING = HERE / 'cache' / 'morning_bars_30s.csv'
RESULTS = HERE / 'results'
RESULTS.mkdir(parents=True, exist_ok=True)

SEED = 42
N_PERMS = 20_000
MIN_N = 30
R_LEVELS = [1.0, 1.5, 2.0, 2.5, 3.0]

# ===================================================================
# Causality tiers (when is a context feature known?)
# ===================================================================
# TIER0 pre-open (<=09:30:00): prior_day_*, overnight_*, gap_*, calendar,
#       news (red_folder/pre_rth), vixy_regime(prior close)
# TIER1 09:30:30: candle_930_*
# TIER2 09:35:   or_5min_*, fvgs_first_5min
# TIER3 09:45:   or_15min_*, fvgs_first_15min, macro_1_*, W1 direction
# LOOKAHEAD: or_45min_* (10:15), macro_2/3/4, rth_*, max_dd, during_session_news
LOOKAHEAD_FEATURES = {
    'or_45min_high', 'or_45min_low', 'or_45min_range',
    'macro_2_range', 'macro_2_num_fvgs', 'macro_3_range', 'macro_3_num_fvgs',
    'macro_4_range', 'macro_4_num_fvgs', 'rth_high', 'rth_low', 'rth_range',
    'rth_close', 'max_drawdown_from_open', 'max_drawup_from_open',
    'directional_changes_30m', 'has_during_session_news',
}


# ===================================================================
# Load + enrich
# ===================================================================
def load() -> pd.DataFrame:
    tr = pd.read_csv(TRADES)
    tr = tr[tr['outcome'].isin(['win', 'loss'])].copy()
    tr['date'] = tr['timestamp'].str.slice(0, 10)
    tr['entry_tod'] = tr['timestamp'].str.slice(11, 19)
    tr['fvg_tod'] = tr['fvg_created_at'].str.slice(11, 19)
    tr['year'] = tr['timestamp'].str.slice(0, 4).astype(int)
    tr['win'] = (tr['outcome'] == 'win').astype(float)
    tr['R'] = np.where(tr['outcome'] == 'win', 1.0, -1.0)
    for c in ['sl_dist', 'mae_r', 'mfe_r', 'entry_price', 'tp']:
        tr[c] = pd.to_numeric(tr[c], errors='coerce')
    # parse hit_kR booleans
    for r in R_LEVELS:
        k = str(r).replace('.', '_')
        col = f'hit_{k}R'
        tr[col] = tr[col].astype(str).str.strip().isin(['True', 'TRUE', 'true', '1', '1.0'])

    # era
    def era(y):
        if y <= 2023:
            return 'IS'
        if y in (2024, 2025):
            return 'OOS'
        return 'TAIL'
    tr['era'] = tr['year'].apply(era)

    # macro window from entry_tod
    def mins(tod):
        h, m, s = int(tod[0:2]), int(tod[3:5]), int(tod[6:8])
        return (h - 9) * 60 + (m - 30) + s / 60
    tr['mins_into'] = tr['entry_tod'].apply(mins)

    # session features
    td = pd.read_csv(TD)
    td['date'] = td['date'].astype(str)
    sess = session_features(td)
    tr = tr.merge(sess, on='date', how='left')

    # W1 alignment (causal only for entries >= 09:45:00)
    tr['w1_known'] = tr['entry_tod'] >= '09:45:00'
    long_up = (tr['direction'] == 'long') & (tr['w1_dir'] == 'up')
    short_dn = (tr['direction'] == 'short') & (tr['w1_dir'] == 'down')
    tr['w1_aligned'] = (long_up | short_dn) & tr['w1_known']
    long_dn = (tr['direction'] == 'long') & (tr['w1_dir'] == 'down')
    short_up = (tr['direction'] == 'short') & (tr['w1_dir'] == 'up')
    tr['w1_counter'] = (long_dn | short_up) & tr['w1_known']

    # ON sweep BEFORE entry (strictly precede)
    swept_hi = tr['sweep_high_tod'].notna() & (tr['sweep_high_tod'] < tr['entry_tod'])
    swept_lo = tr['sweep_low_tod'].notna() & (tr['sweep_low_tod'] < tr['entry_tod'])
    tr['swept_hi_before'] = swept_hi
    tr['swept_lo_before'] = swept_lo
    # H4: continuation in sweep direction
    tr['post_sweep_cont'] = (swept_hi & (tr['direction'] == 'long')) | \
                            (swept_lo & (tr['direction'] == 'short'))
    # contrast: reversal against sweep
    tr['post_sweep_rev'] = (swept_hi & (tr['direction'] == 'short')) | \
                           (swept_lo & (tr['direction'] == 'long'))

    # H1 opening-window FVG cohort
    tr['opening_fvg'] = (tr['fvg_tod'] >= '09:29:30') & (tr['fvg_tod'] <= '09:31:00')
    tr['opening_fvg_short'] = tr['opening_fvg'] & (tr['direction'] == 'short')
    tr['opening_fvg_long'] = tr['opening_fvg'] & (tr['direction'] == 'long')
    return tr


def session_features(td: pd.DataFrame) -> pd.DataFrame:
    mb = pd.read_csv(MORNING, dtype={'date': str, 'tod': str})
    on = td[['date', 'overnight_high', 'overnight_low']].copy()
    mb = mb.merge(on, on='date', how='left')

    rows = []
    for date, g in mb.groupby('date', sort=False):
        g = g.sort_values('tod')
        # W1 candle: 09:30:00 open -> 09:44:30 close
        o = g[g['tod'] == '09:30:00']
        c = g[g['tod'] == '09:44:30']
        if len(o) and len(c):
            w1o = o['open'].iloc[0]
            w1c = c['close'].iloc[0]
            w1_dir = 'up' if w1c > w1o else ('down' if w1c < w1o else 'flat')
        else:
            w1_dir = None
        # ON sweep timing (first bar after 09:30:00 that takes ON hi / lo)
        onh = g['overnight_high'].iloc[0]
        onl = g['overnight_low'].iloc[0]
        post = g[g['tod'] >= '09:30:00']
        sh = post[post['high'] >= onh]['tod']
        sl = post[post['low'] <= onl]['tod']
        rows.append({
            'date': date,
            'w1_dir': w1_dir,
            'sweep_high_tod': sh.iloc[0] if len(sh) else None,
            'sweep_low_tod': sl.iloc[0] if len(sl) else None,
        })
    return pd.DataFrame(rows)


# ===================================================================
# Metrics + permutation engine
# ===================================================================
def cell_stats(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, pf=np.nan, expR=np.nan)
    wr = sub['win'].mean() * 100
    wins = (sub['R'] > 0).sum()
    losses = (sub['R'] < 0).sum()
    pf = wins / losses if losses > 0 else np.inf
    expR = sub['R'].mean()
    return dict(n=n, wr=wr, pf=pf, expR=expR)


def perm_wr_pvalue(universe: pd.DataFrame, mask: np.ndarray, n_perms=N_PERMS, seed=SEED):
    """Within-universe label permutation on cohort win rate.

    Returns (actual_wr, p_two_sided, p_one_sided_directional).
    p_two = 2*min(upper,lower) capped at 1  -> used for the FDR family (conservative).
    p_one = tail on the side the actual deviates -> directional pre-registered read.
    """
    win = universe['win'].values.astype(float)
    nT = len(win)
    nsub = int(mask.sum())
    if nsub < MIN_N:
        return np.nan, np.nan, np.nan
    actual = win[mask].mean() * 100
    rng = np.random.default_rng(seed)
    perm = np.empty(n_perms)
    for i in range(n_perms):
        p = rng.permutation(nT)
        perm[i] = win[p][mask].mean() * 100
    p_up = np.mean(perm >= actual)
    p_lo = np.mean(perm <= actual)
    p_one = p_up if actual >= perm.mean() else p_lo
    p_two = min(1.0, 2.0 * min(p_up, p_lo))
    floor = 1.0 / n_perms
    return actual, max(p_two, floor), max(p_one, floor)


def bracket_expectancy(sub: pd.DataFrame, k: float) -> dict:
    """Reconstruct fixed bracket {target=kR, stop=1R} from hit_kR / mae_r.

      hit_kR True        -> +k       (reached kR favorable before stop)
      hit_kR False, mae>=1 -> -1     (stop hit, target never reached first)
      else               -> eod residual (never reached +k nor -1): scratch=0
    """
    kk = str(k).replace('.', '_')
    hit = sub[f'hit_{kk}R'].values
    mae = sub['mae_r'].values
    R = np.where(hit, k, np.where(mae >= 1.0, -1.0, 0.0))
    resid = int(((~hit) & (mae < 1.0)).sum())
    n = len(sub)
    wins = (R > 0).sum()
    losses = (R < 0).sum()
    gp = R[R > 0].sum()
    gl = -R[R < 0].sum()
    pf = gp / gl if gl > 0 else np.inf
    return dict(k=k, n=n, hit_rate=hit.mean() * 100, expR=R.mean(),
                pf=pf, wins=int(wins), losses=int(losses), resid=resid)


# ===================================================================
# BH-FDR
# ===================================================================
def bh_fdr(pvals, q=0.10):
    p = np.asarray(pvals, float)
    ok = ~np.isnan(p)
    out = np.full(len(p), np.nan)
    idx = np.where(ok)[0]
    m = len(idx)
    if m == 0:
        return out, np.full(len(p), False)
    order = idx[np.argsort(p[idx])]
    ranked = p[order]
    adj = ranked * m / (np.arange(1, m + 1))
    # monotone from the back
    for i in range(m - 2, -1, -1):
        adj[i] = min(adj[i], adj[i + 1])
    adj = np.minimum(adj, 1.0)
    out[order] = adj
    reject = np.full(len(p), False)
    reject[order] = adj < q
    return out, reject


# ===================================================================
# Main
# ===================================================================
def main():
    tr = load()
    fam = []   # list of dicts: {test, era, n, wr, pf, expR, p}

    def base(era):
        d = tr[tr['era'] == era]
        return cell_stats(d), d

    rep = []
    def line(s=''):
        rep.append(s)
        print(s)

    line("=" * 78)
    line("PRE-REGISTERED OVERLAY HYPOTHESES — FVGC v2.0.5 (frozen)")
    line("=" * 78)
    line(f"Universe: {TRADES.name}  (8yr real baseline)")
    for era in ['IS', 'OOS', 'TAIL']:
        st, _ = base(era)
        yrs = sorted(tr[tr['era'] == era]['year'].unique())
        line(f"  {era:4s} {yrs[0]}-{yrs[-1]}: n={st['n']:5d}  WR={st['wr']:.1f}%  "
             f"PF={st['pf']:.2f}  E[R]={st['expR']:+.3f}")
    line("")
    line("Bar: WR>=66.7% (==PF>=2.0 at fixed 1R) AND survives OOS AND clears FDR q=0.10")
    line("")

    # ---- helper that permutes correctly within a universe ----
    def reg(test, era, cohort_col=None, cohort_mask=None):
        uni = tr[tr['era'] == era].reset_index(drop=True)
        if cohort_mask is not None:
            m = cohort_mask.loc[tr['era'] == era].reset_index(drop=True).values
        else:
            m = uni[cohort_col].values.astype(bool)
        sub = uni[m]
        st = cell_stats(sub)
        if st['n'] < MIN_N:
            fam.append(dict(test=test, era=era, n=st['n'], wr=st['wr'], pf=st['pf'],
                            expR=st['expR'], p=np.nan, p1=np.nan, note='n<30'))
            return st
        _, p2, p1 = perm_wr_pvalue(uni, m)
        fam.append(dict(test=test, era=era, n=st['n'], wr=st['wr'], pf=st['pf'],
                        expR=st['expR'], p=p2, p1=p1, note=''))
        return st

    # =============================== H1 ===============================
    line("-" * 78)
    line("H1  Opening-window FVG SHORTS (fvg_created 09:29:30-09:31:00, short)")
    line("-" * 78)
    for era in ['IS', 'OOS', 'TAIL']:
        st = reg('H1 opening_fvg_short', era, 'opening_fvg_short')
        flag = '' if era == 'TAIL' else ''
        line(f"  {era:4s}: n={st['n']:4d}  WR={st['wr']:.1f}%  PF={st['pf']:.2f}  "
             f"E[R]={st['expR']:+.3f}  p={_p(fam)}")
    # >1R target on the opening-short cohort (pooled IS for discovery, OOS check)
    line("  >1R target reconstruction (opening_fvg_short):")
    for era in ['IS', 'OOS']:
        d = tr[(tr['era'] == era) & tr['opening_fvg_short']]
        if len(d) >= MIN_N:
            cells = [bracket_expectancy(d, k) for k in R_LEVELS]
            line(f"    {era}: " + " | ".join(
                f"{c['k']}R hit={c['hit_rate']:.0f}% E[R]={c['expR']:+.2f} PF={c['pf']:.2f}"
                for c in cells) + f"  (n={len(d)})")
        else:
            line(f"    {era}: n={len(d)} <30, skip")
    # longs for contrast
    line("  (contrast) opening_fvg_long:")
    for era in ['IS', 'OOS']:
        st = reg('H1 opening_fvg_long', era, 'opening_fvg_long')
        line(f"    {era}: n={st['n']:4d}  WR={st['wr']:.1f}%  PF={st['pf']:.2f}  E[R]={st['expR']:+.3f}")
    line("")

    # =============================== H2 ===============================
    line("-" * 78)
    line("H2  W1-alignment (entries >=09:45 only; W1=first 15m candle dir)")
    line("-" * 78)
    line(f"  (W1-known entries: {int(tr['w1_known'].sum())} of {len(tr)} tradeable)")
    for era in ['IS', 'OOS', 'TAIL']:
        a = reg('H2 W1-aligned', era, 'w1_aligned')
        line(f"  {era:4s} aligned: n={a['n']:4d}  WR={a['wr']:.1f}%  PF={a['pf']:.2f}  "
             f"E[R]={a['expR']:+.3f}  p={_p(fam)}")
    for era in ['IS', 'OOS', 'TAIL']:
        c = reg('H2 W1-counter', era, 'w1_counter')
        line(f"  {era:4s} counter: n={c['n']:4d}  WR={c['wr']:.1f}%  PF={c['pf']:.2f}  "
             f"E[R]={c['expR']:+.3f}  p={_p(fam)}")
    line("")

    # =============================== H4 ===============================
    line("-" * 78)
    line("H4  Post-sweep continuation (ON hi/lo swept BEFORE entry, sweep dir)")
    line("-" * 78)
    for era in ['IS', 'OOS', 'TAIL']:
        st = reg('H4 post_sweep_cont', era, 'post_sweep_cont')
        line(f"  {era:4s} cont: n={st['n']:4d}  WR={st['wr']:.1f}%  PF={st['pf']:.2f}  "
             f"E[R]={st['expR']:+.3f}  p={_p(fam)}")
    line("  (contrast) post_sweep_reversal:")
    for era in ['IS', 'OOS']:
        st = reg('H4 post_sweep_rev', era, 'post_sweep_rev')
        line(f"    {era}: n={st['n']:4d}  WR={st['wr']:.1f}%  PF={st['pf']:.2f}  E[R]={st['expR']:+.3f}")
    line("")

    # =============================== H3 ===============================
    line("-" * 78)
    line("H3  Exclusion overlay (derive low-WR avoid combos on IS, lock, test OOS)")
    line("-" * 78)
    excl_mask_full, excl_desc, worst = build_exclusions(tr)
    line("  Worst causal pre-entry combos by IS WR (n>=30), with OOS follow-through:")
    line(f"    {'combo':32s} {'IS n':>5s} {'IS WR':>6s} {'OOS n':>6s} {'OOS WR':>7s}")
    for combo, n_is, wr_is, n_oos, wr_oos in worst[:10]:
        line(f"    {'+'.join(combo):32s} {n_is:5d} {wr_is:5.1f}% {n_oos:6d} "
             f"{wr_oos:6.1f}%" if not np.isnan(wr_oos) else
             f"    {'+'.join(combo):32s} {n_is:5d} {wr_is:5.1f}% {n_oos:6d}    n/a")
    line("")
    if len(excl_desc):
        for era in ['IS', 'OOS', 'TAIL']:
            d = tr[tr['era'] == era]
            em = excl_mask_full.loc[d.index].values
            kept, rem = d[~em], d[em]
            sk, srm = cell_stats(kept), cell_stats(rem)
            line(f"  {era:4s}: excluded n={srm['n']:4d} WR={srm['wr']:.1f}%  ||  "
                 f"kept n={sk['n']:4d} WR={sk['wr']:.1f}% (E[R]={sk['expR']:+.3f})  "
                 f"vs all WR={cell_stats(d)['wr']:.1f}%")
        uni = tr[tr['era'] == 'OOS'].reset_index(drop=True)
        m = excl_mask_full.loc[tr['era'] == 'OOS'].reset_index(drop=True).values
        st = cell_stats(uni[m])
        if st['n'] >= MIN_N:
            _, p2, p1 = perm_wr_pvalue(uni, m)
        else:
            p2 = p1 = np.nan
        fam.append(dict(test='H3 excluded-cohort-low', era='OOS', n=st['n'], wr=st['wr'],
                        pf=st['pf'], expR=st['expR'], p=p2, p1=p1, note=''))
        line(f"  Avoid list ({len(excl_desc)} combos, IS WR<=35%): {excl_desc}")
        line(f"  OOS excluded-cohort low-WR test: n={st['n']} WR={st['wr']:.1f}% "
             f"p2={p2:.4f} p1={p1:.4f}")
    else:
        line("  No causal pre-entry combo reaches IS WR<=35% at n>=30.")
        line("  => the prior combo search's low-WR 'avoid' cells were driven by")
        line("     or_45min_range (a 10:15 lookahead feature). No deployable causal")
        line("     do-not-trade overlay is recoverable. H3 has no FDR test to add.")
    line("")

    # =============================== H5 ===============================
    line("-" * 78)
    line("H5  Target study — MFE/MAE, hit-rates, reconstructed E[R] by target/cohort")
    line("-" * 78)
    cohorts = {
        'ALL': tr['win'].notna(),
        'shorts': tr['direction'] == 'short',
        'longs': tr['direction'] == 'long',
        'opening_short': tr['opening_fvg_short'],
        'macro1(9:30-9:45)': tr['mins_into'] < 15,
    }
    for cname, cmask in cohorts.items():
        line(f"  [{cname}]")
        for era in ['IS', 'OOS']:
            d = tr[(tr['era'] == era) & cmask]
            if len(d) < MIN_N:
                line(f"    {era}: n={len(d)} <30")
                continue
            cells = [bracket_expectancy(d, k) for k in R_LEVELS]
            maxresid = max(c['resid'] for c in cells)
            line(f"    {era} (n={len(d)}, MFE_r med={d['mfe_r'].median():.2f}, "
                 f"eod-resid<={maxresid}): " +
                 " | ".join(f"{c['k']}R:E[R]={c['expR']:+.2f},PF={c['pf']:.2f}" for c in cells))
    line("  (eod-resid = trades reaching neither +kR nor -1R; scored 0R/scratch)")
    line("")

    # =========================== POSITIVE CONTROL =====================
    line("-" * 78)
    line("POSITIVE CONTROL (harness validation — not in FDR family)")
    line("-" * 78)
    uni = tr[tr['era'] == 'OOS'].reset_index(drop=True)
    rng = np.random.default_rng(123)
    # (a) null calibration: random masks -> ~5% should be p<0.05
    sig = 0; trials = 400
    for _ in range(trials):
        mm = np.zeros(len(uni), bool)
        mm[rng.choice(len(uni), 120, replace=False)] = True
        _, p2, _ = perm_wr_pvalue(uni, mm, n_perms=2000, seed=int(rng.integers(1e9)))
        if p2 < 0.05:
            sig += 1
    line(f"  Null calibration (two-sided): {sig}/{trials} random masks p<0.05 "
         f"({100*sig/trials:.1f}%, expect ~5%)")
    # (b) power: synthetic oracle cohort enriched in wins
    wins_idx = np.where(uni['win'].values == 1)[0]
    loss_idx = np.where(uni['win'].values == 0)[0]
    orc = np.concatenate([rng.choice(wins_idx, 70, replace=False),
                          rng.choice(loss_idx, 30, replace=False)])
    mm = np.zeros(len(uni), bool); mm[orc] = True
    a, p2, _ = perm_wr_pvalue(uni, mm, n_perms=5000)
    line(f"  Power: synthetic 70%-win oracle (n=100): WR={a:.1f}% p={p2:.4f} "
         f"(expect p~0) -> {'PASS' if p2 < 0.01 else 'FAIL'}")
    line("")

    # =========================== FDR =================================
    fdf = pd.DataFrame(fam)
    pv = fdf['p'].values
    adj, rej = bh_fdr(pv, q=0.10)
    fdf['p_bh'] = adj
    fdf['fdr_reject'] = rej
    fdf.to_csv(RESULTS / 'family_results.csv', index=False)

    line("=" * 78)
    line(f"BH-FDR FAMILY (q=0.10, two-sided p, {int((~fdf['p'].isna()).sum())} valid tests)")
    line("=" * 78)
    show = fdf[~fdf['p'].isna()].sort_values('p')
    line(f"  {'test':28s} {'era':4s} {'n':>5s} {'WR':>6s} {'PF':>6s} {'E[R]':>7s} "
         f"{'p2':>7s} {'p1':>7s} {'p_bh':>7s} sig")
    for _, r in show.iterrows():
        line(f"  {r['test']:28s} {r['era']:4s} {r['n']:5d} {r['wr']:5.1f}% "
             f"{r['pf']:6.2f} {r['expR']:+7.3f} {r['p']:7.4f} {r['p1']:7.4f} "
             f"{r['p_bh']:7.4f} {'***FDR***' if r['fdr_reject'] else ''}")
    nrej = int(fdf['fdr_reject'].sum())
    line("")
    line(f"  Survivors of BH-FDR q=0.10: {nrej}")
    line(f"  (n<30 cells, excluded from family: "
         f"{', '.join(sorted(set(fdf[fdf['note']=='n<30']['test'])))})")
    line("")

    (RESULTS / 'console_report.txt').write_text('\n'.join(rep))
    print(f"\nWrote {RESULTS/'family_results.csv'} and {RESULTS/'console_report.txt'}")


def _p(fam):
    if not fam or (isinstance(fam[-1]['p'], float) and np.isnan(fam[-1]['p'])):
        return 'n<30'
    return f"{fam[-1]['p']:.4f}(1s={fam[-1]['p1']:.4f})"


def build_exclusions(tr: pd.DataFrame):
    """Derive 'do-not-trade' combos from IS ONLY, using strictly causal
    (pre-entry-known) features. Pick combos with IS WR <= 35% and n>=30.
    Returns a full-universe boolean mask and a short description list.

    Causal features used (all TIER0/1, known by 9:30:30):
      direction, candle_930_direction, gap sign, overnight_direction,
      prior_day_close_position bucket, vixy_regime, is_fomc_week.
    Deliberately EXCLUDES or_45min_* (lookahead) which dominated the prior
    combo search's avoid list.
    """
    td = pd.read_csv(TD); td['date'] = td['date'].astype(str)
    feats = td[['date', 'candle_930_direction', 'gap_from_prior_close',
                'overnight_direction', 'prior_day_close_position', 'vixy_regime',
                'is_fomc_week']].copy()
    x = tr.merge(feats, on='date', how='left')
    x.index = tr.index
    fmask = {
        'short': (x['direction'] == 'short'),
        'long': (x['direction'] == 'long'),
        'bull930': (x['candle_930_direction'] == 'bullish'),
        'bear930': (x['candle_930_direction'] == 'bearish'),
        'gap_up': (x['gap_from_prior_close'] > 0),
        'gap_dn': (x['gap_from_prior_close'] < 0),
        'on_up': (x['overnight_direction'] == 'up'),
        'on_dn': (x['overnight_direction'] == 'down'),
        'pd_up': (x['prior_day_close_position'] > 0.75),
        'pd_dn': (x['prior_day_close_position'] < 0.25),
        'fomc': (x['is_fomc_week'] == True),
        'elevated_vixy': (x['vixy_regime'].isin(['elevated', 'high'])),
    }
    excl_groups = [{'short', 'long'}, {'bull930', 'bear930'}, {'gap_up', 'gap_dn'},
                   {'on_up', 'on_dn'}, {'pd_up', 'pd_dn'}]
    def valid(combo):
        s = set(combo)
        return all(len(s & g) < 2 for g in excl_groups)

    from itertools import combinations
    names = list(fmask.keys())
    is_idx = (tr['era'] == 'IS').values
    oos_idx = (tr['era'] == 'OOS').values
    win = tr['win'].values
    ranked = []   # (combo, n_is, wr_is, n_oos, wr_oos)
    for k in (2, 3):
        for combo in combinations(names, k):
            if not valid(combo):
                continue
            m = np.ones(len(tr), bool)
            for f in combo:
                m &= fmask[f].values
            mi = m & is_idx
            n = int(mi.sum())
            if n >= MIN_N:
                wr = win[mi].mean() * 100
                mo = m & oos_idx
                n_o = int(mo.sum())
                wr_o = win[mo].mean() * 100 if n_o > 0 else np.nan
                ranked.append((combo, n, wr, n_o, wr_o))
    ranked.sort(key=lambda c: c[2])   # ascending IS WR
    chosen = [r for r in ranked if r[2] <= 35.0]
    full = np.zeros(len(tr), bool)
    desc = []
    for combo, n, wr, n_o, wr_o in chosen[:8]:
        m = np.ones(len(tr), bool)
        for f in combo:
            m &= fmask[f].values
        full |= m
        desc.append(f"{'+'.join(combo)}(IS n={n},WR={wr:.0f}%)")
    return pd.Series(full, index=tr.index), desc, ranked


if __name__ == '__main__':
    main()
