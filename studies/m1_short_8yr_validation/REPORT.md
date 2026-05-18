# M1 Short Confluence Model — 8-Year Validation

**Date:** 2026-05-18
**Dataset extension:** 2018-01-02 → 2026-05-15 (was Oct 2023 → Mar 2026)
**Question:** Does the M1 Short Confluence Model (multi_cell_confluence study, 2026-05-15) still hold up when re-tested on the full 8-year history?

## Headline Verdict

**The play degrades meaningfully on extended history.** The 2+ tier drops from a claimed 68.5% IS / 76.9% OOS WR to **56.1% WR on the 8-year sample**. The 4+ tier drops from 87.5% to **58.1% WR**. The play retains positive edge (PF 1.28 at 1R, 2.02 at 2R) but the magnitude is much smaller than the recent training window suggested. The original model **overfit to the 2023-2026 favorable regime**.

## Side-by-side: 3-year (Notion) vs 8-year (this study)

| Metric | 3-year (Notion claim) | **8-year (actual)** | Delta |
|---|---|---|---|
| 2+ tier WR | 68.5% IS / 76.9% OOS | **56.1%** (n=187) | -13 to -21pp |
| 2+ tier PF @ 2R | 2.44 | **2.02** | -0.4 |
| 2+ tier hit_2R | 55.0% | **50.3%** | -4.7pp |
| 2+ tier hit_3R | 38.7% | **45.5%** | +6.8pp ✓ |
| 4+ tier WR | 87.5% | **58.1%** (n=31) | -29pp |
| 4+ tier PF @ 2R | 6.00 | **2.43** | -3.6 |
| Median MFE 1R+ | 4.0R | **5.6R** | +1.6R ✓ |

Two things noteworthy:
- **MFE actually held up** (5.6R vs 4.0R claimed). The runner profile is real.
- **3R hit rate is higher** in the 8-year data (45.5% vs 38.7%). The play still produces big winners, just at lower WR.

## Year-by-year (2+ tier)

| Year | n | WR | Med MFE | Comment |
|---|---|---|---|---|
| 2018 | 24 | 50.0% | 6.68R | Trump vol; mediocre |
| 2020 | 30 | **33.3%** | 12.98R | COVID — disaster |
| 2021 | 15 | 60.0% | 4.12R | |
| 2022 | 36 | 55.6% | 5.52R | Bear year, OK |
| 2023 | 23 | 73.9% | 5.69R | Training window starts |
| 2024 | 25 | **48.0%** | 4.86R | Weak even within training |
| 2025 | 20 | **80.0%** | 7.25R | Strong (where the training looks great) |
| 2026 | 10 | 70.0% | 3.21R | Recent — held up |

(2019 had n<5 at 2+ tier — excluded.)

The 2025 / 2026 numbers (75-80%) are the basis of the Notion claim. 2024 was already a weak year buried in the training window. 2020 was a complete miss.

## Regime breakdown (60-day NQ return)

| Regime | n | WR | PF @ 1R | PF @ 2R | Med MFE 1R+ |
|---|---|---|---|---|---|
| Bear (60d < -5%) | 67 | 56.7% | 1.31 | 2.06 | 5.5R |
| Bull (60d > +5%) | 64 | 56.2% | 1.29 | 1.76 | 4.9R |
| Neutral | 50 | 54.0% | 1.17 | 2.17 | 6.1R |

**Regime-robust at the consistent-but-lower level.** WR varies only 2.7pp across bear/bull/neutral — within noise. Bear and bull are essentially identical. The play isn't bear-dependent; it's just modest across all regimes.

## Setup-day predictability — the new finding

**Setup days** = days with no veto AND ≥2 confluences. On these days, only ~26% actually produce a tradeable M1 short FVGC.

**Total setup days (8-year):** 540
**Of which fired tradeable FVGC:** 141 (26.1%)
**Avg trades per fired setup day:** 1.79

What predicts firing?

| Feature | n_on | Fire rate ON | n_off | Fire rate OFF | Lift |
|---|---|---|---|---|---|
| **OR 5-min range top-quartile** | 182 | **34.6%** | 358 | 21.8% | **+12.8pp** |
| Overnight range top-quartile | 162 | 31.5% | 378 | 23.8% | +7.7pp |
| 930 body top-quartile | 235 | 29.4% | 305 | 23.6% | +5.8pp |
| Conf ≥ 3 | 266 | 28.6% | 274 | 23.7% | +4.8pp |
| Thursday | 114 | 28.9% | 426 | 25.4% | +3.6pp |
| Large gap down (≥100pts) | 117 | 28.2% | 423 | 25.5% | +2.7pp |
| Conf ≥ 4 | 85 | 28.2% | 455 | 25.7% | +2.5pp |
| Tuesday | 118 | 26.3% | 422 | 26.1% | +0.2pp |
| Friday | 191 | 25.1% | 349 | 26.6% | -1.5pp |
| Wednesday | 117 | 24.8% | 423 | 26.5% | -1.7pp |
| OpEx week | 79 | 24.1% | 461 | 26.5% | -2.4pp |
| VIXY high | 271 | 24.4% | 269 | 27.9% | -3.5pp |
| **FOMC week** | 75 | **17.3%** | 465 | 27.5% | **-10.2pp** |

