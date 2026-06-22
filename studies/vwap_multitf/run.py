#!/usr/bin/env python3
"""
VWAP Continuation — Multi-Timeframe Extension (1m, 2m, 3m).

Uses the EXACT same simulate_trade logic as the validated 30s study at:
  studies/vwap_continuation_8yr/run.py

A-tier filters (same as validated 30s run):
  - N_trend=3, tol=2.0pt, gap-aligned
  - entry_time < 10:00 ET
  - no red_folder_news
  - not Wednesday
  - prior_day_type != reversal_up
  - R0 >= 10 pts

Primary metric reported: BE@1R→2.5R (r_be1_25), same as 30s validated.

Output:
  studies/vwap_multitf/results/{tf}_trades.csv  per TF
  Final summary table + per-year PF table printed to stdout.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import time as dtime

REPO_ROOT = Path(__file__).resolve().parents[2]
STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TRADING_DAYS = REPO_ROOT / 'data/trading_days/trading_days.csv'

TF_FILES = {
    '1m': REPO_ROOT / 'data/consolidated/nq-front-month.ohlcv-1m.parquet',
    '2m': REPO_ROOT / 'data/consolidated/nq-front-month.ohlcv-2m.parquet',
    '3m': REPO_ROOT / 'data/consolidated/nq-front-month.ohlcv-3m.parquet',
}

RTH_OPEN = dtime(9, 30)
RTH_CUTOFF_ENTRY = dtime(10, 0)
RTH_CLOSE = dtime(16, 0)
MAX_HOLD = dtime(10, 30)

# A-tier signal parameters
N_TREND = 3
TOL_PTS = 2.0
R0_MIN = 10.0


# ----------------------------- data loading -----------------------------

def load_tf_rth(tf: str) -> pd.DataFrame:
    path = TF_FILES[tf]
    print(f"Loading {tf} candles from {path} ...")
    df = pd.read_parquet(path)
    df['ts_ny'] = df['timestamp_ny']
    df['date'] = df['ts_ny'].dt.date
    df['t'] = df['ts_ny'].dt.time
    # RTH window 9:30-10:30 only (max hold window)
    df = df[(df['t'] >= RTH_OPEN) & (df['t'] <= MAX_HOLD)].copy()
    df = df.sort_values('ts_ny').reset_index(drop=True)
    print(f"  rows in 9:30-10:30 window: {len(df):,}")
    print(f"  date range: {df['date'].min()} -> {df['date'].max()}")
    return df


def load_trading_days() -> pd.DataFrame:
    td = pd.read_csv(TRADING_DAYS)
    td['date'] = pd.to_datetime(td['date']).dt.date
    return td


# ----------------------------- simulate_trade (EXACT COPY from 30s run.py) -------------

def simulate_trade(bars: pd.DataFrame, entry_idx: int, side: str,
                   entry_price: float, vwap_entry: float, r0: float,
                   vwap_arr: np.ndarray) -> dict:
    """
    Walk forward bar-by-bar. Record fixed-R hits and dynamic-VWAP exit.
    Returns the resolved trade dict with R outcomes for several exit variants.

    EXACT COPY from studies/vwap_continuation_8yr/run.py — do not modify.
    """
    highs = bars['high'].values
    lows = bars['low'].values
    closes = bars['close'].values
    times = bars['t'].values

    # Pre-define fixed-R targets
    r_targets = [1.0, 1.5, 2.0, 2.5, 3.0]
    if side == 'long':
        tp_prices = {r: entry_price + r * r0 for r in r_targets}
    else:
        tp_prices = {r: entry_price - r * r0 for r in r_targets}

    # Record first index where each TP touched and where VWAP-close-stop hit
    tp_hit_idx = {r: None for r in r_targets}
    sl_idx = None    # dynamic VWAP close stop
    sl_price = None
    one_r_idx = None  # first time +1R reached (used for BE moves)

    for k in range(entry_idx + 1, len(bars)):
        if times[k] > RTH_CLOSE:
            break
        # check TP touches (intrabar)
        for r in r_targets:
            if tp_hit_idx[r] is None:
                if side == 'long' and highs[k] >= tp_prices[r]:
                    tp_hit_idx[r] = k
                elif side == 'short' and lows[k] <= tp_prices[r]:
                    tp_hit_idx[r] = k
        if one_r_idx is None and tp_hit_idx[1.0] is not None:
            one_r_idx = tp_hit_idx[1.0]
        # check dynamic SL (close-based against current VWAP)
        v = vwap_arr[k]
        if sl_idx is None:
            if side == 'long' and closes[k] < v:
                sl_idx = k
                sl_price = closes[k]
            elif side == 'short' and closes[k] > v:
                sl_idx = k
                sl_price = closes[k]
        # safety cutoff at MAX_HOLD or session end
        if times[k] >= MAX_HOLD and sl_idx is None and tp_hit_idx[r_targets[-1]] is None:
            sl_idx = k
            sl_price = closes[k]
            break
        if sl_idx is not None and all(v is not None for v in tp_hit_idx.values()):
            break

    # Resolve each exit variant:
    out = {}
    for r in r_targets:
        # Fixed-R: take TP if hit before SL; else SL close
        tp_i = tp_hit_idx[r]
        if tp_i is not None and (sl_idx is None or tp_i <= sl_idx):
            out[f'r_fixed_{r}'] = float(r)
        else:
            if sl_idx is not None:
                # actual loss in R units: (entry - sl_price)/r0 for long; flipped for short
                loss = (sl_price - entry_price) / r0 if side == 'long' else (entry_price - sl_price) / r0
                out[f'r_fixed_{r}'] = float(loss)
            else:
                # neither hit by MAX_HOLD — exit at close of last bar in window
                last_close = closes[min(len(bars) - 1, entry_idx + 120)]
                pnl = (last_close - entry_price) / r0 if side == 'long' else (entry_price - last_close) / r0
                out[f'r_fixed_{r}'] = float(pnl)

    # BE@1R → 2.5R
    if one_r_idx is not None:
        # after +1R, SL becomes BE (entry price). Check if 2.5R hit before BE breach
        tp25_i = tp_hit_idx[2.5]
        # find first bar after one_r_idx that breaks BE
        be_break_i = None
        for k in range(one_r_idx + 1, len(bars)):
            if times[k] > RTH_CLOSE:
                break
            if side == 'long' and lows[k] <= entry_price:
                be_break_i = k; break
            if side == 'short' and highs[k] >= entry_price:
                be_break_i = k; break
        if tp25_i is not None and (be_break_i is None or tp25_i <= be_break_i):
            out['r_be1_25'] = 2.5
        else:
            out['r_be1_25'] = 0.0
    else:
        # never reached 1R; use the same as fixed_1 outcome (loss)
        out['r_be1_25'] = out['r_fixed_1.0']

    # BE@1R → 3R
    if one_r_idx is not None:
        tp3_i = tp_hit_idx[3.0]
        be_break_i = None
        for k in range(one_r_idx + 1, len(bars)):
            if times[k] > RTH_CLOSE:
                break
            if side == 'long' and lows[k] <= entry_price:
                be_break_i = k; break
            if side == 'short' and highs[k] >= entry_price:
                be_break_i = k; break
        if tp3_i is not None and (be_break_i is None or tp3_i <= be_break_i):
            out['r_be1_3'] = 3.0
        else:
            out['r_be1_3'] = 0.0
    else:
        out['r_be1_3'] = out['r_fixed_1.0']

    out['exit_idx'] = sl_idx if sl_idx is not None else tp_hit_idx[1.0]
    out['tp1_idx'] = tp_hit_idx[1.0]
    out['sl_idx'] = sl_idx
    return out


# ----------------------------- signal generation -----------------------------

def generate_day_signals(day_bars: pd.DataFrame,
                          n_trend: int,
                          tol_pts: float,
                          entry_cutoff: dtime,
                          gap_dir: str | None = None) -> list[dict]:
    """
    Walk one day of RTH bars. Emit one trade per detected entry; reset state on resolution.

    gap_dir: 'up' / 'down' / None — if not None, only emits trades aligned with gap.

    SAME logic as original run.py; adapted to generic TF (not 30s-specific).
    """
    bars = day_bars.reset_index(drop=True)
    if len(bars) < n_trend + 2:
        return []

    closes = bars['close'].values
    highs = bars['high'].values
    lows = bars['low'].values
    vols = bars['volume'].values.astype(float)
    times = bars['t'].values

    # Anchored VWAP (close-weighted, mirroring original spec)
    cum_pv = np.cumsum(closes * vols)
    cum_v = np.cumsum(vols)
    vwap = cum_pv / np.where(cum_v == 0, 1, cum_v)

    trades = []
    i = 0
    while i < len(bars):
        # Establish trend: find n_trend consecutive closes on one side of VWAP
        side = None
        for j in range(i, len(bars) - n_trend - 1):
            window = closes[j:j + n_trend]
            v_win = vwap[j:j + n_trend]
            if np.all(window > v_win):
                side = 'long'
                anchor_idx = j + n_trend - 1
                break
            if np.all(window < v_win):
                side = 'short'
                anchor_idx = j + n_trend - 1
                break
        else:
            break

        # From anchor_idx+1 onward, look for pullback then re-close
        pullback_seen = False
        entry_idx = None
        for k in range(anchor_idx + 1, len(bars)):
            if times[k] >= entry_cutoff:
                break
            v = vwap[k]
            if side == 'long':
                if not pullback_seen and lows[k] <= v + tol_pts:
                    pullback_seen = True
                    continue
                if pullback_seen and closes[k] > v:
                    entry_idx = k
                    break
            else:
                if not pullback_seen and highs[k] >= v - tol_pts:
                    pullback_seen = True
                    continue
                if pullback_seen and closes[k] < v:
                    entry_idx = k
                    break

        if entry_idx is None:
            # advance past this anchor and look again later
            i = anchor_idx + 1
            continue

        # Filter by gap alignment if requested
        if gap_dir is not None:
            if side == 'long' and gap_dir != 'up':
                i = entry_idx + 1
                continue
            if side == 'short' and gap_dir != 'down':
                i = entry_idx + 1
                continue

        entry_price = closes[entry_idx]
        v_entry = vwap[entry_idx]
        r0 = abs(entry_price - v_entry)
        if r0 < 0.25:
            # too tight, skip — would produce noise R
            i = entry_idx + 1
            continue

        # Simulate trade forward
        trade = simulate_trade(
            bars, entry_idx, side, entry_price, v_entry, r0, vwap
        )
        trade.update({
            'side': side,
            'entry_idx': entry_idx,
            'entry_time': times[entry_idx],
            'entry_price': float(entry_price),
            'vwap_at_entry': float(v_entry),
            'r0': float(r0),
            'n_trend': n_trend,
            'tol_pts': tol_pts,
        })
        trades.append(trade)
        # restart search past this trade exit
        i = max(trade.get('exit_idx', entry_idx) + 1, entry_idx + 1)

    return trades


# ----------------------------- aggregation helpers -----------------------------

def stats(rs: pd.Series) -> dict:
    """Compute WR, BE%, L%, PF, EV in R units."""
    if len(rs) == 0:
        return dict(n=0, wr=np.nan, be=np.nan, loss=np.nan, pf=np.nan, ev=np.nan)
    wins = rs[rs > 0].sum()
    losses = -rs[rs < 0].sum()
    pf = wins / losses if losses > 0 else np.inf
    return dict(
        n=int(len(rs)),
        wr=float((rs > 0).mean()),
        be=float((rs == 0).mean()),
        loss=float((rs < 0).mean()),
        pf=float(pf),
        ev=float(rs.mean()),
    )


# ----------------------------- per-TF runner -----------------------------

def run_tf(tf: str, td: pd.DataFrame) -> pd.DataFrame:
    """Run A-tier VWAP continuation signals on a single timeframe."""
    bars = load_tf_rth(tf)

    # Build trading-day context lookup
    td_by_date = {row['date']: row for _, row in td.iterrows()}

    # A-tier day filter
    def day_eligible(ctx) -> bool:
        if ctx is None:
            return False
        if bool(ctx.get('has_red_folder_news')):
            return False
        if ctx.get('day_of_week_name') == 'Wednesday':
            return False
        if ctx.get('prior_day_type') == 'reversal_up':
            return False
        gap = ctx.get('gap_from_prior_close')
        if gap is None or gap == 0:
            return False  # flat gap — no gap_dir, cannot be gap-aligned
        return True

    all_trades = []
    grouped = bars.groupby('date', sort=True)
    total_days = len(grouped)
    print(f"\n[{tf}] Running signals on {total_days} trading days ...")

    for di, (d, day_bars) in enumerate(grouped):
        if di % 200 == 0:
            print(f"  [{tf}] day {di}/{total_days}: {d}")

        ctx = td_by_date.get(d)
        if not day_eligible(ctx):
            continue

        gap = ctx.get('gap_from_prior_close', 0) or 0
        gap_dir = 'up' if gap > 0 else 'down'

        day_trades = generate_day_signals(
            day_bars,
            n_trend=N_TREND,
            tol_pts=TOL_PTS,
            entry_cutoff=RTH_CUTOFF_ENTRY,
            gap_dir=gap_dir,
        )

        for t in day_trades:
            if t['r0'] < R0_MIN:
                continue
            t['date'] = d
            t['gap'] = gap
            t['gap_dir'] = gap_dir
            t['day_of_week_name'] = ctx.get('day_of_week_name')
            t['has_red_folder_news'] = bool(ctx.get('has_red_folder_news'))
            t['prior_day_type'] = ctx.get('prior_day_type')
            t['tf'] = tf
            all_trades.append(t)

    df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()
    if not df.empty:
        out_path = RESULTS_DIR / f'{tf}_trades.csv'
        df.to_csv(out_path, index=False)
        print(f"  [{tf}] Saved {len(df)} trades -> {out_path}")
    else:
        print(f"  [{tf}] No trades found!")
    return df


# ----------------------------- main -----------------------------

def main():
    print("=" * 70)
    print("VWAP Continuation — Multi-TF Extension (1m, 2m, 3m)")
    print("=" * 70)
    print(f"Filters: N_trend={N_TREND}, tol={TOL_PTS}pt, gap-aligned,")
    print(f"         entry<10:00, no red_folder_news, no Wednesday, no reversal_up, R0>={R0_MIN}pt")
    print()

    td = load_trading_days()

    results = {}  # tf -> df

    for tf in ['1m', '2m', '3m']:
        df = run_tf(tf, td)
        results[tf] = df

    # ----------------------------- summary table -----------------------------
    print()
    print("=" * 70)
    print("SUMMARY — BE@1R→2.5R (r_be1_25)")
    print("=" * 70)

    # Validated 30s reference numbers (from all_signals.parquet A-tier filter)
    ref_30s = dict(tf='30s (ref)', n=313, trades_per_yr=313/8, wr=37.4, be=47.3, loss=15.3, pf=4.61, ev=0.73)

    header = f"{'TF':>6} | {'n':>5} | {'tr/yr':>6} | {'W%':>6} | {'BE%':>6} | {'L%':>6} | {'PF':>6} | {'EV':>6}"
    sep = "-" * len(header)
    print(header)
    print(sep)

    # Print 30s reference
    r = ref_30s
    print(f"{'30s*':>6} | {r['n']:>5} | {r['trades_per_yr']:>6.1f} | {r['wr']:>5.1f}% | {r['be']:>5.1f}% | {r['loss']:>5.1f}% | {r['pf']:>6.2f} | {r['ev']:>+6.2f}R")
    print(sep)

    rows_for_year = {}

    for tf in ['1m', '2m', '3m']:
        df = results[tf]
        if df.empty:
            print(f"{'  '+tf:>6} | {'—':>5} | {'—':>6} | {'—':>6} | {'—':>6} | {'—':>6} | {'—':>6} | {'—':>6}")
            continue
        rs = df['r_be1_25']
        s = stats(rs)
        # Estimate year range from data
        df['date'] = pd.to_datetime(df['date'])
        n_years = (df['date'].max() - df['date'].min()).days / 365.25
        n_years = max(n_years, 1.0)
        trades_per_yr = s['n'] / n_years
        print(f"{'  '+tf:>6} | {s['n']:>5} | {trades_per_yr:>6.1f} | {s['wr']*100:>5.1f}% | {s['be']*100:>5.1f}% | {s['loss']*100:>5.1f}% | {s['pf']:>6.2f} | {s['ev']:>+6.2f}R")

        # Collect yearly data
        df['year'] = df['date'].dt.year
        yr_pf = {}
        for yr, grp in df.groupby('year'):
            rs_yr = grp['r_be1_25']
            w = rs_yr[rs_yr > 0].sum()
            l = -rs_yr[rs_yr < 0].sum()
            yr_pf[yr] = round(w / l, 2) if l > 0 else (np.inf if w > 0 else np.nan)
        rows_for_year[tf] = yr_pf

    print(sep)
    print("* 30s reference: from validated all_signals.parquet (A-tier filters applied offline)")
    print()

    # ----------------------------- per-year PF table -----------------------------
    print("=" * 70)
    print("PER-YEAR PF (BE@1R→2.5R) — rows=year, cols=TF")
    print("=" * 70)
    if rows_for_year:
        all_years = sorted(set(yr for d in rows_for_year.values() for yr in d.keys()))
        tfs_present = [tf for tf in ['1m', '2m', '3m'] if tf in rows_for_year]
        col_header = f"{'Year':>6} | " + " | ".join(f"{tf:>8}" for tf in tfs_present)
        print(col_header)
        print("-" * len(col_header))
        for yr in all_years:
            row = f"{yr:>6} | "
            cells = []
            for tf in tfs_present:
                val = rows_for_year.get(tf, {}).get(yr, None)
                if val is None:
                    cells.append(f"{'—':>8}")
                elif np.isinf(val):
                    cells.append(f"{'inf':>8}")
                else:
                    cells.append(f"{val:>8.2f}")
            print(row + " | ".join(cells))

    print()
    print("Results saved to:", RESULTS_DIR)


if __name__ == '__main__':
    main()
