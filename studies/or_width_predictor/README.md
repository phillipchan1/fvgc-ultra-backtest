# OR-Width Predictor

Predicts the 45-min RTH opening range size with a confidence interval, before
the bell and at two live update points. The predicted OR drives sizing /
skip decisions: tight days (Q1) hurt this model's WR severely; wide days
(Q5) carry +18.6% WR and +0.94R E[R]@3R vs tight days (per the OR gradient
study).

## Three-stage forecast

| Stage | When | Adds | OOS MAE | OOS rho | OOS R² | 80% coverage |
|---|---|---|---|---|---|---|
| cold_start | 9:29 (pre-bell) | overnight, gap, ATR, VIX, calendar | 44 pts | 0.60 | 0.11 | 74% |
| plus_5min  | 9:35 | 1-min open candle + 5-min OR | 40 pts | 0.68 | 0.20 | 73% |
| plus_15min | 9:45 | 15-min OR | 35 pts | 0.76 | 0.30 | 73% |

OOS = walk-forward, 504-day rolling training window, tested 2023–2026 (n=712).

## Files

- `features.py` — feature engineering (rolling ATR, NR4/7, pre-market range,
  ON close position, VIX z-score, gap/ATR, candle efficiency)
- `analysis.py` — univariate quintile bucketing, Spearman, monotonicity
- `model.py` — ridge regression on `log(or_45min_range)`, bootstrap
  prediction intervals, permutation importance, walk-forward
- `run.py` — full pipeline. Builds feature table, ranks features, walks
  forward, fits and saves final models, writes report.
- `predict_today.py` — morning briefing CLI

## Usage

Train and validate (one-off, ~30s):
```
python studies/or_width_predictor/run.py
```

Daily briefing:
```
python studies/or_width_predictor/predict_today.py
python studies/or_width_predictor/predict_today.py --date 2026-04-25
python studies/or_width_predictor/predict_today.py --date 2026-04-25 --stage cold_start
```

Output: predicted OR, 80% interval, quintile vs last 60 days, top
drivers in pts.

## Known limitations

- `pm_range` (8:00–9:30) and full VIX series only cover 2023+ days; not
  used in deployed cold-start model. Backfilling pre-market candle data
  to pre-2023 is the highest-value unblock.
- Cold-start R² is positive but modest (0.11). The model **ranks days
  reliably** (Spearman 0.60) but absolute pts are noisy when vol regimes
  shift fast. Treat the cold-start point estimate as a center-of-mass
  guess; the 80% interval is the more honest output.
- Coverage of the 80% interval is ~74% (slightly under-calibrated).
  Acceptable for now; future fix = quantile regression.

## Future work (ranked by expected lift)

1. Backfill 8:00–9:30 candle data → enables pre-market range as a
   cold-start feature (univariate rho 0.48).
2. Add cross-asset ON moves: ES, BTC, DXY, 10Y. Currently absent.
3. Add VIX term structure (VX1/VX2). vix_zscore_20d is in there but the
   curve shape carries extra signal.
4. Quantile regression replacement for residual bootstrap → better
   calibration of the 80% band.
5. Mega-cap NQ component earnings flag (NVDA/MSFT/AAPL/META/GOOG/AMZN/TSLA).