**Two big findings:**

1. **OR 5-min range top-quartile** (knowable by 9:35) is the strongest firing predictor: +12.8pp lift. Equivalent to: on high-vol opens, 1 in 3 setup days fires; on low-vol opens, 1 in 5.

2. **FOMC week LOWERS fire rate by 10pp** — but in the existing factor stack it's counted as a +12pp WR confluence. This is contradictory: FOMC weeks have fewer signals AND when signals fire they produce slightly higher WR. The play probably shouldn't count FOMC as a +confluence — at minimum revisit this factor.

## What changed materially vs the 3-year study

| Factor / Effect | 3-year finding | 8-year reality |
|---|---|---|
| 2+ tier WR | 68-77% | **56%** |
| Best year | 2025 (80%) | Same |
| Worst year | (not tested) | 2020 (33%) — COVID |
| 4+ tier robustness | n=24, 87.5% WR | n=31, 58% WR — much weaker |
| FOMC week | +12pp WR confluence | **-10pp fire rate predictor** |
| Opening range filter | Not in model | **+12.8pp fire predictor — strongest single signal** |
| Median MFE | 4.0R | 5.6R (held up) |

## Recommendations

### Update the Notion page

Don't keep advertising 76.9% OOS WR. Use these honest numbers:
- **2+ tier WR: ~56% over 8 years** (with year-by-year variability 33-80%)
- **PF @ 2R: ~2.0**
- **Median MFE when 1R hits: ~5.6R** (the runner profile is real)
- **Worst year: 2020 (33% WR)** — flag as a known regime weakness

### Add a fire-rate filter

Add this rule to live execution: **only watch for trades on days where the 9:30-9:35 OR range is in the top quartile of the last 90 days.**
- Reduces screen time by 66% (watch 182 of 540 setup days)
- Captures 45% of fires (63 of 141)
- Improves trades-per-screen-day from 0.26 to 0.35

### Re-mine the factor stack

The original 7 factors were chosen on a 3-year window with selection bias toward what worked. With 8 years of data:
- Drop FOMC week as a confluence (it negatively predicts firing)
- Drop or rethink vixy_high (negative fire predictor, neutral WR effect)
- Add OR 5-min range as either a confluence or a fire-rate filter
- Re-run factor mining on the full 8-year frame

This is a separate study — flag as TODO.

### Reset expectations on EV

- 3-year claim: +0.77R/trade with recommended runner exit
- 8-year honest estimate: probably +0.30 to +0.45R/trade — still profitable, but ~half the claimed EV
- For a portfolio sizing decision, use 0.40R/trade not 0.77R/trade

## Methodology Caveats

1. **Factor stack held constant** — used the same 7 factors and 2 vetoes from the multi_cell_confluence study. A fresh factor-mining pass on 8 years would likely produce a different (better) stack.
2. **VIXY data starts April 2018** (vixy_prior_close has NaN for first 3 months). Some early 2018 days have no VIXY-derived confluences computed — minor effect.
3. **`mfe_r` field has the documented post-exit bug.** Used `hit_X_R` columns for runner stats; only used `mfe_r` for median-MFE-among-1R+-trades reporting (where the bug effect is smaller).
4. **Did NOT re-do OOS validation** with the 8-year split. With 8 years, suggest the last 18 months as OOS holdout for a future re-run.

## Files

- `run.py` — analysis script
- `results/trades_m1_short_tagged.csv` — per-trade with conf + veto + tier
- `results/tier_summary.csv` — per-tier WR/PF/hit_X_R
- `results/year_breakdown.csv` — year × tier WR
- `results/regime_breakdown.csv` — bear/bull/neutral × tier WR
- `results/setup_day_predictability.csv` — fire-rate features
- `results/days_with_factors.csv` — per-day factor table

## Bottom line

The play works. The recent 3-year window's 76% WR claim doesn't replicate on 8 years — the real number is ~56%. PF is ~2.0 at 2R, the runner is real (5.6R median MFE on winners), and the play is regime-robust at the lower level. Update the playbook to reflect honest 8-year numbers, add the OR 5-min range filter, and re-mine factors on the full dataset before claiming any higher edge.
