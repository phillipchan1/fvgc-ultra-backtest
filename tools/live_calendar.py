"""Live economic calendar from Forex Factory weekly feed.

Replaces the static `data/raw/market_high_volume_events_*.csv`. The free
public XML at nfs.faireconomy.media is updated continuously by Forex
Factory and covers the current ISO week (`thisweek`), with companion
`lastweek` / `nextweek` feeds available.

Returns event dicts with date/time/country/impact/title. Helpers wrap
the FVGC-specific questions: red-folder for the day, FOMC week, pre-RTH
news.
"""

from __future__ import annotations

import os
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Iterable

try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo('America/New_York')
except ImportError:
    import pytz
    NY_TZ = pytz.timezone('America/New_York')

FF_BASE = 'https://nfs.faireconomy.media'
FF_URLS = {
    'lastweek': f'{FF_BASE}/ff_calendar_lastweek.xml',
    'thisweek': f'{FF_BASE}/ff_calendar_thisweek.xml',
    'nextweek': f'{FF_BASE}/ff_calendar_nextweek.xml',
}
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/121.0.0.0 Safari/537.36')
CACHE_DIR = Path(tempfile.gettempdir()) / 'fvgc_ff_cache'
CACHE_TTL_SEC = 3600  # 1 hour — calendar updates ~daily anyway

IMPACT_ORDER = {'Holiday': 0, 'Low': 1, 'Medium': 2, 'High': 3}


class CalendarError(RuntimeError):
    pass


@dataclass
class CalendarEvent:
    date: date
    time_et: datetime | None        # localized ET datetime, or None for all-day / tentative
    country: str                    # 'USD', 'EUR', etc.
    impact: str                     # 'Holiday' | 'Low' | 'Medium' | 'High'
    title: str
    url: str = ''

    def to_briefing_row(self) -> dict:
        return {
            'date': self.date.isoformat(),
            'event_type': self._event_type(),
            'event': self.title,
            'time_et': self.time_et.strftime('%H:%M') if self.time_et else '',
            'impact': self.impact,
        }

    def _event_type(self) -> str:
        """Short label compatible with the legacy events CSV."""
        title = self.title
        if 'FOMC' in title:
            return 'FOMC Statement' if 'Statement' in title else 'FOMC ' + title.split('FOMC', 1)[-1].strip()
        if 'Non-Farm' in title or 'Non‑Farm' in title or title.startswith('NFP'):
            return 'NFP'
        if 'CPI' in title:
            return 'CPI'
        if 'PPI' in title:
            return 'PPI'
        if 'Retail Sales' in title:
            return 'Retail Sales'
        if 'Triple Witching' in title or 'Quadruple Witching' in title:
            return 'Triple/Quadruple Witching'
        return 'Other'


# ----------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------

def _cache_path(url: str) -> Path:
    safe = url.rsplit('/', 1)[-1]
    return CACHE_DIR / safe


def _read_cache(url: str, max_age_sec: int = CACHE_TTL_SEC) -> str | None:
    p = _cache_path(url)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > max_age_sec:
        return None
    try:
        return p.read_text(encoding='utf-8')
    except OSError:
        return None


