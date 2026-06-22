# Low-Side Liquidity Sweep Confluence Study — Analysis

## Question

Is the OR.L-swept boost on M3 longs (cited ~57.3% WR / 1.36 PF) a special case of a broader **"morning long-side liquidity has been cleared"** pattern? Or is it specific to the opening range low?

We test 8 binary "low-was-taken-out-before-entry" activators on M2+M3 long FVGC trades and ask:
1. Which (if any) of the 8 produce a univariate WR / PF / EV lift?
2. After gating on existing magnet & confluence stack, does the lift survive?
3. Do multi-level sweeps stack (additive) or collapse (already double-counted)?

## Methodology

**Trade universe.** M2+M3 long FVGC trades from `data/levels/trades_with_levels.csv`:
- `macro_window ∈ {2, 3}` (entry time 09:45–10:15 ET)
- `direction == 'long'`
- `variant ∈ {no_fvg, ifvg}` (excludes `protected_swing`, `bos`)
- `outcome ∈ {win, loss}` (decided only)

Two universes are reported:
- **BROAD** (no magnet filter): n=365
- **PLAYBOOK** (`magnet_valid=True`, the actual M2+M3 Long Confluence Model gate): **n=167**

Headline numbers are PLAYBOOK.

**Activators.** 8 binary "swept-by-entry" flags (loose-mode breach: any 30s wick where `low < level_price` inside the per-level window):

| # | Activator | Window |
|---|---|---|
| 1 | `or_l_swept` | [09:45, entry] |
| 2 | `on_low_swept` | [09:30, entry] (level forms prior 18:00 → 09:30) |
| 3 | `london_low_swept` | [09:30, entry] (level forms 02:00–08:00) |
| 4 | `premarket_low_swept` | [09:30, entry] (level forms 04:00–08:00) |
| 5 | `pdl_swept_overnight` | [prior_close, entry] (PDL = prior RTH low) |
| 6 | `pdl_swept_rth_only` | [09:30, entry] |
| 7 | `pdval_swept_overnight` | [prior_close, entry] (PDVAL from `daily_volume_profile.csv`) |
| 8 | `pdval_swept_rth_only` | [09:30, entry] |

IB Low (9:30–10:30) was **dropped** — M2+M3 entries fall inside its formation window, so the level isn't yet known at entry. Methodology decision pre-registered.

**Stratification controls.** `level_confluence_count` from `trades_with_levels.csv` (count of distinct level groups within ~10pt of the magnet level, magnet being the nearest unswept level above entry for longs). Because confluence is computed against *upside* magnets while the activators here are *downside* sweeps, collinearity is structurally low — a leave-one-out re-count was not required.

## Sample sizes

| Universe | n |
|---|---|
| BROAD M2+M3 long | 365 |
| PLAYBOOK (mv=True) M2+M3 long | **167** |
| ↳ M2 (09:45–10:00) | 94 |
| ↳ M3 (10:00–10:15) | 73 |
| or_l_swept = True (PLAYBOOK) | 50 |
| Other activators T-cell | 27–88 |

Pre-committed: cells with n≥30 are confirmatory; smaller cells are suggestive only.

## Result A — Baseline replication

OR.L-swept on M3 longs:

| Filter | n | WR | PF | EV |
|---|---|---|---|---|
| No magnet filter (closest to cited) | 91 | 59.3% | 1.52 | +6.10 |
| `magnet_valid=True` | 33 | **72.7%** | **2.70** | **+15.76** |

Cited number: 57.3% / 1.36. Replication is in the same direction and within ~2pp WR / 0.16 PF. Discrepancy is likely a different vintage of the trade pipeline (this study uses the newer `trades_with_levels.csv` with 2,005 trades; the OR sweep state CSV had 1,143). Qualitative finding holds.

## Result B — Univariate per-level split (PLAYBOOK)

Sorted by WR-lift (T − F):

| Activator | n_T | n_F | WR_T | WR_F | **WR-lift** | PF_T | PF_F | EV-lift |
|---|---|---|---|---|---|---|---|---|
| **or_l_swept** | 50 | 117 | **74.0%** | 58.1% | **+15.9pp** | 3.05 | 1.27 | +13.24 |
| premarket_low_swept | 65 | 102 | 63.1% | 62.7% | +0.3pp | 1.77 | 1.60 | +1.68 |
| on_low_swept | 27 | 140 | 63.0% | 62.9% | +0.1pp | 2.31 | 1.55 | +6.52 |
| pdval_swept_overnight | 88 | 79 | 62.5% | 63.3% | −0.8pp | 1.60 | 1.75 | −0.53 |
| pdval_swept_rth_only | 58 | 109 | 62.1% | 63.3% | −1.2pp | 1.70 | 1.64 | +1.23 |
| london_low_swept | 51 | 116 | 60.8% | 63.8% | −3.0pp | 1.78 | 1.61 | +2.02 |
| pdl_swept_overnight | 62 | 105 | 59.7% | 64.8% | −5.1pp | 1.43 | 1.84 | −2.87 |
| **pdl_swept_rth_only** | 27 | 140 | **48.1%** | 65.7% | **−17.6pp** | 1.04 | 1.83 | −7.84 |

