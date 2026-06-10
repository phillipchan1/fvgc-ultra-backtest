# NQ Session Path Almanac — 9:30–10:15 ET

**Sample:** 2,148 RTH sessions, 2018-01-02 → 2026-05-21, NQ front-month 30s bars.
**Every number carries (n=…) and a 95% Wilson CI.** Definitions frozen in
[DEFINITIONS.md](DEFINITIONS.md) before computation. Null = 500 within-session bar
shuffles (volatility preserved, path order destroyed). "Recent" = 2023–2025.

Labels: **STRUCTURAL** = deviates from the vol-matched null by ≥5pp (these are the
only stats that say something about *path structure*). **MECHANICAL** = true and
useful for expectations, but fully explained by distance + volatility — a shuffled
tape would give you the same number. Stationarity: the brief's strict rule flags
most stats DRIFTING at n≈2,150 by construction; where the chi-square heterogeneity
companion test says year-to-year variation is just sampling noise (het p ≥ 0.05),
the stat is marked *stable-in-practice*. See analysis.md §5.

---

## The 10 numbers worth memorizing

1. **94%** — one side of the 15-minute OR is taken by 10:15 (93.9%, n=2,148,
   CI 92.8–94.8). Phil's remembered number is right, and it refers to the 15m OR
   (the 5m OR version is 99.8%). But this is MECHANICAL — a shuffled tape breaks
   the OR **97.3%** of the time. Reality is 3.4pp *below* chance. Don't treat an
   OR break as information; treat NOT breaking (6%) as the unusual event.
2. **14%** — both sides of the 15m OR are taken by 10:15 (13.6%, n=2,148,
   CI 12.2–15.1; null 23.5%). STRUCTURAL, same sign all 8 years. The morning is
   far more one-sided than chance. Recent-3yr: 16.3%. Full two-way fear is
   mostly unfounded in the first 45 minutes.
3. **59%** — after the first OR15 break, price never returns to the OR midpoint
   before 10:15 (return rate 40.6%, n=2,016 breaks, CI 38.5–42.8; null 52.4%).
   STRUCTURAL, same sign 8/8 years. Breaks hold noticeably better than chance.
4. **86%** — the 9:30–9:45 (W1) high or low is still the session extreme at
   10:15 (86.5%, n=2,148, CI 84.9–87.8; null 76.5%). STRUCTURAL. The first 15
   minutes usually prints an edge of the whole 45-minute range.
5. **73%** — W1's direction matches the 9:30→10:15 net direction (73.3%,
   n=2,134, CI 71.4–75.1; null 70.4%). Stable every single year (het p=0.86).
   Only weakly above chance — but the most reliable directional read you get.
6. **38–40%** — "continuation" in the strong sense: the 10:15 close lands
   beyond W1's directional extreme (up-W1 39.5% n=1,123; down-W1 37.0%
   n=1,017). Reversal through W1's opposite extreme: only **17–18%**. Direction
   persists; *extension* is a minority outcome. Memorize 5 and 6 together.
7. **The magnet ladder** (pooled over all 11 named levels, untaken at 9:30;
   unit = level-instance): P(touched by 10:15) by distance from the open:
   ≤0.10 ATR → **79%** (n=1,541); 0.10–0.25 → **47%** (n=4,256); 0.25–0.50 →
   **21%** (n=4,489); 0.50–1.00 → **5.5%** (n=3,039); >1 ATR → **0.8%**
   (n=1,009). MECHANICAL — null matches within 1pp at every rung. Distance and
   volatility are the whole story; *which* level it is adds nothing.
8. **74% / 56%** — an overnight extreme (ONH or ONL) is touched by 10:15 in
   73.8% of sessions (n=2,148, CI 71.9–75.7), and in 56% of sessions an ON
   extreme is the FIRST named level swept (ONH 32.0%, ONL 24.3%). The opening
   trades the overnight range first. Median first-touch: 2–4 minutes in.
9. **49%, but gap decides** — a prior-day extreme (PDH or PDL) is touched by
   10:15 in 48.9% of sessions overall (n=2,148); 63.7% when the gap is flat
   (n=449) vs 27.7% on a large gap-up (n=184) and 30.4% on a large gap-down
   (n=168). Gap size = distance to yesterday's range; same mechanical ladder.
10. **3–4×** — at 9:45, remaining untaken draws AHEAD of W1's direction get
    touched in W2/W3 at 21–33% (per level), draws BEHIND W1's direction at only
    5–11%. Example after an up-W1: ONH (above) 26.2% (n=623) vs ONL (below)
    8.9% (n=1,000). The cheapest live-read in the atlas.

