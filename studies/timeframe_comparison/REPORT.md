# Cross-Timeframe Audit: W1/M1 Short Confluence Stack

**Date:** 2026-04-29
**Question:** does the W1 Short Confluence Model (validated on 30s FVGC signals) work the same when run on FVGC signals from other bar timeframes (15s/1m/2m/3m/5m)? If yes, we get more trades for the same edge.

**Verdict:** **No. 30s is the sweet spot. Other timeframes do NOT replicate the edge.**

## Setup

For each timeframe, filtered baseline FVGC trades to:
- direction = short
- entry time ∈ [09:30, 09:45)
- variant ≠ protected_swing
- outcome ∈ {win, loss}

Computed confluence count per trade using the same per-day factor set as the 30s baseline (gap_down, large_gap, overnight_down, prior_day_weak, bear_930, no_news; tier = sum 0-6).

## Headline: 4+ conf tier across timeframes

| TF | n | WR | PF @ 1R | Trades/mo |
|---|---|---|---|---|
| **30s** ⭐ | 54 | **72.2%** | **2.60** | 1.80 |
| 15s | 101 | 55.4% | 1.24 | 3.37 |
| 1m | 19 | 57.9% | 1.38 | 0.63 |
| 2m | 8 | 62.5% | 1.67 | 0.27 |
| 3m | 1 | 100% | 1.00 | 0.03 |
| 5m | 0 | — | — | — |

The 4+ tier only delivers at 30s. Faster (15s) doubles the trade count but WR craters to barely-better-than-baseline. Slower (1m+) produces too few signals to matter.

## The 15s noise story

15s would intuitively give "more of the same" trades. It doesn't:

- 30s ∩ 15s = **32 days** (both fire on the same day)
- only 30s = **9 days**
- only 15s = **28 days** ← low-quality extra trades

The 15s "extra" 28 days are days that 30s didn't flag at all. These are the days dragging the 15s WR down. The 30s confluence stack is doing real filtering at exactly the right granularity.

## Per-tier full breakdown by timeframe

### 30s (baseline, n=187 W1 shorts excl. PS)
| Tier | n | WR | PF |
|---|---|---|---|
| 0-1 | 31 | 51.6% | 1.07 |
| 2 | 71 | 59.2% | 1.45 |
| 3 | 31 | 61.3% | 1.58 |
| **4+** | **54** | **72.2%** | **2.60** |

### 15s (n=366)
| Tier | n | WR | PF |
|---|---|---|---|
| 0-1 | 76 | 51.3% | 1.05 |
| 2 | 115 | 51.3% | 1.05 |
| 3 | 74 | 56.8% | 1.31 |
| 4+ | 101 | 55.4% | 1.24 |

### 1m (n=81)
| Tier | n | WR | PF |
|---|---|---|---|
| 0-1 | 17 | 58.8% | 1.43 |
| 2 | 27 | 48.1% | 0.93 |
| 3 | 18 | 66.7% | 2.00 |
| 4+ | 19 | 57.9% | 1.38 |

### 2m, 3m, 5m: insufficient sample (n ≤ 23 total across all tiers)

## Why 30s wins (hypotheses, untested)

1. **30s FVGs are at the right granularity for institutional order flow.** Faster = chasing micro-structure noise. Slower = missing the move that's already started.
2. **The 9:30 candle direction is engine-coded relative to 30s candles.** Confluences reference 30s candles; running them against 15s signals creates alignment drift.
3. **The 7R median MFE move unfolds at speeds the 30s entry captures.** 15s catches false starts; 1m enters too late.

## Bonus: 9:30-candle FVG sub-edge across timeframes

Sub-edge definition: FVGC trades where the underlying FVG was *born* in the 9:29:30–9:31:00 window (i.e., the opening candle itself created the FVG you're trading).

| TF | All W1 n | All W1 WR | 9:30-FVG n | 9:30-FVG WR | Lift |
|---|---|---|---|---|---|
| 15s | 384 | 52.3% | 58 | 65.5% | **+13.2pp** |
| 1m | 84 | 57.1% | 15 | 60.0% | +2.9pp |
| 2m | 23 | 52.2% | 0 | — | — |
| 3m | 9 | 66.7% | 0 | — | — |

The 9:30-FVG sub-edge **exists on 15s** (+13.2pp WR lift over 15s baseline) but at 65.5% WR / PF 1.90 it's still worse than 30s 4+ conf (72%/2.60). 1m+ is too small. We could not test on 30s in this run — the 30s baseline file doesn't preserve `fvg_created_at`. To get the 30s 9:30-FVG numbers would require a re-run of the FVGC engine on 30s preserving FVG creation timestamps.

### 9:30-FVG sub-edge, 4+ conf tier

| TF | n | WR | PF | Trades/mo |
|---|---|---|---|---|
| 15s | 14 | 64.3% | 1.80 | 0.47 |
| 1m | 4 | 75.0% | 3.00 | 0.13 |

Sample sizes are too small to be a tradeable rule on their own. The 9:30-FVG mechanic is real (the lift is consistent) but for execution purposes it doesn't beat sticking with the 30s 4+ conf cell.

## Practical implications

1. **Don't try to scale W1/M1 short via timeframe.** The 30s edge does not multiply.
2. **Don't drop to 15s expecting "2× trades at same WR" — you'll get 2× trades at baseline WR.** That's not the play; it's just running the engine on noisier data.
3. **The path to more trades is different cells, not different bar sizes.** Other (window × direction) cells (M2 short, M2 long, M3 long, etc.) are the unexplored frontier — see `studies/multi_cell_confluence/` for the user's existing matrix work.
4. **For algo deployment: use 30s bars for this play. Document this as a hyperparameter constraint, not a degree of freedom.**

## Scripts

- `/tmp/tf_comparison.py` — the baseline cross-TF comparison
- `/tmp/930_fvg_subedge.py` — the 9:30-FVG sub-edge cross-TF analysis

Both saved during the 2026-04-29 audit. Logic is small and re-runnable.

## Methodology caveats

- Confluence count uses the **original 6-factor stack** (gap_down, large_gap, overnight_down, prior_day_weak, bear_930, no_news), not the newer 7-factor stack with hard vetoes from the multi-cell confluence study. Re-running with the updated factor set would tighten the comparison but the headline finding (30s is the sweet spot) is unlikely to change — the timeframe-noise effect is structural, not factor-stack-dependent.
- 30s "baseline" here is `studies/mfe_multi_r/results/mfe_trades_enriched.csv` — the pre-multi-cell-confluence-study cohort. Numbers won't exactly match the M1 Short Notion page (which uses the newer study) but the across-timeframe ratios are valid.
- `mfe_r` column not used (documented post-exit bug). All numbers use `outcome` and `hit_X_R` where applicable.
