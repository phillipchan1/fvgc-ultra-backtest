# v1 Validation Summary
Cohort: 2021-05-17 → 2026-05-15 (N=1438 trades)
IS: 1106, OOS: 332

## Overall comparison: fixed_1r vs scaled exit (no filter)
   IS fixed_1r    N=1106  WR= 50.0%  PF= 1.04  avg_R=+0.001  total_R=+1.3
   IS scaled      N=1106  WR= 33.5%  PF= 1.04  avg_R=+0.012  total_R=+13.2
  OOS fixed_1r    N=332   WR= 50.9%  PF= 1.09  avg_R=+0.018  total_R=+6.0
  OOS scaled      N=332   WR= 29.8%  PF= 0.97  avg_R=+0.003  total_R=+0.9


## Variant v1_original
Factors: ['prior_cascade', 'pd_just_past', 'strong_body', 'pdh_sweep', 'gap_10_12']

### IS fixed_1r

```
 threshold    n  wr_pct           pf  avg_r  total_r  total_pnl
         0 1106    50.0 1.040000e+00  0.001      1.3      390.0
         1  696    51.3 1.120000e+00  0.027     18.8      774.5
         2  236    58.5 1.510000e+00  0.171     40.3      978.5
         3   18    72.2 2.330000e+00  0.448      8.1      136.8
         4    1   100.0 2.600000e+10  1.000      1.0       26.0
```

### IS scaled

```
 threshold    n  wr_pct           pf  avg_r  total_r  total_pnl
         0 1106    33.5 1.040000e+00  0.012     13.2      476.1
         1  696    35.1 1.130000e+00  0.055     38.3      997.7
         2  236    40.7 1.510000e+00  0.244     57.5     1151.3
         3   18    50.0 2.470000e+00  0.653     11.8      193.4
         4    1   100.0 6.933333e+10  2.667      2.7       69.3
```

### OOS fixed_1r

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 332    50.9 1.09  0.018      6.0      351.5
         1 213    55.4 1.28  0.108     23.0      666.0
         2  76    57.9 1.38  0.158     12.0      302.5
         3   9    55.6 1.65  0.111      1.0       47.5
```

### OOS scaled

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 332    29.8 0.97  0.003      0.9     -125.2
         1 213    35.7 1.27  0.164     34.9      735.7
         2  76    34.2 1.41  0.231     17.6      389.7
         3   9    22.2 0.77 -0.185     -1.7      -21.6
```

### IS anti-pattern-filtered

#### fixed_1r

```
 threshold   n  wr_pct           pf  avg_r  total_r  total_pnl
         0 829    51.9 1.160000e+00  0.039     32.3     1148.2
         1 556    52.0 1.160000e+00  0.041     23.0      798.8
         2 207    58.9 1.530000e+00  0.180     37.3      881.5
         3  17    76.5 2.730000e+00  0.533      9.1      151.8
         4   1   100.0 2.600000e+10  1.000      1.0       26.0
```

#### scaled

```
 threshold   n  wr_pct           pf  avg_r  total_r  total_pnl
         0 829    35.3 1.230000e+00  0.082     67.9     1849.2
         1 556    36.5 1.270000e+00  0.113     62.6     1494.4
         2 207    42.0 1.630000e+00  0.294     60.8     1211.8
         3  17    52.9 2.790000e+00  0.750     12.8      208.4
         4   1   100.0 6.933333e+10  2.667      2.7       69.3
```

### OOS anti-pattern-filtered

#### fixed_1r

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 253    50.6 1.08  0.012      3.0      247.5
         1 173    53.8 1.19  0.075     13.0      381.5
         2  67    55.2 1.23  0.104      7.0      168.5
         3   8    50.0 1.14  0.000      0.0       10.0
```

#### scaled

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 253    31.2 1.04  0.058     14.6      146.6
         1 173    35.8 1.28  0.198     34.2      632.4
         2  67    34.3 1.40  0.223     14.9      344.1
         3   8    12.5 0.51 -0.292     -2.3      -46.6
```


## Variant v2_wider_gap
Factors: ['prior_cascade', 'pd_just_past', 'strong_body', 'pdh_sweep', 'gap_8_12']

### IS fixed_1r

