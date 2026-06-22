# Higher-R Targets — Do Runner-Cells Look Different From 2R-Cells?

## Causal Audit Status

**INVALIDATED — 2026-05-21.** Two contamination sources flow into this study:

1. **`n_vp_targets` / `vp_only_target`** — already flagged below; confirmed invalidated by [`studies/lookahead_audit/rerun_vp_targets_causal.py`](../lookahead_audit/rerun_vp_targets_causal.py).
2. **`range_regime` (the "trusted hit_5R signal" claim)** — inherited from `discovery_2R_hits/run.py:184`, where `range_regime` is built from today's full-session `rth_range`. `range_regime` is **uncomputable causally** — the day's full range is not known until 16:00. The memory claim "+11.9pp OOS causal" is wrong.

No surviving hit_5R headline. Replace with a real-time proxy (e.g., `or_45min_range > rolling_avg`, available 10:15+) or drop the regime concept.

---

> ### ⚠️ Lookahead caveat (read first)
>
> Every finding that uses `n_vp_targets` or `vp_only_target` joins today's
> `daily_volume_profile.csv` on date — and that file stores the full-RTH
> 9:30-16:00 VP. A 9:30-10:15 trade therefore sees POC/VAH/VAL from hours
> that haven't happened yet. See [[project-composite-vp]] for the full
> writeup: under a strictly causal (lag-1) join, the parent Phase A
> `n_vp≥2 → +18pp` headline collapses to **+0.3pp**.
>
> **Findings that *probably* survive a causal rebuild:**
> - `range_regime==expansion` — derived from prior 5-day RTH range, computed
>   pre-open. The hit_5R lift (+11.9pp OOS, n=486) is causal.
> - `lvls_within_1R==0`, `variant==protected_swing` — trade-time attributes,
>   no future leakage.
> - The qualitative *shape* of the n_vp_targets inversion (2R-specialist vs
>   5R-specialist cells differ) is likely directionally correct since it
>   relates VP location to MFE distribution — but the magnitude is inflated.
>
> **Findings that need causal-VP rebuild before citing as live edge:**
> - `n_vp_targets` curves and inversion at hit_5R
> - `vp_only_target==True` lift numbers
> - Anything in §2 and the n_vp portion of §4
>
> Treating the n_vp results as *hypotheses to verify with partial-day VP*
> (accumulate volume only up to entry timestamp). The runner signature
> findings from §3 and §4 that are NOT VP-based are the trusted deliverable.

---

**Hypothesis (Phil).** The features that predict `hit_2R` may not be the
features that predict `hit_5R`. Some setups might be "homerun specialists" —
modest 2R hit, but extreme tails. Others are 2R-specialists that fizzle.

**Verdict.** **Hypothesis confirmed and stronger than expected.** The cells
that maximise `hit_2R` and the cells that maximise `hit_5R` are **structurally
opposed**:

| What helps... | hit_2R | hit_5R |
|---------------|--------|--------|
| **Level confluence ahead** (`n_vp_targets≥2`, `n_targets_in_dir==2`) | YES (+18pp OOS) | NO — *hurts* (-4pp OOS) |
| **Clean path** (`n_targets_in_dir==0`, `lvls_within_1R==0`) | NO — hurts | YES (+8-15pp lift, n_runner sample) |
| **Range regime = expansion** | modest (+8pp) | strongest single signal (+12pp OOS) |
| **Variant = protected_swing** | mild | strongest among variants (+12pp on runner sample) |

Reading: **VP/session magnets are *brakes* past 3R, not targets.** Two POC/VAH/VAL
levels in the 0.5-3R zone push price to ~2R reliably and then stall it there.
The trades that *run* past 4R are the ones with no nearby magnets — clean path,
expansion regime, protected_swing entries.

This means the trader's playbook should branch on which R bucket they care
about: **manage tight to 2-3R when level confluence is high, hold for runner
when path is clean.**

---

## 1. Base-rate decay

