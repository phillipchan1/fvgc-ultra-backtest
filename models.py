# models.py
# ---------------------------------------------------------------------------
# Entry model evaluators for different FVG strategies
# ---------------------------------------------------------------------------

import pandas as pd
from typing import Optional, Dict, List
from config import CONFIG
from fvg_detection import FVG, find_conflicts


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
    min_overlap_ratio = float(CONFIG.get("ifvg_overlap_min_ratio", 0.0))
    same_bar_only = bool(CONFIG.get("ifvg_same_bar", False))
    lookback = int(CONFIG.get("ifvg_lookback_bars", 6))

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
    
    return {
        "entry_model": "fvg_no_fvg",
        "side": base["side"],
        "entry_price": base["entry_price"],
        "fvg": f
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
    
    return {
        "entry_model": "fvg_ifvg",
        "side": base["side"],
        "entry_price": base["entry_price"],
        "fvg": f
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
    
    return {
        "entry_model": "fvg_bos",
        "side": base["side"],
        "entry_price": base["entry_price"],
        "fvg": f
    }


# Model evaluation mapping
EVAL_MAP = {
    "fvg_ifvg": eval_fvg_ifvg,
    "fvg_bos": eval_fvg_bos,
    "fvg_no_fvg": eval_fvg_no_fvg
}
