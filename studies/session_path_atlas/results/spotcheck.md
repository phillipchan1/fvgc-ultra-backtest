# Session table spot-check

## Full-table cross-check vs trading_days.csv (independent pipeline)

| field | n compared | max |diff| | mismatches (>0.25 pt) |
|---|---|---|---|
| or5_high vs or_5min_high | 2148 | 0.00 | 0 |
| or5_low vs or_5min_low | 2148 | 0.00 | 0 |
| or15_high vs or_15min_high | 2148 | 0.00 | 0 |
| or15_low vs or_15min_low | 2148 | 0.00 | 0 |
| open_930 vs rth_open | 2148 | 0.00 | 0 |

## 10 random sessions — independent recompute

- **2019-06-14** arch=BALANCE_CHOP or15_first=none → OK
- **2020-09-18** arch=FAILED_BREAK or15_first=low → OK
- **2020-10-14** arch=SWEEP_AND_REVERSE or15_first=high → OK
- **2020-12-08** arch=FAILED_BREAK or15_first=low → OK
- **2022-05-30** arch=SWEEP_AND_REVERSE or15_first=high → OK
- **2022-07-29** arch=STRAIGHT_RUN or15_first=high → OK
- **2023-05-12** arch=STRAIGHT_RUN or15_first=low → OK
- **2023-12-19** arch=BALANCE_CHOP or15_first=none → OK
- **2024-04-18** arch=BALANCE_CHOP or15_first=none → OK
- **2025-04-21** arch=BREAK_RETEST_GO or15_first=low → OK

Total field mismatches across 10 sessions: **0**
