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
| bsl_ssl | 11 | **63.6** | 3.62 | Small sample, very high PF |
| prev_day | 60 | **58.3** | 1.61 | Solid, reliable |
| asia | 52 | **57.7** | 1.20 | Strong signal |
| htf_fvg_Daily | 42 | **57.1** | 1.38 | Strong when reachable |
| htf_fvg_15m | 164 | **56.7** | 1.37 | Largest sample with edge |
| htf_fvg_1H | 114 | 50.9 | 1.12 | Near-baseline |
| overnight | 127 | 49.6 | 0.95 | Below baseline |
| 6am | 134 | 49.3 | 1.07 | Near-baseline |
| london | 171 | 46.8 | 0.94 | **Below baseline** |
| htf_fvg_4H | 70 | **45.7** | 0.91 | **Below baseline** |
| **baseline (valid only)** | **947** | **51.6** | **1.13** | |

**Key takeaways:**
- When a level is within reach (≤3R), the best draws are: BSL/SSL, prev_day, Asia, HTF Daily FVG, HTF 15m FVG.
- **London within 3R underperforms** (46.8%, PF 0.94). When London is right there, it may be acting as reversal structure rather than a draw that completes. Be cautious using London as your primary target.
- **htf_fvg_4H within 3R also underperforms** (45.7%, PF 0.91). Possibly too wide a zone to act as a clean magnet in this time window.
- 6am and overnight hover near-baseline — neutral, not additive.

**Reference: all distances (including unreachable levels >3R)**

| Group | n | WR% | PF |
|-------|---|-----|----|
| nwog | 5 | 80.0 | 3.80 |
| bsl_ssl | 17 | 58.8 | 2.52 |
| asia | 80 | 58.8 | 1.32 |
| htf_fvg_15m | 228 | 56.6 | 1.36 |
| prev_day | 95 | 54.7 | 1.35 |
| htf_fvg_4H | 120 | 50.8 | 1.07 |
| 6am | 233 | 51.9 | 1.16 |
| htf_fvg_1H | 171 | 46.8 | 0.97 |
| overnight | 181 | 49.7 | 0.94 |
| london | 276 | 48.2 | 0.93 |
| **baseline** | **1572** | **51.7** | **1.09** |

Note: the all-distances view is misleading for a continuation model. A level 6-8R away is not a draw — it just happens to be the nearest available level in that direction. Use the ≤3R view for decision-making.

### Magnet distance (R buckets)

| R bucket | n | WR% | PF |
|----------|---|-----|----|
| < 1R | 366 | 54.6 | 1.24 |
| 1–2R | 336 | 48.8 | 1.00 |
| 2–3R | 242 | 50.8 | 1.13 |
| no valid levels | 625 | 51.8 | 1.03 |
| baseline | 1572 | 51.7 | 1.09 |

**Key takeaway:** The edge comes entirely from levels within **1R**. A target level that's less than one stop distance away produces 54.6% WR and 1.24 PF. Beyond 1R the edge disappears. This is the clearest quantitative filter in this dataset: if your target level is more than 1R away, it doesn't help.

### Available level count (ALC)

Number of distinct groups with at least one available level in the trade direction within 3R:

| ALC | n | WR% | PF |
|-----|---|-----|----|
| 0 | 625 | 51.8 | 1.03 |
| 1 | 278 | 54.3 | 1.31 |
| 2 | 220 | 57.3 | 1.45 |
| 3+ | 449 | 47.2 | 0.94 |
| baseline | 1572 | 51.7 | 1.09 |

**Key takeaway:** ALC 1–2 is the sweet spot. One or two level types converging in your direction is a meaningful positive. Three or more actually underperforms — likely because price is in a contested, level-dense zone where levels are also acting as friction rather than draws.

### Path clear vs obstruction

| State | n | WR% | PF |
|-------|---|-----|----|
| path_clear = True (no obstruction) | 1206 | 50.8 | 1.05 |
| path_clear = False (1+ obstruction) | 366 | 54.6 | 1.24 |
| baseline | 1572 | 51.7 | 1.09 |

**Counterintuitive but consistent:** having an obstruction between entry and TP outperforms a clear path. The most likely explanation: a single level between you and TP often acts as a stepping-stone rather than a wall — price needs to sweep it to reach your target, and that sequence (sweep obstruction → reach TP) is the path of continuation plays.

| Obstruction count | n | WR% | PF |
|------------------|---|-----|----|
| 0 | 1206 | 50.8 | 1.05 |
| 1 | 205 | 56.1 | 1.30 |
| 2+ | 161 | 52.8 | 1.17 |
| baseline | 1572 | 51.7 | 1.09 |

