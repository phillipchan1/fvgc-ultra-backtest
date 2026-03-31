# Study: Which 15-minute macro is best? (9:30–11:00)

## Question

Among baseline trades, which **15-minute window** has the best **win rate** from the open through **11:00**?

## Methodology

- **Source:** [logs/baseline_trades.csv](../../logs/baseline_trades.csv).
- **Tradeable:** `outcome` in `win` / `loss`.
- **Minutes after 9:30:** From [analysis/permutation_test.py](../../analysis/permutation_test.py) `enrich_trade_properties()` (`minutes_into_session`).
- **Buckets (`macro_15m`):** For minutes \(m\) in \([0, 90)\): `macro_15m = floor(m / 15) + 1` → six windows:
  - 1: 9:30–9:45  
  - 2: 9:45–10:00  
  - 3: 10:00–10:15  
  - 4: 10:15–10:30  
  - 5: 10:30–10:45  
  - 6: 10:45–11:00  
- **`m >= 90`:** Entry at or after **11:00** ET → `macro_15m = 7`, saved as [results/trades_after_11am.csv](results/trades_after_11am.csv) when non-empty.

The FVGC model’s **signal window** ends at **10:15** ([fvgc/constants.py](../../fvgc/constants.py)), so buckets **5–6** are typically **empty**; bucket **4** only contains entries that occur after 10:15 but still within your logged baseline (e.g. late fills in that 15m slice).

## Results (refresh with `python studies/macro_15m_compare/run.py`)

### All directions

| macro_15m | Window       | n   | WR    | Total PnL |
|-----------|--------------|-----|-------|-----------|
| 1         | 9:30–9:45    | 432 | 53.47% | +1155.0  |
| 2         | 9:45–10:00   | 549 | 53.01% | +840.0   |
| 3         | 10:00–10:15  | 576 | 49.83% | +95.0    |
| 4         | 10:15–10:30  | 15  | 26.67% | −225.0   |
| 5         | 10:30–10:45  | 0   | —     | —        |
| 6         | 10:45–11:00  | 0   | —     | —        |

**Highest WR among non-empty pre-11 buckets:** macro **1** (9:30–9:45). Bucket **4** is weak in this sample but **n is small**.

### By direction

See script output for long/short per bucket. In the current baseline, **shorts** carry the first window; **macro 4** is poor for both sides with low n.

## Outputs (verification)

- `results/trades_macro_1.csv` … `results/trades_macro_6.csv` — one file per 15m bucket (may be empty for 5–6).
- `results/summary_by_macro.csv` — aggregate table.
- `results/trades_after_11am.csv` — only if any tradeable entry at/after 11:00.

## Conclusions

- Extending the **table** to 11:00 is correct for future data; with the **current** model window, most mass stays in **macros 1–3**, with a thin **macro 4** tail and **no** trades in 5–6.
- Compare **WR** with **sample size**: prefer macros **1–2** on n and WR; treat **4** as noisy until n grows.
