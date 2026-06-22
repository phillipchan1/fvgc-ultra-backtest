# Phase A — Adversarial walk-forward of `n_vp_targets`

## Causal Audit Status

**INVALIDATED — 2026-05-21.** The headline +19.93pp OOS lift was a lookahead artifact. `run.py:51` joined `daily_volume_profile.csv` on `date`, which gave 9:30-10:15 trades access to today's full-session 16:00 POC/VAH/VAL. Under strictly causal lag-1 VP, the same buckets are flat at the OOS base rate (44.2% / 44.8% / 44.5% / 26.7% vs base 44.3%) — no usable signal. Composite VP's lag-1 analysis first surfaced this; [`studies/lookahead_audit/rerun_vp_targets_causal.py`](../lookahead_audit/rerun_vp_targets_causal.py) reproduces the full 4-bucket comparison. **The Verdict below is preserved for historical context only.** Stop building on `n_vp_targets`.

---

## Verdict

**PASS** under a stricter walk-forward than the parent discovery study.

Both kill criteria were cleared with substantial margin:

| criterion | threshold | actual | status |
|-----------|-----------|--------|--------|
| n_vp==0 OOS hit_2R reaches OOS base (44.2%) | must stay below | **32.9%** (−11.3pp drag) | OK |
| n_vp≥2 OOS lift drops below +10pp | must clear +10pp | **+19.93pp** | OK |
| n_vp==2 yearly positive lift | ≥7 of 9 years | **9 of 9** | OK |

Headline `n_vp_targets` bucket rates under the stricter IS=2018-2022 / OOS=2023-2026 split:

| bucket | n_pooled | n_IS | hit_2R IS | lift_IS_pp | n_OOS | hit_2R OOS | lift_OOS_pp |
|--------|---------:|-----:|----------:|-----------:|------:|-----------:|------------:|
| 0      | 2290     | 1100 | 28.2%     | −11.85     | 1190  | 32.9%      | **−11.31** |
| 1      | 1798     |  887 | 49.4%     |  +9.34     |  911  | 53.5%      |  +9.21     |
| **2**  | **435**  | **198** | **62.1%** | **+22.08** | **237** | **62.0%** | **+17.78** |
| 3+ ⚠️  |   25     |    8 | 87.5%     | +47.46     |   17  | 94.1%      | +49.87     |

Base rates: IS = 40.0%, OOS = 44.2% (pooled 42.2%).

⚠️ The `3+` bucket has n_pooled=25 — below the n=50 floor. Flag, do not bank.

The signal *strengthened* under the stricter split. That itself is suspicious — discoveries usually weaken when re-split. Sections 2-6 try to find the crack; none of the slices broke it.

---

## 1. Methodology

- **IS = year ∈ [2018, 2022]** (n=2193, hit_2R=40.0%).
- **OOS = year ∈ [2023, 2026]** (n=2355, hit_2R=44.2%).
- **Buckets are structural** — 0 / 1 / 2 / ≥3 are integer counts of VP levels in the trade direction within 0.5R-3R of entry. No threshold is derived from the data.
- **Lift reported vs matching-era base** (never the pooled base).
- **Cells with n<50 flagged** (only the 3+ bucket trips this).
- **Year-by-year required**: n_vp==2 cohort must be positive in ≥7 of 9 years.
- **No threshold-selection code touches the OOS frame**. `run.py` only references `is_in_oos` for reporting.

