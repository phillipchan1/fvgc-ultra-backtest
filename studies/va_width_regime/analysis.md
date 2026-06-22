# Value Area Width as a Day-Type Filter

## Causal Audit Status

**KILL REINFORCED — 2026-05-21.** `va_width` is sourced from `daily_volume_profile.csv` joined on `date` — a full 9:30-16:00 session aggregate, unknowable at trade time. The headline already concluded null; the contamination doesn't change the verdict but reinforces it. The "entry-vs-POC" bycatch signal is **also contaminated** in the same way (compares entry to today's full-session POC). It needs to be re-evaluated with lag-1 VP before any follow-up.

---

**Status:** Hypothesis rejected as a day-type *filter*. Surprise: a much
stronger trade-level signal (entry-vs-POC, "reversion-to-POC") was uncovered
incidentally and deserves its own follow-up.

**Date:** 2026-05-20
**Author:** Phil Chan (with Claude)
**Data:** `studies/baseline/results/trades.csv` (4,548 non-skip trades) joined
to `data/levels/daily_volume_profile.csv` (2,158 days).
**Split:** IS = 2018-2022 (n=2,193, base hit_2R = 40.0%) ·
OOS = 2023-2026 (n=2,355, base hit_2R = 44.2%). All quartile cuts and z-score
parameters derived from IS-only.

NQ tripled in price across the sample (6.5k → 30k), so raw `va_width` (points)
scales mechanically with price. The primary regime variable is
`va_width_pct = va_width / poc × 100`. Absolute and rolling-20d-z forms are
reported alongside.

---

## TL;DR

| Question | Answer |
|---|---|
| Does VA width alone predict hit_2R? | **No.** Max OOS lift across all four quartiles = **+3.78pp** (Q3). Below the +5pp kill floor. |
| Does VA width add lift on top of `n_vp_targets`? | **Spread exists (13.66pp OOS) but is noise-dominated.** The 18pp IS lift in the tight cell collapses to −14pp OOS. No coherent interaction. |
| Does the tight=reversion / wide=trend hypothesis hold? | **No — inverted and uniform.** Reversion-to-POC plays beat continuation by **~35-40pp OOS in every VA regime**, including Q4_wide (+18pp). VA width does not toggle the play type. |
| Verdict | **KILL as a regime filter.** Do NOT add VA-width to the pre-market briefing as a "tight day → reversion only" / "wide day → breakout only" gate. |
| Bycatch | **Entry-vs-POC ("reversion" trades) is a strong standalone trade-level filter** (+19 to +23pp OOS hit_2R lift across all VA regimes). Worth its own study — likely redundant with `n_vp_targets` (POC-in-direction), but the magnitude warrants confirmation. |

---

## Q1 — VA width distribution

| col | min | p10 | p25_IS | p50_IS | p75_IS | p90 | max | mean | std |
|---|---|---|---|---|---|---|---|---|---|
| `va_width` (pts) | 4 | 29 | 39 | 71 | 121 | 211 | 1,666 | 108.8 | 88.8 |
| `va_width_pct` (%) | 0.040 | 0.282 | 0.430 | 0.685 | 1.122 | 1.492 | 9.558 | 0.803 | 0.605 |
| `va_width_z` (20d) | −2.37 | −1.11 | −0.78 | −0.23 | +0.56 | +1.56 | +14.20 | +0.07 | 1.30 |

- **Long-tail** (max 9.6% of POC, mean 0.8%); roughly log-normal in `va_width_pct`. No bimodality — no natural day-type cluster, the bucketing is imposed.
- **IS quartile cuts** frozen for the rest of the study:
  - `va_width_pct`: Q1 ≤ 0.43%, Q2 ≤ 0.69%, Q3 ≤ 1.12%, Q4 > 1.12%
  - `va_width` absolute: Q1 ≤ 39, Q2 ≤ 71, Q3 ≤ 121, Q4 > 121

Because of the price-scaling problem, the absolute cuts dump nearly all
post-2023 trades into Q3-Q4 (only 34/2355 OOS trades land in absolute-Q1).
`va_width_pct` is more balanced and is the primary view.

## Q2 — per-quartile hit_2R

### `va_width_pct` quartiles ([results/hit_2R_by_va_quartile.csv](results/hit_2R_by_va_quartile.csv))

