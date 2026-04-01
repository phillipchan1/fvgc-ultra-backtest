# Study: Red folder news vs win rate (baseline)

## Question

How does **win rate** on **red-folder event days** compare to **non–red-folder days**, and how do **premarket-scheduled** red days (`has_pre_rth_news`) compare to red days **without** an 8:30-style print?

This study also adds **weekday and week-of-month** labels per event row, **trade stats by `event_type` × weekday**, and **typical session structure** (gap, opening ranges, 9:30 candle, RTH range) averaged over **distinct session dates** in each bucket.

## Data sources

- **Event calendar (red folder):** [data/raw/market_high_volume_events_2020_2025.csv](../../data/raw/market_high_volume_events_2020_2025.csv) — one row per scheduled high-impact event; merged into `trading_days` in [data/trading_days/build_trading_days.py](../../data/trading_days/build_trading_days.py).
- **Per-day flags:** [data/trading_days/trading_days.csv](../../data/trading_days/trading_days.csv)
  - **`has_red_folder_news`:** that calendar date appears in the events file.
  - **`has_pre_rth_news`:** at least one event whose known ET time is **before 10:00** (e.g. NFP/CPI at 8:30 per `EVENT_TIMES` in `build_trading_days.py`). This is the **premarket / pre-open release** flag used elsewhere as “Pre-RTH news.”
  - **`has_during_session_news`:** would be True if any event fell in **[9:30, 11:00] ET**; with the current `EVENT_TIMES` map, this flag is **never True** in the built CSV, so it is **not** used in this study.

- **Trades:** [logs/baseline_trades.csv](../../logs/baseline_trades.csv), tradeable only (`win` / `loss`), joined via [analysis/permutation_test.py](../../analysis/permutation_test.py) `load_data()`.

### JOLTS and other releases

**JOLTS** is **not** in the events CSV. To analyze it like other rows: add dated rows to `market_high_volume_events_2020_2025.csv`, rebuild `trading_days` with `python data/trading_days/build_trading_days.py`, and add **`JOLTS`** to **`EVENT_TIMES`** in `build_trading_days.py` if pre-RTH vs RTH classification matters (JOLTS Job Openings is often **10:00 ET**, i.e. after the open — it would **not** set `has_pre_rth_news` under the current **&lt; 10:00** rule).

## Interpretability (entry vs news time)

- Model entries in this log are **≤ 10:15 ET**. On **NFP/CPI (8:30)** days, every trade is **after** the premarket print — there is no “before the number” cohort for these entries.
- **FOMC (14:00)** and similar afternoon releases: all baseline entries are **before** that time; there are no post-2pm trades in this log, so WR cannot be split “before vs after FOMC” here.

## Definitions: weekday and week-of-month

- **`day_of_week` / `day_of_week_name`:** From the **calendar date** of each event row (pandas: Monday = 0 in `day_of_week`).
- **`week_of_month`:** `min((day_of_month - 1) // 7 + 1, 5)` — e.g. days 1–7 → week 1, 8–14 → week 2. This is **not** ISO week number.
- **Weekend dates in the events file:** Some release rows fall on **Saturday or Sunday** (e.g. certain CPI dates). There is usually **no US RTH session** that day; [red_folder_calendar_with_dow.csv](results/red_folder_calendar_with_dow.csv) still lists them. Trade and `trading_days` stats for those `(event_type, weekday)` buckets will show **n = 0** and **`n_session_dates` = 0** (means are empty).

## Methodology

### Primary segments

Trade must have a `trading_days` row for red-folder splits (see join gap below).

| Segment | Definition |
|---------|------------|
| `all_tradeable` | All win/loss trades |
| `no_red_folder` | `has_red_folder_news == False` |
| `red_folder_all` | `has_red_folder_news == True` |
| `red_folder_pre_rth_news` | red folder **and** `has_pre_rth_news == True` |
| `red_folder_no_pre_rth_news` | red folder **and** `has_pre_rth_news == False` |

**Join gap:** Some tradeable rows have **no** `trading_days` row (session date outside the file’s range). They are counted in `all_tradeable` but **not** in `no_red_folder` / red-folder segments.

