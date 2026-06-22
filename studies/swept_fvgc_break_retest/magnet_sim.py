#!/usr/bin/env python3
"""
§7 Dynamic-magnet exit simulator.

Each signal exits at the NEXT UNTESTED MAGNET (target, from features.next_magnet)
OR at STRUCTURE INVALIDATION (stop = the model's structure-based SL, opposite
side of the FVG), whichever is hit first, walking 30s bars forward to EOD.

R denominator = structure-stop distance = sl_dist (the model's clamped structure
stop). This keeps every signal's outcome on a consistent R scale and comparable
to the cached fixed-R hit_XR fields (retained, not recomputed).

Exit rules:
  - target hit  -> realized_r = +magnet_dist_R   (magnet_dist_pts / sl_dist)
  - stop hit    -> realized_r = -1.0
  - both in one bar -> 'ambiguous', conservatively take the stop (-1.0)
  - neither by EOD -> exit at day's last bar close; realized_r = signed move / sl_dist
  - no untested magnet ahead -> 'eod' fallback (flagged no_magnet)

Variant: realized_r_be applies the validated VWAP-play nuance — once MFE reaches
+1R, the stop moves to break-even (entry); a return to entry then exits at R=0
instead of -1R.

Inputs : results/signals_enriched.csv (from features.py).
Outputs: results/signals_simulated.csv (enriched + sim columns).
"""

from __future__ import annotations

import argparse
import sys
import time as _time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.data import load_candles  # noqa: E402
from studies.swept_fvgc_break_retest.features import CandleIndex, CONS_30S  # noqa: E402

STUDY_DIR = Path(__file__).resolve().parent
RESULTS_DIR = STUDY_DIR / 'results'


def simulate(ci: CandleIndex, df: pd.DataFrame) -> pd.DataFrame:
    exit_type = []
    realized_r = []
    realized_r_be = []
    bars_held = []
    no_magnet = []
    target_r_col = []

    for _, s in df.iterrows():
        entry_idx = int(s['entry_idx'])
        direction = str(s['direction'])
        entry = float(s['entry_price'])
        d = ci.date[entry_idx] if 0 <= entry_idx < ci.n else None

        # structure stop + R denominator
        sl_raw = s.get('sl')
        sl_dist_raw = s.get('sl_dist')
        try:
            sl = float(sl_raw)
            sl_dist = float(sl_dist_raw)
        except (TypeError, ValueError):
            sl, sl_dist = np.nan, np.nan
        if np.isnan(sl) or np.isnan(sl_dist) or sl_dist <= 0:
            # non-tradeable by the model's own SL rules
            exit_type.append('skip'); realized_r.append(np.nan)
            realized_r_be.append(np.nan); bars_held.append(np.nan)
            no_magnet.append(None); target_r_col.append(np.nan)
            continue

        magnet_price = s.get('magnet_price')
        has_magnet = pd.notna(magnet_price)
        magnet_price = float(magnet_price) if has_magnet else np.nan
        target_r = (abs(magnet_price - entry) / sl_dist) if has_magnet else np.nan
        target_r_col.append(target_r)

        end = ci.date_end.get(d, ci.n)
        et = None
        rr = None
        be_armed = False
        rr_be = None
        held = 0
        for j in range(entry_idx + 1, end):
            held = j - entry_idx
            hi, lo = ci.high[j], ci.low[j]

            if direction == 'long':
                stop_hit = lo <= sl
                tgt_hit = has_magnet and hi >= magnet_price
                mfe_1r = hi >= entry + sl_dist
            else:
                stop_hit = hi >= sl
                tgt_hit = has_magnet and lo <= magnet_price
                mfe_1r = lo <= entry - sl_dist

            # arm break-even once +1R favorable reached (for BE variant)
            if not be_armed and mfe_1r:
                be_armed = True

            # --- primary exit (fixed structure stop) ---
            if et is None:
                if stop_hit and tgt_hit:
                    et, rr = 'ambiguous', -1.0
                elif stop_hit:
                    et, rr = 'stop', -1.0
                elif tgt_hit:
                    et, rr = 'target', target_r

            # --- BE variant exit (independent bookkeeping) ---
            if rr_be is None:
                if be_armed:
                    be_stop_hit = (lo <= entry) if direction == 'long' else (hi >= entry)
                    if tgt_hit and be_stop_hit:
                        rr_be = 0.0  # conservative: BE before target in same bar
                    elif tgt_hit:
                        rr_be = target_r
                    elif be_stop_hit:
                        rr_be = 0.0
                else:
                    if stop_hit and tgt_hit:
                        rr_be = -1.0
                    elif stop_hit:
                        rr_be = -1.0
                    elif tgt_hit:
                        rr_be = target_r

            if et is not None and rr_be is not None:
                break

        # EOD fallback
        if et is None:
            last = max(entry_idx, end - 1)
            close = ci.close[last]
            signed = (close - entry) if direction == 'long' else (entry - close)
            et, rr = 'eod', signed / sl_dist
            held = last - entry_idx
        if rr_be is None:
            last = max(entry_idx, end - 1)
            close = ci.close[last]
            signed = (close - entry) if direction == 'long' else (entry - close)
            rr_be = signed / sl_dist

        exit_type.append(et)
        realized_r.append(round(rr, 4))
        realized_r_be.append(round(rr_be, 4))
        bars_held.append(held)
        no_magnet.append(not has_magnet)

    out = df.copy()
    out['sim_exit_type'] = exit_type
    out['sim_realized_r'] = realized_r
    out['sim_realized_r_be'] = realized_r_be
    out['sim_bars_held'] = bars_held
    out['sim_no_magnet'] = no_magnet
    out['sim_target_r'] = target_r_col
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='infile', default=str(RESULTS_DIR / 'signals_enriched.csv'))
    ap.add_argument('--out', default=str(RESULTS_DIR / 'signals_simulated.csv'))
    args = ap.parse_args()

    t0 = _time.time()
    df = pd.read_csv(args.infile)
    candles = load_candles(CONS_30S)
    ci = CandleIndex(candles)
    print(f"  Loaded {len(df)} signals + CandleIndex in {_time.time()-t0:.1f}s")

    t1 = _time.time()
    out = simulate(ci, df)
    print(f"  Simulated in {_time.time()-t1:.1f}s")

    trad = out[out['sim_exit_type'] != 'skip']
    et = trad['sim_exit_type'].value_counts().to_dict()
    print(f"  Tradeable: {len(trad)}  exit types: {et}")
    print(f"  mean realized_r: {trad['sim_realized_r'].mean():.3f}  "
          f"mean realized_r_be: {trad['sim_realized_r_be'].mean():.3f}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {len(out)} rows -> {args.out}")


if __name__ == '__main__':
    main()
