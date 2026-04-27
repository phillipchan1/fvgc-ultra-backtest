#!/usr/bin/env python3
"""
Live market data helper for the morning briefing.

Pulls 1-minute NQ futures bars from the public Yahoo Finance v8/chart
endpoint (no auth, no extra pip deps — stdlib urllib only) and derives
the pre-open session context needed by tools/morning_briefing.py:

  - prior day RTH OHLC
  - overnight H / L / range / direction (prior day 18:00 → today 09:29 ET)
  - asia / london / 6am session H-L
  - current pre-open price and gap vs prior RTH close
  - unfilled 15-minute and 1-hour FVGs on today's and prior day's data

Design notes:
  - We use NQ=F on Yahoo for the continuous front-month NQ contract.
  - The Yahoo chart endpoint returns up to ~2 days of 1-min bars, which
    comfortably spans the overnight window we need.
  - If the network call fails (offline, rate limited, Yahoo hiccup) we
    raise LiveDataError so the caller can fall back to CLI overrides or
    the local trading_days.csv / raw 1m CSV.
"""

from __future__ import annotations

import json
import math
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo('America/New_York')
    UTC_TZ = ZoneInfo('UTC')
except ImportError:                                    # pragma: no cover
    import pytz
    NY_TZ = pytz.timezone('America/New_York')
    UTC_TZ = pytz.UTC


YAHOO_CHART_URL = (
    'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
    '?range={range_}&interval={interval}&includePrePost=true'
)
YAHOO_UA = 'Mozilla/5.0 (morning-briefing/1.0)'

RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)
OVERNIGHT_START = dtime(18, 0)
ASIA_START = dtime(19, 0)
ASIA_END = dtime(2, 0)
LONDON_START = dtime(2, 0)
LONDON_END = dtime(8, 0)
SIXAM_START = dtime(4, 0)
SIXAM_END = dtime(8, 0)


class LiveDataError(RuntimeError):
    pass


# ======================================================================
# Fetch
# ======================================================================

