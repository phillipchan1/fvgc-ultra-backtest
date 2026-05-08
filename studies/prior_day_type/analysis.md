# Study: Day-After-Trend-Day Pattern (Prior Day Type)

## Question

Does yesterday's RTH session character (trend / range / reversal) predict
today's W1/W2/W3 FVGC trade outcomes? Specifically, does adding
`prior_day_type` as a confluence factor lift WR/PF on existing playbook
plays (W1 Short, M2+M3 Long, IFVG Long)?

## Methodology

1. Built a rules-based 6-way classifier (`trend_up`, `trend_down`, `range`,
   `reversal_up`, `reversal_down`, `other`) over each fully-closed RTH
   session in [`data/trading_days/trading_days.csv`](../../data/trading_days/trading_days.csv).
   The classifier is look-ahead clean by construction (it only references
   the prior, fully-closed day).
2. Joined trades from [`logs/baseline_trades.csv`](../../logs/baseline_trades.csv)
   to the daily features and tagged each trade with `prior_day_type` plus
   support fields (`prior_day_range_atr_ratio`,
   `prior_day_directional_changes`, `prior_day_close_vs_open_pct`).
3. Aggregated WR / PF by:
   - `prior_day_type`
   - `prior_day_type x direction x macro_window` (the headline cells)
   - failure-mode cohorts: Monday rows, top-20%-magnitude gap days,
     prior-day red-folder news days.
4. Ran the combo permutation framework (10,000 perms, BH FDR q=0.10,
   min n=30) with new `prior_trend_up / prior_trend_down / prior_range /
   prior_reversal_up / prior_reversal_down` masks added to the standard
   factor set in [`analysis/combo_permutation_test.py`](../../analysis/combo_permutation_test.py).
5. Stacked `prior_day_type` onto three approximated existing playbook
   cohorts (W1 Short, M2+M3 Long, IFVG Long) and reported the WR/PF
   delta.

### Bar resolution caveat

The Notion brief assumed a 30s baseline trade log
(`logs/baseline_trades.csv`, 1,572 tradeable trades, 51.7% baseline WR).
That file was missing locally and a fresh 30s baseline did not finish
within an acceptable window during this run. The study uses the
already-available 1m baseline from
[`studies/baseline_1m/results/trades.csv`](../../studies/baseline_1m/results/trades.csv)
instead (copied in to `logs/baseline_trades.csv`). After the
trading_days join, that yields 766 tradeable trades over the same date
range (Oct 2023 – Mar 2026) at a 49.6% baseline WR. The 1m sample is
~49% of the 30s sample size, so cell-level statistical power is lower
than what the Notion plan anticipates. Re-running on the 30s baseline
once it is regenerated should at minimum confirm the directional
findings below.

### Classifier thresholds

