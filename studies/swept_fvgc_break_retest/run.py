#!/usr/bin/env python3
"""
Swept-Level FVGC Break-&-Retest — orchestration.

Phase 0  : prior-art diagnosis (written up in analysis.md).
Phase 4  : causal per-signal feature enrichment            -> features.py
Phase 7  : dynamic-magnet exit simulation                  -> magnet_sim.py
Phase A  : baseline + regime-matched baselines             -> baseline.py
Phase B–F: single-factor sweeps -> ranking -> tiered mining -> OOS -> regime/TOD.
           (PENDING the lookahead checkpoint on the §4 feature catalog.)

Usage:
    python run.py            # run built phases (4 -> 7 -> A) end to end
    python run.py --sample N # quick slice for iteration
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fvgc.data import load_candles  # noqa: E402
from studies.swept_fvgc_break_retest import features as feat  # noqa: E402
from studies.swept_fvgc_break_retest import magnet_sim as sim  # noqa: E402
from studies.swept_fvgc_break_retest import baseline as base  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / 'results'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', type=int, default=None)
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60, "\nPhase 4 — feature enrichment\n", "=" * 60)
    enriched = feat.enrich(sample=args.sample)
    enriched.to_csv(RESULTS_DIR / 'signals_enriched.csv', index=False)

    print("=" * 60, "\nPhase 7 — dynamic-magnet simulation\n", "=" * 60)
    candles = load_candles(feat.CONS_30S)
    ci = feat.CandleIndex(candles)
    simulated = sim.simulate(ci, enriched)
    simulated.to_csv(RESULTS_DIR / 'signals_simulated.csv', index=False)

    print("=" * 60, "\nPhase A — baseline\n", "=" * 60)
    base.run()

    print("\nPhase B–F pending lookahead checkpoint (see analysis.md).")


if __name__ == '__main__':
    main()