Hit-rate per target, full sample (n=4,548) and strict 2023-2026 OOS:

| target | base (all) | base (strict OOS 2023-2026) |
|--------|-----------|------------------------------|
| hit_1_5R | 46.5% | 50.1% |
| hit_2_0R | 42.2% | 45.7% |
| hit_2_5R | 38.6% | 41.7% |
| hit_3_0R | 35.5% | 38.0% |
| hit_4_0R | 30.6% | 33.7% |
| hit_5_0R | 25.8% | 28.8% |

Decay is roughly linear ~4-5pp per 0.5R through 3R, then flatter (4R→5R only
~5pp drop). **About 1 in 4 trades is a 5R+ runner** in the strict OOS era —
a meaningful tail. (Files: [base_rate_decay.csv](results/base_rate_decay.csv).)

---

## 2. **The big finding** — `n_vp_targets` inverts at high R

Hit rate by `n_vp_targets` (count of POC/VAH/VAL in 0.5–3R ahead of entry):

| n_vp | n | hit_1_5R | hit_2R | hit_2_5R | hit_3R | hit_4R | **hit_5R** |
|------|---|----------|--------|----------|--------|--------|------------|
| 0 | 2,290 | 34.9% | 30.7% | 27.6% | 25.6% | 23.1% | **21.4%** |
| 1 | 1,798 | 54.5% | 51.4% | 47.9% | 44.8% | 39.1% | **32.3%** ← peak |
| 2 | 435   | 64.6% | 62.1% | 55.4% | 47.8% | 36.3% | **23.7%** |
| 3 | 25    | 92.0% | 92.0% | 92.0% | 52.0% | 8.0%  | **8.0%** |

The curve is monotonic through `hit_2_5R`, **non-monotonic at hit_3R** (peak
shifts from 2 to 1), and **inverted by hit_5R** (the worst non-zero bucket
is `n_vp_targets==2`, not 0).

Reading: ≥2 VP magnets nearby = price closes the gap to those magnets, books
2R-2.5R reliably, but then **stalls there**. With one magnet, price tags it
and keeps going. With no magnets, price drifts on momentum alone.

This is the most actionable finding in the study: **at TP=5R, the
"confluence" pattern that was free money for TP=2R is actively harmful.**

(File: [n_vp_targets_x_target.csv](results/n_vp_targets_x_target.csv),
[n_vp_targets_x_target_strict_oos.csv](results/n_vp_targets_x_target_strict_oos.csv).)

### Walk-forward strict (IS=2018-2022, OOS=2023-2026)

`n_vp_targets==2` lift vs era base, both eras:

| target | IS lift pp | OOS lift pp | OOS rate | verdict |
|--------|-----------|-------------|----------|---------|
| hit_1_5R | +19.8 | +17.9 | 65.0% | strong |
| hit_2_0R | +22.1 | +17.8 | 62.0% | strong |
| hit_2_5R | +20.4 | +13.6 | 54.4% | strong |
| hit_3_0R | +15.1 | +9.8 | 47.7% | strong |
| hit_4_0R | +8.3  | +3.4 | 35.9% | weak |
| **hit_5_0R** | **+0.2** | **−4.3** | **23.2%** | **inverts** |

Walk-forward confirms the inversion is not an IS-only artefact. **The
n_vp_targets==2 cell stops being predictive of 5R in OOS — actually goes
negative.** (File: [walk_forward_strict_n_vp_targets.csv](results/walk_forward_strict_n_vp_targets.csv).)

### vp_only_target=True (VP is ONLY target ahead — no session levels in path)

This cohort is the cleaner runner candidate:

| target | n_oos | OOS lift pp | OOS rate |
|--------|-------|-------------|----------|
| hit_2_0R | 455 | +11.6 | 55.8% |
| hit_3_0R | 455 | +10.3 | 48.1% |
| hit_5_0R | 455 | **+4.0** | **31.4%** |

