# Study: Displacement Continuation (Big Candle + Pullback)

## Question
Does a displacement candle continuation entry (50% pullback) outperform baseline, and under which context combos?

## Methodology
- Data: `data/consolidated/nq-front-month.ohlcv-30s.csv`
- Displacement: `abs(close-open) > k * rolling_20_avg_body` where `k in {2.0, 2.5, 3.0}`
- Entry: after retrace to midpoint (50%) within 2 pts, enter continuation on next candle close
- Retrace depth modes: `50_only`, `allow_61_8`, `allow_75`
- Stop: opposite body end `+/- 2` pts (directional)
- Targets: 1R, 2R, 3R tracking via MFE progression
- Context grid:
  - macro scope: `W1`, `W1+W2`, `all`
  - VIXY regime: `low`, `medium`, `high`, `all`
  - gap alignment with direction: `yes/no/all`
  - 9:30 candle alignment with direction: `yes/no/all`
- Statistics:
  - minimum sample size per combo: `n >= 30`
  - permutation test with BH FDR correction at `q=0.10`

## How To Run
```bash
python studies/displacement_continuation/run.py --perms 300
```

## Results
- Run date: 2026-05-08
- Bars analyzed (session only): 52,780 (`9:30-10:15 ET` slice of consolidated 30s history)
- Generated trades (all parameter sets): 19,218
- Tradeable outcomes (`win/loss`): 16,741
- Baseline (all thresholds + retrace modes): **49.37% WR**, **0.975 PF**
- Qualifying combo rows (`n >= 30`): 903
- BH FDR survivors at `q=0.10` (WR): 5

Top positive WR/PF cells (did not survive BH FDR at this permutation depth):
- `threshold=2.5`, `retrace=allow_61_8`, `macro=w1`, `vixy=low`, `gap_aligned=no`, `930_aligned=yes`: `n=39`, `WR=64.10%`, `PF=1.79`
- `threshold=3.0`, `retrace=allow_75`, `macro=w1_w2`, `vixy=medium`, `gap_aligned=yes`, `930_aligned=yes`: `n=43`, `WR=62.79%`, `PF=1.69`
- `threshold=3.0`, `retrace=allow_75`, `macro=all`, `vixy=medium`, `gap_aligned=yes`, `930_aligned=yes`: `n=57`, `WR=61.40%`, `PF=1.59`

FDR-significant cells were all downside cohorts (WR below baseline), led by:
- `threshold=2.0`, `retrace=allow_75`, `macro=all`, `vixy=medium`, `gap_aligned=no`, `930_aligned=all`: `n=436`, `WR=42.89%`, `PF=0.75`
- `threshold=2.0`, `retrace=allow_75`, `macro=all`, `vixy=medium`, `gap_aligned=all`, `930_aligned=no`: `n=414`, `WR=41.06%`, `PF=0.70`
- `threshold=2.0`, `retrace=allow_61_8`, `macro=all`, `vixy=medium`, `gap_aligned=no`, `930_aligned=no`: `n=197`, `WR=40.10%`, `PF=0.67`

## Outputs
- `results/trades.csv`
- `results/summary_by_combo.csv`
- `results/top_combos.csv`

## Conclusions
- On this implementation, the displacement-continuation model is roughly breakeven-to-negative at baseline (`49.37% WR`, `0.975 PF`), below the Notion baseline target.
- The strongest positive slices are small-to-mid sample and do not survive BH FDR at `q=0.10` with `--perms 300`.
- The robust signal appears more useful for **avoidance** than selection: medium-VIXY + misalignment filters show statistically reliable underperformance.
- Next pass should increase permutation depth (for sharper p-values), and test alternate entry trigger variants (e.g., limit-at-50 fill vs next-close continuation) before making playbook decisions.

## Caveats
- This study currently evaluates only the model session window (`9:30-10:15 ET`) for both displacement detection and outcome path, to match project trade-window semantics and keep compute tractable.
- Permutation p-values are based on `300` permutations per combo; increase for publication-grade significance stability.
