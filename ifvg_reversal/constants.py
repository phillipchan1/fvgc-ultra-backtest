"""Tunable parameters for the IFVG Reversal model.

Spec: ifvg_reversal/SPEC.md (v0.3.1). Each constant references the §-section that
defines it. Do not import fvgc.constants here; if something genuinely belongs to
both models, extract it to a shared module first.
"""

import pytz
from datetime import time as dtime

NY_TZ = pytz.timezone('America/New_York')

# §2.1 v0.3.0 — killzone, locked
TRADING_WINDOW_START = dtime(9, 30)
TRADING_WINDOW_END = dtime(11, 0)

# §6.1 v0.3.0 — multi-TF target-gap scan (Tempo: "only consider 30s, 1m, 2m, 3m IFVGs")
TARGET_GAP_TIMEFRAMES = ('30s', '1min', '2min', '3min')

# §6.2 v0.3.0 — FVG size filter (NQ points). Tempo: "ideally 8-15 pts; under 8 = no conviction"
MIN_FVG_SIZE = 8.0
IDEAL_FVG_SIZE_MIN = 8.0
IDEAL_FVG_SIZE_MAX = 15.0

# §4.1 v0.3.5 — tier-ranked levels. Names match data/levels/session_levels.csv
# for static levels; dynamic levels (running 50%) are computed per-candle.
#
# v0.3.5: Asia and London tracked DISTINCTLY from overnight (overnight is the union
# max). Justified by R06 trade 2 diagnostic — Tempo trades london_high specifically
# on days where london_high != overnight_high (= asia_high). 4 recap mentions of
# Asia/London distinctly.
SWEEP_LEVELS_TIER2_STATIC = (
    'overnight_high', 'overnight_low',
    'london_high', 'london_low',
    'asia_high', 'asia_low',
)
SWEEP_LEVELS_TIER3 = ('prev_day_high', 'prev_day_low')
SWEEP_LEVELS_TIER1 = ('data_high', 'data_low')                # deferred → §13.1

# v0.3.6 — CME daily 50% as a sweep level. Replaces v0.3.4 running_50pct which
# computed mid from RTH running H/L (a dynamic level the user doesn't draw on
# their chart). User trades from TradingView "Dynamic Customizable 50% Line"
# with 1-day timeframe = midpoint of the PRIOR CLOSED CME daily candle
# (18:00 NY → 17:00 NY). Static for the trading session.
# Verified vs user's chart on 2026-05-21: 29097.38 ✓.
# Stored as static rows in data/levels/session_levels.csv via
# data/levels/build_daily_50pct.py + add_daily_50pct_to_session_levels.py.
SWEEP_LEVELS_DAILY_50PCT = ('daily_50pct_high', 'daily_50pct_low')

# Tier 2 includes daily 50% alongside overnight (both are "major orderflow").
SWEEP_LEVELS_TIER2 = SWEEP_LEVELS_TIER2_STATIC + SWEEP_LEVELS_DAILY_50PCT
ACTIVE_SWEEP_LEVELS = SWEEP_LEVELS_TIER2 + SWEEP_LEVELS_TIER3

# Tier lookup for ACTIVE_SWEEP_LEVELS.
SWEEP_LEVEL_TIER = {name: 2 for name in SWEEP_LEVELS_TIER2} | {name: 3 for name in SWEEP_LEVELS_TIER3}

# "high" levels are resistance (swept by an upward wick); "low" are support.
SWEEP_LEVEL_SIDE = {
    'overnight_high': 'high', 'overnight_low': 'low',
    'london_high':    'high', 'london_low':    'low',
    'asia_high':      'high', 'asia_low':      'low',
    'prev_day_high':  'high', 'prev_day_low':  'low',
    'daily_50pct_high': 'high', 'daily_50pct_low': 'low',
}

# v0.3.6 — daily_50pct is static (loaded from session_levels.csv), so the
# v0.3.4 "RANGE_FOR_50PCT_VALID" gating is no longer applicable. Kept here for
# backward reference; not consumed by the v0.3.6 sweep detector.
RANGE_FOR_50PCT_VALID = 20.0  # deprecated v0.3.6

# §4.2 v0.3.0 — sweep criterion: wick beyond, close back through same candle
MIN_SWEEP_PENETRATION = 1.0  # NQ points

# §4.3 v0.3.0 — sweep stays valid for 40 min unless nuked
SWEEP_VALIDITY_MINUTES = 40
NUKE_THRESHOLD = 5.0  # candle closes >=5 pts beyond level in sweep direction = invalidated

# §5 v0.3.0 — reaction quality
REACTION_WINDOW_CANDLES = 2
REACTION_MIN_MOVE = 5.0      # M — min move-away from swept level (pts)
REACTION_STALL_BAND = 2.0    # S — close-back-to-level forbidden within this band (pts)

# §7 v0.3.2 — IFVG confirmation
# Inversion must close within this many seconds of the sweep candle's close.
# v0.3.1 used per-TF (2 * tf_seconds) = 60-360s; v0.3.2 switches to a flat
# time window after diagnostic showed valid A+ gaps inverting 3-13 min late
# under the tight per-TF interpretation. See SPEC §7.1 and memory project-ifvg-reversal-tempo.
CONFIRMATION_WINDOW_SECONDS = 300  # 5 minutes
MOMENTUM_BODY_FRACTION = 0.50      # body must be >=50% of candle range
APLUS_BODY_FRACTION = 0.70         # §12 A+ tightens momentum to >=70%

# §6.1 — bar duration per TF (used for A+ "fast reaction" check, not qualification window)
TF_SECONDS = {'30s': 30, '1min': 60, '2min': 120, '3min': 180}
SWEEP_CANDLE_SECONDS = 30          # base TF used by detect_sweeps

# §9 v0.3.0 — stop loss
HARD_STOP_BUFFER = 2.0  # NQ points beyond swing extreme
ENABLE_BREAK_EVEN = False  # §9.4 disabled in v0.3.0 baseline

# §11 v0.3.0 — chop filters
CHOP_AM_RANGE_MIN = 100.0  # < 100 pts by 10:30 NY = chop day, skip
OR_CONTAINMENT_DEADLINE = dtime(10, 15)  # still inside 09:30-09:45 OR by this time = chop
EQUILIBRIUM_BAND = 5.0  # §3.2 ±5 pts around 50% for equilibrium veto
