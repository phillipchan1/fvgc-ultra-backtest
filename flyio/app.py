"""NQ Live Snapshot Service — Fly.io persistent process.

Maintains a 24/7 connection to Databento's Live API for GLBX.MDP3
ohlcv-1m bars on NQ.c.0. Each incoming bar updates an in-memory
session snapshot. The dashboard polls /api/live every ~5-10s to
get sub-minute-fresh data.

Why this exists vs. the Cloudflare Worker:
  - Workers are invocation-based — can't hold a streaming connection.
  - Databento Live API is a TCP/TLS stream (not REST), so it needs
    a persistent process.
  - This service replaces the Worker's ~10-15 min Historical lag with
    ~1-2 second Live lag.

Architecture:
  - Live thread runs the Databento subscription loop (blocking iterator)
  - FastAPI on the main thread serves HTTP for the dashboard
  - Shared state via a Lock-protected dict + bar list
  - Historical backfill on startup so overnight H/L is populated
    immediately rather than waiting for next overnight session
"""

from __future__ import annotations

import logging
import os
import threading
import time as time_module
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import databento as db
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("DATABENTO_API_KEY")
DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"
SYMBOL = "NQ.c.0"
STYPE_IN = "continuous"

NY_TZ = ZoneInfo("America/New_York")

# Databento OHLCV prices for GLBX.MDP3 are fixed-point integers, base 1e-9.
PRICE_SCALE = 1_000_000_000

# Session windows in ET
RTH_OPEN = (9, 30)   # today's RTH open
RTH_CLOSE = (16, 0)  # prior day's RTH close (boundary between prior RTH + overnight)
OR_CLOSE = (10, 15)  # today's opening-range close

# Bar buffer — keep last 24h (~1440 bars). Plenty for overnight + OR.
BAR_BUFFER_HOURS = 24

# CORS — origins allowed to read /api/live
ALLOWED_ORIGINS = [
    "https://phillipchan1.github.io",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
]

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

state_lock = threading.Lock()
bars: deque[dict[str, Any]] = deque()
state: dict[str, Any] = {
    "snapshot": None,
    "connected": False,
    "last_error": None,
    "last_record_at": None,
    "started_at": datetime.now(timezone.utc),
    "bar_count": 0,
    "reconnect_count": 0,
}

log = logging.getLogger("nq-live")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ---------------------------------------------------------------------------
# Bar handling
# ---------------------------------------------------------------------------


def _record_to_bar(rec) -> dict[str, Any] | None:
    """Convert a Databento OHLCV record to our dict shape. Returns None for
    non-bar records (status messages, system errors, etc.)."""
    # OHLCVMsg has the OHLCV fields directly; other record types we ignore.
    if not hasattr(rec, "open") or not hasattr(rec, "close"):
        return None
    try:
        ts_ns = int(rec.ts_event)
    except (AttributeError, TypeError, ValueError):
        return None
    return {
        "ts": datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc),
        "open": float(rec.open) / PRICE_SCALE,
        "high": float(rec.high) / PRICE_SCALE,
        "low": float(rec.low) / PRICE_SCALE,
        "close": float(rec.close) / PRICE_SCALE,
        "volume": int(rec.volume) if hasattr(rec, "volume") else 0,
    }


def _ingest_bar(bar: dict[str, Any]) -> None:
    """Add a bar to the buffer (dedupe + trim) and recompute snapshot."""
    with state_lock:
        # Dedupe by timestamp (Live + Historical can deliver the same minute)
        for existing in reversed(bars):
            if existing["ts"] == bar["ts"]:
                # Update in place (the newer one is usually authoritative)
                existing.update(bar)
                state["snapshot"] = _compute_snapshot()
                return
            if existing["ts"] < bar["ts"]:
                break
        # Append + sort if out of order (rare)
        bars.append(bar)
        if len(bars) >= 2 and bars[-1]["ts"] < bars[-2]["ts"]:
            sorted_bars = sorted(bars, key=lambda b: b["ts"])
            bars.clear()
            bars.extend(sorted_bars)
        # Trim — drop bars older than BAR_BUFFER_HOURS
        cutoff = datetime.now(timezone.utc) - timedelta(hours=BAR_BUFFER_HOURS)
        while bars and bars[0]["ts"] < cutoff:
            bars.popleft()
        state["last_record_at"] = datetime.now(timezone.utc)
        state["bar_count"] = len(bars)
        state["snapshot"] = _compute_snapshot()


