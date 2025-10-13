# Sweep Analysis Report

- Source file: `sweep_results.csv`
- Min trades: `5`
- Rows (finite PF & >= min trades): **1,456**

## Best Finite Profit Factor Setup
- Profit Factor: **96.3333**
- Trades: **12**
- Win Rate: **0.417**
- Net: **2860.00**

**Key Params:**
- points_tp: `20.0`
- points_sl: `20.0`
- require_pullback_from_outside: `False`
- require_directional_close: `True`
- require_prev_close_break: `False`
- ifvg_internal_criterion: `inside`
- ifvg_overlap_min_ratio: `nan`
- ifvg_allow_opposite_internal: `True`
- ifvg_same_bar: `False`
- ifvg_lookback_bars: `10.0`
- ifvg_break_metric: `wick`
- ifvg_allow_equal: `True`
- bos_require_close_through: `True`
- bos_allow_equal: `True`
- skip_conflicting_fvgs: `True`
- ifvg_ignore_internal_conflict: `True`
- entry_touch_type: `close_inside_only`
- allowed_time_buckets: `1000-1015`
- penetrated_midline: `True`
- min_gap_taps: `nan`
- max_gap_taps: `nan`
- min_bars_to_prev_break: `nan`
- max_bars_to_prev_break: `nan`
- gap_size_min_pts: `nan`
- gap_size_max_pts: `nan`

## Variables with Highest Apparent Influence
- win_rate (numeric – spearman_corr): **0.9249**
- avg_trade (numeric – spearman_corr): **0.9021**
- net_per_trade (numeric – spearman_corr): **0.9021**
- net (numeric – spearman_corr): **0.5605**
- ending_balance (numeric – spearman_corr): **0.5605**
- entry_touch_type (categorical – median_range): **0.5286**
- allowed_time_buckets (categorical – median_range): **0.5000**
- gross_profit (numeric – spearman_corr): **0.4847**
- points_tp (numeric – spearman_corr): **0.3028**
- points_sl (numeric – spearman_corr): **0.3028**
- trades (numeric – spearman_corr): **0.0858**
- penetrated_midline (categorical – median_range): **0.0655**

## Model (RF) Permutation Importance — Top Encoded Features
- allowed_time_buckets_1000-1015: **100.785649** (± 61.281191)
- entry_touch_type_close_inside_only: **34.541754** (± 51.602003)
- win_rate: **1.871737** (± 0.281195)
- trades: **0.467042** (± 0.559551)
- max_bars_to_prev_break: **0.099391** (± 0.029747)
- points_tp: **0.025117** (± 0.003628)
- points_sl: **0.023917** (± 0.003452)
- min_gap_taps: **0.018342** (± 0.018506)
- entry_touch_type_tap_only: **0.016897** (± 0.013804)
- gap_size_min_pts: **0.002656** (± 0.002655)
- allowed_time_buckets_: **0.001179** (± 0.000829)
- allowed_time_buckets_0945-1000: **0.000453** (± 0.000430)
- allowed_time_buckets_0930-0945: **0.000188** (± 0.000027)
- gap_size_max_pts: **0.000043** (± 0.000022)
- ifvg_break_metric_wick: **0.000000** (± 0.000000)
