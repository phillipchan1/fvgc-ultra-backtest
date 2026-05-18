#!/usr/bin/env python3
"""
Sanity-check the new consolidation pipeline by comparing its 1m output against
the existing pre-built `data/raw/glbx-mdp3-20200927-20260221.ohlcv-1m.csv` in
the date range where the two overlap.

If the pipeline is correct (front-month picking, filters, aggregation), the two
should agree on OHLC within rounding and on volume within a fraction of a percent
on every minute in the overlap. Disagreement points at a contract-roll bug, a
filter mismatch, or a timezone bug.

Run:
  python tools/validate_consolidation.py
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

NEW_1M = Path("data/consolidated/nq-front-month.ohlcv-1m.parquet")
OLD_1M = Path("data/raw/glbx-mdp3-20200927-20260221.ohlcv-1m.csv")


def load_new() -> pl.DataFrame:
    df = pl.read_parquet(NEW_1M)
    return df.select(
        pl.col("timestamp_utc").alias("ts"),
        pl.col("open").alias("open_new"),
        pl.col("high").alias("high_new"),
        pl.col("low").alias("low_new"),
        pl.col("close").alias("close_new"),
        pl.col("volume").alias("volume_new"),
    )


def load_old() -> pl.DataFrame:
    """
    The existing 1m raw is a *multi-contract* file (not yet front-month filtered).
    For a fair compare we collapse it the same way the new pipeline does: pick the
    contract with max daily volume per date, then keep only those rows.
    """
    df = pl.read_csv(OLD_1M, schema_overrides={"symbol": pl.String})
    df = df.filter(~pl.col("symbol").str.contains("-"))
    df = df.with_columns(
        pl.col("ts_event").str.to_datetime(time_unit="ns", time_zone="UTC")
    )
    df = df.with_columns(pl.col("ts_event").dt.date().alias("_date"))

    daily = (
        df.group_by(["_date", "symbol"])
          .agg(pl.col("volume").sum().alias("dv"))
          .sort(["_date", "dv"], descending=[False, True])
    )
    fm = (
        daily.group_by("_date", maintain_order=True)
             .agg(pl.col("symbol").first().alias("fm"))
    )
    # jitter smoother (same logic as consolidate_data.py)
    fm = fm.sort("_date")
    syms = fm["fm"].to_list()
    for i in range(1, len(syms) - 1):
        if syms[i - 1] == syms[i + 1] and syms[i] != syms[i - 1]:
            syms[i] = syms[i - 1]
    fm = fm.with_columns(pl.Series("fm", syms))

    df = df.join(fm, on="_date", how="inner").filter(pl.col("symbol") == pl.col("fm"))
    df = df.unique(subset=["ts_event"], keep="first").sort("ts_event")
    return df.select(
        pl.col("ts_event").alias("ts"),
        pl.col("open").alias("open_old"),
        pl.col("high").alias("high_old"),
        pl.col("low").alias("low_old"),
        pl.col("close").alias("close_old"),
        pl.col("volume").alias("volume_old"),
    )


def main() -> None:
    print("Loading new 1m parquet...")
    new = load_new()
    print(f"  rows: {len(new):,}  range: {new['ts'].min()} .. {new['ts'].max()}")

    print("Loading + collapsing old 1m raw...")
    old = load_old()
    print(f"  rows: {len(old):,}  range: {old['ts'].min()} .. {old['ts'].max()}")

    print("\nJoining on timestamp...")
    j = new.join(old, on="ts", how="inner")
    print(f"  overlapping minutes: {len(j):,}")
    print(f"  new-only minutes:    {len(new) - len(j):,}")
    print(f"  old-only minutes:    {len(old) - len(j):,}")

    if len(j) == 0:
        print("\nNo overlap found — check timestamp formats / date ranges.")
        return

    # Diffs
    j = j.with_columns(
        (pl.col("open_new")   - pl.col("open_old")).abs().alias("d_open"),
        (pl.col("high_new")   - pl.col("high_old")).abs().alias("d_high"),
        (pl.col("low_new")    - pl.col("low_old")).abs().alias("d_low"),
        (pl.col("close_new")  - pl.col("close_old")).abs().alias("d_close"),
        (pl.col("volume_new") - pl.col("volume_old")).alias("d_vol"),
    )

    print("\nOHLC absolute-diff stats (new vs old, points):")
    for col in ["d_open", "d_high", "d_low", "d_close"]:
        s = j[col]
        print(f"  {col}: mean={s.mean():.4f}  p50={s.median():.4f}  "
              f"p99={s.quantile(0.99):.4f}  max={s.max():.4f}  "
              f"nonzero={int((s > 0).sum()):,}")

    print("\nVolume diff stats (new - old):")
    s = j["d_vol"]
    abs_s = s.abs()
    print(f"  mean={s.mean():.2f}  p50={s.median():.2f}  "
          f"abs_max={int(abs_s.max())}  abs_p99={int(abs_s.quantile(0.99))}")

    # Bucket disagreements by magnitude
    j = j.with_columns(
        pl.max_horizontal("d_open", "d_high", "d_low", "d_close").alias("d_max")
    )
    print("\nBars by max-OHLC-diff bucket:")
    for lo, hi in [(0, 0.25), (0.25, 1.0), (1.0, 5.0), (5.0, 50.0), (50.0, 1e9)]:
        n = j.filter((pl.col("d_max") > lo) & (pl.col("d_max") <= hi)).height
        print(f"  ({lo:>4} .. {hi:>6}]: {n:>10,}  ({100*n/len(j):.3f}%)")

    bad_big = j.filter(pl.col("d_max") > 5.0).sort("ts")
    print(f"\nBars with diff > 5pt: {len(bad_big):,}")
    if len(bad_big):
        # Group by date — likely cluster on roll days
        bad_by_date = (
            bad_big.with_columns(pl.col("ts").dt.date().alias("date"))
                   .group_by("date")
                   .agg(pl.len().alias("n_bad"), pl.col("d_max").max().alias("worst"))
                   .sort("n_bad", descending=True)
        )
        print("\nDates with the most >5pt disagreements:")
        print(bad_by_date.head(15))

        print("\nSample of worst disagreements:")
        print(bad_big.sort("d_max", descending=True).head(10).select([
            "ts", "open_new", "open_old", "close_new", "close_old",
            "volume_new", "volume_old", "d_max",
        ]))

    # Verdict on the "real" disagreements (>1pt = bigger than typical late-print noise)
    real_bad = j.filter(pl.col("d_max") > 1.0).height
    pct_real_bad = 100 * real_bad / len(j)
    if pct_real_bad < 0.01:
        verdict = "PASS (sub-tick noise only)"
    elif pct_real_bad < 0.5:
        verdict = "ACCEPTABLE (likely roll-day or late-print edges)"
    else:
        verdict = "INVESTIGATE"
    print(f"\nReal disagreements (>1pt): {real_bad:,} ({pct_real_bad:.4f}%) -> {verdict}")


if __name__ == "__main__":
    main()
