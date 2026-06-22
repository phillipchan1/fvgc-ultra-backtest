# Account survival — TPT PRO $50K Monte Carlo (Track C, Part 2)

**Program context:** Track A negative → benchmark-only mode. These are survival
mechanics for the ONE validated play, under three WR regimes (per the Track A → C
cross-track decision), because the play's true forward WR is unknown:
**56% (IS era, n=41) / 70% (pooled 8-yr, n=83) / 83% (recent era, n=42).**
No scenario is "the" forecast. Every dollar figure inherits this regime uncertainty.

## Model (full parameter block in `run.py` MC_CONFIG)

- TPT PRO $50K: trailing drawdown **$2,000 on intraday UNREALIZED P&L** (high-water
  mark updates intra-trade); trail stops permanently at the starting balance; no
  daily loss limit (removed Jan 2025). **RE-VERIFY these terms before acting —
  prop-firm rules drift.** Checked 2026-06-09 vs TakeProfitTrader help center.
- Sizing: contracts = floor($700 / (stop pts × $2/pt)) on MNQ, min 1. Mean actual
  risk after rounding ≈ $676 (rounding loses ~
  3% of nominal risk; min-1 never binds
  at these stops). 0.5× rider = $350.
- **CONSERVATIVE path model** (intra-trade MAE is not exposed by the frozen engine
  for wins): every WIN first dips the full stop distance (tests the trailing floor),
  every LOSS first runs up by its empirical pre-stop MFE (drawn from the benchmark's
  own losses, n=25, intra-trade exact — median 0.35R) which ratchets the
  floor up before the stop is hit. An OPTIMISTIC bound (no dip, no ratchet) is shown
  for calibration; **truth is between the two; quote the conservative number.**
- Block bootstrap by calendar month (10,000 paths × 12 months), preserving the
  empirical clumping of ~1 signal/month. Stop sizes from the sampled months' actual
  trades; outcomes redrawn Bernoulli(scenario WR); R = ±1 (1:1 RR, no costs).
- Signal frequency by pool: pooled 0.82/mo; IS-era months
  0.56/mo; recent-era months 1.58/mo.
