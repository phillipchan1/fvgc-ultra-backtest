# Tempo Recaps — Demonstration Log

This folder logs every trade Tempo describes in his daily recaps so we can:

1. **Verify coverage** — for each demonstrated trade, did our model emit a signal at that timestamp? If not, why?
2. **Validate factor importance** — which of our factors were "lit" on his actual A+ winners vs his B-grade losers?
3. **Discover missing rules** — running tally of rules he uses that we don't model yet

## Files

- `demonstrations.csv` — one row per trade. Columns documented below.
- `observed_rules.md` — running list of candidate rules with recurrence counts.
- `recaps/recap_NN_YYYY-MM-DD.md` — raw transcript text per day, for re-reference.

## demonstrations.csv schema

| Column | Type | Notes |
|--------|------|-------|
| recap_id | str | "R01", "R02", … cross-references the recap transcript file |
| recap_date | YYYY-MM-DD | Date the recap describes (= the trading day) |
| trade_seq | int | Trade number within that day (1, 2, 3, …) |
| entry_time_ny | HH:MM | Approximate entry time NY (often vague in recap, use best guess) |
| instrument | str | NQ, ES, MNQ, GC, etc. |
| direction | str | long / short |
| setup_type | str | reversal / continuation / dol / data_wick / re_entry |
| triggering_sweep | str | overnight_low, prev_day_high, london_high, data_wick_low, 50pct_tap, etc. |
| confluences | str | pipe-separated: "smt\|htf_fvg\|equal_lows\|order_block" |
| gap_tf | str | 30s, 1m, 2m, 3m, 15s (data wick) |
| approx_stop_pts | float | If mentioned |
| approx_target_pts | float | If mentioned |
| outcome | str | win / loss / be / skipped |
| approx_r | float | If derivable (-1.0, +1.0, +4.0, etc.) |
| approx_pnl_usd | float | If mentioned |
| chase_entry | bool | Did he enter before candle close |
| half_size | bool | Did he reduce position |
| narrative | str | Short prose summary |
| matched_to_population | bool | Filled later during coverage check |
| matched_population_row_id | int | If matched |
| match_miss_reason | str | If no match: "outside killzone", "5m FVG", "ES instrument", etc. |
| notes | str | Any extra context |

## Workflow

1. User sends raw recap text → save as `recaps/recap_NN_YYYY-MM-DD.md`
2. Extract trades → append rows to `demonstrations.csv`
3. Update `observed_rules.md` recurrence table
4. Once N >= 20 demonstrations: run coverage check against population_scored.csv

## Recap inventory

| ID | Date | Net result | # trades |
|----|------|------------|----------|
| R01 | TBD | break-even | 5 incl. skipped + PM winners |
| R02 | TBD | +$10k+ | 1 main + 1 eval |
| R03 | TBD | mixed | 4 (1 skipped open, GC win, NQ loss, NQ win) |
| R04 | TBD | +$1k/acct | 3 (2 losses + huge ES PM news win) |
| R05 | TBD | +$250 | 2 (loss then DOL win) |
| R06 | TBD | 4W/0L | 4 (CPI data wick + 3 others) |