| bucket | n_IS | hit_2R_IS | lift_IS_pp | n_OOS | hit_2R_OOS | lift_OOS_pp |
|---|---|---|---|---|---|---|
| Q1_tight | 173 | 28.3% | **−11.7** | 553 | 41.8% | −2.5 |
| Q2 | 482 | 39.8% | −0.2 | 688 | 44.2% | −0.1 |
| Q3 | 673 | 40.6% | +0.5 | 760 | 48.0% | **+3.8** |
| Q4_wide | 865 | 42.1% | +2.0 | 354 | 40.1% | −4.1 |

**The IS ordering (tight < wide) inverts in OOS** — the IS-best bucket
(Q4_wide, +2.0pp IS) becomes the worst in OOS (−4.1pp). The OOS-best is Q3
(+3.8pp), still below the +5pp threshold.

Year-by-year stability of IS-best (Q4_wide):
positive lift in 5/9 years, but two of four OOS years are sharply negative
(2023: −8.3pp, 2025: −5.2pp). Not stable.

→ **K1 TRIPPED.** No quartile clears the +5pp OOS lift bar.

### Absolute quartiles ([results/hit_2R_by_va_width_abs.csv](results/hit_2R_by_va_width_abs.csv))

Shows the same shape but is contaminated by the price-scaling drift. Reported
for completeness, not used.

## Q3 — VA width × direction ([results/va_x_direction.csv](results/va_x_direction.csv))

| direction | va_pct_q | n_OOS | hit_2R_OOS | lift_OOS_pp |
|---|---|---|---|---|
| long | Q1_tight | 277 | 45.1% | +1.4 |
| long | Q2 | 385 | 46.5% | +2.8 |
| long | Q3 | 401 | 46.1% | +2.4 |
| long | **Q4_wide** | 159 | **28.3%** | **−15.4** |
| short | Q1_tight | 276 | 38.4% | −6.4 |
| short | Q2 | 303 | 41.3% | −3.6 |
| short | Q3 | 359 | 50.1% | +5.3 |
| short | **Q4_wide** | 195 | **49.7%** | **+4.9** |

The strongest pattern: **wide-VA days are bad for longs (−15.4pp OOS) and OK
for shorts (+4.9pp OOS)**. Plausible — wide-VA days tend to be selloffs.
Useful as a directional skew, *not* as a play-type toggle. But n_OOS for the
Q4_long cell is small (159 trades over 4 years) and the IS sign was flat
(−0.4pp), so this is a directional caution flag at best, not a rule.

## Q4 — VA × `n_vp_targets` ([results/va_x_vp_filter.csv](results/va_x_vp_filter.csv))

The redundancy check. If VA-width is just a noisy proxy for `n_vp_targets`,
the lift should disappear once we condition on `n_vp_targets ≥ 1`.

| vp_cohort | va_pct_q | n_OOS | hit_2R_OOS | lift vs cohort base (OOS, pp) |
|---|---|---|---|---|
| n_vp==0 (base 32.9%) | Q1_tight | 237 | 19.4% | −13.5 |
| n_vp==0 | Q2 | 287 | 31.7% | −1.2 |
| n_vp==0 | Q3 | 437 | 39.1% | **+6.2** |
| n_vp==0 | Q4_wide | 229 | 36.7% | +3.7 |
| **n_vp≥1 (base 55.8%)** | Q1_tight | 316 | 58.5% | +2.8 |
| n_vp≥1 | Q2 | 401 | 53.1% | −2.7 |
| n_vp≥1 | Q3 | 323 | 60.1% | +4.3 |
| **n_vp≥1** | **Q4_wide** | 125 | **46.4%** | **−9.4** |
| n_vp≥2 (base 64.2%) | Q1_tight | 104 | 71.2% | +7.0 |
| n_vp≥2 | Q4_wide | 6 | 50.0% | −14.2 (n=6, ignore) |

K2 (`n_vp≥1` spread < 2pp) is **OK** — there *is* a 13.66pp OOS spread inside
the `n_vp≥1` cohort. But the IS→OOS sign flips that defeated Q2 are present
here too:
- The n_vp≥2 × Q4_wide cell went from +18pp IS to −14pp OOS (n_IS=32, n_OOS=6;
  no statistical content).
- The n_vp==0 × Q1_tight cell stays negative in both eras (−24 IS, −14 OOS) —
  that's the cleanest signal in the table, and it just says "if there's no
  VP target ahead AND the day is balance-tight, skip." But the lift is
  *negative* — it's an additional skip rule on top of `n_vp_targets==0`
  (which is already a skip). No incremental information.

**No coherent VA × VP interaction structure.** The n_vp_targets filter
absorbs the bulk of the predictive content; what VA-width adds on top is
noise.