VP definition: POC, VAH, VAL from `data/levels/daily_volume_profile.csv` (prior session's RTH profile, per date). `r_signed = (level − entry) / sl_dist`, sign-flipped for shorts. "In the trade direction within 3R" = `0.5 ≤ r_signed ≤ 3.0`.

---

## 2. A1 — Walk-forward (the kill test)

Already shown above. The signal is monotonic with bucket and the lift magnitude under the stricter split (+17 to +22pp on n_vp==2) is roughly 3× the original v4 report (+6.7pp). The reason: the original study used IS=2018-2023, so the strong 2023 n_vp==2 cohort (+14pp) was inside the IS lift. Pulling 2023 into OOS shifted that contribution but the OOS lift still held at +17.8pp.

### Year-by-year for `n_vp_targets == 2`

| year | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|------|------|------|------|------|------|------|------|------|------|
| n        | 19  | 13  | 41  | 47  | 78  | 66  | 52  | 100 | 19  |
| hit_2R   | 73.7% | 53.8% | 68.3% | 57.4% | 60.3% | 54.5% | 65.4% | 66.0% | 57.9% |
| year base | 42.9% | 30.4% | 39.1% | 39.3% | 41.4% | 40.8% | 43.7% | 47.5% | 43.6% |
| lift_pp  | +30.8 | +23.4 | +29.2 | +18.1 | +18.9 | +13.7 | +21.7 | +18.5 | +14.3 |

**Positive lift in 9 of 9 years.** Weakest year is 2023 (+13.7pp); strongest is 2018 (+30.8pp). 2018-2019 are tiny cells (n=19 / 13) but consistent.

---

## 3. A2 — Per-VP-level decomposition

| filter | direction | n_IS | hit_IS | lift_IS | n_OOS | hit_OOS | lift_OOS |
|--------|-----------|-----:|-------:|--------:|------:|--------:|---------:|
| poc_in_dir | all | 396 | 61.1% | **+21.07** | 452 | 63.3% | **+19.03** |
| vah_in_dir | all | 459 | 49.9% | +9.85 | 479 | 50.9% | +6.69 |
| val_in_dir | all | 452 | 51.8% | +11.73 | 505 | 59.2% | +14.96 |
| any_vp_in_dir | all | 1093 | 52.0% | +11.93 | 1165 | 55.8% | +11.55 |
| no_vp_in_dir | all | 1100 | 28.2% | −11.85 | 1190 | 32.9% | −11.31 |

### Per-direction (the cleanest finding in A2)

| level × direction | n_IS | lift_IS | n_OOS | lift_OOS | reading |
|-------------------|-----:|--------:|------:|---------:|---------|
| POC × long   | 203 | +19.57 | 278 | +16.55 | strong both sides |
| POC × short  | 193 | +22.66 | 174 | +23.00 | strong both sides |
| **VAL × long**   | **138** | **+25.91** | **202** | **+30.01** | VAL is the magnet for longs |
| VAL × short  | 314 |  +5.50 | 303 |  +4.93 | weak/flat |
| VAH × long   | 353 |  +3.31 | 356 |  −1.27 | weak/flat |
| **VAH × short**  | **106** | **+31.66** | **123** | **+29.74** | VAH is the magnet for shorts |

The signal is **asymmetric**: VAL helps longs (price reaching back up into the value area), VAH helps shorts (price reaching back down into the value area). POC helps both directions roughly equally. This makes structural sense — a long entering from below the value area has VAL as its first re-entry magnet, not VAH.

**Implication**: a count-based rule (`n_vp_targets >= 2`) is correct because it captures both stacking and direction-correct levels; but the per-level breakouts say the lift isn't uniform across the three levels — it's driven by POC + direction-matched VA edge.

---

## 4. A3 — Stall-at-VP (MFE peak proximity)

Walked forward 240 × 30s bars (2 hr) from each `hit_2R == True` winner's entry, found the bar with peak MFE in R, then measured |peak_price − nearest_VP| in R-units. Restricted to winners that had at least one VP target ahead (n=1218 of 1920 winners).

| band              | n     | share | nearest=POC | nearest=VAH | nearest=VAL |
|-------------------|------:|------:|------------:|------------:|------------:|
| <0.25R            | 233   | 19.1% | 18.9% | 44.6% | 36.5% |
| 0.25-0.5R         | 203   | 16.7% | 18.2% | 43.8% | 37.9% |
| 0.5-1.0R          | 244   | 20.0% | 20.9% | 39.3% | 39.8% |
| ≥1.0R             | 538   | 44.2% | 13.9% | 37.2% | 48.9% |

**35.8% of winners peak within 0.5R of a VP level.** That's a meaningful share — but it's not "most." Of the 44% that peak ≥1R away, VAL is the most common nearest level (49%), meaning longs that run past VAL.

**Reading**: VP levels are a real magnet for ~1/3 of winners' MFE peaks, supporting a Phase B "dynamic TP at VP" experiment — but the rule needs to be context-aware (only apply if a VP level lies within 0.5-1R of current price; don't blindly clip every winner).

---

## 5. A4 — Variant × n_vp_targets

| variant | bucket | n_IS | hit_IS | lift_IS | n_OOS | hit_OOS | lift_OOS |
|---------|--------|-----:|-------:|--------:|------:|--------:|---------:|
| bos             | 0  | 325 | 24.3% | −15.73 | 342 | 30.7% | −13.54 |
| bos             | 1  | 292 | 51.4% | +11.33 | 256 | 53.1% |  +8.88 |
| **bos**         | **2** |  64 | **64.1%** | **+24.03** |  72 | **61.1%** | **+16.86** |
| ifvg            | 0  | 128 | 23.4% | −16.60 | 144 | 33.3% | −10.91 |
| **ifvg**        | **2** |  30 | 56.7% | +16.63 |  37 | **70.3%** | **+26.02** |
| no_fvg          | 0  | 481 | 27.7% | −12.39 | 491 | 30.3% | −13.90 |
| **no_fvg**      | **2** |  91 | **62.6%** | **+22.60** | 116 | 61.2% | +16.96 |
| protected_swing | 0  | 166 | **40.96%** |  +0.93 | 213 | 42.3% |  −1.99 |
| protected_swing | 1  | 100 | 49.0% |  +8.96 | 128 | 58.6% | +14.35 |
| protected_swing | 2  |  13 | 61.5% | +21.50 |  12 | 50.0% |  +5.75 |

**Three variants behave the same way** (bos / ifvg / no_fvg): clear monotonic lift, n_vp==0 is a clear drag, n_vp==2 is a clear A+ tag.

