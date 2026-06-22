# Study: Data Wick Play — Baseline

## Question
On red-folder news release days (08:30 and 10:00 NY), does sweeping one side of
the 1-min "data wick" and entering on IFVG inversion produce edge when targeting
the opposite wick side?

Tempo claims this is one of his highest-WR setups and ~20% of his daily trades.

## Methodology
Per SPEC §15. Cohort capped by `market_high_volume_events_*.csv` coverage
(currently ends 2025-09-19) and `trading_days.csv` news flags. ~30 red-folder
days/year × 5 years = ~150 events; ~30-50% should generate a sweep + valid IFVG.

Run: `python studies/ifvg_reversal_data_wick/run.py`.

## Results
TBD.

## Conclusions
TBD.
