# Handoff note — fvgc/context/ reuse (NQ-VP-Lab + Track C)

## For NQ-VP-Lab (session-state tagger reuse)

`fvgc/context/` was built additive-only and is designed for reuse:

- **`fvgc/context/htf.py`** — 30s→HTF resampling with `known_ts` (right-edge) bar
  finality; vectorized HTF FVG inventory with 30s-precise first-touch and inversion
  timestamps (10-trading-day forward-scan cap); confirmed-swing detection with
  `confirm_ts` (a swing is usable only n bars after the pivot). All point-in-time.
- **`fvgc/context/draws.py`** — named-level table loader (joins `session_levels.csv`,
  honors `available_time`, derives `prev_close`); lagged daily ATR14; per-session RTH
  slices; intra-RTH first-sweep times with post-sweep reversal grades.
- **`fvgc/context/snapshot.py`** — per-trade snapshot assembler (draw map, need
  proxies, session state, HTF alignment). `build_context()` caches the heavy HTF
  inventory (~94s cold, ~2s warm at `results/cache/htf_context.pkl`).

Gotchas discovered while building (read before reuse):
1. `session_levels.csv` or_high/or_low rows have **NaN prices** — compute OR live
   from 9:30–9:44:30 bars, expose only from 9:45.
2. The 30s consolidation **drops Sunday-evening bars on post-DST-fallback weeks**
   (every November 2018–2024) — Asia-session levels are wrong on those Mondays.
   Session-quality rule (>=90% overnight-bar coverage) catches them.
3. "Unmitigated FVG" needs a per-use definition: untouched (draw/magnet semantics)
   vs not-inverted (zone semantics). Nesting requires the latter.
4. Use python3.13 (pyarrow); repo-default python3 is 3.9 without parquet support.

## For Track C (portfolio simulation) — instruction from Phil, 2026-06-09

Track A promoted **no** confluence framework. Track C should run the **benchmark-only
reduced version**: the opening-window short no-PS play (FVG created 09:29:30–09:31:00
ET, short, variant≠protected_swing, ~10 signals/yr), **with a three-way sensitivity on
assumed WR: 56% / 70% / 83%** (IS estimate / pooled 8-yr / recent-window implied),
since the true forward number is uncertain across regimes. 1:1 RR per the frozen
engine; survival/sizing conclusions must be reported per scenario, not blended.
