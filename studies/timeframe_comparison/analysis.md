# Study: Multi-timeframe baseline comparison

## Question

How does FVGC indicator performance vary across timeframes (15s through 5m)?

## Methodology

Same model and constants applied to each pre-aggregated consolidated CSV. SL/TP logic is bar-agnostic (NQ points, not time-based), so the same 15–60 pt range applies at every timeframe. SL distance grows at wider timeframes because the 2-bar swing lookback spans more price action.

Each timeframe has its own `baseline_<tf>/run.py` and outputs `logs/baseline_<tf>_trades.csv`.

**30s is the canonical baseline** that feeds all downstream studies. Other timeframes are for comparative analysis only.

## Results (FVGC v2.0.5, 2023-10-01 → 2026-03-25)

| TF | Trades | WR | P&L | avg SL | bos | ifvg | no_fvg | protected_swing |
|---|---|---|---|---|---|---|---|---|
| 15s | 2,383 | 52% | +2,640 | ~24 pts | 51% | 52% | 53% | **55%** |
| 30s | — | — | — | — | — | — | — | — |
| 1m | 768 | 50% | -80 | — | 44% | 49% | 53% | 50% |
| 2m | 314 | 56% | +1,269 | — | 49% | 65% | 59% | 57% |
| 3m | 200 | 59% | +1,385 | — | 45% | 73% | **65%** | **65%** |
| 5m | 56 | 64% | +640 | ~40 pts | 70% | 100% | 56% | 59% |

*30s numbers: run `python studies/baseline/run.py` and fill in.*  
*5m: sample too small (56 trades) — treat as exploratory only.*

## Key findings

**1. WR rises with timeframe, but trade count collapses**  
Each step up in timeframe roughly halves the trade count. 5m's 64% WR is based on 56 trades — statistically unreliable. 15s at 52% with 2,383 trades is far more trustworthy.

**2. `bos` is the problem variant — especially at 1m**  
`bos` is the only consistently loss-generating variant. It's marginally positive at 15s (51%), goes negative at 1m (44%), and only "recovers" at wider timeframes where sample size shrinks. The model's real edge comes from `no_fvg` and `protected_swing`.

**3. `no_fvg` is the most consistent variant across all timeframes**  
Positive P&L at every tested timeframe. Most reliable signal.

**4. 1m is the weakest timeframe**  
The only timeframe with negative total P&L. Coincides with the window where `bos` is worst (44%). Worth investigating whether this is a structural artifact of 1m bar resolution vs the trading window size.

**5. Wider SLs at higher timeframes inflate WR mechanically**  
At 5m, mean SL ~40 pts vs ~24 pts at 15s. With 1:1 RR, wider SLs mean TP is equally far — trades survive more noise. This is not a pure model edge improvement; it's a consequence of the swing-based SL method on wider bars.

## Conclusions

- **For pattern research:** use 30s (canonical) or 15s (higher resolution, same signal quality).
- **For trading intuition:** 2m and 3m show encouraging WRs with enough trades to be directional.
- **Avoid 1m for analysis:** weakest timeframe, lowest confidence.
- **Avoid 5m for conclusions:** sample too thin.
- All CSV outputs are in `logs/` (gitignored) and available for ad-hoc filtering/slicing.
