"""Data Wick — IFVG reversal triggered by red-folder news releases (§15 in SPEC.md).

Sibling setup to the AM IFVG reversal: same FVG-inversion mechanics, but the
sweep level is the high/low of the 1-min "data wick" candle that contains the
news release (08:30 or 10:00 NY).

Per Tempo: estimated 20% of his daily trades; he calls this "A+ extremely high
win rate" when the data wick range is large (≥60 pts) and the opposite side has
not yet been swept.

Code layout mirrors `ifvg_reversal/`:
  data_wick/
    constants.py        — release times, data wick min range
    detectors/
      data_wick.py      — finds the release candle + emits sweep events
    model.py            — pipeline (composes detectors)
    engine.py           — structural-target trade sim (opposite wick side)

FVG inventory (shared/fvg + multi_tf_fvg) is reused as-is.
"""

__version__ = "0.4.1"
