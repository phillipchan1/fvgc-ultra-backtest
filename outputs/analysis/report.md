# Sweep Analysis Report

- Source file: `sweep_results.csv`
- Min trades: `5`
- Rows (finite PF & >= min trades): **6,964**

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
- avg_trade (numeric – spearman_corr): **0.9772**
- net_per_trade (numeric – spearman_corr): **0.9772**
- net (numeric – spearman_corr): **0.8430**
- ending_balance (numeric – spearman_corr): **0.8430**
- win_rate (numeric – spearman_corr): **0.8287**
- points_sl (numeric – spearman_corr): **0.4985**
- entry_touch_type (categorical – median_range): **0.3991**
- gross_profit (numeric – spearman_corr): **0.3306**
- allowed_time_buckets (categorical – median_range): **0.2193**
- run_id (numeric – spearman_corr): **0.1703**
- max_gap_taps (numeric – spearman_corr): **0.1656**
- min_gap_taps (numeric – spearman_corr): **0.1656**

## Model (RF) Permutation Importance — Top Encoded Features
- win_rate: **4.570424** (± 1.068961)
- allowed_time_buckets_1000-1015: **3.735685** (± 2.657592)
- entry_touch_type_close_inside_only: **1.181025** (± 1.295336)
- entry_touch_type_tap_only: **0.426059** (± 0.100228)
- points_sl: **0.296848** (± 0.009073)
- trades: **0.293966** (± 0.088305)
- penetrated_midline_: **0.232693** (± 0.060094)
- penetrated_midline_True: **0.105359** (± 0.042122)
- points_tp: **0.097125** (± 0.007066)
- max_bars_to_prev_break: **0.077721** (± 0.000326)
- gap_size_max_pts: **0.015455** (± 0.003831)
- max_gap_taps: **0.007358** (± 0.001530)
- min_gap_taps: **0.007352** (± 0.001657)
- allowed_time_buckets_: **0.001578** (± 0.000490)
- allowed_time_buckets_0945-1000: **0.000874** (± 0.000303)