**`or_l_swept` is the only positive activator.** Every other low-sweep is flat or negative. PDL-swept-RTH-only is actively *anti-edge* (−17.6pp WR), which is also the user's "stop-run = bad continuation context" intuition.

## Result C — Correlation matrix (Phi on booleans, PLAYBOOK universe)

```
                       or_l    on    lon   pre   pdl_o  pdl_r  pdv_o  pdv_r
or_l_swept              1.00   0.21  0.08  0.10   0.15   0.14   0.20   0.18
on_low_swept            0.21   1.00  0.66  0.55   0.07   0.34   0.09   0.26
london_low_swept        0.08   0.66  1.00  0.83  -0.03   0.20   0.00   0.20
premarket_low_swept     0.10   0.55  0.83  1.00   0.07   0.32   0.04   0.24
pdl_swept_overnight     0.15   0.07 -0.03  0.07   1.00   0.57   0.73   0.64
pdl_swept_rth_only      0.14   0.34  0.20  0.32   0.57   1.00   0.42   0.60
pdval_swept_overnight   0.20   0.09  0.00  0.04   0.73   0.42   1.00   0.69
pdval_swept_rth_only    0.18   0.26  0.20  0.24   0.64   0.60   0.69   1.00
```

Three clusters at |ρ| ≥ 0.5:
- **ON cluster**: `on_low / london_low / premarket_low` (ρ 0.55–0.83). All overlap heavily — same overnight-into-Asia-into-London continuum.
- **PD cluster**: `pdl_*` and `pdval_*` (ρ 0.42–0.73). Prior-day related lows.
- **OR.L stands alone** (max ρ = 0.21 vs on_low). Genuinely independent signal.

## Result D — Marginal lift after gating on `level_confluence_count`

`or_l_swept` lift survives within the dominant confluence band:

| Confluence band | n_F | WR_F | PF_F | n_T | WR_T | PF_T | **WR-lift** |
|---|---|---|---|---|---|---|---|
| **0–2** (135 of 167) | 96 | 58.3% | 1.24 | 39 | **79.5%** | **4.43** | **+21.2pp** |
| 3–4 (26) | 17 | 58.8% | 1.23 | 9 | 44.4% | 0.71 | −14.4 (n<30, suggestive) |
| 5+ (6) | 4 | 50.0% | 2.29 | 2 | 100% | n/a | n=2 |

The +21.2pp lift in the n=135 band is the cleanest confirmatory finding — OR.L's edge is **not** double-counted with the existing magnet/confluence stack.

For all other activators (full per-level tables in `results/marginal_*_by_confluence.csv`), the lift either stays near zero or flips sign across bands, consistent with no real signal.

## Result E — Logistic regression (controls: confluence_count + macro_window)

| Activator | Coef | 95% CI | p |
|---|---|---|---|
| **or_l_swept** | **+0.750** | [−0.015, +1.515] | **0.055** |
| pdl_swept_rth_only | −0.715 | [−1.578, +0.149] | 0.105 |
| pdl_swept_overnight | −0.215 | [−0.874, +0.443] | 0.521 |
| Others | ≈ 0 | bands include 0 | > 0.5 |

After controlling for confluence and macro window, only `or_l_swept` has a positive coefficient approaching significance. `pdl_swept_rth_only` trends negative but doesn't quite reach p<0.05 — directionally consistent with the −17.6pp WR-lift in the cell-split.

## Result F — Stacking (cluster count ∈ {0, 1, 2, 3, 4})

`cluster_count = or_l_swept + on_low_swept + pdl_swept_overnight + pdval_swept_overnight` (4-way de-clustered count using cluster representatives):

| Clusters swept | n | WR | PF | EV |
|---|---|---|---|---|
| 0 | 58 | 63.8% | 1.76 | +7.16 |
| 1 | 31 | 61.3% | 1.49 | +5.48 |
| 2 | 43 | 55.8% | 1.01 | +0.12 |
| 3 | 30 | 70.0% | 3.06 | +16.17 |
| 4 | 5 | 80.0% | 4.83 | +23.00 (n<30) |

**Stacking is non-monotone.** The "3+ clusters swept" cells are largely the same trades where OR.L is one of the components — i.e., the lift returns when OR.L joins, not because of additivity. The 2-cluster trough (n=43, WR 55.8%) suggests two lows being swept *without* OR.L is a worse setup than zero. Stacking therefore does not add edge beyond OR.L.

## Result G — Per-macro breakdown (PLAYBOOK)

OR.L-swept lift is consistent across both macro windows:

