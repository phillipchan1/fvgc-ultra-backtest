# Feature Discovery — Predicting hit_2R on the 30s Baseline

## Causal Audit Status

**INVALIDATED — 2026-05-21.** This study has two distinct lookahead bugs in `run.py`:
1. **VP join (`run.py:50,78`)** — `daily_volume_profile.csv` joined on `date` exposes today's 9:30-16:00 POC/VAH/VAL to 9:30-10:15 trades. The `n_vp_targets` / `vp_only_target` findings collapse to noise under lag-1 VP (see [`studies/lookahead_audit/`](../lookahead_audit/analysis.md)).
2. **`range_regime` (`run.py:184`)** — `pl.col('rth_range') > rolling_avg * 1.25` uses today's full-session range. `range_regime` cannot be computed at trade time; any cell citing range_regime (here and in [higher_R_targets](../higher_R_targets/analysis.md)) is uncomputable causally.

Additional suspect (time-gated, not masked): `or_*_state` and `match_930_dir` derived on lines 137,155-162 — gated features used on trades before the gate.

**Headlines preserved below for historical context.** Do not act on `n_vp_targets`, `vp_only_target`, or `range_regime` findings.

---

**Goal.** Find features (single or stacked) that move the per-trade probability of
reaching ≥2R from the base rate (~42%) toward 55%+ on samples of n≥50, on the
full 2018-01 → 2026-05 baseline.

**Sample.** 4,548 trades (after dropping 2,066 `outcome=skip` rows where the playbook
filtered the signal before execution).

**Headline.** One single-feature finding survives strict IS+OOS testing
(`n_targets_in_dir == 2`, ~+6.7pp both eras). The strongest *negative* filter is
much bigger: trades with **zero** target-in-direction levels in the 0.5R–3R magnet
zone hit 2R only **30.8% IS / 36.7% OOS** (vs ~40-45% base) — a free −9pp drag,
n=878. The cleanest composite (60% OOS hit on n=102, n=204 combined) is:

> **n_targets_in_dir == 2 AND range_regime != contraction AND gap_bucket == large_up**

---

## 1. Methodology

- **IS / OOS split.** Train: 2018-2023 (3,099 trades). Validate: 2024-2026 (1,449 trades).
- **Era base rates.** IS = 40.2%, OOS = 45.4%. ~5pp drift between eras — every
  lift is reported against the *matching* era's base, so a +5pp OOS lift means
  +5pp on top of the already-elevated 45.4%, not +5pp vs 40%.
- **Single-feature rule.** A bucket is a *strict survivor* iff
  `lift_IS ≥ 3pp` AND `lift_OOS ≥ 3pp` AND `n_IS ≥ 50` AND `n_OOS ≥ 50`.
- **Anti-survivor (negative filter).** Bucket where `lift_IS ≤ −3pp` AND
  `lift_OOS ≤ −3pp` AND `n ≥ 50` in each era.
- **Ranking score.** `lift_IS_pp × √min(n_IS, n_OOS)`. Rewards lift × confidence
  rather than raw lift on tiny samples.
- **Stack pool.** Loose (lift_IS≥1.5, lift_OOS≥0, n≥80 each era) plus anti-survivor
  inversions used as negative filters. Stacks require `lift ≥ 5pp` (2-feat) /
  `≥ 8pp` (3-feat) on BOTH eras AND n≥50 each era.
- **Year-by-year check.** Every reported survivor and top stack gets a 2018-2026
  hit-rate-per-year table to spot fragile averages.
- **Multiple comparisons.** ~90 single-feature buckets tested. By chance ~4-5 of
  them would clear IS at p≈0.05; the IS+OOS double-cross is what kills noise.
- **Per-variant pass.** Discovery repeated within each of the 4 variants
  (bos / ifvg / no_fvg / protected_swing).

---

## 2. The headline single-feature finding

### `n_targets_in_dir == 2`

For each trade, count the curated session/HTF levels lying **in the trade's direction**
between 0.5R and 3R of entry. Levels counted: prev_day H/L, asia H/L, london H/L,
6am H/L, overnight H/L, NWOG H/L, BSL/SSL, OR_15min (after 9:45), daily POC/VAH/VAL.

The bucketed rate is **non-monotonic** — sweet spot is *exactly two* magnets ahead:

