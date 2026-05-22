#!/usr/bin/env python3
"""
Incrementally update the NQ front-month dataset from Databento.

Single source of truth: `data/raw/glbx-mdp3-*.ohlcv-1s.csv` (the 1s tape).
All consolidated timeframes in `data/consolidated/` are *derived* from it.

What this does:
  1. Read the current end timestamp from the consolidated 1s parquet.
  2. Fetch the missing window of OHLCV-1s from Databento (NQ.FUT parent
     symbol = all active months, so front-month detection still works).
  3. Append the raw delta to the master 1s CSV (no full rewrite).
  4. Apply the same consolidate pipeline (front-month pick, outlier filter,
     timeframe aggregation) to the delta only.
  5. Append to each consolidated parquet + CSV via atomic write
     (read existing tail → concat → dedupe on timestamp → sort → tmp+rename).

Run:
  python tools/update_data.py --dry-run     # preview gap + cost, no writes
  python tools/update_data.py               # do the update
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
import time
from pathlib import Path

import polars as pl
from dotenv import load_dotenv

# Make `consolidate_data` importable when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from consolidate_data import (
    OUTPUT_DIR,
    PRICE_FLOOR,
    TIMEFRAMES,
    aggregate_timeframe,
    apply_outlier_filter,
    pick_front_month,
)

# --- Paths --------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CONSOLIDATED_DIR = ROOT / "data" / "consolidated"
LOG_DIR = ROOT / "logs"

NY_TZ = "America/New_York"
DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1s"
SYMBOL = "NQ.FUT"
STYPE_IN = "parent"


# --- Helpers ------------------------------------------------------------------

def _t(msg: str, t0: float) -> None:
    print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)


def find_master_csv() -> Path:
    """Return the largest existing master 1s CSV (the historical archive)."""
    candidates = sorted(RAW_DIR.glob("glbx-mdp3-*.ohlcv-1s.csv"))
    if not candidates:
        raise FileNotFoundError(f"No master 1s CSV in {RAW_DIR}")
    return max(candidates, key=lambda p: p.stat().st_size)


def find_consolidated_max_ts() -> dt.datetime:
    """Latest UTC timestamp present in the 1s consolidated parquet."""
    p = CONSOLIDATED_DIR / "nq-front-month.ohlcv-1s.parquet"
    mx = (
        pl.scan_parquet(p)
        .select(pl.col("ts_event").max())
        .collect()
        .item()
    )
    if mx is None:
        raise RuntimeError(f"Could not read max ts_event from {p}")
    return mx


def get_databento_available_end(*, t0: float) -> dt.datetime:
    """Ask Databento what's the latest available ts for our schema."""
    import databento as db

    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        raise RuntimeError("DATABENTO_API_KEY not set. Add it to .env at project root.")
    client = db.Historical(api_key)
    r = client.metadata.get_dataset_range(dataset=DATASET)
    end_str = r["schema"][SCHEMA]["end"]
    available_end = dt.datetime.fromisoformat(end_str.replace("Z", "+00:00"))
    _t(f"Databento {SCHEMA} available up to {available_end.isoformat()}", t0)
    return available_end