```
 threshold    n  wr_pct           pf  avg_r  total_r  total_pnl
         0 1106    50.0 1.040000e+00  0.001      1.3      390.0
         1  790    51.8 1.120000e+00  0.037     28.9      896.8
         2  345    55.4 1.290000e+00  0.108     37.3      855.8
         3   62    62.9 1.670000e+00  0.261     16.2      287.5
         4    1   100.0 2.600000e+10  1.000      1.0       26.0
```

### IS scaled

```
 threshold    n  wr_pct           pf  avg_r  total_r  total_pnl
         0 1106    33.5 1.040000e+00  0.012     13.2      476.1
         1  790    35.1 1.130000e+00  0.061     48.5     1075.3
         2  345    40.3 1.390000e+00  0.211     72.9     1323.9
         3   62    43.5 1.970000e+00  0.439     27.2      483.3
         4    1   100.0 6.933333e+10  2.667      2.7       69.3
```

### OOS fixed_1r

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 332    50.9 1.09  0.018      6.0      351.5
         1 242    53.7 1.25  0.074     18.0      644.0
         2 102    57.8 1.42  0.157     16.0      407.5
         3  20    60.0 1.34  0.200      4.0       65.0
```

### OOS scaled

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 332    29.8 0.97  0.003      0.9     -125.2
         1 242    34.7 1.23  0.115     27.9      680.9
         2 102    36.3 1.48  0.241     24.6      556.8
         3  20    25.0 0.79 -0.088     -1.8      -48.7
```

### IS anti-pattern-filtered

#### fixed_1r

```
 threshold   n  wr_pct           pf  avg_r  total_r  total_pnl
         0 829    51.9 1.160000e+00  0.039     32.3     1148.2
         1 627    52.5 1.170000e+00  0.051     32.1      935.2
         2 304    56.2 1.330000e+00  0.126     38.3      842.0
         3  57    66.7 1.890000e+00  0.336     19.2      331.8
         4   1   100.0 2.600000e+10  1.000      1.0       26.0
```

#### scaled

```
 threshold   n  wr_pct           pf  avg_r  total_r  total_pnl
         0 829    35.3 1.230000e+00  0.082     67.9     1849.2
         1 627    36.2 1.250000e+00  0.113     70.7     1560.3
         2 304    41.8 1.510000e+00  0.265     80.4     1482.8
         3  57    45.6 2.200000e+00  0.536     30.5      531.5
         4   1   100.0 6.933333e+10  2.667      2.7       69.3
```

### OOS anti-pattern-filtered

#### fixed_1r

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 253    50.6 1.08  0.012      3.0      247.5
         1 196    52.6 1.16  0.051     10.0      357.0
         2  89    56.2 1.30  0.124     11.0      267.0
         3  19    57.9 1.15  0.158      3.0       27.5
```

#### scaled

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 253    31.2 1.04  0.058     14.6      146.6
         1 196    35.2 1.25  0.158     30.9      619.6
         2  89    38.2 1.54  0.276     24.6      553.1
         3  19    21.1 0.69 -0.127     -2.4      -73.7
```


## Variant v3_add_pen_le2
Factors: ['prior_cascade', 'pd_just_past', 'strong_body', 'pdh_sweep', 'gap_8_12', 'shallow_sweep']

### IS fixed_1r

```
 threshold    n  wr_pct   pf  avg_r  total_r  total_pnl
         0 1106    50.0 1.04  0.001      1.3      390.0
         1  820    51.6 1.11  0.033     26.9      874.0
         2  374    53.7 1.21  0.076     28.4      680.0
         3   83    65.1 2.05  0.303     25.2      532.8
         4    6    50.0 0.73  0.010      0.1      -25.0
```

### IS scaled

```
 threshold    n  wr_pct   pf  avg_r  total_r  total_pnl
         0 1106    33.5 1.04  0.012     13.2      476.1
         1  820    35.4 1.14  0.069     56.9     1235.3
         2  374    38.8 1.31  0.173     64.6     1133.5
         3   83    47.0 2.35  0.437     36.2      807.9
         4    6    33.3 1.04  0.344      2.1        4.3
```

### OOS fixed_1r

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 332    50.9 1.09  0.018      6.0      351.5
         1 250    54.4 1.27  0.088     22.0      716.8
         2 111    55.9 1.36  0.117     13.0      392.5
         3  26    61.5 1.53  0.231      6.0      112.2
         4   1     0.0 0.00 -1.000     -1.0      -10.5
