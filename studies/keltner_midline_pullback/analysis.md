# Study: Keltner Channel Midline Pullback Continuation

## Question

Does a 5m Keltner band-break plus 30s pullback to the channel midline (EMA), entered on the first continuation 30s close, beat the FVGC-style baseline — and under which context combos does edge concentrate?

## Methodology

- **5m Keltner**: `EMA(n)` midline, `ATR(n)` from simple rolling mean of true range, bands = `EMA ± mult × ATR` for `n ∈ {10, 20, 30}`, `mult ∈ {1.0, 1.5, 2.0}`.
- **Break**: long when the 5m candle **closes** above upper band; short when it **closes** below lower band. Break must end within the project session window (`9:30–10:15` ET, matching [`TRADING_WINDOW_*`](../../fvgc/constants.py)).
- **Pullback**: after the break bar completes, on **30s** bars (`data/consolidated/nq-front-month.ohlcv-30s.csv`, same session slice), price must reach within **2 / 3 / 5 pts** of the midline EMA (bar overlaps `[ema–tol, ema+tol]`).
- **Invalidation** (before midline touch): 30s **close** through the opposite band (long: close below lower; short: close above upper) abandons the setup.
- **Entry**: first 30s bar **after** the touch whose close is in continuation direction (long: close > open; short: close < open).
- **R & stop** (per implementation choice): initial **1R** = distance from entry to the **opposite** Keltner band at entry. Opposite band and mid are taken from the last **completed** 5m bar (merge-asof backward on bar end times) so indicators are not lookahead. **Stop fill**: position exits when a 30s candle **closes** through the opposite band (same as Notion “30s close” rule). **Win / loss**: same as displacement studies — first **1R** excursion via intrabar high/low **before** that stop close counts as **win** (profit fixed at +1R); **loss** if stop close happens before +1R; **ambiguous** if same bar; **eod** if neither by session end.
- **Context** (from `data/trading_days/trading_days.csv`): macro window (W1 / W1+W2 / all), VIXY bucket (`low` / `medium` / `high` / `all`), gap alignment filter (`required` = trade only when gap sign matches direction vs `not_required`).
- **Statistics**: minimum `n ≥ 30` per combo row; **300** label-shuffle permutations per combo with **Benjamini–Hochberg** FDR at `q = 0.10` on WR and PF p-values.

## How to run

```bash
# from repo root
python studies/keltner_midline_pullback/run.py --perms 300
```

## Results

- **Run date**: 2026-05-08  
- **Session 30s bars**: 52,780 (`9:30–10:15` ET on consolidated history)  
- **Parameter instantiations**: 9 (EMA × ATR mult) × 3 pullback tolerances → up to **27** rows per raw break event when a trade completes  
- **Total simulated rows** (`results/trades.csv`): **20,777**  
- **Outcomes**: win 7,771 · loss 5,083 · eod 7,914 · ambiguous 9  

**Baseline (all Keltner variants combined, win / loss only)**  

- **Tradeable**: 12,854  
- **Win rate**: **60.46%**  
- **Profit factor (R-units)**: **1.147**  
- *(FVGC Notion baseline cited at ~51.7% WR / ~1.1 PF for comparison is indicator-only; this study uses a different entry model, so direct “beat baseline” is directional only.)*

**Grid**

- Qualifying combo rows (`n ≥ 30`): **491**  
- BH FDR survivors at `q = 0.10` (**WR**): **26** (see `results/summary_by_combo.csv`)  

**Top WR / PF slices** (small `n`; interpret cautiously):  

| ema | mult | tol | macro | vixy | gap | n | WR% | PF |
|-----|------|-----|-------|------|-----|---|-----|-----|
| 20 | 2.0 | 2 | all | medium | not_required | 32 | 93.75 | 10.92 |
| 20 | 2.0 | 3 | all | medium | not_required | 33 | 90.91 | 7.88 |
| 20 | 2.0 | 2 | w1 | all | required | 33 | 84.85 | 4.11 |

Several FDR-pass rows at the bottom of the sorted summary tie to **large `n`** but show **WR ~53%** and **PF &lt; 1** (e.g. tight Keltner + gap-required filters). Those rows survive multiple testing because label-shuffle p-values flag **departures** from the pooled null — not positive expectancy alone. Treat “survives FDR” as statistical structure, not automatic tradability.

## Outputs

- `results/trades.csv` — all simulated trades with Keltner params, pullback tolerance, MFE flags, and calendar context.  
- `results/summary_by_combo.csv` — full combo grid with permutation and BH-adjusted p-values.  
- `results/top_combos.csv` — top 25 rows after sorting by FDR-survival and WR/PF.

## Conclusions

- On this implementation, the **aggregated** Keltner midline-pullback + 1R target specification lands near **~60% WR** and **~1.15 PF** in R-units over tradeable outcomes — materially higher than the cited **~51.7%** FVGC indicator baseline, but **not comparable one-for-one** (different entry, risk definition, and session slice).
- **Strong headline slices** (e.g. `EMA=20`, `mult=2`, `VIXY=medium`) are **tiny‑`n`** and should be validated with more permutations, walk-forward splits, and out-of-sample data before playbook use.
- Bottom-ranked **FDR** survivors illustrate that **multiple-comparison correction does not imply profitability** — some significant rows underperform the global mean.

## Caveats

- Session window matches other studies (**9:30–10:15 ET**); overnight / globex Keltner breaks are excluded even if 5m data exist.  
- **Permutation count** (`300`) is moderate; raise `--perms` for more stable p-values.  
- **Gap / VIXY** fields depend on `trading_days` join quality for early history (missing rows → context NaNs).  
- **Ambiguous** outcomes (9 total) are edge cases where +1R and stop-close triggers could interact on the same bar; not excluded from the dataset.  
- Does **not** modify [`fvgc/model.py`](../../fvgc/model.py).