## Q5 — Rolling 20d z-score ([results/hit_2R_by_va_z.csv](results/hit_2R_by_va_z.csv))

| bucket | n_OOS | hit_2R_OOS | lift_OOS_pp |
|---|---|---|---|
| tight_z (≤ −0.75) | 447 | 42.3% | −2.0 |
| mid_z | 1,372 | 44.5% | +0.2 |
| wide_z (≥ +0.75) | 536 | 45.3% | **+1.1** |

Relative-compression has *less* signal than absolute width. The rolling-z
framing doesn't rescue VA-width.

## Q6 — Reversion-to-POC vs continuation ([results/reversion_vs_trend.csv](results/reversion_vs_trend.csv))

The original hypothesis: tight-VA days favor reversion-to-POC; wide-VA days
favor continuation/breakout. Tested by tagging each trade as:
- **reversion** = entry on the far side of POC from trade direction
  (long below POC, short above POC) → trade targets POC
- **continuation** = entry on the near side of POC → trade moves away from POC

| va_pct_q | play_type | n_OOS | hit_2R_OOS | lift_OOS_pp |
|---|---|---|---|---|
| Q1_tight | reversion | 241 | **67.2%** | **+23.0** |
| Q1_tight | continuation | 312 | 22.1% | −22.1 |
| Q2 | reversion | 342 | **63.2%** | **+18.9** |
| Q2 | continuation | 346 | 25.4% | −18.8 |
| Q3 | reversion | 399 | **63.9%** | **+19.7** |
| Q3 | continuation | 361 | 30.5% | −13.8 |
| Q4_wide | reversion | 167 | **62.3%** | **+18.0** |
| Q4_wide | continuation | 187 | 20.3% | −23.9 |

**The hypothesis is wrong.** Reversion-to-POC plays beat continuation plays
by 35-45pp **in every VA regime, including Q4_wide.** VA-width is not the
toggle that flips the play type; the play type itself is the signal.

The bycatch is *much* bigger than the question being asked. Caveats before
declaring victory on the reversion finding:
- Almost certainly highly overlapping with `n_vp_targets` and specifically
  `poc_in_dir` (POC at 0.5-3R in trade direction implies the trade is moving
  *toward* POC, which by construction means entry is on the far side).
- The "reversion" tag is mechanical from entry vs POC at trade time, so it
  has zero look-ahead.
- This deserves a dedicated study to (a) separate it cleanly from
  `n_vp_targets`, (b) compute year-by-year, (c) compute profit factor with
  realistic stop discipline.

---

## Kill criteria evaluation

- **K1 (any va-quartile OOS lift ≥ +5pp): TRIPPED.** Max = +3.78pp (Q3).
- **K2 (`n_vp≥1` × va-pct OOS spread < 2pp): OK** (spread = 13.66pp), but the
  spread is dominated by IS→OOS sign flips in small cells. There is no
  reproducible interaction; the spread is variance, not signal.

→ **Overall verdict: KILL as a regime filter.** Do not add a
"today is a tight-VA / wide-VA day → use these setups" gate to the
pre-market playbook.

## What to actually do with this

1. **Drop VA-width from the briefing.** No tight/wide-VA day-type gate.
2. **Keep the directional caution flag (Q3):** wide-VA days are hostile to
   long FVGCs (−15pp OOS, n=159). Watch this — if it persists, it's a
   gating rule on its own.
3. **Spawn a follow-up on the entry-vs-POC ("reversion") trade-level filter.**
   The 35-45pp OOS gap is the largest single-feature spread seen in this
   project; if it survives orthogonalization against `n_vp_targets` /
   `poc_in_dir`, it's promotion to the playbook.
4. **Stop testing single-feature day-type gates derived from daily VP shape
   alone** without orthogonalizing against `n_vp_targets` first — the
   trade-level VP geometry seems to be where the edge lives.

## Files

- [run.py](run.py)
- [results/run.log](results/run.log)
- [results/va_width_hist.csv](results/va_width_hist.csv)
- [results/hit_2R_by_va_quartile.csv](results/hit_2R_by_va_quartile.csv)
- [results/hit_2R_by_va_width_abs.csv](results/hit_2R_by_va_width_abs.csv)
- [results/yearly_best_bucket.csv](results/yearly_best_bucket.csv)
- [results/va_x_direction.csv](results/va_x_direction.csv)
- [results/va_x_vp_filter.csv](results/va_x_vp_filter.csv)
- [results/hit_2R_by_va_z.csv](results/hit_2R_by_va_z.csv)
- [results/reversion_vs_trend.csv](results/reversion_vs_trend.csv)
