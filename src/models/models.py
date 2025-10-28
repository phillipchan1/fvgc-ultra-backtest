# models.py
# ---------------------------------------------------------------------------
# Entry model evaluators for different FVG strategies
# ---------------------------------------------------------------------------

import pandas as pd
from typing import Optional, Dict, List
from ..core.config import CONFIG
from ..core.fvg_detection import FVG, find_conflicts


def _entry_touch_type(fvg: FVG, row: pd.Series) -> str:
    """Classify entry-bar interaction with the gap.

    Returns: "tap" if the bar touched the gap but closed outside it in continuation direction;
             "close_inside" if the close is inside the gap bounds.
    """
    c = float(row["close"]) 
    low = float(row["low"]) 
    high = float(row["high"]) 
    lower = float(fvg.lower)
    upper = float(fvg.upper)
    # Ensure there is an interaction
    touched = (low <= upper and high >= lower)
    if not touched:
        return "none"
    if fvg.direction == "bullish":
        return "tap" if c >= upper else ("close_inside" if (c > lower and c < upper) else "tap")
    else:
        return "tap" if c <= lower else ("close_inside" if (c > lower and c < upper) else "tap")


def _gap_taps_before_entry(df: pd.DataFrame, fvg: FVG, entry_idx: int) -> int:
    """Count prior bars that touched the gap after creation and before entry bar."""
    lower = float(fvg.lower)
    upper = float(fvg.upper)
    start = max(fvg.created_idx + 1, 0)
    end = max(entry_idx - 1, start - 1)
    if end < start:
        return 0
    window = df.iloc[start:end + 1]
    touches = (window["low"] <= upper) & (window["high"] >= lower)
    return int(touches.sum())


def _penetrated_midline_on_entry(fvg: FVG, row: pd.Series) -> Optional[bool]:
    """Whether the entry bar penetrated beyond the 50% of the gap in pullback direction."""
    lower = float(fvg.lower)
    upper = float(fvg.upper)
    mid = (lower + upper) / 2.0
    low = float(row["low"]) 
    high = float(row["high"]) 
    # Must interact with gap
    if not (low <= upper and high >= lower):
        return None
    if fvg.direction == "bullish":
        return low <= mid
    else:
        return high >= mid


def _time_bucket_label(ts_et: str) -> str:
    """Return time bucket label HHMM-HHMM for ET ISO timestamp string."""
    # ts_et is ISO string in ET. Extract HH:MM:SS
    hhmm = ts_et[11:16].replace(":", "")  # HHMM
    h = int(hhmm[:2]); m = int(hhmm[2:])
    mins = h * 60 + m
    # Define buckets
    buckets = [
        (9 * 60 + 30, 9 * 60 + 45, "0930-0945"),
        (9 * 60 + 45, 10 * 60 + 0, "0945-1000"),
        (10 * 60 + 0, 10 * 60 + 15, "1000-1015"),
    ]
    for start, end, label in buckets:
        if mins >= start and mins < end:
            return label
    return "other"


def _bars_to_prev_break(df: pd.DataFrame, fvg: FVG) -> Optional[int]:
    """Number of bars after creation until current bar breaks previous bar in FVG direction.

    Uses wick comparison: for bullish, first j such that high[j] > high[j-1];
    for bearish, first j such that low[j] < low[j-1]. Returns bar count delta from creation,
    or None if not found.
    """
    start = fvg.created_idx + 1
    for j in range(start, len(df)):
        if fvg.direction == "bullish":
            if j - 1 >= 0 and float(df.iloc[j]["high"]) > float(df.iloc[j - 1]["high"]):
                return j - fvg.created_idx
        else:
            if j - 1 >= 0 and float(df.iloc[j]["low"]) < float(df.iloc[j - 1]["low"]):
                return j - fvg.created_idx
    return None