def fetch_databento_ohlcv_1s(start: dt.datetime, end: dt.datetime, *, t0: float) -> "pl.DataFrame":
    """
    Fetch NQ.FUT (parent) 1s OHLCV from Databento between [start, end).
    Returns a polars DataFrame with columns matching the master CSV schema:
      ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume, symbol
    """
    import databento as db  # imported lazily so --dry-run doesn't require a key

    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DATABENTO_API_KEY not set. Add it to .env at project root."
        )

    _t(f"Fetching Databento {SCHEMA} {SYMBOL} [{start} .. {end})...", t0)
    client = db.Historical(api_key)
    store = client.timeseries.get_range(
        dataset=DATASET,
        schema=SCHEMA,
        symbols=SYMBOL,
        stype_in=STYPE_IN,
        start=start,
        end=end,
    )
    df_pd = store.to_df(pretty_ts=False, price_type="float", map_symbols=True)
    _t(f"  received {len(df_pd):,} rows", t0)

    if len(df_pd) == 0:
        return pl.DataFrame()

    # Normalize ts_event: Databento returns a DatetimeIndex; promote to column,
    # keep UTC, nanosecond resolution. Master CSV stores ts_event as the first
    # column with format "2018-01-01T23:00:00.000000000Z".
    df_pd = df_pd.reset_index().rename(columns={"index": "ts_event"})
    if "ts_event" not in df_pd.columns:
        # to_df() returns ts_event as the index name when ts_event is the bar key
        ts_idx_name = df_pd.columns[0]
        df_pd = df_pd.rename(columns={ts_idx_name: "ts_event"})

    df = pl.from_pandas(df_pd)

    # Normalize ts_event to tz-aware UTC datetime[ns].
    # With pretty_ts=False, Databento returns int64 nanoseconds since epoch.
    ts_dtype = df.schema["ts_event"]
    if ts_dtype == pl.Datetime:
        if ts_dtype.time_zone is None:
            df = df.with_columns(pl.col("ts_event").dt.replace_time_zone("UTC"))
    elif ts_dtype in (pl.Int64, pl.UInt64):
        df = df.with_columns(
            pl.col("ts_event").cast(pl.Int64).cast(pl.Datetime("ns")).dt.replace_time_zone("UTC")
        )
    else:
        df = df.with_columns(
            pl.col("ts_event").cast(pl.Utf8).str.to_datetime(time_unit="ns", time_zone="UTC")
        )

    # Master CSV column set
    master_cols = ["ts_event", "rtype", "publisher_id", "instrument_id",
                   "open", "high", "low", "close", "volume", "symbol"]
    have = set(df.columns)
    missing = [c for c in master_cols if c not in have]
    if missing:
        raise RuntimeError(
            f"Databento response missing expected columns {missing}. "
            f"Got: {df.columns}"
        )
    df = df.select(master_cols)

    return df


def write_delta_raw_csv(delta: pl.DataFrame, start_d: dt.date, end_d: dt.date) -> Path:
    """
    Write the delta as its own raw CSV next to the master. The consolidate
    script already globs `glbx-mdp3-*.ohlcv-1s.csv`, so this keeps a clean
    archive trail of every fetch.
    """
    fname = f"glbx-mdp3-{start_d:%Y%m%d}-{end_d:%Y%m%d}.ohlcv-1s.csv"
    out = RAW_DIR / fname

    # Match master format: ts_event ISO-8601 with nanos + Z. Polars writes UTC
    # datetimes as "2018-01-01T23:00:00.000000000Z" by default with datetime_format.
    delta.write_csv(
        out,
        datetime_format="%Y-%m-%dT%H:%M:%S%.9fZ",
    )
    return out


def append_to_master_csv(master: Path, delta_csv: Path) -> None:
    """Append delta CSV rows (skip header) to the master CSV."""
    with open(delta_csv, "r") as src, open(master, "a") as dst:
        next(src)  # skip delta header
        shutil.copyfileobj(src, dst)


def _coerce_to_schema(df: pl.DataFrame, target_schema: pl.Schema) -> pl.DataFrame:
    """Cast each column in df to match target_schema dtypes (column order too)."""
    casts = []
    for col, dtype in target_schema.items():
        casts.append(pl.col(col).cast(dtype).alias(col))
    return df.select(casts)


def append_consolidated_1s(delta_clean: pl.DataFrame, *, t0: float) -> None:
    """
    Append delta to nq-front-month.ohlcv-1s.parquet via atomic tmp-rename.
    Schema: [ts_event, open, high, low, close, volume, symbol].
    """
    target = CONSOLIDATED_DIR / "nq-front-month.ohlcv-1s.parquet"
    existing = pl.read_parquet(target)
    delta_proj = _coerce_to_schema(delta_clean, existing.schema)
    combined = (
        pl.concat([existing, delta_proj], how="vertical")
        .unique(subset=["ts_event"], keep="last")
        .sort("ts_event")
    )
    tmp = target.with_suffix(".parquet.tmp")
    combined.write_parquet(tmp, compression="zstd")
    tmp.replace(target)
    _t(f"  1s parquet: +{len(delta_proj):,} -> {len(combined):,} total", t0)


