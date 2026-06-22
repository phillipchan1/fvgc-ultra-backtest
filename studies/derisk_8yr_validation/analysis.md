# Derisk @50% + tp3R — 8yr validation & "when to go for more R"

**Date:** 2026-06-02. Derived from `studies/baseline/results/trades.csv` (full 8yr 30s,
n=4,542 tradeable) — reusing precomputed `entry_idx`, so no signal regeneration.
Only a lightweight high/low path-walk was needed for the BE-stop ordering that
baseline doesn't store. `run_fast.py` is the canonical script (`run.py` = slow re-sim, deprecated).

**Validation gate PASSED:** reconstructed WINDOW (2023-10→2026-03) lock0.5_tp3R =
PF 1.379 / WR 69.2% / +0.116R vs worktree exact sim 1.367 / 68.6% / +0.115R.
(n 1769 vs 1575 — baseline file is a slightly newer model gen; PF matches to ±0.012.)

## Q1: Was the Notion insight backtested on all data? NO — just 2.5yr (Oct23–Mar26).

## Q2: Does it hold on the full 8yr? PARTIALLY.

| Era | n | baseline PF | lock0.5_tp3R PF | lift |
|---|---|---|---|---|
| WINDOW (Notion, 2.5yr) | 1769 | 1.10 | **1.38** | +0.28 |
| PRE 2018–2023 (untested 5.5yr) | 2657 | **0.91** | **1.21** | +0.30 |
| ALL 8yr | 4542 | **0.98** | **1.27** | +0.29 |
| POST 2026 (n=116) | 116 | 0.84 | 0.98 | +0.14 |

**Two separate truths:**
1. **The BE@0.5R + tp3R *rule* is robust** — it lifts PF by a steady **+0.28–0.30 over
   baseline in every era**. The risk-management mechanic generalizes.
2. **The blind FVGC *pattern* is much weaker than the headline suggests.** Over 8yr the
   rule's absolute PF is **1.27, not 1.37**, and baseline FVGC is a **coinflip-to-losing
   (PF 0.98)**. 2024–26 was an unusually kind regime. tp3R-over-tp1R adds only **~+0.01R/trade** —
   real but marginal; the BE lock does the heavy lifting (Notion said this).

## Q3: WHEN to go for more R / size up — conditional reach (8yr, generalizes across eras)

Overall reach: P(2R)=42%, P(3R)=36%, P(5R)=26%.

### Pre-trade signals (knowable at entry — use for sizing & TP choice)

| Signal | Go BIG / tp3R+ / size up | Go LIGHT / tp1R / skip |
|---|---|---|
| **45-min OR width** ⭐ | **Q5 widest**: PF 1.89, P3R 47%, Δ(3R)+0.051 | **Q1 narrow**: PF 0.87 (losing), P3R 24%, Δ negative |
| **FVG size** | **>20pt**: bWR 56%, PF 1.29, P3R 44% | ≤5pt: PF 1.14, weakest |
| **Variant** | **protected_swing**: PF 1.38, P3R 42%, P5R 35% (best runner) | bos/ifvg modest |
| **Direction** | **long**: tp3R Δ+0.017 (benefits from runners) | short: Δ 0.000 (banks edge by 1R) |
| **SL distance** | >50pt: high WR 59%/PF 1.41 BUT low reach → use tp1R/2R, not 3R |  |
| **Entry time** | 09:45–10:00 runs furthest | 09:30–09:45 worst (PF 0.92) |

**OR width is the dominant lever** (= the "Range Determines Reach" companion insight; it
generalizes on 8yr). Narrow-OR days are where blind FVGC actually loses money — the place
to size down or stand aside, not to chase 3R.

### In-trade signals (knowable only after you're in profit — "let it run" rules)
Conditioned on reaching 1R, so not entry filters:
- **Hit 1R fast (≤4 bars)** → P3R **80%**, P5R **64%** → hold for 3R+.
- **fast-to-1R + wide OR** → P3R **80%**, P5R **63%**, Δ(3R)+0.094 → the max-R, size-up cell.
- Slow grind to 1R (>12 bars) → P3R 60% → take 1R/2R, don't push.

## Caveats
- Reach (Part B) is exact from baseline `mfe_r`/hit flags. Derisk PF (Part A) is the
  path-walk reconstruction, validated to ±0.012 PF against the worktree sim.
- Speed/combo cells with bWR=100% are post-1R diagnostics, not standalone entry edges.
- No transaction costs/slippage; same-bar trigger optimism (matches original study).
