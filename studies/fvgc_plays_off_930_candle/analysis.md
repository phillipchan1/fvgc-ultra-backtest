# Study: FVGC plays off the 9:30 candle

## Question

What is the win rate when the model’s **Fair Value Gap** is **created** during the RTH open (first ~90 seconds), versus the full baseline? How do **longs** and **shorts** compare? Optionally, how many trades also have FVG price bounds overlapping the **9:29:30 → 9:30:00** micro-gap from 30s OHLC?

## Outputs (verification)

Each run writes CSVs under **`results/`** in this folder:

- **`trades_opening_fvg_window_<window>.csv`** — tradeable trades whose `fvg_created_at` falls in the opening window (`default_92930_093100` or `tight_92930_093030`).
- **`trades_opening_fvg_and_micro_gap_<window>.csv`** — subset that also has FVG bounds overlapping the 9:29:30→9:30 micro-gap (only when run **without** `--no-candle-gap`).

Re-run `run.py` to refresh these files.

## Methodology

- **Data:** [logs/baseline_trades.csv](../../logs/baseline_trades.csv) (same universe as other permutation work).
- **Tradeable:** `outcome` in `win` / `loss` (excludes skip, ambiguous, eod for headline WR).
- **Opening window (primary):** `fvg_created_at` converted to **America/New_York**. A trade is in the **opening FVG cohort** when that time is between **09:29:30** and **09:31:00** inclusive (first two full 30s bars of RTH through the end of the first minute). Use `python run.py --window tight` for **09:29:30–09:30:30** only.
- **Micro-gap overlap (secondary):** From [data/consolidated/nq-front-month.ohlcv-30s.csv](../../data/consolidated/nq-front-month.ohlcv-30s.csv), for each session date take the bar starting **9:29:30** (use its **close**) and the bar starting **9:30:00** (use its **open**). The open-gap interval is `[min(close, open), max(close, open)]`. Overlap = **FVG** `[fvg_bottom, fvg_top]` intersects that interval (non-empty intersection).
- **No changes** to [fvgc/model.py](../../fvgc/model.py).

## Results

Run: `python studies/fvgc_plays_off_930_candle/run.py` (repo root).

| Cohort | n | Win rate | Notes |
|--------|---|----------|--------|
| All tradeable | 1572 | 51.7% | Baseline |
| FVG created in opening window | 100 | 61.0% | `fvg_created_at` in 9:29:30–9:31:00 |
| · long only | 46 | 45.7% | Under baseline |
| · short only | 54 | 74.1% | Strong |
| Opening window + overlaps 9:29:30→9:30 micro-gap | 8 | 75.0% | Very small n — illustrative only |

Re-run after refreshing `baseline_trades.csv` if the log changes.

## Conclusions

- Trades whose **FVG is formed in the opening window** show a higher aggregate WR than baseline in this sample, driven largely by **shorts**; **longs** in that window underperform the baseline.
- **Overlap** with the candle-derived micro-gap is a **strict** filter; counts are low — use for exploration, not standalone significance.
- For execution ideas, align discretionary “930 gap” plays with **short** setups when the model’s `fvg_created_at` sits in the open window; validate on new data and with your risk rules.