def append_consolidated_tf(tf: str, delta_tf: pl.DataFrame, *, t0: float) -> None:
    """
    Append delta to nq-front-month.ohlcv-<tf>.parquet AND .csv atomically.
    Schema: [timestamp_utc, timestamp_ny, open, high, low, close, volume].
    """
    parquet = CONSOLIDATED_DIR / f"nq-front-month.ohlcv-{tf}.parquet"
    csv_path = CONSOLIDATED_DIR / f"nq-front-month.ohlcv-{tf}.csv"

    existing = pl.read_parquet(parquet)
    delta_proj = _coerce_to_schema(delta_tf, existing.schema)
    combined = (
        pl.concat([existing, delta_proj], how="vertical")
        .unique(subset=["timestamp_utc"], keep="last")
        .sort("timestamp_utc")
    )

    tmp_parquet = parquet.with_suffix(".parquet.tmp")
    tmp_csv = csv_path.with_suffix(".csv.tmp")
    combined.write_parquet(tmp_parquet, compression="zstd")
    combined.write_csv(tmp_csv)
    tmp_parquet.replace(parquet)
    tmp_csv.replace(csv_path)

    _t(f"  {tf}: +{len(delta_proj):,} -> {len(combined):,} total", t0)


def build_delta_clean(delta_raw: pl.DataFrame, *, t0: float) -> pl.DataFrame:
    """
    Apply the consolidate pipeline to the delta:
      drop spreads -> pick front-month per date -> filter to front-month
      -> price floor -> outlier filter -> dedupe -> sort.
    Returns a clean 1s frame [ts_event, open, high, low, close, volume, symbol].
    """
    _t("Cleaning delta (drop spreads, pick front-month, filter)...", t0)

    df = delta_raw.filter(~pl.col("symbol").str.contains("-"))

    df = df.with_columns(pl.col("ts_event").dt.date().alias("_date"))

    daily_vol = (
        df.group_by(["_date", "symbol"])
          .agg(pl.col("volume").sum().alias("daily_vol"))
    )
    front = pick_front_month(daily_vol, jitter=True)
    _t(f"  delta front-month schedule:\n{front}", t0)

    df = (
        df.join(front, on="_date", how="inner")
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
    )

    n_before = len(df)
    df = apply_outlier_filter(df)
    _t(f"  outlier filter: {n_before:,} -> {len(df):,} (dropped {n_before - len(df):,})", t0)

    return df


