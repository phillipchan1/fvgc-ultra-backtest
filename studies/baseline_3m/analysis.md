# Study: Indicator baseline (3m)

## Question

How does the FVGC entry model behave on 3m bars over the full available consolidated NQ history?

## Methodology

- **Data:** `data/consolidated/nq-front-month.ohlcv-3m.csv` — front-month continuous series, 3m OHLCV (resampled from 30s consolidated via inline script).
- **Model:** `fvgc/model.py` — signal generation only (no external context).
- **Execution:** `fvgc/engine.py` `simulate_trades` — first touch of SL or TP on subsequent **3m** bars. SL/TP levels use the same constants as the 30s baseline (15–60 pt range, 1:1 RR).
- **Purpose:** Compare against 30s canonical baseline to understand timeframe sensitivity.

## How to run

```bash
python studies/baseline_3m/run.py
```

Verifiable outputs: `results/trades.csv`, `results/fvgs.csv` (committed; re-run `run.py` to regenerate).

## Results

Model version: v2.0.5  
Data range: 2023-10-01 → 2026-03-25  
Bars: 265,575 | FVGs: 16,241 | Signals: 293

| Metric | Value |
|---|---|
| Trades executed | 200 |
| Skipped (no SL/TP) | 93 |
| Win rate | **59%** |
| Total P&L | **+1,385 pts** |

| Variant | W | L | WR | P&L |
|---|---|---|---|---|
| bos | 29 | 36 | 45% | -215 |
| ifvg | 8 | 3 | 73% | +245 |
| no_fvg | 50 | 27 | **65%** | +965 |
| protected_swing | 30 | 16 | **65%** | +390 |

## Conclusions

- 3m shows the strongest aggregate WR among timeframes with meaningful sample size (200 trades).
- `no_fvg` and `protected_swing` both hit 65% — notable given 200-trade sample.
- `ifvg` at 73% is eye-catching but n=11 is too small to conclude much.
- `bos` continues its pattern of underperformance at 45% — consistent across 1m, 2m, 3m.
- **Caution:** 200 trades is at the low end for statistical confidence on per-variant conclusions; treat as directional signal, not definitive.
