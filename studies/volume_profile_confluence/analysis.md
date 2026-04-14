# Volume Profile Confluence Study

## Question

Does the FVGC entry model perform better when entries occur near prior-day
volume profile levels (POC, VAH, VAL)? Is there an additive confluence model?

## Background: Volume Profile Primer

Volume Profile is a horizontal histogram showing how much volume traded at each
price level during a session. Three key levels:

- **POC (Point of Control):** The price where the most volume traded. Acts as a
  magnet — price tends to gravitate back to it.
- **VAH (Value Area High):** Top of the 70% value area. Acts as resistance.
- **VAL (Value Area Low):** Bottom of the 70% value area. Acts as support.
- **Value Area:** The price range containing 70% of the session's total volume.
  Prices inside the VA are "accepted"; prices outside are "rejected."

For this study we use the **prior day's RTH (9:30-16:00 ET) volume profile**
computed from 30s OHLCV candles with 1.0 NQ-point price buckets.

### How to Set Up Volume Profile on TradingView

1. Open NQ futures chart (any timeframe — 1m or 5m recommended for intraday)
2. Click **Indicators** (top toolbar) → search **"Session Volume Profile"**
3. Add it to the chart
4. Click the gear icon on the indicator → **Inputs**:
   - Session: **Regular** (this gives you RTH 9:30-16:00)
   - Value Area Volume: **70**
5. Under **Style**:
   - Enable: **POC**, **Value Area High**, **Value Area Low**
   - Extend POC/VA lines: **Right** (so they project into the next session)
   - Pick distinct colors — e.g. POC = yellow, VAH = red, VAL = green
6. The prior day's POC, VAH, and VAL lines will now extend into the current
   session as horizontal levels

**Alternative (Fixed Range):** If you want to manually draw VP for a specific
day, use **Indicators → Fixed Range Volume Profile**, then click-drag from the
prior day's 9:30 bar to the 16:00 bar. Same settings apply.

### How to Track in Tradezella

Tradezella does not have a built-in volume profile overlay. Workflow:

1. Use TradingView for live VP levels during the session
2. Log trades in Tradezella as usual
3. Create a **custom tag**: `thu_va_play` for this specific play
4. In the trade notes, record: `Prior day POC: ___  VAH: ___  VAL: ___`
5. Filter your journal by the `thu_va_play` tag to track live performance
6. Compare your live WR/PF against the backtest numbers below

---

## Methodology

1. Built daily VP (POC/VAH/VAL) from consolidated 30s NQ candles for 580
   trading days (Oct 2023 – Mar 2026)
2. Enriched 1,569 tradeable (win/loss) baseline entries with VP proximity
3. Tested proximity thresholds (10/15/20 NQ pts + R-based), value area
   position, directional alignment
4. Permutation testing (10k perms) for statistical significance
5. Cross-timeframe validation (30s, 1m, 5m)
6. Additive confluence testing with existing factors

---

## Key Results

### VP Proximity Alone: No Edge

| Filter | N | WR | PF | p (WR) |
|--------|---|----|----|--------|
| **ALL TRADES** | 1,569 | 51.8% | 1.09 | — |
| Near any VP (15pt) | 314 | 49.4% | 1.00 | 0.19 |
| NOT near VP (15pt) | 1,255 | 52.4% | 1.12 | — |
| Inside VA | 454 | 50.7% | 1.16 | 0.31 |
| Outside VA | 1,115 | 52.2% | 1.07 | — |

VP proximity is neutral to slightly negative. Not an edge by itself.

### Directional Alignment: Negative Signal

| Filter | N | WR | PF | p (WR) |
|--------|---|----|----|--------|
| Longs near VAL (15pt) | 49 | 40.8% | 0.66 | 0.08 |
| Shorts near VAH (15pt) | 71 | 42.3% | 0.78 | 0.06 |
| **Dir. VP aligned** | **120** | **41.7%** | **0.73** | **0.013** |

Statistically significant in the *wrong* direction. Entries near
directionally-aligned VP levels (longs at support, shorts at resistance)
underperform. These levels attract liquidity sweeps that run stops.

### Near POC: Interesting but Small N

| Filter | N | WR | PF | p (PF) |
|--------|---|----|----|--------|
| Longs near POC (10pt) | 32 | 62.5% | 2.29 | 0.030 |
| Longs near POC (15pt) | 49 | 57.1% | 1.92 | 0.034 |

PF is statistically significant but WR is not (p=0.14-0.27). Monthly
consistency is choppy (some months 0/4, others 3/3). Needs more data.

---

## THE PLAY: Thursday + Inside Value Area

### Stats

| Metric | Value | Baseline |
|--------|-------|----------|
| **N** | 76 | 1,569 |
| **Win Rate** | **73.7%** | 51.8% |
| **Profit Factor** | **2.89** | 1.09 |
| **Total PnL** | +1,085 pts | +1,910 pts |
| **p-value (WR)** | **0.0002** | — |
| **p-value (PF)** | **0.0003** | — |

