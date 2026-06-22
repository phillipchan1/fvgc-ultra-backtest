# Part 3 — Pre-registered hypothesis family (Track C)

The ONLY new statistical tests in this track (m=3, BH q=0.10 within family).
Derived from Track B structural facts; tested at the trade level on ALL tradeable
FVGC v2.0.5 baseline signals (post quality filter), NOT just the benchmark cohort.
Registration rows were written to `test_ledger.csv` before any computation
(test_id suffix `__REGISTERED`). Procedure per hypothesis: IS first; ONE
confirmatory OOS look; exact binomial vs the cohort's own split base rate; no
sub-slicing, no variants, no interactions; all results reported regardless of
direction. Era boundary = Track A split (2024-02-13).

A hypothesis is VALIDATED only if it passes IS at q<0.10 within the family AND the
single OOS look (same direction, p<0.05). A VALIDATED label means
**FORWARD-TEST NEXT** — it does not enter any playbook from this run.

## T1_w1_alignment — entries >=9:45: trade direction matches W1 (9:30-9:45) direction

| split | condition | n | WR | PF | cohort base | exact binomial p | q (BH, m=3) |
|---|---|---|---|---|---|---|---|
| IS | TRUE | 1118 | 49.6% | 0.99 | 49.3% (n=1930) | 0.8342 | 0.834 |
| IS | FALSE (complement) | 812 | 48.9% | 0.99 | — | — | — |
| OOS (one look) | TRUE | 746 | 53.9% | 1.17 | 51.8% (n=1238) | 0.2562 | — |
| OOS | FALSE (complement) | 492 | 48.6% | 0.93 | — | — | — |
| benchmark sub-row (descriptive, NO TEST) | TRUE ∩ benchmark | 12 | 66.7% | — | — | — | — |

**Verdict: NOT VALIDATED** — no IS effect (q=0.834).

## T2_w1_stop_protection — entries >=9:45: model stop strictly beyond W1 extreme

| split | condition | n | WR | PF | cohort base | exact binomial p | q (BH, m=3) |
|---|---|---|---|---|---|---|---|
| IS | TRUE | 199 | 59.3% | 1.51 | 49.3% (n=1930) | 0.0056 | 0.017 |
| IS | FALSE (complement) | 1731 | 48.2% | 0.95 | — | — | — |
| OOS (one look) | TRUE | 118 | 49.2% | 1.07 | 51.8% (n=1238) | 0.5816 | — |
| OOS | FALSE (complement) | 1120 | 52.1% | 1.07 | — | — | — |
| benchmark sub-row (descriptive, NO TEST) | TRUE ∩ benchmark | 0 | — | — | — | — | — |

**Verdict: NOT VALIDATED** — passed IS (q=0.017) but FAILED the one-shot OOS look — effect reversed direction (49.2% vs base 51.8%).

## T3_on_expansion — all entries: session in expanded overnight-range tercile

| split | condition | n | WR | PF | cohort base | exact binomial p | q (BH, m=3) |
|---|---|---|---|---|---|---|---|
| IS | TRUE | 1130 | 47.3% | 0.90 | 47.6% (n=2806) | 0.8117 | 0.834 |
| IS | FALSE (complement) | 1676 | 47.9% | 0.93 | — | — | — |
| OOS (one look) | TRUE | 625 | 53.3% | 1.19 | 52.5% (n=1700) | 0.6890 | — |
| OOS | FALSE (complement) | 1075 | 52.0% | 1.07 | — | — | — |
| benchmark sub-row (descriptive, NO TEST) | TRUE ∩ benchmark | 34 | 70.6% | — | — | — | — |

**Verdict: NOT VALIDATED** — no IS effect (q=0.834).


## Descriptive-only: OR5-contradiction state at entry (LOW-N EXPLORATORY, no test)

Entries ≥9:45 with known W1 direction and OR5 state. "Contradiction" = W1 direction
up but OR5 low already broken before entry, or the mirror. Ledger-exempt; no
p-values; tabulated for the film room's eye-training context only.

| state | n | WR |
|---|---|---|
| consistent | 1961.0 | 50.1% |
| w1down_or5high_broken | 546.0 | 50.7% |
| w1up_or5low_broken | 661.0 | 50.5% |
