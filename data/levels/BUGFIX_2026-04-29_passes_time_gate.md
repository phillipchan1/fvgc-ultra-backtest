# Bug fix: passes_time_gate not enforced in HTF FVG loop

**Date:** 2026-04-29
**File:** `data/levels/enrich_trades_with_levels.py`
**Severity:** High — caused look-ahead bias in `htf_fvg_*_swept` columns
**Reporter:** Phil flagged the 2026-01-29 09:38 W1 short trade asking "where is the bullish 15m FVG that was tapped?" when nothing was visible on chart.

## What was wrong

`enrich_row` had two near-identical loops to populate `level_events`:

1. **Session-levels loop** (line 269) — iterates LEVEL_REGISTRY for session levels (overnight, 6am, prev_day, etc.). Correctly checks `passes_time_gate` before including a level.
2. **HTF loop** (line 285) — iterates `liqu_day` for HTF FVG levels (15m / 1H / 4H / Daily). **Missing `passes_time_gate` check.**

Because HTF FVGs include intraday-tagged ones (e.g. a 15m FVG created from the 9:30-9:45 candle becomes available at 10:00), the missing gate caused these FVGs to leak into candidate sets for trades entering BEFORE their `available_time`.

## Concrete example

Trade: 2026-01-29 09:38:30 W1 short, entry 26026.50.

The `htf_fvg_15m` group's `_swept` field was computed from `nearest_magnet_price(direction='short', entry=26026.50, candidate_prices)`. Without the time gate, candidates included:

- `htf_fvg_15m_bearish_81660_intraday` at price 26008.25 (top=26122.50, bottom=26008.25, available_time='10:00')

This intraday FVG has price 26008.25 just below the 26026.50 entry, making it the "nearest below". And `is_level_swept('resistance', 26008.25, sub_9:30_to_9:38:30)` returned `True` trivially because `max(high)` in that window was 26175 — i.e., price was *above* 26008.25 the entire time, which is meaningless as a "sweep" event.

So the cached label said `htf_fvg_15m_swept='in_session'` even though:
- (a) the FVG didn't exist as a defined structure at 9:38:30
- (b) the legitimate nearest bullish 15m FVG below entry (at 25871.00) was untouched

## The fix

Add the same `passes_time_gate` check that the session-levels loop has:

```python
if liqu_day is not None and not liqu_day.empty:
    for _, r in liqu_day.iterrows():
        if _is_session_liquidity_row(r.get('timeframe')):
            continue
        # Bug fix 2026-04-29: HTF (FVG) loop must respect passes_time_gate
        # the same way the session-levels loop above does.
        if not passes_time_gate(str(r.get('available_time')), ts):
            continue
        # ... rest unchanged
```

## Impact assessment

Audited 1572 enriched trades:
- 221 had cached `htf_fvg_15m_swept='in_session'`
- **101 (46%) were look-ahead bias** — became `available` after fix
- 120 were legitimate sweeps
- 383 trades total had any kind of label change (some swung the other way through edge cases in availability_time parsing)

## Plays affected

- **W1 Short — Post-Sweep Continuation** (most affected): cohort drops from 55 trades / 94.5% WR to 4 trades / 50% WR. Status changed to `under_review`.
- **W1 Short — Confluence Model**: not affected (does not use `htf_fvg_15m_swept`).
- **15m FVG Breakout Continuation**: not affected by this bug specifically (rejected for separate reproduction failure).

Other plays that use `htf_fvg_*_swept` columns should be re-validated against the corrected data.

## Why this wasn't caught earlier

- The label looked statistically associated with strong outcomes (94.5% WR) so it appeared "validated"
- The Notion narrative ("price taps the FVG, bounces, you short the bounce") was plausible-sounding, so it wasn't critically examined
- Phil's audit ("show me the FVG on the 1/29 chart") is the kind of check that catches this — the data didn't match the chart-based mental model

## Recommendation

Run a similar reconciliation pass on every "verified" play that depends on engine-computed structural labels: pull a few trades, ask "would I have seen this on the chart at entry time?", and verify the engine's classification matches.