One obstruction is the most additive. Two or more is still positive but diminishing.

### Confluence count (levels within 10 pts of target)

| Confluence | n | WR% | PF |
|-----------|---|-----|----|
| 1 | 781 | 53.8 | 1.23 |
| 2 | 318 | 49.4 | 1.00 |
| 3+ | 367 | 49.6 | 0.97 |
| baseline | 1572 | 51.7 | 1.09 |

A **single** level at the target is better than a cluster. When 3+ levels stack at the same price, they may be acting as magnet *and* resistance simultaneously — price reaches the zone and reverses hard, creating losses or early exits.

### Best combinations: short cluster × available level count

From the existing short clusters (macro_w1, prior_close_low):

| Cluster | ALC | n | WR% | PF |
|---------|-----|---|-----|----|
| short_prior_close_low | 2 | 25 | **80.0** | 3.45 |
| short_prior_close_low | 1 | 22 | 77.3 | 3.74 |
| either_cluster | 2 | 50 | 68.0 | 2.29 |
| either_cluster | 1 | 59 | 64.4 | 1.84 |
| short_macro_w1 | 2 | 36 | 66.7 | 2.40 |
| short_macro_w1 | 1 | 45 | 64.4 | 1.74 |
| neither_cluster | 3+ | 111 | 44.1 | 0.86 |
| baseline | — | 1572 | 51.7 | 1.09 |

**The signal compounds.** A short in the prior_close_low cluster with 1–2 available levels in the downside direction hits 77–80% WR. Neither-cluster trades with 3+ levels underperform significantly at 44%.

### What this means for trade selection

1. **Before entry, check:** is there a level within 1R of your target in the trade direction? If yes and it's a 15m FVG, Asia, BSL/SSL, or prev_day level — that's a meaningful tailwind.
2. **ALC filter:** 1–2 available levels in direction = best zone. 0 is neutral. 3+ is a flag to reduce or skip.
3. **Obstruction is not a dealbreaker.** One level between entry and TP is fine — it may actually help by being swept en route.
4. **Confluence cuts both ways.** A single clean level target beats a stacked zone.
5. **London and overnight as nearest targets underperform.** These are often swept as part of the opening drive rather than being strong singular draws.

---

## Study 2: Level hit rate — which levels get hit in the first 45 min?

**Script:** `study_level_hit_rate_45min.py`
**Source:** `liquidity_levels.csv` (available levels per day) × 30s bar H/L for 9:30–10:15 window.

"Available" here = `swept_pre_rth = False` and valid price on that date. Scoped to levels within **300 pts** of RTH open (run `--scope N` to change).

**Coverage:** 13,979 level-day pairs across 616 days, all groups.

**Availability notes:**
- `6am_high / 6am_low` — forms at close of the 6am 4H candle (10:00 AM ET). Hit window = 10:00–10:15 only (15 min).
- `or_high / or_low` — not computed (stub). Excluded.
- `overnight_high / overnight_low` — always available (they are the overnight extreme, cannot be swept before RTH opens).

### Group ranking: hit rate within first 45 min (≤300 pts from open)

| Rank | Group | Hit Rate | n | Notes |
|------|-------|----------|---|-------|
| 1 | nwog | **72.5%** | 204 | Monday only |
| 2 | asia | **59.2%** | 1,078 | Strong consistent draw |
| 3 | bsl_ssl | **56.5%** | 1,096 | London swing H/L |
| 4 | london | **54.3%** | 1,096 | |
| 5 | 6am | **46.1%** | 1,106 | 15-min check window (10:00–10:15) |
| 6 | htf_fvg_Daily | 43.8% | 429 | |
| 7 | overnight | 41.1% | 1,067 | |
| 8 | prev_day | 40.6% | 937 | |
| 9 | htf_fvg_4H | 35.9% | 1,153 | |
| 10 | htf_fvg_1H | 30.5% | 2,063 | |
| 11 | htf_fvg_15m | 29.0% | 3,750 | |

**Key takeaway:** Session structure levels (NWOG, Asia, BSL/SSL, London) get hit far more often than HTF FVGs. If an Asia or London level is available and within range, expect a 55–60% base rate of price visiting it in the first 45 min.

### Distance from open is the dominant factor

| Distance from RTH open | Hit Rate | n |
|------------------------|----------|---|
| 0–25 pts | **88.1%** | 2,185 |
| 25–50 pts | **67.1%** | 2,031 |
| 50–100 pts | 44.2% | 3,248 |
| 100–200 pts | 19.3% | 3,879 |
| 200–300 pts | 6.8% | 2,636 |

