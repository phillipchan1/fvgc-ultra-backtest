# Study: Keltner PF Optimization (Stop Variants + DOW Grid)

## Question

Can we raise **profit factor (PF)** while keeping the Keltner midline-pullback edge, by (1) using a **fixed 1R intrabar stop** instead of a **close-through-opposite-band** stop, (2) adding a **scale-out** (half at 1R, half to 2R with breakeven), and (3) extending the context permutation grid with **day-of-week** filters?

## Methodology

- **Entry**: identical to [studies/keltner_midline_pullback/run.py](../keltner_midline_pullback/run.py) (5m Keltner break, 30s pullback to EMA within tolerance, continuation entry on first bullish/bearish 30s close after touch). Helpers are loaded from that module via `importlib`.
- **Exit variant A — `close_band` (v2)**: same as the parent study — stop when a 30s bar **closes** through the opposite Keltner band; **1R target** on first favorable excursion to `tp_1r` (intrabar), with same win/loss/eod/ambiguous resolution order as the parent.
- **Exit variant B — `fixed_1r` (v1)**: **intrabar stop** at the opposite band **price** (`sl_price`) like [fvgc/engine.py](../../fvgc/engine.py) (SL hit on `low <= sl` for longs before TP check order as in engine); **1R TP** at `tp_1r`.
- **Exit variant C — `scaleout` (v3)**: before first touch of **1R**, full size uses the same intrabar SL as v1. After **half** exits at **1R**, the **runner** (remaining half) uses **breakeven** at `entry_price` and targets **2R** (`tp_2r`). Same-bar after scale: evaluate **2R** then **BE**. Outcome `partial_win` (+0.5R net typical) is mapped to **win** for WR/PF summaries (`outcome_so_wl`) so permutations align with win/loss-only cohorts.
- **Grid**: `ema_period × atr_mult × pullback_tol × macro_scope × vixy_filter × gap_filter × dow_filter` with `dow_filter ∈ {all, Monday, …, Friday, not_monday}`. `min_n = 30`, **300** label permutations per variant, **Benjamini–Hochberg** FDR at `q = 0.10` on WR and PF p-values (batched like the parent study).
- **Outputs**: wide `trades.csv` (all three exits per row); stacked `summary_by_combo_all_variants.csv`; per-variant top-25 CSVs; `comparison_side_by_side.csv` merges PF/WR for the same combo keys across variants (`pf_lift_f1_vs_cb`, `wr_delta_f1_vs_cb`).

## How to run

```bash
python studies/keltner_pf_optimization/run.py --perms 300
```

## Results (run: 2026-05-11, `--perms 300`)

**Session**: same 30s slice as parent (`9:30–10:15` ET), **20,777** trade rows (one row per entry × parameter bundle).

### Aggregate (all EMA × mult × tol), win/loss only

| Variant      | Tradeable | WR     | PF    | avg R |
|-------------|------------|--------|-------|-------|
| close_band  | 12,854     | 60.46% | 1.147 | +0.077 |
| fixed_1r    | 13,994     | 50.39% | 1.016 | +0.008 |
| scaleout    | 12,346     | 43.76% | 0.729 | −0.152 |

**Interpretation**

- **close_band** remains the strongest **aggregate** profile: the “slow” stop avoids many intrabar stop-outs that **fixed_1r** takes, so WR stays high. Losses are larger than −1R on average (band close), but not enough to flip the balance until intrabar SL is applied globally.
- **fixed_1r** improves the *mechanical* cap on loss size per event but **increases** stop-out frequency before 1R, collapsing WR toward 50% and **lowering PF** on the full pooled sample versus close_band.
- **scaleout** underperforms on aggregate: many trades still lose **−1R** before any scale; runners that scratch at BE contribute **+0.5R** at best while full losses remain **−1R**, which drags PF below 1.

### Grid artifacts

- `summary_by_combo_all_variants.csv`: **5,523** qualifying combo rows across three variants (with DOW dimension).
- `comparison_side_by_side.csv`: sort by `pf_f1` to find contexts where intrabar stop beats close-band on PF (subset-specific; not guaranteed globally).

## Conclusions

- The hypothesis that a **global** switch to **fixed 1R intrabar** stops would raise PF **without** changing entries is **not supported** on the pooled sample: PF and WR both **drop** vs close_band.
- **Scale-out** as implemented is **not** a free PF lift on aggregate; it needs redesign (e.g. different BE rule, wider 2R target, or coupling to contexts where MFE to 2R is frequent) or should be evaluated only on **pre-filtered** subsets.
- **Next steps** (outside this study): (1) optimize **only** under slices where close_band losses are oversized (e.g. wide-band cohort) rather than replacing the stop globally; (2) try **cap loss at −1R** while keeping close-band *signal* semantics (hybrid); (3) re-run with higher `--perms` for stable FDR on the enlarged grid.

## Caveats

- Permutation count **300** is moderate; BH survivors should be treated as exploratory.
- `scaleout` summary treats **`partial_win` as `win`** for WR/PF alignment — total R can be **&lt; 1** on those rows; inspect `pnl_r_so` in `trades.csv` for distribution.
- Does **not** modify [fvgc/model.py](../../fvgc/model.py).

## Outputs

- `results/trades.csv`
- `results/summary_by_combo_all_variants.csv`
- `results/top_combos_close_band.csv`
- `results/top_combos_fixed_1r.csv`
- `results/top_combos_scaleout.csv`
- `results/comparison_side_by_side.csv`
