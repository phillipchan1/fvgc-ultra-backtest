# 9:30 Candle Anatomy — Findings

## Causal Audit Status

**REVALIDATED (core) — 2026-05-21.** The `range_z ≤ -1 → +7.1pp OOS hit_2R` finding uses the 9:30 candle's own range — known at 9:31. The only material caveat is that entries at 9:30 sharp (mod=570) cannot legally see candle_930 features; this denominator-shrink is small in practice.

**The `VP × rule → 65.4% hit_2R OOS (n=104)` cross-cell is CONTAMINATED** (today-VP join). Use only the pure range_z signal.

---

**Question.** Does the *shape* of the 9:30 RTH open candle (body/range
ratio, wick direction, close position, relative size, hammer/star/doji
flags) predict FVGC trade quality?

**TL;DR.** Most shape features are folklore on this data. Body-direction
match × decisiveness, close-position, wicks, doji/marubozu/hammer flags
— all noise. **One feature survives walk-forward: `range_z ≤ -1`** (the
9:30 candle is anomalously *small* vs its trailing 20-day mean). IS
lift +5.8pp on hit_2R, OOS lift +7.1pp, 7/9 positive years. The signal
adds genuine lift on top of `n_vp_targets >= 1`: stack OOS hit_2R 65.4%
(n=104) vs VP-only 55.8% (n=1,165). **Caveat:** `range_z` is structurally
close to a "range regime" / volatility indicator; it may be re-discovering
the known low-volatility-favors-continuation effect rather than anything
about the candle's *shape*. Treat as a confluence multiplier on top of
VP, not a standalone filter.

---

## Setup
- N trades: 4,548 non-skip (IS 2018-22 = 2,193, OOS 2023-26 = 2,355).
- Base hit_2R: 0.422.
- 9:30 OHLC reconstructed from 1m bars (trading_days.csv only stores
  range/body/direction).
- Features derived: body_range_ratio, upper/lower wick %, close_pos,
  range_z (20-day rolling z-score of range), is_doji, is_marubozu,
  is_hammer, is_shooting_star.

## Q2 — Single-feature scan
Top OOS cells, n≥100, signed lift vs rest:

| Feature | Bucket | n_OOS | p_hit_2R | lift_pp |
|---|---|---|---|---|
| `range_z` | (-∞, -1.0] | 211 | 0.507 | **+7.1** |
| `close_pos` | [0, 0.2] | 654 | 0.480 | +5.2 |
| `close_pos` | (0.4, 0.6] | 287 | 0.390 | -5.9 |
| `body_range_ratio` | (0.2, 0.4] | 421 | 0.401 | -5.0 |
| `close_pos` | (0.8, 1.0] | 564 | 0.413 | -3.9 |
| `is_doji` | True | 192 | 0.474 | +3.4 |

Most flags (`is_hammer`, `is_shooting_star`, `is_marubozu`) showed no
material lift. `is_doji` was modestly positive OOS but did not survive
the walk-forward (it was *negative* in IS).

## Q3 — Direction match × decisiveness
| split | match | shape | n | p_hit_2R |
|---|---|---|---|---|
| OOS | match | decisive | 632 | 0.470 |
| OOS | match | absorption | 341 | 0.413 |
| OOS | opposed | decisive | 380 | 0.411 |
| OOS | opposed | absorption | 275 | 0.422 |

There's a *mild* preference for direction-matched + decisive candles
(47.0% vs ~41-45% elsewhere OOS) but the IS counterpart did not
replicate (IS match+decisive = 38.2%, worse than IS match+mid = 42.8%).
**Inconclusive — fails the IS/OOS cross-check.**

## Q4 — Backward: what did winners' 9:30 candle look like?
Comparing mean shape features of hit_2R vs non-hits:

| split | cohort | body/range | close_pos | range_z |
|---|---|---|---|---|
| IS | hit_2R | 0.447 | 0.560 | +0.258 |
| IS | no_hit_2R | 0.453 | 0.570 | +0.277 |
| OOS | hit_2R | 0.517 | 0.464 | **+0.126** |
| OOS | no_hit_2R | 0.507 | 0.496 | **+0.210** |

The only consistent backward signal is that winners came on days with
*lower* range_z (i.e., quieter 9:30 candles). This corroborates the
forward Q2/Q5 finding.