**Event-type overlap:** For each `event_type`, stats include every trade whose **session date** has **at least one** row of that type. If a **single date** has two event types (e.g. CPI + OPEX), trades on that date count toward **both** types’ rows — sums of `n` across types are **not** a partition of all trades.

### `event_type` × weekday (trades)

For each pair `(event_type, day_of_week_name)` present in the events calendar:

- Session dates are those event rows with that type **and** that weekday.
- Trades included: `date` is in that set **and** the trade’s session **`day_of_week_name`** matches (guards against misaligned rows).

Columns include **`long_n`** / **`short_n`**, **`avg_pnl`**, and standard win/loss counts.

### Day-structure profile (session-level, not trade-level)

For the **same** `(event_type, day_of_week_name)` buckets, we take **distinct dates** in [data/trading_days/trading_days.csv](../../data/trading_days/trading_days.csv) and compute the **mean** of:

- `gap_from_prior_close_pct`
- `or_5min_range`, `or_45min_range`
- `candle_930_range`
- `rth_range`

So each date in a bucket counts **once**, even if there are many trades that day. This is a **profile of the session**, not an average weighted by number of trades.

## Results (refresh)

```bash
python studies/red_folder_news_compare/run.py
```

### All directions (primary segments)

| segment | n | wins | losses | win_rate_pct | total_pnl |
|---------|---|------|--------|--------------|-----------|
| all_tradeable | 1572 | 813 | 759 | 51.72 | 1865.0 |
| no_red_folder | 1245 | 655 | 590 | 52.61 | 2190.0 |
| red_folder_all | 268 | 129 | 139 | 48.13 | -190.0 |
| red_folder_pre_rth_news | 144 | 69 | 75 | 47.92 | 25.0 |
| red_folder_no_pre_rth_news | 124 | 60 | 64 | 48.39 | -215.0 |

### By direction

See [results/summary_by_red_folder_by_direction.csv](results/summary_by_red_folder_by_direction.csv).

### By event_type (overlapping days)

See [results/summary_by_event_type.csv](results/summary_by_event_type.csv).

### Calendar and weekday profiles

| File | Contents |
|------|----------|
| [results/red_folder_calendar_with_dow.csv](results/red_folder_calendar_with_dow.csv) | Each event row: `date`, `event_type`, `event`, `day_of_week`, `day_of_week_name`, `week_of_month` |
| [results/summary_event_type_by_dow.csv](results/summary_event_type_by_dow.csv) | Trade WR / n / PnL / long / short by `event_type` × `day_of_week_name` |
| [results/profile_day_structure_by_event_dow.csv](results/profile_day_structure_by_event_dow.csv) | Mean gap / ranges over **distinct** session dates per bucket |

## Outputs (all CSVs)

| File | Contents |
|------|----------|
| [results/summary_by_red_folder.csv](results/summary_by_red_folder.csv) | Primary segments |
| [results/summary_by_red_folder_by_direction.csv](results/summary_by_red_folder_by_direction.csv) | Same segments × long/short |
| [results/summary_by_event_type.csv](results/summary_by_event_type.csv) | WR by event type (non-exclusive) |
| [results/red_folder_calendar_with_dow.csv](results/red_folder_calendar_with_dow.csv) | Event calendar + DOW + week-of-month |
| [results/summary_event_type_by_dow.csv](results/summary_event_type_by_dow.csv) | WR by event type × weekday |
| [results/profile_day_structure_by_event_dow.csv](results/profile_day_structure_by_event_dow.csv) | Mean day fields by event type × weekday |

## Conclusions (qualitative)

- In this sample, **no red folder** is slightly **higher WR** and **positive** total PnL vs **red folder all**; red sub-splits (pre-RTH vs no pre-RTH) are **similar WR** with modest n.
- Treat **event_type** and **event × weekday** rows as descriptive; overlap and small n limit strong claims.
- Use **profile_day_structure** to compare typical gaps/ranges **across** buckets; it does not replace trade-level PnL.