def _write_cache(url: str, body: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(url).write_text(body, encoding='utf-8')
    except OSError:
        pass


def _fetch_xml(url: str, timeout: float = 10.0) -> str:
    """Fetch with a small disk cache to avoid 429s on rapid reruns.

    Cache TTL is 1h. On HTTP 429 (rate limited), fall back to any stale
    cache rather than failing — the calendar barely changes minute-to-minute.
    """
    cached = _read_cache(url)
    if cached is not None:
        return cached
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode('windows-1252')
            _write_cache(url, body)
            return body
    except urllib.error.HTTPError as e:
        if e.code == 429:
            stale = _read_cache(url, max_age_sec=86400 * 7)  # 1 week stale ok
            if stale is not None:
                return stale
        raise CalendarError(f'Forex Factory fetch failed ({url}): {e}') from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        stale = _read_cache(url, max_age_sec=86400 * 7)
        if stale is not None:
            return stale
        raise CalendarError(f'Forex Factory fetch failed ({url}): {e}') from e


def _parse_xml(body: str) -> list[CalendarEvent]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise CalendarError(f'Forex Factory XML parse failed: {e}') from e
    out: list[CalendarEvent] = []
    for ev in root.findall('event'):
        d_str = (ev.findtext('date') or '').strip()
        t_str = (ev.findtext('time') or '').strip()
        country = (ev.findtext('country') or '').strip()
        impact = (ev.findtext('impact') or '').strip()
        title = (ev.findtext('title') or '').strip()
        url = (ev.findtext('url') or '').strip()
        try:
            d = datetime.strptime(d_str, '%m-%d-%Y').date()
        except ValueError:
            continue
        et_dt: datetime | None = None
        t_clean = t_str.lower().replace(' ', '')
        if t_clean and t_clean not in ('allday', 'tentative', 'tba'):
            try:
                t = datetime.strptime(t_clean, '%I:%M%p').time()
                et_dt = datetime.combine(d, t, tzinfo=NY_TZ)
            except ValueError:
                et_dt = None
        out.append(CalendarEvent(
            date=d, time_et=et_dt, country=country,
            impact=impact, title=title, url=url,
        ))
    return out


def fetch_week(which: str = 'thisweek') -> list[CalendarEvent]:
    if which not in FF_URLS:
        raise ValueError(f'unknown week: {which}')
    return _parse_xml(_fetch_xml(FF_URLS[which]))


def fetch_for_target(target_date: date) -> list[CalendarEvent]:
    """Fetch enough weeks to cover `target_date` plus a few-day buffer.

    Default to thisweek. If the target date isn't covered (e.g. running on
    Sunday for next-Monday), retries with nextweek. If still missing, falls
    back to lastweek (rare — running for last Friday).
    """
    today = datetime.now(tz=NY_TZ).date()
    delta = (target_date - today).days
    weeks: list[str] = ['thisweek']
    if delta >= 5:
        weeks.append('nextweek')
    if delta <= -5:
        weeks.append('lastweek')
    events: list[CalendarEvent] = []
    last_err: Exception | None = None
    for w in weeks:
        try:
            events.extend(fetch_week(w))
        except CalendarError as e:
            last_err = e
    if not events and last_err is not None:
        raise last_err
    return events


# ----------------------------------------------------------------------
# Filters / questions
# ----------------------------------------------------------------------

def filter_us_high(events: Iterable[CalendarEvent], target_date: date,
                   min_impact: str = 'High') -> list[CalendarEvent]:
    """USD events on target_date at or above min_impact.

    Note: Forex Factory marks NFP/CPI/PPI as 'High'. Witching / OPEX is
    typically a 'Medium' or no-impact tag. Use min_impact='Medium' to
    include those if needed.
    """
    threshold = IMPACT_ORDER.get(min_impact, 3)
    return [
        e for e in events
        if e.date == target_date
        and e.country == 'USD'
        and IMPACT_ORDER.get(e.impact, 0) >= threshold
    ]


_FOMC_DECISION_KEYWORDS = ('FOMC Statement', 'Federal Funds Rate', 'FOMC Economic Projections', 'FOMC Press Conference')

def is_fomc_week(events: Iterable[CalendarEvent], target_date: date) -> bool:
    ty, tw, _ = target_date.isocalendar()
    for e in events:
        if e.country != 'USD':
            continue
        if not any(kw in e.title for kw in _FOMC_DECISION_KEYWORDS):
            continue
        ey, ew, _ = e.date.isocalendar()
        if ey == ty and ew == tw:
            return True
    return False


def is_pre_rth_news(events: Iterable[CalendarEvent], target_date: date) -> bool:
    """Any High-impact USD event scheduled before 10:00 ET on target_date."""
    cutoff = datetime.combine(target_date, dtime(10, 0), tzinfo=NY_TZ)
    for e in filter_us_high(events, target_date):
        if e.time_et is not None and e.time_et < cutoff:
            return True
    return False
