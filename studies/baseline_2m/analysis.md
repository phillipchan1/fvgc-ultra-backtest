# Study: Indicator baseline (2m)

## Question

How does the FVGC entry model behave on 2m bars over the full available consolidated NQ history?

## Methodology

- **Data:** `data/consolidated/nq-front-month.ohlcv-2m.csv` — front-month continuous series, 2m OHLCV (resampled from 30s consolidated via inline script).
- **Model:** `fvgc/model.py` — signal generation only (no external context).
- **Execution:** `fvgc/engine.py` `simulate_trades` — first touch of SL or TP on subsequent **2m** bars. SL/TP levels use the same constants as the 30s baseline (15–60 pt range, 1:1 RR).
- **Purpose:** Compare against 30s canonical baseline to understand timeframe sensitivity.

## How to run

```bash
python studies/baseline_2m/run.py
```

Outputs under `logs/` (gitignored): `baseline_2m_trades.csv`, `baseline_2m_fvgs.csv`.

## Results

Model version: v2.0.5  
Data range: 2023-10-01 → 2026-03-25  
Bars: 398,364 | FVGs: 21,939 | Signals: 417

| Metric | Value |
|---|---|
| Trades executed | 314 |
| Skipped (no SL/TP) | 103 |
| Win rate | **56%** |
| Total P&L | **+1,269 pts** |

| Variant | W | L | WR | P&L |
|---|---|---|---|---|
| bos | 47 | 49 | 49% | -90 |
| ifvg | 13 | 7 | **65%** | +245 |
| no_fvg | 63 | 44 | **59%** | +789 |
| protected_swing | 49 | 37 | 57% | +325 |

## Conclusions

- 2m shows a meaningful WR lift over 1m (56% vs 50%) with reasonable sample size (314 trades).
- `no_fvg` and `protected_swing` are strong; `ifvg` at 65% is promising but only 20 trades.
- `bos` dips back to near-breakeven (49%) — consistent with its underperformance at 1m.
- Average SL distance increases vs shorter timeframes as 2-bar swings span more price action.
