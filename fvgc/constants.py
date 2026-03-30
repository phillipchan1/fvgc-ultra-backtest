"""Tunable parameters for the FVGC model (Notion §6)."""

import pytz
from datetime import time as dtime

NY_TZ = pytz.timezone('America/New_York')

TRADING_WINDOW_START = dtime(9, 30)
TRADING_WINDOW_END = dtime(10, 15)

SWING_LOOKBACK = 2
FVG_START_TIME = dtime(9, 30)
MIN_FVG_SIZE = 3.0  # NQ points; §1.1 v2.0

SL_INCREMENT = 5
SL_MIN = 15
SL_MAX = 60
RR_RATIO = 1.0
