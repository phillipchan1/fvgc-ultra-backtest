# Multi-Day Composite Volume Profile Study

**Verdict: FAIL — single-day VP remains canonical.**

Composite POC/VAH/VAL over rolling 5-/10-/20-day windows is not a stronger
hit_2R signal than yesterday's single-day VP. The top "magnet" buckets become
structurally too rare to use, and OOS lift collapses (best composite −4.25pp
vs yesterday's −1.10pp — and both fail to beat their base rates).

Bonus finding: Phase A's published lift was inflated by look-ahead. The
`n_vp_targets` feature joined **today's** full-RTH VP (9:30-16:00) to trades
that entered in the first 45 min. When the join is made causal (yesterday's
VP), the +22pp IS lift collapses to **−3.19pp**. See "Lookahead audit" below.

## Methodology

### Composite construction (Q1)

`studies/composite_vp/build_composite_vp.py`. For each session `d` and window
`W ∈ {5, 10, 20}`:

1. Take all 30s RTH bars (9:30-16:00 ET) from the `W` trading days strictly
   preceding `d` (look-ahead-safe).
2. Run the same TPO-volume distribution that `fvgc/volume_profile.py` uses
   for single-day VP: each bar's volume is spread uniformly over the
   1-point buckets it spans; POC is the heaviest bucket; VA is grown
   outward from the POC until 70% of total composite volume is captured.

This is volume-weighted, not equal-day-weighted — high-volume sessions
contribute proportionally more. We chose volume-weighting because the
question is "where is multi-day price *acceptance* concentrated", which is
fundamentally a volume question.

Output: `results/composite_vp_levels.csv` (2,158 rows, 2018-01-02 → 2026-05-15).

VA-width grows with window length, as expected:

| Window | Mean VA-width | Median VA-width |
|--------|--------------:|----------------:|
| 5d     | 311.5 pts     | 258.0 pts       |
| 10d    | 454.9 pts     | 378.5 pts       |
| 20d    | 658.0 pts     | 556.5 pts       |

For reference, single-day VA-width is ~50-100 pts in this dataset.

### Splits

- **IS**: year ≤ 2022 (n=2,193 trades from baseline)
- **OOS**: year ≥ 2023 (n=2,355 trades)
- Bucket boundaries (0 / 1 / 2 / 3+) are STRUCTURAL, never tuned on OOS.

### Feature

For each trade, signed R-distance to each VP level
`r = (level − entry) / sl_dist` (sign-flipped for shorts). A level is "in
the target zone" if `r ∈ [0.5, 3.0]`. `n_vp_<window>` is the count of POC,
VAH, VAL that land in-zone for that trade.

## Q2/Q3 — Bucket lift per window

`results/hit_2R_by_window.csv`. Phase-A-style table (causal lag — yesterday's
VP joined to today's trade):

| Window | Bucket | n_IS | hit_2R_IS | lift_IS_pp | n_OOS | hit_2R_OOS | lift_OOS_pp |
|--------|--------|-----:|----------:|-----------:|------:|-----------:|------------:|
| 1d     | 0      | 1499 | 40.6%     | +0.6       | 1586  | 44.2%      | −0.05       |
| 1d     | 1      |  542 | 39.3%     | −0.7       |  572  | 44.8%      | +0.5        |
| 1d     | 2      |  142 | 36.6%     | −3.4       |  182  | 44.5%      | +0.3        |
| 1d     | 3+     |   10 | 40.0%     | −0.0       |   15  | 26.7%      | −17.6       |
| 5d     | 0      | 1684 | 40.7%     | +0.7       | 1784  | 44.4%      | +0.15       |
| 5d     | 1      |  498 | 37.4%     | −2.7       |  541  | 44.0%      | −0.25       |
| 5d     | 2      |   11 | 54.5%     | +14.5      |   30  | 40.0%      | −4.25       |
| 5d     | 3+     |    0 | —         | —          |    0  | —          | —           |
| 10d    | 0      | 1828 | 40.8%     | +0.8       | 1950  | 43.7%      | −0.50       |
| 10d    | 1      |  361 | 36.3%     | −3.7       |  397  | 46.4%      | +2.1        |
| 10d    | 2      |    4 | 25.0%     | −15.0      |    8  | 62.5%      | +18.3       |
| 10d    | 3+     |    0 | —         | —          |    0  | —          | —           |
| 20d    | 0      | 1930 | 40.4%     | +0.3       | 1996  | 44.4%      | +0.19       |
| 20d    | 1      |  261 | 37.9%     | −2.1       |  358  | 43.3%      | −0.95       |
| 20d    | 2      |    2 | 0.0%      | −40.0      |    1  | 0.0%       | −44.2       |
| 20d    | 3+     |    0 | —         | —          |    0  | —          | —           |

Two structural points:

1. **The 3+ bucket vanishes for every composite window.** Because the
   composite VA is much wider than single-day, the three levels rarely cluster
   tightly enough to all fall inside a single 2.5R window above entry. Even
   the 2-bucket has only 11-30 trades — too few to call a signal.

2. **No composite shows monotone lift** across 0 → 1 → 2 → 3+ on IS
   (`IS_mono_increasing = False` for every window). Phase A's headline
   monotonicity disappears the moment we either lag VP causally or aggregate
   across days.

## Q3 (continued) — vs yesterday's VP

`results/vs_yesterday.csv` (top-bucket `n_vp ≥ 2`):

| Window | IS_n | IS_hit_2R | IS_lift_pp | mono | yrs_pos | OOS_n | OOS_hit_2R | OOS_lift_pp |
|--------|-----:|----------:|-----------:|:----:|:-------:|------:|-----------:|------------:|
| 1d     | 152  | 36.8%     | **−3.19**  | ✗    | 2/5     | 197   | 43.1%      | **−1.10**   |
| 5d     |  11  | 54.5%     | +14.51     | ✗    | 3/4     |  30   | 40.0%      | −4.25       |
| 10d    |   4  | 25.0%     | −15.04     | ✗    | 1/3     |   8   | 62.5%      | +18.25      |
| 20d    |   2  |  0.0%     | −40.04     | ✗    | 0/1     |   1   |  0.0%      | −44.25      |

IS window selection picks 5d (highest IS top-bucket lift +14.51pp). OOS
result: 5d top-bucket only n=30 with −4.25pp lift. The 10d result (+18pp
OOS) is on n=8, not actionable.

**Δ(best composite − yesterday) OOS lift = −3.15pp** vs. the +3pp floor
required → composite formulation rejected.

## Q4 — Additivity

`results/additivity.csv` (2×2 cells of `n_vp_1d ≥ 2` × `n_vp_5d ≥ 2`):

| Cell                       | n_IS | hit_2R_IS | lift_IS_pp | n_OOS | hit_2R_OOS | lift_OOS_pp |
|----------------------------|-----:|----------:|-----------:|------:|-----------:|------------:|
| y_lo × c_lo                | 2033 | 40.2%     | +0.15      | 2141  | 44.3%      | +0.03       |
| y_lo (0-1) × c_hi (≥2)     |    8 | 62.5%     | +22.46     |   17  | 52.9%      | +8.69       |
| y_hi (≥2) × c_lo (0-1)     |  149 | 36.9%     | −3.12      |  184  | 44.6%      | +0.32       |
| y_hi (≥2) × c_hi (≥2)      |    3 | 33.3%     | −6.70      |   13  | 23.1%      | −21.17      |

The `y_lo × c_hi` cell shows promise on IS (+22pp on n=8) and survives OOS
(+8.7pp on n=17), but the **n=17 OOS sample is far too thin** to ship as a
playbook entry. Worth a follow-up if a larger ruleset is built.

## Q5 — DoW stability

`results/dow_stability.csv` (top-bucket `n_vp_5d ≥ 2`):

| DoW | n_top | top_hit_2R | lift_pp |
|-----|------:|-----------:|--------:|
| Mon |     7 | 28.6%      | −13.45  |
| Tue |     8 | 62.5%      | +20.65  |
| Wed |    11 | 45.5%      | +4.34   |
| Thu |     5 | 40.0%      | −3.34   |
| Fri |    10 | 40.0%      | −2.69   |

The Monday weakness hypothesis (weekend-spanning composite) is
*directionally* supported but sample sizes are too small for confidence.
Tue/Wed/Thu/Fri don't show a clean clean-day premium either.

## Q6 — Walk-forward summary

| Metric                       | Value         |
|------------------------------|---------------|
| IS window selected           | 5d            |
| 5d IS top-bucket lift        | +14.51pp (n=11) |
| 5d OOS top-bucket lift       | −4.25pp (n=30)  |
| Yesterday OOS top-bucket lift| −1.10pp (n=197) |
| Delta vs yesterday OOS       | −3.15pp         |
| Kill floor                   | +3.00pp         |
| **Verdict**                  | **FAIL**        |

## Lookahead audit — Phase A revisited

The parent Phase A study joined `daily_volume_profile.csv` on `date`, which
gives each trade today's full-RTH (9:30-16:00) POC/VAH/VAL — i.e. data from
hours that hadn't happened yet at entry time. Re-running the same bucket
table with that join reproduces Phase A's headline:

| Bucket | IS hit_2R | IS lift | OOS hit_2R | OOS lift |
|--------|----------:|--------:|-----------:|---------:|
| 0      | 28.2%     | −11.9pp | 32.9%      | −11.3pp  |
| 1      | 49.4%     | +9.3pp  | 53.5%      | +9.2pp   |
| 2      | 62.1%     | +22.1pp | 62.0%      | +17.8pp  |
| 3+     | 87.5%     | +47.5pp | 94.1%      | +49.9pp  |

The lift is monotone and very large — but this is because the feature is
literally answering "did today's value area end up containing the trade's
trajectory", which is a near-tautological proxy for "did this trade hit 2R."
When the join is made causal (yesterday's VP), every bucket collapses to
±1pp of base.

This does **not** invalidate yesterday's VP as a feature for live use — a
trader on day `d` has access to `d-1`'s VP and can use it. But it means the
**Phase A "PASS" verdict and the magnitudes in memory `project_vp_targets.md`
overstate the edge** by a wide margin. Two implications:

1. The `n_vp ≥ 2` "A+ cell" in the playbook should be benchmarked against
   the lag-1 numbers (−3pp IS / −1pp OOS), not Phase A's reported +18pp.
2. A real live-usable analogue would be a **partial-day VP** (RTH volume
   accumulated only up to entry time, ~9:30-9:45/10:00/10:15). That's a
   different feature than either of the two tested here. A follow-up study
   should re-run the bucket analysis against a partial-day VP joined at the
   trade's exact entry timestamp.

## Files

- `build_composite_vp.py` — composite VP construction (volume-weighted, causal).
- `run.py` — bucket analysis, walk-forward, additivity, DoW.
- `results/composite_vp_levels.csv` — per-day composite POC/VAH/VAL for W=5,10,20.
- `results/hit_2R_by_window.csv` — bucket × window table.
- `results/vs_yesterday.csv` — top-bucket comparison.
- `results/additivity.csv` — composite × yesterday cells.
- `results/dow_stability.csv` — DoW lift for best composite.
- `results/year_by_year.csv` — annual hit_2R for best composite top bucket.

## Conclusion

Composite VP is rejected as a stronger alternative to yesterday's single-day
VP. The path forward is **partial-day VP** (causal, accumulated through
entry time), which is materially different from both formulations tested
here and may explain the Phase A signal without the lookahead.
