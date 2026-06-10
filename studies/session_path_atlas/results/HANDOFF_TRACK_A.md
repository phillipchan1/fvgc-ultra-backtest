# Track B → Track A handoff: atlas conditionals as candidate scorecard factors

Per program protocol: a conditional that moves a touch-probability by 15+ points
is a natural scorecard input, but promotion goes through Track A's IS/OOS
process — never directly into a playbook.

## Candidates (≥15pp movers, FDR-surviving, n≥100)

| # | Factor (as-of 9:30) | Moves | Size | Source cell |
|---|---|---|---|---|
| 1 | Gap bucket (ATR-normed) | P(PDH/PDL touched by 10:15) | flat 63.7% (n=449) ↔ large_up 27.7% (n=184) vs 48.9% marginal | part2 T6 × gap_cat |
| 2 | Open position × draw asymmetry | P(below-draw swept before above-draw) | below_range & above_heavy 73.8% (n=210) ↔ above_range & below_heavy 24.7% (n=368) vs 46.6% | part2 T9 × (4×5) |
| 3 | Draw asymmetry alone | same event | above_heavy 70.3% (n=445) ↔ below_heavy 27.5% (n=666) | part2 T9 × asym |
| 4 | W1 direction (as-of 9:45) | P(ahead-side draw touched in W2/W3) | ahead 21–33% vs behind 5–11% per level | part3 draw_touch_w23 |

Sub-15pp but clean and non-geometric: ON-range bucket → OR15 extension ≥0.25
ATR given break (compressed 12.2% n=631 / expanded 26.4% n=640 vs 19.1%).

## Warnings

1. **All of #1–#4 are distance proxies.** Part 1 shows touch probabilities match
   the shuffle null at every distance rung; these conditioners "work" by moving
   the distance map. A scorecard factor built on them must beat a
   distance-only baseline (|level − open|/ATR), or it adds nothing.
2. **Track A prior art:** generic draw-map/target-alignment vocabulary tested
   flat at the trade level on 2018–2024 IS (58 factors, zero FDR survivors).
   These session-level touch probabilities are NOT trade edges.
3. The structural Part-1 facts (one-sidedness: both-sides 13.6% vs 23.5% null;
   ret-mid 40.6% vs 52.4%; W1-holds 86.5% vs 76.5%) are properties of the
   tape, not signals — useful for exit/runner design assumptions (breaks tend
   to hold; mid-retrace is a minority event), not for entry filters.
4. Regime note for any IS/OOS split: morning two-sidedness shifted around
   2022; recent-3yr values differ from pooled by 3–13pp on the affected stats.
