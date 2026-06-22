# Study: Pre-registered overlay hypotheses on the frozen FVGC v2.0.5 model

**Run:** `python studies/overlay_hypotheses/run.py` → `results/family_results.csv`, `results/console_report.txt`
**Model:** frozen v2.0.5, **unchanged**. **Universe:** `logs/baseline_trades.csv.preserve` (real 8-yr baseline).

---

## Setup, universe, and two facts that frame everything

**1. The live `logs/baseline_trades.csv` is a clobbered 2024–26 slice and cannot support the
pre-registered split.** The protocol requires *develop through 2023, lock, evaluate on 2024–25*.
That needs pre-2023 trades, which only exist in `baseline_trades.csv.preserve` (2018-01-02 →
2026-05-15, **4 542** tradeable win/loss trades). All numbers here come from the `.preserve`
universe. The "~1 572 trades / 51.7% WR" cited in earlier docs is a more-recent-slice artifact;
on the full 8 years the baseline WR is **~49.5%**.

**2. The model is fixed 1R:1R (`RR_RATIO=1.0`).** Every win = +1.0R, every loss = −1.0R. Therefore
`expectancy(R) = 2·WR − 1` and base-model `PF = WR/(1−WR)`. **The promotion bar "≥65% WR AND
≥2.0 PF" collapses to WR ≥ 66.7%** for the base target (PF 2.0 ⟺ WR 66.7%). PF only decouples from
WR for reconstructed >1R targets (H5/H1).

**Era base rates (the most important context for reading every cell below):**

| Era | Years | n | WR | PF | E[R] |
|-----|-------|---|----|----|------|
| IS  | 2018–2023 | 2 773 | **47.9%** | 0.92 | −0.043 |
| OOS | 2024–2025 | 1 441 | **52.9%** | 1.12 | +0.058 |
| TAIL| 2026 (partial) | 328 | 48.5% | 0.94 | −0.030 |

The base system is **a coin flip at 1R over the full history** (pooled E[R] ≈ 0). There is a real
+5pp WR regime shift from IS to OOS. **Most "OOS improvements" below are this base-rate drift, not
the overlay.** Read every cohort against *its own era's* base rate.

**Statistical protocol as implemented:**
- Within-era label permutation (20 000 perms) → null = the era's base rate.
- Two-sided p reported for the FDR family (`p2`); one-sided directional p (`p1`) shown alongside.
- One combined family → Benjamini-Hochberg FDR at **q = 0.10** across all 15 valid tests.
- Min n = 30 per cell (smaller cells reported but excluded from the family).
- **Positive control passed:** null calibration 5.2% at p<0.05 (expect ~5%); synthetic 70%-win
  oracle recovered at p = 0.0008.
- Causal discipline: features are tiered by availability time. `or_45min_range` (known 10:15),
  `macro_2/3/4`, `rth_*` etc. are **lookahead for 9:30–9:45 entries** and are excluded from filters.

---

## Per-hypothesis results

### H1 — Opening-window FVG **shorts** (`fvg_created_at` ∈ 09:29:30–09:31:00, short only)

| Era | n | WR | PF | E[R] | p2 (p1) |
|-----|---|----|----|------|---------|
| IS  | 49 | **53.1%** | 1.13 | +0.061 | 0.558 (0.279) |
| OOS | 50 | **72.0%** | 2.57 | +0.440 | 0.0078 (0.0039) |
| TAIL| 10 | 70.0% | 2.33 | +0.400 | n<30 |

By year: 2020 50%, 2021 50%, 2022 60%, 2023 45.5% — then 2024 60%, **2025 80%** (n=30), 2026 70%.
The 2018–19 "100%" is n=2 / n=1 noise.

**The edge is real in 2024–25 and absent in 2018–23.** Per protocol it must clear the bar in
**both** legs; it fails IS outright (53%, p=0.56). Under one-sided directional p the OOS leg would
clear FDR (`p_bh≈0.0585`); under two-sided it does not (`p_bh≈0.117`) — but this is moot because IS
fails. **Critically, the prior "8-yr validation" (and the `project_opening_fvg_short` memo, ~70% WR)
was computed on the live 2024–26 slice — i.e. on this very OOS window — so it was never out-of-sample
before 2023.** This run is the first genuinely independent pre-2023 test, and the signal isn't there.

**>1R target (this cohort):** OOS median MFE = **4.25R** — these trades run hard. Reconstructed
brackets: OOS 2R E[R]=+0.98/PF 3.88, 3R E[R]=+1.36/PF 4.58; IS 3R PF 2.07. A >1R target is strongly
supported *if you take the cohort* — but the cohort selection is the regime-fragile part.

