# Thursday × Inside Value Area — Retest

**Date:** 2026-05-22
**Status:** **INVALIDATED** — does not survive 5.5yr holdout
**Notion entry:** [Thursday Inside Value Area](https://www.notion.so/342e2f0e77608166bc8ed85bf46b2dca)
**Original study:** `studies/volume_profile_confluence/` (2026-04-14)

## Headline

The original claim of 73.7% WR / 2.89 PF on n=76 Thursday-inside-VA FVGC trades **does not survive** when extended to the full 8-year data we now have. The 2018-2023 holdout — never seen by the original study — shows the cell sitting at baseline (50.0% WR, PF 0.97, n=170).

The original 2023-10 → 2026-03 window reproduces approximately (n=93 here vs 76 in Notion; 69.9% WR / PF 2.47 vs 73.7% / 2.89). So the in-sample signal is real. It just doesn't generalize.

## Three-Window Test

| Window | Period | Cell n | Cell WR | Cell PF | Cell EV/trade | Perm p (within-Thursday) |
|---|---|---|---|---|---|---|
| **Holdout** | 2018-01 → 2023-09 | 170 | 50.0% | 0.97 | +0.000R | 0.119 |
| **In-sample** | 2023-10 → 2026-03 | 93 | 69.9% | 2.47 | +0.398R | **0.0022** |
| **Forward** | 2026-03-26 → 2026-05-15 | 8 | 37.5% | 0.60 | −0.250R | 0.939 |
| **Full** | 2018-01 → 2026-05 | 271 | 56.5% | 1.34 | +0.129R | 0.011 |

The in-sample window is the only one where the cell beats baseline. Holdout is at base rate. Forward is below.

## Why the Original Looked Strong

1. **Multi-comparison search space.** The original `volume_profile_confluence/run.py` tested ~5 VP-location masks × ~13 context factors (5 DOW + variants + 930 + overnight + VIXY + news) — minimum ~65 combos. With Bonferroni on just the DOW dimension (5), the in-sample p=0.0022 → ~0.011, marginal. Add VP-location states and it's not significant.
2. **Small sample.** n=76 (Notion) / 93 (this retest) is fragile. The full 271-trade combined cell drops WR from 69.9% to 56.5%.
3. **Regime alignment.** The FVGC model itself is regime-sensitive: 2018-2023 baseline WR was 47.8% (PF 0.92), 2023-2026 was 52.3% (PF 1.12). The "edge" co-occurred with the model becoming profitable overall.

## Per-DOW × Inside-VA, Holdout

Sanity check that nothing else hides in here:

| DOW | n | WR | PF |
|---|---|---|---|
| Mon | 130 | 51.5% | 1.11 |
| Tue | 148 | 40.5% | 0.73 |
| Wed | 183 | 47.5% | 0.95 |
| Thu | 170 | 50.0% | 0.97 |
| Fri | 202 | 47.5% | 1.03 |

Nothing meaningful. Thursday is not even the best DOW in this window.

## Causal Audit

The Notion play uses prior-day VP — this IS causally observable (set in stone before 9:30). The retest uses `tools/causal_features.load_lagged_vp` which shifts VP forward by one trading day. No lookahead in the feature itself; this kill is a multi-comparison / small-sample story, not a causal bug.

## Hardening Pass — Targeted Filters (2026-05-22, second run)

After the kill verdict, we asked a sharper question: even if the headline
fails, are there pre-registered sub-filters on the parent Thu+InsideVA cell
that survive permutation against the parent itself? Five filters were
committed before running:

| Hypothesis | n | WR | PF | p vs parent | IS WR | OOS n |
|---|---|---|---|---|---|---|
| Parent: Thu+InsideVA | 271 | 56.5% | 1.30 | — | 57.0% | 6 |
| H1 va_width ≤ 500 | 268 | 56.3% | 1.29 | 1.00 | 56.9% | 6 |
| **H2 MW2 (9:45-10:00)** | **87** | **65.5%** | **1.90** | **0.047** | **66.3%** | **1** |
| H3 bearish 9:30 | 121 | 57.0% | 1.33 | 0.90 | 58.3% | 6 |
| H4 no_news + vixy normal | 139 | 59.0% | 1.44 | 0.40 | 59.0% | 0 |
| H5 va_width 100..500 | 199 | 59.3% | 1.46 | 0.13 | 60.1% | 6 |

**Only H2 (MW2 9:45-10:00) clears p < 0.05.** Notion's other "best"
sub-cells revert at scale: bearish 9:30 (originally claimed 80% WR) is now
57%. Those were small-n noise.

H2 caveats: with 5 pre-registered tests, Bonferroni-corrected p ≈ 0.23 —
not significant under family-wise correction. And the OOS partition has
only 1 trade. So H2 is a candidate worth tracking forward, **not** a
confirmed filter. Frequency drops to ~11 trades/yr if MW2-only restriction
is applied.

## Verdict

**Remove from playbook** or tier-down to "watchlist / unverified". The play
does not have an out-of-sample edge over 5.5 years of additional data. The
forward 8-trade sample, while small, points the same direction.

If keeping any version of this play on a watchlist, restrict to **MW2 only
(9:45-10:00)** — the single sub-filter that beat permutation on the parent
cell. But treat as unconfirmed until ≥30 pure-OOS trades accrue.

## Reproduce

```bash
python3 studies/thursday_inside_va/run.py
```

Outputs:
- `results/summary.csv` — per-window stats
- `results/run.log` — full run output