---

## Mechanical truths (true, useful, not structure)

These set expectations. None of them beats the shuffle null — do not read
"confirmation" or "smart money" into them.

| Stat | Value (n, CI) | Null |
|---|---|---|
| OR5: ≥1 side taken by 10:15 | 99.8% (2,148; 99.5–99.9) | 100.0% |
| OR15: ≥1 side taken by 10:00 | 81.6% (2,148; 79.9–83.2) | — |
| OR15 first break = high side (given break) | 51.4% (2,016; 49.2–53.6) | 51.1% |
| Median time of first OR15 break | 9:48 ET (IQR 9:45–9:52) | 9:47.5 |
| Median time of first OR5 break | 9:35:30 (IQR 9:35–9:37:30) | — |
| Extension ≥10/20/30/50 pts beyond broken side | 77% / 57% / 44% / 26% (2,016) | 79/61/48/29% |
| Extension ≥0.25 ATR beyond broken side | 19.1% (2,016; 17.4–20.8) — STRUCTURAL low vs null 24.6% | 24.6% |
| Nearest untaken named draw touched by 10:15 | 67.4% (2,148; 65.4–69.3), stable | 67.5% |
| Nearest BELOW draw before nearest ABOVE draw | 46.6% (1,822; 44.3–48.9) of decided; 39.6% of all both-side sessions | 46.0% |
| PD high+low both pre-RTH-untaken touch rates | see magnet ladder — nothing special about PD levels | matches |
| 9:30–10:15 range | median 0.43 ATR (IQR 0.33–0.57; n=2,148) | mean matches null |
| MFE / MAE from the open | median 0.18 / 0.18 ATR | — |
| Net move (close−open) | median ~0; ±0.39 ATR at p10/p90 | — |

Point-based extension stats (10/20/30/50 pts) drift hard with NQ's price level
(het p<1e-4); use the ATR-normalized row for cross-year thinking. Recent-3yr:
≥20pts = 67%, ≥50pts = 34%.

---

## Folk beliefs this data killed

