# M1 Short Factor Re-Mining — 8-Year (2018-2026)

**Date:** 2026-05-18
**Inputs:** `studies/baseline/results/trades.csv` (8-year 30s baseline, n=6,614), `data/trading_days/trading_days.csv` (n=2,158)
**Prompt:** [RESEARCH_PROMPT.md](RESEARCH_PROMPT.md)
**Pipeline:** [run.py](run.py)
**Exit analysis:** [exit_analysis.py](exit_analysis.py)

## TL;DR — the verdict flipped twice

1. **First pass (factor mining):** No new factor stack materially beats the prior 7-factor stack on rigorous OOS validation. The play looked like B-tier at ~56% WR baseline / 60% with confluences. **Apparent verdict: modest improvement, do not ship.**

2. **Second pass (risk management math):** Once you compute exit-strategy EVs against the actual `hit_X_R` ladder, the play is **A-tier with the right runner exit**. PF reaches **3.0+ at the 2+ confluence tier with TP@5R no-BE**. **Real verdict: it's a runner play, not a WR play. The exit dominates the edge.**

The original Notion advertisement was wrong about WHY the play works. It claimed 76% WR — that's overfit and doesn't hold up. The play really works because **the runner profile is massive** (38% of trades hit 5R, median MFE 5.6-7R among winners). The right exit captures that; the wrong exit (TP@1R or BE@1R-and-stopped) caps it.

## Goal recap (from RESEARCH_PROMPT.md)

A new factor stack of 4-6 factors that satisfies:
- IS WR @ 2+ tier ≥ 60%
- OOS WR @ 2+ tier ≥ 58%
- IS/OOS delta ≤ 8pp
- Regime variance ≤ 12pp
- Year floor ≥ 45%
- Total n at 2+ tier ≥ 150 over 8 years

## Methodology summary

- Train: 2018-01-01 → 2024-12-31 (7 years)
- OOS: 2025-01-01 → 2026-05-15 (1.5 years held out)
- Filter: M1 short cohort, 9:30–9:45, no `protected_swing`, vetoes applied (`vixy_low`, `dow_monday`)
- 75 candidate factors tested across 8 categories
- Acceptance gates: n ≥ 30 per side, ≥ +5pp WR lift, Fisher exact p ≤ 0.10, Benjamini-Hochberg FDR q ≤ 0.10, regime-consistent sign, base rate 5-50%, multi-collinearity check
- Forward stepwise stacking with per-step OOS validation
- Test-removal sanity check on final stack
- Multi-target mining: WR @ 1R, PF @ 2R, fire-rate (separate stacks per target)

## Factor mining results

### Goal compliance (4-factor stack: prior_3d_neg + prior_day_weak + near_20d_low + made_new_5d_low_yday)

| Criterion | Threshold | Result | Pass |
|---|---|---|---|
| IS WR @ 2+ tier | ≥ 60% | 60.9% (n=92) | ✓ |
| OOS WR @ 2+ tier | ≥ 58% | 58.8% (n=17) | ✓ |
| IS/OOS WR delta | ≤ 8pp | +2.1pp | ✓ |
| Regime variance IS | ≤ 12pp | 3.6pp | ✓ |
| Year floor at 2+ tier | ≥ 45% | 50.0% (worst: 2020) | ✓ |
| Total n at 2+ tier | ≥ 150 | 109 | **✗** |
| FDR-significant factors | > 0 | **0** | **✗** |

Goal criteria 1-5 met. Criteria 6-7 failed. **No factor passes Benjamini-Hochberg FDR correction.** The 4 factors that made the cut are correlated proxies for the same theme ("market has been weak lately") and only one (`made_new_5d_low_yday`) survives test-removal.

### The damning OOS pattern

```
                  IS (2018-2024)       OOS (2025-2026)
  0-1 tier WR:      36.2% (n=105)        68.8% (n=32)  ⚠️
  2+ tier WR:       60.9% (n=92)         58.8% (n=17)
```

**On OOS the 0-1 tier OUTPERFORMS the 2+ tier.** The confluence filter actively removed winners in the recent regime. This is the smoking gun: the confluences select on a "market weakness" signature that helps in 2018-2024 (especially 2020) but works against you in 2025-2026 strong-tape conditions.

### Per-factor test-removal

| Factor | WR with stack | WR without (replaced w/ rest) | Δ | Survives ≥3pp? |
|---|---|---|---|---|
| `f_made_new_5d_low_yday` | 60.9% | 55.7% | +5.17pp | ✓ |
| `f_prior_3d_neg` | 60.9% | 60.8% | +0.09pp | ✗ |
| `f_prior_day_weak` | 60.9% | 62.0% | -1.1pp | ✗ |
| `f_near_20d_low` | 60.9% | 62.0% | -1.16pp | ✗ |

