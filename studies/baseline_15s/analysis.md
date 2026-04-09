# Study: Indicator baseline (15s)

## Question

How does the FVGC entry model behave on 15s bars over the full available consolidated NQ history?

## Methodology

- **Data:** `data/consolidated/nq-front-month.ohlcv-15s.csv` — front-month continuous series, 15s OHLCV (generated via `tools/consolidate_data.py` from the same 1s raw source as the 30s baseline).
- **Model:** `fvgc/model.py` — signal generation only (no external context).
- **Execution:** `fvgc/engine.py` `simulate_trades` — first touch of SL or TP on subsequent **15s** bars. SL/TP levels use the same constants as the 30s baseline (15–60 pt range, 1:1 RR).
- **Purpose:** Compare against 30s canonical baseline to understand timeframe sensitivity.

## How to run

```bash
python studies/baseline_15s/run.py
```

Verifiable outputs: `results/trades.csv`, `results/fvgs.csv` (committed; re-run `run.py` to regenerate).

## Results

Model version: v2.0.5  
Data range: 2023-10-01 → 2026-03-25  
Bars: 3,138,139 | FVGs: 77,842 | Signals: 3,707

| Metric | Value |
|---|---|
| Trades executed | 2,383 |
| Skipped (no SL/TP) | 1,324 |
| Win rate | **52%** |
| Total P&L | **+2,640 pts** |

| Variant | W | L | WR | P&L |
|---|---|---|---|---|
| bos | 365 | 348 | 51% | +420 |
| ifvg | 180 | 169 | 52% | +495 |
| no_fvg | 592 | 527 | 53% | +1,395 |
| protected_swing | 111 | 91 | **55%** | +330 |

## Conclusions

- 15s produces the largest trade sample (2,383) of all tested timeframes — strong statistical confidence.
- All four variants are positive at 15s, including `bos` which turns negative at 1m.
- `protected_swing` is the best-performing variant at 55% WR.
- Compared to 1m, the 15s baseline has 3x more trades and is the only timeframe where `bos` is profitable.
- **Recommended as a secondary baseline for high-resolution pattern analysis.** The 30s file remains canonical.
