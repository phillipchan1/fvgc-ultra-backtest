"""Phase 1 — Session data-quality rule, chronological IS/OOS split, walk-forward folds.

Phil's amendment (2026-06-09): no year-based exclusion. Instead exclude any session
missing >10% of expected overnight/pre-market 30s bars (18:00 prior ET -> 09:30 ET,
expected 1860 bars), and report removals per year.

Split: IS = first 70% of quality-passing sessions (by date), OOS = final 30%.
Within IS: 4 chronological walk-forward folds.

Outputs:
  results/cache/session_quality.csv   (per-session coverage + pass flag)
  results/phase1_split.json           (boundary date, folds, config, removal report)

Run with python3.13 (pyarrow required).
"""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
CACHE = RESULTS / "cache"

EXPECTED_ON_BARS = 1860  # 18:00 -> 09:30 ET = 15.5h * 120 bars/h
MIN_COVERAGE = 0.90

# --- per-session overnight coverage from 30s bars --------------------------
bars = pd.read_parquet("data/consolidated/nq-front-month.ohlcv-30s.parquet",
                       columns=["timestamp_ny"])
ts = pd.to_datetime(bars["timestamp_ny"])
if ts.dt.tz is None:
    ts = ts.dt.tz_localize("America/New_York", ambiguous="infer",
                           nonexistent="shift_forward")

# Session date: bars at/after 18:00 belong to the NEXT calendar day's session.
tod_minutes = ts.dt.hour * 60 + ts.dt.minute
session_date = ts.dt.normalize().where(tod_minutes < 18 * 60,
                                       ts.dt.normalize() + pd.Timedelta(days=1))
# Overnight/pre-market = [18:00 prior, 09:30): i.e. tod >= 18:00 or tod < 09:30
is_on = (tod_minutes >= 18 * 60) | (tod_minutes < 9 * 60 + 30)

on_counts = (pd.DataFrame({"session": session_date.dt.date, "on": is_on})
             .groupby("session")["on"].sum())

quality = on_counts.rename("n_on_bars").to_frame()
quality["coverage"] = quality["n_on_bars"] / EXPECTED_ON_BARS
quality["pass"] = quality["coverage"] >= MIN_COVERAGE
quality.index = pd.to_datetime(quality.index)

# --- restrict to sessions with baseline trade rows --------------------------
trades = pd.read_csv(CACHE / "baseline_trades_8yr.csv", parse_dates=["timestamp"])
trade_sessions = pd.Series(sorted(trades["timestamp"].dt.normalize().unique()))

q = quality.reindex(trade_sessions)
q["n_on_bars"] = q["n_on_bars"].fillna(0).astype(int)
q["coverage"] = q["coverage"].fillna(0.0)
q["pass"] = q["pass"].fillna(False)

removed = q[~q["pass"]]
removal_by_year = removed.groupby(removed.index.year).size().to_dict()
kept = q[q["pass"]]

# --- 70/30 chronological split + 4 IS walk-forward folds --------------------
dates = kept.index.sort_values()
n_is = int(len(dates) * 0.70)
is_dates, oos_dates = dates[:n_is], dates[n_is:]
boundary = str(oos_dates[0].date())

fold_edges = [int(round(i * n_is / 4)) for i in range(5)]
folds = {f"fold{i+1}": {"start": str(is_dates[fold_edges[i]].date()),
                        "end": str(is_dates[fold_edges[i + 1] - 1].date()),
                        "n_sessions": fold_edges[i + 1] - fold_edges[i]}
         for i in range(4)}

q_out = q.reset_index().rename(columns={"index": "session_date"})
q_out["session_date"] = q_out["session_date"].dt.date
q_out.to_csv(CACHE / "session_quality.csv", index=False)

split = {
    "created": "2026-06-09",
    "session_quality_rule": {
        "expected_on_bars": EXPECTED_ON_BARS,
        "window": "18:00 prior ET -> 09:30 ET",
        "min_coverage": MIN_COVERAGE,
        "sessions_total": int(len(q)),
        "sessions_removed": int(len(removed)),
        "removed_by_year": {str(k): int(v) for k, v in removal_by_year.items()},
    },
    "split": {
        "rule": "chronological 70/30 by quality-passing session date",
        "n_is_sessions": int(len(is_dates)),
        "n_oos_sessions": int(len(oos_dates)),
        "is_start": str(is_dates[0].date()),
        "is_end": str(is_dates[-1].date()),
        "oos_boundary_date": boundary,
        "oos_end": str(oos_dates[-1].date()),
    },
    "is_folds": folds,
}
(RESULTS / "phase1_split.json").write_text(json.dumps(split, indent=2))

print(json.dumps(split, indent=2))
print("\nRemoved sessions detail (worst 15):")
print(removed.sort_values("coverage").head(15).to_string())
