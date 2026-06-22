# Sweep-Then-FVGC Confluence Study

**Status:** killed — OOS lift fails the +8pp threshold. VP target gate, not the sweep,
is doing the work.

## Hypothesis

An FVGC SHORT fired within N minutes after a BSL (London-session swing high) sweep is
higher-probability than the same FVGC signal without the recent sweep. Symmetrically for
LONG after SSL sweep. The "Turtle Soup" pattern combined with FVGC entry should produce
a confluence cell with elevated hit_2R.

## Data and method

- **Trades:** `studies/baseline/results/trades.csv`, 4,548 entered (non-skip) trades
  2018-01 → 2026-05.
- **Levels:** `data/levels/liquidity_levels.csv`, `group='bsl_ssl'`. `bsl_level` is the
  highest confirmed swing high in the London window 02:00–08:00 ET; `ssl_level` the
  lowest swing low. One BSL and one SSL per session date.
- **Bars:** `data/consolidated/nq-front-month.ohlcv-30s.parquet`, 5.88M 30-second bars.
- **Sweep detection:** for each trade, scan 30s bars on the trade date in the window
  [09:30, entry_time). A BSL sweep is recorded if any bar high > `bsl_level`. The
  most-recent sweep bar gives `bsl_swept_min_ago` (minutes between sweep bar and entry).
  SSL is symmetric with `low < ssl_level`. Windows tested: 5, 10, 15, 30 minutes.
- **Direction-aligned flag:** `sweep_aligned_Nm` = (SHORT ∧ BSL swept ≤N min) ∨ (LONG ∧ SSL
  swept ≤N min). This is the Turtle Soup × FVGC pairing.
- **IS:** 2018-01 → 2022-12. **OOS:** 2023-01 → 2026-05. Window size selected post-hoc
  across all four; kill criteria applied to OOS only.

Validation: ran the sweep-detector on the first 100 entered trades and spot-checked. 84
of 100 had at least one sweep (BSL or SSL) within 10 minutes — sane, since both extremes
of the London range are usually broken inside the first 30 min of RTH.

## Headline results

All entered trades hit_2R baseline = **42.22%**.

### Overall direction-aligned sweep cells (full sample)

| window | n_aligned | wr_2R aligned | n_not_aligned | wr_2R not | lift_pp |
|---|---|---|---|---|---|
| 5m  | 1222 | 44.35 | 3326 | 41.43 | +2.92 |
| 10m | 1451 | 43.83 | 3097 | 41.46 | +2.37 |
| 15m | 1600 | 44.12 | 2948 | 41.18 | +2.94 |
| 30m | 1844 | 44.90 | 2704 | 40.38 | +4.52 |

Mild lift, but the magic is asymmetric — see below.

### Lift is short-only

Pooled across all years, **LONG ∧ SSL sweep is flat to negative**, while **SHORT ∧ BSL
sweep is +6–9pp**:

| cell | n | wr_2R |
|---|---|---|
| long_sweep_aligned_10m       | 716  | 40.64 |
| long_NOT_sweep_aligned_10m   | 1568 | 42.35 |
| short_sweep_aligned_10m      | 735  | **46.94** |
| short_NOT_sweep_aligned_10m  | 1529 | 40.55 |

Confirms the cross-study pattern already documented in `project_turtle_soup` and
`project_on_sweep_reversal`: **reversal longs are structurally weak; reversal shorts
carry the signal.**

### IS/OOS split — the decay

Short cell, the only one that mattered:

| split | window | n aligned | wr_2R aligned | n not | wr_2R not | **lift_pp** |
|---|---|---|---|---|---|---|
| IS  | 5m  | 281 | 49.11 | 850 | 37.53 | **+11.58** |
| IS  | 10m | 355 | 47.61 | 776 | 37.11 | **+10.50** |
| IS  | 15m | 403 | 47.89 | 728 | 36.26 | **+11.63** |
| IS  | 30m | 454 | 48.46 | 677 | 35.01 | **+13.45** |
| OOS | 5m  | 326 | 46.93 | 807 | 43.99 | +2.94 |
| OOS | 10m | 380 | 46.32 | 753 | 44.09 | +2.23 |
| OOS | 15m | 414 | 46.38 | 719 | 43.95 | +2.43 |
| OOS | 30m | 486 | 47.12 | 647 | 43.12 | +4.00 |

The signal looked like a clean +10–13pp filter in 2018–2022 and collapsed to +2–4pp in
2023–2026. Decay is consistent across window choice, so it isn't a knob-tuning artifact.

### Yearly stability (short × sweep_aligned_10m)

| year | n_aligned | wr_2R_aligned | wr_2R_base | lift_pp |
|---|---|---|---|---|
| 2018 | 31  | 67.74 | 42.55 | +25.19 |
| 2019 | 12  | 33.33 | 30.95 | +2.38  |
| 2020 | 73  | 42.47 | 34.95 | +7.52  |
| 2021 | 98  | 50.00 | 42.25 | +7.75  |
| 2022 | 141 | 45.39 | 43.36 | +2.03  |
| 2023 | 102 | 48.04 | 40.57 | +7.47  |
| 2024 | 121 | 44.63 | 44.86 | -0.23  |
| 2025 | 115 | 46.96 | 47.52 | -0.56  |
| 2026 | 42  | 45.24 | 45.95 | -0.71  |