def _scenario_filters(df: pd.DataFrame, fvg: FVG, row: pd.Series, idx: int) -> Optional[Dict]:
    """Apply scenario-focused filters. Returns annotations dict if pass, else None."""
    annotations: Dict = {}

    # Touch classification
    touch = _entry_touch_type(fvg, row)
    annotations["entry_touch_type"] = touch
    desired_touch = CONFIG.get("entry_touch_type")
    if desired_touch == "tap_only" and touch != "tap":
        return None
    if desired_touch == "close_inside_only" and touch != "close_inside":
        return None

    # Tap counts before entry
    taps = _gap_taps_before_entry(df, fvg, idx)
    annotations["gap_taps_before_entry"] = int(taps)
    min_taps = CONFIG.get("min_gap_taps")
    max_taps = CONFIG.get("max_gap_taps")
    if min_taps is not None and taps < int(min_taps):
        return None
    if max_taps is not None and taps > int(max_taps):
        return None

    # Midline penetration
    pen = _penetrated_midline_on_entry(fvg, row)
    annotations["penetrated_midline"] = pen if pen is not None else False
    desired_pen = CONFIG.get("penetrated_midline")
    if desired_pen is not None and pen is not None and bool(desired_pen) != bool(pen):
        return None

    # Time constraints
    entry_et = row["timestamp"].tz_convert(CONFIG["session_tz"]).isoformat()
    label = _time_bucket_label(entry_et)
    annotations["time_bucket"] = label
    allowed = CONFIG.get("allowed_time_buckets")
    if allowed is not None and isinstance(allowed, list) and label not in allowed:
        return None
    first_five_only = CONFIG.get("first_five_only")
    if first_five_only:
        # 09:30:00 - 09:35:00
        hhmmss = entry_et[11:19]
        if not ("09:30:00" <= hhmmss < "09:35:00"):
            return None
    annotations["first_five"] = (label == "0930-0945" and entry_et[11:16] < "09:35")

    # Gap size bounds
    gap_size = float(fvg.size_pts) if fvg.size_pts is not None else 0.0
    annotations["fvg_size_pts"] = gap_size
    gmin = CONFIG.get("gap_size_min_pts")
    gmax = CONFIG.get("gap_size_max_pts")
    if gmin is not None and gap_size < float(gmin):
        return None
    if gmax is not None and gap_size > float(gmax):
        return None

    # Bars to prev break
    bars_to_break = _bars_to_prev_break(df, fvg)
    annotations["bars_to_prev_break"] = bars_to_break if bars_to_break is not None else -1
    bmin = CONFIG.get("min_bars_to_prev_break")
    bmax = CONFIG.get("max_bars_to_prev_break")
    if bars_to_break is not None:
        if bmin is not None and bars_to_break < int(bmin):
            return None
        if bmax is not None and bars_to_break > int(bmax):
            return None

    return annotations

def strict_pullback_pass(fvg: FVG, row: pd.Series, idx: int) -> Optional[Dict]:
    """Check if FVG passes strict pullback requirements."""
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    prev_close = float(row["prev_close"]) if pd.notna(row["prev_close"]) else None
    bars_since = idx - fvg.created_idx
    
    if CONFIG["disallow_same_bar_entry"] and bars_since == 0:
        return None
    if bars_since < CONFIG["min_bars_since_creation"]:
        return None

    if fvg.direction == "bullish":
        if CONFIG["require_pullback_from_outside"] and o < fvg.upper:
            return None
        if not (l <= fvg.upper and h >= fvg.lower):
            return None
        if CONFIG["require_directional_close"] and c <= o:
            return None
        if CONFIG["require_prev_close_break"] and prev_close and c <= prev_close:
            return None
        return {"side": "long", "entry_price": c}
    else:
        if CONFIG["require_pullback_from_outside"] and o > fvg.lower:
            return None
        if not (h >= fvg.lower and l <= fvg.upper):
            return None
        if CONFIG["require_directional_close"] and c >= o:
            return None
        if CONFIG["require_prev_close_break"] and prev_close and c >= prev_close:
            return None
        return {"side": "short", "entry_price": c}


def prev_extreme_break_ok_no_fvg(row: pd.Series, direction: str) -> bool:
    """Check if previous extreme was broken (for no_fvg model)."""
    if not CONFIG["require_prev_extreme_break_no_fvg"]:
        return True
    # Allow configuration of metric (close vs wick) and equality handling
    metric = CONFIG.get("nofvg_break_metric", "close")
    allow_equal = bool(CONFIG.get("nofvg_allow_equal", False))

    px_high = float(row["high"]) if metric == "wick" else float(row["close"]) 
    px_low = float(row["low"]) if metric == "wick" else float(row["close"]) 

    ph = float(row["prev_high"]) if pd.notna(row["prev_high"]) else None
    pl = float(row["prev_low"]) if pd.notna(row["prev_low"]) else None

    if direction == "bullish" and ph is not None:
        return (px_high > ph) or (allow_equal and px_high == ph)
    if direction == "bearish" and pl is not None:
        return (px_low < pl) or (allow_equal and px_low == pl)
    return False


def opposite_ifvg_same_bar(df: pd.DataFrame, idx: int, direction: str, fvg: FVG) -> bool:
    """Check if opposite direction iFVG exists on same bar."""
    row = df.iloc[idx]
    if direction == "bullish":
        if bool(row.get("bear_fvg", False)):
            lo, up = float(row["bear_lower"]), float(row["bear_upper"])
            return not (up < fvg.lower or lo > fvg.upper)
    else:
        if bool(row.get("bull_fvg", False)):
            lo, up = float(row["bull_lower"]), float(row["bull_upper"])
            return not (up < fvg.lower or lo > fvg.upper)
    return False