| n_targets_in_dir | n_IS | hit_2R IS | n_OOS | hit_2R OOS | combined |
|------------------|------|-----------|-------|------------|----------|
| 0 (no magnet) | 507 | **30.8%** | 371 | **36.7%** | 33.2% |
| 1 | 716 | 39.0% | 425 | 44.0% | 40.9% |
| **2** | **422** | **46.9%** | **301** | **52.2%** | **49.1%** |
| 3+ | 1192 | 42.4% | 681 | 46.4% | 43.8% |

The 3+ bucket is interesting: high target count modestly lifts but not as much as 2.
Reading: "one nearby magnet isn't enough resolution; three or more is a congested
zone where price stalls on the first ones." Two is the structural sweet spot.

### Year-by-year for `n_targets_in_dir == 2`

| year | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|------|------|------|------|------|------|------|------|------|------|
| hit_2R | 50% | 50% | 41.6% | 41.5% | 48.8% | 53.2% | 54.9% | 51.5% | 48.3% |
| n | 20 | 8 | 89 | 82 | 129 | 94 | 113 | 130 | 58 |
| year base rate | 42.9 | 30.4 | 39.1 | 39.3 | 41.4 | 40.8 | 43.7 | 47.5 | 43.6 |
| lift_pp | +7.1 | +19.6 | +2.5 | +2.2 | +7.4 | +12.4 | +11.2 | +4.0 | +4.7 |

Lift is **positive in 9/9 years**. 2020-2021 are the weakest cells (only +2pp) but
neither breaks negative. Reasonable confidence in this signal.

---

## 3. The headline negative filter

### `n_targets_in_dir == 0` — flat-out skip

| year | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|------|------|------|------|------|------|------|------|------|------|
| hit_2R | 23.3% | 14.3% | 28.4% | 33.3% | 32.6% | 31.9% | 33.6% | 38.0% | 38.7% |
| n | 30 | 14 | 95 | 102 | 175 | 91 | 125 | 171 | 75 |

**Never reaches base rate in any year.** 878 trades total, 33.2% hit_2R vs 42.2%
sample base. This is the most actionable finding in the study: filtering out the
"no level in trade direction within 0.5–3R" set drops the worst 19% of the trade
list. Effect on the remaining pool:

| filter | n | hit_2R | vs base |
|--------|---|--------|---------|
| no filter (all) | 4548 | 42.2% | — |
| drop `n_targets == 0` | 3670 | 44.4% | +2.2pp |
| keep only `n_targets == 2` | 723 | 49.1% | +6.9pp |

So: the negative filter is mild on what's left (+2pp) but **doesn't cost you any
edge** — it removes a tail of trades that were essentially coin-flip-with-drag.

---

## 4. The composite filter (the deliverable)

### `n_targets_in_dir == 2 AND range_regime != contraction AND gap_bucket == large_up`

Where `range_regime` is current `rth_range` vs 5-day rolling mean: contraction
< 0.75×, expansion > 1.25×, normal in between. `gap_bucket=large_up` is gap from
prior close ≥ +25 NQ pts.

| era | n | hit_2R | lift vs era base |
|-----|---|--------|------------------|
| IS (2018-2023) | 102 | **50.0%** | +9.8pp |
| OOS (2024-2026) | 102 | **59.8%** | +14.4pp |
| combined | 204 | **54.9%** | +12.7pp |

### Year-by-year

| year | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|------|------|------|------|------|------|------|------|------|------|
| hit_2R | 37.5% | 66.7% | 35.0% | 52.9% | 57.1% | 53.8% | **60.9%** | **58.1%** | **61.5%** |
| n | 8 | 3 | 20 | 17 | 28 | 26 | 46 | 43 | 13 |

Caveats:
- Early-year cells are tiny (2018-2021 have n<30). The OOS years carry the weight,
  and they are clean (n=46/43/13 at 60%+).
- 2020 is the only weak full-size year (35% on n=20).
- The signal is **strengthening** through time, not decaying — opposite of the
  classic overfit shape.

### Variant breakdown of the composite

| variant | n | hit_2R |
|---------|---|--------|
| bos | 72 | **61.1%** |
| no_fvg | 89 | 52.8% |
| ifvg | 20 | 50.0% |
| protected_swing | 23 | 47.8% |