Same n, more durable across R. The combo "VP magnet ahead AND no session/HTF
levels cluttering the path" is the better universal filter — strong at 2R,
*still positive* at 5R (where pure `n_vp≥2` flips negative). (File:
[walk_forward_strict_vp_only.csv](results/walk_forward_strict_vp_only.csv).)

---

## 3. Per-target top survivors — different features at different R

From the parent v4 scan (IS=2018-2023, OOS=2024-2026), survivors at each target
(lift ≥3pp both eras, n_floor varies by target):

| target | top survivor | OOS lift pp | OOS rate | n_OOS |
|--------|--------------|-------------|----------|-------|
| hit_1_5R | n_targets_in_dir==2 | +7.2 | 55.5% | 301 |
| hit_2_0R | n_targets_in_dir==2 | +6.8 | 52.2% | 301 |
| hit_2_5R | *(no survivor at n_floor=100)* | — | — | — |
| hit_3_0R | range_regime==expansion | +7.6 | 46.5% | 486 |
| hit_4_0R | range_regime==expansion | +9.7 | 43.4% | 486 |
| hit_5_0R | **range_regime==expansion** | **+11.9** | **40.7%** | **486** |

**Regime shift at hit_2_5R / hit_3R.** Below: level-count features dominate.
Above: range-regime and "clean-path" features dominate. (File:
[per_target_top_survivors.csv](results/per_target_top_survivors.csv).)

### Survivor overlap

| feature \| value | hit_1_5R | hit_2R | hit_3R | hit_4R | hit_5R | n_R survived |
|------------------|----------|--------|--------|--------|--------|--------------|
| n_targets_in_dir \| 2 | +7.2 | +6.8 | +5.6 | +3.9 | — | 4 |
| range_regime \| expansion | — | — | +7.6 | +9.7 | +11.9 | 3 |
| variant \| protected_swing | — | — | +4.6 | +6.5 | +8.4 | 3 |
| lvls_within_1R \| 0 | — | — | — | +3.5 | +4.9 | 2 |

(File: [survivor_overlap.csv](results/survivor_overlap.csv).)

There is **no single feature that is a survivor at every R target**. The closest
is `n_targets_in_dir==2` (1.5R-4R) but it drops at 5R. `range_regime==expansion`
is the closest to a "runner specialist" — it appears only at 3R+ and grows
stronger with R. This is the cleanest signature for "this is a hold-for-runner
day."

---

## 4. Runner signature — what predicts hit_5R given hit_2R already cleared?

Conditional on `hit_2R == True` (n=1,920 of 4,548), base rates:
- `P(hit_3R | hit_2R)` = 83.9%
- `P(hit_4R | hit_2R)` = 72.5%
- `P(hit_5R | hit_2R)` = 61.2%

In other words: of trades that already cleared 2R, ~61% continue to 5R. The
2R→5R extension is the rule, not the exception — but it's not uniform.

Top runner-cohort predictors (lift on P(hit_5R | hit_2R), n_runner≥30):

| feature | value | n_runner | P(hit_5R\|hit_2R) | lift_pp | n_oos | P(hit_5R\|hit_2R, OOS) |
|---------|-------|----------|--------------------|---------|-------|------------------------|
| range_regime | expansion | 569 | **78.9%** | +17.8 | 300 | 79.0% |
| lvls_within_1R | 0 | 292 | 75.7% | +14.5 | 176 | 72.2% |
| variant | protected_swing | 296 | 73.7% | +12.5 | 171 | 73.7% |
| n_targets_in_dir | 0 | 292 | 73.3% | +12.1 | 165 | 73.3% |
| n_vp_clip | 0 | 702 | 69.7% | +8.5  | 392 | 69.4% |

Note that **n_targets_in_dir==0** — the "anti-survivor" of `hit_2R` from the
parent study — is a **runner predictor**. Once you've cleared 2R with no levels
in your path, there's nothing to stop you. The trades that *don't* hit 2R from
this cohort are skipped (30%-ish), but the ones that do mostly run.

Anti-runner cohorts (fizzle after 2R):