def has_internal_fvg(df: pd.DataFrame, idx: int, parent: FVG) -> bool:
    """Check if an internal FVG exists within a lookback window relative to parent.

    Searches up to CONFIG["ifvg_lookback_bars"] bars back from `idx` (inclusive).
    If CONFIG["ifvg_same_bar"] is True, at least one qualifying internal FVG must
    be on the same bar as `idx`. Otherwise any bar in the window qualifies.
    """
    mode = CONFIG.get("ifvg_internal_criterion", "inside")  # "inside" | "overlap"
    allow_opposite = bool(CONFIG.get("ifvg_allow_opposite_internal", True))
    # Be tolerant to None or non-numeric values
    _overlap_raw = CONFIG.get("ifvg_overlap_min_ratio", 0.0)
    try:
        min_overlap_ratio = float(_overlap_raw) if _overlap_raw is not None else 0.0
    except Exception:
        min_overlap_ratio = 0.0
    same_bar_only = bool(CONFIG.get("ifvg_same_bar", False))
    _lookback_raw = CONFIG.get("ifvg_lookback_bars", 6)
    try:
        lookback = int(_lookback_raw) if _lookback_raw is not None else 6
    except Exception:
        lookback = 6

    start = max(parent.created_idx + 1, idx - lookback + 1)
    end = idx

    p_low, p_up = float(parent.lower), float(parent.upper)

    def bar_candidates(row: pd.Series):
        cands = []
        if bool(row.get("bull_fvg", False)):
            cands.append(("bullish", float(row["bull_lower"]), float(row["bull_upper"])))
        if bool(row.get("bear_fvg", False)):
            lo = float(row["bear_lower"])  # high
            up = float(row["bear_upper"])  # lo2
            low_b, up_b = (min(lo, up), max(lo, up))
            cands.append(("bearish", low_b, up_b))
        return cands

    found_same_bar = False
    found_any = False

    for k in range(start, end + 1):
        row = df.iloc[k]
        cands = bar_candidates(row)
        if not cands:
            continue
        for child_dir, c_low, c_up in cands:
            same_dir = (child_dir == parent.direction)
            if not (same_dir or allow_opposite):
                continue
            if mode == "inside":
                ok = (p_low <= c_low) and (c_up <= p_up)
            else:
                overlap = max(0.0, min(p_up, c_up) - max(p_low, c_low))
                child_size = max(0.0, c_up - c_low)
                ok = child_size > 0 and overlap > 0 and (overlap / child_size) >= min_overlap_ratio
            if ok:
                found_any = True
                if k == idx:
                    found_same_bar = True
        if same_bar_only and k == idx:
            # If we require same-bar, we can break early after evaluating idx
            break

    return (found_same_bar if same_bar_only else found_any)


def ifvg_prev_hilo_break_ok(row: pd.Series, direction: str) -> bool:
    """Check if previous high/low was broken (for iFVG model) with configurable metric and equality."""
    if not CONFIG["ifvg_require_prev_high_low_break"]:
        return True
    metric = CONFIG.get("ifvg_break_metric", "close")  # "close" | "wick"
    allow_equal = bool(CONFIG.get("ifvg_allow_equal", False))

    px_high = float(row["high"]) if metric == "wick" else float(row["close"])
    px_low = float(row["low"]) if metric == "wick" else float(row["close"])

    ph = row.get("prev_high")
    pl = row.get("prev_low")
    ph = float(ph) if pd.notna(ph) else None
    pl = float(pl) if pd.notna(pl) else None
    
    if direction == "bullish" and ph is not None:
        return (px_high > ph) or (allow_equal and px_high == ph)
    if direction == "bearish" and pl is not None:
        return (px_low < pl) or (allow_equal and px_low == pl)
    return False


def swing_points(df: pd.DataFrame, left=2, right=2):
    """Identify swing highs and lows."""
    h = df["high"].values
    l = df["low"].values
    n = len(df)
    sh = [False] * n
    sl = [False] * n
    
    for i in range(left, n - right):
        sh[i] = all(h[i] > h[i - k - 1] for k in range(left)) and all(h[i] >= h[i + k + 1] for k in range(right))
        sl[i] = all(l[i] < l[i - k - 1] for k in range(left)) and all(l[i] <= l[i + k + 1] for k in range(right))
    
    df["is_sw_high"] = pd.Series(sh, index=df.index)
    df["is_sw_low"] = pd.Series(sl, index=df.index)


def last_swing_level(df: pd.DataFrame, idx: int, direction: str, left: int, right: int, lookback: int):
    """Find last swing level for BOS model."""
    if "is_sw_high" not in df.columns:
        swing_points(df, left, right)
    
    start = max(0, idx - lookback)
    window = df.iloc[start:idx]
    
    if direction == "bullish":
        highs = window[window["is_sw_high"] == True]
        return (float(highs["high"].iloc[-1]), "high") if not highs.empty else (None, None)
    else:
        lows = window[window["is_sw_low"] == True]
        return (float(lows["low"].iloc[-1]), "low") if not lows.empty else (None, None)


