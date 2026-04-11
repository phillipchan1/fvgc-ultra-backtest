# Sweep Continuation Study

## Purpose

Quantify, for NQ 30s front-month, two things:

1. **Base rate** — after a liquidity level is swept, how often does price
   continue (RUN) vs reverse (REVERSE) vs chop, broken down by level
   type, time of day, and runway to the next level.
2. **FVGC lift** — does taking an FVGC continuation entry within 40 bars
   (20 min) of a same-direction sweep produce a different win rate than
   the unconditional FVGC baseline, and if so under what conditions.

A third sub-study (`hold_vs_bank.py`) asks: among winning sweep-tagged
trades, how often does price reach the *next* same-direction level?
This informs whether you should bank profits at the level you just
took out or hold for the next pool.

## Definitions

**Level types constructed (v1):**

| Type             | Side | Construction |
|------------------|------|--------------|
| `PDH` / `PDL`    | high/low | Prior RTH (09:30–16:00 ET) session extremes. Active from the first bar of the next calendar day. |
| `ONH` / `ONL`    | high/low | Globex session extremes (18:00 ET prior day through 09:29:59 ET target day). Active from first 09:30 bar. |
| `ORH_5` / `ORL_5`   | high/low | RTH 09:30–09:34:59 extremes. Active from 09:35. |
| `ORH_15` / `ORL_15` | high/low | RTH 09:30–09:44:59 extremes. Active from 09:45. |
| `ORH_30` / `ORL_30` | high/low | RTH 09:30–09:59:59 extremes. Active from 10:00. |
| `PWH` / `PWL`    | high/low | Prior ISO week RTH extremes. Active from the first bar after the week closes. |
| `H1_SH` / `H1_SL` | high/low | 1h resample fractal (n=2). Active at the confirmation bar. |
| `H4_SH` / `H4_SL` | high/low | 4h resample fractal (n=2). Active at the confirmation bar. |

**Sweep event:** the first 30s bar at or after a level's `created_idx`
whose wick crosses the level (`bar.high > price` for high-side, `bar.low
< price` for low-side). Only the first touch counts; subsequent touches
of the same level are ignored.

**Sweep kind:**
- `run_through` — `close` crosses past the level by at least
  `RUN_THROUGH_EPS_ATR * ATR14 = 0.25 * ATR14`.
- `wick_only` — the close did not break through (classic reversal
  signature).

**Outcome labels at horizon H bars after the sweep (default H ∈ {10, 60,
120}):**
- `RUN` — `close[H] - level_price` >= `RUN_THRESHOLD_ATR * ATR14[sweep_idx]`
  (in the direction of the sweep).
- `REVERSE` — `close[H] - level_price` <= `-REV_THRESHOLD_ATR * ATR14[sweep_idx]`.
- `CHOP` — otherwise.

All thresholds are ATR-normalized so labels hold up across regimes.

**FVGC conditional tagging (Pass B):** a tradeable FVGC result is
"sweep-tagged" if there exists at least one same-direction sweep event
within `[entry_idx - 40, entry_idx]` (≤ 20 minutes before entry). If
more than one sweep exists in the window, the most recent one is
attached.

## Tunables (top of `run.py`)

```
ATR_LEN = 14
RUN_THRESHOLD_ATR = 1.0
REV_THRESHOLD_ATR = 1.0
RUN_THROUGH_EPS_ATR = 0.25
LOOKBACK_SWEEP_TO_ENTRY_BARS = 40   # 20 min on 30s
HORIZONS_BARS = [10, 60, 120]        # 5 / 30 / 60 min
```

## How to run

```bash
# Full history
python studies/sweep_continuation/run.py

# Hold vs bank sub-study
python studies/sweep_continuation/hold_vs_bank.py

# Custom data slice
python studies/sweep_continuation/run.py --data path/to/slice.csv
```

Writes CSVs under `studies/sweep_continuation/results/`:

- `levels.csv`
- `sweep_events.csv`
- `base_rates_by_type_h{10,60,120}.csv`
- `base_rates_by_type_tod_h{10,60,120}.csv`
- `base_rates_by_runway_h{10,60,120}.csv`
- `base_rates_by_kind_h{10,60,120}.csv`
- `fvgc_with_sweep_trades.csv`
- `fvgc_lift_overall.csv`
- `fvgc_lift_by_feature.csv`
- `fvgc_lift_by_type_tod.csv`
- `hold_vs_bank.csv`

## Correctness checks performed

- `sweep_idx >= level_created_idx` for every sweep (no sweep before the
  level was known).
- `ORH_5` levels only active at/after 09:35 ET, `ORH_15` at/after 09:45,
  `ORH_30` at/after 10:00. Same for their `L` counterparts.
- Random spot-check of 5 sweeps prints ±2 bars of context for manual
  eyeballing against TradingView.
- Pass B sweep-tagged + untagged trade counts sum to tradeable (win /
  loss) FVGC baseline — verify in `fvgc_lift_overall.csv` vs the
  standard baseline summary.

## Known gaps / next iterations

- **Equal highs / equal lows clustering.** v1 treats each fractal
  independently; a proper "relative equal highs" detector (≥2 wicks
  within 0.15×ATR) would surface juicier pools. Would slot into
  `levels.py`.
- **4H FVG edges.** Huge primary targets in your framework. Need a
  higher-timeframe FVG detector (cannot reuse `fvgc.model` directly
  because it detects entries, not HTF pools). Proposed: add
  `htf_fvgs.py` and extend levels with `H4_FVG_TOP` / `H4_FVG_BOT`.
- **Level significance score.** Touch counts and "interest" scores
  (e.g. how much volume traded near the level in the hour it formed)
  could upgrade the feature set once equal-levels exist.
- **Higher-timeframe bias agreement.** Currently only implicit via 4H
  swings. A dedicated daily bias flag would strengthen Pass B.
- **Walk-forward/out-of-sample split.** Right now base rates and lift
  numbers are computed on the full history in one pass. After v1
  settles, split into train/val or use expanding window.
- **Macro calendar.** No red-folder news. The `macro_window` feature is
  time-of-day only (8:30, 9:30, 10:00, 14:00, 15:00 ± 10 min).
- **Weekly and monthly levels.** PWH/PWL are here; monthly + quarterly
  high/low would be easy additions.
- **CHOP threshold asymmetry.** Currently symmetric (1 ATR run / 1 ATR
  reverse). Consider loosening the CHOP band to surface more decisive
  moves — or tightening to reduce noise. Tune once you see the first
  distribution.

## Observations / trade-off log

_(Populated after the first real run. Expected pattern: `ORH_5`/`ORL_5`
runs hot during `open30`; `PDH`/`PDL` reverts during `midday`; 4H swings
mostly reverse on first touch but run when daily bias agrees.)_

## What I'd trade differently tomorrow

_(Populated after the first real run — rules you can actually take or
skip based on the cells where |delta| ≥ 5pp and N ≥ 30.)_