**`protected_swing` is the exception**: n_vp==0 *does not drag* (+0.9pp IS, −2pp OOS — essentially flat). Its 0 bucket isn't a "skip"-grade signal the way it is for the other three. The n_vp==2 cell is also small (n=13/12) and OOS lift collapses to +5.8pp.

**Implication**: when wiring this as a filter, scope the "skip when n_vp==0" rule to bos / ifvg / no_fvg. Do not apply to protected_swing trades.

---

## 6. A5 — Robustness slices

### Direction × bucket

| dir | bucket | n_IS | hit_IS | lift_IS | n_OOS | hit_OOS | lift_OOS |
|-----|--------|-----:|-------:|--------:|------:|--------:|---------:|
| long  | 0  | 491 | 26.9% | −13.15 | 564 | 31.2% | −13.04 |
| long  | 2  | 109 | 58.7% | +18.68 | 154 | 59.7% | +15.49 |
| short | 0  | 609 | 29.2% | −10.81 | 626 | 34.5% | −9.74  |
| short | 2  |  89 | 66.3% | **+26.26** |  83 | 66.3% | **+22.02** |

Signal is real on both directions. Shorts × n_vp==2 are the strongest cell (+26pp IS / +22pp OOS).

### Macro window × bucket

M1, M2, M3 all show clean monotone in both eras. M4 (post 10:15) is too small (n_IS=18 on the 0 bucket) to count. Best macro × bucket cell in OOS:

| macro | bucket | n_OOS | hit_OOS | lift_OOS |
|-------|--------|------:|--------:|---------:|
| M1    | 2 | 59 | 66.1% | +21.86 |
| M2    | 2 | 70 | 65.7% | +21.47 |
| M3    | 2 | 106 | 58.5% | +14.24 |

### VIXY regime × bucket

| regime   | bucket=0 OOS lift | bucket=2 OOS lift |
|----------|------------------:|------------------:|
| low      | −13.65            | +22.94            |
| normal   | −12.67            | +5.75 (n=18)      |
| elevated | −15.14            | +6.77             |
| high     |  −7.97            | +22.42            |

The signal works in **all four VIXY regimes**. It's NOT a VIXY-shaped effect — the regime distributes the strength differently (strongest in low + high), but the monotone never breaks. Important: this was the specific cross-check requested to rule out the VIXY-trap pattern. **It clears.**

---

## 7. What I tried to break and couldn't

Adversarial checks attempted, all failed to break the signal:

- Stricter walk-forward (IS=2018-2022 / OOS=2023-2026): held +17.78pp OOS
- Year-by-year over 9 years: 9/9 positive on n_vp==2
- Direction split: clean monotone on both
- Variant split: clean on 3 of 4; protected_swing is the lone weak case (documented)
- Macro window slice: clean on M1/M2/M3
- VIXY regime cross-check: clean on all 4 regimes
- Per-VP-level decomposition: signal is structurally interpretable (VAL→longs, VAH→shorts, POC→both) rather than statistical noise

The one piece I'd still want to monitor live: the lift looks *too* clean given how many features were mined. Recommend tracking n_vp_targets bucket × actual hit_2R quarterly for the next 12 months as the final acceptance gate before fully banking the filter.

---

## 8. Recommended actions

### Skip rule (the cleanest free-money item)
- **If n_vp_targets == 0 AND variant ∈ {bos, ifvg, no_fvg}: SKIP**
- 2,290 trades in the historical sample, hit_2R ≈ 30% (vs 42% base). 9pp drag in every era, every direction, every VIXY regime.
- Caveat: do not apply to `protected_swing` — there the 0-bucket isn't a drag.

### A+ tag
- **If n_vp_targets >= 2 AND variant ∈ {bos, ifvg, no_fvg}: flag as A+ setup**
- ~430 historical trades, hit_2R ≈ 62%, ~ +18-22pp lift across both eras.
- Strongest cell: short × n_vp==2 (66% OOS).

### Direction-aware confidence
- The single most reliable per-level pair is VAL-for-longs and VAH-for-shorts. Worth surfacing as a "direction-matched VA edge" tag separate from POC.

### Phase B candidate (out of scope here)
- Dynamic TP at VP — about 1/3 of winners stall within 0.5R of a VP level (mostly VAH/VAL). Worth a separate study on whether clipping winners at a VP level inside 1R improves equity curve vs holding to fixed 2R.

---

## Files

| file | purpose |
|------|---------|
| [run.py](run.py) | Reproducible pipeline (single script, no notebook deps) |
| [results/walk_forward.csv](results/walk_forward.csv) | A1 bucket × era table |
| [results/per_vp_level.csv](results/per_vp_level.csv) | A2 POC/VAH/VAL × direction × era |
| [results/stall_analysis.csv](results/stall_analysis.csv) | A3 peak proximity bands |
| [results/variant_x_vp.csv](results/variant_x_vp.csv) | A4 variant × bucket × era |
| [results/yearly_n_vp_2.csv](results/yearly_n_vp_2.csv) | A5 9-year n_vp==2 detail |
| [results/robustness.csv](results/robustness.csv) | A5 direction + macro + VIXY combined |
