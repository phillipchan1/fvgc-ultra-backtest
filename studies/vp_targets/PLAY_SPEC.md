# VP Magnet Play — Working Spec

This is a playbook entry, not a study. Numbers below come from
[analysis.md](analysis.md) and [results/play_economics.csv](results/play_economics.csv).

---

## What it is

A grade/skip overlay on the 30s FVGC baseline, scored at signal time by
**`n_vp_targets`** — count of yesterday's daily Volume Profile levels (POC,
VAH, VAL) that lie in the trade direction within **0.5R to 3R** of the
proposed entry, where R is `sl_dist`.

POC/VAH/VAL are known overnight. `entry_price` and `sl_dist` are set the
moment a signal fires. **The score is computable in real-time at signal
time** — not a backtest-only feature.

---

## The grades

| grade | rule | n/yr | hit_2R | PF | expectancy | size |
|-------|------|-----:|-------:|---:|-----------:|------|
| **A+** | n_vp≥2 + variant≠PS + **VA-edge** (VAL-for-long / VAH-for-short) + range≠contraction | ~11 | 84-92% | 10-13 | +1.5R | **1.5×** |
| **A**  | n_vp≥2 + variant≠PS | ~48 | 64-69% | 4.2 | +1.03R | **1.0×** |
| **B**  | n_vp==1 | ~200 | 51-54% | 2.6 | +0.70R | **0.5×** |
| **SKIP** | n_vp==0 + variant ∈ {bos, ifvg, no_fvg} | (drops ~210/yr) | 28-33% | 1.35 | +0.21R | — |
| **N/A** | protected_swing variant | ~76 | base | base | base | use default — n_vp does not discriminate here |

Notes:
- "PS" = `protected_swing`. n_vp_targets does *not* discriminate within PS
  (see A4 in analysis.md), so the grading framework does not apply to that
  variant — trade it on its own merit.
- "VA-edge" = `r_signed(VAL) ∈ [0.5, 3.0]` for longs, `r_signed(VAH) ∈ [0.5, 3.0]`
  for shorts. It's *not* the same as `n_vp≥2`; it's the
  **direction-matched VA boundary specifically** sitting ahead. A+ requires both.

---

## Frequency & cadence (so you know what to expect)

- **51 setups/year** at grade A or above (one a week on average).
- Median gap between A-grade setups: 6 trading days.
- 95th percentile gap: 26 days.
- **Max gap historically: 65 trading days (~3 months).** Budget for that
  psychologically; do not force trades during the dry spells.
- Strongest year (n_vp≥2 count): 2025 (109). Weakest: 2019 (14).

---

## Entry

Standard FVGC entry. The grading overlay does not change the entry — it
changes whether you take it and how big.

At signal time:
1. Compute `r_signed(POC) = (POC − entry)/sl_dist`, flipped sign for shorts.
2. Same for VAH and VAL.
3. `n_vp_targets = sum of three in [0.5, 3.0]`.
4. Look up the grade in the table above.
5. If SKIP: pass. If A+ / A / B: take at the indicated size.

---

## Stop loss

Unchanged from the baseline FVGC model: SL is set by FVG geometry at signal
time. `sl_dist = |entry - SL|` is the R unit for everything below.

---

## Take profit & stop management (per grade)

Full bar-by-bar sim of 12 rules across A / A+ / B cohorts in
`results/rm_sim_A.csv`. Highlights:

### A-grade — Stop to BE at +1.5R, TP +2.5R (Rule G)

| rule | exp R | PF | max DD | max consec losers |
|------|------:|---:|-------:|------------------:|
| baseline -1R/+2R | +0.594 | 2.29 | −10R | 7 |
| fixed -1R/+2.5R | **+0.611** | 2.18 | −12.2R | 8 |
| **G: -1R, BE@+1.5R, +2.5R** | +0.580 | **2.48** | **−10R** | **5** |

Rule G wins on PF and consistency, costs only 0.03R/trade vs the
expectancy-best rule. **WR drops to 40%** (BE scratches resolve as 0R, not
+R), so the trader has to accept "60% scratch-or-lose, 40% real winners".

### CRITICAL — BE@1R is a trap on this cohort

Moving stop to BE at +1R (Rule D / E) costs −0.16R of expectancy per trade
with no PF gain. Too many trades push to +1R, get scratched on the retest,
then continue to the original TP. Don't do this. BE@+1.5R is the threshold.

### A+ cell — run to +3R, NO BE (Rule C)

| rule on A+ cell | exp R | PF | max DD |
|-----------------|------:|---:|-------:|
| **C: -1R / +3R fixed** | **+2.07** | **11.17** | **−2R** |
| B: -1R / +2.5R fixed | +1.78 | 9.74 | −2R |
| G: BE@+1.5R / +2.5R | +1.72 | 10.19 | −2R |

80% WR, winners actually run. BE clips them. Max DD over 9 years = −2R
(literally two consecutive losers total).

**Why not run to the moon?** MFE distribution on winners in this cohort:

| cohort | mfe p25 | median | p75 | p90 | % winners reaching 3R | 4R |
|--------|--------:|-------:|----:|----:|----------------------:|---:|
| n_vp==0 winners | 4.04 | **8.23** | 13.1 | 17.8 | 84% | 75% |
| n_vp==1 winners | 4.07 | 6.08 | 8.68 | 12.7 | 87% | 76% |
| n_vp==2 winners | 3.09 | **4.27** | 5.78 | 7.34 | 77% | 59% |

