"""Tunable parameters for the data-wick play. Spec: §15 in ifvg_reversal/SPEC.md."""

from datetime import time as dtime

# §15.1 — release times. Only the 1-min candle at these timestamps is treated as a "data wick".
RELEASE_TIMES_NY = (
    dtime(8, 30),    # NFP, CPI, PPI, GDP, retail sales, etc.
    dtime(10, 0),    # ISM, Consumer Confidence, JOLTS, etc.
)

# §15.4 — trading window per release. Window = (release_minute + 1, release_minute + N).
# v0.4.1: widened from 60 -> 120. Data wicks have huge liquidity that persists longer
# than ordinary sweeps; 60 was too restrictive (cut off setups that resolved later in the AM).
SETUP_WINDOW_MINUTES = 120

# §15.7 v0.4.1 — proximity threshold for hybrid stop.
# If entry is within PROXIMITY_TO_WICK_PTS of the swept wick extreme, the hard stop
# is placed beyond the wick (structural) instead of at the gap edge. Default tempo:
# gap-edge is right except when the gap is right under the wick, in which case wick
# stop is more meaningful.
PROXIMITY_TO_WICK_PTS = 10.0

# §15.2 — data wick minimum range to qualify (Tempo: "if the 1m candle is large enough
# e.g. 60 points he'll take a sweep+inversion"). Conservative floor at 30 pts.
MIN_DATA_WICK_RANGE = 30.0
APLUS_DATA_WICK_RANGE = 60.0  # §15.9 — A+ requires the 60+pt magnitude Tempo emphasizes

# §15.10 — start with same TF set as main model. 15s is a stretch goal.
TARGET_GAP_TIMEFRAMES = ('30s', '1min', '2min', '3min')