def passes_bos(row: pd.Series, level: float, direction: str) -> bool:
    """Check if BOS level was broken."""
    allow_equal = bool(CONFIG.get("bos_allow_equal", False))
    if CONFIG["bos_require_close_through"]:
        cmp = float(row["close"]) - level
        if direction == "bullish":
            return (cmp > 0) or (allow_equal and cmp == 0)
        else:
            return (cmp < 0) or (allow_equal and cmp == 0)
    else:
        if direction == "bullish":
            return (float(row["high"]) > level) or (allow_equal and float(row["high"]) == level)
        else:
            return (float(row["low"]) < level) or (allow_equal and float(row["low"]) == level)


# =============================
# ENTRY MODEL EVALUATORS
# =============================

def eval_fvg_no_fvg(f: FVG, active: List[FVG], row: pd.Series, idx: int, df: pd.DataFrame) -> Optional[Dict]:
    """Evaluate FVG with no additional conditions."""
    if f.size_pts is None or f.middle_body_pts is None:
        return None
    if f.size_pts < CONFIG["min_gap_pts"] or f.middle_body_pts < CONFIG["min_middle_body_pts"]:
        return None
    
    conflict, _ = find_conflicts(active, f)
    if conflict and CONFIG["skip_conflicting_fvgs"] and not CONFIG.get("ifvg_ignore_internal_conflict", False):
        return None
    
    base = strict_pullback_pass(f, row, idx)
    if base is None:
        return None
    if not prev_extreme_break_ok_no_fvg(row, f.direction):
        return None
    if CONFIG["block_if_opposite_ifvg_same_bar"] and opposite_ifvg_same_bar(df, idx, f.direction, f):
        return None
    # Scenario filters
    annotations = _scenario_filters(df, f, row, idx)
    if annotations is None:
        return None

    return {
        "entry_model": "fvg_no_fvg",
        "side": base["side"],
        "entry_price": base["entry_price"],
        "fvg": f,
        **annotations,
    }


def eval_fvg_ifvg(f: FVG, active: List[FVG], row: pd.Series, idx: int, df: pd.DataFrame) -> Optional[Dict]:
    """Evaluate FVG with internal FVG condition."""
    if f.size_pts is None or f.middle_body_pts is None:
        return None
    if f.size_pts < CONFIG["min_gap_pts"] or f.middle_body_pts < CONFIG["min_middle_body_pts"]:
        return None
    
    conflict, _ = find_conflicts(active, f)
    if conflict and CONFIG["skip_conflicting_fvgs"]:
        return None
    
    base = strict_pullback_pass(f, row, idx)
    if base is None:
        return None
    if not has_internal_fvg(df, idx, f):
        return None
    if not ifvg_prev_hilo_break_ok(row, f.direction):
        return None
    # Scenario filters
    annotations = _scenario_filters(df, f, row, idx)
    if annotations is None:
        return None

    return {
        "entry_model": "fvg_ifvg",
        "side": base["side"],
        "entry_price": base["entry_price"],
        "fvg": f,
        **annotations,
    }


def eval_fvg_bos(f: FVG, active: List[FVG], row: pd.Series, idx: int, df: pd.DataFrame) -> Optional[Dict]:
    """Evaluate FVG with Break of Structure condition."""
    if f.size_pts is None or f.middle_body_pts is None:
        return None
    if f.size_pts < CONFIG["min_gap_pts"] or f.middle_body_pts < CONFIG["min_middle_body_pts"]:
        return None
    
    conflict, _ = find_conflicts(active, f)
    if conflict and CONFIG["skip_conflicting_fvgs"]:
        return None
    
    base = strict_pullback_pass(f, row, idx)
    if base is None:
        return None
    
    lvl, kind = last_swing_level(df, idx, f.direction, CONFIG["bos_left"], CONFIG["bos_right"], CONFIG["bos_lookback_bars"])
    if lvl is None:
        return None
    if not passes_bos(row, lvl, f.direction):
        return None
    # Scenario filters
    annotations = _scenario_filters(df, f, row, idx)
    if annotations is None:
        return None

    return {
        "entry_model": "fvg_bos",
        "side": base["side"],
        "entry_price": base["entry_price"],
        "fvg": f,
        **annotations,
    }


# Model evaluation mapping
EVAL_MAP = {
    "fvg_ifvg": eval_fvg_ifvg,
    "fvg_bos": eval_fvg_bos,
    "fvg_no_fvg": eval_fvg_no_fvg
}
