# Prior-Day 50% Level Study — Analysis

**Status:** Completed 2026-04-23
**Sample:** 1572 tradeable FVGC trades (Oct 2023 – Mar 2026)
**Data:** 30s NQ front-month, RTH window 9:30–10:15 ET
**Baseline:** 51.7% WR, PF 1.09

## TL;DR — Do NOT promote to playbook

Across all four sub-studies and both candidate mid definitions (`pd_hl_mid` = prior-day H/L midpoint; `pd_va_mid` = prior-day VA midpoint), **zero primary Bonferroni-corrected tests reach significance** (α = 0.0125, 4 tests). No single result meets the playbook promotion gate.

**The failed-trade hypothesis ("shorts trading INTO the 50% level fail more") is NOT supported.** Shorts entering within 15pt above `pd_hl_mid` and trading down INTO it win 54.5% (n=33) — slightly BETTER than baseline, not worse. Null not rejected.

## What the data says

### Sub-study A — Directional asymmetry (primary 15pt threshold)

| Cell                                             | n   | WR    | PF   | med MFE(R) |
|--------------------------------------------------|-----|-------|------|-----------|
| Baseline                                         | 1572| 51.7  | 1.09 | 4.60      |
| pd_hl_mid / long / trading_into / near 15pt      | 28  | 50.0  | 1.36 | 2.71      |
| pd_hl_mid / long / trading_away / near 15pt      | 23  | 60.9  | 1.89 | 7.18      |
| pd_hl_mid / short / trading_into / near 15pt     | 33  | 54.5  | 1.16 | 4.24      |
| pd_hl_mid / short / trading_away / near 15pt     | 26  | 50.0  | 1.08 | 2.56      |
| pd_va_mid / long / trading_into / near 15pt      | 34  | 52.9  | 1.19 | 5.28      |
| **pd_va_mid / long / trading_away / near 15pt**  | **27**  | **70.4**  | **2.44** | **4.87**      |
| pd_va_mid / short / trading_into / near 15pt     | 20  | 50.0  | 0.87 | 3.74      |
| pd_va_mid / short / trading_away / near 15pt     | 30  | 46.7  | 1.00 | 3.05      |

Primary permutation p-values: all > 0.25. None significant.

**One exploratory finding worth a note** (not in primary tests, not Bonferroni-corrected):
`pd_va_mid / long / trading_away / near 15pt` = 70.4% WR / PF 2.44 / n=27. This is longs that are already ABOVE the VA midpoint, entering within 15pt of it — i.e., value-area midpoint acting as trampoline-style support. Interesting but small n and the symmetric short cell doesn't show an equivalent pattern, so treat as hypothesis-generating.

**Very-tight cells (exploratory, not registered):**
- `pd_hl_mid / short / trading_into / near 5pt`: 83.3% WR / PF 4.73 / **n=12** — too small to act on but worth logging.

### Sub-study B — Target magnet (reach rate)

The mid acts as a reliable magnet when already close, fading with distance:

| Mid        | Distance bucket | n   | Reach rate |
|------------|----------------|-----|-----------|
| pd_hl_mid  | 0.0–1.0R       | 101 | 92.1%     |
| pd_hl_mid  | 1.0–2.0R       | 71  | 73.2%     |
| pd_hl_mid  | 2.0–3.0R       | 76  | 65.8%     |
| pd_hl_mid  | 3.0R+          | 363 | 38.8%     |
| pd_va_mid  | 0.0–1.0R       | 82  | 92.7%     |
| pd_va_mid  | 1.0–2.0R       | 89  | 77.5%     |
| pd_va_mid  | 2.0–3.0R       | 85  | 56.5%     |
| pd_va_mid  | 3.0R+          | 382 | 38.7%     |

This tracks the baseline MFE distribution — not unique edge from the mid. But it's useful for TP planning: if the mid is within 1R of entry, treat it as a high-probability partial/TP1 target (>90% reach). Beyond 2R, it's no better than any other arbitrary point.

### Sub-study C — Rejection + first-FVGC-reversal

Primary combo (τ=3pt, lookback=20 bars = 10 min):
- `first_fvgc_pd_hl_mid`: 56.0% WR, PF 1.29, n=84, WR 95% CI [45.2, 66.7] — spans baseline
- `first_fvgc_pd_va_mid`: 48.9% WR, PF 1.04, n=88, WR 95% CI [38.6, 59.1] — spans baseline