Six of nine positive years, but the last three (2024, 2025, 2026) are flat to negative.
2018 carries an outsized share of the IS lift (n=31, +25pp); strip it and IS lift is
already mediocre.

### Stack with VP targets (sweep × has_vp)

`has_vp` = `n_vp_targets ≥ 1` (prior-day POC/VAH/VAL within 0.5–3.0 R ahead). Cells with
n in each direction × sweep × has_vp:

| split | direction | sweep | has_vp | n | wr_2R |
|---|---|---|---|---|---|
| IS  | short | False | True  | 338 | 50.59 |
| IS  | short | True  | True  | 184 | **58.70** |
| OOS | short | False | True  | 316 | 57.28 |
| OOS | short | True  | True  | 191 | **58.12** |
| IS  | long  | False | True  | 357 | 52.10 |
| IS  | long  | True  | True  | 214 | 48.13 |
| OOS | long  | False | True  | 448 | 55.58 |
| OOS | long  | True  | True  | 210 | 51.90 |

`has_vp` carries the lift (consistent with `project_vp_targets`). Adding sweep:
- SHORTS: +8pp IS, **+0.8pp OOS** — the sweep contribution decayed away.
- LONGS: -4pp in both splits — sweep makes longs *worse*.

The VP target gate is doing all the work that looked like sweep signal pooled.

### Variant breakdown (10m window, all years)

| variant | direction | n_aligned | wr_2R aligned | wr_2R total | lift_pp |
|---|---|---|---|---|---|
| protected_swing | short | 110 | 54.55 | 47.76 | **+6.78** |
| ifvg            | long  | 87  | 47.13 | 41.95 | +5.18 |
| bos             | short | 228 | 48.25 | 43.29 | +4.95 |
| no_fvg          | short | 287 | 44.60 | 41.18 | +3.42 |
| protected_swing | long  | 113 | 48.67 | 45.79 | +2.88 |
| ifvg            | short | 110 | 42.73 | 40.07 | +2.66 |
| no_fvg          | long  | 278 | 39.21 | 42.07 | -2.86 |
| bos             | long  | 238 | 36.13 | 39.72 | -3.58 |

`protected_swing × short × sweep` is the cleanest cell at 54.55% n=110, but no IS/OOS
split shown here, and at n=110 it's well within the noise of a 50% baseline plus 6
chance-significant cells out of 8 tested.

## Kill criteria check

> If sweep-aligned trades don't lift hit_2R by ≥ +8pp in OOS, the confluence doesn't
> beat random additions.

OOS lift for the best short cell (30m window) is **+4.0pp**, the rest are +2–3pp. **Fails
the kill criterion.** Study killed.

## Comparison to Turtle Soup v0.3

`project_turtle_soup.md` (Apr 2026) reports a 5-factor additive short model: score 3+ =
**73.2% WR (n=56)**, score 4+ = **100% WR (n=13)**. That study's discovery sample was
2023-10 → 2026-02 — overlapping our OOS window.

Our sweep + FVGC short cell tops out at **48% WR** even in IS and **46% WR** in OOS at
sample sizes 5-10× larger. These are not the same signal:

- Turtle Soup uses W3 (10:00–10:15) timing, depth-banded sweep wick (5-15pt), MSS
  reclaim, prior-day-strong, gap-flat. All five are needed for the 73% tier.
- Sweep-then-FVGC uses any BSL sweep within the last 30 minutes and any FVGC trigger.
- Turtle Soup's "any session level" sweep includes `bsl_level` but also `or_high`,
  `prev_day_high`, `6am_high`, etc. — broader liquidity definition.

The two findings are consistent in direction (short reversals after sweep) but Turtle
Soup is a much narrower, much sharper filter. Sweep-then-FVGC alone is too loose to be
useful.

## Conclusions

1. **Sweep-then-FVGC fails kill criteria** in OOS. Do not promote.
2. **`has_vp` is the real filter.** Both directions benefit; `n_vp_targets ≥ 1` lifts
   shorts ~+19pp and longs ~+23pp in OOS. Confirmed prior finding in `project_vp_targets`.
3. **Sweep is short-only signal** — confirms `project_on_sweep_reversal` and
   `project_turtle_soup` cross-study finding that reversal longs are structurally weak.
4. **The promising-looking IS edge (+11-13pp on shorts) decayed sharply post-2023.**
   Consistent with the broader pattern that the 2023+ regime compresses the WR gap
   between filtered and unfiltered trades.
5. **`protected_swing × short × sweep_aligned_10m`** at 54.55% n=110 is interesting but
   underpowered after IS/OOS split, and the lift here is essentially absorbed by
   `has_vp` and Turtle Soup's existing filter stack.

## Don't extend

This study should not be extended. Better next steps:
- Re-validate Turtle Soup v0.3 strictly OOS on 2026-02 → 2026-05 (post-discovery window).
- Mine for what *makes* the sweep signal decay 2024+ — is it changed liquidity behavior
  during the ATH expansion, or session-time drift?

## Artifacts

- `run.py` — full pipeline
- `_validate.py` — 100-trade sanity-check
- `results/trades_with_sweep.csv` — enriched trades
- `results/cells_overall.csv`, `results/cells_is_oos.csv` — cell summaries
- `results/yearly_stability.csv` — year-by-year lift
- `results/variant_breakdown.csv` — variant × direction × sweep
- `results/sweep_x_vp.csv` — VP stack
- `results/run.log` — full log