def log_run(payload: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = " | ".join(f"{k}={v}" for k, v in payload.items())
    with open(LOG_DIR / "update_data.log", "a") as f:
        f.write(line + "\n")


# --- Main ---------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the gap to fill and exit. Does not call Databento, does not write.",
    )
    ap.add_argument(
        "--end",
        type=str,
        default=None,
        help="UTC end (exclusive), ISO 8601. Default: now (UTC).",
    )
    ap.add_argument(
        "--overlap-hours",
        type=float,
        default=1.0,
        help="Re-fetch this many hours before the last known timestamp as a "
             "boundary sanity check (deduped on append). Default: 1.0.",
    )
    return ap.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    t0 = time.time()

    print("=" * 70)
    print(f"NQ data update  ({dt.datetime.now(dt.timezone.utc).isoformat()})")
    print("=" * 70)

    master = find_master_csv()
    last_ts = find_consolidated_max_ts()  # tz-aware UTC
    # Ensure tz-aware UTC
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=dt.timezone.utc)

    # End boundary: cap at Databento's actual available end for this schema
    # (publish lag is a few minutes). User --end is honored but still capped.
    available_end = get_databento_available_end(t0=t0)
    if args.end:
        requested_end = dt.datetime.fromisoformat(args.end).astimezone(dt.timezone.utc)
        end_ts = min(requested_end, available_end)
    else:
        end_ts = available_end

    start_ts = last_ts + dt.timedelta(seconds=1) - dt.timedelta(hours=args.overlap_hours)

    gap = end_ts - start_ts
    print(f"Master CSV     : {master.name} ({master.stat().st_size / 1e9:.2f} GB)")
    print(f"Consolidated   : max ts_event = {last_ts.isoformat()}")
    print(f"Fetch window   : [{start_ts.isoformat()}, {end_ts.isoformat()})")
    print(f"Window span    : {gap} ({gap.total_seconds() / 3600:.1f} hours)")
    print(f"Overlap re-fetch: {args.overlap_hours:.1f}h (deduped on append)")

    if end_ts <= last_ts:
        print("Nothing to fetch — consolidated is already at or past end_ts.")
        return 0

    if args.dry_run:
        print("\n--dry-run: skipping fetch and writes.")
        return 0

    # 1. Fetch from Databento
    delta_raw = fetch_databento_ohlcv_1s(start_ts, end_ts, t0=t0)
    if len(delta_raw) == 0:
        print("No rows returned from Databento. Nothing to do.")
        return 0

    fetched_min = delta_raw["ts_event"].min()
    fetched_max = delta_raw["ts_event"].max()
    _t(f"Delta range: {fetched_min} .. {fetched_max}", t0)

    # 2. Write raw delta CSV (archive snapshot). Do NOT append to master yet —
    #    we commit to master last, only after every consolidated parquet has
    #    been successfully rewritten. If anything below fails, master stays
    #    untouched and the run is fully retryable.
    start_d = fetched_min.date() if hasattr(fetched_min, "date") else dt.date.fromisoformat(str(fetched_min)[:10])
    end_d = fetched_max.date() if hasattr(fetched_max, "date") else dt.date.fromisoformat(str(fetched_max)[:10])
    delta_csv = write_delta_raw_csv(delta_raw, start_d, end_d)
    _t(f"Wrote raw delta -> {delta_csv.name} ({delta_csv.stat().st_size / 1e6:.1f} MB)", t0)

    # 3. Clean delta + aggregate + append to each consolidated TF
    delta_clean = build_delta_clean(delta_raw, t0=t0)
    if len(delta_clean) == 0:
        print("Delta cleaned to zero rows (all filtered). Nothing to commit.")
        return 0

    append_consolidated_1s(delta_clean, t0=t0)
    for tf in TIMEFRAMES:
        delta_tf = aggregate_timeframe(delta_clean, tf)
        append_consolidated_tf(tf, delta_tf, t0=t0)

    # 4. All consolidated writes committed — now safe to grow the master CSV.
    append_to_master_csv(master, delta_csv)
    _t(f"Appended delta to master -> {master.name} "
       f"({master.stat().st_size / 1e9:.2f} GB)", t0)

    # 5. Acceptance check: print new max ts across all parquets
    print("\nAcceptance check — max timestamp per consolidated parquet:")
    for tf_name in ["1s"] + list(TIMEFRAMES):
        p = CONSOLIDATED_DIR / f"nq-front-month.ohlcv-{tf_name}.parquet"
        ts_col = "ts_event" if tf_name == "1s" else "timestamp_utc"
        mx = pl.scan_parquet(p).select(pl.col(ts_col).max()).collect().item()
        print(f"  {tf_name:4s} {mx}")

    log_run({
        "when": dt.datetime.now(dt.timezone.utc).isoformat(),
        "start": start_ts.isoformat(),
        "end": end_ts.isoformat(),
        "delta_raw_rows": len(delta_raw),
        "delta_clean_rows": len(delta_clean),
        "duration_s": f"{time.time() - t0:.1f}",
    })

    _t("Done.", t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
