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
import json as _json
import queue
import urllib.error
import urllib.request
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import databento as db
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

# FVGC engine — imported lazily inside the play-history compute path so a
# missing/broken pandas install can't take down the live snapshot service.
# (Live data + narratives still work without it.)
try:
    import pandas as _pd
    from fvgc.model import generate_signals as _fvgc_generate_signals
    _FVGC_AVAILABLE = True
    _FVGC_IMPORT_ERROR: str | None = None
except Exception as _fvgc_err:  # pragma: no cover — diagnostic path only
    _pd = None
    _fvgc_generate_signals = None
    _FVGC_AVAILABLE = False
    _FVGC_IMPORT_ERROR = repr(_fvgc_err)

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

# Intra-day narrative regeneration (event-driven, GPT-5 Nano).
# Fly.io watches for state transitions (OR locks; play arming via dashboard
# webhook) and refreshes the relevant narrative blocks. Cheap (~$0.01-0.05/day)
# but only useful if OPENAI_API_KEY is set and BRIEFING_URL is reachable.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-nano")
BRIEFING_URL = os.environ.get(
    "BRIEFING_URL",
    "https://phillipchan1.github.io/fvgc-ultra-backtest/briefing.json",
)
# Optional shared secret for the POST /api/narrative-trigger endpoint. If
# unset, the endpoint trusts any caller (relies on CORS to gate). Setting
# it is recommended for production.
NARRATIVE_TRIGGER_SECRET = os.environ.get("NARRATIVE_TRIGGER_SECRET")

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
    # Narrative store — keyed by event id ('or_5min_lock', 'or_15min_lock',
    # 'or_45min_lock', 'play:M1 Long:ARMED', etc). Each value: {text,
    # generated_at_utc, trigger, model}.
    "narratives": {},
    "briefing_context": None,                # cached briefing.json
    "briefing_context_fetched_at": None,     # datetime
}

