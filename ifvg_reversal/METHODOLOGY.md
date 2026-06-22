# IFVG Reversal — Methodology

How we build, validate, and refine the model. SPEC.md owns the *rules*; this
file owns the *process* for arriving at those rules.

**Current status: Step 1 complete (N=1438 / 5-year cohort). Step 2 — building lift tables.**

---

## The five-step sequence

### Step 0 — scaffold & detectors
Build the detectors (sweep, multi-TF FVG, chop), the pipeline (model.py), the
engine (fixed 1R), and a baseline study to confirm end-to-end correctness on
a small cohort. **Done as of v0.3.2.**

### Step 1 — generate population
Run the model with **deliberately loose defaults** on the full available
cohort (2018-2026) to produce a large enough study sample (≥100 trades).

The Step 1 model is intentionally over-inclusive — every gate is a hypothesis
we haven't tested yet, so we drop or relax all of them and let candidates
through with rich per-factor metadata attached. Each emitted row carries
flags for every factor we'll later analyze.

The Step 1 model is **not a trading strategy**. It's a candidate generator.

**Completion criterion:** `N ≥ 100` trades in the population CSV.

**Artifact:** `studies/ifvg_reversal_population/results/population.csv`.

### Step 2 — per-factor lift table
For each factor (gap size, body fraction, sweep tier, P/D position, reaction
quality, inversion latency, gap source TF, time-of-killzone, etc.), bucket
the population and measure: N, WR, PF, avg R, total P&L. Hold all other
factors at baseline (Step 1 defaults).

Output is one row per (factor, bucket) → a lift table that tells us which
factors carry real edge and which are noise.

**Methodological catches:**
- With ~10 factors × 4 buckets = 40 comparisons, ~2 will look significant
  by chance. Require `N ≥ 30` per bucket and bootstrap CI on PF before
  believing any single lift result.
- Non-monotonic lifts (U-shaped) are real findings, not bugs.
- A factor with no signal *is* a finding — drop it from confluence.

**Artifact:** one subfolder per factor: `studies/ifvg_reversal_factor_<name>/`.

### Step 3 — confluence stack
Take factors with measured lift. Score each signal 0..N by how many factors
are "lit up" at preferred levels. Backtest score thresholds (e.g., 3+, 4+, 5+)
to find the A+/B/C grading tiers.

Pattern reference: `Turtle Soup` study did this and shipped (see memory
[[project-turtle-soup]]). 5-factor additive score, threshold 3+ for trade,
4+ for A+.

**Artifact:** `studies/ifvg_reversal_confluence/`.

### Step 4 — IS/OOS validation
Hold out the last 6-12 months. Steps 1-3 use older data only. Then validate
the confluence model on the held-out window.

Pattern reference: `Win/Loss Discriminator` (see memory
[[project-win-loss-discriminator]]) — IS/OOS feature mining pipeline.

### Step 5 — promote to SPEC + playbook
Lock the confluence rules into SPEC.md as v1.0. Add to the during-session
playbook. Document explicitly which factors were tested and dropped.

---

## Step 1 — loose-default config

Listed deltas from v0.3.2 defaults (in `ifvg_reversal/constants.py`):

| Setting | v0.3.2 | Step 1 loose | Why |
|---------|--------|--------------|-----|
| `MIN_FVG_SIZE` | 8.0 | **6.0** | Test the 8pt floor empirically before assuming it |
| `CONFIRMATION_WINDOW_SECONDS` | 300 | **600** | 10-min window; capture slow-reaction tail |
| `MOMENTUM_BODY_FRACTION` | 0.50 | **0.30** | Test the body-fraction threshold empirically |
| Premium/Discount gate | enforced | **off** | Bucket P/D position post-hoc, don't pre-filter |
| Equilibrium veto | enforced | **off** | Bucket post-hoc |
| Chop filter | enforced | **off** | Tag each trade with chop flags, bucket post-hoc |
| Reaction quality (§5) | enforced | **off** | Tag stall / nuke / move-away as factors, bucket post-hoc |
| Killzone (§2) | enforced | **kept** | Without it, nothing makes sense — fixes the universe |
| Multi-TF detection (§6.1) | 30s/1m/2m/3m | **kept** | Structural, not a tuning param |
| Sweep criterion (§4.2) | wick + same-candle reclaim | **kept** | Same reason |
| Active sweep levels | tier 2-3 | **kept** | Tier 4-5 dropped for spec reasons (SPEC §4.5) |

**Cohort:** entire 2018-01-01 → latest available date. Hold out last 6 months
when we get to Step 4.

---

## Factor status table

Update one row per factor as Step 2 completes.

| Factor | Step 1 N | Bucketed? | Buckets used | Lift finding | Keep in confluence? | Artifact |
|--------|----------|-----------|--------------|--------------|---------------------|----------|
| sweep tier | — | — | 2 / 3 | — | — | — |
| sweep level (ON_high vs ON_low vs PD_high vs PD_low) | — | — | 4-way | — | — | — |
| sweep penetration (pts) | — | — | 1-3 / 3-5 / 5-10 / 10+ | — | — | — |
| gap size (pts) | — | — | 6-8 / 8-12 / 12-15 / 15+ | — | — | — |
| gap source TF | — | — | 30s / 1m / 2m / 3m | — | — | — |
| inversion latency (s) | — | — | 0-60 / 60-180 / 180-300 / 300-600 | — | — | — |
| momentum body fraction | — | — | 0.3-0.5 / 0.5-0.7 / 0.7-0.9 / 0.9+ | — | — | — |
| P/D position | — | — | strict / mid / wrong-side | — | — | — |
| reaction quality | — | — | clean / nuked / stalled / weak | — | — | — |
| chop day | — | — | clean / chop | — | — | — |
| killzone minute | — | — | 0-30 / 30-60 / 60-90 | — | — | — |
| direction | — | — | long / short | — | — | — |
| trade day-of-week | — | — | Mon..Fri | — | — | — |
| news adjacency | — | — | near / clear | — | — | — |

Update conventions:
- Each row's `Artifact` column points to the study folder that produced the
  bucketed result.
- Mark `Keep in confluence?` as Yes / No / Threshold (e.g., "Yes if body>0.7").
- A "No" with N≥30 per bucket is a real finding worth documenting.

---

## Reusable utilities (build once, use forever)

These should land in the repo at the right level (model-specific in
`ifvg_reversal/analysis/`, general-purpose at repo root) when the pattern
recurs.

- **Lift-table builder.** Input: a population CSV + factor column + bucket
  spec. Output: WR, PF, avg R, N, bootstrap CI per bucket. Use for every
  Step-2 factor.
- **Bootstrap PF confidence interval.** Sample trades with replacement,
  recompute PF, repeat 1000×, report 5th/95th percentile.
- **IS/OOS splitter.** Takes a date column and an OOS window; returns two
  views. Used for Step 4 on every model going forward.

Defer building until needed. First lift table will probably hand-code in
pandas; second one extracts the utility.

---

## Changelog

- **2026-05-20** — Methodology doc created at Step 1 entry. v0.3.2 confirmed
  as Step-0 scaffold (tuned-tight, not the Step-1 generator). Loose-default
  config above defines the Step-1 spec.
- **2026-05-20** — Step 1 complete on 5-year cohort (2021-05-16 → 2026-05-15)
  using v0.3.4 detectors with loose defaults. N=1438, WR 50.2%, PF 1.05 — clean
  breakeven population, no preselection edge baked in. Step 2 begins.