```

### OOS scaled

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 332    29.8 0.97  0.003      0.9     -125.2
         1 250    34.0 1.22  0.108     26.9      674.4
         2 111    36.0 1.46  0.203     22.6      586.9
         3  26    26.9 0.94 -0.042     -1.1      -15.3
         4   1     0.0 0.00 -1.000     -1.0      -10.5
```

### IS anti-pattern-filtered

#### fixed_1r

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 829    51.9 1.16  0.039     32.3     1148.2
         1 649    52.2 1.16  0.046     30.1      897.8
         2 325    55.1 1.28  0.103     33.3      777.8
         3  74    67.6 2.19  0.354     26.2      525.2
         4   6    50.0 0.73  0.010      0.1      -25.0
```

#### scaled

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 829    35.3 1.23  0.082     67.9     1849.2
         1 649    36.4 1.26  0.118     76.4     1641.3
         2 325    40.6 1.46  0.239     77.8     1428.0
         3  74    48.6 2.53  0.507     37.5      802.5
         4   6    33.3 1.04  0.344      2.1        4.3
```

### OOS anti-pattern-filtered

#### fixed_1r

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 253    50.6 1.08  0.012      3.0      247.5
         1 199    53.3 1.19  0.065     13.0      421.5
         2  96    55.2 1.31  0.104     10.0      300.2
         3  25    60.0 1.35  0.200      5.0       74.8
         4   1     0.0 0.00 -1.000     -1.0      -10.5
```

#### scaled

```
 threshold   n  wr_pct   pf  avg_r  total_r  total_pnl
         0 253    31.2 1.04  0.058     14.6      146.6
         1 199    34.7 1.24  0.150     29.9      598.1
         2  96    38.5 1.58  0.256     24.6      631.4
         3  25    24.0 0.85 -0.070     -1.8      -40.3
         4   1     0.0 0.00 -1.000     -1.0      -10.5
```


## Best cells (OOS focus, score >= 2 and >= 3)

```
       variant cohort     mode  thresh   n   wr   pf  avg_r  total_r
   v1_original     IS fixed_1r       2 236 58.5 1.51  0.171     40.3
  v2_wider_gap     IS fixed_1r       2 345 55.4 1.29  0.108     37.3
v3_add_pen_le2     IS fixed_1r       2 374 53.7 1.21  0.076     28.4
   v1_original    OOS fixed_1r       2  76 57.9 1.38  0.158     12.0
  v2_wider_gap    OOS fixed_1r       2 102 57.8 1.42  0.157     16.0
v3_add_pen_le2    OOS fixed_1r       2 111 55.9 1.36  0.117     13.0
   v1_original     IS fixed_1r       3  18 72.2 2.33  0.448      8.1
  v2_wider_gap     IS fixed_1r       3  62 62.9 1.67  0.261     16.2
v3_add_pen_le2     IS fixed_1r       3  83 65.1 2.05  0.303     25.2
   v1_original    OOS fixed_1r       3   9 55.6 1.65  0.111      1.0
  v2_wider_gap    OOS fixed_1r       3  20 60.0 1.34  0.200      4.0
v3_add_pen_le2    OOS fixed_1r       3  26 61.5 1.53  0.231      6.0
   v1_original     IS   scaled       2 236 40.7 1.51  0.244     57.5
  v2_wider_gap     IS   scaled       2 345 40.3 1.39  0.211     72.9
v3_add_pen_le2     IS   scaled       2 374 38.8 1.31  0.173     64.6
   v1_original    OOS   scaled       2  76 34.2 1.41  0.231     17.6
  v2_wider_gap    OOS   scaled       2 102 36.3 1.48  0.241     24.6
v3_add_pen_le2    OOS   scaled       2 111 36.0 1.46  0.203     22.6
   v1_original     IS   scaled       3  18 50.0 2.47  0.653     11.8
  v2_wider_gap     IS   scaled       3  62 43.5 1.97  0.439     27.2
v3_add_pen_le2     IS   scaled       3  83 47.0 2.35  0.437     36.2
   v1_original    OOS   scaled       3   9 22.2 0.77 -0.185     -1.7
  v2_wider_gap    OOS   scaled       3  20 25.0 0.79 -0.088     -1.8
v3_add_pen_le2    OOS   scaled       3  26 26.9 0.94 -0.042     -1.1
```
