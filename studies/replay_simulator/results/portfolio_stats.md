# Portfolio statistics — benchmark play replay (Track C, Part 1)

**Program context (state every time):** Track A returned a NEGATIVE result — zero FDR
survivors among 58 narrative factors. This replay therefore runs in **reduced,
benchmark-only mode**: the opening-window FVG short (created 09:29:30–09:31:00 ET,
no protected_swing), executed mechanically per `REPLAY_RULES.md`. Everything below is
an **operational characteristic of already-validated trades — not new evidence of
edge.** All trades are 1:1 RR, ±1.0R exactly, no costs/slippage modeled.

**Reconciliation: PASS.** Replay = Track A re-derived benchmark exactly:
n=83, wins=58 (69.9% WR), PF 2.846, avg
+0.398R; IS 41 trades / 23 wins (56.1%);
recent 42 / 35 (83.3%). 6,480 other FVGC
signals logged OBSERVED-NOT-TRADED (context only).

---

## HEADLINE: trade frequency — the most important operational fact in this report

**The validated play fires 0.83 times per month
(n=83 over 100.4 months, 1,845 sessions).** That is
roughly ONE trade per month, not per week. Only 3.69% of
sessions produce a trade. The longest dry spell was
**189 consecutive sessions
(~56.4 calendar weeks) with zero trades** — and the two longest
droughts were back-to-back: 2018-03-27 → 2019-04-26
(395 days), then 2019-04-26 → 2020-04-29
(369 days). **From 2018-03-27 to
2020-04-29 — over two years — the play fired exactly once.** A trader
waiting for this setup in 2018–2020 would have spent two years mostly flat.

Frequency is itself regime-dependent:

| era | n | trades/month | % sessions with a trade | longest gap (sessions) | longest gap (weeks) |
|---|---|---|---|---|---|
| full 8-yr | 83 | 0.83 | 3.69% | 189 | 56.4 |
| IS era (2018-01→2024-02-12) | 41 | 0.56 | 2.63% | 189 | 56.4 |
| recent era (2024-02-13→2026-05-15) | 42 | 1.55 | 6.14% | 42 | 8.9 |

Trades per complete calendar month, full sample (100 months):
0 trades: 51 months, 1 trades: 29 months, 2 trades: 12 months, 3 trades: 5 months, 4 trades: 1 months, 5 trades: 2 months.

**What this means, plainly:** the validated play alone cannot support a 3–5
setups/week operating tempo. At ~1 trade/month the gap between what is validated and
how often Phil wants to be in the market is the single most important operational
fact here. Anything traded at higher frequency is, by definition, outside the
validated cohort.

---

## Per-era performance (the replayed trades themselves)

| era | n | WR | avg R | expectancy/trade | PF | total R | max DD (R) | DD length |
|---|---|---|---|---|---|---|---|---|
| full 8-yr | 83 | 69.9% | +0.398 | +0.398R | 2.85 | +33.0 | 4.0 | 14 trades / 414 days |
| IS era | 41 | 56.1% | +0.122 | +0.122R | 1.26 | +5.0 | 4.0 | 14 trades / 414 days |
| recent era | 42 | 83.3% | +0.667 | +0.667R | 6.51 | +28.0 | 1.0 | 2 trades / 1 days |

Equity curve (in R): `equity_curve_r.csv`. Era boundary = Track A split
(2024-02-13), so these numbers reconcile with the program ledger to the trade.

## Losing streaks — calendar reality at ~1 trade/month

Observed maximal losing streaks (full sample): {1: 9, 2: 3, 3: 2, 4: 1}.
Longest: 4 consecutive losses,
2021-01-27 → 2021-02-03
(**only 2 sessions / 7
calendar days** — losses CLUSTER, because qualifying sessions can fire two trades
30 seconds apart; tiebreak T-2 takes both).
IS era alone: {1: 4, 2: 2, 3: 2, 4: 1}, longest 4. Recent era:
{1: 5, 2: 1}, longest 2.

Two distinct risks, both real at this frequency:
1. **Clustered**: the observed worst streak was 4 losses inside
   7 days (two double-signal sessions) — at full Part 2
   sizing that is ~$1,400 of risk in a single session, twice in one week.
2. **Stretched**: under iid at each era's WR, P(a given trade starts a streak
   ≥2/3/4) is full 9.1%/2.7%/0.8%
   (n=83); IS 19.3%/8.5%/3.7%
   (n=41). With trades arriving ~monthly when NOT clustered, a 3-loss streak
   can just as easily be **a quarter of a calendar year spent losing** — and at ~7
   IS-regime trades/year there is no statistical way to tell that drawdown apart
   from a dead edge in real time.

## What living with this system feels like

**If the recent era (2024-02→2026-05) is the true regime
(83.3% WR, n=42):** about 1.6 trades a month, five of
six are winners, and the equity curve grinds up +0.67R per trade with
shallow drawdowns (max 1.0R in 27.0 months). The
psychological load is not losses — it is **waiting**: even here, the longest gap was
8.9 weeks with no signal, and most months offer one or two
shots. The danger in this regime is boredom-driven off-playbook trades, not the
play itself.

**If the IS era (2018→2024-02) is the true regime (56.1% WR, n=41):** the
play is barely better than a coinflip with positive expectancy of only
+0.12R per trade, arriving 0.56 times a month.
That is roughly **+0.07R per calendar month** —
months of effort for near-zero progress, a max drawdown that took
414 days to recover,
plus year-long signal droughts (2018–2020 fired once in two years).
A trader cannot distinguish this regime from a broken edge in real time on ~7
trades a year — which is precisely why the Part 2 survival numbers are run at 56%
as a mandatory scenario, not a footnote.

Which regime is true is **unknown**. The 8-yr pooled 69.9% is arithmetically real
but is a blend of those two states; nothing in Track A or B predicts which one
forward trades will come from.
