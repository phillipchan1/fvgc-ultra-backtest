# Path A — Re-discover High-WR Filters Using Causal Features Only

## Verdict

**Effectively null result.** Out of 278 (feature, bucket) cells tested under
strict causal feature load (IS 2018-22 / OOS 2023-26, ±3pp double-cross,
n≥50 both eras, 7/9 year-stability), **1 positive survivor and 1 anti-survivor**
emerge. Both are marginal, mechanism-unclear, and arguably attributable to
multiple-comparison residual.

| Side       | Feature                     | Bucket  | Lift IS / OOS    | n IS / OOS  | Years pos/neg |
|------------|-----------------------------|---------|------------------|-------------|---------------|
| Survivor   | `month_name`                | October | +8.5pp / +8.0pp  | 233 / 175   | 7/8 active    |
| Anti-surv. | `abs_dist_london_low_R`     | Q2      | −3.3pp / −3.6pp  | 548 / 536   | 7/9           |

**Recommendation.** Path B (deepen the surviving studies — Turtle Soup v0.3,
IFVG Reversal Tempo v0.3.1, UFVG First-Touch, Morning Narrative v1) is the
higher-EV next move. October seasonality is worth tracking as a contextual
prior, not a filter rule. The anti-survivor is non-monotonic across quartiles
and likely an artifact.

## Control test results (Phase A2)

All three controls passed — pipeline produced no survivor-grade fake cells.

| Control                                       | Style          | Worst |lift_is| | Worst |lift_oos| | Verdict |
|-----------------------------------------------|----------------|------------------|-------------------|---------|
| `is_fomc_week`                                | structural-null| ~1pp             | ~1pp              | PASS    |
| `day_of_week_name == 'Tuesday'`               | structural-null| ~1pp             | ~1pp              | PASS    |
| Label-shuffle on `prior_day_range_atr_ratio`  | shuffle-null   | ~2.2pp (1σ noise)| ~2.5pp            | PASS    |

Gate definition (after [user clarification](/Users/philchan/.claude/plans/path-a-re-discover-high-wr-sunny-moore.md)): a control fails only if it produces a cell clearing the same
survivor criteria as the main scan (lift ≥+3pp BOTH eras, n≥50 both). Single-era
2pp lifts on a 4-bucket quartile split are within 1σ sampling noise (SE ≈ 2.1pp
at n≈547 per bucket) and are not a failure signal. Raw output in [results/control_test.csv](results/control_test.csv).

## Methodology

- **Universe.** [logs/baseline_trades.csv](../../logs/baseline_trades.csv), filtered to `outcome != 'skip'` → 4,548 trades.
- **Target.** `outcome == 'win'` (binary). Overall WR = 49.4% (IS=47.3%, OOS=51.4%).
- **Walk-forward.** IS = 2018-2022 (n=2,193), OOS = 2023-2026-05 (n=2,355). All thresholds and quartile cut points are derived from IS only.
- **Causal feature load.** All day-level joins go through [tools/causal_features.py](../../tools/causal_features.py): `add_trade_level_features` + `load_causal_features` + `load_lagged_vp` + `load_session_levels`. Gated features are NaN-masked for trades whose `mod < gate`. Forbidden columns (`rth_close|high|low|range`, `directional_changes_30m`, `max_drawdown_from_open`, `max_drawup_from_open`) are structurally refused. No `daily_volume_profile.csv` join on `date` — only via `load_lagged_vp`.
- **Conditional baselines.** Each feature's lift is computed against the WR of the SUBSET where the feature is non-null in that era (not the global 49.4%). This removes the time-of-day bias on gated features (a feature only available post-10:15 is judged against trades that fire post-10:15).
- **Bucketing.** Categorical → each value; small-int counts → {0,1,2,3+}; numeric → IS-quartile cuts (frozen on IS, applied to OOS).
- **Survivor criteria.** lift_is ≥ +3pp AND lift_oos ≥ +3pp AND min(n_is, n_oos) ≥ 50 AND positive lift in ≥7 of 9 calendar years.
- **Anti-survivor criteria.** Symmetric with sign flipped.
- **88 features → 278 cells** tested (after dropping degenerate quartile splits): 39 categorical + 10 small-int + 39 numeric.

