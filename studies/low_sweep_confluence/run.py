#!/usr/bin/env python3
"""
Study: Low-side liquidity sweep activators for M2+M3 Long FVGC trades.

Hypothesis (Phil): the OR.L-swept boost on M3 longs (~57.3% WR / 1.36 PF) is a
special case of a broader "morning long-side liquidity has been cleared"
pattern. Test 8 binary "low taken out before entry" signals as confluence #7
candidates for the M2+M3 Long Confluence Model.

Levels tested:
  1. or_l                — 9:30-9:45 RTH low; sweep window [9:45, entry]
  2. on_low              — overnight (prior 18:00 → today 9:30); window [9:30, entry]
  3. london_low          — today 02:00-08:00; window [9:30, entry]
  4. premarket_low       — today 04:00-08:00; window [9:30, entry]
  5. pdl_swept_rth_only  — PDL; window [9:30, entry]
  6. pdl_swept_overnight — PDL; window [prior_close, entry] (incl. overnight)
  7. pdval_swept_rth_only— PD VAL; window [9:30, entry]
  8. pdval_swept_overnight— PD VAL; window [prior_close, entry]

Trade universe: M2+M3 long FVGC (macro_window in {2,3}, direction=long,
variant in {no_fvg, ifvg}, decided outcome). Headline numbers gated by
magnet_valid=True (the playbook). Baseline replication run on M3 longs
without magnet_valid filter to match cited 57.3% / 1.36 PF.

Sweep semantics: loose-mode breach (any 30s wick where low < level_price)
inside the per-level window. Strict (wick + close-back-inside) reported as
sensitivity-check on OR.L only.

Run from repo root:
  python studies/low_sweep_confluence/run.py
"""

from __future__ import annotations

import sys
from datetime import time as dtime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.constants import NY_TZ  # noqa: E402

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'

CANDLES_30S_PATH = ROOT / 'data' / 'consolidated' / 'nq-front-month.ohlcv-30s.csv'
TRADES_WITH_LEVELS_PATH = ROOT / 'data' / 'levels' / 'trades_with_levels.csv'
DAILY_VP_PATH = ROOT / 'data' / 'levels' / 'daily_volume_profile.csv'

RTH_OPEN = dtime(9, 30)
RTH_CLOSE = dtime(16, 0)
OR_END = dtime(9, 45)
M2_START = dtime(9, 45)
M2_END = dtime(10, 0)
M3_END = dtime(10, 15)
LONDON_START = dtime(2, 0)
LONDON_END = dtime(8, 0)
PREMARKET_START = dtime(4, 0)
PREMARKET_END = dtime(8, 0)
ON_START = dtime(18, 0)

DAY_END = dtime(23, 59, 59)

# Activator columns in canonical order
ACTIVATORS = (
    'or_l_swept',
    'on_low_swept',
    'london_low_swept',
    'premarket_low_swept',
    'pdl_swept_overnight',
    'pdl_swept_rth_only',
    'pdval_swept_overnight',
    'pdval_swept_rth_only',
)


# ===================================================================
# Data loading
# ===================================================================

def load_30s_candles(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], utc=True)
    df['timestamp_ny'] = df['timestamp_utc'].dt.tz_convert(NY_TZ)
    df = df.sort_values('timestamp_utc').reset_index(drop=True)
    df['date'] = df['timestamp_ny'].dt.date
    df['t'] = df['timestamp_ny'].dt.time
    return df


