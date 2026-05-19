# studies/multi_cell_8yr_v2/

Re-runs the multi-cell confluence matrix study on the 2018–2026 dataset
extension, with stricter year-floor and regime-spread gates.

## Files

- `utils.py` — paths, dates, gate thresholds
- `build_analysis_frame.py` — builds `trades_analysis_8yr.csv` from `mfe_trades_enriched.csv`
- `phase_a_validate_frozen.py` — applies the prior frozen stacks to 8yr; reports drift
- `phase_b_remine.py` — re-mines factor stacks on 8yr IS, validates OOS, scores against 5 gates
- `REPORT.md` — verdicts + per-cell Notion-page diffs

## Prereq

`studies/mfe_multi_r/results/mfe_trades_enriched.csv` must be regenerated on the
8yr baseline (`studies/baseline/results/trades.csv`). Stage and run:

```
cp studies/baseline/results/trades.csv logs/baseline_trades.csv
python3 studies/mfe_multi_r/run.py
```

## Run

```
python3 studies/multi_cell_8yr_v2/build_analysis_frame.py
python3 studies/multi_cell_8yr_v2/phase_a_validate_frozen.py
python3 studies/multi_cell_8yr_v2/phase_b_remine.py
```

Output in `results/`. Top-level verdict in `REPORT.md`.