## Phase A1 — Survivors

### Survivor: `month_name == October`

- **IS (2018-2022):** n=233, WR=55.79% vs subset baseline 47.29% → +8.51pp
- **OOS (2023-2026):** n=175, WR=59.43% vs subset baseline 51.42% → +8.01pp
- **Year-by-year** ([results/yearly_stability.csv](results/yearly_stability.csv)):

| Year | n  | WR     | Baseline WR | Lift pp |
|------|----|--------|-------------|---------|
| 2018 | 34 | 44.12% | 49.69%      | **−5.57** |
| 2019 | 6  | 50.00% | 43.48%      | +6.52    |
| 2020 | 60 | 63.33% | 46.02%      | +17.32   |
| 2021 | 52 | 57.69% | 48.29%      | +9.40    |
| 2022 | 81 | 54.32% | 47.32%      | +7.00    |
| 2023 | 62 | 51.61% | 49.74%      | +1.87    |
| 2024 | 42 | 69.05% | 50.53%      | +18.51   |
| 2025 | 71 | 60.56% | 54.64%      | +5.93    |
| 2026 | 0  | —      | —           | —        |

Positive in 7 of 8 active years (2026 has no October data — only May).

**Adversarial check — what would have to be true for this to be wrong?**

1. **Multiple-comparison residual.** 12 month buckets tested. Under H0, P(observing best-of-12 with lift this large) is non-trivial. Naive binomial on 7/8 positive years: P(≥7|p=0.5) = 9/256 ≈ 3.5%; Bonferroni for 12 = ~42%. That's not survivable. But the *magnitude*: z-score on the IS+OOS pooled lift is ≈ 4.0 (n=408 pooled, SE≈2.5pp on +8pp); Bonferroni-12 p < 0.001. Magnitude survives, year-stability alone does not.
2. **Selection on the most volatile month.** October historically has elevated realized vol (1987, 2008, 2018 selloffs, 2020 recovery, 2022 bear-bounce). FVGC is intraday — higher RTH range = more reach = more 1R hits. This is plausible. But that mechanism should also show up in `prior_day_range_atr_ratio` or `overnight_range_R` — and neither cleared the threshold.
3. **2026 missing entirely.** The "8/9 active" claim is fragile: by Oct 2026 the lift could regress to mean. Only 3 full-OOS Octobers observed.
4. **Adjacent month (November) cleared lift+n but failed year-stability** (positive 5/9 years). If October is real, November should partly co-move. It doesn't — argues against a stable "Q4 seasonality" story and for an October-specific outlier.

**Verdict:** statistically survives strict criteria, mechanism unclear, practical
edge is ~50 trades/year so small absolute PnL contribution. **Track as a
contextual prior; do not codify as a filter rule.**

## Phase A4 — Anti-survivor

### Anti-survivor: `abs_dist_london_low_R == Q2`

- Bucket Q2 = entry is 1.46-2.92 R-units (sl_dist) from London session low.
- **IS:** n=548, WR=43.98% vs 47.29% → −3.31pp
- **OOS:** n=536, WR=47.76% vs 51.42% → −3.62pp
- **Year-by-year:** negative in 7 of 9 years (2018 marginal +1.6pp, 2025 marginal +0.8pp; the other 7 years are −2 to −9pp).

