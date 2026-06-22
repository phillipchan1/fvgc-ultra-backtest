# Naked VP Levels Study — kill

## Verdict

**KILL.** The hypothesis "POC/VAH/VAL untouched since inception is a stronger
magnet than one already tapped" is not supported on this dataset.

> ⚠ **Inherited lookahead caveat.** This study uses the same VP join as
> the parent [[project_vp_targets]]: `daily_volume_profile.csv` keyed by trade
> date D, which stores **today's full-RTH VP** (9:30-16:00). A FVGC trade in
> the first 45 min therefore "sees" today's POC/VAH/VAL before it could
> possibly be known. The composite-VP study found that under strictly causal
> (lag-1, yesterday's-VP) data the `n_vp_targets >= 2` lift collapses to
> +0.3pp. The naked-vs-touched comparison here remains internally valid
> (both sides use the same lookahead), but the *absolute* lifts cited below
> are inflated. The kill verdict only strengthens under the causal frame
> because naked is a strict subset of the parent count — it cannot rescue a
> count signal that already collapses.

| criterion | threshold | actual | status |
|-----------|-----------|--------|--------|
| `n_naked_vp_targets >= 2` OOS lift exceeds `n_vp_targets >= 2` by ≥ +5pp | yes | **+0.00pp** | KILL |
| Naked cohort at higher N (2, 3, 5) maintains n ≥ 200 in the >=2 bucket | yes | only N=1 clears the floor | KILL |
| Monotonic lift as level becomes more stale | yes | non-monotone; freshest cohort has the highest IS lift | KILL |

`n_vp_targets` remains the cleaner story. Naked refinement is not free alpha
on this dataset; it discards sample without improving hit_2R.

---

## 1. Methodology

- Touch detection: for each (vp_date D, level_type ∈ {POC, VAH, VAL}, level_price X),
  find the most recent date d strictly less than D where ETH daily H/L straddled X
  (`day_low[d] <= X <= day_high[d]`). `days_since_touched = D_idx - d_idx` in trading-day units.
  Levels with no prior touch in the available history (back to 2018-01-01)
  flagged "naked-since-inception" (dsd = 999).
- Bars: ETH daily H/L computed from `data/consolidated/nq-front-month.ohlcv-15m.parquet`
  grouped by NY calendar date. Daily H/L from 15m bars is identical to from 1m
  or 30s (max/min over the day), so this is fast without information loss.
- VP join: same convention as parent study (`trades.date == vp.date`).
- Splits: IS = 2018-2022 (n=2193, base hit_2R=40.0%); OOS = 2023-2026
  (n=2355, base hit_2R=44.2%). Pooled n=4548.
- Naked thresholds tested: N ∈ {1, 2, 3, 5}. N is selected on IS only;
  OOS is frozen for the chosen N.
- Kill criterion: if `n_naked_vp_targets >= 2` OOS lift is not ≥ +5pp larger
  than `n_vp_targets >= 2` OOS lift, the naked refinement is not a real cut.

---

## 2. The touch-history is dense — most VP levels are not naked

`days_since_touched` quantiles across all 2,158 × 3 = 6,474 (date × level)
pairs:

| q10 | q25 | **q50** | q75 | q90 | q95 | q99 |
|----:|----:|--------:|----:|----:|----:|----:|
| 1   | 1   | **1**   | 5   | 47  | 999 | 999 |

- **Median dsd = 1 trading day.** Yesterday's daily range typically straddles
  today's VP levels.
- 378 of 6,474 levels (5.8%) are naked-since-inception (dsd=999).
- The "naked level" concept is rarer than the mentor framing implies. NQ
  daily ranges (~100-200 pts) routinely re-cover prior-day VP levels.

This is the core reason the hypothesis can't be tested cleanly: stricter
thresholds (N≥2) immediately collapse cohort sizes below the 200-trade floor
in the most relevant `n_naked >= 2` bucket. See §3.

---

## 3. Threshold scan — only N=1 clears the n≥200 floor

`n_naked_vp_targets` bucket counts for each tested N (IS-side):

| N  | bucket | n_IS | hit_2R_IS | lift_IS_pp |
|---:|:------|----:|----------:|-----------:|
| 1  | 0     | 1100 | 28.2% | −11.85 |
| 1  | 1     | 887  | 49.4% |  +9.34 |
| 1  | 2     | 198  | 62.1% | +22.08 |
| 1  | 3+    |   8  | 87.5% | +47.46 |
| 2  | 0     | 1713 | 37.2% | −2.79 |
| 2  | 1     | 394  | 47.2% | +7.17 |
| 2  | 2     |  82  | 61.0% | +20.94 |
| 2  | 3+    |   4  |100.0% | +59.96 |
| 3  | 0     | 1862 | 37.8% | −2.28 |
| 3  | 1     | 265  | 50.6% | +10.53 |
| 3  | 2     |  63  | 60.3% | +20.28 |
| 5  | 0     | 1950 | 38.9% | −1.16 |
| 5  | 1     | 203  | 47.3% | +7.25 |
| 5  | 2     |  38  | 57.9% | +17.86 |

At N=1 the chosen-bucket >=2 has n_IS=206 (>=200 floor cleared). At N=2,
the >=2 bucket has only 86 trades — below the n≥200 floor specified in
the methodology guardrails. N=3 and N=5 collapse further.

**Selected N = 1** (the only choice that satisfies the cohort-size floor
when partitioning by n_naked).

At N=1, `n_naked_vp_targets` is **mathematically identical** to
`n_vp_targets`. By construction every level has dsd ≥ 1 (we look at d < D
strictly). So the chosen-threshold filter degenerates to the parent feature.

---

## 4. Head-to-head — chosen N delivers zero lift

| feature | bucket | n_IS | hit_IS | lift_IS | n_OOS | hit_OOS | lift_OOS |
|---------|--------|-----:|-------:|--------:|------:|--------:|---------:|
| n_vp_targets       | ==0  | 1100 | 28.2% | −11.85 | 1190 | 32.9% | −11.31 |
| n_vp_targets       | ==1  |  887 | 49.4% |  +9.34 |  911 | 53.5% |  +9.21 |
| n_vp_targets       | ==2  |  198 | 62.1% | +22.08 |  237 | 62.0% | +17.78 |
| **n_vp_targets**   | **>=2** | **206** | **63.1%** | **+23.07** | **254** | **64.2%** | **+19.93** |
| n_naked_vp_targets | ==0  | 1100 | 28.2% | −11.85 | 1190 | 32.9% | −11.31 |
| n_naked_vp_targets | ==1  |  887 | 49.4% |  +9.34 |  911 | 53.5% |  +9.21 |
| n_naked_vp_targets | ==2  |  198 | 62.1% | +22.08 |  237 | 62.0% | +17.78 |
| **n_naked_vp_targets** | **>=2** | **206** | **63.1%** | **+23.07** | **254** | **64.2%** | **+19.93** |

Every row matches to the third decimal. **Delta = +0.00pp.** This is the
"all levels are naked under N=1" degeneracy, not a coincidence.

---

## 5. The decisive counter-evidence — freshness ≠ stronger

The hypothesis predicts: more days-since-touch → bigger magnet. Tested by
bucketing trades on the freshness of the freshest in-direction target.
Restricted to the n=2,258 trades with at least one in-dir VP level ahead.

| freshness of freshest in-dir target | n_IS | hit_2R_IS | lift_IS_pp | n_OOS | hit_2R_OOS | lift_OOS_pp |
|-------------------------------------|-----:|----------:|-----------:|------:|-----------:|------------:|
| **fresh (dsd == 1, touched yesterday)** | **641** | **53.4%** | **+13.32** | **620** | **56.0%** | **+11.72** |
| recent (dsd 2-4)                    |  229 | 51.5%   |  +11.49   |  226 | 61.1%   |  +16.82   |
| stale (dsd 5-30)                    |  135 | 49.6%   |   +9.59   |  211 | 48.8%   |   +4.57   |
| very stale (>30, incl. inception)   |   88 | 46.6%   |   +6.55   |  108 | 57.4%   |  +13.16   |

The trend is **non-monotone** and on IS slightly **inverted**: freshly-touched
levels have the largest IS lift (+13.3pp) and the largest cohort (n=641).
The "very stale" cohort (>30 days, including all 88 IS naked-since-inception
trades) has the **weakest IS lift** at +6.6pp.

On OOS, "recent" wins (+16.8pp, n=226) and the other three are within ~7pp
of each other. There is no signature of "more-naked = stronger magnet."

**Reading:** what makes a VP level a magnet is that price has done volume
work around it (the VP construction itself), not whether the level is fresh
or stale. The count of VP levels ahead carries the signal; the freshness of
those levels does not refine it.

---

## 6. Per-level-type — naked-ness doesn't change the asymmetry pattern

Numbers below match the parent A2 table (because at N=1, "naked X" == "X in
direction"). Listed here only to confirm no asymmetry was lost.

| filter | direction | n_IS | lift_IS | n_OOS | lift_OOS |
|--------|-----------|-----:|--------:|------:|---------:|
| naked_poc | all   | 396 | +21.07 | 452 | +19.03 |
| naked_vah | all   | 459 |  +9.85 | 479 |  +6.69 |
| naked_val | all   | 452 | +11.73 | 505 | +14.96 |
| naked_poc | long  | 203 | +19.57 | 278 | +16.55 |
| **naked_val** | **long**  | **138** | **+25.91** | **202** | **+30.01** |
| naked_vah | long  | 353 |  +3.31 | 356 |  −1.27 |
| naked_poc | short | 193 | +22.66 | 174 | +23.00 |
| **naked_vah** | **short** | **106** | **+31.66** | **123** | **+29.74** |
| naked_val | short | 314 |  +5.50 | 303 |  +4.93 |

Same VAL→longs, VAH→shorts, POC→both asymmetry as the parent finding. The
"naked" framing doesn't change anything here.

---

## 7. Yearly n_naked_vp_targets == 2 (degenerate vs n_vp_targets == 2)

Mirrors the parent table exactly. Documented for the record:

| year | n | hit_2R | lift_pp |
|------|--:|-------:|--------:|
| 2018 | 19  | 73.7% | +30.83 |
| 2019 | 13  | 53.8% | +23.41 |
| 2020 | 41  | 68.3% | +29.18 |
| 2021 | 47  | 57.4% | +18.13 |
| 2022 | 78  | 60.3% | +18.88 |
| 2023 | 66  | 54.5% | +13.72 |
| 2024 | 52  | 65.4% | +21.70 |
| 2025 |100  | 66.0% | +18.48 |
| 2026 | 19  | 57.9% | +14.30 |

9 of 9 positive — identical to parent because the cohorts are identical
under N=1.

---

## 8. Why the hypothesis fails on this data

1. **NQ daily ranges are large relative to day-over-day VP drift.** With
   100-200 pt daily ranges and 30-80 pt VP shifts, yesterday's range
   covers today's VP levels more than half the time (q50 dsd = 1). The
   "level untouched since being set" condition almost never holds for
   recent levels.
2. **Naked-since-inception is rare and small-cohort.** Only 378 out of
   6,474 (date × level) pairs qualify, and the subset where one happens
   to sit at 0.5R-3R in trade direction is even smaller (~88 IS trades).
   Not enough sample to dominate the parent count signal.
3. **The magnet effect is structural, not freshness-driven.** A VP level
   reflects high-volume price acceptance; price often returns to that
   acceptance area regardless of whether it touched recently. The
   "naked = stronger" framing implies prior touches discharge the magnet,
   but the data shows freshly-touched levels are pulled toward at least
   as readily as untouched ones.

---

## 9. What this study rules out (so we don't repeat the question)

- "VP levels touched yesterday are stale" — false; they still drag price.
- "Naked-since-inception levels are the real signal hiding inside
  n_vp_targets" — false; that cohort is *smaller* and has *weaker* lift.
- "Should we ship n_naked_vp_targets >= 2 instead of n_vp_targets >= 2" —
  no; identical filter at the only viable N, sample-thinning at higher N.

What we did NOT test (out of scope, per spec):
- Multi-day composite VP (separate study).
- HTF FVG nesting (separate study).
- Naked session HIGH/LOW levels (PD H/L, ON H/L) — could be a follow-up
  but VP-level-specific naked-ness was the question here.
- Same hypothesis on the day-of-touch level (using session H/L vs. only
  bars where price actually traded to the level for several seconds).
  Daily H/L-straddle is a strict "touch"; if price wicked through 6555
  for 1 second, it counts. Stricter touch definitions might shift the
  picture but the median dsd would only get larger, making the "naked"
  cohort even smaller — not bigger.

---

## 10. Files

| file | purpose |
|------|---------|
| [run.py](run.py) | Reproducible pipeline |
| [results/touch_history.csv](results/touch_history.csv) | (vp_date, level_type, last_touch_date, days_since_touched) — 6,474 rows |
| [results/threshold_scan.csv](results/threshold_scan.csv) | N ∈ {1,2,3,5} × bucket × IS/OOS |
| [results/walk_forward.csv](results/walk_forward.csv) | n_naked (N=1) walk-forward — identical to parent |
| [results/naked_vs_touched_hit_2R.csv](results/naked_vs_touched_hit_2R.csv) | Head-to-head: n_vp_targets vs n_naked_vp_targets |
| [results/decomposition.csv](results/decomposition.csv) | Q4 all-naked vs mixed vs all-touched (degenerate at N=1) |
| [results/per_level_type.csv](results/per_level_type.csv) | Q5 naked POC vs VAH vs VAL × direction |
| [results/yearly_n_naked_vp_2.csv](results/yearly_n_naked_vp_2.csv) | Q6 9-year robustness |
| [results/freshness_vs_hit_2R.csv](results/freshness_vs_hit_2R.csv) | Counter-evidence — fresh vs stale targets |