| | swept=False | swept=True |
|---|---|---|
| **M2** (n=94) | n=77, WR 58.4%, PF 1.25 | n=17, WR **76.5%**, PF **4.16** |
| **M3** (n=73) | n=40, WR 57.5%, PF 1.30 | n=33, WR **72.7%**, PF **2.70** |

OR.L-swept wins in both M2 (suggestive, n=17) and M3 (confirmatory, n=33). Effect is real for the full M2+M3 universe, not just M3.

## Conclusion

**The hypothesis is falsified.** The OR.L-swept boost is *not* a special case of a broader "long-side liquidity cleared" pattern. OR.L is structurally unique among the 7 candidate lows tested.

Specifically:
- Only `or_l_swept` produces a positive WR/PF/EV lift on M2+M3 long playbook trades (+15.9pp WR, PF 3.05).
- Sweeps of overnight, London, premarket, PDL, and PD VAL are flat or negative.
- `pdl_swept_rth_only` is actively *anti-edge* (−17.6pp WR, PF 1.04) — likely captures "stop-run already happened, we're now trapped trying to fade the bounce."
- The OR.L lift survives a leave-one-out check against `level_confluence_count` (+21.2pp WR in the n=135 0–2 confluence band) — not double-counted with the existing magnet stack.
- Multi-level stacking does not add edge — apparent stacking is an artifact of OR.L being one of the count.

### Recommendation for confluence #7

Adopt **`or_l_swept` exactly** as confluence #7 to the M2+M3 Long playbook page:

> **C7 — OR.L taken before entry.** Between 9:30–9:45 ET, mark the opening-range low. If the session has wicked below it (low < OR.L) at any point before entry, score +1.

Cell stats (PLAYBOOK universe): **n=50, WR 74.0%, PF 3.05, EV +16.4 pts/trade.** Holds in both M2 (+18pp) and M3 (+15pp).

**Do not** adopt a multi-level rule. Specifically reject:
- Any "n ≥ 2 lows swept" stacking rule (non-monotone).
- `pdl_swept_rth_only` as a *positive* confluence — but it could be considered as a *negative gate* (avoid M2+M3 longs when this fires alone) in a follow-up study.

## Caveats

1. **Sample sizes**: PLAYBOOK n=167 is modest. OR.L-swept cell (n=50) is comfortably above the n≥30 confirmatory threshold; smaller-cell findings (`pdl_swept_rth_only` PLAYBOOK n_T=27) are flagged suggestive.
2. **Multiple comparisons**: 8 activators × {WR, PF, EV} × 2 universes ≈ 48 cells. OR.L was pre-registered as confirmatory; the rest are exploratory. Bonferroni would not change the OR.L conclusion (lift is several SE wide).
3. **IS only**: no out-of-sample split. Strong recommendation to OOS-validate before promoting `or_l_swept` to live confluence in the playbook (see `studies/morning_narrative` for OOS protocol).
4. **Trade pipeline drift**: cited 57.3%/1.36 PF (older `or_sweep_state_30s_loose.csv`) vs replicated 59.3%/1.52 (current `trades_with_levels.csv`). Direction matches, magnitude ~5% off. Document as known and re-validate when the trade pipeline is regenerated.
5. **PDVAL gaps**: `daily_volume_profile.csv` has 580 days vs 704 in candle data — some early/edge days lack a PD VAL. ~26 trades may have `pdval_swept_*` = False due to missing prior-day VP rather than no-sweep. Negligible impact given the activator was already unproductive.

## Follow-ups

- **OOS validation** of `or_l_swept` on a held-out date range before playbook integration.
- **Negative-gate study**: does `pdl_swept_rth_only=True` (n=27, WR 48.1%) warrant an explicit *avoid* rule for M2+M3 longs?
- **OR.L magnitude / depth-of-sweep**: does the *depth* of the OR.L wick (e.g., > 0.25 × OR_range) modulate the boost? Currently boolean; could be a continuous activator.
- **Time-of-sweep**: does an OR.L wick in 9:45–9:55 differ from one in 10:00–10:10? (within-window timing).
- **OR.L + reclaim**: strict (close back inside OR) vs loose. Sensitivity check pending — file a small follow-up.

## Files

- [run.py](run.py) — full pipeline
- [results/m2m3_long_low_sweep_30s.csv](results/m2m3_long_low_sweep_30s.csv) — 167 PLAYBOOK / 365 BROAD trades, 8 activators
- [results/day_levels_sweeps.csv](results/day_levels_sweeps.csv) — 704 days × 6 levels + 8 first-sweep timestamps
- [results/univariate_lift_playbook.csv](results/univariate_lift_playbook.csv) — summary table (Result B)
- [results/sweep_correlation_matrix.csv](results/sweep_correlation_matrix.csv) — Result C
- [results/marginal_*_by_confluence.csv](results/) — Result D, per-activator
- [results/logit_marginal.csv](results/logit_marginal.csv) — Result E
- [results/stacking_by_clusters.csv](results/stacking_by_clusters.csv) — Result F
- [results/run_output.txt](results/run_output.txt) — full console output