| feature | value | n_runner | P(hit_5R\|hit_2R) | lift_pp |
|---------|-------|----------|--------------------|---------|
| lvls_within_1R | 7+ | 80 | 26.3% | **−34.9** |
| **n_vp_clip** | **2** | 270 | **38.2%** | **−23.0** |
| range_regime | contraction | 412 | 41.8% | −19.4 |
| ath_dist_bucket | 100-200 | 131 | 48.1% | −13.1 |
| lvls_within_1R | 5-6 | 301 | 49.8% | −11.3 |
| sl_dist_bucket | Q4_large | 649 | 50.9% | −10.3 |

**`n_vp_clip==2` is the canonical fizzle-after-2R cohort.** Two VP magnets ahead
= price hits them and stops. This corroborates the inversion in §2.
(File: [runner_signature.csv](results/runner_signature.csv).)

---

## 5. Best multi-R consistent cells

The "consistent multi-R" candidate the trader asked for. Filters that work at
both ends of the R spectrum, n_OOS ≥ 100:

| filter | hit_2R OOS | hit_3R OOS | hit_5R OOS | n_OOS |
|--------|------------|------------|------------|-------|
| range_regime==expansion | 47.7% (+3pp) | 46.5% (+7.6pp) | 40.7% (+11.9pp) | 486 |
| variant==protected_swing | 43.5% (+5pp) | 39.5% (+4.6pp) | 36.6% (+8.4pp) | 306 |
| **vp_only_target==True (strict OOS)** | **55.8%** | **48.1%** | **31.4%** | **455** |

`vp_only_target==True` is the trader's best "across-the-board" filter — it lifts
at every R from 2R through 5R, on the strictest OOS split (2023-2026). The
combo "≥1 VP magnet ahead AND nothing else cluttering" is the cleanest signal
that survives the whole R range.

(File: [best_multi_R_cells.csv](results/best_multi_R_cells.csv).)

---

## 6. Year-by-year (n_vp_targets≥2 lift pp vs base, all years)

| year | n | hit_1_5R | hit_2R | hit_2_5R | hit_3R | hit_4R | hit_5R |
|------|---|----------|--------|----------|--------|--------|--------|
| 2018 | 20 | +29.7 | +32.1 | +29.6 | +24.0 | +16.4 | +6.4 |
| 2019 | 14 | +28.1 | +26.7 | +22.5 | +18.2 | +9.7 | +12.6 |
| 2020 | 43 | +23.2 | +28.3 | +26.7 | +22.5 | +20.5 | +6.0 |
| 2021 | 49 | +16.7 | +19.9 | +15.8 | +5.0 | **−6.1** | **−8.9** |
| 2022 | 80 | +18.9 | +19.9 | +20.3 | +13.9 | +5.1 | **−3.0** |
| 2023 | 67 | +16.3 | +14.4 | +12.7 | +5.7 | **−1.8** | **−8.4** |
| 2024 | 58 | +22.7 | +25.3 | +17.6 | +11.1 | +4.9 | **−4.1** |
| 2025 | 109 | +21.0 | +20.4 | +16.1 | +10.8 | **−1.1** | **−6.5** |
| 2026 | 20 | +13.4 | +16.4 | +19.8 | +21.6 | +19.9 | +13.0 |

`hit_5R` lift goes negative in 5 of the last 6 years for the
`n_vp_targets≥2` cohort. The brake effect is consistent. (File:
[yearly_n_vp_ge2_by_target.csv](results/yearly_n_vp_ge2_by_target.csv).)

---

## 7. Kill-criteria check

> "If no feature gives `hit_5R` lift ≥ +10pp on n ≥ 50 in OOS, conclude that
> hit_5R is essentially random within the trade pool and report negative."

**Passed.** `range_regime==expansion` gives +11.9pp lift on hit_5R, n_OOS=486.
Other features at +8-11pp range, n_OOS 200+.

> "If hit_3R/5R survivors are exactly the same as hit_2R survivors, the
> discovery is just hit_2R rebranded."