# Module-level cursors for event detection. Updated by _check_narrative_events
# from inside state_lock so they're consistent with the snapshot they read.
_prev_or5_complete = False
_prev_or15_complete = False
_prev_or45_complete = False
# Background work queue for narrative generation.
_narrative_queue: "queue.Queue[dict]" = queue.Queue(maxsize=32)

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
        _check_narrative_events(state["snapshot"])


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
    # 5-min opening range (9:30–9:35) — first refinement step of the
    # stepwise OR forecast. Locks 5 minutes after open and feeds the
    # 5min→45min quintile transition matrix in briefing.json.
    or5_close_dt = open_dt + timedelta(minutes=5)

    prior_rth: list[dict] = []     # yesterday 9:30–16:00 ET
    overnight: list[dict] = []     # yesterday 16:00 ET → today 9:30 ET
    session_bars: list[dict] = []  # today 9:30 ET onward
    or_bars: list[dict] = []       # today 9:30–10:15 ET (45-min OR)
    or15_bars: list[dict] = []     # today 9:30–9:45 ET  (15-min OR)
    or5_bars: list[dict] = []      # today 9:30–9:35 ET  (5-min OR)
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
            if bar_et < or5_close_dt:
                or5_bars.append(b)
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
        "or_5min": None,          # 5-min OR (Stepwise forecast step 1)
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

    # 5-min OR — first refinement step of the stepwise OR forecast.
    # Locks at 9:35 ET. The dashboard uses width here to refine the
    # cold-start Q1–Q5 forecast via the 5→45 quintile transition matrix.
    if or5_bars:
        h5 = max(b["high"] for b in or5_bars)
        l5 = min(b["low"]  for b in or5_bars)
        snap["or_5min"] = {
            "high": h5,
            "low":  l5,
            "width": h5 - l5,
            "bar_count": len(or5_bars),
            "minutes_elapsed": min(5, secs_since_open // 60),
            "seconds_elapsed": min(5 * 60, secs_since_open),
            "complete": now_et >= or5_close_dt,
        }
    elif now_et >= open_dt:
        snap["or_5min"] = {
            "high": None, "low": None, "width": 0,
            "bar_count": 0, "minutes_elapsed": 0, "seconds_elapsed": 0,
            "complete": False,
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
# Narrative generation (event-driven AI re-narration)
# ---------------------------------------------------------------------------
# Pattern: detect state transitions (OR(5m) locked, OR(15m) locked, OR(45m)
# locked, a play armed/missed/done) → push a regen request onto
# _narrative_queue → background worker calls GPT-5 Nano → result lands in
# state["narratives"][event_id]. Dashboard polls /api/narratives every 30s
# and slots fresh narratives into the corresponding section, with a
# "✨ updated N min ago" tag.
#
# Cost budget: GPT-5 Nano @ ~$0.05 / 1M input + $0.40 / 1M output. Each
# narrative ≈ 400 in + 200 out = ~$0.0001 / call. Even with 30 events/day
# we're under a penny.


def _fetch_briefing_context() -> dict | None:
    """Pull briefing.json from GitHub Pages so the narrative generator has
    morning context. Called at startup and re-called on stale cache."""
    try:
        req = urllib.request.Request(BRIEFING_URL, headers={
            "Cache-Control": "no-cache",
            "User-Agent": "nq-live-snapshot/0.1",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
        log.info("Fetched briefing context (date=%s, narratives in sections: %d)",
                 (data.get("meta") or {}).get("date"),
                 sum(1 for k in data
                     if isinstance(data.get(k), dict)
                     and data[k].get("narrative")))
        return data
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log.warning("briefing.json fetch failed: %s", e)
        return None
    except Exception:
        log.exception("briefing.json parse failed")
        return None


def _openai_chat(prompt: str, max_tokens: int = 500, timeout: int = 60) -> str | None:
    """One-shot OpenAI chat completion. Returns the response text or None.

    Mirrors the implementation in tools/morning_briefing.py so prompt + voice
    stay consistent. urllib-only — no extra Python dep."""
    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set — narrative regen disabled")
        return None
    payload: dict[str, Any] = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": max_tokens,
    }
    if "gpt-5" in OPENAI_MODEL or OPENAI_MODEL.startswith("o1") \
            or OPENAI_MODEL.startswith("o3"):
        payload["reasoning_effort"] = "minimal"
    body = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body, method="POST",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:300]
        log.warning("OpenAI HTTP %s: %s", e.code, err)
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning("OpenAI network error: %s", e)
        return None
    try:
        out = payload["choices"][0]["message"]["content"]
        return out.strip() if out else None
    except (KeyError, IndexError, AttributeError):
        return None


def _build_narrative_prompt(event: str, snap: dict, extra: dict | None = None) -> str | None:
    """Construct the per-event prompt. Returns None if context insufficient."""
    ctx = state.get("briefing_context") or {}
    fc = ctx.get("or_forecast") or {}
    morning = fc.get("narrative") or "(no morning narrative cached)"
    sw = fc.get("stepwise") or {}
    forecast_pts = fc.get("point_pts")
    forecast_q = (fc.get("quintile") or "?").split(" ", 1)[0]

    def _q(width: float, cuts: list) -> str:
        if not cuts:
            return "?"
        for i, c in enumerate(cuts):
            if width <= c:
                return f"Q{i+1}"
        return "Q5"

    if event == "or_5min_lock":
        or5 = (snap.get("or_5min") or {})
        w = or5.get("width", 0)
        q_5 = _q(w, (sw.get("thresholds") or {}).get("or_5min") or [])
        return (
            "You are writing a 1-2 sentence intra-session update for a NQ futures "
            "trader using the FVGC model. Plain prose. No headers, no bullets, "
            "no emoji. Match the calm voice of the morning context.\n\n"
            "MORNING CONTEXT (written ~6:10 AM ET):\n"
            f"{morning}\n\n"
            "WHAT JUST HAPPENED (9:35 ET):\n"
            f"- 5-min OR locked at {w:.0f} pts ({q_5}).\n"
            f"- Cold-start forecast was {forecast_pts} pts ({forecast_q}).\n\n"
            "Write 1-2 sentences on the first stepwise refinement: how today's "
            "5-min OR compares to the morning forecast and what it implies for "
            "the 45-min OR. Don't repeat the morning context."
        )

    if event == "or_15min_lock":
        or5 = (snap.get("or_5min") or {})
        or15 = (snap.get("or_15min") or {})
        w15 = or15.get("width", 0)
        q_15 = _q(w15, (sw.get("thresholds") or {}).get("or_15min") or [])
        sweep_bits = []
        if or15.get("high_swept"): sweep_bits.append("OR.H swept")
        if or15.get("low_swept"):  sweep_bits.append("OR.L swept")
        sweep = ", ".join(sweep_bits) if sweep_bits else "neither side swept"
        return (
            "You are writing a 1-2 sentence intra-session update for a NQ futures "
            "trader using the FVGC model. Plain prose, no headers, no emoji.\n\n"
            "MORNING CONTEXT:\n"
            f"{morning}\n\n"
            "WHAT JUST HAPPENED (9:45 ET):\n"
            f"- 15-min OR locked at {w15:.0f} pts ({q_15}).\n"
            f"- 5-min OR was {or5.get('width', 0):.0f} pts.\n"
            f"- Cold-start forecast: {forecast_pts} pts ({forecast_q}).\n"
            f"- {sweep}.\n"
            f"- FVGC To OR H/L kill switches: width>150 = veto, both swept = veto.\n\n"
            "Write 1-2 sentences on what the 15-min OR tells us about today's "
            "regime + any actionable implication for FVGC To OR H/L. Concrete, "
            "no fluff."
        )

    if event == "or_45min_lock":
        or45 = (snap.get("opening_range") or {})
        w45 = or45.get("width", 0)
        q_45 = _q(w45, (sw.get("thresholds") or {}).get("or_45min") or [])
        return (
            "You are writing a 1-2 sentence intra-session update for a NQ futures "
            "trader using the FVGC model. Plain prose.\n\n"
            "MORNING CONTEXT:\n"
            f"{morning}\n\n"
            "WHAT JUST HAPPENED (10:15 ET):\n"
            f"- 45-min OR locked at {w45:.0f} pts ({q_45}).\n"
            f"- Cold-start forecast: {forecast_pts} pts ({forecast_q}).\n\n"
            "Write 1-2 sentences on the locked regime and what it means for "
            "the rest of the session — sizing, target multiples, trades to "
            "favor / skip. No bullets."
        )

    if event.startswith("play:"):
        # Format: "play:<name>:<new_state>". Dashboard POSTs these with extra
        # = {play, fired_factors, missed_factors, count, max, action}.
        parts = event.split(":", 2)
        if len(parts) < 3:
            return None
        play_name = parts[1]
        new_state = parts[2]
        extra = extra or {}
        # Look up morning narrative for this play.
        morning_play = None
        for p in (ctx.get("matrix_plays") or []):
            if p.get("name") == play_name:
                morning_play = p
                break
        morning_text = (morning_play or {}).get("narrative") or "(no morning narrative for this play)"
        fired = ", ".join(extra.get("fired_factors") or []) or "(none)"
        missed = ", ".join(extra.get("missed_factors") or []) or "(none)"
        action = extra.get("action") or ""
        return (
            "You are writing a 1-2 sentence intra-session update on a specific "
            "NQ futures play for a trader using the FVGC model.\n\n"
            f"PLAY: {play_name}\n"
            f"NEW STATE: {new_state}\n\n"
            "MORNING CONTEXT (written ~6:10 AM ET):\n"
            f"{morning_text}\n\n"
            "CURRENT STATE:\n"
            f"- Confluence count: {extra.get('count', '?')}/{extra.get('max', '?')}\n"
            f"- Fired factors: {fired}\n"
            f"- Missed factors: {missed}\n"
            f"- Recommended action: {action}\n\n"
            "Write 1-2 sentences on what just changed and exactly what to do "
            "next (size, target, kill conditions if relevant). No filler."
        )

    return None


def _narrative_worker() -> None:
    """Background worker — pulls regen requests off the queue, calls OpenAI,
    stores result in state["narratives"]. Single-threaded (one outstanding
    OpenAI call at a time) to keep cost predictable + avoid races."""
    while True:
        try:
            req = _narrative_queue.get(timeout=300)
        except queue.Empty:
            continue
        event = req.get("event", "")
        snap = req.get("snap") or {}
        extra = req.get("extra") or {}
        log.info("narrative: regenerating for event=%s", event)
        prompt = _build_narrative_prompt(event, snap, extra)
        if not prompt:
            log.info("narrative: no prompt for event=%s — skipped", event)
            continue
        text = _openai_chat(prompt)
        if not text:
            log.warning("narrative: OpenAI returned empty for event=%s", event)
            continue
        with state_lock:
            state["narratives"][event] = {
                "text": text,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "trigger": event,
                "model": OPENAI_MODEL,
            }
        log.info("narrative: stored %s (%d chars)", event, len(text))


def _check_narrative_events(snap: dict) -> None:
    """Detect OR-lock transitions and queue narrative regen.
    Called from inside state_lock by _ingest_bar/_bulk_ingest right after
    state["snapshot"] is updated. Per-play events come in via the POST
    /api/narrative-trigger endpoint — the dashboard owns the play state
    machine and pings Fly when transitions fire there."""
    global _prev_or5_complete, _prev_or15_complete, _prev_or45_complete
    or5_c  = bool((snap.get("or_5min") or {}).get("complete"))
    or15_c = bool((snap.get("or_15min") or {}).get("complete"))
    or45_c = bool((snap.get("opening_range") or {}).get("complete"))

    def _q(ev: str) -> None:
        try:
            _narrative_queue.put_nowait({"event": ev, "snap": snap})
        except queue.Full:
            log.warning("narrative queue full — dropped event %s", ev)

    if or5_c  and not _prev_or5_complete:  _q("or_5min_lock")
    if or15_c and not _prev_or15_complete: _q("or_15min_lock")
    if or45_c and not _prev_or45_complete: _q("or_45min_lock")
    _prev_or5_complete  = or5_c
    _prev_or15_complete = or15_c
    _prev_or45_complete = or45_c


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
        # Sync narrative-event cursors silently to current state so the
        # backfill doesn't trigger a spurious regen storm for OR-lock events
        # that already happened earlier today.
        global _prev_or5_complete, _prev_or15_complete, _prev_or45_complete
        snap = state["snapshot"] or {}
        _prev_or5_complete  = bool((snap.get("or_5min") or {}).get("complete"))
        _prev_or15_complete = bool((snap.get("or_15min") or {}).get("complete"))
        _prev_or45_complete = bool((snap.get("opening_range") or {}).get("complete"))
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
        # Historical has a publishing lag — for ohlcv-1s the observed lag
        # is just over 15 minutes. Pull until 20 min ago and round down to
        # the minute boundary so the `end` is always a clean timestamp the
        # historical endpoint has definitely published. Otherwise we hit
        # 422 "data_end_after_available_end".
        end = (datetime.now(timezone.utc) - timedelta(minutes=20)).replace(
            second=0, microsecond=0)
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
# Play history — retrospective view ("did the FVGC engine emit a signal?")
# ---------------------------------------------------------------------------
# Pattern: aggregate today's session bars (1s) into 30s candles → feed to
# fvgc.model.generate_signals (the canonical engine, same code the backtest
# uses) → match each emitted signal to a matrix play by direction + variant
# + window. Dashboard polls /api/play-history and shows fired/missed plays.
#
# Cached for 30s — the engine is cheap (~1k candles for a full RTH session)
# but no point recomputing more often than the bar cadence anyway.

_play_history_cache: dict | None = None
_play_history_cache_at: datetime | None = None
PLAY_HISTORY_TTL_SEC = 30


def _parse_play_window(win_str: str) -> dict | None:
    """Parse "9:30-9:45" → {'start_min': 570, 'end_min': 585}. Returns None
    on unparseable input — caller falls back to no window filter."""
    if not win_str or "-" not in win_str:
        return None
    try:
        a, b = win_str.split("-", 1)
        def _to_min(s: str) -> int:
            s = s.strip()
            h, m = s.split(":")
            return int(h) * 60 + int(m)
        return {"start_min": _to_min(a), "end_min": _to_min(b),
                "raw": win_str}
    except Exception:
        return None


# Pandas .floor() accepts shorthand strings — same vocabulary the engine
# uses. We accept the same syntax for the play's `timeframe` field.
_TF_FLOOR_MAP = {
    "30s": "30s", "30sec": "30s", "30 seconds": "30s",
    "1m":  "1min", "1min": "1min", "1 min": "1min", "1minute": "1min",
    "2m":  "2min", "2min": "2min",
    "3m":  "3min", "3min": "3min",
    "5m":  "5min", "5min": "5min",
    "15m": "15min", "15min": "15min",
    "30m": "30min", "30min": "30min",
}
DEFAULT_PLAY_TF = "30s"  # matrix plays per project memory — 8yr validated


def _normalize_tf(tf_value: Any) -> str:
    """Coerce a play.timeframe field to a pandas-friendly freq string.
    Falls back to DEFAULT_PLAY_TF for missing / unparseable values."""
    if not tf_value:
        return _TF_FLOOR_MAP[DEFAULT_PLAY_TF]
    s = str(tf_value).strip().lower()
    if s in _TF_FLOOR_MAP:
        return _TF_FLOOR_MAP[s]
    return _TF_FLOOR_MAP[DEFAULT_PLAY_TF]


def _aggregate_session_to_tf(session_bars: list[dict], freq: str) -> "Any":
    """Bucket 1s OHLCV dicts into `freq` candles in the shape fvgc expects:
    columns timestamp_utc (tz-aware UTC), timestamp_ny (tz-aware NY),
    open/high/low/close/volume.

    freq is a pandas frequency string ('30s', '1min', '2min', '5min', etc.).
    Returns None when pandas isn't available or there are no bars."""
    if _pd is None or not session_bars:
        return None
    rows = [{
        "timestamp_utc": b["ts"],
        "open": b["open"], "high": b["high"],
        "low": b["low"], "close": b["close"],
        "volume": b.get("volume", 0),
    } for b in session_bars]
    df = _pd.DataFrame(rows)
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    ts_buckets = df["timestamp_utc"].dt.floor(freq)
    agg = (
        df.groupby(ts_buckets)
        .agg(open=("open", "first"), high=("high", "max"),
             low=("low", "min"), close=("close", "last"),
             volume=("volume", "sum"))
        .reset_index()
        .rename(columns={"timestamp_utc": "timestamp_utc"})
    )
    agg["timestamp_ny"] = agg["timestamp_utc"].dt.tz_convert(NY_TZ)
    agg = agg.sort_values("timestamp_utc").reset_index(drop=True)
    return agg


def _signal_to_json(s: dict, timeframe: str = "30s") -> dict:
    """Convert a raw FVGC signal dict into a JSON-friendly + display-ready
    structure. Tagged with `timeframe` so the dashboard can disambiguate
    when multiple TFs are scanned in the same session."""
    ts = s.get("timestamp")
    ts_iso = ts.isoformat() if ts is not None else None
    ts_human = ts.strftime("%-I:%M:%S %p") if ts is not None else None
    def _num(x):
        if x in ("", None): return None
        try: return float(x)
        except (TypeError, ValueError): return None
    return {
        "timestamp_et": ts_iso,
        "time_et_human": ts_human,
        "timeframe": timeframe,
        "direction": s.get("direction"),
        "variant": s.get("variant"),
        "entry_price": _num(s.get("entry_price")),
        "sl": _num(s.get("sl")),
        "tp": _num(s.get("tp")),
        "sl_dist": _num(s.get("sl_dist")),
        "fvg_top": _num(s.get("fvg_top")),
        "fvg_bottom": _num(s.get("fvg_bottom")),
        "fvg_mid": _num(s.get("fvg_mid")),
        "fvg_direction": s.get("fvg_direction"),
        "fvg_id": s.get("fvg_id"),
    }


def _match_signal_for_play(p: dict, signals_by_tf: dict, now_min: int) -> tuple:
    """Find the first matching signal for play `p`. Returns
    (matched_signal_dict_or_None, status_str, play_tf, play_variants)."""
    win = _parse_play_window(p.get("window", ""))
    direction = p.get("direction")
    play_tf = _normalize_tf(p.get("timeframe"))
    # Required variants from post_pending IDs (e.g. variant_no_fvg).
    play_variants = [
        f.get("id", "").replace("variant_", "")
        for f in (p.get("post_pending") or [])
        if isinstance(f.get("id"), str) and f["id"].startswith("variant_")
    ]
    candidate_signals = signals_by_tf.get(play_tf, [])
    matched = None
    for s in candidate_signals:
        if direction and s["direction"] != direction:
            continue
        sig_iso = s.get("timestamp_et")
        if not sig_iso:
            continue
        try:
            sig_dt = datetime.fromisoformat(sig_iso)
        except ValueError:
            continue
        sig_min = sig_dt.hour * 60 + sig_dt.minute
        if win and (sig_min < win["start_min"] or sig_min > win["end_min"]):
            continue
        if play_variants and s.get("variant") not in play_variants:
            continue
        matched = s
        break
    # Status — window-aware. "pending" while window is still open; once it
    # closes without a matching signal, it's a definitive "no_signal".
    if p.get("veto_active"):
        status = "vetoed"
    elif matched is not None:
        status = "fired"
    elif win and now_min < win["end_min"]:
        status = "pending"
    else:
        status = "no_signal"
    return matched, status, play_tf, play_variants


def _match_signals_to_plays(signals_by_tf: dict, matrix_plays: list[dict],
                            now_et: datetime) -> list[dict]:
    """For each matrix play, find the best-matching signal in the play's
    timeframe (direction + variant + window). signals_by_tf is keyed by
    pandas freq string ('30s', '1min', etc.) — each play matches only
    against signals from its own timeframe."""
    now_min = now_et.hour * 60 + now_et.minute
    out = []
    for p in matrix_plays:
        matched, status, play_tf, play_variants = _match_signal_for_play(
            p, signals_by_tf, now_min)
        out.append({
            "name": p.get("name"),
            "window": p.get("window"),
            "direction": p.get("direction"),
            "timeframe": play_tf,
            "status": status,
            "veto_active": bool(p.get("veto_active")),
            "matched_signal": matched,
            "required_variants": play_variants,
        })
    return out


def _compute_play_history() -> dict:
    """Run the FVGC engine across every timeframe present in today's
    matrix plays and return a playbook-only retrospective.

    Multi-TF: each matrix play declares a `timeframe` (defaulting to 30s
    per the 8yr-validated memory note). We aggregate session bars to
    every unique TF and run generate_signals once per TF. Plays match
    only signals from their own TF — a 1m FVG doesn't validate a 30s
    play and vice versa.

    Filtering: we ONLY return signals that matched a playbook play.
    Raw "all FVGC signals today" was noise — the trader cares about
    playbook validation, not engine output. The total raw signal count
    is reported as `raw_signal_count` for diagnostic.

    Output shape:
      {
        "as_of_utc":         ISO timestamp,
        "session_date_et":   "2026-05-20",
        "engine_available":  bool,
        "timeframes_run":    ["30s", "1min"],
        "raw_signal_count":  int,      # total engine output across all TFs
        "signal_count":      int,      # signals matched to a play
        "signals":           [ ...playbook-matched signals (with play_name + tf)... ],
        "plays":             [ ...one entry per matrix play with status... ],
        "candle_counts":     {"30s": 590, "1min": 295},
      }
    """
    out_base: dict[str, Any] = {
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "engine_available": _FVGC_AVAILABLE,
        "timeframes_run": [],
        "signals": [],
        "plays": [],
        "signal_count": 0,
        "raw_signal_count": 0,
        "candle_counts": {},
    }
    if not _FVGC_AVAILABLE:
        out_base["error"] = f"fvgc engine import failed: {_FVGC_IMPORT_ERROR}"
        return out_base

    with state_lock:
        all_bars = list(bars)
        ctx = state.get("briefing_context")

    if not all_bars:
        out_base["error"] = "no bars in buffer yet"
        return out_base

    # Today's session = bars from 9:30 ET onward.
    now_et = datetime.now(NY_TZ)
    open_dt = now_et.replace(hour=RTH_OPEN[0], minute=RTH_OPEN[1],
                             second=0, microsecond=0)
    session_bars = [b for b in all_bars
                    if b["ts"].astimezone(NY_TZ) >= open_dt]
    out_base["session_date_et"] = open_dt.strftime("%Y-%m-%d")

    if not session_bars:
        out_base["note"] = "session hasn't started yet"
        return out_base

    matrix_plays = (ctx or {}).get("matrix_plays") or []
    if not matrix_plays:
        out_base["error"] = "no matrix plays in briefing context"
        return out_base

    # Discover every TF that any play needs. Default fall-through is 30s.
    play_tfs = {_normalize_tf(p.get("timeframe")) for p in matrix_plays}
    out_base["timeframes_run"] = sorted(play_tfs)

    # Run engine once per TF. Cache results by TF for play matching below.
    signals_by_tf: dict[str, list] = {}
    candle_counts: dict[str, int] = {}
    for tf in play_tfs:
        df = _aggregate_session_to_tf(session_bars, tf)
        if df is None or df.empty:
            signals_by_tf[tf] = []
            continue
        try:
            sigs_raw, _fvgs = _fvgc_generate_signals(df)
        except Exception as e:
            log.exception("FVGC signal generation failed for tf=%s", tf)
            out_base.setdefault("warnings", []).append(
                f"engine error tf={tf}: {e}")
            signals_by_tf[tf] = []
            continue
        signals_by_tf[tf] = [_signal_to_json(s, timeframe=tf) for s in sigs_raw]
        candle_counts[tf] = int(len(df))

    raw_count = sum(len(v) for v in signals_by_tf.values())
    plays_matched = _match_signals_to_plays(signals_by_tf, matrix_plays, now_et)

    # Filtered signal list — only the ones that validated at least one
    # playbook play. Each signal gets a `play_names` array showing which
    # plays it lit up (a single signal can validate multiple plays).
    sig_to_plays: dict[tuple, list[str]] = {}
    for p in plays_matched:
        m = p.get("matched_signal")
        if not m:
            continue
        key = (m.get("timestamp_et"), m.get("timeframe"), m.get("direction"),
               m.get("variant"))
        sig_to_plays.setdefault(key, []).append(p["name"])
    playbook_signals = []
    seen_keys = set()
    for p in plays_matched:
        m = p.get("matched_signal")
        if not m:
            continue
        key = (m.get("timestamp_et"), m.get("timeframe"), m.get("direction"),
               m.get("variant"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        playbook_signals.append({**m, "play_names": sig_to_plays[key]})
    # Chronological order.
    playbook_signals.sort(key=lambda s: s.get("timestamp_et") or "")

    out_base.update({
        "signals": playbook_signals,
        "signal_count": len(playbook_signals),
        "raw_signal_count": raw_count,
        "plays": plays_matched,
        "candle_counts": candle_counts,
    })
    return out_base


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

    # Briefing context (matrix_plays definitions, morning narratives) —
    # always fetch, even without OPENAI_API_KEY. Used by:
    #   - narrative worker (when key is set) for prompt context
    #   - play-history endpoint to match FVGC signals to matrix plays
    ctx = _fetch_briefing_context()
    if ctx:
        with state_lock:
            state["briefing_context"] = ctx
            state["briefing_context_fetched_at"] = datetime.now(timezone.utc)
    else:
        log.info("briefing context unavailable — play-history will lack play matches")

    if OPENAI_API_KEY:
        nt = threading.Thread(target=_narrative_worker, daemon=True,
                              name="narrative-worker")
        nt.start()
        log.info("Started narrative worker (model=%s)", OPENAI_MODEL)
    else:
        log.info("OPENAI_API_KEY not set — intraday narrative regen disabled")
    yield


app = FastAPI(title="NQ Live Snapshot", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
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


@app.get("/api/narratives")
def api_narratives(response: Response) -> dict[str, Any]:
    """Return the current narrative store. Dashboard polls this every 30s
    and slots fresh narratives into the matching DOM blocks."""
    with state_lock:
        # Shallow copy so the response is decoupled from future mutations.
        narrs = dict(state["narratives"])
        ctx_at = state.get("briefing_context_fetched_at")
        has_key = bool(OPENAI_API_KEY)
    response.headers["Cache-Control"] = "no-store"
    return {
        "narratives": narrs,
        "enabled": has_key,
        "briefing_context_fetched_at_utc":
            ctx_at.isoformat() if ctx_at else None,
        "model": OPENAI_MODEL,
    }


@app.post("/api/narrative-trigger")
async def api_narrative_trigger(req: Request) -> dict[str, Any]:
    """Dashboard pings here when it detects a play state transition
    (WAIT→LIVE / LIVE→ARMED / →MISSED / →DONE). Fly enqueues a regen.

    Expected JSON body:
      {
        "event": "play:M1 Long:ARMED",
        "extra": {
          "count": 4, "max": 4,
          "fired_factors": ["no_pre_rth_news", "prior_day_mid", "dow_wednesday", "variant_no_fvg"],
          "missed_factors": [],
          "action": "TAKE full size, BE@1R -> 3R fixed"
        }
      }
    """
    # Optional shared-secret gate.
    if NARRATIVE_TRIGGER_SECRET:
        if req.headers.get("X-Trigger-Secret") != NARRATIVE_TRIGGER_SECRET:
            return {"error": "unauthorized"}

    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid json"}

    event = (body or {}).get("event")
    if not event or not isinstance(event, str):
        return {"error": "missing event"}
    extra = (body or {}).get("extra") or {}

    # Idempotency: don't re-regen if we already have a fresh narrative for
    # this exact event. Same-day same-state = same story.
    with state_lock:
        existing = state["narratives"].get(event)
    if existing:
        return {"ok": True, "status": "already_generated",
                "generated_at_utc": existing.get("generated_at_utc")}

    # Refresh briefing context if it's stale (>4h) — covers the case where
    # the morning cron published a new briefing after Fly already started.
    with state_lock:
        ctx_at = state.get("briefing_context_fetched_at")
    if ctx_at is None or (datetime.now(timezone.utc) - ctx_at) > timedelta(hours=4):
        ctx = _fetch_briefing_context()
        if ctx:
            with state_lock:
                state["briefing_context"] = ctx
                state["briefing_context_fetched_at"] = datetime.now(timezone.utc)

    # Take a current snapshot to include in the prompt.
    with state_lock:
        snap = state.get("snapshot") or {}

    try:
        _narrative_queue.put_nowait({"event": event, "snap": snap, "extra": extra})
    except queue.Full:
        return {"error": "queue full"}
    return {"ok": True, "status": "queued", "event": event}


@app.get("/api/play-history")
def api_play_history(response: Response) -> dict[str, Any]:
    """Today's playbook retrospective: which FVGC signals fired, which
    plays they validated, which plays didn't get a signal in their window.

    Cached for PLAY_HISTORY_TTL_SEC since bar cadence is 30s — recomputing
    more often is wasted work."""
    global _play_history_cache, _play_history_cache_at
    now = datetime.now(timezone.utc)
    if (_play_history_cache_at is not None and _play_history_cache is not None
            and (now - _play_history_cache_at).total_seconds() < PLAY_HISTORY_TTL_SEC):
        response.headers["Cache-Control"] = "no-store"
        return {**_play_history_cache, "from_cache": True}
    result = _compute_play_history()
    _play_history_cache = result
    _play_history_cache_at = now
    response.headers["Cache-Control"] = "no-store"
    return result


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "nq-live-snapshot",
        "endpoints": [
            "/health", "/api/live", "/api/narratives",
            "/api/narrative-trigger", "/api/play-history",
        ],
        "source": "databento-live",
        "fvgc_engine": _FVGC_AVAILABLE,
    }
