# Study: Indicator baseline (1m)

## Question

How does the FVGC entry model behave on 1m bars over the full available consolidated NQ history?

## Methodology

- **Data:** `data/consolidated/nq-front-month.ohlcv-1m.csv` — front-month continuous series, 1m OHLCV (resampled from 30s consolidated via `tools/gen_1m_candles.py`).
- **Model:** `fvgc/model.py` — signal generation only (no external context).
- **Execution:** `fvgc/engine.py` `simulate_trades` — first touch of SL or TP on subsequent **1m** bars. SL/TP levels use the same constants as the 30s baseline (15–60 pt range, 1:1 RR).
- **Purpose:** Compare against 30s canonical baseline to understand timeframe sensitivity.

## How to run

```bash
python studies/baseline_1m/run.py
```

Outputs under `logs/` (gitignored): `baseline_1m_trades.csv`, `baseline_1m_fvgs.csv`.

## Results

Model version: v2.0.5  
Data range: 2023-10-01 → 2026-03-25  
Bars: 796,650 | FVGs: 34,736 | Signals: 938

| Metric | Value |
|---|---|
| Trades executed | 768 |
| Skipped (no SL/TP) | 170 |
| Win rate | **50%** |
| Total P&L | **-80 pts** |

| Variant | W | L | WR | P&L |
|---|---|---|---|---|
| bos | 96 | 123 | 44% | -785 |
| ifvg | 39 | 40 | 49% | +65 |
| no_fvg | 170 | 148 | **53%** | +430 |
| protected_swing | 75 | 75 | 50% | +210 |

## Conclusions

- 1m is the weakest timeframe tested — the only one with negative aggregate P&L.
- `bos` at 44% WR is the primary drag, pulling the entire baseline below breakeven.
- `no_fvg` holds at 53% and is the only consistently strong variant at this timeframe.
- The drop in trade count (768 vs 2,383 at 15s) reduces statistical confidence for per-variant conclusions.
- **Not recommended as a primary analysis timeframe.** Use 30s or 15s for more reliable signal counts.
