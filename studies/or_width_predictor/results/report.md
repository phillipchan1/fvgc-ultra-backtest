# OR-Width Predictor — Results

## Walk-forward performance (out-of-sample, 2023–2026)

| model | n_features | n | mae_pts | mape_pct | r2 | spearman_rho | interval_coverage_80 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cold_start | 17 | 712 | 43.776 | 32.487 | 0.112 | 0.599 | 0.742 |
| plus_5min | 21 | 712 | 40.265 | 29.285 | 0.202 | 0.682 | 0.733 |
| plus_15min | 23 | 712 | 35.342 | 24.883 | 0.298 | 0.756 | 0.732 |

Reading the table:
- **MAE_pts**: average absolute error in NQ pts. Lower = tighter forecast.
- **R²**: variance explained. 0.40 ≈ "useful," 0.60+ ≈ "strong."
- **Spearman rho**: rank-correlation of forecast vs actual. ≥0.6 = the ranking is reliable.
- **Cover80**: fraction of actual ORs inside the 80% prediction band.
  Should be ~0.80 if calibrated.

## Univariate feature ranking (top 20)

| feature | n | spearman_rho | spread_z | monotonicity | score |
| --- | --- | --- | --- | --- | --- |
| or_15min_range | 1393 | 0.795 | 1.928 | 1.000 | 1.362 |
| macro_2_range | 1393 | 0.737 | 1.874 | 1.000 | 1.306 |
| or_5min_range | 1393 | 0.693 | 1.687 | 1.000 | 1.190 |
| candle_930_range | 1393 | 0.583 | 1.489 | 1.000 | 1.036 |
| overnight_range | 1393 | 0.594 | 1.470 | 1.000 | 1.032 |
| atr_5d | 1388 | 0.565 | 1.442 | 1.000 | 1.004 |
| atr_10d | 1383 | 0.546 | 1.355 | 1.000 | 0.951 |
| atr_20d | 1373 | 0.531 | 1.299 | 1.000 | 0.915 |
| prior_day_range | 1392 | 0.484 | 1.231 | 1.000 | 0.858 |
| pm_range | 560 | 0.475 | 1.062 | 1.000 | 0.769 |
| vix_zscore_20d | 657 | 0.337 | 0.840 | 1.000 | 0.589 |
| vixy_prior_close | 1254 | 0.227 | 0.840 | 0.750 | 0.534 |
| gap_abs | 1392 | 0.294 | 0.767 | 1.000 | 0.530 |
| vix_5d_chg | 1216 | 0.184 | 0.766 | 0.750 | 0.475 |
| pm_volume | 560 | 0.213 | 0.634 | 0.750 | 0.424 |
| atr_ratio_5_20 | 1373 | 0.206 | 0.637 | 1.000 | 0.421 |
| pdr_pctile_20d | 1373 | 0.199 | 0.633 | 1.000 | 0.416 |
| gap_from_prior_close | 1392 | -0.083 | 0.715 | 0.500 | 0.399 |
| vix_1d_chg | 1219 | 0.095 | 0.668 | 0.500 | 0.382 |
| prior_day_close_position | 1392 | -0.170 | 0.427 | 1.000 | 0.298 |

## Permutation importance — cold-start model

_Larger MAE increase = feature matters more in the multivariate model._

| feature | mae_increase_pts | mae_increase_std | model |
| --- | --- | --- | --- |
| overnight_range | 8.183 | 0.559 | cold_start |
| atr_20d | 7.646 | 0.449 | cold_start |
| gap_abs | 2.565 | 0.237 | cold_start |
| atr_5d | 2.299 | 0.208 | cold_start |
| atr_ratio_5_20 | 1.611 | 0.274 | cold_start |
| prior_day_close_position | 0.367 | 0.121 | cold_start |
| gap_atr_ratio | 0.148 | 0.107 | cold_start |
| has_pre_rth_news | 0.115 | 0.057 | cold_start |
| prior_day_range | 0.111 | 0.132 | cold_start |
| is_opex_week | 0.106 | 0.080 | cold_start |
| is_fomc_week | 0.069 | 0.066 | cold_start |
| vix_5d_chg | 0.057 | 0.027 | cold_start |
| has_red_folder_news | 0.030 | 0.027 | cold_start |
| nr4_flag | 0.014 | 0.022 | cold_start |
| pdr_pctile_20d | 0.009 | 0.041 | cold_start |
| nr7_flag | -0.010 | 0.014 | cold_start |
| vixy_prior_close | -0.052 | 0.022 | cold_start |

## Permutation importance — plus_5min

| feature | mae_increase_pts | mae_increase_std | model |
| --- | --- | --- | --- |
| or_5min_range | 9.176 | 0.547 | plus_5min |
| atr_20d | 7.111 | 0.406 | plus_5min |
| gap_abs | 3.736 | 0.304 | plus_5min |
| atr_5d | 3.186 | 0.230 | plus_5min |
| overnight_range | 2.704 | 0.367 | plus_5min |
| atr_ratio_5_20 | 0.976 | 0.163 | plus_5min |
| gap_atr_ratio | 0.549 | 0.143 | plus_5min |
| has_pre_rth_news | 0.275 | 0.100 | plus_5min |
| fvgs_first_5min | 0.179 | 0.044 | plus_5min |
| prior_day_close_position | 0.058 | 0.061 | plus_5min |
| pdr_pctile_20d | 0.053 | 0.077 | plus_5min |
| has_red_folder_news | 0.050 | 0.050 | plus_5min |
| vixy_prior_close | 0.035 | 0.014 | plus_5min |
| candle_930_efficiency | 0.029 | 0.027 | plus_5min |
| nr4_flag | 0.026 | 0.034 | plus_5min |

## Permutation importance — plus_15min

| feature | mae_increase_pts | mae_increase_std | model |
| --- | --- | --- | --- |
| or_15min_range | 18.408 | 0.517 | plus_15min |
| atr_20d | 7.167 | 0.488 | plus_15min |
| atr_5d | 6.683 | 0.421 | plus_15min |
| gap_abs | 3.610 | 0.286 | plus_15min |
| atr_ratio_5_20 | 1.363 | 0.231 | plus_15min |
| gap_atr_ratio | 1.149 | 0.187 | plus_15min |
| vix_5d_chg | 0.105 | 0.032 | plus_15min |
| has_pre_rth_news | 0.104 | 0.079 | plus_15min |
| has_red_folder_news | 0.088 | 0.037 | plus_15min |
| fvgs_first_5min | 0.075 | 0.020 | plus_15min |
| is_fomc_week | 0.050 | 0.059 | plus_15min |
| fvgs_first_15min | 0.049 | 0.009 | plus_15min |
| nr4_flag | 0.047 | 0.022 | plus_15min |
| vixy_prior_close | 0.032 | 0.017 | plus_15min |
| overnight_range | 0.030 | 0.219 | plus_15min |