The composite is strongest on `bos` (61% on n=72). The combined 54.9% on n=204
clears the user's "60% on n≥100" bar in *OOS* only (59.8%); combined just under.

---

## 5. Top-10 single-feature ranked

Rows sorted by `score = lift_IS × √min(n_IS, n_OOS)`. Bold rows = strict survivors
(both eras lift ≥3pp, both n≥50).

| # | feature | value | n_IS | hit_IS | lift_IS | n_OOS | hit_OOS | lift_OOS | verdict |
|---|---------|-------|------|--------|---------|-------|---------|----------|---------|
| 1 | **n_targets_in_dir** | **2** | 422 | 46.9% | +6.7pp | 301 | 52.2% | +6.8pp | **survives** |
| 2 | gap_bucket | large_up | 1058 | 43.6% | +3.4pp | 881 | 46.0% | +0.6pp | weak OOS |
| 3 | variant | protected_swing | 326 | 45.7% | +5.5pp | 306 | 48.0% | +2.7pp | borderline |
| 4 | macro_window | M3 | 948 | 43.9% | +3.7pp | 626 | 41.1% | **−4.3pp** | **flipped OOS** |
| 5 | has_target_in_dir | True | 2269 | 42.3% | +2.1pp | 1401 | 47.7% | +2.3pp | mild |
| 6 | pdr_position | above_pdh | 593 | 43.7% | +3.5pp | 485 | 44.5% | −0.8pp | flat OOS |
| 7 | prior_day_type | trend_up | 334 | 44.9% | +4.7pp | 171 | 42.1% | **−3.3pp** | **flipped OOS** |
| 8 | range_regime | expansion | 749 | 43.0% | +2.8pp | 486 | 50.8% | +5.4pp | OOS-only strong |
| 9 | n_targets_in_dir | 3+ | 1192 | 42.4% | +2.2pp | 681 | 46.4% | +1.0pp | weak |
| 10 | **prior_day_type** | **reversal_up** | 375 | 43.5% | +3.3pp | 238 | 48.7% | +3.4pp | **survives** |

**Items 4 and 7 are the today's-VIXY-trap analogues**: looked strong on 6 years of
IS data, completely flipped sign on OOS. Specifically:
- `macro_window=M3` (10:00-10:15): IS lifted hit_2R by ~4pp; OOS *hurt* by ~4pp.
  Cell still has ~42% in OOS — base shifted up around it.
- `prior_day_type=trend_up`: same story. Trend-day-after-trend was a 2018-23 thing.

Don't trust either as filters without further work.

---

## 6. Top-10 stacks

### 2-feature (lift ≥5pp on both eras, n≥50 each)

| # | filter | n_IS | n_OOS | hit_IS | hit_OOS | lift_IS | lift_OOS |
|---|--------|------|-------|--------|---------|---------|----------|
| 1 | n_targets==2 & range_regime!=contraction | 328 | 219 | 49.1% | 53.9% | +8.9pp | +8.5pp |
| 2 | n_targets==2 & has_target_in_dir!=False ⓘ | 422 | 301 | 46.9% | 52.2% | +6.7pp | +6.8pp |
| 3 | n_targets==2 & gap_bucket!=small_dn | 399 | 281 | 46.6% | 54.1% | +6.4pp | +8.7pp |
| 4 | range_regime==expansion & n_targets==3+ | 275 | 176 | 46.2% | 52.3% | +6.0pp | +6.9pp |
| 5 | n_targets==2 & gap_bucket==large_up | 142 | 160 | 46.5% | 55.6% | +6.3pp | +10.3pp |
| 6 | entry_bucket==9:30-9:35 & range!=contraction | 139 | 93 | 47.5% | 54.8% | +7.3pp | +9.5pp |
| 7 | n_targets==3+ & prior_day_type==reversal_up | 163 | 82 | 45.4% | 54.9% | +5.2pp | +9.5pp |

ⓘ #2 is logically equivalent to #1 of the single-feature table — `has_target!=False`
is implied by `n_targets==2`. Keep #1 as the canonical "2-feat" stack.

### 3-feature (lift ≥8pp on both eras, n≥50 each)