- "Safe buffer" = EOD balance ≥ $52,000 (floor locked at $50,000 + one full trail
  width of cushion; also TPT's standard-withdrawal threshold).

## Primary grid — CONSERVATIVE path model, pooled signal frequency (0.82/mo)

Full sizing ($700 risk/trade):

| scenario | WR | risk/trade | signals | P(termination) 3/6/12mo | P(floor locked, 12mo) | med months to lock | median balance 3/6/12mo | p10–p90 balance 12mo | P(safe buffer, 12mo) |
|---|---|---|---|---|---|---|---|---|---|
| 56pct IS regime | 56% | $700 | 0.82/mo | 13.3% / 34.2% / 60.2% | 35.7% | 6mo | $50,000 / $50,000 / $49,726 | $48,154–$53,340 | 33.7% (med 6mo) |
| 70pct pooled 8yr | 70% | $700 | 0.82/mo | 6.5% / 18.1% / 32.8% | 62.1% | 5mo | $50,660 / $51,280 / $52,030 | $48,593–$55,410 | 60.0% (med 6mo) |
| 83pct recent regime | 83% | $700 | 0.82/mo | 2.3% / 6.2% / 10.9% | 84.9% | 5mo | $50,700 / $52,020 / $54,080 | $50,000–$57,420 | 84.1% (med 5mo) |

Half sizing ($350 risk/trade):

| scenario | WR | risk/trade | signals | P(termination) 3/6/12mo | P(floor locked, 12mo) | med months to lock | median balance 3/6/12mo | p10–p90 balance 12mo | P(safe buffer, 12mo) |
|---|---|---|---|---|---|---|---|---|---|
| 56pct IS regime | 56% | $350 | 0.82/mo | 0.2% / 1.2% / 6.7% | 8.6% | 9mo | $50,000 / $50,250 / $50,340 | $49,020–$51,660 | 7.1% (med 10mo) |
| 70pct pooled 8yr | 70% | $350 | 0.82/mo | 0.1% / 0.3% / 1.1% | 28.4% | 9mo | $50,320 / $50,620 / $51,260 | $49,990–$52,610 | 26.2% (med 9mo) |
| 83pct recent regime | 83% | $350 | 0.82/mo | 0.0% / 0.0% / 0.1% | 53.6% | 9mo | $50,350 / $50,970 / $51,990 | $50,700–$53,550 | 51.8% (med 9mo) |

## Era-matched frequency riders (regimes also differed in signal frequency)

The 56% regime historically produced only 0.56 signals/month; the
83% regime 1.58/month. Pairing each WR with its own era's
frequency:

| scenario | WR | risk/trade | signals | P(termination) 3/6/12mo | P(floor locked, 12mo) | med months to lock | median balance 3/6/12mo | p10–p90 balance 12mo | P(safe buffer, 12mo) |
|---|---|---|---|---|---|---|---|---|---|
| 56pct IS regime | 56% | $700 | 0.56/mo | 7.1% / 21.9% / 47.3% | 29.8% | 7mo | $50,000 / $50,000 / $49,965 | $48,197–$52,720 | 28.7% (med 7mo) |
| 56pct IS regime | 56% | $350 | 0.56/mo | 0.0% / 0.4% / 2.9% | 3.3% | 10mo | $50,000 / $50,020 / $50,300 | $49,280–$51,320 | 2.6% (med 10mo) |
| 83pct recent regime | 83% | $700 | 1.58/mo | 6.1% / 11.0% / 12.2% | 90.1% | 3mo | $52,000 / $54,020 / $58,070 | $50,000–$62,210 | 89.2% (med 3mo) |
| 83pct recent regime | 83% | $350 | 1.58/mo | 0.0% / 0.0% / 0.1% | 94.6% | 6mo | $50,950 / $51,920 / $53,930 | $52,200–$55,860 | 93.9% (med 6mo) |

## Path-model sensitivity (OPTIMISTIC bound, $700, pooled)

| scenario | WR | risk/trade | signals | P(termination) 3/6/12mo | P(floor locked, 12mo) | med months to lock | median balance 3/6/12mo | p10–p90 balance 12mo | P(safe buffer, 12mo) |
|---|---|---|---|---|---|---|---|---|---|
| 56pct IS regime | 56% | $700 | 0.82/mo | 5.6% / 16.0% / 33.9% | 40.1% | 6mo | $50,000 / $50,080 / $50,620 | $48,000–$53,430 | 40.1% (med 6mo) |
| 70pct pooled 8yr | 70% | $700 | 0.82/mo | 1.7% / 5.1% / 10.8% | 68.8% | 6mo | $50,660 / $51,320 / $52,640 | $49,360–$55,420 | 68.8% (med 6mo) |
| 83pct recent regime | 83% | $700 | 0.82/mo | 0.4% / 0.9% / 1.8% | 89.4% | 5mo | $50,700 / $52,030 / $54,110 | $51,370–$57,430 | 89.4% (med 5mo) |

## Reading notes (do not skip)

- "med months to lock/buffer" are CONDITIONAL on the event happening within 12
  months (e.g. at 56%/$700 only 36% of paths ever lock; the median
  is over those paths).
- Under the CONSERVATIVE model every win first dips a full stop, so MORE signals =
  more floor tests early. That is why the 83% era-matched row (1.58 signals/mo)
  shows P(termination) ≈ the pooled row despite a better regime. The OPTIMISTIC
  rows bound that artifact from the other side; truth is between.
- **Half-sizing converts termination risk into stagnation risk.** At 56%/$350 the
  account almost never dies (7%
  in 12mo) but also almost never builds the buffer
  (7%). There is
  no sizing that makes a +0.12R-expectancy, ~0.6-signal/month play grow a $50K
  account safely — sizing reallocates the failure mode, it does not remove it.

## Synthesis — the honest constraint math

Phil's prior constraint math assumed **8 trades per 2 weeks (~16–17/month), under
which ~4 weeks to a safe buffer was the floor.** The validated play does not deliver
that tempo. It delivers **0.82 signals/month pooled** (IS era:
0.56; recent era: 1.58). Recomputed
honestly at $700 risk (expectancy per trade: 56% → +$84; 70% → +$280; 83% → +$462):

- **83% regime, its own frequency (1.58/mo):** ~
  4 trades to build the $2,000 buffer ⇒ expectation ~3 months;
  Monte Carlo median **3 months**,
  P(buffer within 12mo) 89%, P(termination within 12mo)
  12% (n=10,000 paths).
- **70% pooled regime:** ~7 trades ⇒ ~9 months in expectation at
  0.82/mo; Monte Carlo P(buffer within 12mo) only
  60%, median balance at 12mo $52,030,
  P(termination) 33%.
- **56% regime at its own frequency (0.56/mo): ~
  24 trades to buffer ⇒ ~4 YEARS in expectation.** Monte Carlo:
  P(buffer within 12mo) 29%, P(termination within 12mo)
  47%, median 12-month balance $49,965.
  **This is the sobering number of the program: in the historically-real IS regime,
  the account most likely neither locks its floor nor builds a buffer within a
  year — it sits exposed to the $2,000 trail on a ~coinflip play for years.**

Where Phil's old math said "4 weeks to buffer," the validated play at validated
frequency says **~3 months in the BEST regime
and effectively never (within a year) in the worst.** The regime question (which WR
is forward-true) dominates every sizing decision; nothing in this program resolves
it. Forward data per FORWARD_TEST_PROTOCOL.md §A is the only resolver.

*Fill caveat: stop fills modeled AT the stop price; real stop slippage on MNQ makes
all termination probabilities slightly worse than shown. Unrealized-trough modeling
is conservative; fills are optimistic. Both stated in analysis.md.*
