# Near-Miss Liquidity Draw Study

## Question

Do FVGC trades taken on days where price made a strong impulsive approach toward a
named time-based liquidity level (Asia high/low, 6am high/low, prior-day high/low)
but fell short (came within 20 pts without touching, then reversed) outperform the
baseline? Does the directionality of the near-miss matter — i.e., does a near-miss
toward the same side as the trade help or hurt?

## Methodology

### Data

- **Candles:** 30s consolidated NQ front-month (`data/consolidated/nq-front-month.ohlcv-30s.csv`)
- **Session levels:** `data/levels/session_levels.csv` — pre-built Asia/6am/prev-day H/L per date
- **Baseline trades:** the full 8yr FVGC trade log, joined on date. By default `run.py`
  reads `logs/baseline_trades.csv`, but that file has at times been clobbered to a
  shorter range (2024→26) by other studies. The 8yr log (2018→26) lives in
  `logs/baseline_trades.csv.preserve`; point `run.py` at it via the
  `NEAR_MISS_TRADES_CSV` env var to reproduce the results below:
  `NEAR_MISS_TRADES_CSV=logs/baseline_trades.csv.preserve python studies/near_miss_draw/run.py`

### Near-Miss Definition (tagger.py)

For each W1 bar window (9:30–10:15 ET, 30s bars):

1. **Impulsive leg:** A move of ≥15 points in a single direction within a rolling
   10-bar (5-minute) window. Direction is determined by whether the window low
   precedes the window high (upward) or vice versa.
2. **Proximity:** The extreme of the leg (window high for up, window low for down) falls
   within 20 pts of a named liquidity level on the appropriate side — resistance for
   upward moves, support for downward moves.
3. **Confirmation:** Price reverses ≥5 pts off the extreme before end of W1 (10:15 ET).

When multiple near-miss events occur on the same day, the one closest to the level
(smallest `near_miss_distance_pts`) is retained.

**FVG gap count** (`near_miss_gap_count`): count of FVGs created during the impulsive
leg using `detect_fvg` from `fvgc/model.py`. Direction-matched (bullish FVGs for
upward legs, bearish for downward).

### The Setup Being Tested