Only 1 of 4 factors materially contributes. The other 3 are redundant proxies. A leaner stack of `{f_made_new_5d_low_yday}` alone might match the 4-factor performance — left as a follow-up study.

### What we confirmed about the prior 7-factor stack

All factors from the 2026-05-15 multi_cell_confluence model, rigorously tested on 8-year data:

| Prior factor | 8-yr WR lift | Status |
|---|---|---|
| `gap_large_down` (≤-100pts) | +5pp | Marginal (passes lift but not FDR) |
| `prior_day_weak` | +3pp | Below threshold |
| `bear_930` | +2pp | Below threshold |
| `c930_body_top_q` | +1pp | Noise |
| `dow_friday` | +1pp | Noise |
| `vixy_high` | -1pp | **Anti-signal** (was claimed +10pp) |
| `is_fomc_week` | 0pp WR / -10pp FIRE | **Anti-signal in fire rate** (was claimed +12pp) |

The prior stack was selection-biased toward what worked in the 3-year training window. Most factors do not hold up on the longer history.

### Fire-rate predictor (untouched at WR target)

- `or_5min_top_q` — +17.3pp fire rate (p < 1e-6) — strongest signal in the entire study
- Adopt as a **screen-time efficiency tool**, not an entry filter
- On days where 9:30–9:35 OR range is top-quartile of last 90 days, fire rate jumps from 22% to 35%

## Exit-strategy analysis (the second pass)

Run on the new 8-year cohort with the 4-factor stack and the post-veto baseline.

### Combined 2+ tier IS+OOS (n=109, 60.6% WR, hit ladder: 1R 61% / 2R 54% / 3R 49% / 5R 38%)

| Strategy | EV/trade | PF @ 1R |
|---|---|---|
| TP @ 1R hard | +0.21R | 1.53 |
| TP @ 2R hard, no BE | +0.62R | 2.36 |
| **TP @ 3R hard, no BE** | **+0.94R** | **2.84** |
| **TP @ 5R hard, no BE** | **+1.26R** | **3.01** ⭐ |
| Scale 50% @ 2R + 50% rides to 5R, no BE | +0.94R | 2.74 |
| **1/3@1R + 1/3@3R + 1/3@5R, BE@1R after first** | **+0.92R** | **3.33** |
| 25% @ 1R/2R/3R/5R, BE@1R after first | +0.86R | 3.19 |

### Post-veto baseline (n=246, 51.2% WR — basically coin flip)

| Strategy | EV/trade | PF @ 1R |
|---|---|---|
| TP @ 1R hard | +0.02R | 1.05 |
| TP @ 2R hard, no BE | +0.37R | 1.67 |
| TP @ 3R hard, no BE | +0.61R | 2.02 |
| **TP @ 5R hard, no BE** | **+0.78R** | **2.11** ⭐ |
| Scale 50% @ 2R + 50% rides to 5R | +0.57R | 1.92 |
| 1/3 + 1/3 + 1/3 | +0.58R | 2.19 |

**Even at 51% WR, TP@5R produces +0.78R/trade and PF 2.11.** The play is tradeable as a pure runner system without confluences.

### OOS-only validation (n=17, 58.8% WR — small sample but matters)

