# ATH Availability Study

## Question

When NQ's rolling ATH sits above the 9:30 open as an unswept liquidity magnet,
how often is it swept by 10:15? Does an overhead ATH change the WR of the
W1 short playbook or FVGC entries? The motivating trade: a W1 short (4
confluences) on 2026-04-23 with ATH ~150 pts overhead that lost — was the
magnet the reason?

## Data

- **Source**: 1m candles, `data/consolidated/nq-front-month.ohlcv-1m.csv`
- **Period**: 2023-10-02 → 2026-02-06 (bounded by `trading_days.csv`)
- **Sessions with 1m coverage**: 560
- **ATH definition**: rolling `max(high)` across every bar strictly before that
  day's 9:30 ET bar. Recomputed per session.
- **Window**: 9:30 – 10:15 for sweep detection, extended to 10:30 for post-sweep
  classification.

## Key finding #1 — ATH is a magnet only inside ~100 pts

| Bucket (dist ATH − open) | n | % days | P(sweep by 10:15) | median min-to-sweep |
|---|---:|---:|---:|---:|
| `<50 pts`       |  46 |  8.2% | **63.0%** | 2 |
| `50–100 pts`    |  55 |  9.8% | **27.3%** | 25 |
| `100–200 pts`   |  80 | 14.3% | **2.5%**  | 32 |
| `200–400 pts`   |  90 | 16.1% |   0.0%    | — |
| `>400 pts`      | 289 | 51.6% |   0.0%    | — |

**Takeaway.** The magnet hypothesis is strong under 50 pts (63% sweep) and
real-but-modest from 50–100 pts. From 100 pts out it's effectively zero. A
sweep from 150 pts away by 10:15 happens **~2.5% of sessions** — so "ATH is
close enough to pull price up" was **not** a good reason to skip today's short.

ATH is in play (≤400 pts overhead) on **48.4%** of all sessions; only **18.0%**
(101/560) have ATH within 100 pts — the cells where the magnet actually bites.

## Key finding #2 — post-sweep behavior is 3-way, not one-sided

Across all 46 sweep days:

| Post-sweep class     | n  | % |
|---|---:|---:|
| continuation         | 16 | 34.8% |
| fade (no reversal, close ends below ATH) | 14 | 30.4% |
| reversal (≥50 pts down within 30 min)    | 13 | 28.3% |
| sweep_and_hold       |  3 |  6.5% |

No clean one-sided narrative. Sweeping ATH does **not** consistently continue
("buy the breakout") and does **not** consistently reverse ("turtle soup").
Useful for sizing expectations but not a trade trigger on its own.

## Key finding #3 — ATH overhead does NOT degrade W1 shorts

W1 shorts (n=229 total, 60.7% baseline WR) segmented by ATH bucket:

| Bucket | n | WR | mean MFE (R) | MFE ≥ 2R | MFE ≥ 3R |
|---|---:|---:|---:|---:|---:|
| ALL           | 229 | 60.7% | 6.5 | 78.2% | 67.2% |
| `<50`         |  14 | 64.3% | 3.5 | 64.3% | 42.9% |
| `50–100`      |  12 | 50.0% | 6.0 | 83.3% | 83.3% |
| `100–200`     |  31 | 58.1% | 6.4 | 80.6% | 61.3% |
| `200–400`     |  45 | 66.7% | 8.2 | 86.7% | 80.0% |
| `>400`        | 120 | 60.0% | 6.3 | 77.5% | 66.7% |
| overhead <200 |  57 | 57.9% | 5.6 | 77.2% | 61.4% |
| overhead <400 | 102 | 61.8% | 6.7 | 81.4% | 69.6% |