def _compute_snapshot() -> dict[str, Any] | None:
    """Build the JSON snapshot. Caller must hold state_lock."""
    if not bars:
        return None

    now = datetime.now(timezone.utc)
    now_et = now.astimezone(NY_TZ)
    today_et = now_et.date()
    open_dt = now_et.replace(
        hour=RTH_OPEN[0], minute=RTH_OPEN[1], second=0, microsecond=0
    )
    or_close_dt = now_et.replace(
        hour=OR_CLOSE[0], minute=OR_CLOSE[1], second=0, microsecond=0
    )
    # Prior RTH close = yesterday 16:00 ET. Anchors the start of the
    # overnight session so we don't conflate prior-day RTH with overnight.
    prev_close_dt = (open_dt - timedelta(days=1)).replace(
        hour=RTH_CLOSE[0], minute=RTH_CLOSE[1], second=0, microsecond=0
    )
    prev_open_dt = prev_close_dt.replace(
        hour=RTH_OPEN[0], minute=RTH_OPEN[1], second=0, microsecond=0
    )

    prior_rth: list[dict] = []   # yesterday 9:30–16:00 ET
    overnight: list[dict] = []   # yesterday 16:00 ET → today 9:30 ET
    session_bars: list[dict] = [] # today 9:30 ET onward
    or_bars: list[dict] = []     # today 9:30–10:15 ET

    for b in bars:
        bar_et = b["ts"].astimezone(NY_TZ)
        if bar_et >= open_dt:
            session_bars.append(b)
            if bar_et < or_close_dt:
                or_bars.append(b)
        elif bar_et >= prev_close_dt:
            overnight.append(b)
        elif bar_et >= prev_open_dt:
            prior_rth.append(b)
        # else: older than yesterday's RTH open — outside any defined window

    last = bars[-1]
    lag_seconds = max(0, int((now - last["ts"]).total_seconds()))

    snap = {
        "current_price": last["close"],
        "current_ts_utc": last["ts"].isoformat(),
        "current_ts_et": last["ts"].astimezone(NY_TZ).isoformat(),
        "fetched_at_utc": now.isoformat(),
        "fetched_at_et": now_et.isoformat(),
        "lag_seconds": lag_seconds,
        "bar_count": len(bars),
        "pre_open": now_et < open_dt,
        "in_session": len(session_bars) > 0,
        "source": "databento-live",
        "prior_rth": None,
        "overnight": None,
        "opening_range": None,
    }

    if prior_rth:
        high = max(b["high"] for b in prior_rth)
        low = min(b["low"] for b in prior_rth)
        close = prior_rth[-1]["close"]
        snap["prior_rth"] = {
            "high": high,
            "low": low,
            "close": close,
            "range": high - low,
            "bar_count": len(prior_rth),
        }

    if overnight:
        high = max(b["high"] for b in overnight)
        low = min(b["low"] for b in overnight)
        snap["overnight"] = {
            "high": high,
            "low": low,
            "range": high - low,
            "bar_count": len(overnight),
        }
        # Derived gap vs prior RTH close, when both are known.
        if snap["prior_rth"]:
            snap["gap_pts"] = last["close"] - snap["prior_rth"]["close"]

    if or_bars:
        high = max(b["high"] for b in or_bars)
        low = min(b["low"] for b in or_bars)
        snap["opening_range"] = {
            "high": high,
            "low": low,
            "width": high - low,
            "bar_count": len(or_bars),
            "minutes_elapsed": min(len(or_bars), 45),
            "complete": now_et >= or_close_dt,
        }
    elif now_et >= open_dt:
        snap["opening_range"] = {
            "high": None,
            "low": None,
            "width": 0,
            "bar_count": 0,
            "minutes_elapsed": 0,
            "complete": False,
        }

    # Intraday factors — machine-readable booleans the dashboard uses to
    # re-evaluate matrix-play confluence + tier live.
    snap["intraday_factors"] = _compute_intraday_factors(
        or_bars, session_bars, now_et, or_close_dt
    )

    return snap


def _compute_intraday_factors(
    or_bars: list, session_bars: list, now_et, or_close_dt
) -> dict[str, Any]:
    """Derive bool factors from live bars. None = not yet computable; True/
    False = known. Threshold constants come from the validated insights:
      - 9:30 body top quartile: >= 23 pts
      - 9:30 range bottom quartile: <= 22 pts
      - 5-min OR bottom quartile: <= 42 pts
      - 5-min OR top quartile: >= 72 pts
      - 45-min OR tight (Q1 ~bottom 20%): <= 125 pts
      - 45-min OR wide  (Q5 ~top 20%): >= 205 pts
    """
    factors: dict[str, Any] = {
        "bear_930": None,
        "bull_930": None,
        "c930_body_top_q": None,
        "c930_range_bot_q": None,
        "or_5m_bot_q": None,
        "or_5m_top_q": None,
        "wide_45min_or": None,
        "tight_45min_or": None,
    }

    # 9:30 candle = the first OR bar (ts_event = 9:30:00 ET, ascending sort).
    if or_bars:
        c = or_bars[0]
        body = abs(c["close"] - c["open"])
        rng = c["high"] - c["low"]
        factors["bear_930"] = c["close"] < c["open"]
        factors["bull_930"] = c["close"] > c["open"]
        factors["c930_body_top_q"] = body >= 23
        factors["c930_range_bot_q"] = rng <= 22

    # First 5-min OR (bars 9:30-9:34 inclusive).
    if len(or_bars) >= 5:
        first5 = or_bars[:5]
        rng5 = max(b["high"] for b in first5) - min(b["low"] for b in first5)
        factors["or_5m_bot_q"] = rng5 <= 42
        factors["or_5m_top_q"] = rng5 >= 72

    # 45-min OR — only after the window has fully closed.
    if or_bars and now_et >= or_close_dt:
        hi = max(b["high"] for b in or_bars)
        lo = min(b["low"] for b in or_bars)
        rng45 = hi - lo
        factors["tight_45min_or"] = rng45 <= 125
        factors["wide_45min_or"] = rng45 >= 205

    return factors


