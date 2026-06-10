# Pre-Session Lookup — NQ 9:30–10:15 worksheet

Answer the five questions below from the pre-market state (all knowable at
9:30), read off the rows that apply, then update once at 9:45 with §6.
Every number: probability (n, 95% CI). Source: 2,148 sessions 2018→2026-05.
Definitions: results/DEFINITIONS.md. ATR = yesterday's 14-day RTH ATR.

**Defaults that apply EVERY morning (no conditioning needed):**
- One side of the 15m OR will go: 94% (n=2,148, 92.8–94.8). Both sides: 14%
  (12.2–15.1) — recent years closer to 16–18%.
- If a side breaks, 59% of the time price never re-sees the OR midpoint
  before 10:15 (n=2,016).
- The 9:30–9:45 high/low will probably bound the morning: 86% (84.9–87.8).
- Expected 9:30–10:15 range: median 0.43 ATR (IQR 0.33–0.57).
- Shape priors (NOT predictable from pre-market state — use as-is):
  STRAIGHT_RUN 43% · FAILED_BREAK 24% · TWO_WAY 14% (recent 15–18%) ·
  SWEEP&REVERSE 8% · CHOP 6% (recent 3–6%) · BREAK_RETEST_GO 6%.

---

## Q1. Gap vs prior close, in ATR? (flat <0.10 / small <0.30 / medium <0.60 / large ≥0.60)

Drives only the PD-extreme question (distance mechanics):
P(PDH or PDL touched by 10:15):

| gap | p (n, CI) |
|---|---|
| flat | 63.7% (449, 59.2–68.0) |
| small_up | 52.6% (432, 47.8–57.2) |
| small_down | 58.6% (326, 53.2–63.8) |
| medium_up | 38.0% (355, 33.1–43.2) |
| medium_down | 47.4% (234, 41.1–53.8) |
| large_up | 27.7% (184, 21.7–34.6) |
| large_down | 30.4% (168, 23.9–37.7) |

Marginal: 48.9% (2,148). Nothing else moves with gap that distance doesn't
explain. Large gap + premium/above-range open → also read Q4/Q5 rows.

## Q2. Prior-day type? (outside / inside / trend_up / trend_down / neutral)

**Read nothing into it.** 2 of 50 tested cells moved; no stable story. Same
for two-day streak (Q3) — this question exists so you stop asking it.

## Q3. Two-day streak? (up-up / down-down / mixed)

**Moves nothing.** 0 of 30 cells. P(both OR sides | down-down) = 15.2%
(448, 12.2–18.9) vs 13.6% marginal. Skip.

## Q4. Where did we open in yesterday's range? (above / premium / discount / below)

Moves the *order of draws* (distance mechanics), not OR behavior:
P(nearest BELOW draw touched before nearest ABOVE draw), marginal 46.6%:

| open position | p (n, CI) |
|---|---|
| above_range | 31.4% (472, 27.3–35.7) |
| premium | 43.1% (601, 39.2–47.1) |
| discount | 56.5% (462, 51.9–61.0) |
| below_range | 63.1% (287, 57.3–68.5) |

## Q5. Draw-count asymmetry? (above_heavy / balanced / below_heavy, ±2 levels)

The inversion rule — the lone draw BEHIND the crowd is the near one:

| asymmetry | P(below-draw first) (n, CI) |
|---|---|
| above_heavy | 70.3% (445, 65.9–74.4) |
| balanced | 49.6% (711, 46.0–53.3) |
| below_heavy | 27.5% (666, 24.2–31.0) |

Two-way cells (pre-registered): above_range & below_heavy → 24.7% (368,
20.6–29.4); below_range & above_heavy → 73.8% (210, 67.5–79.3); discount &
above_heavy → 71.5% (172, 64.4–77.7); premium & below_heavy → 29.7% (232,
24.2–35.9).

**Phil's template query** ("leaning bullish, last two days up, needs sell-side
below first"): P(nearest below first | streak=up-up & below_heavy) = **31.7%
(n=218, CI 25.8–38.1)** vs 46.6% marginal — EXPLORATORY (this pair was not
pre-registered; treat as the draw-asym row, which it matches). The data says
the opposite of the intuition: in that state the above-side draw usually goes
first. Bullish continuation does NOT typically wait for a below-sweep in the
first 45 minutes.

**Overnight range vs 20-day (bonus, from Q1 inputs):** compressed ON →
P(ON extreme touched) 83.0% (687, 80.0–85.6) and extension ≥0.25 ATR | break
12.2% (631); expanded ON → ON touch 64.8% (677, 61.2–68.3) and extension
26.4% (640) vs 19.1% marginal. Compressed overnights leak into the ON levels
but then go nowhere; expanded overnights touch less but travel farther.

---

## §6. The 9:45 update (W1 just closed)

1. **Direction read:** W1 close vs 9:30 open. That direction matches the
   10:15 net direction 73% (n=2,134, 71.4–75.1) — but expect chop-extension,
   not fireworks:

| W1 | continuation (close beyond W1 extreme) | chop (inside W1 range) | reversal (beyond opposite extreme) | n |
|---|---|---|---|---|
| up | 39.5% | 42.7% | 17.8% | 1,123 |
| down | 37.0% | 46.0% | 17.0% | 1,017 |

2. **Contradiction flag:** if W1 closed against the OR5 side it broke
   (e.g. W1 up but OR5 low side was the break), reversal risk roughly
   doubles: 28.7% (n=87, LOW-N) / 22.1% (n=86, LOW-N).
3. **Which remaining draws are live:** draws AHEAD of W1 direction get
   touched in W2/W3 at 21–33% (6am 32%, London 27–30%, ON 26%, Asia 21%,
   prev-close 14%, PD 9–10% — distance-ordered); draws BEHIND at 5–11%.
   Roughly: ahead-side draw odds ≈ 3× behind-side.
4. **Whether W1 swept a level changes nothing** in the 3-way outcome (≤3pp).

---

*Suppression discipline: cells n<30 never shown; n<100 marked LOW-N. All rows
above n≥100 unless flagged. Conditioning depth ≤2, pre-registered only (one
labeled exploratory exception above).*