**Verdict: EXPLORATORY** (caught regime-dependence; not a promotable 8-yr edge — fails IS).

### H2 — W1-alignment (entry direction vs first-15m candle; entries ≥ 09:45 only, so causal)

| Cohort | Era | n | WR | PF | E[R] | p2 (p1) |
|--------|-----|---|----|----|------|---------|
| aligned | IS | 1 103 | 49.9% | 0.99 | −0.003 | 0.094 (0.047) |
| aligned | OOS | 632 | 55.5% | 1.25 | +0.111 | 0.083 (0.042) |
| aligned | TAIL | 142 | **43.7%** | 0.78 | −0.127 | 0.158 (0.079) |
| counter | OOS | 412 | 49.3% | 0.97 | −0.015 | 0.096 (0.048) |

Aligned beats counter by ~6pp in OOS (55.5 vs 49.3) but aligned IS is dead-on base rate (49.9 vs
47.9) and **TAIL reverses** (43.7%). Nothing approaches 66.7%; nothing survives FDR.

**Verdict: REJECT** as a per-trade edge. Mild, unstable directional tilt — live-read only (§3).

### H4 — Post-sweep continuation (ON high/low swept *before* entry, trade in sweep direction)

| Cohort | Era | n | WR | PF | E[R] | p2 (p1) |
|--------|-----|---|----|----|------|---------|
| continuation | IS | 986 | 47.4% | 0.90 | −0.053 | 0.730 (0.365) |
| continuation | OOS | 562 | 55.7% | 1.26 | +0.114 | 0.099 (0.049) |
| reversal (contrast) | OOS | 329 | 51.1% | 1.04 | +0.021 | 0.498 |

Continuation rides the era base rate (IS 47.4 ≈ base 47.9; OOS 55.7 vs base 52.9 = +2.8pp). Fails
FDR; far from the bar. The "97% sweep / 100% continuation" descriptive lore does **not** translate
to a tradeable per-trade edge.

**Verdict: REJECT.**

### H3 — Exclusion overlay ("do-not-trade" filter from low-WR combos)

Re-derived avoid combos on **IS only**, using **strictly causal pre-entry features** (direction,
9:30 candle dir, gap sign, overnight dir, prior-day position, VIXY regime, FOMC week) —
deliberately **excluding `or_45min_range`**, which drove the prior combo search's 21–28%-WR avoid
cells but is a 10:15 lookahead.

**No causal pre-entry combo reaches ≤35% IS WR at n≥30.** The worst causal cells sit ~38–43% IS WR,
and most **do not hold OOS**:

| Worst causal combo | IS n | IS WR | OOS n | OOS WR |
|--------------------|------|-------|-------|--------|
| bull930+gap_up+on_dn | 34 | 38.2% | 23 | 56.5% |
| gap_up+on_dn | 76 | 40.8% | 41 | 53.7% |
| bear930+pd_dn+elevated_vixy | 89 | 42.7% | 117 | 57.3% |
| short+fomc+elevated_vixy | 32 | 40.6% | 56 | 39.3% |
| short+bull930+on_dn | 352 | 43.2% | 99 | 40.4% |

The handful that stay low (FOMC+elevated-VIXY shorts; short into a bullish-930 after an down
overnight) are weak and small. **The prior "avoid list" was a lookahead artifact.** No deployable
causal do-not-trade overlay is recoverable, so H3 contributes no FDR test.

**Verdict: REJECT** (and a useful confirmation that the old exclusion edge was `or_45min_range`
contamination).

### H5 — Target study (MFE/MAE; reconstructed fixed brackets {target = kR, stop = 1R})

Reconstruction validated: at k=1.0 it reproduces the model exactly (`hit_1_0R == win`, 0 mismatches).
`eod-resid` (reached neither +kR nor −1R, scored 0R) is small — ≤21 of 2 773 for ALL-IS.

E[R] / PF by target, **consistent across BOTH eras** (the only finding that is):

| Cohort | Era | 1R | 1.5R | 2R | 2.5R | 3R |
|--------|-----|----|------|----|----|----|
| ALL | IS | −0.04 / 0.92 | +0.11 / 1.19 | +0.21 / 1.35 | +0.29 / 1.45 | +0.34 / 1.51 |
| ALL | OOS | +0.06 / 1.12 | +0.22 / 1.42 | +0.37 / 1.69 | +0.48 / 1.83 | +0.57 / 1.95 |
| shorts | IS | −0.05 / 0.91 | +0.11 / 1.19 | +0.21 / 1.36 | — | +0.34 / 1.51 |
| macro1 (9:30–9:45) | OOS | +0.05 / 1.11 | +0.22 / 1.44 | +0.41 / 1.77 | — | +0.64 / 2.10 |
| opening_short | OOS | +0.44 / 2.57 | +0.75 / 3.50 | +0.98 / 3.88 | — | +1.36 / 4.58 |