Price near-misses a resistance (or support) level, reverses, and retraces enough to
produce a new FVGC entry signal. That signal is taken **in the same direction** as
the original near-miss approach — effectively "going back for it." Bonus: a second
named liquidity level sits between the entry and the original target, creating a
stacked magnetic draw (e.g., 6am High between FVG entry and Asia High as in the
May 14 '26 textbook example).

### Cohort Splits (run.py)

| Cohort | Definition |
|--------|-----------|
| **C1 — "going back for it" (main signal, causally clean)** | `near_miss_present=True` + aligned direction (`up`→`long`; `down`→`short`) + entry **after** `near_miss_confirmed_time` + near-miss level still above entry (longs) / below entry (shorts) |
| **C1b — "going back for it + stacked draw"** | C1 + at least one other named level between entry price and near-miss target |
| **C2 — "fade of near miss"** | `near_miss_present=True` + opposite direction + entry after confirm |
| **C3 — aligned + near miss, all** | `near_miss_present=True` + aligned direction, no time/level gate (shows full population vs C1) |
| **C4 — control** | `near_miss_present=False` |

Only `win` / `loss` outcomes count toward stats; `skip`, `eod`, `ambiguous` excluded.

## Results

8yr baseline (2018-01-02 → 2026-05-15). Tagger produced near-miss days on 59.4% of
trading sessions (1557/2620 days); 421 near misses triggered against in-session FVGs.

_Re-run 2026-06-13 against `logs/baseline_trades.csv.preserve` (8yr); all headline
numbers below reproduced exactly, including C1 longs ≤10pts = 61.2% WR / PF 1.66 (n=134)._

### Cohort overview

| Cohort | n | W | L | WR% | PF | avgPnL |
|--------|---|---|---|-----|----|--------|
| BASELINE (all trades) | 4542 | 2248 | 2294 | 49.5 | 1.00 | -0.04 |
| C4 — no near miss on day (control) | 1167 | 543 | 624 | 46.5 | 0.84 | -2.17 |
| C3 — aligned + near miss, all | 1778 | 953 | 825 | **53.6** | **1.19** | +2.25 |
| C1 — going back for it (clean) | 299 | 158 | 141 | **52.8** | **1.21** | +2.26 |
| C1b — C1 + stacked intermediate draw | 44 | 20 | 24 | 45.5 | 0.71 | -3.86 |
| C2 — fade of near miss | 697 | 335 | 362 | 48.1 | 0.96 | -0.44 |

**Key finding:** The near-miss + aligned signal is real (C3/C1 both +3pp WR vs baseline,
positive PF). The "fade" is a slight loser. The stacked-draw sub-filter (C1b) *hurts* —
the intermediate level appears to be creating chop/resistance that stops the trade before
it reaches the near-miss target.

### C1 breakdown by near-miss level type

| Level | n | WR% | PF | avgPnL |
|-------|---|-----|----|--------|
| asia_high | 24 | **66.7** | **2.33** | +10.83 |
| insession_5m_bearish | 22 | **68.2** | **2.05** | +8.86 |
| insession_15m_bullish | 4 | 75.0 | 2.17 | +8.75 *(tiny n)* |
| asia_low | 35 | 54.3 | 1.51 | +5.00 |
| 6am_high | 85 | 56.5 | 1.31 | +2.94 |
| prev_day_high | 19 | 47.4 | 1.24 | +2.37 |
| insession_5m_bullish | 23 | 43.5 | 0.69 | -4.57 |
| 6am_low | 69 | 44.9 | 0.93 | -0.87 |
| prev_day_low | 15 | 40.0 | 0.65 | -5.67 |
| insession_15m_bearish | 3 | 33.3 | 0.30 | -11.67 *(tiny n)* |

Pattern: **resistance levels** (asia_high, 5m bearish FVG, 6am_high) have consistent
edge for longs going back toward them. **Support levels** (6am_low, prev_day_low) are
net-negative — shorts going back toward support are not the edge.

### C1 by direction

| Direction | n | WR% | PF | avgPnL |
|-----------|---|-----|----|--------|
| LONG | 153 | **58.2** | **1.50** | +4.67 |
| SHORT | 146 | 47.3 | 0.98 | -0.27 |

**The entire C1 edge is in LONGS.** Shorts going back for the near-miss are coinflip.

### C1 LONGS: distance buckets

| Distance | n | WR% | PF | avgPnL |
|----------|---|-----|----|--------|
| 0–5 pts | 109 | **60.6** | **1.56** | +4.91 |
| 5–10 pts | 25 | **64.0** | **2.07** | +9.60 |
| 10–15 pts | 12 | 25.0 | 0.41 | -9.58 ← kill zone |
| 15–20 pts | 7 | 57.1 | 2.00 | +7.86 *(tiny n)* |

Distance 10–15 pts is a kill zone (n=12, 25% WR). Filtering to ≤10pts gives:

**C1 LONGS, distance ≤10 pts: 61.2% WR / PF 1.66 (n=134)** ← candidate headline

Full per-trade CSVs: `results/trades_*.csv`
Summary CSV: `results/cohort_summary.csv`

## Caveats

### (a) Arbitrary first-pass thresholds

The 20 pt (near-miss threshold) and 15 pt (minimum leg size) values are first-pass
choices. They are not optimised and should not be selected by grid search — doing so
would require a fresh OOS holdout. The 5 pt reversal requirement is similarly
a minimum floor.

### (b) "Impulsive" approximated by range-in-window

The 10-bar rolling range captures large moves but also catches choppy back-and-forth
bars that accumulate 15 pts of range without being directional. True displacement
(single-directional momentum) would require an additional check, e.g., that the
leg net-move is at least X% of the window range. This is a known approximation.

### (c) Lookahead risk — entry-before-confirmation

The near-miss is confirmed only after the ≥5 pt reversal is observed, which happens
sometime during W1. Trades entered *before* the confirmation bar are causal-ambiguous:
the trader couldn't have known the near-miss was complete at entry time.

`run.py` flags these with `entry_before_nm_confirm=True` on the merged DataFrame and
prints a count. **For a strictly causal interpretation of cohort 1 and cohort 2,
exclude rows where `entry_before_nm_confirm=True` before drawing conclusions.**

The confirmation time is stored as `near_miss_confirmed_time` in `near_miss_days.csv`.