### Why It Works (the interaction)

Neither factor alone has an edge:
- Thursday alone: 55.2% WR, p=0.09 (not significant)
- Inside VA alone: 50.7% WR, p=0.31 (not significant)
- **Thursday + Inside VA: 73.7% WR, p=0.0002** (highly significant)

The edge is the interaction. Hypothesis: Thursdays see institutional
rebalancing and options positioning ahead of Friday expiration. When NQ opens
inside the prior day's Value Area, the market is in balance/acceptance mode.
FVGC entries in this environment catch clean rotations within accepted value
rather than getting swept by directional moves.

### Direction: Both Work Equally

| Direction | N | WR | PF | PnL |
|-----------|---|----|----|-----|
| Long | 42 | 73.8% | 2.49 | +545 |
| Short | 34 | 73.5% | 3.57 | +540 |

Not directionally biased — take whatever the model gives you.

### Macro Window Breakdown

| Window | Time | N | WR | PF | PnL |
|--------|------|---|----|----|-----|
| MW1 | 9:30-9:45 | 14 | 78.6% | 4.06 | +260 |
| **MW2** | **9:45-10:00** | **34** | **79.4%** | **3.95** | **+590** |
| MW3 | 10:00-10:15 | 28 | 64.3% | 1.81 | +235 |

All three macro windows are valid. MW2 is strongest with most volume.
MW4 had 0 trades in sample — play ends at 10:15.

### Variant Breakdown

| Variant | N | WR | PF |
|---------|---|----|----|
| **no_fvg** | **30** | **83%** | **5.68** |
| bos | 24 | 67% | 2.23 |
| ifvg | 15 | 67% | 1.78 |
| protected_swing | 7 | 71% | 3.00 |

All variants profitable. `no_fvg` is the standout (83% WR, 5.68 PF).

### Context Enrichment

| Factor | Value | N | WR | PF |
|--------|-------|---|----|----|
| 930 candle | **bearish** | 30 | **80%** | **4.96** |
| 930 candle | bullish | 46 | 70% | 2.22 |
| Overnight | up | 40 | 75% | 3.46 |
| Overnight | down | 27 | 70% | 2.62 |
| VIXY | normal | 18 | 83% | 5.24 |
| VIXY | elevated | 12 | 75% | 3.31 |
| VIXY | high | 38 | 68% | 2.32 |
| News | no red folder | 66 | 73% | 2.83 |
| News | has red folder | 10 | 80% | 3.24 |

Works across all contexts. Bearish 930 + normal VIXY are the strongest
sub-filters but sample sizes get thin.

### Multi-R Hit Rates

| R-Level | Thu + Inside VA | Baseline | Delta |
|---------|-----------------|----------|-------|
| 1R | 73.7% | 51.8% | +21.9% |
| 1.5R | 57.9% | 41.0% | +16.9% |
| **2R** | **50.0%** | **34.4%** | **+15.6%** |
| 2.5R | 44.7% | 29.3% | +15.4% |
| 3R | 35.5% | 26.1% | +9.4% |
| 4R | 22.4% | 21.4% | +1.0% |
| 5R | 18.4% | 18.1% | +0.3% |

Half of these trades reach 2R. The edge decays after 3R — target 1R-2R,
not runners.

### Monthly Consistency

| Month | N | W | L | WR | PnL |
|-------|---|---|---|------|------|
| 2023-10 | 2 | 1 | 1 | 50% | -5 |
| 2023-12 | 5 | 3 | 2 | 60% | +40 |
| 2024-01 | 2 | 2 | 0 | 100% | +40 |
| 2024-04 | 1 | 0 | 1 | 0% | -30 |
| 2024-05 | 3 | 3 | 0 | 100% | +80 |
| 2024-06 | 4 | 4 | 0 | 100% | +60 |
| 2024-07 | 3 | 2 | 1 | 67% | +25 |
| 2024-08 | 7 | 5 | 2 | 71% | +110 |
| 2024-09 | 5 | 4 | 1 | 80% | +80 |
| **2024-10** | **6** | **6** | **0** | **100%** | **+205** |
| 2024-11 | 2 | 2 | 0 | 100% | +80 |
| 2024-12 | 4 | 2 | 2 | 50% | +15 |
| 2025-01 | 1 | 1 | 0 | 100% | +35 |
| 2025-02 | 1 | 1 | 0 | 100% | +40 |
| 2025-03 | 1 | 0 | 1 | 0% | -20 |
| 2025-04 | 5 | 4 | 1 | 80% | +95 |
| 2025-05 | 2 | 1 | 1 | 50% | -10 |
| 2025-06 | 3 | 3 | 0 | 100% | +110 |
| 2025-08 | 5 | 3 | 2 | 60% | +30 |
| 2025-09 | 5 | 4 | 1 | 80% | +70 |
| 2025-10 | 9 | 5 | 4 | 56% | +35 |