**Passed.** Distinct survivors: hit_2R = `n_targets_in_dir==2`; hit_5R =
`range_regime==expansion`. The 4-target overlap `n_targets_in_dir==2` drops
*out* before hit_5R; `range_regime==expansion` enters *at* hit_3R. Two
different signal families.

---

## 8. Recommended trade-management implications

These are hypotheses derived from the data — not yet expectancy-validated
in a simulator. Treat as candidate rules to test next, not as-shipped:

1. **`n_vp_targets≥2` → tight scratch at 2-2.5R.** This cell hits 2R at 62%
   but only 24% at 5R. Don't let it ride. ~62.1% hit_2R · 2R + 37.9% · -1R ≈
   +0.86R expectancy, vs the BE-or-stop-out drift past 2R.

2. **`vp_only_target==True` → trail for runner.** 31.4% hit_5R OOS on n=455.
   This is the cohort where holding past 2R pays.

3. **`range_regime==expansion` → upgrade TP from 2R to 4R+.** This is the
   only feature whose lift *grows* with R: +7.6pp at 3R, +9.7pp at 4R,
   +11.9pp at 5R. On expansion days, the runners are the rule.

4. **`range_regime==contraction` → cap at 1R, maybe skip.** 41.8% hit_5R on the
   runner cohort vs 61.2% base; this is the worst "if you hit 2R you fizzle"
   regime.

5. **`lvls_within_1R==7+` (heavy congestion) → skip or scratch fast.** Only
   26% of the hit_2R cohort here makes 5R. Lots of nearby levels = lots of
   stalls.

---

## 9. Open questions / follow-on studies

- **Pair stack: `range_regime==expansion` × `vp_only_target==True`.** Both
  individually survive at hit_5R; the combination should be the A++ runner
  filter. n is probably ~150-200 OOS — worth a dedicated walk-forward.

- **`n_targets_in_dir==2 × range_regime==expansion`** — the 2R-specialist
  cell *only when* the regime would let it run. Does conditioning fix the
  fizzle problem, or do the brakes still apply?

- **Per-variant deep dive.** `protected_swing` is the strongest runner variant;
  `ifvg` is a fizzler (-8.3pp anti-runner). The per-variant runner profile
  could justify variant-specific TP schedules.

- **Expectancy simulation.** Take a candidate management policy ("scratch at
  2.5R if `n_vp≥2`, else trail to 5R if `vp_only_target`") and compute
  per-trade R against the as-shipped fixed-TP baseline.

---

## Files

| file | purpose |
|------|---------|
| [run.py](run.py) | Cross-target synthesis pipeline |
| [results/base_rate_decay.csv](results/base_rate_decay.csv) | §1 |
| [results/n_vp_targets_x_target.csv](results/n_vp_targets_x_target.csv) | §2 |
| [results/n_vp_targets_x_target_strict_oos.csv](results/n_vp_targets_x_target_strict_oos.csv) | §2 OOS |
| [results/vp_only_target_x_target.csv](results/vp_only_target_x_target.csv) | §2 |
| [results/walk_forward_strict_n_vp_targets.csv](results/walk_forward_strict_n_vp_targets.csv) | §2 walk-forward |
| [results/walk_forward_strict_vp_only.csv](results/walk_forward_strict_vp_only.csv) | §2 walk-forward |
| [results/per_target_top_survivors.csv](results/per_target_top_survivors.csv) | §3 |
| [results/survivor_overlap.csv](results/survivor_overlap.csv) | §3 |
| [results/per_target_full_scan.csv](results/per_target_full_scan.csv) | §3 raw |
| [results/runner_signature.csv](results/runner_signature.csv) | §4 |
| [results/best_multi_R_cells.csv](results/best_multi_R_cells.csv) | §5 |
| [results/yearly_n_vp_ge2_by_target.csv](results/yearly_n_vp_ge2_by_target.csv) | §6 |
| [results/run.log](results/run.log) | Full run output |
