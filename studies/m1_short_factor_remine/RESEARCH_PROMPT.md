# Agent Research Prompt: M1 Short Factor Stack Re-Mining (8-year)

**Owner:** Phil
**Author of prompt:** Claude (2026-05-18)
**Estimated effort:** 1-2 days of focused work for a competent analyst-agent

You are a quantitative research agent. Read this entire prompt before starting. Do not skip the methodology section — it bakes in lessons from a recent audit where a factor stack overfit a 3-year training window and dropped 20pp WR on out-of-sample data.

## 1. Context (read this first)

The **M1 Short Confluence Model** is an FVGC short-side play in the 9:30–9:45 NY window. The original 7-factor stack was mined on Oct 2023 – Mar 2026 (3 years) by `studies/multi_cell_confluence/` and claimed 68% WR IS / 77% WR OOS at the 2+ confluence tier.

A recent 8-year validation ([studies/m1_short_8yr_validation/REPORT.md](studies/m1_short_8yr_validation/REPORT.md)) re-tested the same stack on 2018-01 → 2026-05 data and found:
- 2+ tier WR: **56.1%** (was claimed 68-77%) — overfit confirmed
- PF @ 2R: **2.02** (was 2.44)
- Median MFE 1R+: **5.6R** (runner profile survived)
- Regime-robust at ~55-57% across bear/bull/neutral
- Worst year: 2020 at 33% WR (COVID — a regime the original never saw)

Two specific factors smell wrong:
- `is_fomc_week` is a +12pp **WR** confluence in the model, but a **-10pp fire-rate predictor** in the 8-year data. Contradiction — likely noise.
- `vixy_high` is a +10pp WR confluence but a -3.5pp fire-rate predictor — similar pattern.

A new candidate emerged from the predictability analysis: **OR 5-min range top-quartile (+12.8pp fire rate)** — untested for WR effect.

**Your job:** re-mine the factor stack on 8 years from scratch with rigorous OOS protocol. Produce a stack that holds up.

## 2. Goal

