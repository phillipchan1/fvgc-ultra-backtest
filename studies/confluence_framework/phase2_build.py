"""Phase 2 — build per-trade point-in-time snapshots.

Computes the full feature library (fvgc/context/) for every program trade
(IS + OOS rows both get FEATURES — no OUTCOME evaluation happens here; OOS
outcome evaluation stays locked until Phase 5), reuses the near_miss_draw
tagger (C1 causal gating), and writes:

  results/phase2_snapshots.csv
  results/phase2_quality_report.md

Run from repo root with python3.13. First run is slow (HTF FVG touch scans);
intermediates cached under results/cache/htf_context.pkl.
"""
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from harness import load_program_trades, benchmark_mask  # noqa: E402
from fvgc.context.snapshot import build_context, build_snapshots  # noqa: E402

RESULTS = HERE / "results"
CACHE = RESULTS / "cache"

t0 = time.time()
trades = load_program_trades()
print(f"program trades: {len(trades)} (IS {sum(trades.split=='IS')} / "
      f"OOS {sum(trades.split=='OOS')})")

print("building context (cached after first run)...")
ctx = build_context(
    bars_path=ROOT / "data/consolidated/nq-front-month.ohlcv-30s.parquet",
    session_levels_csv=ROOT / "data/levels/session_levels.csv",
    trading_days_csv=ROOT / "data/trading_days/trading_days.csv",
    cache_dir=CACHE)
print(f"  context ready in {time.time()-t0:.0f}s | 15m FVGs: {len(ctx['fvgs15'])} "
      f"| 1h FVGs: {len(ctx['fvgs60'])} | sweeps: {len(ctx['sweeps'])}")

t1 = time.time()
snaps = build_snapshots(trades, ctx)
print(f"snapshots built in {time.time()-t1:.0f}s: {snaps.shape}")

# ---- near-miss reuse (studies/near_miss_draw/tagger.py, C1 causal gating) ----
spec = importlib.util.spec_from_file_location(
    "nm_tagger", ROOT / "studies/near_miss_draw/tagger.py")
nm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nm)

bars = ctx["bars"].reset_index(drop=True)
tod = bars["timestamp_ny"].dt.time
w1_mask = (tod >= nm.W1_START) & (tod <= nm.W1_END)
levels_df = pd.read_csv(ROOT / "data/levels/session_levels.csv", low_memory=False)
target_names = ["asia_high", "asia_low", "6am_high", "6am_low",
                "prev_day_high", "prev_day_low"]

nm_rows = []
for day, g in bars[w1_mask].groupby(bars.loc[w1_mask, "timestamp_ny"].dt.normalize()):
    dstr = str(day.date())
    day_lv = levels_df[(levels_df["date"] == dstr)
                       & (levels_df["level_name"].isin(target_names))
                       & levels_df["price"].notna()
                       & (levels_df["swept_pre_rth"].fillna(False) != True)]  # noqa: E712
    if day_lv.empty:
        continue
    rec = nm.scan_day(list(g.index), bars, day_lv)
    if rec:
        rec["session_date"] = day
        nm_rows.append(rec)
nm_days = pd.DataFrame(nm_rows)
print(f"near-miss days: {len(nm_days)} / {bars[w1_mask]['timestamp_ny'].dt.normalize().nunique()}")

snaps = snaps.merge(
    nm_days[["session_date", "near_miss_direction", "near_miss_level_price",
             "near_miss_confirmed_time"]],
    on="session_date", how="left")
conf = pd.to_datetime(snaps["near_miss_confirmed_time"])
aligned = ((snaps["near_miss_direction"] == "up") & (snaps["direction"] == "long")) | \
          ((snaps["near_miss_direction"] == "down") & (snaps["direction"] == "short"))
beyond = np.where(snaps["direction"] == "long",
                  snaps["near_miss_level_price"] > trades["entry_price"].values,
                  snaps["near_miss_level_price"] < trades["entry_price"].values)
# C1 causal gate: the near-miss exists for a trade only after its confirm time
snaps["near_miss_c1"] = (conf.notna() & (conf <= snaps["timestamp"])
                         & aligned & beyond)
snaps["near_miss_fade"] = (conf.notna() & (conf <= snaps["timestamp"])
                           & ~aligned)
snaps = snaps.drop(columns=["near_miss_direction", "near_miss_level_price",
                            "near_miss_confirmed_time"])

# ---- attach identifiers + outcomes (outcomes used by harness only) ----------
carry = trades[["timestamp", "direction", "variant", "entry_price", "sl_dist",
                "fvg_created_at", "fvg_top", "fvg_bottom", "fvg_mid",
                "outcome", "pnl", "win", "r", "split", "fold"]].reset_index(drop=True)
carry["fvg_size"] = carry["fvg_top"] - carry["fvg_bottom"]
carry["fvg_age_min"] = ((carry["timestamp"] - carry["fvg_created_at"])
                        .dt.total_seconds() / 60)
carry["is_benchmark"] = benchmark_mask(trades).values
snaps = snaps.drop(columns=["direction", "variant"]).merge(
    carry, on="timestamp", how="left", validate="1:1")

out_path = RESULTS / "phase2_snapshots.csv"
snaps.to_csv(out_path, index=False)
print(f"wrote {out_path} {snaps.shape}")

# ---- data-quality report -----------------------------------------------------
feat_cols = [c for c in snaps.columns
             if c not in {"timestamp", "session_date", "outcome", "pnl", "win",
                          "r", "split", "fold"}]
miss = snaps[feat_cols].isna().mean().sort_values(ascending=False)
lines = ["# Phase 2 — snapshot data-quality report\n",
         f"rows: {len(snaps)}  features: {len(feat_cols)}\n",
         "## Missingness (top 25)\n",
         miss.head(25).round(4).to_string(), "\n",
         "## Categorical distributions\n"]
for c in ["or_state", "macro_window", "first_sweep_name", "struct_15m",
          "struct_1h", "pd_zone", "gap_class"]:
    lines.append(f"### {c}\n{snaps[c].value_counts(dropna=False).to_string()}\n")
lines.append("## Key numeric sanity (describe)\n")
for c in ["draw_asym_dir", "n_untaken_above", "n_untaken_below",
          "nearest_untaken_dir_dist_R", "htf15m_nearest_above",
          "pd_range_pos", "gap_atr", "atr14_lag1"]:
    lines.append(f"### {c}\n{snaps[c].describe().round(3).to_string()}\n")
lines.append("## Boolean feature true-rates\n")
bools = [c for c in feat_cols if snaps[c].dtype == bool
         or set(snaps[c].dropna().unique()) <= {True, False}]
lines.append(snaps[bools].mean(numeric_only=False).apply(
    lambda x: round(float(x), 3)).to_string())
(RESULTS / "phase2_quality_report.md").write_text("\n".join(map(str, lines)))
print("wrote quality report")
print(f"total {time.time()-t0:.0f}s")