The `100–200` cell (today's case) runs 58.1% WR — roughly in line with the
60.7% baseline. WR noise across buckets is within what you'd expect from
sample-size variance. **There is no base-rate case for vetoing a W1 short
because ATH is 100–200 pts overhead.** Today's loss looks like a normal
~40% tail event, not a structural misread.

Caveat — small signal in the `<50` cell: when W1 shorts trigger with ATH
literally right overhead, mean MFE collapses from 6.5R to 3.5R and the MFE≥3R
rate falls from 67% to 43%. WR stays OK, but trail-to-3R+ setups seem to
underperform. Worth revisiting after more samples accumulate — too thin
(n=14) to actually act on.

### Side cut — W1 shorts on days where ATH *did* get swept during the window

- n=5, 2 wins / 3 losses, 40% WR.

Only 5 trades, so not actionable, but directionally consistent with "shorting
into a fulfilled upward sweep is worse." Flag for revisit when dataset grows.

## Key finding #4 — ATH overhead does NOT boost FVGC longs either

FVGC long WR runs 48.3% – 53.6% across every bucket. Mean MFE is flat. No
evidence that "ATH is overhead → longs get pulled up" produces edge above the
baseline 51.5%.

FVGC shorts show the same flat pattern (51%–57% across buckets), with one
exception: `<50 pts` overhead drops to **44.0% WR (n=50)** — shorting when
ATH is right overhead hurts modestly. Again, n=50 is thin; treat as a hint.

## Answers to the original questions

1. **How often is ATH "in play" (≤400 pts, unswept at open)?** 48.4% of sessions.
   Tight-enough to be a real magnet (≤100 pts): 18.0%.

2. **P(sweep by 10:15 | ATH within X pts)?** `<50`: 63%. `50–100`: 27%.
   `100–200`: **2.5%**. `200+`: ~0%.

3. **Does the market continue or reverse after sweeping?** 3-way split:
   35% continuation / 30% fade / 28% reversal. No edge from the sweep event alone.

4. **Should ATH-overhead veto W1 shorts?** **No.** WR in the `100–200` bucket
   (today's case) is 58% vs 61% baseline. The loss today was a normal ~40%
   outcome, not a miscategorized setup.

## Playbook implications

**Do not add** an ATH-overhead veto to W1 short. The base rate doesn't support
it.

**Consider (requires more data)**: in the `<50 pts` cell, W1 shorts have normal
WR but reduced MFE expansion — might warrant a tighter trail / earlier profit
take. Needs n > 30 before acting.

**Pre-market context flag** — a useful pre-market briefing addition: when ATH
is within 100 pts and unswept, flag that 63% / 27% sweep-by-10:15 probability
so Phil's mental model matches the data. Beyond 100 pts, ATH should not
influence bias.

## Caveats

- **Bull-regime bias**: dataset is Oct 2023 – Feb 2026, structurally bullish.
  In a bear/chop regime, the 63% sweep rate for `<50 pts` likely collapses.
  Re-run when regime shifts.
- **Small buckets**: `<50` W1 shorts n=14, `50–100` n=12, sweep days n=46.
  Treat any cell with n<30 as directional only.
- **Post-sweep classification** is rule-based (50-pt retrace within 30 min;
  20-pt continuation through end of window). Edge cases may misclassify.
- **Missing recent W1 shorts** (7 trades in Feb–Mar 2026) aren't tagged because
  the master `trading_days.csv` ends 2026-02-20. Re-run after that CSV refreshes.

## Follow-ups worth running (if signal materializes)

- **Gap-type split** within ATH-in-play — does `gap_down + ATH overhead`
  behave differently than `gap_up + ATH overhead`?
- **Overnight context** — did ON already probe ATH and fail? Fresh test vs
  retest should matter.
- **Parallel levels** — same framework for PDH, weekly high, monthly high. PDH
  at <50 pts may be a stronger magnet than ATH.
- **A dedicated ATH-sweep-reversal signal** — 28% reversal rate on a known
  setup day isn't a trade by itself, but combined with FVGC entries in the
  right direction it might be.

## Files

- `results/daily_ath_context.csv` — 560 rows, one per session.
- `results/base_rates.csv` — bucket summary.
- `results/post_sweep_outcomes.csv` — 46 sweep days classified.
- `results/w1_shorts_by_ath.csv` + `w1_shorts_stats.csv`.
- `results/fvgc_longs_by_ath.csv`, `fvgc_shorts_by_ath.csv`, plus stats CSVs.
