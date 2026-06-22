# DOL Continuation — Progress Note

Paused: 2026-05-25. Switching back to IFVG reversal work.

## Current state

**Best version: v5** (`run_v5.py`, results in `results/dol_trades_v5.csv`)

| | v1 | v2 | v3 | v4 | **v5** |
|---|---|---|---|---|---|
| Signals (1yr) | 463 | 64 | 688 | 1,294 | **298** |
| WR | 21% | 28% | 23% | 26.5% | **33.6%** |
| PF | 0.63 | 0.81 | 0.49 | 0.68 | **0.90** |
| Total R | — | — | −343 | −285 | **−2.9** |

Near break-even. Edge clearly concentrated in a sub-cell — needs one more cut to test if it's real.

## What v5 does (causal, lookahead-clean)

1. Detects 3-candle FVG inversions across 30s/1m/2m/3m/5m
2. **Per-TF min gap size** (30s:6 / 1m:10 / 2m:15 / 3m:18 / 5m:22 pts) — gaps must be visible on chart
3. Killzone 9:30–11:00 NY, using bar **close** time
4. **HTF 15m bias gate**: trade direction must match last 15m structure (last closed 15m close vs close 2 bars prior, |delta| > 8 pts; neutral days blocked)
5. Body fraction ≥ 0.55 on the inverting candle
6. Targets nearest DOL: OR (post 9:45), overnight H/L, asia H/L, london H/L, PDH/PDL, session_so_far, running_50pct
7. R-distance bounds 1.0R – 5.0R
8. Strict path-clear: opposing FVG only counts if it lies entirely between entry and target AND hasn't been wicked into

## What v5 confirmed about 5/13 + 5/21

- **5/13 9:44 short captured** ✅ (30s wins +1.64R, 1m loses; was the textbook trade you remembered)
- **5/21 noise eliminated** ✅ (was 6 trades in v4 incl. two losing longs at or_high during chop; now 0)

## The clear sub-cell — by DOL target

Winners (PF > 1, mostly counter-bias toward unswept magnets):
- overnight_high: N=27, WR 59.3%, **PF 4.19**, +22.9R
- asia_low: N=27, WR 44.4%, PF 1.60, +9.6R
- london_high: N=31, PF 1.47, +8.8R
- london_low: N=37, PF 0.80, +3.4R
- or_low (shorts only): N=31, PF 1.03

Killers (drag PF below 1):
- or_high: N=37, **PF 0.30**, −17.5R
- overnight_low: N=27, PF 0.43, −11.4R
- prev_day_low: N=17, PF 0.17, −6.8R
- running_50pct: N=16, PF 0.34
- session_high/low_so_far: marginal

**By TF: 30s carries everything.** 30s PF 1.06 (+16R, N=200). 1m/2m/3m/5m all negative.

## Hypothesis to test on resume (v6)

The "magnet vs anti-magnet" asymmetry suggests:
- Counter-trend DOLs **toward unswept liquidity** (15m bullish + target overnight_high = magnetic) → real edge
- Counter-trend DOLs **toward already-swept liquidity** → no edge / chop

Concrete v6 cuts to try, in order of expected lift:
1. **30s gap TF only** — drops 100 trades, keeps positive ones
2. **Drop or_high/or_low/running_50pct/session_so_far targets** — these are floating/swept levels, not magnets
3. **"Target must be unswept today" rule** — for overnight/asia/london/PD, check if today's session has already wicked through. If swept, kill the trade.

Conservative prediction after #1+#2+#3: ~120 trades/yr, WR 45%+, PF ≥ 1.5.

## Files

- `run_v5.py` — current best
- `run_v4.py` — strict path + open killzone (kept for diff)
- `run_v3.py` — wicked-into mitigation (early)
- `run_v2.py`, `run.py` — abandoned
- `results/dol_trades_v5.csv` — 298 trades, full features
- `results/dol_trades_v4_readable.csv` — v4 list with TZ-stripped timestamps for browsing