**The model's entries have favorable-excursion skew the 1R target throws away** (ALL OOS median MFE
= 1.32R; IS 0.92R). Extending the target lifts E[R] from ~0 to +0.2–0.4R **in IS as well as OOS** —
this is structural, not regime-dependent. **But it does not satisfy the joint promotion bar:**
higher targets lower the win rate, so broad-book PF tops out ~1.5 (IS) / ~1.95 (OOS) at 3R — only
the already-selected sub-cohorts (opening_short, macro1-OOS) clear PF 2.0.

**Verdict: EXPLORATORY / actionable** — the strongest, most robust effect in the study, but it is an
**exit-management** change (target overlay), and it raises expectancy without manufacturing a
66.7%-WR / 2.0-PF system on the broad book.

---

## 1. Entry filters that raise WR/PF (with frequency cost)

Honestly: **none clear the promotion bar (WR ≥ 66.7%) out-of-sample with a stable IS leg.** The
only large-lift entry filter is **opening-window shorts (H1)** — OOS 72% WR / PF 2.57 — but it is a
**2024–25 regime effect** (53% in 2018–23) and costs frequency (~25 trades/yr → ~8/yr at tier).
Treat it as a *watch-list* entry, not a validated filter. Smaller tilts (W1-aligned +6pp OOS,
post-sweep-continuation +3pp OOS) are within base-rate drift and fail FDR.

## 2. "When NOT to trade" exclusion list

**No causal exclusion overlay survives.** The prior FDR-significant low-WR cells (21–28% WR) were
built on `or_45min_range`, unknown until 10:15 and thus unusable at a 9:30–9:45 entry. Rebuilt on
causal pre-entry features, the worst cells only reach ~40% IS WR and mostly revert to ≥53% OOS. The
two that persist (and even these are weak, low-confidence): **FOMC-week shorts in an elevated-VIXY
regime** (40.6% IS → 39.3% OOS) and **shorts taken into a bullish 9:30 candle after a down
overnight** (43.2% IS → 40.4% OOS). Use as soft de-emphasis at most, not a hard filter.

## 3. Live-read context (NOT validated as per-trade entry edge)

For the 9:45 discretionary read only — directionally suggestive, statistically not an edge:
- **W1 (first-15m) direction:** trading *with* W1 ran ~6pp better than *against* it in 2024–25
  (55.5% vs 49.3%), but the effect is absent in 2018–23 and reversed in 2026. Lean, don't rely.
- **Overnight sweep state:** continuation after an ON-high/low sweep tracks the base rate; the sweep
  *reversal* contrast is also flat (~51%). The sweep tells you structure, not odds.
- **Target awareness:** entries routinely extend past 1R (OOS median MFE 1.32R; opening-shorts 4.25R)
  — the actionable read is on the **exit**, not the entry.

---

## Honest summary

**Nothing new cleared the promotion bar, and the headline candidate was a caught false positive.**
Re-tested on the full 8-year `.preserve` universe with a genuine pre-2023 lock, the opening-window
short (H1) — previously believed "8-yr validated" at ~70% WR — is **53% in-sample (2018–23) and 72%
out-of-sample (2024–25)**: the prior validation had unknowingly run on the recent slice, so the
"edge" is a 2024–25 regime artifact, not a stable structural edge (EXPLORATORY, not PROMOTE). W1
alignment (H2) and post-sweep continuation (H4) are indistinguishable from era base-rate drift and
fail FDR (REJECT). The "do-not-trade" exclusion overlay (H3) collapses once the lookahead
`or_45min_range` is removed — there is no deployable causal avoid list (REJECT). The single robust,
IS-and-OOS-consistent result is mechanical, not a filter: **the frozen 1R target throws away real
favorable-excursion skew, and extending it to ~2R roughly triples per-trade expectancy in both eras
(H5)** — but it lowers win rate and tops the broad book out near PF 1.5–1.95, short of the 2.0 bar.
Net: at 1R the FVGC entry model is a coin flip over 8 years; the only durable lever found is on the
exit, and the most interesting entry cohort is real only in the most recent regime.
