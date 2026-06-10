# Forward-test protocol & pre-registered hypotheses — Track A close-out (2026-06-09)

**No framework was promoted.** Phase 3 produced zero FDR survivors, so there is no
scorecard to log live. This document instead pre-registers (a) the follow-up study
Phil requested at the gate, and (b) the near-miss hypotheses — with goalposts set NOW
so future evaluation cannot move them.

---

## A. Pre-registered follow-up study: benchmark time-concentration (HEADLINE finding)

The opening-window short (no-PS) is 69.9% WR / PF 2.85 pooled (n=83, 8yr) but
**56.1% (n=41) in IS (2018→2024-02) vs ~83% implied (35/42) in the 2024-02→2026-05
window**. The edge appears regime-concentrated.

**Study spec (research queue):** year-by-year and rolling-24-month WR/PF of the
benchmark cohort on the canonical 8-yr baseline:
- When did the edge emerge? Is the improvement monotonic in time?
- Recent-24-month estimate with an exact binomial CI (pre-register: Clopper–Pearson 90%).
- Pre-registered interpretation rule: if the rolling-24m CI lower bound stays ≥55%
  for every window ending after 2024-06, treat the play as currently-live with
  regime risk; if any window's point estimate drops below 50%, treat the edge as
  regime-bound and size accordingly.
This study uses already-seen data (no OOS seal issue) but must be a NEW ledger family.

## B. Pre-registered single question for forward data: the long side

The top three Phase-3 near-misses are ALL longs-side cells:

| hypothesis | IS cell | n | WR | PF | raw p |
|---|---|---|---|---|---|
| `or_break_against` longs (OR broke down, FVGC long = fade) | longs | 253 | 56.9% | 1.44 | .0046 |
| `macro_w3` longs (10:00–10:15 entries) | longs | 477 | 54.1% | 1.27 | .0078 |
| `fvg_stale` longs (FVG age >15 min) | longs | 93 | 59.1% | 1.46 | .037 |

(also `fvg_large` longs 59.3%/n=59, `near_miss_c1` longs 56.2%/n=96 — same side.)

**Pre-registered question (ONE test, not five):** *is there an unexploited long-side
opening play?* Operationalized as: FVGC longs where (OR broke low OR entry in W3) —
the union cell, frozen here before any forward data is seen.
- Goalposts (set now): evaluate after ≥60 forward signals. Success = WR ≥58% with
  exact-binomial p<0.05 vs 50% AND PF ≥1.3. Anything less = hypothesis dead, no re-tuning.
- These remain UNPROMOTED. Do not trade them on backtest evidence alone.

## C. Benchmark-grading hints (descriptive only, n too small)

Within the IS benchmark cohort: `target_aligned` 63.3% (n=30) vs 56.1% base;
`htf15_toward_1atr` 61.1% (n=36). If Phil logs anything live per-signal, log these two
booleans on benchmark signals; revisit only after ≥60 logged signals.

## D. What NOT to do

- Do not assemble the near-misses into a scorecard and trade it — that is the
  threshold-relaxation this program was designed to prevent.
- Do not evaluate anything new against the 2024-02→2026-05 window casually: it is
  this program's sealed OOS and its reuse burns it for any future Track A revival.
