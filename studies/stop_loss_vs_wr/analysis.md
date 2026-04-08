# Study: Stop-loss distance vs win rate

## Question

Does **larger model stop distance** (`sl_dist`, in points) correlate with **lower win rate** on baseline FVGC trades? Hypothesis: wider stops are associated with worse WR (exploratory; not a causal claim).

## Methodology

- **Source:** [`logs/baseline_trades.csv`](../../logs/baseline_trades.csv) only — no full backtest, no candle replay, no `fvgc.model` run in this script.
- **Universe:** Tradeable rows only: `outcome` ∈ {`win`, `loss`} (same convention as [`analysis/permutation_test.py`](../../analysis/permutation_test.py)).
- **Key field:** `sl_dist` — logged by [`log_signals`](../../fvgc/engine.py); produced by the model as rounded stop distance. Rows with missing/non-numeric `sl_dist` are dropped (with a console warning if any).
- **Aggregation:** Group by `sl_dist`; compute `n`, wins, losses, win rate %, total and average PnL per bucket.
- **Discrete grid:** Per [`fvgc/constants.py`](../../fvgc/constants.py), stops use 5-point increments between 15 and 60 — expect natural buckets, not a continuous spectrum.

## Results

Outputs (regenerate with `python studies/stop_loss_vs_wr/run.py` from repo root):

| File | Description |
|------|-------------|
| [`results/summary_by_sl_dist.csv`](results/summary_by_sl_dist.csv) | One row per `sl_dist`: n, wins, losses, win_rate_pct, total_pnl, avg_pnl |
| [`results/trades_sl_dist_<points>.csv`](results/) | Full trade rows for that `sl_dist` (verification) |

Example summary from a local run of the baseline log (numbers **will change** when `baseline_trades.csv` is refreshed):

| sl_dist | n | wins | losses | win_rate_pct |
|--------:|--:|-----:|-------:|-------------:|
| 15 | 335 | 168 | 167 | 50.15 |
| 20 | 342 | 167 | 175 | 48.83 |
| 25 | 272 | 149 | 123 | 54.78 |
| 30 | 212 | 109 | 103 | 51.42 |
| 35 | 147 | 81 | 66 | 55.10 |
| 40 | 113 | 57 | 56 | 50.44 |
| 45 | 55 | 34 | 21 | 61.82 |
| 50 | 54 | 25 | 29 | 46.30 |
| 55 | 24 | 13 | 11 | 54.17 |
| 60 | 18 | 10 | 8 | 55.56 |

## Conclusions

- **Interpretation:** Win rate by `sl_dist` is **descriptive**. `sl_dist` is not assigned at random — market context and setup type drive both stop width and outcome. Do not treat bucket WR as proof that “wider stops cause losses.”
- **Sample size:** Counts shrink at high `sl_dist` (e.g. 55–60); treat those WRs as **noisy**.
- **Next steps (optional):** Stratify by `direction` or `variant`, or use permutation / trend tests only if you need stronger inference than bucket tables.