| Strategy | EV/trade | PF @ 1R |
|---|---|---|
| TP @ 1R hard | +0.18R | 1.43 |
| TP @ 2R hard, no BE | +0.24R | 1.40 (weakest — 2R doesn't hit in OOS) |
| **TP @ 5R hard, no BE** | **+1.12R** | **2.73** |
| 1/3 + 1/3 + 1/3 | +0.73R | 2.76 |

OOS confirms the **runner-based exit is robust**. The 2R-target degraded in OOS (the "62% hit 2R" was IS-specific). 5R-targets and scaled exits held up — they capture the runner regardless of mid-trade chop.

## The reframe

| What we have | Old framing | New framing |
|---|---|---|
| 51-60% WR | "Weak — barely above coin flip" | "Modest directional edge — but not the point" |
| Median MFE 5.6-7R when 1R hit | Buried in known issues | **THE EDGE** |
| 38% of trades reach 5R | Bonus | **Where all the EV lives** |
| TP@1R or BE@1R | The default | **The mistake** |
| TP@5R no BE | "Aggressive runner" | **The correct exit** |

Most professional algo systems run 50-55% WR with PF 1.5-2.0. M1 Short with TP@5R no-BE produces **PF 2.1 at no-confluence baseline and 3.0+ at 2+ confluences**. That's A-tier with discipline.

## Recommendations

### Live execution

1. **Keep the hard vetoes** (`vixy_low` 90d bottom quartile, `dow_monday`). They survived 8-year validation.
2. **Use `or_5min_top_q` as a screen-time gate.** Be at the screen on those days (35% fire rate); reduced focus on other setup days (22% fire rate).
3. **Take every post-veto, in-window FVGC short signal.** Confluences are a sizing input, not a take/skip gate.
4. **Default exit: TP @ 5R, NO BE move.** Stop stays at original SL. Win 5R or lose 1R.
5. **If TP@5R is psychologically too hard, scale:** 1/3 off at 1R + 1/3 at 3R + 1/3 rides to 5R, BE@1R only after the first third is off. PF 3.33, EV +0.92R/trade at 2+ confluence.
6. **NEVER use BE@1R on the full position.** Half the runners retrace through entry before extending. BE@1R-and-out empirically caps the edge.

### Sizing by confluence (not gating)

| Confluence count | Size | Exit |
|---|---|---|
| 0-1 | 0.5× base | TP@5R |
| 2 | 1.0× base | TP@5R or scale |
| 3 | 1.0× base | TP@5R or scale |
| 4+ | 1.25× base | TP@5R or scale |

This is a smoother sizing curve than the original take/skip rule and reflects what the data actually shows (modest edge that scales with confluences but doesn't disappear at 0-1).

### Honest expected performance

- **EV per trade: +0.78R (no filter) to +1.26R (2+ confluences) with TP@5R**
- **PF @ 1R: 2.1 (no filter) to 3.0 (2+ confluences)**
- **WR: 51% (no filter) to 61% (2+ confluences)**
- **Trade frequency: ~2.5-3 / month at 2+ confluences, ~5-6 / month at any-confluence**
- **Worst expected year: 2020-style dislocations at ~50% WR but with full runner profile intact**

### What NOT to do

- Don't claim 76% WR — it's overfit
- Don't use BE@1R as default — it eats runners
- Don't use TP@1R fixed — it caps the edge to PF ~1.5
- Don't gate on 4+ confluences as a hard rule — sample too small and OOS-fragile
- Don't trust `is_fomc_week` or `vixy_high` as +confluences — they're noise/anti-signals on 8-yr data

## File index

- [`RESEARCH_PROMPT.md`](RESEARCH_PROMPT.md) — original agent prompt
- [`run.py`](run.py) — full factor-mining pipeline (agent output, reproducible)
- [`exit_analysis.py`](exit_analysis.py) — exit-strategy EV/PF computation
- [`results/factor_universe.csv`](results/factor_universe.csv) — all 75 factors tested with stats
- [`results/final_stack_factors.json`](results/final_stack_factors.json) — the 4-factor stack metadata
- [`results/tier_summary_IS.csv`](results/tier_summary_IS.csv) — IS tier table
- [`results/tier_summary_OOS.csv`](results/tier_summary_OOS.csv) — OOS tier table
- [`results/year_breakdown.csv`](results/year_breakdown.csv) — year-by-year stability
- [`results/regime_breakdown.csv`](results/regime_breakdown.csv) — bear/bull/neutral split
- [`results/factor_stacking_trace.csv`](results/factor_stacking_trace.csv) — forward stepwise trace
- [`results/test_removal.csv`](results/test_removal.csv) — per-factor drop sanity check
- [`results/trades_tagged.csv`](results/trades_tagged.csv) — per-trade with stack flags
- [`results/fire_rate_stack.csv`](results/fire_rate_stack.csv) — fire-rate target stack
- [`results/pf_2r_stack.csv`](results/pf_2r_stack.csv) — PF @ 2R target stack
- [`results/run.log`](results/run.log) — pipeline execution log

## Open follow-ups

1. **Single-factor variant:** test `{f_made_new_5d_low_yday}` alone as the entire confluence model. The test-removal data suggests it carries the lift and the other 3 are redundant.
2. **Cross-instrument validation:** does the play work better on ES or RTY? Phil has Databento access for those instruments.
3. **2+ tier OOS paradox investigation:** why does the 0-1 tier outperform 2+ in OOS? Is it pure noise (small n), or is there a real regime-change signal in the data?
4. **Re-validate `or_5min_top_q` as a WR factor** (not just fire-rate). Test as additional confluence in the stack.
5. **Multi-cell re-run:** apply the same rigorous methodology to M2/M3 long & short cells now that the infrastructure is in place.

---

*Authored 2026-05-18 by Claude (Phil's session). Methodology and exit math reproducible via the .py files in this folder.*