1. **"More liquidity below means price goes down first."** Inverted. With a
   below-heavy draw map, the nearest below-draw is hit first only **27.5%**
   (n=666, CI 24.2–31.0) vs 46.6% marginal; above-heavy → **70.3%** (n=445).
   Draw-count asymmetry is a *distance proxy*: a lopsided map means you opened
   at one end of the recent range, and the lone draw behind you is closer than
   the crowd ahead. (Phil's template query — see PRE_SESSION_LOOKUP.md §4.)
2. **Two-day streaks mean nothing.** up-up vs down-down vs mixed: 0 of 30
   tested cells move any Tier-1 event; every delta <4pp. E.g. P(OR15 both
   sides | down-down) = 15.2% vs 13.6% marginal (n=448, q=0.74).
3. **Prior-day type (alone) means almost nothing** for the morning: 2 of 50
   cells move, both marginal. Inside/outside/trend days do not set up a
   predictably different first 45 minutes.
4. **Day of week means almost nothing**: 1 of 50 cells (Wednesday lowers
   W1→net persistence to 67.5% vs 73.3%, n=427, q=0.078 — fragile, treat as
   noise until it survives a fresh sample).
5. **You cannot predict the morning's shape at 9:30.** Zero of 180 tested
   archetype × conditioner cells move ≥5pp at FDR q=0.10 (42 more suppressed
   at n<30). The path archetype is decided
   in-session, not pre-market.
6. **"Levels pull price."** No level shows touch rates above its
   distance-matched null — not PDH/PDL, not ON, not Asia/London/6am, not prior
   close. The magnet ladder is pure distance×vol. (The E2 aged-naked-VP-POC
   result from the VP program is trade-conditional and not contradicted here.)
7. **The 97% 6am claim is true but not tradeable as stated.** P(6am H or L
   taken by the 10:00 candle close) = **97.0%** (n=2,148, CI 96.2–97.7) under
   the repo definition (04:00–08:00 window H/L), *counting 8:00–9:30 pre-market
   sweeps*. By 10:00 strictly: 95.7%. Literal 06:00–9:30 pre-open H/L: 93.4%
   (n=2,147) by 10:15, 89.7% by 10:00. The catch: conditional on a 6am side
   still being intact at 9:30, it gets touched by 10:15 only **45.1%**
   (n=1,995, CI 42.9–47.3). The 97% is mostly (a) the level being taken before
   RTH even opens and (b) near-distance mechanics. As a "the market will take
   it after the open" claim, it's a coin flip.
8. **"94% OR break" as evidence of directional energy.** Verified at 93.9% —
   but a random path breaks 97.3%. The break itself carries no information;
   what carries information is one-sidedness after the break (#2, #3 above).

---

## Reference tables

### OR behavior (full)
See `part1_base_rates.csv` section A_OR (16 stats). Key conditional movers:
- Extension ≥0.25 ATR | break: 26.4% after expanded overnight (n=640) vs 12.2%
  after compressed (n=631), marginal 19.1%. The only clean non-geometric
  conditional on OR behavior.
- Return to mid | break: 49.8% on flat-gap premium opens (n=215) vs 40.6%
  marginal (q=0.075).

### Named-level touch probabilities (per level × distance)
See `part1_base_rates.csv` section B_magnet (60 rows). All MECHANICAL;
use the pooled ladder (#7 above) plus the level's current distance.
Median touch times: ≤0.10 ATR rung ≈ 1 min after open; 0.10–0.25 ≈ 7–8 min;
0.25–0.50 ≈ 20 min; 0.50–1.00 ≈ 29 min.

### First-sweep identity (which level goes first, n=2,148)
ONH 32.0% (30.1–34.0) · ONL 24.3% (22.5–26.2) · none 15.0% (13.6–16.6) ·
6amL 7.2% · 6amH 6.4% · LondonL 6.0% · LondonH 5.1% · AsiaH 1.2% · AsiaL 1.1% ·
PDH 0.7% · PDL 0.7% · prev-close 0.4%. Median first-sweep time: 2–6 min.

### Ping-pong (opposite side of the pair also swept by 10:15, both untaken at 9:30)
PD pair: 1.0% after PDH-first (n=99), 0.0% after PDL-first (n=85) ·
ON pair: 5.9% (n=882) / 3.8% (n=704) · London: 10.6% (n=320) / 10.9% (n=304) ·
6am: 17.3% (n=225) / 17.8% (n=231) · Asia: 7.3% (n=41, LOW-N) / suppressed.
Two-way level runs in the first 45 min are rare; the wider the pair, the rarer.

### Archetypes (n=2,148; not conditionable at 9:30)
STRAIGHT_RUN 42.9% (40.8–45.0) · FAILED_BREAK 24.1% (22.4–26.0) ·
TWO_WAY_SWEEP 13.6% (12.2–15.1) · SWEEP_AND_REVERSE 7.6% (6.6–8.8) ·
BALANCE_CHOP 6.2% (5.2–7.2) · BREAK_RETEST_GO 5.6% (4.7–6.7).
Regime note (chi² p=2.9e-05): since 2022, TWO_WAY_SWEEP ≈15–18% (was 10–11%)
and BALANCE_CHOP ≈3–6% (was up to 12%). Use recent shares for live priors.

### W1 → W2/W3 transition table (consult at 9:45)
| W1 state | continuation | chop | reversal | n |
|---|---|---|---|---|
| up | 39.5% (36.7–42.4) | 42.7% (39.8–45.6) | 17.8% (15.7–20.2) | 1,123 |
| down | 37.0% (34.1–40.0) | 46.0% (43.0–49.1) | 17.0% (14.8–19.4) | 1,017 |
| up, OR5 both sides broken | 40.7% | 47.5% | 11.7% | 162 |
| up, OR5 low broken (contradictory W1) | 26.4% | 44.8% | 28.7% | 87 LOW-N |
| down, OR5 low broken (aligned) | 37.1% | 49.1% | 13.8% | 749 |
| down, OR5 high broken (contradictory) | 41.9% | 36.0% | 22.1% | 86 LOW-N |

continuation = 10:15 close beyond W1's directional extreme; reversal = beyond
the opposite extreme; chop = close inside W1's range. W1-sweep (Y/N) shifts
these by ≤3pp — knowing a level was swept in W1 adds nothing to the 3-way read.

### Remaining-draw touch in W2/W3 (as-of 9:45; denominator = untaken at 9:45)
Ahead of W1 direction: 6am 32% · London 27–30% · ON extreme 26% · Asia 21% ·
prev-close 14–15% · PD extreme 9–10% (distance-ordered, as the ladder predicts).
Behind W1 direction: 5–11% across all levels. Full table:
`part3_transitions.csv` (table=draw_touch_w23).
