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
# 1-second OHLCV — tick-precise H/L, sub-second `current_price`, and the
# >150-pt kill switch on or_15min fires the instant any 1s bar pushes
# width past the threshold. Factor logic (bear_930, c930_body_top_q, etc.)
# aggregates these 1s bars into synthetic 1-min candles at compute time.
SCHEMA = "ohlcv-1s"
SYMBOL = "NQ.c.0"
STYPE_IN = "continuous"

NY_TZ = ZoneInfo("America/New_York")

# Databento OHLCV prices for GLBX.MDP3 are fixed-point integers, base 1e-9.
PRICE_SCALE = 1_000_000_000

# Session windows in ET
RTH_OPEN = (9, 30)   # today's RTH open
RTH_CLOSE = (16, 0)  # prior day's RTH close (boundary between prior RTH + overnight)
OR_CLOSE = (10, 15)  # today's opening-range close

# Bar buffer.
#   24h × 3600 sec/h = 86400 1s bars at ~100 bytes each → ~8 MB in memory.
#   Fly.io free tier is 256 MB so this is fine, and 24h is needed to keep
#   yesterday's prior_rth window in the buffer.
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

    # 15-min opening range (9:30–9:45) — used by FVGC To Opening Range H/L
    # for its kill switches (width > 150, both sides swept, direction toward
    # swept side). DISTINCT from the 45-min OR (9:30–10:15) used by the
    # Range Briefing's Q1–Q5 quintile system.
    or15_close_dt = open_dt + timedelta(minutes=15)

    prior_rth: list[dict] = []     # yesterday 9:30–16:00 ET
    overnight: list[dict] = []     # yesterday 16:00 ET → today 9:30 ET
    session_bars: list[dict] = []  # today 9:30 ET onward
    or_bars: list[dict] = []       # today 9:30–10:15 ET (45-min OR)
    or15_bars: list[dict] = []     # today 9:30–9:45 ET  (15-min OR)
    post_or15_bars: list[dict] = []  # today after 9:45 ET (used for sweep detection)

    for b in bars:
        bar_et = b["ts"].astimezone(NY_TZ)
        if bar_et >= open_dt:
            session_bars.append(b)
            if bar_et < or_close_dt:
                or_bars.append(b)
            if bar_et < or15_close_dt:
                or15_bars.append(b)
            else:
                post_or15_bars.append(b)
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
        "opening_range": None,    # 45-min OR (Range Briefing)
        "or_15min": None,         # 15-min OR (FVGC To Opening Range H/L)
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

    # Elapsed in the session — timestamp-based (was: bar-count-based, which
    # silently broke when we switched to 1s bars: 45 1m bars vs 2700 1s bars
    # for the same 45 minutes of session).
    secs_since_open = max(0, int((now_et - open_dt).total_seconds()))

    if or_bars:
        high = max(b["high"] for b in or_bars)
        low = min(b["low"] for b in or_bars)
        snap["opening_range"] = {
            "high": high,
            "low": low,
            "width": high - low,
            "bar_count": len(or_bars),
            "minutes_elapsed": min(45, secs_since_open // 60),
            "seconds_elapsed": min(45 * 60, secs_since_open),
            "complete": now_et >= or_close_dt,
        }
    elif now_et >= open_dt:
        snap["opening_range"] = {
            "high": None,
            "low": None,
            "width": 0,
            "bar_count": 0,
            "minutes_elapsed": 0,
            "seconds_elapsed": 0,
            "complete": False,
        }

    # 15-min OR — used by FVGC To Opening Range H/L kill switches.
    if or15_bars:
        h15 = max(b["high"] for b in or15_bars)
        l15 = min(b["low"]  for b in or15_bars)
        complete_15 = now_et >= or15_close_dt
        or15: dict[str, Any] = {
            "high": h15,
            "low":  l15,
            "width": h15 - l15,
            "bar_count": len(or15_bars),
            "minutes_elapsed": min(15, secs_since_open // 60),
            "seconds_elapsed": min(15 * 60, secs_since_open),
            "complete": complete_15,
            "high_swept": None,
            "low_swept":  None,
        }
        # OR-side-swept tracking: only meaningful once OR is locked at 9:45.
        # A side is "swept" if any post-9:45 bar wicked beyond the locked
        # OR boundary. Both-swept fires the kill switch; one-side-swept
        # restricts the play to the opposite direction.
        if complete_15:
            or15["high_swept"] = any(b["high"] > h15 for b in post_or15_bars)
            or15["low_swept"]  = any(b["low"]  < l15 for b in post_or15_bars)
        snap["or_15min"] = or15
    elif now_et >= open_dt:
        snap["or_15min"] = {
            "high": None, "low": None, "width": 0,
            "bar_count": 0, "minutes_elapsed": 0, "seconds_elapsed": 0,
            "complete": False,
            "high_swept": None, "low_swept": None,
        }

    # Intraday factors — machine-readable booleans the dashboard uses to
    # re-evaluate matrix-play confluence + tier live.
    snap["intraday_factors"] = _compute_intraday_factors(
        or_bars, session_bars, now_et, open_dt, or_close_dt
    )

    return snap


def _bars_in_window(bars_list: list, window_start, window_end) -> list:
    """Return bars whose ts (ET) falls in [window_start, window_end). Works
    on any bar granularity — we filter by timestamp, not by index."""
    out = []
    for b in bars_list:
        ts = b["ts"].astimezone(NY_TZ)
        if window_start <= ts < window_end:
            out.append(b)
    return out


def _synth_minute(window_bars: list) -> dict | None:
    """Aggregate a list of sub-minute OHLCV bars into a single synthetic
    1-minute candle. None if no bars present. Used to derive the "9:30
    1-min candle" factors (bear_930, c930_body_top_q, ...) when the
    underlying stream is sub-minute granularity."""
    if not window_bars:
        return None
    return {
        "open":  window_bars[0]["open"],
        "high":  max(b["high"]  for b in window_bars),
        "low":   min(b["low"]   for b in window_bars),
        "close": window_bars[-1]["close"],
        "bar_count": len(window_bars),
    }


def _compute_intraday_factors(
    or_bars: list, session_bars: list, now_et, open_dt, or_close_dt
) -> dict[str, Any]:
    """Derive bool factors from live bars. None = not yet computable; True/
    False = known. Threshold constants come from the validated insights:
      - 9:30 body top quartile: >= 23 pts
      - 9:30 range bottom quartile: <= 22 pts
      - 5-min OR bottom quartile: <= 42 pts
      - 5-min OR top quartile: >= 72 pts
      - 45-min OR tight (Q1 ~bottom 20%): <= 125 pts
      - 45-min OR wide  (Q5 ~top 20%): >= 205 pts

    Bar-size-agnostic. Aggregates sub-minute bars into synthetic 1-min
    candles for the candle-level factors; works directly on min/max across
    bars for window-range factors.
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

    one_min = timedelta(minutes=1)
    five_min = timedelta(minutes=5)
    c930_end = open_dt + one_min
    or5_end  = open_dt + five_min

    # 9:30 candle — aggregate the first full minute. Only emit factors once
    # the minute is COMPLETE (now past 9:31), otherwise mid-formation bars
    # would cause bear_930 to flicker. The conservative "wait for completion"
    # mirrors the old 1m behavior where the bar didn't appear until 9:31.
    if now_et >= c930_end:
        c930 = _synth_minute(_bars_in_window(session_bars, open_dt, c930_end))
        if c930:
            body = abs(c930["close"] - c930["open"])
            rng = c930["high"] - c930["low"]
            factors["bear_930"] = c930["close"] < c930["open"]
            factors["bull_930"] = c930["close"] > c930["open"]
            factors["c930_body_top_q"] = body >= 23
            factors["c930_range_bot_q"] = rng <= 22

    # First 5-min OR — only after 9:35 (window closed).
    if now_et >= or5_end:
        first5 = _bars_in_window(session_bars, open_dt, or5_end)
        if first5:
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


def _bulk_ingest(new_bars: list[dict[str, Any]]) -> int:
    """Append a batch of bars and recompute snapshot ONCE. Used by the
    historical backfill — calling _ingest_bar() per bar would recompute
    the snapshot on each insertion, causing O(n²) work that's fine for
    1m bars (n=1440) but ~7B ops for 1s bars (n=86400).
    """
    if not new_bars:
        return 0
    with state_lock:
        bars.extend(new_bars)
        # Sort and neighbor-dedupe in one pass.
        sorted_bars = sorted(bars, key=lambda b: b["ts"])
        deduped: list[dict[str, Any]] = []
        last_ts = None
        for b in sorted_bars:
            if last_ts is not None and b["ts"] == last_ts:
                deduped[-1] = b  # newer wins
            else:
                deduped.append(b)
                last_ts = b["ts"]
        bars.clear()
        bars.extend(deduped)
        # Trim — drop bars older than BAR_BUFFER_HOURS
        cutoff = datetime.now(timezone.utc) - timedelta(hours=BAR_BUFFER_HOURS)
        while bars and bars[0]["ts"] < cutoff:
            bars.popleft()
        state["last_record_at"] = datetime.now(timezone.utc)
        state["bar_count"] = len(bars)
        # Single snapshot recompute at end.
        state["snapshot"] = _compute_snapshot()
        return len(bars)


# How far back to backfill on startup. 8h covers most of overnight session
# from a morning start (e.g. 9 AM ET → fetches back to 1 AM ET). The full
# overnight (16:00 prior day → 9:30 today) requires 17h+; we skip the
# earlier half to keep startup fast. The morning briefing's prior_rth in
# briefing.json is the canonical source the dashboard falls back to.
BACKFILL_HOURS = 8


def historical_backfill() -> None:
    """Load recent OHLCV bars from Databento Historical so the snapshot is
    meaningful immediately on startup. Bulk-ingests in a single pass so the
    snapshot is only recomputed once, regardless of bar count."""
    log.info("Fetching historical backfill (%dh of bars, schema=%s)…",
             BACKFILL_HOURS, SCHEMA)
    try:
        client = db.Historical(key=API_KEY)
        # Historical has a publishing lag; pull until ~15 min ago to avoid
        # 422 "data_end_after_available_end" errors.
        end = datetime.now(timezone.utc) - timedelta(minutes=15)
        start = end - timedelta(hours=BACKFILL_HOURS)
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

        batch: list[dict[str, Any]] = []
        for ts_event, row in df.iterrows():
            ts = ts_event.to_pydatetime() if hasattr(ts_event, "to_pydatetime") else ts_event
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            batch.append({
                "ts": ts.astimezone(timezone.utc),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row.get("volume", 0)),
            })
        total = _bulk_ingest(batch)
        log.info("Historical backfill: ingested %d bars (buffer total %d)",
                 len(batch), total)
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
