# `tools/causal_features.py` — Design Doc

**Purpose.** Centralize the join logic that every trade-level study needs, so the lookahead bug pattern (`trades.join(features, on='date')` where `features` contains full-session aggregates) cannot recur silently.

## Why this exists

Composite VP discovered that `daily_volume_profile.csv` joined on date gives 9:30-10:15 trades access to today's 9:30-16:00 POC/VAH/VAL. The Phase A `n_vp_targets ≥ 2` headline +19.93pp OOS lift collapsed to -1.10pp under lag-1 VP. The bug is mechanical: any per-date features table built from full-session data corrupts every backtest that joins on date.

Hand-rolled joins are the bug surface. A canonical helper eliminates the surface.

## Design choices

1. **Time gates are first-class.** Every feature has a `mod` (minute-of-day) at which it's known. The helper masks values to NaN for trades whose `mod` is below the gate. No more "we masked this one column with `mask_pre_945=True`" ad-hoc inside individual studies.

2. **Contaminated columns are refused, not masked.** `rth_close`, `rth_high`, `rth_low`, `rth_range`, `directional_changes_30m`, `max_drawdown_from_open`, `max_drawup_from_open` are full-session aggregates — there is no `mod` at which they become available (other than 16:00, which is past the trade horizon). The helper raises ValueError if a study asks for them. If a study genuinely needs these, it must reconstruct from causal bars itself — the friction is intentional.

3. **VP lagging is a separate function.** `load_lagged_vp()` builds yesterday's POC/VAH/VAL/va_width/rth_volume — the only causally-safe way to use the daily VP. Today's VP is never loaded. The columns are renamed `*_lag1` so existing code that references `df['poc']` won't silently keep working with the wrong values.

4. **Session levels respect `available_time`.** `session_levels.csv` already encodes when each level is observable ('open' or 'HH:MM'). `load_session_levels()` reads this column and masks accordingly. No callers have to know the rules.

5. **Polars-native.** The repo's studies are mixed pandas/polars; the helper uses polars and returns polars DataFrames. Studies that work in pandas can call `.to_pandas()` at the boundary.

## Schema

```
Input:  pl.DataFrame with at minimum 'timestamp' column (NY local datetime)
Output: input + 'date' + 'mod' + requested feature columns
```

Adding `date` and `mod` is idempotent — if they already exist, the helper leaves them alone.

## What it does NOT do

- Doesn't compute *bars*-from-OHLCV (that's `data/levels/`'s job).
- Doesn't enforce IS/OOS splits (the study's job).
- Doesn't pre-compute derived features like `n_vp_targets` (let studies do their own R-zone math, using lagged VP).
- Doesn't try to be smart about missing data; passes through Nones.

## When to extend it

If a new build pipeline lands a new column in `trading_days.csv`, add it to `SAFE_AT_OPEN` or `GATED_FEATURES` here. If a new full-session aggregate appears (e.g., realized vol over the whole day), add it to `CONTAMINATED`.

If a study needs a feature observable mid-session that doesn't fit any existing gate (e.g., volume-at-10:30), prefer recomputing from the 30s parquet over expanding `trading_days.csv` with another per-date scalar.

## Future work

- **Lazy / chunked support**: the current implementation reads the full `trading_days.csv` and `session_levels.csv`. If we ever load multi-million-row trade frames, switch to `pl.scan_csv` + lazy joins.
- **Live-feature parity**: `tools/morning_briefing.py` constructs many of the same features at 9:25 ET for live use. Refactor to source from this helper to guarantee live ↔ backtest parity.
- **Test the missing-data edges**: dates not present in `trading_days.csv` currently produce silent nulls. Could add a strict mode that raises.

## Testing

`tools/test_causal_features.py` covers:

- API hygiene (CONTAMINATED disjoint from loadable; refuses ContaminatedRequest; rejects unknown features; SAFE_AT_OPEN all mod=570; gates in RTH window)
- Time-gating (pre-/post-gate masking for or_15min, or_45min, candle_930)
- Lagged VP (returns d-1, not d)
- Session levels (or_high masked pre-9:45; prev_day_high available at open)
- Schema preservation (row count + input columns)

Run: `python -m pytest tools/test_causal_features.py -v` — 18 tests, ~0.2s.
