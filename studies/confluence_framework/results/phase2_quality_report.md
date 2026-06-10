# Phase 2 — snapshot data-quality report

rows: 4509  features: 97

## Missingness (top 25)

htf1h_nearest_above           0.3637
htf1h_nearest_below           0.3063
lvl_or_high_dist              0.2965
lvl_or_high_dist_atr          0.2965
lvl_or_low_dist_atr           0.2965
lvl_or_low_dist               0.2965
htf15m_nearest_above          0.2431
need_v3_z10_n10               0.2306
need_v3_z20_n10               0.2306
need_v3_z15_n10               0.2306
htf15m_nearest_below          0.1876
nearest_untaken_dir_dist_R    0.1690
nearest_untaken_dir_dist      0.1690
need_v3_z20_n4                0.0812
need_v3_z15_n4                0.0812
need_v3_z10_n4                0.0812
need_v2_last_fvg              0.0100
n_swept_so_far                0.0000
htf1h_n_above                 0.0000
htf1h_n_below                 0.0000
first_sweep_name              0.0000
need_v1_x40_y5                0.0000
need_v1_x30_y10               0.0000
need_v1_x30_y5                0.0000
need_v1_x20_y10               0.0000


## Categorical distributions

### or_state
or_state
forming       1337
broke_low     1176
broke_high    1147
inside         663
broke_both     186

### macro_window
macro_window
W3    1614
W2    1558
W1    1337

### first_sweep_name
first_sweep_name
prev_day_high       1094
prev_day_low         963
london_high          566
london_low           554
asia_high            381
asia_low             367
daily_50pct_low      170
daily_50pct_high     137
6am_low               75
nwog_high             70
6am_high              49
nwog_low              48
bsl_level             18
ssl_level             17

### struct_15m
struct_15m
mixed    1751
up       1484
down     1274

### struct_1h
struct_1h
mixed    1783
up       1394
down     1332

### pd_zone
pd_zone
premium     1273
discount    1178
above       1069
below        989

### gap_class
gap_class
flat        1766
gap_up      1451
gap_down    1292

## Key numeric sanity (describe)

### draw_asym_dir
count    4509.000
mean       -0.657
std         4.414
min        -8.000
25%        -5.000
50%        -1.000
75%         3.000
max         8.000

### n_untaken_above
count    4509.000
mean        3.574
std         2.465
min         0.000
25%         1.000
50%         4.000
75%         6.000
max         8.000

### n_untaken_below
count    4509.000
mean        3.702
std         2.448
min         0.000
25%         1.000
50%         4.000
75%         6.000
max         8.000

### nearest_untaken_dir_dist_R
count    3747.000
mean        2.648
std         2.484
min         0.010
25%         0.938
50%         1.892
75%         3.500
max        31.217

### htf15m_nearest_above
count    3413.000
mean      135.561
std       114.667
min         0.750
25%        58.250
50%       108.000
75%       176.500
max      1289.500

### pd_range_pos
count    4509.000
mean        0.492
std         0.799
min        -6.017
25%         0.069
50%         0.528
75%         0.974
max         3.782

### gap_atr
count    4509.000
mean        0.004
std         0.500
min        -2.811
25%        -0.251
50%         0.025
75%         0.286
max         2.063

### atr14_lag1
count    4509.000
mean      296.958
std       118.351
min        55.661
25%       219.179
50%       276.714
75%       357.679
max       956.089

## Boolean feature true-rates

target_aligned            0.612
nested_15m                0.055
opp_htf_inverted_today    0.516
need_v1_x20_y5            0.726
need_v1_x20_y10           0.592
need_v1_x30_y5            0.636
need_v1_x30_y10           0.535
need_v1_x40_y5            0.518
need_v1_x40_y10           0.462
need_v2_last_fvg          0.519
need_v3_z10_n4            0.455
need_v3_z10_n10           0.566
need_v3_z15_n4            0.348
need_v3_z15_n10           0.482
need_v3_z20_n4            0.257
need_v3_z20_n10           0.390
struct_15m_aligned        0.295
struct_1h_aligned         0.300
pd_zone_aligned           0.261
near_miss_c1              0.069
near_miss_fade            0.117
is_benchmark              0.018