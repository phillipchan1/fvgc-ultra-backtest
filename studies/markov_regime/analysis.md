# Markov-Regime Conditioning of FVGC Trades

## The question

A YouTube "hedge fund method" repackages **Markov regime-switching**: bucket each
day into bull / sideways / bear from a trailing 20-day return (±5%), build a 3×3
transition matrix, and trade the bull-minus-bear differential. Does any of this
help **our** edge — FVG continuation in the 9:30–10:15 ET window on 30s bars?

## Verdict on the method (before running anything)

- **As an intraday signal: no.** The matrix updates once per day off daily
  returns. It cannot say anything about 9:30–10:15 microstructure. Our 45-minute
  window isn't "too narrow" — it's on a different timescale entirely.
- **As a pre-market bias gate: testable.** Computed before the open, a daily
  regime can gate *which days / directions* we take and how we size. That is the
  only defensible application, and it's exactly the slot the playbook reserves
  for "bull/bear/neutral regime" / "60-day NQ return regime".
- **Two traps the video ignores:**
  1. *Mechanical stickiness.* The trailing-N-day state is autocorrelated by
     construction — consecutive windows overlap N−1 days — so the celebrated
     ~80% "persistence" is mostly an artifact, not predictive power. Measured on
     non-overlapping blocks it largely vanishes. **So we test the trades, not the
     matrix.**
  2. *Collapse to momentum.* Once stickiness is mechanical, the bull−bear signal
     reduces to "trailing 20-day return > +thr → long". That's 20-day time-series
     momentum (TSMOM) in Markov costume — real, but not novel and not intraday.

## What `run.py` does

1. **Daily close** series, anchored at the last bar ≤ 16:00 ET.
2. **Regime per trading day D** from the trailing-N-day return *as of D−1's close*
   — strictly look-ahead-safe (label known at the open). Bucketed at ±threshold.
3. **Tag** every baseline FVGC trade with its day's regime.
4. **Conditional table:** regime × direction → win rate, expectancy (R), profit
   factor, vs. the unconditional baseline. This is the *correlation* view.
5. **Alignment + permutation test:** "with regime" (long-in-bull + short-in-bear)
   vs "against". Significance via a **day-level** label shuffle (preserves
   intraday clustering, so the null variance isn't understated). This is the
   *is-it-just-noise* check — the closest we get to a causal read without a true
   experiment.
6. **Sensitivity grid** over (lookback ∈ {10,20,40}) × (threshold ∈ {3,5,8%}) so
   the conclusion doesn't hinge on the video's arbitrary 20-day / 5% choice.

## How to run

```bash
python studies/markov_regime/run.py                       # 20d / 5% default
python studies/markov_regime/run.py --lookback 40 --threshold 0.08 --perms 10000
python studies/markov_regime/run.py --no-sensitivity      # main combo only
```

Outputs land in `results/`: `trades_tagged.csv`, `conditional_table.csv`,
`permutation_summary.csv`.

## How to read the result

- **Worth wiring in** only if the *with-regime* expectancy beats *against-regime*
  by a margin that (a) **survives the permutation test** (p < 0.05) and (b) is
  **stable across the sensitivity grid**. One significant cell among nine that
  flips sign when you change the lookback is overfitting, not edge.
- **Direction matters more than the gate.** If longs only earn in bull regimes
  and shorts only in bear, that's a usable filter. If the lift is symmetric and
  small, the regime is just re-deriving what variant/time-of-day filters already
  capture.
- **Watch the sample.** Gating *removes* counter-regime trades. With the book
  already confined to a 45-minute window, a per-cell `n` in the low tens is noise
  — treat those rows as directional hints, not decisions.
- **Logic is unit-tested** (see the smoke tests in the PR/commit): a planted
  with-regime edge is recovered at p≈0.001; pure noise is not flagged.

> Engineered as a *bias gate*, not a signal generator. If the numbers come back
> flat, the correct conclusion is that FVGC's edge is regime-agnostic at this
> timescale — which is itself worth knowing before building the full HMM.