When VP magnets are ahead, the move *converges* to the magnet — median MFE
4.3R vs 8.2R with no magnet. So this cohort is structurally a "two-handle
move into magnet" play, not a "let it run forever" play.

---

## Position sizing & per-grade exits

| grade | size | stop | TP | BE move | reason |
|-------|-----:|------|-----|---------|--------|
| **A+** | 1.5× | −1R | **+3R** | **none** | 80% WR, real runners — BE clips them. Max DD −2R historically. |
| **A**  | 1.0× | −1R | **+2.5R** | **BE@+1.5R** | best PF (2.48) & loser-streak control (5). −0.03R exp vs no-BE. |
| **B**  | 0.5× | −1R | +2.5R or +3R | none | marginal cohort (PF 1.14-1.16). Half-size for emotional headroom. |
| SKIP   | 0    | — | — | — | n_vp==0 + variant ∈ {bos, ifvg, no_fvg}. PF 1.30, drag. |
| N/A    | 1.0× | model default | model default | model default | protected_swing — overlay doesn't apply. |

**Worst historical drawdown (9 years, A-grade, rule G):** −10R cumulative.
Max consecutive losers: 5. At 1.0× this is −5R single-streak drawdown. Plan
2× emotional headroom (−10R per streak budget).

**A+ cell historical max DD: −2R.** That's not a typo — only 2 consecutive
losers occurred across the full 9-year sample.

---

## Confluence stacking (the score)

These are the top stacks vs the base play. Use to confirm A+ grading or to
upgrade an A to A+ when in doubt:

| confluence | n | wr_2R | PF | OOS wr_2R |
|------------|--:|------:|---:|----------:|
| base: n_vp≥2 & variant≠PS | 435 | 64.1% | 4.17 | 64.9% |
| + VA-edge & variant==bos | 50 | **86.0%** | **12.29** | 84.6% |
| **+ VA-edge & range≠contraction** | 96 | 84.4% | 10.80 | **91.8%** |
| + VA-edge (any direction-matched VA) | 123 | 83.7% | 10.30 | 87.0% |
| + range≠contraction | 279 | 69.2% | 4.80 | 69.9% |
| + macro_window in M1/M2 | 256 | 65.6% | 4.17 | 69.2% |
| + variant==bos | 146 | 64.4% | 4.08 | 62.8% |

**The two A+ qualifying stacks are robust in OOS** (84% and 92%). The other
confluences (bos, M1/M2, gap_bucket, range_regime alone) are *useful but
already largely captured* by n_vp≥2 — the lift is modest. Don't over-engineer
the score; the structural signal IS the VA edge.

---

## What's still unverified (live-monitor list)

The signal passed adversarial walk-forward, but it was found by mining 90+
features. The honest list of remaining doubts:

1. **VP feature in live tooling.** Need to confirm `tools/morning_briefing.py`
   (or equivalent) actually surfaces POC/VAH/VAL at 9:30 with the same
   definition (prior RTH session, not overnight, not 24h). The signal becomes
   useless if the live numbers diverge from the backtest definition.
2. **First-quarter live tracking.** Log every FVGC signal with computed
   n_vp_targets + final outcome for the next 12 weeks. If A-grade live WR
   falls below 55%, demote to B-grade until investigated.
3. **Dynamic TP at VP** (Phase B candidate). About 36% of winners peak within
   0.5R of a VP level (mostly VAH/VAL). A "scale half at first VP / runner to
   2.5R" approach might improve PF further. Out of scope for the working
   spec — test offline first.
4. **Today's developing VP vs prior-day VP.** The backtest uses the prior
   day's profile. As the session unfolds, today's developing POC may also
   matter. Not tested. Use prior-day for now.

---

## Pre-market briefing card (what to surface each morning)

The morning briefing should answer four questions before 9:30:

1. **Today's VP anchors:** POC=__, VAH=__, VAL=__ (from prior RTH session).
2. **Hypothetical n_vp for the obvious entries:**
   - Long at OR.H: how many VP levels lie 0.5-3R above? (proxies a breakout-long grade)
   - Short at OR.L: how many VP levels lie 0.5-3R below? (proxies a breakdown-short grade)
3. **VA-edge alignment:** is VAL above or below current price? VAH? This
   tells you whether a long or short would qualify for A+ if the FVGC fires.
4. **Range regime:** today's 5-day rth_range bucket. Contraction days
   demote A+ → A.

This is a straight extension of the existing `tools/morning_briefing.py` —
plug in the daily_volume_profile read and surface a one-line "VP grid"
section.

---

## Sanity checks you should run on day 1 of live use

- [ ] On the *next* FVGC signal: compute n_vp_targets by hand from VPs and
      compare to whatever the live tool reports. Numbers should match exactly.
- [ ] Run `studies/vp_targets/run.py` on the current trades.csv after the
      next month of live data and confirm the walk-forward verdict still PASS.
- [ ] After 25 A-grade live trades: hit_2R should be in [55%, 75%]. Outside
      that range, escalate.