21 months with data. Only 3 losing months (all n=1-2 trades). No catastrophic
drawdowns. The worst stretch was Oct 2025 at 56% WR — still profitable.

### SL Stats

- Mean SL: 29.4 pts
- Median SL: 30.0 pts
- Range: 15-60 pts

Standard FVGC stop sizing. Nothing unusual.

---

## Sample Trades — Narrative Walkthroughs

### Winner: 2024-10-10 (Thu) — Two Longs Inside VA

**Prior day VP:** POC 20414, VAH 20483, VAL 20341

Wednesday was a range day that built heavy volume around 20414. Thursday
opens and NQ is rotating inside that accepted range. At 9:55 a bullish FVG
forms and taps — entry long at 20356.50, right in the middle of the VA. Entry
is 58 pts from POC, well within the value area. SL 45 pts. Price rotates up
through the VA, hits 1R cleanly. MFE reached 152 pts (3.4R). One minute later,
another long entry at 20378.00, also inside VA. Same result — win, MFE 130 pts.

**Why it worked:** Thursday rotation day, price accepted inside prior day's
value. No reason for price to break out aggressively. FVG entries caught the
natural rotation back toward POC and beyond.

### Winner: 2025-04-17 (Thu) — Short Inside VA

**Prior day VP:** POC 18626, VAH 18735, VAL 18351

Wednesday saw a wide range with POC at 18626. Thursday opens with a bearish
930 candle. At 9:32, a short BOS entry at 18433.75 — firmly inside the VA
(entry is 82 pts above VAL, 301 pts below VAH). SL 45 pts. Price drops
quickly, MFE 172 pts (3.8R). The short works because price is rotating within
accepted value, and the bearish 930 candle confirmed downward pressure.

### Winner: 2024-08-08 (Thu) — Long BOS, Huge MFE

**Prior day VP:** POC 18522, VAH 18558, VAL 18128 (wide 430pt VA)

Very wide VA from a volatile Wednesday. Thursday at 9:59, a long BOS entry
at 18208.75, well inside the VA. SL 55 pts. This one ran — MFE 408 pts
(7.4R). The wide VA gave plenty of room for price to rotate back toward POC.

### Loss: 2025-04-10 (Thu) — IFVG Long Stopped Out

**Prior day VP:** POC 17430, VAH 18868, VAL 17202 (massive 1666pt VA)

Unusual day: prior day's VA was extremely wide (1666 pts) due to extreme
volatility. The VA covered almost the entire range, so "inside VA" was
trivially satisfied. At 10:08, a long IFVG entry at 18674.25, SL 60 pts.
Stopped out for -60 pts. The wide VA diluted the signal — when the VA is
this wide, it doesn't convey the same "accepted range" meaning.

**Lesson:** Extremely wide VA days (1000+ pts) may dilute the play.
Worth tracking VA width as a potential filter in future analysis.

### Loss: 2025-05-22 (Thu) — Long BOS Into Resistance

**Prior day VP:** POC 21516, VAH 21557, VAL 21240

Entry long at 21280.75, just 40 pts above VAL. SL 50 pts. Price failed to
rotate up and stopped out for -50 pts. Entry was near the bottom of the VA
with POC 235 pts away — the rotation distance was too far for a 50pt SL
to survive the noise.

---

## What VP Doesn't Do for FVGC

- **Directional alignment hurts.** Longs at VAL and shorts at VAH
  underperform (41.7% WR, p=0.013). VP levels attract liquidity sweeps.
- **Proximity alone is neutral.** Being near any VP level doesn't help.
- **Multi-timeframe confirms.** Same pattern at 1m and 5m — VP proximity
  is flat or slightly negative.
- **Runners are not improved.** VP doesn't help trades reach 4R-5R.

VP's value for FVGC is not as a proximity filter but as a **context
classifier** — specifically the Thursday + Inside VA combination.

---

## Execution Checklist

### Wednesday Night Prep
1. Pull up prior day's VP on TradingView (Session Volume Profile, Regular session)
2. Note VAH and VAL prices
3. Confirm tomorrow is Thursday
4. Set alerts at VAH and VAL if desired

### Thursday Morning
1. At the open, check: is NQ trading between VAL and VAH?
2. If yes, this play is active for MW1-MW3 (9:30-10:15)
3. Take any FVGC entry where entry_price is between VAL and VAH
4. Long or short — both work equally
5. Target 1R. If bearish 930 candle, consider trailing to 2R
6. SL per standard FVGC rules (median ~30 pts)

### Post-Trade
1. Log in Tradezella with `thu_va_play` tag
2. Note the VP levels in trade notes
3. Track live performance vs backtest (73.7% WR, 2.89 PF)
