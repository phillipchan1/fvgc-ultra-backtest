"""
HTF FVG Nesting Recheck.

Re-tests the hypothesis that FVGC entries occurring inside a same-direction HTF
FVG have elevated hit_2R. The original test (studies/discovery_2R_hits/explore_v3.py)
returned zero nested trades — that was a bug, not a real result.

Root cause of the v3 bug:
  dates = df['date'].to_numpy()        # produces numpy.datetime64
  htf_by_date = {... datetime.date ...}  # built from polars-iter_rows
  htf_by_date.get(dates[i], [])        # numpy.datetime64 != datetime.date  → all empty

Fix: keep dates as datetime.date everywhere (use .to_list()).

Study questions answered:
  Q1 — data structure audit (printed; also see analysis.md)
  Q2 — fixed nesting check using fvg_top / fvg_bottom (both populated for all HTF rows)
  Q3 — direction-aware (long entries inside bullish HTF FVG, short inside bearish)
  Q4 — per-timeframe lift on hit_2R for 15m / 1H / 4H / Daily, plus multi-tf compound
  Q5 — stacked with n_vp_targets >= 1
  Q6 — IS (2018-22) → OOS (2023-26) walk-forward
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
trades_pl = (
    pl.read_csv(ROOT / "studies/baseline/results/trades.csv", try_parse_dates=True)
    .filter(pl.col("outcome") != "skip")
    .with_columns(pl.col("timestamp").dt.date().alias("date"))
)
trades = trades_pl.to_pandas()
# Force pure datetime.date (pd.Timestamp is dt.date subclass but hashes differently).
trades["date"] = trades["date"].apply(lambda x: dt.date(x.year, x.month, x.day))

levels = pl.read_csv(ROOT / "data/levels/liquidity_levels.csv", try_parse_dates=True)
htf = (
    levels.filter(pl.col("group").str.starts_with("htf_"))
    .select(["date", "timeframe", "fvg_direction", "fvg_top", "fvg_bottom"])
    .filter(pl.col("fvg_top").is_not_null() & pl.col("fvg_bottom").is_not_null())
)

print(f"trades (non-skip): {len(trades)}")
print(f"HTF level rows:    {htf.height}")
print(f"HTF by timeframe:  {htf.group_by('timeframe').len().sort('timeframe').to_pandas().to_dict('records')}")


# ---------------------------------------------------------------------------
# Build per-date HTF lookup. Keys are datetime.date.
# ---------------------------------------------------------------------------
htf_by_date: dict[dt.date, list[tuple[str, str, float, float]]] = {}
for r in htf.iter_rows(named=True):
    htf_by_date.setdefault(r["date"], []).append(
        (r["timeframe"], r["fvg_direction"], r["fvg_top"], r["fvg_bottom"])
    )


# ---------------------------------------------------------------------------
# Compute nesting flags
# ---------------------------------------------------------------------------
TFS = ["15m", "1H", "4H", "Daily"]
flags = {f"nested_{tf}": np.zeros(len(trades), dtype=bool) for tf in TFS}
flags["nested_any"] = np.zeros(len(trades), dtype=bool)
flags["nested_count"] = np.zeros(len(trades), dtype=np.int32)

entry = trades["entry_price"].to_numpy()
direction = trades["direction"].to_numpy()
dates_list = trades["date"].tolist()

for i in range(len(trades)):
    fvgs = htf_by_date.get(dates_list[i], [])
    if not fvgs:
        continue
    want_dir = "bullish" if direction[i] == "long" else "bearish"
    seen_tfs: set[str] = set()
    for tf, fd, top, bottom in fvgs:
        if fd != want_dir:
            continue
        if bottom <= entry[i] <= top:
            flags[f"nested_{tf}"][i] = True
            flags["nested_any"][i] = True
            seen_tfs.add(tf)
    flags["nested_count"][i] = len(seen_tfs)

for k, v in flags.items():
    trades[k] = v

n_nested_any = int(trades["nested_any"].sum())
print(f"\nNested (same-direction, any TF): {n_nested_any}/{len(trades)} ({n_nested_any/len(trades)*100:.1f}%)")
for tf in TFS:
    col = f"nested_{tf}"
    n = int(trades[col].sum())
    print(f"  nested_{tf}: {n} ({n/len(trades)*100:.1f}%)")


# ---------------------------------------------------------------------------
# Outcome column. baseline uses hit_2_0R.
# ---------------------------------------------------------------------------
HIT = "hit_2_0R"
trades[HIT] = trades[HIT].astype("boolean").astype(float)

trades["is_oos"] = trades["date"].apply(lambda d: d.year >= 2023)
trades["year"] = trades["date"].apply(lambda d: d.year)


# ---------------------------------------------------------------------------
# Helper: lift rows
# ---------------------------------------------------------------------------
def lift_row(df: pd.DataFrame, mask: pd.Series, label: str, base_label: str = "baseline") -> dict:
    n = int(mask.sum())
    base_n = int(len(df))
    base = float(df[HIT].mean()) if base_n else float("nan")
    rate = float(df.loc[mask, HIT].mean()) if n else float("nan")
    return {
        "cell": label,
        "n": n,
        "base_n": base_n,
        f"{HIT}_rate": rate,
        f"{HIT}_base": base,
        "lift_pp": (rate - base) * 100 if not (np.isnan(rate) or np.isnan(base)) else float("nan"),
    }


# ---------------------------------------------------------------------------
# Q4 — per-TF lift, full sample
# ---------------------------------------------------------------------------
rows = []
rows.append(lift_row(trades, pd.Series([True] * len(trades), index=trades.index), "ALL"))
for tf in TFS:
    rows.append(lift_row(trades, trades[f"nested_{tf}"], f"nested_{tf}"))
rows.append(lift_row(trades, trades["nested_any"], "nested_any"))
# Multi-TF: nested in ≥2 different TFs simultaneously
rows.append(lift_row(trades, trades["nested_count"] >= 2, "nested_count>=2"))
rows.append(lift_row(trades, trades["nested_count"] >= 3, "nested_count>=3"))
# Heavy combos
rows.append(lift_row(trades, trades["nested_4H"] & trades["nested_Daily"], "nested_4H_AND_Daily"))
rows.append(lift_row(trades, trades["nested_1H"] & trades["nested_4H"], "nested_1H_AND_4H"))

per_tf_full = pd.DataFrame(rows)
per_tf_full.to_csv(OUT / "per_tf_full.csv", index=False)


# ---------------------------------------------------------------------------
# Q6 — IS/OOS split
# ---------------------------------------------------------------------------
is_df = trades[~trades["is_oos"]].copy()
oos_df = trades[trades["is_oos"]].copy()
print(f"\nIS  (2018-22): {len(is_df)}  base hit_2R = {is_df[HIT].mean():.3f}")
print(f"OOS (2023-26): {len(oos_df)}  base hit_2R = {oos_df[HIT].mean():.3f}")


def evaluate(df: pd.DataFrame, name: str) -> pd.DataFrame:
    rows = [lift_row(df, pd.Series([True] * len(df), index=df.index), f"{name}::ALL")]
    for tf in TFS:
        rows.append(lift_row(df, df[f"nested_{tf}"], f"{name}::nested_{tf}"))
    rows.append(lift_row(df, df["nested_any"], f"{name}::nested_any"))
    rows.append(lift_row(df, df["nested_count"] >= 2, f"{name}::nested_count>=2"))
    rows.append(lift_row(df, df["nested_count"] >= 3, f"{name}::nested_count>=3"))
    rows.append(lift_row(df, df["nested_4H"] & df["nested_Daily"], f"{name}::nested_4H_AND_Daily"))
    rows.append(lift_row(df, df["nested_1H"] & df["nested_4H"], f"{name}::nested_1H_AND_4H"))
    return pd.DataFrame(rows)


is_lift = evaluate(is_df, "IS")
oos_lift = evaluate(oos_df, "OOS")
wf = pd.concat([is_lift, oos_lift], ignore_index=True)
wf.to_csv(OUT / "walk_forward.csv", index=False)


# ---------------------------------------------------------------------------
# Per-year stability
# ---------------------------------------------------------------------------
rows = []
for yr, sub in trades.groupby("year"):
    base = sub[HIT].mean()
    for tf in TFS + ["any"]:
        col = f"nested_{tf}"
        m = sub[col]
        n = int(m.sum())
        rate = sub.loc[m, HIT].mean() if n else np.nan
        rows.append({
            "year": yr,
            "cell": col,
            "n": n,
            f"{HIT}_rate": rate,
            f"{HIT}_base": base,
            "lift_pp": (rate - base) * 100 if pd.notna(rate) else np.nan,
        })
yearly = pd.DataFrame(rows)
yearly.to_csv(OUT / "yearly.csv", index=False)


# ---------------------------------------------------------------------------
# Q5 — stack with n_vp_targets
# ---------------------------------------------------------------------------
vp = pd.read_csv(ROOT / "data/levels/daily_volume_profile.csv", parse_dates=["date"])
vp["date"] = vp["date"].apply(lambda x: dt.date(x.year, x.month, x.day))
df_vp = trades.merge(vp[["date", "poc", "vah", "val"]], on="date", how="left")

is_long = df_vp["direction"].to_numpy() == "long"
ep = df_vp["entry_price"].to_numpy()
sl_dist = df_vp["sl_dist"].to_numpy()


def signed_R(level: np.ndarray) -> np.ndarray:
    diff = level - ep
    return np.where(is_long, diff, -diff) / sl_dist


def in_zone(r: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return (r >= 0.5) & (r <= 3.0)


poc_in = in_zone(signed_R(df_vp["poc"].to_numpy().astype(float)))
vah_in = in_zone(signed_R(df_vp["vah"].to_numpy().astype(float)))
val_in = in_zone(signed_R(df_vp["val"].to_numpy().astype(float)))
df_vp["n_vp_targets"] = poc_in.astype(int) + vah_in.astype(int) + val_in.astype(int)
df_vp["has_vp"] = df_vp["n_vp_targets"] >= 1

rows = []
for split_name, sub in [("ALL", df_vp), ("IS", df_vp[~df_vp["is_oos"]]), ("OOS", df_vp[df_vp["is_oos"]])]:
    rows.append(lift_row(sub, pd.Series([True] * len(sub), index=sub.index), f"{split_name}::ALL"))
    rows.append(lift_row(sub, sub["has_vp"], f"{split_name}::has_vp"))
    rows.append(lift_row(sub, sub["nested_any"], f"{split_name}::nested_any"))
    rows.append(lift_row(sub, sub["has_vp"] & sub["nested_any"], f"{split_name}::has_vp_AND_nested_any"))
    rows.append(lift_row(sub, sub["has_vp"] & ~sub["nested_any"], f"{split_name}::has_vp_only"))
    rows.append(lift_row(sub, ~sub["has_vp"] & sub["nested_any"], f"{split_name}::nested_only"))

stack = pd.DataFrame(rows)
stack.to_csv(OUT / "vp_stack.csv", index=False)


# ---------------------------------------------------------------------------
# Summary print
# ---------------------------------------------------------------------------
def fmt(df: pd.DataFrame) -> str:
    show = df.copy()
    show[f"{HIT}_rate"] = show[f"{HIT}_rate"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "")
    show[f"{HIT}_base"] = show[f"{HIT}_base"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "")
    show["lift_pp"] = show["lift_pp"].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "")
    return show.to_string(index=False)


print("\n" + "=" * 78)
print("Q4 — per-TF lift (full sample, hit_2R)")
print("=" * 78)
print(fmt(per_tf_full))

print("\n" + "=" * 78)
print("Q6 — walk-forward (IS 2018-22 / OOS 2023-26)")
print("=" * 78)
print(fmt(wf))

print("\n" + "=" * 78)
print("Q5 — VP × nesting stack")
print("=" * 78)
print(fmt(stack))

print("\nSaved:")
for p in sorted(OUT.glob("*.csv")):
    print(f"  {p.relative_to(ROOT)}")
