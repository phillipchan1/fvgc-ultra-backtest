#!/usr/bin/env python3
"""
Consolidate Databento ES OHLCV-1s CSVs into clean front-month candle files at
multiple timeframes. Mirror of consolidate_data.py for ES; used for SMT
divergence detection.

Steps:
  1. Scan all `data/raw/ES-glbx-mdp3-*.ohlcv-1s.csv` files
  2. Drop calendar-spread rows (symbol contains '-')
  3. Pick the front-month ES contract per calendar date
  4. Apply price floor + dynamic outlier filter
  5. Aggregate to 15s / 30s / 1m / 2m / 3m / 5m / 15m
  6. Write each timeframe to both Parquet and CSV

Run:
  python tools/consolidate_es.py
"""

from __future__ import annotations

import time
from pathlib import Path

import polars as pl

# --- Paths --------------------------------------------------------------------

DATA_DIR = Path("data/raw")
OUTPUT_DIR = Path("data/consolidated")

# --- Filters ------------------------------------------------------------------

# ES traded ~3000 in 2021 and grew to ~6000+ by 2026. A 500-pt floor
# catches zero-pad / corrupt rows without killing historical data. The dynamic
# outlier filter below does the real work. ES tick is 0.25 (vs NQ 0.25 but smaller %).
PRICE_FLOOR = 500
OUTLIER_THRESHOLD = 30  # ES moves ~1/4 the points of NQ — tighter outlier band

# Timeframes to emit. Each will produce both .parquet and .csv outputs.
TIMEFRAMES = ["15s", "30s", "1m", "2m", "3m", "5m", "15m"]

# Polars truncate-interval aliases
TF_TO_EVERY = {
    "15s": "15s",
    "30s": "30s",
    "1m":  "1m",
    "2m":  "2m",
    "3m":  "3m",
    "5m":  "5m",
    "15m": "15m",
}

NY_TZ = "America/New_York"


# --- Reusable pipeline helpers (importable) -----------------------------------
# These operate on in-memory polars DataFrames and are shared with
# tools/update_data.py, which appends a small delta without re-scanning the
# full 12 GB raw archive.

def pick_front_month(daily_vol: pl.DataFrame, *, jitter: bool = True) -> pl.DataFrame:
    """
    Given a frame with columns (_date, symbol, daily_vol), return one row per
    _date with the front-month symbol (max daily volume), optionally smoothed
    by a 1-day jitter filter so a single anomalous day doesn't fragment rolls.

    The jitter filter needs at least 3 dates of context; with fewer dates it
    is a no-op.
    """
    front = (
        daily_vol
        .sort(["_date", "daily_vol"], descending=[False, True])
        .group_by("_date", maintain_order=True)
        .agg(pl.col("symbol").first().alias("front_month"))
        .sort("_date")
    )

    if jitter and len(front) >= 3:
        syms = front["front_month"].to_list()
        smoothed = syms.copy()
        for i in range(1, len(syms) - 1):
            if syms[i - 1] == syms[i + 1] and syms[i] != syms[i - 1]:
                smoothed[i] = syms[i - 1]
        front = front.with_columns(pl.Series("front_month", smoothed))

    return front


def apply_outlier_filter(
    df: pl.DataFrame,
    *,
    threshold_pts: float = OUTLIER_THRESHOLD,
    bucket: str = "30s",
) -> pl.DataFrame:
    """
    Drop rows whose (open+close)/2 deviates more than `threshold_pts` from the
    median mid within the same `bucket` (default 30s) window. Operates on a
    1s OHLCV frame with a `ts_event` column (datetime).
    """
    with_mid = df.with_columns(
        ((pl.col("open") + pl.col("close")) / 2.0).alias("_mid"),
        pl.col("ts_event").dt.truncate(bucket).alias("_bucket"),
    )
    with_med = with_mid.with_columns(
        pl.col("_mid").median().over("_bucket").alias("_med")
    )
    return (
        with_med
        .filter((pl.col("_mid") - pl.col("_med")).abs() <= threshold_pts)
        .drop(["_mid", "_bucket", "_med"])
    )


def aggregate_timeframe(df: pl.DataFrame, tf: str, *, ny_tz: str = NY_TZ) -> pl.DataFrame:
    """
    Aggregate a clean 1s OHLCV frame to the target timeframe. Output columns:
    timestamp_utc, timestamp_ny, open, high, low, close, volume. Matches the
    schema of the existing consolidated parquets for 15s/30s/1m/2m/3m/5m/15m.
    """
    every = TF_TO_EVERY[tf]
    return (
        df
        .with_columns(pl.col("ts_event").dt.truncate(every).alias("timestamp_utc"))
        .group_by("timestamp_utc", maintain_order=False)
        .agg(
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
        )
        .sort("timestamp_utc")
        .with_columns(
            pl.col("timestamp_utc").dt.convert_time_zone(ny_tz).alias("timestamp_ny")
        )
        .select(["timestamp_utc", "timestamp_ny", "open", "high", "low", "close", "volume"])
    )


# --- Helpers ------------------------------------------------------------------

def _t(msg: str, t0: float) -> None:
    print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)


def discover_raw_files() -> list[Path]:
    files = sorted(DATA_DIR.glob("ES-glbx-mdp3-*.ohlcv-1s.csv"))
    if not files:
        raise FileNotFoundError(f"No ohlcv-1s CSVs found in {DATA_DIR}")
    print("Raw input files:")
    for f in files:
        # Follow symlink for size if needed
        try:
            size = f.stat().st_size
        except OSError:
            size = f.resolve().stat().st_size
        print(f"  {f.name}  ({size / 1e9:.2f} GB)")
    return files