**This is the single most powerful predictor.** A level within 25 pts of the open gets hit 88% of the time. Beyond 100 pts, hit rate drops below 20%. For continuation target selection, prioritize levels inside 100 pts.

### Group × distance (hit rate %)

| Group | 0–25 | 25–50 | 50–100 | 100–200 | 200+ |
|-------|------|-------|--------|---------|------|
| htf_fvg_Daily | **100%** | **96.8%** | 81.8% | 40.4% | 9.0% |
| htf_fvg_4H | 95.1% | 81.0% | 58.2% | 24.2% | 7.4% |
| htf_fvg_1H | 93.4% | 73.7% | 46.8% | 18.2% | 4.9% |
| asia | 92.4% | 73.2% | 54.3% | 30.1% | 27.1% |
| htf_fvg_15m | 92.2% | 68.2% | 38.1% | 13.4% | 3.0% |
| bsl_ssl | 90.5% | 68.7% | 46.6% | 22.2% | 29.5% |
| prev_day | 94.2% | 68.3% | 43.1% | 24.5% | 11.7% |
| london | 90.0% | 66.8% | 43.6% | 18.8% | 20.9% |
| overnight | 83.8% | 57.8% | 34.6% | 11.6% | 7.1% |
| nwog | 97.7% | 70.0% | 33.3% | 8.3% | 0.0% |
| 6am | 66.8% | 52.1% | 37.1% | 21.2% | 23.1% |

**Notable:** HTF Daily FVG within 50 pts is hit 96.8% of the time. When a Daily FVG is right there, price is nearly certain to interact with it. Asia and BSL/SSL maintain elevated hit rates even at 100–200 pts (27–30%) compared to HTF 15m (13%) — session levels have a gravitational pull that persists at distance.

### Gap direction effects

| Group | flat gap | gap down | gap up |
|-------|----------|----------|--------|
| nwog | **92.9%** | 75.9% | 68.7% |
| asia | 66.7% | 56.0% | 60.7% |
| bsl_ssl | 63.3% | 52.3% | 58.5% |
| london | 56.7% | 50.8% | 56.4% |
| overnight | 45.6% | 35.5% | 43.8% |
| prev_day | 34.6% | 38.3% | 43.2% |
| htf_fvg_Daily | 31.6% | 47.6% | 43.8% |

**NWOG is most sensitive to gap direction.** A flat gap on Monday means 93% hit rate — the market hasn't moved away from the weekly open. Gap up or down reduces it significantly.

**prev_day reverses the pattern** — higher hit rate on gap_up days (43%) than flat (35%). When the market gaps toward prev_day resistance, it follows through to tag it.

**HTF Daily FVG** is more likely hit on gap_down days (47.6%) than flat (31.6%), suggesting gap_down days create the move that runs into those support zones.

### 9:30 candle direction

| Group | Down candle | Up candle |
|-------|-------------|-----------|
| htf_fvg_1H | 33.8% | 26.8% |
| htf_fvg_4H | 38.2% | 33.6% |
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
| asia | flat | up | 61.8% | 34 |
| asia | gap_up | down | 61.7% | 308 |
| bsl_ssl | gap_up | down | 60.5% | 314 |
| asia | gap_up | up | 59.5% | 274 |
| london | flat | down | 58.9% | 56 |
| london | gap_up | down | 57.8% | 315 |
| asia | gap_down | up | 57.0% | 207 |
| htf_fvg_Daily | gap_down | down | **55.1%** | 78 |

**For a continuation model:** Asia and BSL/SSL on gap_up days with a down 930 candle show ~60% hit rate with large sample sizes (274–314 trades). These are your highest-confidence targets in this dataset.

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

### Data sources

| Use | File |
|-----|------|
| Level construction | `data/consolidated/nq-front-month.ohlcv-30s.csv` |
| In-session sweep detection | `data/raw/glbx-mdp3-20231002-20251027.ohlcv-30s-trading-session.csv` |
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

**Bullish FVG** (`c1.high < c3.low`): gap bottom = `c1.high`, top = `c3.low`. Mitigation: later bar `low <= bottom`.

**Bearish FVG** (`c1.low > c3.high`): gap bottom = `c3.high`, top = `c1.low`. Mitigation: later bar `high >= top`.

`price` in `liquidity_levels.csv` = `fvg_mid` for HTF rows. `fvg_top` / `fvg_bottom` retain the zone. Hit rate study uses body edges for FVGs (enters the zone), not mid.

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