| # | filter | n_IS | n_OOS | hit_IS | hit_OOS | lift_IS | lift_OOS |
|---|--------|------|-------|--------|---------|---------|----------|
| 1 | range==expansion & n_targets==3+ & gap==large_up | 94 | 69 | **56.4%** | **59.4%** | +16.2pp | +14.0pp |
| 2 | n_targets==2 & range!=contraction & has_target!=False ⓘ | 328 | 219 | 49.1% | 53.9% | +8.9pp | +8.5pp |
| 3 | n_targets==2 & range!=contraction & gap!=small_dn | 312 | 200 | 48.7% | 56.5% | +8.5pp | +11.1pp |
| 4 | **n_targets==2 & range!=contraction & gap==large_up** | **102** | **102** | **50.0%** | **59.8%** | +9.8pp | +14.4pp |
| 5 | entry_bucket==9:30-9:35 & range!=contraction & n_targets!=0 | 109 | 72 | 49.5% | 54.2% | +9.3pp | +8.8pp |

ⓘ #2 is logically equivalent to 2-feat #1 (the third filter is redundant).

**#1 has the highest hit rate (56.4%/59.4%) but smallest sample (n=94/69 — below
the n_OOS≥100 bar).** #4 is the recommended deliverable: 59.8% OOS on n=102, plus
the IS sample is also 100+.

---

## 7. Variant-specific survivors

Per-variant search (n≥30 each era, lift≥3pp both):

| variant | feature | value | n_IS | hit_IS | lift_IS | n_OOS | hit_OOS | lift_OOS |
|---------|---------|-------|------|--------|---------|-------|---------|----------|
| protected_swing | n_targets==2 | — | 53 | **60.4%** | +14.7pp | 49 | **57.1%** | +9.1pp |
| bos | n_targets==2 | — | 151 | **52.3%** | +11.5pp | 75 | **54.7%** | +12.1pp |
| bos | gap_bucket==large_up | — | 341 | 46.3% | +5.5pp | 234 | 47.9% | +5.3pp |
| ifvg | lvls_within_1R==1-2 | — | 102 | 44.1% | +8.4pp | 79 | 54.4% | +5.1pp |
| ifvg | n_targets==3+ | — | 175 | 42.3% | +6.6pp | 100 | 56.0% | +6.7pp |
| bos | range_regime==expansion | — | 235 | 45.1% | +4.3pp | 143 | 51.7% | +9.2pp |
| protected_swing | pdr_position==above_pdh | — | 57 | 50.9% | +5.2pp | 74 | 51.4% | +3.3pp |
| no_fvg | pdr_position==lower_mid | — | 167 | 43.1% | +3.6pp | 97 | 51.5% | +6.6pp |

**Takeaway.** `n_targets_in_dir == 2` repeats as the top filter for both `bos` and
`protected_swing`. For `ifvg`, the cleaner signal is `n_targets == 3+` or simply
"a couple of close levels" (`lvls_within_1R == 1-2`). The level-confluence signal
*is the* signal, just expressed differently per variant.

---

## 8. Anti-survivors (avoid)

| feature | value | n_IS | hit_IS | lift_IS | n_OOS | hit_OOS | lift_OOS |
|---------|-------|------|--------|---------|-------|---------|----------|
| n_targets_in_dir | 0 | 507 | **30.8%** | −9.4pp | 371 | **36.7%** | −8.7pp |
| has_target_in_dir | False | 507 | 30.8% | −9.4pp | 371 | 36.7% | −8.7pp |
| range_regime | contraction | 687 | 34.4% | −5.8pp | 479 | 36.7% | −8.6pp |
| gap_bucket | small_dn | 191 | 36.1% | −4.1pp | 101 | 41.6% | −3.8pp |

`n_targets==0` and `has_target==False` are the same set (878 trades, 33% hit_2R).
`range_regime==contraction` is the next-biggest drag — 1,166 trades, 35% hit_2R.
A "skip when 5-day range contracted" rule alone would lift the remaining pool
hit_2R to ~44.4%.

---

## 9. Lessons — features that looked great IS and failed OOS

These are this study's analogues of today's VIXY trap. All cleared a casual
"IS lift looks great" eyeball test and reversed sign OOS:

| feature | value | IS lift | OOS lift | reading |
|---------|-------|---------|----------|---------|
| macro_window | M3 (10:00-10:15) | +3.7pp | −4.3pp | "10am macro" was a 2018-23 phenomenon |
| entry_bucket | D_10:00-10:15 | +3.7pp | −4.3pp | same as above |
| prior_day_type | trend_up | +4.7pp | −3.3pp | trend-day continuation has decayed |
| pdr_position | above_pdh | +3.5pp | −0.8pp | "trading above PDH" used to help, no longer |
| is_month_start | True | +3.2pp | −2.9pp | first-of-month bias has flipped |