Sensitivity — rejection-only flag across lookback windows:
- Shorter lookback (10 bars / 5 min) does best: `rej_pd_hl_mid_tau3_lb10` = 57.0% WR, n=86, PF 1.41. Interesting but not Bonferroni-significant.
- Longer lookback (40 bars) degrades to 49.8% WR — the signal dilutes with stale rejections.

Primary permutation p-values: 0.25–0.40. No significance.

### Sub-study D — POC confluence

Day-level coincidence with prior-day POC:

| Mid        | Within 5pt | Within 10pt | Within 15pt |
|------------|-----------|-------------|-------------|
| pd_hl_mid  | 7.6%      | 15.7%       | 22.7%       |
| pd_va_mid  | 14.4%     | **33.4%**   | 45.3%       |

**Phil's friend's observation is confirmed at the data level:** POC coincides with `pd_va_mid` roughly 2× more often than with `pd_hl_mid` at every threshold — 1/3 of days have POC within 10pt of the VA midpoint. But additive edge within the near-mid subset didn't materialize: sample sizes collapsed to 5–13 trades per cell, well below the 30-trade floor.

## Interpretation for Phil

1. **Today's failed short was not a systematic pattern.** The "price rejected off the 50% and reversed through me" narrative is intuitive but the 1572-trade sample shows no reliable directional asymmetry around either mid definition. Shorts entering near the mid from above (the exact setup that supposedly burned you) win at ~54% — slightly above baseline, not below.

2. **The 50% line is a decent TP1 target when close.** If pd_hl_mid or pd_va_mid sits within 1R of your entry in trade direction, ~92% of trades tag it. Use it for partials, not as the engine of the trade.

3. **POC and the VA-midpoint are close cousins.** 1/3 of days, they're within 10pt. If your friend trades POC confluence, you can validate his levels pre-market by computing (prior VAH + prior VAL) / 2. But the confluence doesn't boost FVGC win rates in this dataset.

4. **The rejection-then-first-FVGC setup is not dead, just not proven.** Primary combo n=84, WR 56%, short-lookback variant WR 57%. Directionally correct but underpowered. If you want to keep watching it, consider forward-testing with a trade journal rather than promoting to the playbook.

5. **Today's trade (2026-04-23) is not in the backtest.** Data ends 2026-03-25. No way to verify the specific setup against historical trades.

## False-positive defenses — all held

- Primary thresholds pre-registered (15pt, τ=3, lb=20).
- 4 primary tests, Bonferroni α=0.0125 — no test crosses.
- Robustness checks across 5/10/20pt and τ=1/3 show no directionally-consistent edge.
- VP-redundancy control (`near_mid & NOT near_VAH/VAL`) matches the uncontrolled cells — confirms the mid isn't hiding a distinct signal from VP proximity.
- Small-n cells (< 30) reported but not used for conclusions.

## Playbook decision

**Do NOT add any play to `playbook/playbook.json`.** Promotion rule requires: Bonferroni-corrected p < 0.0125 AND n ≥ 50 AND consistent across τ AND consistent across mid variants. Zero candidates qualify.

Candidate patterns to forward-test (not actionable yet):
- Short-lookback rejection off `pd_hl_mid` (τ=3, lb=10) — 57% WR / n=86 / PF 1.41.
- `pd_va_mid / long / trading_away / near 15pt` — 70% WR / n=27 / PF 2.44 — if this holds up in next 6 months of data, revisit.

## Artifacts

- `results/A_rejection_segmentation.csv` — Sub-study A
- `results/B_target_magnet.csv` — Sub-study B
- `results/C_rejection_fvgc.csv` — Sub-study C
- `results/C_spot_check.md` — 5 qualifying trades per mid for manual TV verification
- `results/D_poc_confluence.csv` — Sub-study D
- `results/permutation_results.csv` — all primary permutation p-values
- `results/trades_with_rejection_flags.csv` — per-trade rejection flags (reusable)
- `results/2026-04-23_check.txt` — empty (data ends 2026-03-25)

## Reusable for future studies

- `data/levels/trades_with_pd_mid.csv` — base table now carries `pd_hl_mid`, `pd_va_mid`, and directional interaction columns for any downstream study that wants mid-level features.
- `studies/pd_50pct_level/rejection_events.py` — the rejection-detection helper generalizes to any horizontal level. Next study needing "price wicked off X and reversed" logic can call `tag_trades_with_rejections` with a different mid-level source.
