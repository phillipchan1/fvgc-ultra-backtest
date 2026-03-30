# Study: Indicator baseline (pattern-only)

Setup and sharing notes for collaborators: see the [repository README](../../README.md).

## Question

How does the FVGC entry model behave over the full available consolidated NQ history, before adding narrative or regime filters?

## Methodology

- **Data:** [`data/consolidated/nq-front-month.ohlcv-30s.csv`](../../data/consolidated/nq-front-month.ohlcv-30s.csv) — front-month continuous series, 30s OHLCV (see [`tools/consolidate_data.py`](../../tools/consolidate_data.py)). This is the canonical artifact for “official” baseline numbers; it is **not** the same as loading a single raw 1s file without the full consolidation pipeline.
- **Model:** [`fvgc/model.py`](../../fvgc/model.py) — signal generation only (no external context).
- **Execution:** [`fvgc/engine.py`](../../fvgc/engine.py) `simulate_trades` — first touch of SL or TP on subsequent **30s** bars within the entry session; simplified EOD handling when the session rolls to the next calendar day.

## How to run

From the repo root:

```bash
python studies/baseline/run.py
```

Equivalent CLI (summary only, no per-trade listing):

```bash
python tools/run_backtest.py --baseline
```

Outputs under `logs/` (gitignored): `baseline_trades.csv`, `baseline_fvgs.csv`.

## Results

Re-run the study and paste summary stats here, or refer to the console output from `print_summary` (wins, losses, EOD, ambiguous, total P&L, by-variant breakdown).

## Caveats

- Simulated fills are for **sanity checks and relative comparisons**, not live execution.
- Long samples mix multiple regimes; aggregate stats are a baseline; year/month/variant splits can be added in follow-up studies.