| Year | n   | WR     | Baseline WR | Lift pp |
|------|-----|--------|-------------|---------|
| 2018 | 39  | 51.28% | 49.69%      | +1.59   |
| 2019 | 21  | 38.10% | 43.48%      | −5.38   |
| 2020 | 148 | 41.22% | 46.02%      | −4.80   |
| 2021 | 152 | 46.05% | 48.29%      | −2.24   |
| 2022 | 188 | 43.62% | 47.32%      | −3.71   |
| 2023 | 139 | 43.88% | 49.74%      | −5.86   |
| 2024 | 158 | 44.94% | 50.53%      | −5.60   |
| 2025 | 186 | 55.38% | 54.53%      | +0.84   |
| 2026 | 53  | 39.62% | 48.48%      | −8.85   |

**Adversarial check:**

1. **Non-monotonic in quartiles.** Q1 (entry close to London low, ≤1.46R) shows
   +1.7pp IS lift. Q3 and Q4 (further out) are flat. **Only Q2 is bad.** A real
   level-distance effect should be monotonic (closer = more reactive, or further
   = more freedom) — not "1.46-2.92R is uniquely cursed." This is suspicious.
2. **Correlated near-miss: `abs_dist_ssl_level_R` Q2** also clears anti-survivor
   lift (−3.7/−3.9pp). SSL (sell-side liquidity) is the same level family as
   London low on many days. Two anti-survivors that are largely the same
   underlying observation, not independent confirmation.
3. **Mechanism story (charitable).** Entries 1.5-3R from a major prior low are
   inside the "magnet zone": the level is close enough to attract sweeps but
   far enough that price has room to chop into it without triggering rotation.
   Plausible but ad-hoc.
4. **No clean playbook rule.** "Don't take entries 1.46-2.92R from London low"
   is not actionable without context. The Q2 cut points are IS-derived (R-units
   anchored on sl_dist quartiles) — they don't translate to a human-readable
   threshold like "don't trade within 2R of a swing low."

**Verdict:** marginal anti-edge, mechanism is non-monotonic in a way that does
not pattern-match a real effect. Flagged for future cross-check (does it
re-appear with different bucketing? Different level distance encoding?) but
**not playbook-grade**.

## Phase A3 — Stacks

**Not run.** Only 1 strict survivor; pairwise and triple stacks require ≥2 and
≥3 respectively. Output CSVs ([results/stacks_2feat.csv](results/stacks_2feat.csv),
[results/stacks_3feat.csv](results/stacks_3feat.csv)) are empty stubs.

## Near-misses worth noting (under strict, fail one criterion)

These cleared lift ≥+2pp both eras OR ≥-2pp both eras with n≥50 both, but did
not pass the strict +3pp or year-stability bar. Useful as residual signal for
follow-up studies, not as standalone rules.

### Positive near-misses

| Feature                                | Bucket      | IS lift | OOS lift | n IS / OOS | Note |
|----------------------------------------|-------------|---------|----------|------------|------|
| `entry_above_nwog_high`                | true        | +9.3pp  | +2.4pp   | 105 / 184  | OOS<3pp; large IS but small n. New-Week-Opening-Gap signal worth a follow-up. |
| `has_prior_win`                        | true        | +2.8pp  | +3.6pp   | 928 / 1147 | Just below +3pp IS. **Heat-streak effect** — earning a prior win on the same day correlates with +3pp WR on the next trade. Huge n. Worth deepening into a stand-alone "session momentum" study. |
| `prior_day_close_position` Q1          | (low close) | +2.2pp  | +4.5pp   | 550 / 404  | Prior close near LoD → next-day FVGC longs/shorts work slightly better. |
| `prior_day_type == reversal_up`        | —           | +3.4pp  | +3.2pp   | 302 / 311  | Cleared lift criterion but only 5/9 years positive → failed year-stability. |
| `month_name == November`               | —           | +5.0pp  | +3.1pp   | 172 / 143  | Cleared lift but 5/9 year-stability. Adjacent to October survivor — fail argues against generic "Q4 seasonality." |

### Negative near-misses