**If you'd built a playbook on the 2018-23 data alone, you would have wired these
in.** Each had n_IS ≥ 300, multi-year stability through 2023, and clean IS lift.
The IS→OOS double-cross is the only thing that catches them. *Never trust an
IS-only edge.*

---

## 10. What didn't move the needle

The following feature groups produced **no surviving cells** in either direction
(lift was within ±2pp on both eras, or one era flipped and the other didn't):

- VIXY regime — every level (low/normal/elevated/high) shows era-dependent lift.
  Today's lesson confirmed: not a stable filter on 8 years.
- Day-of-week — Monday/Friday slightly worse, but each year tells a different story.
- Calendar event flags — `is_fomc_week`, `is_opex_week`, `has_red_folder_news`,
  `is_month_end`. All within ±1.5pp on both eras.
- OR break states (5/15/45min) — `above`, `below`, `inside` all near base rate.
- ATH distance — `gt_500` and `200-500` slightly weaker, `lt_50` slightly stronger,
  but neither survives IS+OOS at lift≥3pp.
- HTF FVG confluence count — buckets sit within ±1.5pp.
- Match-direction features (`match_on_dir`, `match_930_dir`, `match_gap_dir`) —
  surprisingly flat. Trading "with the gap" or "with the 9:30 candle" doesn't
  predict 2R.

The absence of these effects is itself a finding — the *level structure ahead*
matters more than the macro context around the trade.

---

## 11. Recommended actions

1. **Implement the negative filter** as a soft veto: when `n_targets_in_dir == 0`,
   the trade has a 33% hit_2R prior. Either skip outright or downsize. This is
   the single biggest free-money item in the study (878 trades, −9pp drag).

2. **Use `n_targets_in_dir == 2` as a "preferred" tag** on signals — those trades
   hit 2R at 49% vs 42% baseline. Especially strong on `bos` and `protected_swing`
   variants (>52% combined).

3. **Use the composite (n_targets==2 & range!=contraction & gap==large_up) as an
   A+ flag** for pre-market briefings: when the day's gap_up is ≥25pts AND
   today's range is shaping up normal/expansion AND a signal happens to land
   with exactly 2 levels in its direction 0.5-3R away → expect ~55-60% hit_2R.

4. **Out-of-sample-validate quarterly.** The 5pp era drift between IS and OOS
   base rates says the world changes; today's strict survivors should be
   re-tested every 6-12 months against fresh data.

5. **What NOT to do.** Don't add `macro_window=M3`, `prior_day_type=trend_up`,
   `pdr_position=above_pdh`, or `is_month_start` as filters. Each looked good
   in a 6-year IS window and reversed sign in OOS — exactly the kind of
   plausible-but-broken signal the VIXY result warned us about.

---

## Files

| file | purpose |
|------|---------|
| [run.py](run.py) | Reproducible pipeline |
| [results/feature_matrix.parquet](results/feature_matrix.parquet) | Per-trade engineered features (4,548 × 35) |
| [results/single_feature_ranked.csv](results/single_feature_ranked.csv) | All single-feature buckets, ranked |
| [results/survivors_strict.csv](results/survivors_strict.csv) | Strict survivors (the 2 single features) |
| [results/survivors_loose.csv](results/survivors_loose.csv) | Wider pool for stack search |
| [results/anti_survivors.csv](results/anti_survivors.csv) | Negative filters |
| [results/variant_survivors.csv](results/variant_survivors.csv) | Per-variant survivors |
| [results/stack_2feat.csv](results/stack_2feat.csv) | 2-feature stacks |
| [results/stack_3feat.csv](results/stack_3feat.csv) | 3-feature stacks |
| [results/top_filters_yearly_rate.csv](results/top_filters_yearly_rate.csv) | Year-by-year hit_2R for top filters |
| [results/top_filters_yearly_n.csv](results/top_filters_yearly_n.csv) | Year-by-year sample sizes |
| [results/survivors_yearly.csv](results/survivors_yearly.csv) | Year-by-year for strict survivors |