## Q5 — Walk-forward (frozen rule)
IS-picked best rule: `range_z ∈ (-5, -1]`, n_IS=203, IS lift +5.82pp.
**OOS frozen: n=211, p_hit_2R=0.507, lift +7.10pp.** Single rule
survives both legs. All other candidates either flip sign IS→OOS
(upper_wick_pct ≥ 0.5, body_range_ratio ∈ (0.2,0.4]) or have smaller
margins.

## Year-by-year stability for `range_z ≤ -1`
| year | n_cohort | p_hit_2R_cohort | p_hit_2R_rest | lift_pp | + |
|---|---|---|---|---|---|
| 2018 | 14 | 0.429 | 0.429 | 0.0 | False |
| 2019 | 8 | 0.500 | 0.279 | +22.1 | True |
| 2020 | 42 | 0.429 | 0.388 | +4.0 | True |
| 2021 | 36 | 0.528 | 0.384 | +14.4 | True |
| 2022 | 103 | 0.437 | 0.411 | +2.6 | True |
| 2023 | 51 | 0.549 | 0.395 | +15.4 | True |
| 2024 | 58 | 0.552 | 0.426 | +12.6 | True |
| 2025 | 64 | 0.422 | 0.480 | -5.8 | **False** |
| 2026 | 38 | 0.526 | 0.424 | +10.2 | True |

**7/9 positive (passes ≥7/9 bar).** 2018 was a no-op (lift 0), 2025
flipped. 2025 is the only year where the rule actively hurt — worth
flagging but not enough to kill.

## Q6 — Stack with `n_vp_targets >= 1`
| split | cohort | n | p_hit_2R | p_hit_3R |
|---|---|---|---|---|
| OOS | baseline | 2,355 | 0.442 | 0.378 |
| OOS | has_vp | 1,165 | 0.558 | 0.484 |
| OOS | rule_pass | 211 | 0.507 | 0.408 |
| OOS | has_vp AND rule | **104** | **0.654** | **0.519** |
| OOS | has_vp AND ~rule | 1,061 | 0.549 | 0.481 |
| OOS | ~has_vp AND rule | 107 | 0.364 | 0.299 |

This is the most interesting finding. The rule **lifts the VP cell
from 55.8% → 65.4% on hit_2R** (+9.6pp, n=104 OOS) and from 48.4% →
51.9% on hit_3R. But the rule on its own *without* VP confluence is
*worse* than baseline (36.4%). Read: small-9:30 + VP target nearby is
A+; small-9:30 by itself is not a usable filter.

## Q1+Q6 interpretation
The "decisive open = continuation" / "absorption open = reversal" folk
hypothesis does **not** hold up. Body/range, wicks, close position,
hammer/star flags are all noise. The one survivor is *range size*,
which is a known volatility-regime fact more than a candle-shape fact.

## Caveats / kill criteria
- **Multiple-comparison risk:** ~30 candidate buckets across 6 features
  + 4 flags. At p=0.05 nominal we'd expect a handful of false positives.
  Only `range_z ≤ -1` survived both IS lift *and* OOS lift *and* 7/9
  years — that's a high bar, but not bulletproof.
- **range_z proxy for known regime:** the prior `vixy_regime` / `range`
  bucketing studies likely capture overlapping information. The lift
  on top of the VP cell suggests *some* independent contribution, but
  this should be validated against vixy_regime/prior_day_range_atr_ratio
  to confirm it isn't redundant. (Not done in this study; flagged for
  follow-up.)
- **2025 flipped negative** (-5.8pp). 2018 was no-op (n=14). The rule
  has a small-sample year-to-year variance problem because n_cohort is
  typically 30-100/yr.
- **Direction-match interaction was inconclusive** (mild OOS, opposite
  IS). Don't lean on it.

## Recommendation
1. **Use `range_z(9:30) ≤ -1` as a confluence multiplier on the VP cell.**
   When `n_vp_targets >= 1` AND 9:30 range_z ≤ -1, OOS hit_2R is 65.4%
   (n=104, p_hit_3R 51.9%). Treat as an "A+ entry" tier.
2. **Do not use 9:30 candle direction-match or shape flags as standalone
   filters.** They are folklore on this dataset.
3. **Follow-up:** confirm `range_z` is not redundant with `vixy_regime`
   or `prior_day_range_atr_ratio`. If it adds independent information,
   integrate into the playbook scoring sheet. If not, drop in favor of
   the existing regime feature.
4. **Kill candidate features:** is_marubozu (-4.4pp IS, -0.9pp OOS),
   close_pos middle (-5.6 IS, -5.9 OOS — these aren't filters, they're
   bad cells; the absence of them is a non-rule), body_range_ratio
   extremes (both flipped).