Build a **new factor stack of 4-6 factors** for the M1 Short play that satisfies ALL:
- 2+ tier WR ≥ 60% on 7-year training (2018-01 → 2024-12)
- 2+ tier WR ≥ 58% on 1.5-year OOS holdout (2025-01 → 2026-05)
- WR delta IS vs OOS ≤ 8pp (didn't overfit)
- WR variance across bear/bull/neutral ≤ 12pp (regime-robust)
- Each factor passes per-factor acceptance criteria (Section 5)
- Total trade count at 2+ tier ≥ 150 over 8 years (tradeable cadence)

If no stack achieves this, report so honestly — don't manufacture an edge that isn't there. Acceptable outcome: "the play is genuinely ~56% WR on the full sample and the original 68-77% claim was a regime artifact."

## 3. Data Inputs (paths relative to repo root)

**Trade dataset (canonical 30s FVGC baseline):**
- `studies/baseline/results/trades.csv` — 6,614 trades, 2018-01-02 to 2026-05-15
  - Cols: timestamp, direction, entry_price, variant, sl_dist, outcome, hit_X_R (for X in {1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0}), bars_to_X_R, mfe_r, mae_r, fvg_id, fvg_created_at, etc.
  - ⚠️ **Do NOT use `mfe_r` for runner expectations** — documented post-exit bug. Use `hit_X_R` columns instead.

**Per-day factor table:**
- `data/trading_days/trading_days.csv` — 2,158 days, 63 columns
  - Includes: gap_from_prior_close, overnight_*, prior_day_*, candle_930_*, or_5min/15min/45min_*, day_of_week_name, is_fomc_week, is_opex_week, is_quad_witching, has_red_folder_news, vixy_prior_close, vixy_regime, prior_day_range_atr_ratio, prior_day_directional_changes, prior_day_close_vs_open_pct, prior_day_type

**Reference implementations:**
- `studies/m1_short_8yr_validation/run.py` — current 8-year analysis with veto/conf computation
- `studies/multi_cell_confluence/factor_mining.py` — original factor mining pipeline
- `studies/multi_cell_confluence/tier_construction.py` — original stacking logic
- `studies/multi_cell_confluence/oos_validation.py` — OOS protocol the original used

**Read these BEFORE starting** — understand what was tried before so you don't repeat mistakes.

## 4. Filter Definition (the trade cohort)

Filter `trades.csv` to:
- `direction == 'short'`
- `09:30:00 ≤ time(timestamp) < 09:45:00`
- `variant != 'protected_swing'` (confirmed -32pp WR contamination)
- `outcome ∈ {'win', 'loss'}` (skip 'skip' outcomes)

Apply hard vetoes (filter OUT days where ANY active):
- `vixy_prior_close ≤ rolling_90d_q25(vixy_prior_close)` (low-VIX regime)
- `day_of_week_name == 'Monday'` (Monday weakness in data)

The remaining trades are your universe. Expect ~250 trades over 8 years.

## 5. Candidate Variable List (test all of these)

For each variable, compute a binary version (default: top/bottom quartile or threshold). Continuous versions can be tested separately if a binary doesn't show signal.

### A. Pre-Market Gap & Range
- `gap_large_down` (gap ≤ -100 pts)
- `gap_medium_down` (-100 < gap ≤ -30)
- `gap_small_down` (-30 < gap ≤ -10)
- `gap_pct_2sigma` (gap_pct ≤ -2σ of 90d rolling)
- `gap_atr_ratio_high` (|gap| / atr_20 ≥ 0.5)
- `overnight_range_top_q` (90d top quartile)  ⭐ priority
- `overnight_range_atr_ratio_high`
- `overnight_direction_down`
- `overnight_swept_prior_high` (overnight high > prior_day_high then reversed)
- `overnight_swept_prior_low`
- `overnight_inside_prior_day` (overnight stayed within prior RTH range)

### B. Prior Session Character
- `prior_day_weak` (close in bottom ⅓ of range — current default)
- `prior_day_strong` (close in top ⅓)
- `prior_day_range_atr_ratio_low` (compressed prior day)
- `prior_day_range_atr_ratio_high` (expanded)
- `prior_day_inside_day`
- `prior_day_outside_day`
- `prior_day_directional_changes_high` (chop)
- `prior_day_directional_changes_low` (clean trend)
- `prior_day_was_red`
- `prior_day_close_vs_open_pct_neg_strong` (< -1%)
- `prior_2day_return_neg`
- `prior_3day_return_neg`
- `prior_5day_return_neg`  ⭐ priority
- `made_new_5d_low_yesterday`
- `made_new_20d_low_yesterday`
- `prior_day_type_*` (use existing buckets in trading_days)

### C. Multi-Day Trend Regime
- `ret_5d_neg`
- `ret_10d_neg`
- `ret_20d_neg`
- `ret_60d_neg` (already used as regime label)
- `below_20d_ma`
- `below_50d_ma`
- `below_200d_ma`  ⭐ priority (sustainable down-regime)
- `bear_streak_3d` (3 consecutive red closes)
- `days_since_ATH_high` (≥ 30 days)
- `days_since_20d_low_low` (recent low → continuation)

### D. Volatility Regime
- `vixy_high` (90d top quartile — currently in stack, evaluate carefully)
- `vixy_rising_5d` (5d change > 0)
- `vixy_falling_5d`
- `vixy_z_score_90d_high` (z > 1)
- `nq_realized_vol_20d_top_q`
- `atr_20_vs_atr_60_ratio_high` (vol expansion)
- `vix_spike_yesterday` (VIXY 1d change > 90d top quartile)

### E. Open Structure (knowable by 9:30:30 or 9:35)
- `bear_930` (currently in stack)
- `c930_body_top_q` (currently in stack)
- `c930_body_pct_high` (continuous: body/range ≥ 0.7)
- `c930_swept_prior_day_high` (open wicked through prior H — failed test)
- `c930_swept_prior_day_low`
- `c930_close_in_bot_q` (close in bottom quartile of 9:30 range — committed selling)
- `or_5min_top_q` ⭐⭐ HIGH PRIORITY (+12.8pp fire — untested for WR)
- `or_5min_direction_down`
- `or_5min_close_in_top_q` (OR closed in top — reversal setup)
- `or_5min_atr_ratio_high`
- `or_5min_high_above_prior_day_high` (sweep)
- `first_3_bars_all_red` (need 30s OHLC to compute — derive from 30s bars)

### F. Calendar / Time
- `is_fomc_week` ⚠️ evaluate carefully — suspect overfit
- `is_opex_week`
- `is_quad_witching`
- `days_to_fomc_le_2` (next FOMC within 2 days)
- `days_since_fomc_le_3` (last FOMC within 3 days)
- `dow_tuesday`
- `dow_wednesday`
- `dow_thursday`
- `dow_friday` (currently in stack)
- `is_first_5d_of_month`
- `is_last_5d_of_month`
- `days_to_quarter_end_le_5`
- `is_post_holiday` (Tue after Mon holiday)

### G. News / Events
- `has_red_folder_news` (today)
- `has_pre_rth_news` (8:30 release)
- `has_post_945_news` (10am release — during trade window)
- `is_cpi_day`, `is_nfp_day`, `is_fomc_day` (event-level)
- `is_day_after_cpi`, `is_day_after_nfp`

### H. Engineered Combinations (test these AFTER finding single-factor edges — they're interactions)
- `bear_setup_score_3` = bear_930 + gap_down + overnight_direction_down ≥ 3
- `compression_pop` = prior_day_inside_day AND gap_down
- `continuation` = prior_day_weak AND gap_down AND bear_930
- `fear_with_open_confirmation` = vixy_high AND bear_930
- `sweep_and_fail` = overnight_swept_prior_high AND bear_930 AND gap_down

## 6. Methodology — strict OOS protocol

### Split
- **Training:** 2018-01-01 → 2024-12-31 (7 years)
- **OOS:** 2025-01-01 → 2026-05-15 (~1.5 years, expect ~30-40 trades at 2+ tier)
- **Do not peek at OOS during mining.** Compute factor lifts only on training. OOS evaluation happens once, at the end, after the stack is finalized.

### Per-factor acceptance criteria

A candidate factor is ACCEPTED only if it satisfies ALL on TRAINING data:

1. **Base rate sanity:** factor true on 5-50% of trades (not too rare, not too common)
2. **Sample size:** n_present ≥ 30 AND n_absent ≥ 30
3. **WR lift:** WR_present − WR_absent ≥ 5pp
4. **Statistical significance:** Fisher exact test p ≤ 0.10 (two-sided)
5. **Regime consistency:** WR_present − WR_absent ≥ 0 in each of {bear, bull, neutral} subsets (allow noise but no reversal)
6. **No multi-collinearity:** correlation with already-accepted factors < 0.7 (otherwise it's redundant)

### Stacking — forward stepwise

1. Sort candidates by WR lift on training (descending)
2. Start with top-1 as the base
3. Forward iteration:
   - For each remaining candidate, compute WR lift when STACKED on the current selection (i.e., trades where current selection true + candidate true)
   - Add the candidate with the highest marginal lift
   - Re-validate on OOS: did the OOS WR at the new (k+1)-conf tier improve? If not, STOP.
4. Cap final factor count at 6.
5. **Test removal:** drop each retained factor, confirm training WR at 2+ tier drops by ≥ 3pp. If dropping a factor doesn't hurt, it's noise.

### Tier construction
After stack is fixed, define tiers as confluence count buckets (0-1, 2, 3, 4+). Report per-tier WR/PF/hit_X_R on both training and OOS. The 2+ tier is the operational threshold; the 4+ tier is the conviction cell.

### Multi-target mining
Run the same methodology three times, with three different target signals:

1. **WR @ 1R lift** (primary — predicts winning trades)
2. **PF @ 2R lift** (predicts profitable RR, captures runners)
3. **Fire-rate lift** (predicts whether ANY FVGC fires on a setup day — different question)

Report separate factor stacks for each. Some factors may be in all three; others may specialize. The fire-rate stack is a screen-time efficiency tool, not an entry filter.

### Anti-overfit guardrails

- **Bonferroni-aware:** if you tested ~70 candidate factors, naive p ≤ 0.10 is too lenient. Apply Benjamini-Hochberg false-discovery-rate correction (target FDR q ≤ 0.10) before declaring significance.
- **Time-based folds (if you do CV):** never random folds. Use blocked time-series CV (e.g., 5 expanding-window folds over training period).
- **Per-year sanity check:** the final stack's 2+ tier WR should not be < 45% in any single year of training (allow noise, but no complete failures). Flag any year-failure as a regime warning.
- **No factor that requires data unknown by 9:30:30** unless explicitly tagged as a "9:35 entry filter" (the OR 5-min range factor is a legitimate 9:35-knowable filter).

## 7. Deliverables

Save all artifacts to `studies/m1_short_factor_remine/`.

### Required outputs

1. **`REPORT.md`** — human-readable summary:
   - Final factor stack (4-6 factors) with per-factor narrative (why economically?)
   - Tier table (0-1/2/3/4+) with WR/PF/hit_X_R on both IS and OOS
   - Regime breakdown per tier
   - Year-by-year stability (no year < 45% at 2+ tier)
   - IS vs OOS delta (must be ≤ 8pp at 2+ tier)
   - Comparison to current 7-factor stack — net improvement?
   - Reject list — all candidates that didn't make it, one-line reason each
   - Honest verdict: "ready to ship" vs "modest improvement" vs "no improvement found"

2. **`run.py`** — fully reproducible analysis script. Should re-run end-to-end and regenerate all results.

3. **`results/`** directory with:
   - `factor_universe.csv` — all candidates tested with their stats (n, WR_present, WR_absent, lift, p_value, fdr_q, regime_consistency)
   - `final_stack_factors.json` — the 4-6 selected factors with metadata
   - `tier_summary_IS.csv` and `tier_summary_OOS.csv`
   - `year_breakdown.csv`
   - `regime_breakdown.csv`
   - `factor_stacking_trace.csv` — forward-stepwise trace (which factor was added at each step, marginal lift IS, marginal lift OOS)
   - `trades_tagged.csv` — per-trade with new factor flags + tier
   - `fire_rate_stack.csv` — separate fire-rate factor stack (Section 6 multi-target mining)
   - `pf_2r_stack.csv` — separate PF @ 2R factor stack

4. **`PROPOSED_NOTION_UPDATE.md`** — markdown content ready to paste into the M1 Short Notion page if the new stack is approved. Should include: trigger description, pre-market checklist, exit strategy section, hard vetoes section, tier table with both IS and OOS, regime breakdown, last-20-trades table.

### Reporting rules

- **Always include n** when reporting WR. "73% WR" is meaningless; "73% WR (n=15)" tells the truth.
- **Always report IS and OOS separately.** Never blend them in a headline number.
- **Honesty about failure is the goal.** If no stack beats 56% WR on OOS, say so. Don't manufacture a result.
- **Per-factor economic narrative is required.** Each factor in the final stack must have a 1-2 sentence "why does this make sense as a bearish edge" rationale. Pure data-mined factors with no narrative go in the reject list.

## 8. Out of scope

- Cross-instrument analysis (NQ + ES + RTY + YM) — separate study
- Live execution / order management rules
- Position sizing math
- Re-deriving the FVGC indicator itself
- Anything that requires bar-level data outside what's already in `studies/baseline/results/trades.csv` or `data/trading_days/trading_days.csv`

If you find that an obvious-seeming factor requires data we don't have, list it in REPORT.md under "factors we couldn't test — needs new data".

## 9. Anti-patterns to avoid (lessons from prior audits this session)

These are MISTAKES that were caught in recent audits. Don't repeat:

1. ❌ **Don't use `mfe_r`** for runner expectations — post-exit bug
2. ❌ **Don't use cached `htf_fvg_*_swept` columns** without `passes_time_gate` enforcement (look-ahead bias — see `data/levels/BUGFIX_2026-04-29_passes_time_gate.md`)
3. ❌ **Don't report hero WR without sample size** — N=10 at 90% is not a play
4. ❌ **Don't claim regime robustness from a sample with 13 bear days** — sample sizes matter per cell
5. ❌ **Don't add factors with no economic story** — even if they pass statistics on training data, they're unlikely to hold OOS
6. ❌ **Don't peek at OOS during factor mining** — it's a one-shot validation
7. ❌ **Don't use `protected_swing` variant** in any cohort — confirmed -32pp WR
8. ❌ **Don't blend regimes** when stratifying — report per-regime AND combined
9. ❌ **Don't drop low-performing years from the reporting** — 2020's 33% WR matters
10. ❌ **Don't optimize for a single metric** — a stack with great training WR but degraded OOS is overfit by definition

## 10. Suggested execution flow

1. **Hour 1:** Read this prompt + the referenced files (REPORT.md, factor_mining.py, run.py). Understand the existing model and where it failed.
2. **Hour 2:** Build the per-day factor frame — compute all ~70 candidate variables and join with the trade cohort. Save `factor_universe.csv` with per-factor base rates and basic WR stats.
3. **Hour 3-4:** Run per-factor acceptance test on TRAINING only. Compute lift, Fisher p, FDR q, regime consistency. Save survivor list.
4. **Hour 5:** Forward stepwise stacking on training. Re-evaluate on OOS at each step. Stop when OOS stops improving. Test removal.
5. **Hour 6:** Run the same on PF @ 2R and fire-rate targets (multi-target mining).
6. **Hour 7:** Build year-by-year and regime breakdown. Sanity-check each surviving factor.
7. **Hour 8:** Write REPORT.md with honest verdict. Save all artifacts. Write PROPOSED_NOTION_UPDATE.md.
8. **Commit + push** with a descriptive commit message naming the new factor stack and the IS/OOS WR improvement (or lack thereof).

## 11. Final reminder

The goal is NOT to find a stack that hits 76% WR on training. It is to find a stack that holds up OOS. If the honest answer is "the play is 55-60% WR and we can't improve it materially," that's a valuable answer. **Don't manufacture an edge.**

A null result with rigorous methodology is more valuable than a fragile edge with sloppy methodology.

---

*Prompt last updated 2026-05-18. Reference outputs from prior audits in `studies/m1_short_8yr_validation/` and `data/levels/BUGFIX_2026-04-29_passes_time_gate.md`.*