| Feature                       | Bucket | IS lift | OOS lift | n IS / OOS | Note |
|-------------------------------|--------|---------|----------|------------|------|
| `month_name == January`       | —      | −2.9pp  | −7.5pp   | 142 / 264  | Strongest seasonal negative. January FVGC consistently underperforms. |
| `is_opex_week`                | true   | −3.6pp  | −2.1pp   | 362 / 444  | OPEX week trades underperform. OOS lift below threshold but suggestive. |
| `macro_2_range_R` Q4 (large)  | —      | −2.3pp  | −4.8pp   | 187 / 223  | Large 10:00 macro range → lower subsequent WR. Gated post-10:00 trades only. |

## Kill criteria audit

| Criterion                                                                  | Triggered? | Notes |
|----------------------------------------------------------------------------|-----------|-------|
| No single-feature survivor at lift_oos ≥+5pp on n≥100                       | **YES** for one survivor (October +8.0pp OOS, n=175); but only one cell  | The brief said "report null result, recommend Path B" if zero. We have one marginal survivor with unclear mechanism. Recommending Path B anyway. |
| Control test produced a fake survivor                                       | No        | All 3 controls clean under survivor-grade gate. |
| All survivors fail year-by-year (positive in <6 of 9)                       | No        | October passes 7/8 active; anti-survivor passes 7/9. |

## Null-result section + Path B recommendation

The brief asked for either a meaningful filter or an explicit null + Path B
recommendation. We are closer to null than to a meaningful filter:

- **1 strict survivor** is roughly the expected base rate under H0 given 278
  tests with strict double-cross + year-stab gating.
- **The survivor's mechanism is not clean** (broad seasonality, not a tradeable
  state-of-the-market filter).
- **The anti-survivor is non-monotonic** in quartiles and partially redundant
  with a correlated feature — not the clean "skip-rule" the brief hoped for.
- **The near-misses (`has_prior_win`, `entry_above_nwog_high`, January under-
  performance) are the most interesting residual signals** — each deserves a
  dedicated focused study, but none would survive on its own under a multi-
  comparison-aware bar.

**Path B = deepen the studies that already survived audit.** Per [MEMORY.md](../../.claude/projects/-Users-philchan-Work-fvgc-backtest/memory/MEMORY.md):

- Turtle Soup v0.3 (Score 3+ = 73.2% WR n=56) — needs more sample; gather more reversal days.
- IFVG Reversal Tempo v0.3.1 (PF 1.69 N=4) — too small; expand the cohort.
- UFVG First-Touch (depth ≤50% = ~60% WR) — refine depth + add stack with IFVG.
- Morning Narrative v1 (bull PF 2.58, bear PF 1.55) — already actionable; instrument live.
- 9:30 Candle Anatomy (range_z≤-1 = +7.1pp) and HTF Nesting (nested_15m = +25.8pp) — these are the strongest survivors. Stack them with the trigger.

Single-feature mining of the 4,548-trade baseline has now been attempted twice
under causal load (this study + win_loss_discriminator v1). Both returned
near-null. The data has been thoroughly fingerprinted. **Further single-feature
search has diminishing returns; structural stacks of validated multi-feature
plays are the higher-EV move.**

## Reproducibility

```
# Tests
pytest tools/test_causal_features.py -v    # 25 passing

# Run
python studies/win_rate_discovery/run.py --controls-only    # gate
python studies/win_rate_discovery/run.py                    # full A1..A4
```

Outputs:
- [results/control_test.csv](results/control_test.csv)
- [results/single_feature_ranked.csv](results/single_feature_ranked.csv) (278 rows, score-sorted)
- [results/survivors_strict.csv](results/survivors_strict.csv)
- [results/anti_survivors.csv](results/anti_survivors.csv)
- [results/yearly_stability.csv](results/yearly_stability.csv)
- [results/stacks_2feat.csv](results/stacks_2feat.csv), [results/stacks_3feat.csv](results/stacks_3feat.csv) (empty stubs)