The Notion v1 thresholds left ~77% of NQ RTH sessions classified as
`other`. Per the Notion guidance ("if 'other' > 40%, loosen thresholds
and re-run"), the thresholds were loosened in two passes to bring
`other` below 40%. The final thresholds in
[`build_trading_days.py`](../../data/trading_days/build_trading_days.py)
are:

| Category    | Notion v1                                              | Final                                                  |
|-------------|--------------------------------------------------------|--------------------------------------------------------|
| TREND_*     | range_ratio > 1.30, body_ratio > 0.70, dir_changes ≤ 4 | range_ratio > 1.10, body_ratio > 0.50, dir_changes ≤ 8 |
| RANGE       | range_ratio < 0.80, body_ratio < 0.30, close_pos 0.30–0.70 | range_ratio < 1.00, body_ratio < 0.45, close_pos 0.25–0.75 |
| REVERSAL_*  | drawdown/drawup ratio > 0.50                            | drawdown/drawup ratio > 0.30                            |

`directional_changes_30m` is the count of close-to-close sign flips
across the 13 RTH 30-minute closes. `prior_day_range_atr_ratio` uses a
20-day rolling average of `rth_range`, shifted by one day so the
classification is causal. The drawdown/drawup is measured from the RTH
open (`min(low - open)` and `max(high - open)`).

Final per-day distribution (1,393 RTH days, 2020-09-28 → 2026-02-20):

| prior_day_type | days | share |
|----------------|------|-------|
| other          |  508 | 36.5% |
| range          |  264 | 19.0% |
| reversal_up    |  196 | 14.1% |
| trend_down     |  169 | 12.1% |
| trend_up       |  144 | 10.3% |
| reversal_down  |  112 |  8.0% |

Trade-side counts after joining to baseline trades (n=766):

| prior_day_type | trades |
|----------------|--------|
| other          |  295   |
| range          |  173   |
| reversal_up    |   81   |
| trend_down     |   79   |
| trend_up       |   71   |
| reversal_down  |   67   |

## Results

### Aggregate WR / PF by `prior_day_type`

Source: [`results/summary_by_prior_day_type.csv`](results/summary_by_prior_day_type.csv).
Baseline: WR=49.6%, PF=1.00.

| prior_day_type | n   | WR     | WR lift   | PF    | PF lift |
|----------------|----:|-------:|----------:|------:|--------:|
| trend_down     |  79 | 59.5%  | **+9.9pp** | 1.43  | +0.44   |
| reversal_down  |  67 | 55.2%  | +5.6pp    | 1.45  | +0.46   |
| range          | 173 | 49.7%  | +0.1pp    | 1.08  | +0.08   |
| other          | 295 | 47.1%  | -2.5pp    | 0.85  | -0.15   |
| reversal_up    |  81 | 46.9%  | -2.7pp    | 0.88  | -0.11   |
| trend_up       |  71 | 46.5%  | -3.1pp    | 0.81  | -0.18   |

The split is directional and clean: the two "yesterday closed weak"
buckets (`trend_down`, `reversal_down`) produce above-baseline WR and
PF; the two "yesterday closed strong" buckets (`trend_up`,
`reversal_up`) produce below-baseline WR and PF. This is the inverse
of the most literal reading of the Notion hypothesis (which expected a
lift on `trend_up` followed by short reversals), but is consistent with
the broader Crabel/Raschke "day after a trend day, mean-revert" idea
once you account for direction: after a trend-up day the next-day FVGC
edge is *worse on average*, not better in either direction.

### Headline cells (prior_day_type × today direction × macro window)

Source: [`results/summary_by_prior_type_x_today_direction_x_macro.csv`](results/summary_by_prior_type_x_today_direction_x_macro.csv).
The strongest individual cells (small samples, treat as hypothesis-generating):

| prior_day_type | today dir | window | n  | WR     | PF    | WR lift  |
|----------------|-----------|-------:|---:|-------:|------:|---------:|
| trend_down     | short     | W1     | 14 | 85.7%  | 5.53  | +36.1pp  |
| reversal_down  | short     | W2     | 15 | 80.0%  | 6.21  | +30.4pp  |
| reversal_up    | short     | W1     | 13 | 76.9%  | 4.67  | +27.3pp  |
| reversal_up    | long      | W3     | 16 | 68.8%  | 2.86  | +19.1pp  |
| trend_down     | long      | W2     | 17 | 64.7%  | 1.74  | +15.1pp  |
| reversal_down  | short     | W3     | 11 | 63.6%  | 2.54  | +14.0pp  |

And the worst cells (avoid list):

| prior_day_type | today dir | window | n  | WR     | PF    |
|----------------|-----------|-------:|---:|-------:|------:|
| reversal_down  | long      | W1     |  5 | 20.0%  | 0.18  |
| range          | long      | W3     | 26 | 26.9%  | 0.38  |
| reversal_up    | short     | W3     | 13 | 30.8%  | 0.43  |
| trend_down     | long      | W1     |  6 | 33.3%  | 0.44  |
| reversal_up    | long      | W2     | 16 | 37.5%  | 0.64  |

### Combo permutation grid (10,000 perms, BH FDR q=0.10)

Source: [`results/combo_top_results.txt`](results/combo_top_results.txt),
[`results/combo_summary.csv`](results/combo_summary.csv).

- 2,015 combos tested (n ≥ 30), 565 of them include a `prior_day_*`
  factor.
- 257 combos significant at raw p < 0.05.
- **7 combos survive the BH FDR q=0.10 correction.** All seven also
  clear the WR ≥ 65% / PF ≥ 2.0 success threshold.
- Of those seven, only one references a prior-day factor — and it is
  `prior_day_down`, the **existing** `prior_day_close_position < 0.25`
  mask, not a new `prior_day_type` mask:

  ```
  prior_day_down + wide_45min_or                 n=40   WR=77.5%  PF=3.68  p_wr=0.0002 [FDR,PASS]
  ```

- The new `prior_day_type` masks (`prior_trend_up`, `prior_trend_down`,
  `prior_range`, `prior_reversal_up`, `prior_reversal_down`) produce
  several combos that pass raw p < 0.05 but **none** that survive BH
  FDR correction. The strongest:

  | combo                                                  | n  | WR    | PF   | p_wr   |
  |--------------------------------------------------------|---:|------:|-----:|-------:|
  | not_fomc_week + prior_reversal_down + short_only       | 30 | 70.0% | 3.50 | 0.0185 |
  | gap_up + prior_range + short_only                      | 48 | 68.8% | 2.33 | 0.0035 |
  | overnight_up + prior_range + short_only                | 44 | 68.2% | 2.31 | 0.0093 |
  | prior_range + wide_overnight                           | 32 | 68.8% | 2.28 | 0.0182 |
  | low_vixy + prior_range                                 | 34 | 67.6% | 2.17 | 0.0263 |
  | prior_reversal_down + short_only                       | 39 | 66.7% | 2.71 | 0.0227 |
  | no_pre_rth_news + prior_trend_down + short_only        | 36 | 66.7% | 2.24 | 0.0250 |

  These are directionally consistent with the aggregate finding
  (`reversal_down`, `trend_down` → short bias is strong; `prior_range`
  also tilts toward shorts under the right conditions) but cell n is
  small enough that BH FDR strips them out.

### Stacking onto existing playbook plays

Source: [`results/playbook_stack_lift.csv`](results/playbook_stack_lift.csv).
Note: the W1 Short / M2+M3 Long / IFVG Long cohorts here are
approximations defined inside the runner for self-contained reproducibility;
they are NOT the production confluence-model cohorts from the live
playbook (which use additional gates this study does not see). Treat
the deltas as directional, not authoritative replacements.

**W1 Short approximation** (macro_window==1 & direction=='short'):
baseline n=105, WR=57.1%, PF=1.42.

| stacked prior_day_type | n  | WR     | PF    | WR delta vs play |
|------------------------|---:|-------:|------:|-----------------:|
| trend_down             | 14 | 85.7%  | 5.53  | **+28.6pp**      |
| reversal_up            | 13 | 76.9%  | 4.67  | **+19.8pp**      |
| trend_up               | 12 | 50.0%  | 1.00  | -7.1pp           |
| range                  | 26 | 50.0%  | 1.26  | -7.1pp           |
| reversal_down          | 12 | 50.0%  | 1.22  | -7.1pp           |
| other                  | 28 | 46.4%  | 0.77  | -10.7pp          |

**M2+M3 Long approximation** (macro_window in [2,3] & direction=='long'):
baseline n=287, WR=47.0%, PF=0.86 (already underwater).

| stacked prior_day_type | n  | WR     | PF    | WR delta vs play |
|------------------------|---:|-------:|------:|-----------------:|
| trend_down             | 32 | 62.5%  | 1.36  | **+15.5pp**      |
| reversal_up            | 32 | 53.1%  | 1.25  | +6.1pp           |
| trend_up               | 22 | 40.9%  | 0.52  | -6.1pp           |
| range                  | 62 | 41.9%  | 0.71  | -5.1pp           |
| reversal_down          | 22 | 40.9%  | 0.72  | -6.1pp           |

**IFVG Long approximation**: sample (n=31) too small to draw conclusions.

### Failure-mode probes

Source: [`results/summary_prior_type_gap_monday_news.csv`](results/summary_prior_type_gap_monday_news.csv).

- **Monday matters for `trend_up`.** Trend-up Mondays (prior session was
  Friday) produce WR=26.7% (n=15) — i.e., a Friday trend-up degrades
  the next session's edge sharply. Trend-down does not show the same
  weekday sensitivity.
- **Big gaps amplify `trend_down` and crush everything else.**
  trend_down with a top-20%-magnitude gap: WR=76.5% (n=17). Same
  cohort with smaller gaps: WR=54.8% (n=62). Other categories are
  flat-to-worse on big-gap days.
- **Prior-day red-folder news distorts `trend_up`.** trend_up days
  driven by news (e.g., 8:30 CPI/NFP) flip the next-day edge: WR=68.4%
  (n=19) when the prior session was a red-folder day, vs 38.5% (n=52)
  when it was not. The mechanical-trend-up signal that the Notion brief
  worried about is real and large in this slice.

## Conclusions

1. **Hypothesis: partially supported, but weaker than the Notion
   prediction and not statistically significant after BH FDR
   correction.** No `prior_day_type` mask, on its own or in any 2-way /
   3-way combo, clears the primary success threshold (WR ≥ 65%,
   PF ≥ 2.0, n ≥ 30, BH-corrected p < 0.10). Several
   `prior_day_type` combos clear raw p < 0.05 with strong WR/PF
   (e.g., `prior_reversal_down + short_only`: WR=66.7%, PF=2.71, n=39),
   but BH FDR does not survive at q=0.10.

2. **Directional finding is real and useful as a confluence input.**
   When stacked on the (approximated) W1 Short cohort, a prior
   `trend_down` day raises WR from 57% to 86% (n=14, +29pp); a prior
   `reversal_up` day raises it to 77% (n=13, +20pp). When stacked on
   the (approximated) M2+M3 Long cohort, a prior `trend_down` day
   raises WR from 47% to 63% (n=32, +16pp). These exceed the secondary
   success threshold (≥5pp WR lift on at least one cohort), but cell
   sample sizes are small.

3. **Recommended next steps before promoting any play to the
   playbook:**
   1. Re-run on the 30s baseline to roughly double the per-cell n.
      This study used the 1m log because the 30s log was unavailable
      locally. The findings would also benefit from re-running the
      classifier with the v1 (strict) thresholds on the 30s sample —
      the loosening was driven entirely by `other > 40%` on the daily
      grid, not by trade-side power, and tighter buckets may produce
      larger per-bucket effect sizes (at the cost of more `other`).
   2. Investigate the **prior-day red-folder + trend_up** interaction
      explicitly. The 30pp WR swing inside `trend_up` based on news
      attribution is the single largest effect this study surfaced and
      may be a cleaner factor than `prior_day_type` itself.
   3. Stack `prior_trend_down` and `prior_reversal_down` onto the
      *production* W1 Short and M2+M3 Long cohorts (not the
      approximations used here) to confirm the WR lift before
      considering a Notion playbook entry.
   4. Treat `prior_day_type` as a **bias filter**, not a primary
      signal: include it in confluence stacks where direction lines up
      ("prior trend_down → tilt short", "prior trend_up → avoid long")
      rather than as a standalone trigger.

4. **Negative result worth recording: the `prior_day_close_position`
   factor that already exists in the trading_days schema captures most
   of the lift that the new `prior_day_type` masks deliver.** The one
   FDR-surviving prior-day combo (`prior_day_down + wide_45min_or`,
   WR=77.5%, PF=3.68, n=40) uses the existing
   `prior_day_close_position < 0.25` mask. The new `prior_day_type`
   masks do not yet earn their place in the standard factor set on
   strict statistics; they earn their place as confluence inputs on
   directional cohorts only.

## Outputs

All emitted to [`results/`](results/):

- [`trades_by_prior_day_type.csv`](results/trades_by_prior_day_type.csv)
  — one row per joined trade plus prior-day fields, used for
  downstream verification.
- [`summary_by_prior_day_type.csv`](results/summary_by_prior_day_type.csv)
  — aggregate WR/PF/lift per prior_day_type.
- [`summary_by_prior_type_x_today_direction_x_macro.csv`](results/summary_by_prior_type_x_today_direction_x_macro.csv)
  — the headline cell table.
- [`summary_prior_type_gap_monday_news.csv`](results/summary_prior_type_gap_monday_news.csv)
  — robustness probes for the failure modes called out in the Notion
  brief (Monday rows, large gap days, prior-day red-folder news days).
- [`playbook_stack_lift.csv`](results/playbook_stack_lift.csv) — WR/PF
  deltas when stacking each prior_day_type onto W1 Short / M2+M3 Long
  / IFVG Long cohorts.
- [`combo_summary.csv`](results/combo_summary.csv) — full combo
  permutation grid with BH FDR-corrected p-values.
- [`combo_top_results.txt`](results/combo_top_results.txt) — formatted
  ranking, plus a CLEARED-THRESHOLDS section for combos that pass the
  primary success bar.
- [`run.log`](results/run.log) — full stdout from the run.