def fetch_yahoo_1m(symbol: str = 'NQ=F',
                   range_: str = '2d',
                   interval: str = '1m',
                   timeout: float = 10.0) -> list[dict]:
    """Return a list of {ts_ny, open, high, low, close, volume} dicts.

    Stdlib only — urllib + json. Raises LiveDataError on any failure.
    """
    url = YAHOO_CHART_URL.format(symbol=symbol, range_=range_, interval=interval)
    req = urllib.request.Request(url, headers={'User-Agent': YAHOO_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise LiveDataError(f'Yahoo fetch failed: {e}') from e

    try:
        result = payload['chart']['result'][0]
    except (KeyError, IndexError, TypeError) as e:
        err = (payload or {}).get('chart', {}).get('error')
        raise LiveDataError(f'Yahoo returned no result: {err or e}') from e

    timestamps = result.get('timestamp') or []
    q = (result.get('indicators', {}).get('quote') or [{}])[0]
    opens = q.get('open') or []
    highs = q.get('high') or []
    lows = q.get('low') or []
    closes = q.get('close') or []
    vols = q.get('volume') or []

    bars = []
    for i, ts in enumerate(timestamps):
        o, h, l, c = (
            opens[i] if i < len(opens) else None,
            highs[i] if i < len(highs) else None,
            lows[i] if i < len(lows) else None,
            closes[i] if i < len(closes) else None,
        )
        if None in (o, h, l, c) or any(map(_is_nan, (o, h, l, c))):
            continue
        bars.append({
            'ts_ny': datetime.fromtimestamp(ts, tz=UTC_TZ).astimezone(NY_TZ),
            'open': float(o),
            'high': float(h),
            'low': float(l),
            'close': float(c),
            'volume': float(vols[i]) if i < len(vols) and vols[i] is not None else 0.0,
        })

    if not bars:
        raise LiveDataError('Yahoo returned empty bar series')
    return bars


def _is_nan(x) -> bool:
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return False


# ======================================================================
# Context derivation
# ======================================================================

@dataclass
class SessionContext:
    asof: datetime
    symbol: str
    prior_rth_date: date | None = None
    prior_rth_open: float | None = None
    prior_rth_high: float | None = None
    prior_rth_low: float | None = None
    prior_rth_close: float | None = None
    prior_day_close_position: float | None = None   # 0..1 within prior RTH range

    overnight_high: float | None = None
    overnight_low: float | None = None
    overnight_range: float | None = None
    overnight_direction: str | None = None            # 'up' / 'down' / 'flat'

    asia_high: float | None = None
    asia_low: float | None = None
    london_high: float | None = None
    london_low: float | None = None
    sixam_high: float | None = None
    sixam_low: float | None = None

    current_price: float | None = None
    current_ts: datetime | None = None
    gap_pts: float | None = None
    gap_pct: float | None = None

    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: (v.isoformat() if hasattr(v, 'isoformat') else v)
                for k, v in self.__dict__.items() if k != 'notes'}


def _slice(bars: list[dict], start_ny: datetime, end_ny: datetime) -> list[dict]:
    return [b for b in bars if start_ny <= b['ts_ny'] < end_ny]


def _extrema(bars: list[dict]) -> tuple[float | None, float | None]:
    if not bars:
        return None, None
    return max(b['high'] for b in bars), min(b['low'] for b in bars)


def derive_session_context(bars: list[dict],
                           asof_ny: datetime,
                           symbol: str = 'NQ=F') -> SessionContext:
    """Derive the pre-open context from a list of 1m bars.

    `asof_ny` is the reference moment (NY time) — usually "now" or the
    briefing target date at 09:15 ET. All session windows are computed
    relative to that.
    """
    ctx = SessionContext(asof=asof_ny, symbol=symbol)

    today = asof_ny.date()

    # --- Prior RTH (find the most recent weekday strictly before today
    # that has any bars within 9:30–16:00) ---
    prior = None
    for back in range(1, 10):
        candidate = today - timedelta(days=back)
        start = datetime.combine(candidate, RTH_START, tzinfo=NY_TZ)
        end = datetime.combine(candidate, RTH_END, tzinfo=NY_TZ)
        rth = _slice(bars, start, end)
        if rth:
            prior = (candidate, rth)
            break
    if prior is not None:
        pd_date, pd_bars = prior
        ctx.prior_rth_date = pd_date
        ctx.prior_rth_open = pd_bars[0]['open']
        ctx.prior_rth_close = pd_bars[-1]['close']
        ctx.prior_rth_high, ctx.prior_rth_low = _extrema(pd_bars)
        denom = (ctx.prior_rth_high or 0) - (ctx.prior_rth_low or 0)
        if denom > 0:
            ctx.prior_day_close_position = (
                (ctx.prior_rth_close - ctx.prior_rth_low) / denom
            )
    else:
        ctx.notes.append('prior RTH bars not found in live feed')

    # --- Overnight: prior day 18:00 → today 09:29:59 ---
    if ctx.prior_rth_date is not None:
        on_start = datetime.combine(ctx.prior_rth_date, OVERNIGHT_START, tzinfo=NY_TZ)
        on_end = datetime.combine(today, RTH_START, tzinfo=NY_TZ)
        on_bars = _slice(bars, on_start, on_end)
        if on_bars:
            ctx.overnight_high, ctx.overnight_low = _extrema(on_bars)
            ctx.overnight_range = ctx.overnight_high - ctx.overnight_low
            on_open = on_bars[0]['open']
            on_close = on_bars[-1]['close']
            pct = (on_close - on_open) / on_open * 100 if on_open else 0.0
            if pct > 0.1:
                ctx.overnight_direction = 'up'
            elif pct < -0.1:
                ctx.overnight_direction = 'down'
            else:
                ctx.overnight_direction = 'flat'
        else:
            ctx.notes.append('overnight window empty in live feed')

        # Asia (prior 19:00 → today 02:00)
        ah, al = _extrema(_slice(
            bars,
            datetime.combine(ctx.prior_rth_date, ASIA_START, tzinfo=NY_TZ),
            datetime.combine(today, ASIA_END, tzinfo=NY_TZ),
        ))
        ctx.asia_high, ctx.asia_low = ah, al

        # London (today 02:00 → 08:00)
        lh, ll = _extrema(_slice(
            bars,
            datetime.combine(today, LONDON_START, tzinfo=NY_TZ),
            datetime.combine(today, LONDON_END, tzinfo=NY_TZ),
        ))
        ctx.london_high, ctx.london_low = lh, ll

        # 6am window (today 04:00 → 08:00)
        sh, sl = _extrema(_slice(
            bars,
            datetime.combine(today, SIXAM_START, tzinfo=NY_TZ),
            datetime.combine(today, SIXAM_END, tzinfo=NY_TZ),
        ))
        ctx.sixam_high, ctx.sixam_low = sh, sl

    # --- Current pre-open price (latest bar strictly before 9:30 or asof) ---
    cutoff = min(
        asof_ny,
        datetime.combine(today, RTH_START, tzinfo=NY_TZ),
    )
    pre = [b for b in bars if b['ts_ny'] < cutoff]
    if pre:
        latest = pre[-1]
        ctx.current_price = latest['close']
        ctx.current_ts = latest['ts_ny']
        if ctx.prior_rth_close is not None:
            ctx.gap_pts = ctx.current_price - ctx.prior_rth_close
            ctx.gap_pct = ctx.gap_pts / ctx.prior_rth_close * 100

    return ctx


# ======================================================================
# Live unfilled FVG detection on higher timeframes
# ======================================================================

@dataclass
class UnfilledFVG:
    timeframe: str                 # '15m', '1H', '4H'
    direction: str                 # 'bullish' / 'bearish'
    created_ts: datetime
    top: float
    bottom: float
    size: float
    near_edge: float               # the price the edge is approached from
    distance_pts: float | None = None   # vs current price, signed (+ above, - below)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2


def resample_to_tf(bars: list[dict], minutes: int) -> list[dict]:
    """Bucket 1m bars into fixed-minute candles aligned to wall clock."""
    if not bars:
        return []
    buckets: dict[datetime, dict] = {}
    for b in bars:
        ts = b['ts_ny']
        # Align to minutes-of-day boundary
        mins = ts.hour * 60 + ts.minute
        bucket_minute = (mins // minutes) * minutes
        key = ts.replace(hour=bucket_minute // 60,
                         minute=bucket_minute % 60,
                         second=0, microsecond=0)
        rec = buckets.get(key)
        if rec is None:
            buckets[key] = {
                'ts_ny': key,
                'open': b['open'],
                'high': b['high'],
                'low': b['low'],
                'close': b['close'],
                'volume': b['volume'],
            }
        else:
            rec['high'] = max(rec['high'], b['high'])
            rec['low'] = min(rec['low'], b['low'])
            rec['close'] = b['close']
            rec['volume'] += b['volume']
    return sorted(buckets.values(), key=lambda r: r['ts_ny'])


def find_unfilled_fvgs(bars: list[dict],
                       tf_minutes: int,
                       min_size: float = 3.0,
                       current_price: float | None = None) -> list[UnfilledFVG]:
    """Detect 3-candle FVGs on `tf_minutes` candles and keep the ones that
    haven't been wicked into (near-edge mitigation) by any later candle.
    """
    tf_bars = resample_to_tf(bars, tf_minutes)
    if len(tf_bars) < 3:
        return []

    label = _tf_label(tf_minutes)
    fvgs: list[UnfilledFVG] = []

    for i in range(2, len(tf_bars)):
        c1, c2, c3 = tf_bars[i - 2], tf_bars[i - 1], tf_bars[i]

        # Bullish FVG: c1.high < c3.low
        if c1['high'] < c3['low']:
            top = c3['low']
            bottom = c1['high']
            if top - bottom >= min_size:
                mitigated = False
                for later in tf_bars[i + 1:]:
                    if later['low'] <= top:           # wick-in from above
                        mitigated = True
                        break
                if not mitigated:
                    fvgs.append(UnfilledFVG(
                        timeframe=label,
                        direction='bullish',
                        created_ts=c3['ts_ny'],
                        top=top,
                        bottom=bottom,
                        size=top - bottom,
                        near_edge=top,
                    ))

        # Bearish FVG: c1.low > c3.high
        if c1['low'] > c3['high']:
            top = c1['low']
            bottom = c3['high']
            if top - bottom >= min_size:
                mitigated = False
                for later in tf_bars[i + 1:]:
                    if later['high'] >= bottom:       # wick-in from below
                        mitigated = True
                        break
                if not mitigated:
                    fvgs.append(UnfilledFVG(
                        timeframe=label,
                        direction='bearish',
                        created_ts=c3['ts_ny'],
                        top=top,
                        bottom=bottom,
                        size=top - bottom,
                        near_edge=bottom,
                    ))

    if current_price is not None:
        for f in fvgs:
            f.distance_pts = f.near_edge - current_price

    return fvgs


def _tf_label(minutes: int) -> str:
    if minutes % 60 == 0:
        return f'{minutes // 60}H'
    return f'{minutes}m'


# ======================================================================
# Daily RTH H/L from intraday bars
# ======================================================================

def fetch_rth_daily_ranges(symbol: str = 'NQ=F',
                           range_: str = '60d',
                           interval: str = '5m') -> list[dict]:
    """Return one record per RTH day with high/low/range/close.

    Aggregates 5-minute Yahoo bars filtered to 9:30–16:00 ET. Skips today's
    incomplete session. Used by the OR predictor to live-compute ATR_N,
    NR4/7, pdr_pctile_20d when trading_days.csv is stale.
    """
    bars = fetch_yahoo_1m(symbol=symbol, range_=range_, interval=interval)
    by_date: dict[date, dict] = {}
    for b in bars:
        ts = b['ts_ny']
        t = ts.time()
        if t < RTH_START or t >= RTH_END:
            continue
        d = ts.date()
        rec = by_date.get(d)
        if rec is None:
            by_date[d] = {
                'date': d,
                'high': b['high'],
                'low': b['low'],
                'close': b['close'],
                'last_ts': ts,
            }
        else:
            rec['high'] = max(rec['high'], b['high'])
            rec['low'] = min(rec['low'], b['low'])
            if ts > rec['last_ts']:
                rec['close'] = b['close']
                rec['last_ts'] = ts
    out = []
    for d in sorted(by_date):
        r = by_date[d]
        out.append({
            'date': d,
            'high': r['high'],
            'low': r['low'],
            'close': r['close'],
            'range': r['high'] - r['low'],
        })
    return out