# ---------------------------------------------------------------------------
# Historical backfill (run once on startup)
# ---------------------------------------------------------------------------


def historical_backfill() -> None:
    """Load last ~24h of 1-min bars from Databento Historical so the
    snapshot is meaningful immediately on startup (otherwise we'd have to
    wait for fresh bars to stream in, and overnight H/L would be empty).
    """
    log.info("Fetching historical backfill (%dh of bars)…", BAR_BUFFER_HOURS)
    try:
        client = db.Historical(key=API_KEY)
        # Historical has a publishing lag; pull until ~15 min ago to avoid
        # 422 "data_end_after_available_end" errors.
        end = datetime.now(timezone.utc) - timedelta(minutes=15)
        start = end - timedelta(hours=BAR_BUFFER_HOURS)
        df = client.timeseries.get_range(
            dataset=DATASET,
            symbols=SYMBOL,
            schema=SCHEMA,
            stype_in=STYPE_IN,
            start=start,
            end=end,
        ).to_df()
        if df.empty:
            log.warning("Historical backfill returned 0 bars")
            return
        ingested = 0
        for ts_event, row in df.iterrows():
            # Convert pandas Timestamp → tz-aware UTC datetime
            ts = ts_event.to_pydatetime() if hasattr(ts_event, "to_pydatetime") else ts_event
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bar = {
                "ts": ts.astimezone(timezone.utc),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row.get("volume", 0)),
            }
            _ingest_bar(bar)
            ingested += 1
        log.info("Historical backfill: ingested %d bars", ingested)
    except Exception as e:
        log.exception("Historical backfill failed: %s", e)
        with state_lock:
            state["last_error"] = f"historical backfill: {e}"


# ---------------------------------------------------------------------------
# Live subscription thread
# ---------------------------------------------------------------------------


def live_thread() -> None:
    """Block on a Databento Live connection, ingest bars as they stream.
    Reconnect on disconnect with exponential backoff."""
    backoff = 1
    while True:
        try:
            log.info("Connecting to Databento Live (%s/%s/%s)…",
                     DATASET, SCHEMA, SYMBOL)
            client = db.Live(key=API_KEY)
            client.subscribe(
                dataset=DATASET,
                schema=SCHEMA,
                stype_in=STYPE_IN,
                symbols=[SYMBOL],
            )
            with state_lock:
                state["connected"] = True
                state["last_error"] = None
            log.info("Live subscription active — listening for bars")
            backoff = 1  # reset after successful connect

            for record in client:
                bar = _record_to_bar(record)
                if bar is not None:
                    _ingest_bar(bar)

            # Iterator returning means the server closed the stream.
            log.warning("Live stream ended; will reconnect")
        except Exception as e:
            log.exception("Live thread error: %s", e)
            with state_lock:
                state["last_error"] = str(e)
        finally:
            with state_lock:
                state["connected"] = False
                state["reconnect_count"] += 1

        # Reconnect with backoff (cap at 60s).
        time_module.sleep(backoff)
        backoff = min(backoff * 2, 60)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not API_KEY:
        log.error("DATABENTO_API_KEY env var not set — service will not function")
    else:
        # Historical first (blocking, ~10s) so snapshot is meaningful
        # immediately. Then start the Live thread.
        historical_backfill()
        t = threading.Thread(target=live_thread, daemon=True, name="databento-live")
        t.start()
        log.info("Started Databento Live thread")
    yield


app = FastAPI(title="NQ Live Snapshot", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    with state_lock:
        return {
            "ok": True,
            "connected": state["connected"],
            "bar_count": state["bar_count"],
            "last_record_at": state["last_record_at"].isoformat()
                if state["last_record_at"] else None,
            "last_error": state["last_error"],
            "started_at": state["started_at"].isoformat(),
            "reconnect_count": state["reconnect_count"],
            "uptime_seconds": int(
                (datetime.now(timezone.utc) - state["started_at"]).total_seconds()
            ),
        }


@app.get("/api/live")
def api_live(response: Response) -> dict[str, Any]:
    with state_lock:
        snap = state["snapshot"]
        connected = state["connected"]
    if snap is None:
        response.status_code = 503
        return {
            "error": "no snapshot yet",
            "connected": connected,
        }
    response.headers["Cache-Control"] = "no-store"
    return snap


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "nq-live-snapshot",
        "endpoints": ["/health", "/api/live"],
        "source": "databento-live",
    }
