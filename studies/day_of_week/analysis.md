# Study: Performance by day of week

## Question

Does the FVGC **baseline** perform differently on certain days of the week?

## Methodology

- **Source:** [logs/baseline_trades.csv](../../logs/baseline_trades.csv) only — **no full backtest**, no candle replay, no `fvgc.model` run.
- **Cohort:** Tradeable rows only (`outcome` is `win` or `loss`).
- **Weekday:** `day_of_week_name` from the **entry `timestamp`** (calendar day of the session). This is a straight splice of the historical baseline log.

## Results (refresh)

```bash
python studies/day_of_week/run.py
```

### All directions (Mon–Fri)

| day | n | wins | losses | win_rate_pct | total_pnl | avg_pnl |
|-----|---|------|--------|--------------|-----------|---------|
| Monday | 291 | 147 | 144 | 50.52 | 435.0 | 1.49 |
| Tuesday | 311 | 153 | 158 | 49.20 | 115.0 | 0.37 |
| Wednesday | 322 | 164 | 158 | 50.93 | 150.0 | 0.47 |
| Thursday | 330 | 184 | 146 | **55.76** | **920.0** | 2.79 |
| Friday | 318 | 165 | 153 | 51.89 | 245.0 | 0.77 |

### By direction

See [results/summary_by_day_of_week_by_direction.csv](results/summary_by_day_of_week_by_direction.csv).

## Outputs

| File | Contents |
|------|----------|
| [results/summary_by_day_of_week.csv](results/summary_by_day_of_week.csv) | One row per weekday |
| [results/summary_by_day_of_week_by_direction.csv](results/summary_by_day_of_week_by_direction.csv) | Long/short × weekday |
| [results/trades_monday.csv](results/trades_monday.csv) … `trades_friday.csv` | Trade rows per weekday |

## Conclusions (qualitative)

- **Thursday** is strongest in this sample on both WR and total PnL; **Tuesday** is weakest on WR.
- **Short Thursday** drives much of the edge; long Wednesday is slightly negative on total PnL here.
- Descriptive only; no formal significance test.