def load_daily_vp(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date']).dt.date
    return df


def load_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if df['timestamp'].dt.tz is None:
        df['timestamp'] = df['timestamp'].dt.tz_localize(NY_TZ, ambiguous='infer', nonexistent='shift_forward')
    else:
        df['timestamp'] = df['timestamp'].dt.tz_convert(NY_TZ)
    return df


# ===================================================================
# Per-day level computation
# ===================================================================

def compute_session_lows_per_day(
    candles: pd.DataFrame,
    daily_vp: pd.DataFrame,
) -> pd.DataFrame:
    """One row per trading day with all 6 base level prices."""
    by_date = {d: g for d, g in candles.groupby('date')}
    dates = sorted(by_date.keys())

    vp_lookup = dict(zip(daily_vp['date'], daily_vp['val']))

    rows = []
    for i, d in enumerate(dates):
        day = by_date[d]
        prior_d = dates[i - 1] if i > 0 else None
        prior_day = by_date.get(prior_d) if prior_d else None

        or_bars = day[(day['t'] >= RTH_OPEN) & (day['t'] < OR_END)]
        or_low = float(or_bars['low'].min()) if len(or_bars) else None

        lon = day[(day['t'] >= LONDON_START) & (day['t'] < LONDON_END)]
        london_low = float(lon['low'].min()) if len(lon) else None

        pre = day[(day['t'] >= PREMARKET_START) & (day['t'] < PREMARKET_END)]
        premarket_low = float(pre['low'].min()) if len(pre) else None

        on_parts: list[pd.DataFrame] = []
        if prior_day is not None:
            on_parts.append(prior_day[prior_day['t'] >= ON_START])
        on_parts.append(day[day['t'] < RTH_OPEN])
        overnight = pd.concat(on_parts, ignore_index=True) if on_parts else pd.DataFrame()
        on_low = float(overnight['low'].min()) if len(overnight) else None

        if prior_day is not None:
            prior_rth = prior_day[(prior_day['t'] >= RTH_OPEN) & (prior_day['t'] < RTH_CLOSE)]
            pdl = float(prior_rth['low'].min()) if len(prior_rth) else None
        else:
            pdl = None

        pdval = vp_lookup.get(prior_d) if prior_d else None
        if pdval is not None and pd.isna(pdval):
            pdval = None

        rows.append({
            'date': d,
            'prior_date': prior_d,
            'or_low': or_low,
            'on_low': on_low,
            'london_low': london_low,
            'premarket_low': premarket_low,
            'pdl': pdl,
            'pdval': pdval,
        })
    return pd.DataFrame(rows)


# ===================================================================
# Per-day first-sweep timestamps
# ===================================================================

def _first_breach(slc: pd.DataFrame, level: Optional[float]) -> Optional[pd.Timestamp]:
    if level is None or pd.isna(level):
        return None
    if slc.empty:
        return None
    breaches = slc.loc[slc['low'] < level, 'timestamp_ny']
    return breaches.iloc[0] if len(breaches) else None


def compute_first_sweep_times(
    candles: pd.DataFrame,
    day_levels: pd.DataFrame,
) -> pd.DataFrame:
    by_date = {d: g for d, g in candles.groupby('date')}

    rows = []
    for _, lr in day_levels.iterrows():
        d = lr['date']
        prior_d = lr['prior_date']
        day = by_date.get(d)
        prior_day = by_date.get(prior_d) if prior_d else None
        if day is None:
            continue

        post_or = day[day['t'] >= OR_END]
        post_open = day[day['t'] >= RTH_OPEN]
        pre_open_today = day[day['t'] < RTH_OPEN]
        prior_post_close = (
            prior_day[prior_day['t'] >= dtime(16, 0)]
            if prior_day is not None else pd.DataFrame()
        )

        rows.append({
            'date': d,
            'or_low': lr['or_low'],
            'on_low': lr['on_low'],
            'london_low': lr['london_low'],
            'premarket_low': lr['premarket_low'],
            'pdl': lr['pdl'],
            'pdval': lr['pdval'],
            # First in-session sweep (after [9:45, end-of-day) for OR.L; [9:30, end-of-day) for others)
            'or_l_first_swept_at': _first_breach(post_or, lr['or_low']),
            'on_low_first_swept_at': _first_breach(post_open, lr['on_low']),
            'london_low_first_swept_at': _first_breach(post_open, lr['london_low']),
            'premarket_low_first_swept_at': _first_breach(post_open, lr['premarket_low']),
            'pdl_rth_first_swept_at': _first_breach(post_open, lr['pdl']),
            'pdval_rth_first_swept_at': _first_breach(post_open, lr['pdval']),
            # PDL/PDVAL pre-RTH sweep (boolean only — used for *_overnight variant)
            'pdl_pre_rth_swept': (
                _first_breach(prior_post_close, lr['pdl']) is not None
                or _first_breach(pre_open_today, lr['pdl']) is not None
            ),
            'pdval_pre_rth_swept': (
                _first_breach(prior_post_close, lr['pdval']) is not None
                or _first_breach(pre_open_today, lr['pdval']) is not None
            ),
        })
    return pd.DataFrame(rows)


# ===================================================================
# Trade tagging
# ===================================================================

def tag_m2m3_longs(
    trades: pd.DataFrame,
    sweep_times: pd.DataFrame,
) -> pd.DataFrame:
    """Filter to M2+M3 long FVGC trades and add 8 *_swept boolean activators."""
    sweep_idx = sweep_times.set_index('date')

    out_rows = []
    for _, t in trades.iterrows():
        ts = t['timestamp']
        tt = ts.time()
        # Filter universe: macro 2 or 3 (entry in [9:45, 10:15)), long, no_fvg/ifvg, decided
        if not (M2_START <= tt < M3_END):
            continue
        if t['direction'] != 'long':
            continue
        if t['variant'] not in ('no_fvg', 'ifvg'):
            continue
        outcome = t.get('outcome')
        if outcome not in ('win', 'loss'):
            continue

        d = ts.date()
        if d not in sweep_idx.index:
            continue
        sr = sweep_idx.loc[d]

        def swept_by(col: str) -> bool:
            v = sr.get(col)
            if v is None or pd.isna(v):
                return False
            return v <= ts

        or_l = swept_by('or_l_first_swept_at')
        on_low = swept_by('on_low_first_swept_at')
        london = swept_by('london_low_first_swept_at')
        premarket = swept_by('premarket_low_first_swept_at')
        pdl_rth = swept_by('pdl_rth_first_swept_at')
        pdval_rth = swept_by('pdval_rth_first_swept_at')
        pdl_overnight = bool(sr.get('pdl_pre_rth_swept', False)) or pdl_rth
        pdval_overnight = bool(sr.get('pdval_pre_rth_swept', False)) or pdval_rth

        macro = 2 if tt < M2_END else 3

        row = t.to_dict()
        row.update({
            'macro_window': macro,
            'or_l_swept': or_l,
            'on_low_swept': on_low,
            'london_low_swept': london,
            'premarket_low_swept': premarket,
            'pdl_swept_overnight': pdl_overnight,
            'pdl_swept_rth_only': pdl_rth,
            'pdval_swept_overnight': pdval_overnight,
            'pdval_swept_rth_only': pdval_rth,
        })
        out_rows.append(row)

    df = pd.DataFrame(out_rows)
    if df.empty:
        return df
    # Cluster representative count — pick the broadest variant per cluster:
    #   ON cluster: on_low_swept (proxy for ON/London/PM family)
    #   PD cluster: pdl_swept_overnight
    #   PDVAL cluster: pdval_swept_overnight
    #   OR.L: standalone
    df['n_lows_swept_clusters'] = (
        df['or_l_swept'].astype(int)
        + df['on_low_swept'].astype(int)
        + df['pdl_swept_overnight'].astype(int)
        + df['pdval_swept_overnight'].astype(int)
    )
    df['n_lows_swept_all'] = sum(df[a].astype(int) for a in ACTIVATORS)
    return df


# ===================================================================
# Statistics helpers
# ===================================================================

def cell_stats(sub: pd.DataFrame) -> Optional[dict]:
    if sub.empty:
        return None
    wins = int((sub['outcome'] == 'win').sum())
    losses = int((sub['outcome'] == 'loss').sum())
    decided = wins + losses
    if decided == 0:
        return None
    wr = wins / decided * 100
    pnl = pd.to_numeric(sub['pnl'], errors='coerce')
    gross_win = pnl[sub['outcome'] == 'win'].sum()
    gross_loss = abs(pnl[sub['outcome'] == 'loss'].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
    ev_per_trade = pnl.sum() / decided
    return {
        'n': decided,
        'wins': wins,
        'losses': losses,
        'wr': wr,
        'pf': pf,
        'ev': ev_per_trade,
        'mean_mfe_r': float(pd.to_numeric(sub['mfe_r'], errors='coerce').mean()),
    }


def fmt_pf(pf: float) -> str:
    return f'{pf:5.2f}' if pf != float('inf') else '  inf'


def print_split(df: pd.DataFrame, col: str, label: Optional[str] = None) -> None:
    label = label or col
    s_t = cell_stats(df[df[col]])
    s_f = cell_stats(df[~df[col]])
    print(f'\n  --- {label} ---')
    print(f'  {"":24s}  {"n":>4s}  {"W":>4s}  {"L":>4s}  {"WR%":>6s}  {"PF":>6s}  {"EV":>7s}  {"mfeR":>6s}')
    for tag, s in (('=False', s_f), ('=True ', s_t)):
        if s is None:
            print(f'  {label + tag:24s}  {"0":>4s}  {"-":>4s}  {"-":>4s}  {"-":>6s}  {"-":>6s}  {"-":>7s}  {"-":>6s}')
            continue
        print(
            f'  {label + tag:24s}  {s["n"]:>4d}  {s["wins"]:>4d}  {s["losses"]:>4d}  '
            f'{s["wr"]:>5.1f}%  {fmt_pf(s["pf"]):>6s}  {s["ev"]:>+6.2f}  {s["mean_mfe_r"]:>5.2f}'
        )
    if s_t and s_f:
        print(f'  lift (T-F):              wr={s_t["wr"]-s_f["wr"]:+5.1f}pp  pf={s_t["pf"]-s_f["pf"]:+5.2f}  ev={s_t["ev"]-s_f["ev"]:+5.2f}')


def summary_lift_table(df: pd.DataFrame, activators: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for col in activators:
        s_t = cell_stats(df[df[col]])
        s_f = cell_stats(df[~df[col]])
        if s_t is None or s_f is None:
            rows.append({'activator': col, 'n_T': s_t['n'] if s_t else 0, 'n_F': s_f['n'] if s_f else 0,
                         'wr_T': None, 'wr_F': None, 'wr_lift': None,
                         'pf_T': None, 'pf_F': None, 'ev_T': None, 'ev_F': None, 'ev_lift': None})
            continue
        rows.append({
            'activator': col,
            'n_T': s_t['n'], 'n_F': s_f['n'],
            'wr_T': round(s_t['wr'], 1), 'wr_F': round(s_f['wr'], 1),
            'wr_lift': round(s_t['wr'] - s_f['wr'], 1),
            'pf_T': round(s_t['pf'], 2) if s_t['pf'] != float('inf') else None,
            'pf_F': round(s_f['pf'], 2) if s_f['pf'] != float('inf') else None,
            'ev_T': round(s_t['ev'], 2),
            'ev_F': round(s_f['ev'], 2),
            'ev_lift': round(s_t['ev'] - s_f['ev'], 2),
        })
    out = pd.DataFrame(rows)
    return out.sort_values('wr_lift', ascending=False, na_position='last').reset_index(drop=True)


def phi_correlation_matrix(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame:
    M = df[list(cols)].astype(int)
    return M.corr(method='pearson').round(3)  # Pearson on 0/1 == Phi


def stratified_split(df: pd.DataFrame, activator: str, stratifier: str) -> pd.DataFrame:
    rows = []
    for band in sorted(df[stratifier].dropna().unique()):
        band_df = df[df[stratifier] == band]
        s_t = cell_stats(band_df[band_df[activator]])
        s_f = cell_stats(band_df[~band_df[activator]])
        rows.append({
            'band': band,
            'n_F': s_f['n'] if s_f else 0,
            'wr_F': round(s_f['wr'], 1) if s_f else None,
            'pf_F': round(s_f['pf'], 2) if s_f and s_f['pf'] != float('inf') else None,
            'n_T': s_t['n'] if s_t else 0,
            'wr_T': round(s_t['wr'], 1) if s_t else None,
            'pf_T': round(s_t['pf'], 2) if s_t and s_t['pf'] != float('inf') else None,
            'wr_lift': round(s_t['wr'] - s_f['wr'], 1) if s_t and s_f else None,
        })
    return pd.DataFrame(rows)


def confluence_band(c: float) -> str:
    if pd.isna(c):
        return 'NA'
    c = int(c)
    if c <= 2:
        return '0-2'
    if c <= 4:
        return '3-4'
    return '5+'


def n_clusters_band(n: int) -> str:
    if n == 0:
        return '0'
    if n == 1:
        return '1'
    if n == 2:
        return '2'
    return '3+'


# ===================================================================
# Logistic regression for marginal lift (CI on activator coefficient)
# ===================================================================

def logit_marginal(df: pd.DataFrame, activator: str, controls: list[str]) -> Optional[dict]:
    """OLS logit via statsmodels; falls back to None if statsmodels missing or fit fails."""
    try:
        import statsmodels.api as sm
    except ImportError:
        return None
    sub = df.dropna(subset=[activator] + controls).copy()
    if sub.empty:
        return None
    X_parts = [sub[activator].astype(int).rename('activator')]
    for c in controls:
        X_parts.append(pd.to_numeric(sub[c], errors='coerce').rename(c))
    X = pd.concat(X_parts, axis=1).dropna()
    y = (sub.loc[X.index, 'outcome'] == 'win').astype(int).values
    X = sm.add_constant(X, has_constant='add')
    try:
        res = sm.Logit(y, X).fit(disp=0, method='bfgs', maxiter=200)
    except Exception:
        return None
    coef = float(res.params['activator'])
    se = float(res.bse['activator'])
    p = float(res.pvalues['activator'])
    return {'coef': coef, 'se': se, 'p': p, 'ci_lo': coef - 1.96 * se, 'ci_hi': coef + 1.96 * se, 'n': len(X)}


# ===================================================================
# Pipeline
# ===================================================================

def main() -> None:
    print('=' * 70)
    print('FVGC — Low-Side Liquidity Sweep Confluence Study')
    print('M2+M3 Long universe; 8 low-sweep activators')
    print('=' * 70)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print('\n  Loading 30s candles ...')
    candles = load_30s_candles(CANDLES_30S_PATH)
    print(f'  {len(candles):,} bars  ({candles["timestamp_ny"].min()} → {candles["timestamp_ny"].max()})')

    print('\n  Loading daily volume profile (PD VAL) ...')
    daily_vp = load_daily_vp(DAILY_VP_PATH)
    print(f'  {len(daily_vp)} days')

    print('\n  Computing per-day session lows ...')
    day_levels = compute_session_lows_per_day(candles, daily_vp)
    print(f'  {len(day_levels)} days')

    print('\n  Computing per-day first-sweep timestamps ...')
    sweep_times = compute_first_sweep_times(candles, day_levels)
    sweep_times.to_csv(RESULTS_DIR / 'day_levels_sweeps.csv', index=False)
    print(f'  Wrote day_levels_sweeps.csv ({len(sweep_times)} days)')

    print('\n  Loading trades_with_levels ...')
    trades = load_trades(TRADES_WITH_LEVELS_PATH)
    print(f'  {len(trades):,} trades total')

    print('\n  Tagging M2+M3 long trades ...')
    tagged = tag_m2m3_longs(trades, sweep_times)
    print(f'  {len(tagged)} M2+M3 long decided trades')
    out_csv = RESULTS_DIR / 'm2m3_long_low_sweep_30s.csv'
    tagged.to_csv(out_csv, index=False)
    print(f'  Wrote {out_csv}')

    if tagged.empty:
        print('  No tagged trades — aborting analysis.')
        return

    # Headline universe = magnet_valid filter (the playbook universe)
    if 'magnet_valid' not in tagged.columns:
        print('  WARNING: magnet_valid column missing; using full M2+M3 set as universe.')
        playbook = tagged.copy()
    else:
        mv = tagged['magnet_valid'].astype(str).str.lower().eq('true')
        playbook = tagged[mv].copy()
    print(f'\n  Playbook universe (magnet_valid=True): n={len(playbook)}')
    print(f'  Broad universe (no magnet filter):       n={len(tagged)}')

    # ---------------------------------------------------------------
    # 0. Baseline replication: cited 57.3% / 1.36 PF on M3 longs OR.L-swept
    # ---------------------------------------------------------------
    print('\n' + '=' * 70)
    print('  0. BASELINE REPLICATION — OR.L-swept on M3 longs (no magnet filter)')
    print('=' * 70)
    m3 = tagged[tagged['macro_window'] == 3].copy()
    print(f'  M3 longs (no magnet filter): n={len(m3)}')
    print_split(m3, 'or_l_swept', 'or_l_swept (M3, no_mv)')
    m3_mv = playbook[playbook['macro_window'] == 3].copy()
    print(f'\n  M3 longs (magnet_valid=True): n={len(m3_mv)}')
    print_split(m3_mv, 'or_l_swept', 'or_l_swept (M3, mv=True)')

    # ---------------------------------------------------------------
    # 1. Per-level univariate split (BROAD + PLAYBOOK)
    # ---------------------------------------------------------------
    for label, universe in (('BROAD (no magnet filter)', tagged),
                            ('PLAYBOOK (magnet_valid=True)', playbook)):
        print('\n' + '=' * 70)
        print(f'  1. UNIVARIATE per-level split — {label}  (n={len(universe)})')
        print('=' * 70)
        for col in ACTIVATORS:
            print_split(universe, col)

        summary = summary_lift_table(universe, ACTIVATORS)
        print(f'\n  --- Summary lift table sorted by WR-lift ({label}) ---')
        print(summary.to_string(index=False))
        suffix = 'broad' if 'BROAD' in label else 'playbook'
        summary.to_csv(RESULTS_DIR / f'univariate_lift_{suffix}.csv', index=False)

    # ---------------------------------------------------------------
    # 2. Pairwise correlation matrix (Phi on booleans)
    # ---------------------------------------------------------------
    print('\n' + '=' * 70)
    print('  2. CORRELATION MATRIX — 8 activators (PLAYBOOK universe)')
    print('=' * 70)
    corr = phi_correlation_matrix(playbook, ACTIVATORS)
    print(corr.to_string())
    corr.to_csv(RESULTS_DIR / 'sweep_correlation_matrix.csv')

    # Also report base rates (P(swept=True) per activator) on PLAYBOOK
    print('\n  Base rates (P(swept=True) on PLAYBOOK):')
    for col in ACTIVATORS:
        rate = playbook[col].mean() * 100
        print(f'    {col:24s}  {rate:5.1f}%  (n_T={playbook[col].sum()}/{len(playbook)})')

    # ---------------------------------------------------------------
    # 3. Marginal lift after gating on level_confluence_count
    # ---------------------------------------------------------------
    print('\n' + '=' * 70)
    print('  3. MARGINAL LIFT — stratified by level_confluence_count band')
    print('=' * 70)
    if 'level_confluence_count' not in playbook.columns:
        print('  level_confluence_count column missing; skipping.')
    else:
        playbook['confluence_band'] = playbook['level_confluence_count'].apply(confluence_band)
        for col in ACTIVATORS:
            print(f'\n  --- {col} stratified by confluence_band ---')
            tab = stratified_split(playbook, col, 'confluence_band')
            print(tab.to_string(index=False))
            tab.to_csv(RESULTS_DIR / f'marginal_{col}_by_confluence.csv', index=False)

    # ---------------------------------------------------------------
    # 4. Logistic regression for cleanest marginal-lift estimate
    # ---------------------------------------------------------------
    print('\n' + '=' * 70)
    print('  4. LOGISTIC REGRESSION — outcome_win ~ activator + level_confluence_count + macro_window')
    print('=' * 70)
    controls = ['level_confluence_count', 'macro_window']
    logit_rows = []
    for col in ACTIVATORS:
        res = logit_marginal(playbook, col, controls)
        if res is None:
            print(f'  {col:24s}  [logit unavailable / failed to fit]')
            continue
        sig = '*' if res['p'] < 0.05 else ' '
        print(
            f'  {col:24s}  coef={res["coef"]:+6.3f}  se={res["se"]:.3f}  '
            f'95%CI=[{res["ci_lo"]:+6.3f}, {res["ci_hi"]:+6.3f}]  p={res["p"]:.3f} {sig}  n={res["n"]}'
        )
        logit_rows.append({'activator': col, **res})
    if logit_rows:
        pd.DataFrame(logit_rows).to_csv(RESULTS_DIR / 'logit_marginal.csv', index=False)

    # ---------------------------------------------------------------
    # 5. Stacking — n_lows_swept_clusters (4-way: OR.L, ON-cluster, PDL, PDVAL)
    # ---------------------------------------------------------------
    print('\n' + '=' * 70)
    print('  5. STACKING — by n_lows_swept_clusters (PLAYBOOK universe)')
    print('=' * 70)
    print('  cluster_count = sum of {or_l, on_low, pdl_overnight, pdval_overnight}')
    rows = []
    for n in sorted(playbook['n_lows_swept_clusters'].unique()):
        sub = playbook[playbook['n_lows_swept_clusters'] == n]
        s = cell_stats(sub)
        if s is None:
            continue
        rows.append({
            'cluster_count': int(n), 'n': s['n'], 'wins': s['wins'], 'losses': s['losses'],
            'wr': round(s['wr'], 1), 'pf': round(s['pf'], 2) if s['pf'] != float('inf') else None,
            'ev': round(s['ev'], 2), 'mean_mfe_r': round(s['mean_mfe_r'], 2),
        })
    stack = pd.DataFrame(rows)
    print(stack.to_string(index=False))
    stack.to_csv(RESULTS_DIR / 'stacking_by_clusters.csv', index=False)

    # ---------------------------------------------------------------
    # 6. By macro_window split for the headline activator (whichever wins)
    # ---------------------------------------------------------------
    print('\n' + '=' * 70)
    print('  6. PER-MACRO breakdown for each activator (PLAYBOOK)')
    print('=' * 70)
    for col in ACTIVATORS:
        print(f'\n  --- {col} ---')
        for m in (2, 3):
            sub = playbook[playbook['macro_window'] == m]
            s_t = cell_stats(sub[sub[col]])
            s_f = cell_stats(sub[~sub[col]])
            t_str = (f'n={s_t["n"]} wr={s_t["wr"]:.1f}% pf={fmt_pf(s_t["pf"])} ev={s_t["ev"]:+5.2f}'
                     if s_t else 'n=0')
            f_str = (f'n={s_f["n"]} wr={s_f["wr"]:.1f}% pf={fmt_pf(s_f["pf"])} ev={s_f["ev"]:+5.2f}'
                     if s_f else 'n=0')
            print(f'    M{m}  swept=False: {f_str}')
            print(f'    M{m}  swept=True : {t_str}')

    print('\nDone.')


if __name__ == '__main__':
    main()
