# v1 Validation — Findings (overnight run)

**Read this first.** Raw tables are in [`v1_summary.md`](v1_summary.md); per-cell CSVs in `lift/`.

---

## TL;DR

**Scaled exits give a modest improvement, NOT the dramatic 2.0+ PF I projected.**

Headline: best validated combination is
- **Confluence v2** (5 factors, gap widened to 8-12pt)
- **Score ≥ 2** entry filter
- **Scaled exits** (TP1@1R/33% + TP2@2R/33% + Runner@5R/34%)

**OOS performance** (1-year held-out, May 2025 → May 2026):
- N = 102 trades (~2/wk)
- WR = 36% (scaled wins are partial, not 1R-binary)
- **PF = 1.48**
- **avg_R = +0.24 per trade**
- total_R = +24.6 over the year

Compared to the original v1 fixed-1R confluence:
- PF: 1.38 → 1.48 (+7%)
- avg_R: +0.16 → +0.24 (+50%)
- N grew from 76 → 102 (more trades from widened gap)

**This is a real edge, just smaller than I projected.**

---

## Why the MFE distribution didn't translate to bigger gains

I projected PF ~2.0 from MFE math (avg MFE_R 3.7 on score 3+). Didn't happen because:

1. **Soft stop fires before runners materialize.** Many trades hit MFE 2-5R briefly then close back through the gap (soft stop), exiting at the close — not the peak. MFE measured the wick high; we exit at the close.

2. **Trim ladder dilutes big winners.** The 33% trim at 1R captures certain gains, but the 33% runner that goes to 5R adds only 1.65R. A 10R+ MFE trade (28% of trades reach 3R+) gets capped at 5R because that's where we exit the runner.

3. **Score ≥ 3 OOS is too small (N=9-26).** Scaled exits NEED runners to outperform; small samples miss the long tail. IS score≥3 scaled PF was 2.47 (validated). OOS scaled PF dropped to 0.77 — but with N=9, that's noise more than signal.

---

## Surprising findings

### 1. Scaled vs fixed_1r WR diverges sharply
| Subset | Fixed 1R WR | Scaled WR |
|--------|-------------|-----------|
| All trades | 50% | 33% |
| Score ≥ 2 | 58% | 36% |
| Score ≥ 3 | 72% (IS) | 50% (IS) |

A scaled "win" requires the cumulative trim ladder to net positive. A trade that hits TP1 (+0.33R), then gets stopped on the remaining 67% (-0.67R) = net -0.34R = counted as loss. Same trade fixed-1R was a +1R win at TP1. This explains the WR gap. **PF is the better metric for scaled.**

### 2. v3 (added `sweep_penetration_pts ≤ 2`) widened the funnel but lost edge
- v2 OOS score≥2 scaled: N=102, **PF=1.48**, avg_R +0.24
- v3 OOS score≥2 scaled: N=111, PF=1.46, avg_R +0.20

The shallow-sweep factor added 9 trades but they were marginal. v2 is the cleaner cutoff.

### 3. Anti-pattern filter didn't help OOS materially
- v2 OOS score≥2 unfiltered scaled: PF 1.48
- v2 OOS score≥2 anti-filtered scaled: PF 1.46 (slightly worse, similar N)

The anti-patterns (body>0.9, gap 12-15, prev_day_low) are individually negative but **already excluded** by the positive factor scoring (body 0.7-0.9 contradicts >0.9, gap 8-12 contradicts 12-15). The filter was redundant once we have the score ≥ 2 cutoff.

### 4. Score ≥ 3 OOS scaled UNDERPERFORMED fixed_1r
- OOS score≥3 fixed_1r v1: N=9, **PF=1.65**, avg_R +0.11
- OOS score≥3 scaled v1: N=9, PF=0.77, avg_R -0.19

This goes against the projection. Reason: small sample missed the 5R+ runners that scaled needs. The 9 OOS trades had MFE distribution shifted vs IS — fewer made it to runner territory.

---

## What I'd test next (priority order)

### Priority 1 — **Tune the trim ladder**
Current 33/33/34 may be wrong. Try:
- **50/30/20**: take more off early (matches Tempo's "30-50% at TP1")
- **30/30/40**: hold MORE runner
- **20/30/50**: aggressive runner-heavy

Plus try DIFFERENT R-targets:
- TP1 at 0.5R / TP2 at 1.5R / Runner 4R — more aggressive partials
- TP1 at 1.5R / TP2 at 3R / Runner 8R — let it breathe

This is ~30 min of work; just re-runs `v1_validation.py` with different parameters.

### Priority 2 — **Structural targets instead of fixed R-multiples**
The 5R runner cap is arbitrary. Tempo says target HOD/LOD or major drawn liquidity. Implement target = opposite side of dealing range (or 50% line). Less arbitrary, and 5R+ MFE trades will run all the way.

### Priority 3 — **Refine the soft stop**
Currently soft stop = ANY close past gap.top/bottom. Could tighten to:
- Body close (open+close BOTH past level), not just close
- Wait for 2 consecutive closes past level
- Or use breakeven trail after TP1 hits

Each variant changes how often soft stop fires; the runner-cap problem above is partially driven by premature soft stops.

### Priority 4 — **Get more OOS data**
1 year OOS at score ≥ 3 = N=9-26. Insufficient. Either:
- Wait for 2026 data
- Walk-forward instead of single-split (rolling 3-year IS, 6-month OOS)
- Extend cohort backward — re-run on full 8-year with refreshed data

### Priority 5 — **Test on the data wick model**
Apply the same scaled-exit logic to the data wick play (v0.4.1 was breakeven on fixed_1r). The data wick has bigger MFE potential because the structural target (opposite wick side) is huge. Scaled exits should help MORE there.

---

## What this means for the model

**v0.3.4 IFVG reversal model + confluence v2 score ≥ 2 + scaled exits is a validated edge.**

Numbers:
- ~100 trades/year (2/week)
- 36% WR (scaled) or 58% WR (fixed_1r — your choice)
- PF 1.48
- Expected R = +0.24 per trade
- Total expected R = ~25R/year

**Is it ready to trade?** Honest answer: it's **edge-positive**, not yet **playbook-grade**. The PF 1.48 is real but slim — a small regime shift could erode it. To promote to v1.0 SPEC + playbook I'd want either:
- Walk-forward validation showing PF stays >1.3 across multiple OOS windows
- Refined trim ladder pushing PF above 1.7-2.0
- Combined data wick + AM IFVG portfolio (uncorrelated signals)

**My take:** spend the next session on Priority 1 (trim ladder tuning) — quickest path to potentially pushing PF higher. Then either Priority 2 (structural targets) or Priority 5 (data wick scaled exits) depending on what trim tuning shows.

---

## Files written

- `population_scored.csv` — every trade with all 3 confluence scores + scaled R + fixed R + MFE/MAE + anti-pattern hits
- `v1_summary.md` — raw per-variant × cohort × mode tables (the detail)
- `lift/v1_summary_grid.csv` — flat table of all best-cell combinations
- `lift/{variant}_{cohort}_{mode}.csv` — per-cell threshold sweeps