def build_front_month_schedule(files: list[Path], t0: float) -> pl.DataFrame:
    """
    Streaming pass: compute total volume per (date, symbol), then per date pick
    the symbol with max volume as the front month. Apply a 1-day jitter smoother
    so a single anomalous day doesn't fragment the roll schedule.
    """
    _t("Pass 1/2: scanning raw for daily volume by symbol...", t0)

    scans = [
        pl.scan_csv(
            str(f),
            schema_overrides={"symbol": pl.String},
            # ts_event is RFC3339 with nanoseconds; let polars try-parse later
        )
        for f in files
    ]
    lf = pl.concat(scans, how="vertical")

    daily = (
        lf
        .filter(~pl.col("symbol").str.contains("-"))   # drop spreads
        .with_columns(
            pl.col("ts_event").str.to_datetime(time_unit="ns", time_zone="UTC")
        )
        .with_columns(pl.col("ts_event").dt.date().alias("_date"))
        .group_by(["_date", "symbol"])
        .agg(pl.col("volume").sum().alias("daily_vol"))
        .sort(["_date", "daily_vol"], descending=[False, True])
        .collect(engine="streaming")
    )

    _t(f"  daily (date, symbol) rows: {len(daily):,}", t0)

    front = pick_front_month(daily, jitter=True)

    # Print the roll schedule (one line per contract change)
    print("\nFront-month roll schedule:")
    prev = None
    for d, sym in zip(front["_date"].to_list(), front["front_month"].to_list()):
        if sym != prev:
            print(f"  {d}  ->  {sym}")
            prev = sym
    print()

    return front


def consolidate_to_timeframes(
    files: list[Path],
    front: pl.DataFrame,
    t0: float,
) -> dict[str, pl.DataFrame]:
    """
    Streaming pass 2: join to front-month schedule, apply filters, then collect
    a clean front-month-only 1s frame. From that one in-memory frame, aggregate
    to all requested timeframes (cheap once data is filtered).
    """
    _t("Pass 2/2: filtering to front month + applying outlier filter...", t0)

    scans = [
        pl.scan_csv(
            str(f),
            schema_overrides={"symbol": pl.String},
        )
        for f in files
    ]
    lf = pl.concat(scans, how="vertical")

    front_lf = front.lazy()

    # Filter steps:
    #  - drop spreads
    #  - parse ts_event
    #  - tag _date, join front-month, keep only rows where symbol == front_month
    #  - apply price floor on all four OHLC columns
    cleaned = (
        lf
        .filter(~pl.col("symbol").str.contains("-"))
        .with_columns(
            pl.col("ts_event").str.to_datetime(time_unit="ns", time_zone="UTC")
        )
        .with_columns(pl.col("ts_event").dt.date().alias("_date"))
        .join(front_lf, on="_date", how="inner")
        .filter(pl.col("symbol") == pl.col("front_month"))
        .filter(
            (pl.col("open") >= PRICE_FLOOR)
            & (pl.col("high") >= PRICE_FLOOR)
            & (pl.col("low") >= PRICE_FLOOR)
            & (pl.col("close") >= PRICE_FLOOR)
        )
        .select(["ts_event", "open", "high", "low", "close", "volume", "symbol"])
        .unique(subset=["ts_event"], keep="first")
        .sort("ts_event")
        .collect(engine="streaming")
    )

    _t(f"  clean 1s rows (pre-outlier): {len(cleaned):,}", t0)

    # Dynamic outlier filter: drop rows whose (open+close)/2 deviates >100pt
    # from the median mid within the same 30s bucket.
    _t("Applying outlier filter (>100pt from 30s median)...", t0)
    n_before = len(cleaned)
    cleaned = apply_outlier_filter(cleaned)
    _t(f"  dropped {n_before - len(cleaned):,} outliers; final 1s rows: {len(cleaned):,}", t0)

    # Optionally write the cleaned 1s frame too (handy for any sub-minute work)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    one_s_parquet = OUTPUT_DIR / "es-front-month.ohlcv-1s.parquet"
    cleaned.write_parquet(one_s_parquet, compression="zstd")
    _t(f"  wrote cleaned 1s parquet -> {one_s_parquet} "
       f"({one_s_parquet.stat().st_size / 1e9:.2f} GB)", t0)

    # Aggregate to each timeframe
    out: dict[str, pl.DataFrame] = {}
    for tf in TIMEFRAMES:
        _t(f"Aggregating {tf}...", t0)
        agg = aggregate_timeframe(cleaned, tf)
        out[tf] = agg
        _t(f"  {tf}: {len(agg):,} candles  "
           f"({agg['timestamp_utc'].min()} .. {agg['timestamp_utc'].max()})", t0)

    return out


def write_outputs(by_tf: dict[str, pl.DataFrame], t0: float) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for tf, df in by_tf.items():
        parquet_path = OUTPUT_DIR / f"es-front-month.ohlcv-{tf}.parquet"
        csv_path = OUTPUT_DIR / f"es-front-month.ohlcv-{tf}.csv"

        df.write_parquet(parquet_path, compression="zstd")
        df.write_csv(csv_path)

        _t(
            f"  wrote {tf}: "
            f"{parquet_path.name} ({parquet_path.stat().st_size / 1e6:.1f} MB) + "
            f"{csv_path.name} ({csv_path.stat().st_size / 1e6:.1f} MB)",
            t0,
        )


def main() -> None:
    t0 = time.time()
    print("=" * 70)
    print("ES front-month consolidation  (polars streaming, multi-TF)")
    print("=" * 70)

    files = discover_raw_files()
    front = build_front_month_schedule(files, t0)
    by_tf = consolidate_to_timeframes(files, front, t0)

    _t("Writing outputs...", t0)
    write_outputs(by_tf, t0)

    _t("Done.", t0)


if __name__ == "__main__":
    main()
