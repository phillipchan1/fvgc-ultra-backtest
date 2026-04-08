"""
Single source of truth for level types used by builders, enrichment, and studies.
Do not hard-code level names elsewhere — import from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal, Optional

BuilderId = Literal['build_session_levels', 'build_htf_fvgs']
Side = Literal['resistance', 'support', 'both']
Timeframe = Literal['15m', '1H', '4H', 'Daily']


@dataclass(frozen=True)
class LevelDef:
    name: str
    group: str
    side: Side
    available_time: str  # "open" or "HH:MM"
    builder: BuilderId
    timeframe: Optional[Timeframe] = None


def _session(
    name: str,
    group: str,
    side: Side,
    available_time: str,
) -> LevelDef:
    return LevelDef(
        name=name,
        group=group,
        side=side,
        available_time=available_time,
        builder='build_session_levels',
        timeframe=None,
    )


def _htf(name: str, group: str, side: Side, tf: Timeframe) -> LevelDef:
    return LevelDef(
        name=name,
        group=group,
        side=side,
        available_time='open',
        builder='build_htf_fvgs',
        timeframe=tf,
    )


LEVEL_REGISTRY: tuple[LevelDef, ...] = (
    _session('prev_day_high', 'prev_day', 'resistance', 'open'),
    _session('prev_day_low', 'prev_day', 'support', 'open'),
    _session('london_high', 'london', 'resistance', 'open'),
    _session('london_low', 'london', 'support', 'open'),
    _session('asia_high', 'asia', 'resistance', 'open'),
    _session('asia_low', 'asia', 'support', 'open'),
    _session('overnight_high', 'overnight', 'resistance', 'open'),
    _session('overnight_low', 'overnight', 'support', 'open'),
    _session('6am_high', '6am', 'resistance', 'open'),
    _session('6am_low', '6am', 'support', 'open'),
    _session('nwog_high', 'nwog', 'resistance', 'open'),
    _session('nwog_low', 'nwog', 'support', 'open'),
    _session('bsl_level', 'bsl_ssl', 'resistance', 'open'),
    _session('ssl_level', 'bsl_ssl', 'support', 'open'),
    _session('or_high', 'opening_range', 'both', '09:45'),
    _session('or_low', 'opening_range', 'both', '09:45'),
    # HTF: template names; liquidity_levels.csv rows use htf_fvg_{tf}_{dir}_{created_idx} per instance.
    _htf('htf_fvg_15m_bullish', 'htf_fvg_15m', 'support', '15m'),
    _htf('htf_fvg_15m_bearish', 'htf_fvg_15m', 'resistance', '15m'),
    _htf('htf_fvg_1H_bullish', 'htf_fvg_1H', 'support', '1H'),
    _htf('htf_fvg_1H_bearish', 'htf_fvg_1H', 'resistance', '1H'),
    _htf('htf_fvg_4H_bullish', 'htf_fvg_4H', 'support', '4H'),
    _htf('htf_fvg_4H_bearish', 'htf_fvg_4H', 'resistance', '4H'),
    _htf('htf_fvg_Daily_bullish', 'htf_fvg_Daily', 'support', 'Daily'),
    _htf('htf_fvg_Daily_bearish', 'htf_fvg_Daily', 'resistance', 'Daily'),
)


def iter_registry() -> Iterator[LevelDef]:
    yield from LEVEL_REGISTRY


def groups_in_order() -> list[str]:
    seen: list[str] = []
    for e in LEVEL_REGISTRY:
        if e.group not in seen:
            seen.append(e.group)
    return seen


def session_level_names() -> frozenset[str]:
    return frozenset(e.name for e in LEVEL_REGISTRY if e.builder == 'build_session_levels')


def htf_registry_rows() -> tuple[LevelDef, ...]:
    return tuple(e for e in LEVEL_REGISTRY if e.builder == 'build_htf_fvgs')


def htf_timeframe_direction_to_name(timeframe: str, direction: str) -> Optional[str]:
    """Template name pattern (actual CSV rows append _{created_idx})."""
    d = direction.lower()
    if d not in ('bullish', 'bearish'):
        return None
    return f'htf_fvg_{timeframe}_{d}'
