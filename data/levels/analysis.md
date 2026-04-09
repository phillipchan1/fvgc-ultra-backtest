# Level Analysis

Two studies in this folder. Both run on clean level data with corrected pre-RTH sweep logic (see [Pipeline Notes](#pipeline-notes)).

**Dataset:** Oct 2023 – Feb 2026, NQ front-month, ~615 trading days, 2,005 baseline trades.

---

## Study 1: Level WR — does having a level target improve trade outcomes?

**Script:** `study_level_proximity.py`
**Source:** `trades_with_levels.csv` (each trade enriched with nearest available level, obstruction count, confluence, etc.)

"Available" = level exists on that date, was not swept pre-RTH, was not swept by RTH bars between 9:30 and entry. The magnet pool is available levels only.

### Level group as nearest magnet: WR by group

**Primary view: magnet_valid=True only (level within 3R).**

This is the correct lens for a continuation model. `magnet_valid=True` means the nearest available level in the trade direction is within 3R — i.e., a realistic target given your stop size. Levels beyond 3R are not actionable draws and inflate/distort the group WR if included.

| Group | n | WR% | PF | Notes |
|-------|---|-----|----|-------|
| htf_fvg_1H | 53 | **64.2** | 2.16 | Fresh unmitigated 1H gaps |
| bsl_ssl | 10 | **60.0** | 3.00 | Small sample, very high PF |
| htf_fvg_15m | 89 | **58.4** | 1.51 | Strong with good sample |
| prev_day | 77 | **57.1** | 1.45 | Reliable |
| asia | 59 | 54.2 | 1.22 | Modest edge |
| 6am | 129 | 51.9 | 1.18 | Near-baseline |
| htf_fvg_Daily | 31 | 51.6 | 1.03 | Near-baseline |
| overnight | 117 | 48.7 | 0.86 | **Below baseline** |
| london | 173 | 47.4 | 0.95 | **Below baseline** |
| htf_fvg_4H | 35 | 45.7 | 0.99 | **Below baseline** |
| **baseline (valid only)** | **778** | **51.5** | **1.09** | |

**Key takeaways:**
- **htf_fvg_1H leads** (64.2%, PF 2.16) after the mitigation fix. These are now genuinely fresh, unmitigated gaps — prior data included wicked-into FVGs that diluted the signal.
- **htf_fvg_15m** (58.4%, PF 1.51) and **prev_day** (57.1%, PF 1.45) remain strong.
- **London within 3R underperforms** (47.4%, PF 0.95). London levels are often swept as part of the opening drive rather than acting as a clean draw. Use with caution as primary target.
- **overnight underperforms** (48.7%, PF 0.86) — lowest PF in the group.
- **htf_fvg_4H within 3R underperforms** (45.7%, PF 0.99). Possibly too wide a zone for a clean 45-min target.

**Reference: all distances (including unreachable levels >3R)**

| Group | n | WR% | PF |
|-------|---|-----|----|
| nwog | 8 | 75.0 | 3.17 |
| htf_fvg_15m | 173 | **61.8** | 1.64 |
| bsl_ssl | 16 | 56.3 | 2.17 |
| prev_day | 147 | 54.4 | 1.28 |
| htf_fvg_1H | 90 | 53.3 | 1.12 |
| 6am | 247 | 53.0 | 1.21 |
| htf_fvg_Daily | 55 | 50.9 | 1.05 |
| asia | 107 | 50.5 | 1.05 |
| london | 341 | 48.1 | 0.95 |
| overnight | 199 | 47.2 | 0.84 |
| htf_fvg_4H | 69 | 39.1 | 0.73 |
| **baseline** | **1572** | **51.7** | **1.09** |

Note: the all-distances view is misleading for a continuation model. A level 6-8R away is not a draw — it just happens to be the nearest available level in that direction. Use the ≤3R view for decision-making.

### Magnet distance (R buckets)

| R bucket | n | WR% | PF |
|----------|---|-----|----|
| < 1R | 223 | **54.3** | 1.21 |
| 1–2R | 309 | 49.8 | 1.08 |
| 2–3R | 242 | **54.1** | 1.24 |
| no valid levels | 794 | 50.9 | 1.01 |
| baseline | 1572 | 51.7 | 1.09 |

**Key takeaway:** Edge at **<1R** (54.3%) and **2–3R** (54.1%). The 1–2R band is the weakest (49.8%, essentially flat). Having a level anywhere within 3R beats having none (50.9%), but the sweet spots are very close (<1R) or near the outer edge of your target window (2–3R).

### Available level count (ALC)

Number of distinct groups with at least one available level in the trade direction within 3R:

| ALC | n | WR% | PF |
|-----|---|-----|----|
| 0 | 794 | 50.9 | 1.01 |
| 1 | 295 | **54.9** | 1.31 |
| 2 | 167 | **55.1** | 1.30 |
| 3+ | 316 | 49.1 | 1.01 |
| baseline | 1572 | 51.7 | 1.09 |

**Key takeaway:** ALC 1–2 is the sweet spot (55% WR, PF 1.30). Three or more levels in direction underperforms baseline — price is in a contested, level-dense zone where friction replaces draw.

### Path clear vs obstruction

| State | n | WR% | PF |
|-------|---|-----|----|
| path_clear = True (no obstruction) | 1349 | 51.3 | 1.07 |
| path_clear = False (1+ obstruction) | 223 | **54.3** | 1.21 |
| baseline | 1572 | 51.7 | 1.09 |

**Counterintuitive but consistent:** having an obstruction between entry and TP outperforms a clear path. The most likely explanation: a single level between you and TP often acts as a stepping-stone — price needs to sweep it to reach your target, and that sequence (sweep obstruction → reach TP) is the path of continuation plays.

| Obstruction count | n | WR% | PF |
|------------------|---|-----|----|
| 0 | 1349 | 51.3 | 1.07 |
| 1 | 135 | **58.5** | 1.40 |
| 2+ | 88 | 47.7 | 0.98 |
| baseline | 1572 | 51.7 | 1.09 |

**One obstruction is strongly additive** (58.5%, PF 1.40). Two or more is below baseline — too many levels in path = contested zone, not stepping-stones.

### Confluence count (levels within 10 pts of target)

| Confluence | n | WR% | PF |
|-----------|---|-----|----|
| 1 | 832 | 52.3 | 1.13 |
| 2 | 228 | 51.3 | 1.13 |
| 3+ | 392 | 50.0 | 1.01 |
| baseline | 1572 | 51.7 | 1.09 |

A single clean level at the target is slightly better than a stacked zone. When 3+ groups stack at the same price, the zone may act as both magnet and reversal point simultaneously.

### Best combinations: short cluster × available level count

From the existing short clusters (macro_w1, prior_close_low):

| Cluster | ALC | n | WR% | PF |
|---------|-----|---|-----|----|
| short_prior_close_low | 1 | 27 | **77.8** | 4.52 |
| short_prior_close_low | 2 | 18 | **66.7** | 2.37 |
| short_macro_w1 | 1 | 52 | **65.4** | 1.96 |
| either_cluster | 1 | 67 | **64.2** | 2.08 |
| either_cluster | 2 | 45 | 60.0 | 1.82 |
| short_macro_w1 | 2 | 34 | 58.8 | 1.75 |
| neither_cluster | 1 | 61 | 42.6 | 0.90 |
| neither_cluster | 3+ | 90 | 47.8 | 0.94 |
| baseline | — | 1572 | 51.7 | 1.09 |

**The signal compounds.** A short in the prior_close_low cluster with 1 available level in the downside direction hits 77.8% WR, PF 4.52. Neither-cluster trades underperform regardless of ALC.

### What this means for trade selection

1. **Before entry, check for a fresh (unmitigated) level within 3R.** Best draws: 1H FVG, 15m FVG, prev_day, BSL/SSL. These produce meaningful WR lift above baseline.
2. **ALC filter:** 1–2 available levels in direction = best zone (~55% WR, PF 1.30). 0 is neutral. 3+ is a flag to reduce or skip.
3. **One obstruction between entry and TP is a positive signal** (58.5%, PF 1.40) — it suggests price has a level to sweep en route.
4. **Two or more obstructions = friction** (47.7%, below baseline). Don't take trades with a crowded path.
5. **London and overnight as nearest targets underperform.** These are often swept as part of the opening drive rather than being strong singular draws.
6. **htf_fvg_4H within 3R also underperforms.** Too wide a zone for a clean 45-min target.

---

## Study 2: Level hit rate — which levels get hit in the first 45 min?

**Script:** `study_level_hit_rate_45min.py`
**Source:** `liquidity_levels.csv` (available levels per day) × 30s bar H/L for 9:30–10:15 window.

"Available" here = `swept_pre_rth = False` and valid price on that date. Scoped to levels within **300 pts** of RTH open (run `--scope N` to change).

**Coverage:** 10,743 level-day pairs across 616 days, all groups. (HTF FVG count reduced vs prior — correctly excludes wicked-into gaps.)

**Availability notes:**
- `6am_high / 6am_low` — forms at close of the 6am 4H candle (10:00 AM ET). Hit window = 10:00–10:15 only (15 min).
- `or_high / or_low` — not computed (stub). Excluded.
- `overnight_high / overnight_low` — always available (they are the overnight extreme, cannot be swept before RTH opens).
- HTF FVGs: mitigated = wicked into the near edge (bearish: `high >= fvg_bottom`; bullish: `low <= fvg_top`). Only unmitigated FVGs are included.

### Group ranking: hit rate within first 45 min (≤300 pts from open)

| Rank | Group | Hit Rate | n | Notes |
|------|-------|----------|---|-------|
| 1 | nwog | **72.5%** | 204 | Monday only |
| 2 | asia | **59.2%** | 1,078 | Strong consistent draw |
| 3 | bsl_ssl | **56.5%** | 1,096 | London swing H/L |
| 4 | london | **54.3%** | 1,096 | |
| 5 | 6am | **46.1%** | 1,106 | 15-min check window (10:00–10:15) |
| 6 | overnight | 41.1% | 1,067 | |
| 7 | prev_day | 40.6% | 937 | |
| 8 | htf_fvg_Daily | 26.3% | 285 | Fresh daily gaps only |
| 9 | htf_fvg_15m | 26.2% | 2,065 | |
| 10 | htf_fvg_4H | 23.5% | 677 | |
| 11 | htf_fvg_1H | 22.5% | 1,132 | |

**Key takeaway:** Session structure levels (NWOG, Asia, BSL/SSL, London) get hit far more often than HTF FVGs. This gap widened after the mitigation fix — HTF FVGs drop from ~30–44% to ~22–26% because only genuinely fresh (never-wicked) gaps remain. If an Asia or London level is available and within range, expect 55–60% base rate of price visiting it in the first 45 min. HTF FVGs in the first 45 min are visited only ~1-in-4 times.

### Distance from open is the dominant factor

| Distance from RTH open | Hit Rate | n |
|------------------------|----------|---|
| 0–25 pts | **86.1%** | 1,926 |
| 25–50 pts | **62.6%** | 1,708 |
| 50–100 pts | 39.6% | 2,643 |
| 100–200 pts | 17.1% | 2,814 |
| 200+ pts | 6.3% | 1,652 |

**This is the single most powerful predictor.** A level within 25 pts of the open gets hit 86% of the time. Beyond 100 pts, hit rate drops below 20%. For continuation target selection, prioritize levels inside 100 pts.

### Group × distance (hit rate %)

| Group | 0–25 | 25–50 | 50–100 | 100–200 | 200+ |
|-------|------|-------|--------|---------|------|
| htf_fvg_Daily | **100%** | 70.8% | 42.2% | 16.5% | 2.2% |
| asia | 92.4% | 73.2% | 54.3% | 30.1% | 27.1% |
| bsl_ssl | 90.5% | 68.7% | 46.6% | 22.2% | 29.5% |
| htf_fvg_1H | 89.0% | 52.5% | 32.3% | 12.9% | 3.1% |
| london | 90.0% | 66.8% | 43.6% | 18.8% | 20.9% |
| prev_day | 94.2% | 68.3% | 43.1% | 24.5% | 11.7% |
| htf_fvg_15m | 85.8% | 58.3% | 30.0% | 12.7% | 2.1% |
| htf_fvg_4H | 84.3% | 54.7% | 32.1% | 11.1% | 1.6% |
| overnight | 83.8% | 57.8% | 34.6% | 11.6% | 7.1% |
| nwog | 97.7% | 70.0% | 33.3% | 8.3% | 0.0% |
| 6am | 66.8% | 52.1% | 37.1% | 21.2% | 23.1% |

**Notable:** All groups converge near 85–100% when within 25 pts. Asia and BSL/SSL maintain elevated hit rates even at 100–200 pts (22–30%) compared to HTF FVGs (11–13%) — session levels have gravitational pull that persists at distance. HTF FVGs outside 50 pts are hit <33% of the time.

### Gap direction effects

| Group | flat gap | gap down | gap up |
|-------|----------|----------|--------|
| nwog | **92.9%** | 75.9% | 68.7% |
| asia | 66.7% | 56.0% | 60.7% |
| bsl_ssl | 63.3% | 52.3% | 58.5% |
| london | 56.7% | 50.8% | 56.4% |
| overnight | 45.6% | 35.5% | 43.8% |
| prev_day | 34.6% | 38.3% | 43.2% |
| htf_fvg_Daily | 19.2% | 31.1% | 25.3% |
| htf_fvg_15m | 23.6% | 25.5% | 28.1% |

**NWOG is most sensitive to gap direction.** A flat gap on Monday means 93% hit rate — the market hasn't moved away from the weekly open. Gap up or down reduces it significantly.

**prev_day reverses the pattern** — higher hit rate on gap_up days (43%) than flat (35%). When the market gaps toward prev_day resistance, it follows through to tag it.

**HTF FVG Daily** is more likely hit on gap_down days (31.1%) than flat (19.2%), suggesting gap_down days create the move that runs into those support zones.

### 9:30 candle direction

| Group | Down candle | Up candle |
|-------|-------------|-----------|
| htf_fvg_1H | 25.3% | 19.3% |
| htf_fvg_4H | 25.0% | 22.0% |
| htf_fvg_15m | 29.2% | 22.7% |
| all groups avg | ~42% | ~38% |

Weak but consistent: a down opening candle produces modestly higher hit rates across all groups (~4% lift on average). The signal is too small to be a primary filter but slightly confirms momentum.

### Top combos (n ≥ 30)

| Group | Gap | 930 Candle | Hit Rate | n |
|-------|-----|-----------|----------|---|
| nwog | gap_down | up | **81.2%** | 32 |
| nwog | gap_up | down | 72.2% | 54 |
| asia | flat | down | 69.6% | 56 |
| nwog | gap_up | up | 65.6% | 61 |
| bsl_ssl | flat | down | 64.3% | 56 |
| bsl_ssl | flat | up | 61.8% | 34 |
| asia | flat | up | 61.8% | 34 |
| asia | gap_up | down | 61.7% | 308 |
| bsl_ssl | gap_up | down | 60.5% | 314 |
| asia | gap_up | up | 59.5% | 274 |
| london | flat | down | 58.9% | 56 |
| london | gap_up | down | 57.8% | 315 |
| asia | gap_down | up | 57.0% | 207 |
| bsl_ssl | gap_up | up | 56.2% | 281 |
| london | gap_up | up | 54.8% | 281 |

**For a continuation model:** Asia and BSL/SSL on gap_up days with a down 930 candle show ~60% hit rate with large sample sizes (274–314 trades). These are your highest-confidence targets in this dataset.

### Which 15-min window do levels get hit in?

Of the levels that get hit in the first 45 min, here is the distribution across the three 15-min macro windows:

| Group | 9:30-9:45 | 9:45-10:00 | 10:00-10:15 |
|-------|-----------|------------|-------------|
| nwog | **93%** | 4% | 3% |
| asia | **84%** | 9% | 7% |
| bsl_ssl | **82%** | 9% | 9% |
| london | **82%** | 9% | 8% |
| prev_day | **83%** | 9% | 8% |
| overnight | 71% | 15% | 14% |
| htf_fvg_Daily | 68% | 21% | 11% |
| htf_fvg_4H | 69% | 13% | 18% |
| htf_fvg_15m | 66% | 17% | 17% |
| htf_fvg_1H | 58% | **20%** | **23%** |
| 6am | 0% | 0% | **100%** | (available only from 10:00) |

**Key takeaway:** Session levels (Asia, BSL/SSL, London, prev_day, NWOG) are overwhelmingly hit in the **first macro** (9:30–9:45). If an Asia or London level hasn't been touched by 9:45, the probability of it being hit later is low. HTF FVGs — especially 1H — are more spread across all three windows (~20% each in windows 2 and 3). Session levels are the opening drive target; FVGs are more often the target of secondary impulses in macros 2 and 3.

### WR by macro window × nearest magnet (magnet_valid=True)

Which level type produces the best WR outcome per 15-min window?

**9:30–9:45 (macro 1)**

| Level group | n | WR% | PF |
|-------------|---|-----|----|
| asia | 22 | **72.7** | 3.23 |
| prev_day | 21 | **61.9** | 1.71 |
| htf_fvg_1H | 18 | 61.1 | 2.03 |
| london | 66 | 53.0 | 1.30 |
| overnight | 50 | 42.0 | 0.68 |
| **baseline** | **276** | **54.0** | **1.30** |

**9:45–10:00 (macro 2)**

| Level group | n | WR% | PF |
|-------------|---|-----|----|
| htf_fvg_15m | 29 | **69.0** | 2.19 |
| htf_fvg_1H | 22 | **68.2** | 2.44 |
| prev_day | 27 | 59.3 | 1.66 |
| 6am | 39 | 56.4 | 1.63 |
| london | 54 | 46.3 | 0.81 |
| asia | 20 | 40.0 | 0.59 |
| **baseline** | **255** | **53.7** | **1.17** |

**10:00–10:15 (macro 3)**

| Level group | n | WR% | PF |
|-------------|---|-----|----|
| htf_fvg_1H | 12 | **66.7** | 2.59 |
| htf_fvg_15m | 39 | 56.4 | 1.55 |
| htf_fvg_4H | 11 | 54.5 | 1.22 |
| london | 51 | 41.2 | 0.76 |
| htf_fvg_Daily | 12 | 25.0 | 0.29 |
| **baseline** | **240** | **50.4** | **1.07** |

**Key takeaways:**

1. **Asia as target is strictly a macro 1 play.** 72.7% WR in 9:30–9:45, drops to 40.0% in macro 2. If price hasn't reached Asia by 9:45, stop using it as your draw.

2. **htf_fvg_1H is consistent across all three windows** (61% / 68% / 67%) — the only group that maintains strong WR throughout. This makes sense: fresh unmitigated 1H gaps are meaningful draws in any impulse.

3. **htf_fvg_15m is especially strong in macro 2** (69%, PF 2.19 vs 45% in macro 1). Macro 2 is the FVG macro.

4. **London declines with each macro** (53% → 46% → 41%). By macro 3, London as a target is significantly below baseline. Never target London in macro 3.

5. **Overall WR by window** (magnet_valid=True): 9:30–9:45 = 54.0% / 9:45–10:00 = 53.7% / 10:00–10:15 = 50.4%. First two macros are above baseline; macro 3 converges toward it.

6. **htf_fvg_Daily in macro 3 = 25% WR** — severely underperforms. If a Daily FVG hasn't been hit in macros 1-2 and you're in macro 3, don't trade toward it.

---

## Putting both studies together: continuation model targeting

You enter in the direction price is already moving. You want a level target. Here's how the two studies combine:

### Choosing your target

| Priority | Criteria | Why |
|----------|----------|-----|
| 1 | Level within 50 pts of entry | 67–88% base hit rate in 45 min; within 1R produces best WR lift |
| 2 | Group: Asia, BSL/SSL, prev_day, 15m FVG | These as nearest target produce 55–59% WR vs 51.7% baseline |
| 3 | ALC = 1 or 2 levels in direction | Strongest WR outcomes, 54–57% |
| 4 | 1 obstruction between entry and target | WR 56.1%, PF 1.30 — sweep obstruction en route |
| 5 | Single level at target, not a cluster | Confluence = 1 produces 53.8%; 3+ = 49.6% |

### Context that improves confidence the level gets hit

| Signal | Effect |
|--------|--------|
| Level within 25 pts | +40–50% hit rate vs 100–200 pts zone |
| Asia/BSL/SSL + flat gap | 64–70% hit rate |
| NWOG available + flat gap | 93% hit rate (Monday, rare) |
| Daily FVG within 50 pts | 96.8% hit rate |
| Gap_up day + Asia/BSL/SSL target | 59–62% hit rate (large sample) |

### What to avoid

- **London or overnight as your only available magnet** — produces below-baseline WR (0.93–0.94 PF).
- **Target level beyond 100 pts** — less than 20% base rate of being hit in 45 min.
- **ALC of 3+** — contested zone, WR 47.2%, PF 0.94.
- **htf_fvg_1H as nearest magnet** — only group that reliably underperforms baseline (46.8% WR, 0.97 PF).
- **High confluence (3+ groups stacked at target)** — PF 0.97, below baseline.

---

## Open questions for future study

1. **Direction-filtered hit rate** — this study counts all in-scope levels (above and below open). Splitting by whether the level is in the gap direction (resistance above on gap_up day) vs against it would sharpen the numbers significantly.
2. **Sequence** — when multiple levels are available, which gets hit first? Does price sweep the closest level before the target?
3. **Available level count for the hit rate study** — how does the number of available levels on a given day affect the probability of any one being hit?
4. **Post-hit behavior** — does price reverse at the level (making it a valid TP) or blow through? Level quality as an exit vs a magnet.
5. **6am level definition** — current pipeline uses 4am–8am bars; the correct definition per the 6am 4H candle is 6am–10am (available at 10:00). Rebuilding with the correct window would improve 6am level quality.

---

## Pipeline notes

### Sweep logic (fixed Apr 2026)

The original `_finalize_pre_rth_sweep` used the full overnight window (18:00 prev day → 9:29 today) for all level types. This caused Asia, London, 6am, and BSL/SSL to always register as `swept_pre_rth = True` because their formation windows are subsets of the overnight window — price trivially "sweeps" a level during the same bars it was formed from.

**Fix:** each level type now uses a level-specific sweep check window starting *after* formation ends:

| Level | Formation ends | Sweep check from |
|-------|----------------|-----------------|
| prev_day | Prior RTH close | 18:00 prev day |
| nwog | Friday close | 18:00 prev day |
| asia | 2:00 AM | **2:00 AM** |
| london | 8:00 AM | **8:00 AM** |
| 6am | 8:00 AM | **8:00 AM** |
| bsl_ssl | 8:00 AM | **8:00 AM** |
| overnight | IS the overnight H/L | **always False** |

After the fix, availability rates changed substantially:

| Group | Before (available) | After (available) |
|-------|--------------------|-------------------|
| asia | 0 | 387 / 1120 (35%) |
| london | 0 | 687 / 1120 (61%) |
| 6am | 0 | 611 / 1120 (55%) |
| bsl_ssl | 0 | 663 / 1120 (59%) |
| overnight | 0 (NaN) | 1120 / 1120 (100%) |

The nearest magnet distribution in `trades_with_levels.csv` changed significantly — London and 6am are now the top two magnet groups (276 and 233 trades), ahead of htf_fvg_15m (228).

### Rebuild order after any pipeline change

```bash
python data/levels/build_liquidity_levels.py
python data/levels/enrich_trades_with_levels.py
python data/levels/study_level_proximity.py
python data/levels/study_level_hit_rate_45min.py
```

### FVG mitigation fix (fixed Apr 2026)

The original mitigation logic used the **far edge** of the gap (full fill) as the threshold:
- Bearish FVG: mitigated when `high >= top` (price fully filled the gap)
- Bullish FVG: mitigated when `low <= bottom` (price fully filled the gap)

**Fix:** mitigation now uses the **near edge** (wick-in = mitigated):
- Bearish FVG: mitigated when `high >= bottom` (price wicked into the gap from below)
- Bullish FVG: mitigated when `low <= top` (price wicked into the gap from above)

Same fix applied to `fvg_swept_pre_rth` (overnight pre-market sweep detection).

The `price` field for HTF FVG rows was also corrected:
- Before: `price = fvg_mid` (midpoint of gap)
- After: `price = fvg_bottom` for bearish FVGs (near edge approached from below), `price = fvg_top` for bullish FVGs (near edge approached from above)

This is now consistent with how `is_level_swept` checks proximity: `high >= price` for resistance, `low <= price` for support.

**Impact:** HTF FVG row counts in the ≤300pt scope dropped significantly (e.g., htf_fvg_1H: 2,063 → 1,132) as previously "active" but wicked-into FVGs are now correctly excluded. Hit rates for HTF FVGs also dropped (~30–44% → ~22–26%) — the prior numbers were inflated by stale levels.

### In-session sweep fix (fixed Apr 2026)

`enrich_trades_with_levels.py` was pointing to `data/raw/glbx-mdp3-20231002-20251027.ohlcv-30s-trading-session.csv` which only covers through Oct 2025. All 2026 trades had empty bar windows — every level appeared `available` even when swept during RTH before entry.

**Fix:** switched to `data/consolidated/nq-front-month.ohlcv-30s.csv` which covers the full backtest range.

### Data sources

| Use | File |
|-----|------|
| Level construction + in-session sweep | `data/consolidated/nq-front-month.ohlcv-30s.csv` |
| Trading calendar | `data/trading_days/trading_days.csv` |
| Trades | `logs/baseline_trades.csv` |

### Level taxonomy

| Group | Type | Formation window | Available at |
|-------|------|-----------------|--------------|
| prev_day | Session | Prior RTH 9:30–16:00 | Open if not swept 18:00–9:30 |
| overnight | Session | 18:00 prev – 9:29 today | Always |
| asia | Session | 19:00 prev – 2:00 AM | Open if not swept 2:00–9:30 |
| london | Session | 2:00–8:00 AM | Open if not swept 8:00–9:30 |
| 6am | Session | 4:00–8:00 AM (current builder) | Open if not swept 8:00–9:30 |
| bsl_ssl | Session | London swing H/L (2:00–8:00) | Open if not swept 8:00–9:30 |
| nwog | Session | Friday close–Monday open | Monday only |
| htf_fvg_15m/1H/4H/Daily | HTF FVG | Per candle formation | Open if still active and not swept overnight |
| opening_range | Session | 9:30–9:45 (first 15 min) | 9:45 — stub, not computed |

### FVG geometry

**Bullish FVG** (`c1.high < c3.low`): gap bottom = `c1.high`, top = `c3.low`. Mitigation: later bar `low <= top` (wicked into gap from above).

**Bearish FVG** (`c1.low > c3.high`): gap bottom = `c3.high`, top = `c1.low`. Mitigation: later bar `high >= bottom` (wicked into gap from below).

`price` in `liquidity_levels.csv` = near edge for HTF rows:
- Bearish FVG: `price = fvg_bottom` (nearest edge when approaching from below)
- Bullish FVG: `price = fvg_top` (nearest edge when approaching from above)

`fvg_top` / `fvg_bottom` / `fvg_mid` retain the full zone geometry.

### `trades_with_levels.csv` key columns

| Column | Meaning |
|--------|---------|
| `nearest_magnet_pts/R/group` | Closest available level in trade direction |
| `magnet_within_1R/2R/3R` | Whether nearest magnet is within that R distance |
| `path_clear` | No available levels between entry and TP |
| `obstruction_count` | Available levels between entry and TP |
| `level_confluence_count` | Distinct groups within 10 pts of magnet |
| `available_level_count` | Distinct groups with ≥1 available level within 3R in direction |
| `no_valid_levels` | True if nothing available within 3R in direction |
| `{group}_swept` | `available` / `in_session` / `pre_rth` for nearest level in that group |
