# FVGC Backtest

Fair Value Gap Continuation (**FVGC**) — a rule-based entry model for NQ futures, plus a small backtesting toolkit. This repo is the **pattern / indicator baseline**: signals and simulated SL–TP outcomes on OHLCV. Narrative context (news, regime, etc.) is intentionally out of scope for now.

---

## What you get

| Piece | Role |
|--------|------|
| **`fvgc/`** | Core package: load candles, detect FVGs and entries (**v2.0.5**), simulate trades. |
| **`tools/run_backtest.py`** | CLI for day-to-day runs (recent window or full-history baseline). |
| **`studies/baseline/`** | Same full-history baseline as `--baseline`, documented for sharing. |
| **`data/consolidated/`** | Canonical **30s** front-month OHLCV (continuous contract logic in `tools/consolidate_data.py`). |

**Baseline** means: run the model on the full consolidated 30s history, simulate first touch of stop vs target on subsequent 30s bars, and write summary stats plus CSVs under `logs/`. Use it to answer “how does this rule set behave on our sample?” before layering filters.

---

## Setup

```bash
git clone <repo-url>
cd fvgc-backtest
pip install -r requirements.txt
```

Large CSVs may use **Git LFS**. If data files look tiny or text says “pointer”, install [Git LFS](https://git-lfs.com) and run `git lfs pull`.

---

## Run the indicator baseline (full history)

From the **repository root** (paths assume `data/consolidated/nq-front-month.ohlcv-30s.csv` exists):

```bash
python tools/run_backtest.py --baseline
```

Or equivalently:

```bash
python studies/baseline/run.py
```

**What it does**

- Loads pre-aggregated **30s** candles (no 1s aggregation in this path).
- Generates signals and simulates SL/TP per `fvgc/engine.py`.
- Prints aggregate summary (wins, losses, win rate, total P&L, breakdown by **variant**).
- Writes **`logs/baseline_trades.csv`** and **`logs/baseline_fvgs.csv`** (folder is gitignored).

**Runtime**

- Expect **many minutes** on a multi-year file (~1.5M+ bars). Cost is the bar-by-bar Python signal loop, not loading the CSV. For a quick check, use `--last-days` on a smaller slice (see below).

More detail: [`studies/baseline/analysis.md`](studies/baseline/analysis.md).

---

## Other useful commands

```bash
# Last N calendar days — prints each trade line + summary (good for spot checks)
python tools/run_backtest.py --last-days 14

# Custom data path (e.g. raw 1s — will aggregate to 30s on the fly)
python tools/run_backtest.py --data path/to/file.csv --last-days 14

# Example study (performance by weekday)
python studies/day_of_week/run.py
```

Legacy entry points (same behavior):

```bash
python backtest.py --last-days 14
python consolidate_data.py   # builds consolidated CSVs from data/raw/
```

---

## Repository layout

```
fvgc/                   Core Python package (model, data, engine, constants)
tools/                  CLI — run_backtest.py, consolidate_data.py
studies/                Analyses — baseline/, day_of_week/, _template/
data/raw/               Raw 1s exports (often Git LFS)
data/consolidated/      Pre-built 15s / 30s front-month series
logs/                   Generated CSVs (gitignored)
```

---

## Model version

Current: **v2.0.5** — see [`fvgc/model.py`](fvgc/model.py) for the version history. The entry logic there is treated as validated; changes should follow your spec process (e.g. Notion) and parity checks.

---

## Roadmap / known gaps

- **Entry labeling and variants** (`no_fvg`, `ifvg`, `bos`, `protected_swing`, etc.) are useful for breakdowns but **may need refinement** as you iterate on definitions and documentation. The baseline numbers are still a solid starting point for comparison.
- Simulated execution is **not** live fills — use for relative performance and sanity checks.
- **Narrative / contextual filters** (calendar, news, regime) are future work on top of this baseline.
