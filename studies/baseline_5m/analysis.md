# Study: Indicator baseline (5m)

## Question

How does the FVGC entry model behave on 5m bars over the full available consolidated NQ history?

## Methodology

- **Data:** `data/consolidated/nq-front-month.ohlcv-5m.csv` — front-month continuous series, 5m OHLCV (resampled from 30s consolidated via inline script).
- **Model:** `fvgc/model.py` — signal generation only (no external context).
- **Execution:** `fvgc/engine.py` `simulate_trades` — first touch of SL or TP on subsequent **5m** bars. SL/TP levels use the same constants as the 30s baseline (15–60 pt range, 1:1 RR).
- **Purpose:** Compare against 30s canonical baseline to understand timeframe sensitivity.

## How to run

```bash
python studies/baseline_5m/run.py
```

Verifiable outputs: `results/trades.csv`, `results/fvgs.csv` (committed; re-run `run.py` to regenerate).

## Results

Model version: v2.0.5  
Data range: 2023-10-01 → 2026-03-25  
Bars: 159,345 | FVGs: 11,034 | Signals: 128

| Metric | Value |
|---|---|
| Trades executed | 56 |
| Skipped (no SL/TP) | 72 |
| Win rate | **64%** |
| Total P&L | **+640 pts** |

| Variant | W | L | WR | P&L |
|---|---|---|---|---|
| bos | 14 | 6 | 70% | +340 |
| ifvg | 2 | 0 | 100% | +90 |
| no_fvg | 9 | 7 | 56% | +120 |
| protected_swing | 10 | 7 | 59% | +90 |

## Caveats — sample size too small

**56 total trades is insufficient for statistical conclusions.** Individual variant counts (ifvg=2, bos=20) make per-variant WRs unreliable. Treat this as exploratory only.

## Why SLs are larger at 5m

The SL is set from the 2-bar swing (per `SWING_LOOKBACK = 2` in `constants.py`). On 5m bars, a 2-bar lookback spans 10 minutes of price action, which naturally places the swing further from the entry. Mean SL at 5m is ~40 pts vs ~24 pts at 15s. The 1:1 RR means TP is equally far — trades are given much more room, which inflates apparent WR.

## Conclusions

- Results are **not actionable** at this sample size.
- The high WR is partly a mechanical artifact of wider SLs on longer bars, not a pure edge improvement.
- **Do not use 5m as a study timeframe without a much longer data history.**
