# fvg_continuation_backtest_db_1s.py
# ---------------------------------------------------------------------------
# Multi-entry FVG Backtest (ICT-style)
# Detects and labels: fvg_ifvg, fvg_bos, fvg_no_fvg
# Uses Databento-style OHLCV 1s data, resampled to 30s
# ---------------------------------------------------------------------------

from __future__ import annotations
import pandas as pd
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import itertools
import warnings
import pathlib

# =============================
# CONFIGURATION
# =============================
CONFIG = {
    "data_path": "glbx-mdp3-20250911-20251010.ohlcv-1s.csv",
    "symbol": None,
    "start_date": None,
    "end_date": None,

    "session_tz": "America/New_York",
    "session_start": "09:30:00",
    "session_end": "10:15:00",

    "points_tp": 20.0,
    "points_sl": 20.0,
    "assume_tp_first": False,

    # priority order; first match wins for a given FVG on a given bar
    "models_to_eval": ["fvg_ifvg", "fvg_bos", "fvg_no_fvg"],
    "max_trades_per_session_per_model": 3,

    "min_gap_pts": 0.75,
    "min_middle_body_pts": 1.0,
    "fvg_max_age_bars": 20,
    "max_active_per_side": 3,
    "invalidate_on_wick_through": False,

    # conflict handling & baseline guards
    "skip_conflicting_fvgs": True,
    "require_prev_extreme_break_no_fvg": True,
    "block_if_opposite_ifvg_same_bar": True,

    # baseline shape (used by all models as the base continuation filter)
    "disallow_same_bar_entry": True,
    "min_bars_since_creation": 1,
    "require_pullback_from_outside": True,
    "require_directional_close": True,
    "require_prev_close_break": True,
    "require_close_outside_gap": False,

    # iFVG knobs
    "ifvg_same_bar": True,
    "ifvg_lookback_bars": 6,
    "ifvg_require_prev_high_low_break": True,
    "ifvg_respect_IEL": False,

    # BOS knobs
    "bos_left": 2,
    "bos_right": 2,
    "bos_lookback_bars": 12,
    "bos_require_close_through": True,

    "trades_csv": "trades.csv"
}

# =============================
# LOAD DATA
# =============================
REQUIRED_COLS = [
    "ts_event","open","high","low","close","volume","symbol"
]

def load_db_1s_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    df["timestamp"] = pd.to_datetime(df["ts_event"], utc=True)
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    if CONFIG["start_date"]:
        df = df[df["timestamp"] >= pd.Timestamp(CONFIG["start_date"], tz="UTC")]
    if CONFIG["end_date"]:
        df = df[df["timestamp"] <= pd.Timestamp(CONFIG["end_date"], tz="UTC")]

    sym = CONFIG["symbol"] or df["symbol"].mode().iloc[0]
    df = df[df["symbol"] == sym].copy()
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
    return df[["timestamp","open","high","low","close","volume"]]

def resample_to_30s(df: pd.DataFrame) -> pd.DataFrame:
    agg = {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    df = (
        df.set_index("timestamp")
          .resample("30S").agg(agg)
          .dropna(subset=["open","high","low","close"])
          .reset_index()
    )
    df["prev_close"] = df["close"].shift(1)
    df["prev_high"] = df["high"].shift(1)
    df["prev_low"] = df["low"].shift(1)
    return df

# =============================
# FVG DETECTION
# =============================
_fvg_seq = itertools.count(1)

@dataclass
class FVG:
    fvg_id: int
    direction: str
    created_at: pd.Timestamp
    created_idx: int
    lower: float
    upper: float
    size_pts: float
    middle_body_pts: float
    valid: bool = True
    expired: bool = False
    deactivated_reason: str = ""

def detect_fvgs(df: pd.DataFrame) -> pd.DataFrame:
    hi2 = df["high"].shift(2)
    lo2 = df["low"].shift(2)
    mid_open = df["open"].shift(1)
    mid_close = df["close"].shift(1)
    mid_body = (mid_close - mid_open).abs()

    df["bull_fvg"] = df["low"] > hi2
    df["bull_lower"] = hi2
    df["bull_upper"] = df["low"]
    df["bull_size"] = (df["bull_upper"] - df["bull_lower"]).where(df["bull_fvg"])
    df["bull_middle_body"] = mid_body.where(df["bull_fvg"])

    df["bear_fvg"] = df["high"] < lo2
    df["bear_lower"] = df["high"]
    df["bear_upper"] = lo2
    df["bear_size"] = (df["bear_upper"] - df["bear_lower"]).where(df["bear_fvg"]).abs()
    df["bear_middle_body"] = mid_body.where(df["bear_fvg"])
    return df

# =============================
# LIFECYCLE / CONFLICT MGMT
# =============================
def update_fvg_validity(active_fvgs: List[FVG], row: pd.Series, idx: int):
    o,h,l,c = float(row["open"]),float(row["high"]),float(row["low"]),float(row["close"])
    for f in active_fvgs:
        if not f.valid or f.expired:
            continue
        if idx - f.created_idx >= CONFIG["fvg_max_age_bars"]:
            f.valid = False; f.expired=True; f.deactivated_reason="expired"; continue
        if f.direction=="bullish" and c < f.lower:
            f.valid=False; f.deactivated_reason="inverted_close"
        elif f.direction=="bearish" and c > f.upper:
            f.valid=False; f.deactivated_reason="inverted_close"

def prune_active_fvgs(active: List[FVG]) -> List[FVG]:
    valid = [f for f in active if f.valid and not f.expired]
    bulls = [f for f in valid if f.direction=="bullish"]
    bears = [f for f in valid if f.direction=="bearish"]
    bulls.sort(key=lambda x: x.created_at, reverse=True)
    bears.sort(key=lambda x: x.created_at, reverse=True)
    return bulls[:CONFIG["max_active_per_side"]] + bears[:CONFIG["max_active_per_side"]]

def find_conflicts(active: List[FVG], fvg: FVG) -> Tuple[bool,List[int]]:
    conflicts=[]
    for f in active:
        if f.fvg_id==fvg.fvg_id or not f.valid or f.direction==fvg.direction:
            continue
        overlap = not (fvg.upper < f.lower or fvg.lower > f.upper)
        if overlap:
            conflicts.append(f.fvg_id)
    return (len(conflicts)>0,conflicts)

# =============================
# HELPERS
# =============================
def in_session(ts: pd.Timestamp, tz: str, start: str, end: str) -> bool:
    local = ts.tz_convert(tz).strftime("%H:%M:%S")
    return start <= local <= end

def strict_pullback_pass(fvg: FVG, row: pd.Series, idx:int) -> Optional[Dict]:
    o,h,l,c = float(row["open"]),float(row["high"]),float(row["low"]),float(row["close"])
    prev_close = float(row["prev_close"]) if pd.notna(row["prev_close"]) else None
    bars_since = idx - fvg.created_idx
    if CONFIG["disallow_same_bar_entry"] and bars_since==0:
        return None
    if bars_since < CONFIG["min_bars_since_creation"]:
        return None

    if fvg.direction=="bullish":
        if CONFIG["require_pullback_from_outside"] and o < fvg.upper: return None
        if not (l <= fvg.upper and h >= fvg.lower): return None
        if CONFIG["require_directional_close"] and c <= o: return None
        if CONFIG["require_prev_close_break"] and prev_close and c <= prev_close: return None
        return {"side":"long","entry_price":c}
    else:
        if CONFIG["require_pullback_from_outside"] and o > fvg.lower: return None
        if not (h >= fvg.lower and l <= fvg.upper): return None
        if CONFIG["require_directional_close"] and c >= o: return None
        if CONFIG["require_prev_close_break"] and prev_close and c >= prev_close: return None
        return {"side":"short","entry_price":c}

def prev_extreme_break_ok_no_fvg(row: pd.Series, direction: str) -> bool:
    if not CONFIG["require_prev_extreme_break_no_fvg"]: return True
    c = float(row["close"])
    ph = float(row["prev_high"]) if pd.notna(row["prev_high"]) else None
    pl = float(row["prev_low"]) if pd.notna(row["prev_low"]) else None
    if direction=="bullish" and ph is not None:
        return c > ph
    if direction=="bearish" and pl is not None:
        return c < pl
    return False

def opposite_ifvg_same_bar(df: pd.DataFrame, idx:int, direction:str, fvg:FVG) -> bool:
    row = df.iloc[idx]
    if direction=="bullish":
        if bool(row.get("bear_fvg",False)):
            lo,up=float(row["bear_lower"]),float(row["bear_upper"])
            return not (up < fvg.lower or lo > fvg.upper)
    else:
        if bool(row.get("bull_fvg",False)):
            lo,up=float(row["bull_lower"]),float(row["bull_upper"])
            return not (up < fvg.lower or lo > fvg.upper)
    return False

# iFVG helpers
def has_internal_fvg(df: pd.DataFrame, idx:int, parent:FVG) -> bool:
    row = df.iloc[idx]
    if parent.direction=="bullish":
        if bool(row.get("bull_fvg",False)):
            return parent.lower <= row["bull_lower"] <= row["bull_upper"] <= parent.upper
    else:
        if bool(row.get("bear_fvg",False)):
            return parent.lower <= row["bear_lower"] <= row["bear_upper"] <= parent.upper
    return False

def ifvg_prev_hilo_break_ok(row: pd.Series, direction: str) -> bool:
    if not CONFIG["ifvg_require_prev_high_low_break"]: return True
    c=float(row["close"]); ph=row.get("prev_high"); pl=row.get("prev_low")
    ph=float(ph) if pd.notna(ph) else None
    pl=float(pl) if pd.notna(pl) else None
    if direction=="bullish" and ph: return c>ph
    if direction=="bearish" and pl: return c<pl
    return False

# BOS helpers
def swing_points(df: pd.DataFrame, left=2, right=2):
    h=df["high"].values; l=df["low"].values; n=len(df)
    sh=[False]*n; sl=[False]*n
    for i in range(left, n-right):
        sh[i]=all(h[i]>h[i-k-1] for k in range(left)) and all(h[i]>=h[i+k+1] for k in range(right))
        sl[i]=all(l[i]<l[i-k-1] for k in range(left)) and all(l[i]<=l[i+k+1] for k in range(right))
    df["is_sw_high"]=pd.Series(sh,index=df.index)
    df["is_sw_low"]=pd.Series(sl,index=df.index)

def last_swing_level(df: pd.DataFrame, idx:int, direction:str, left:int, right:int, lookback:int):
    if "is_sw_high" not in df.columns: swing_points(df,left,right)
    start=max(0,idx-lookback)
    window=df.iloc[start:idx]
    if direction=="bullish":
        highs=window[window["is_sw_high"]==True]
        return (float(highs["high"].iloc[-1]),"high") if not highs.empty else (None,None)
    else:
        lows=window[window["is_sw_low"]==True]
        return (float(lows["low"].iloc[-1]),"low") if not lows.empty else (None,None)

def passes_bos(row: pd.Series, level: float, direction: str) -> bool:
    if CONFIG["bos_require_close_through"]:
        return float(row["close"]) > level if direction=="bullish" else float(row["close"]) < level
    return float(row["high"]) > level if direction=="bullish" else float(row["low"]) < level

# =============================
# ENTRY MODEL EVALUATORS (per-gap)
# =============================
def eval_fvg_no_fvg(f:FVG, active:List[FVG], row:pd.Series, idx:int, df:pd.DataFrame) -> Optional[Dict]:
    if f.size_pts is None or f.middle_body_pts is None: return None
    if f.size_pts<CONFIG["min_gap_pts"] or f.middle_body_pts<CONFIG["min_middle_body_pts"]: return None
    conflict,_=find_conflicts(active,f)
    if conflict and CONFIG["skip_conflicting_fvgs"]: return None
    base = strict_pullback_pass(f,row,idx)
    if base is None: return None
    if not prev_extreme_break_ok_no_fvg(row,f.direction): return None
    if CONFIG["block_if_opposite_ifvg_same_bar"] and opposite_ifvg_same_bar(df,idx,f.direction,f):
        return None
    return {"entry_model":"fvg_no_fvg","side":base["side"],"entry_price":base["entry_price"],"fvg":f}

def eval_fvg_ifvg(f:FVG,active:List[FVG],row:pd.Series,idx:int,df:pd.DataFrame)->Optional[Dict]:
    if f.size_pts is None or f.middle_body_pts is None: return None
    if f.size_pts<CONFIG["min_gap_pts"] or f.middle_body_pts<CONFIG["min_middle_body_pts"]: return None
    conflict,_=find_conflicts(active,f)
    if conflict and CONFIG["skip_conflicting_fvgs"]: return None
    base=strict_pullback_pass(f,row,idx)
    if base is None: return None
    if not has_internal_fvg(df,idx,f): return None
    if not ifvg_prev_hilo_break_ok(row,f.direction): return None
    return {"entry_model":"fvg_ifvg","side":base["side"],"entry_price":base["entry_price"],"fvg":f}

def eval_fvg_bos(f:FVG,active:List[FVG],row:pd.Series,idx:int,df:pd.DataFrame)->Optional[Dict]:
    if f.size_pts is None or f.middle_body_pts is None: return None
    if f.size_pts<CONFIG["min_gap_pts"] or f.middle_body_pts<CONFIG["min_middle_body_pts"]: return None
    conflict,_=find_conflicts(active,f)
    if conflict and CONFIG["skip_conflicting_fvgs"]: return None
    base=strict_pullback_pass(f,row,idx)
    if base is None: return None
    lvl,kind=last_swing_level(df,idx,f.direction,CONFIG["bos_left"],CONFIG["bos_right"],CONFIG["bos_lookback_bars"])
    if lvl is None: return None
    if not passes_bos(row,lvl,f.direction): return None
    return {"entry_model":"fvg_bos","side":base["side"],"entry_price":base["entry_price"],"fvg":f}

EVAL_MAP = {
    "fvg_ifvg": eval_fvg_ifvg,
    "fvg_bos": eval_fvg_bos,
    "fvg_no_fvg": eval_fvg_no_fvg
}

# =============================
# BACKTEST LOOP
# =============================
def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    trades=[]
    active=[]
    model_count={}
    consumed=set()

    df = detect_fvgs(df)

    for i,row in df.iterrows():
        ts=row["timestamp"]
        local_date = ts.tz_convert(CONFIG["session_tz"]).date()

        # new FVGs at this bar
        if bool(row.get("bull_fvg",False)):
            active.append(FVG(next(_fvg_seq),"bullish",ts,i,
                              float(row["bull_lower"]),float(row["bull_upper"]),
                              float(row["bull_size"]),float(row["bull_middle_body"])))
        if bool(row.get("bear_fvg",False)):
            active.append(FVG(next(_fvg_seq),"bearish",ts,i,
                              float(row["bear_lower"]),float(row["bear_upper"]),
                              float(row["bear_size"]),float(row["bear_middle_body"])))

        active = prune_active_fvgs(active)
        update_fvg_validity(active,row,i)

        if not in_session(ts,CONFIG["session_tz"],CONFIG["session_start"],CONFIG["session_end"]):
            continue

        # for each active FVG, pick ONE model (priority order)
        chosen=[]
        for f in active:
            if not f.valid or f.fvg_id in consumed: 
                continue
            for model in CONFIG["models_to_eval"]:
                res = EVAL_MAP[model](f,active,row,i,df)
                if res:
                    key=(model,local_date)
                    if model_count.get(key,0) >= CONFIG["max_trades_per_session_per_model"]:
                        continue
                    chosen.append(res)
                    consumed.add(f.fvg_id)  # one entry per gap
                    model_count[key]=model_count.get(key,0)+1
                    break

        # resolve each chosen trade independently
        for sig in chosen:
            side=sig["side"]; entry=float(sig["entry_price"]); f=sig["fvg"]
            tp = entry + CONFIG["points_tp"] if side=="long" else entry - CONFIG["points_tp"]
            sl = entry - CONFIG["points_sl"] if side=="long" else entry + CONFIG["points_sl"]

            outcome=None; exit_px=None; exit_ts=None
            for j in range(i+1,len(df)):
                r=df.iloc[j]; ts2=r["timestamp"]
                h,l,c=float(r["high"]),float(r["low"]),float(r["close"])
                hit_tp = (h>=tp) if side=="long" else (l<=tp)
                hit_sl = (l<=sl) if side=="long" else (h>=sl)
                if hit_tp and hit_sl:
                    if CONFIG["assume_tp_first"]:
                        hit_sl=False
                    else:
                        hit_tp=False
                if hit_tp or hit_sl:
                    outcome = "TP" if hit_tp else "SL"
                    exit_px = tp if hit_tp else sl
                    exit_ts = ts2
                    break
                if not in_session(ts2,CONFIG["session_tz"],CONFIG["session_start"],CONFIG["session_end"]):
                    outcome="Flat"; exit_px=c; exit_ts=ts2; break
            if outcome is None:
                r=df.iloc[-1]; outcome="Flat"; exit_px=float(r["close"]); exit_ts=r["timestamp"]

            trades.append({
                "entry_model": sig["entry_model"],
                "entry_time_utc": ts.isoformat(),
                "entry_time_et": ts.tz_convert(CONFIG["session_tz"]).isoformat(),
                "exit_time_utc": pd.Timestamp(exit_ts).isoformat(),
                "exit_time_et": pd.Timestamp(exit_ts).tz_convert(CONFIG["session_tz"]).isoformat(),
                "side": side,
                "entry_price": round(entry,4),
                "tp_price": round(tp,4),
                "sl_price": round(sl,4),
                "exit_price": round(float(exit_px),4),
                "outcome": outcome,
                "fvg_id": f.fvg_id,
                "fvg_dir": f.direction,
                "fvg_created_at_utc": f.created_at.isoformat(),
                "fvg_lower": round(f.lower,4),
                "fvg_upper": round(f.upper,4),
                "fvg_size_pts": round(f.size_pts,4),
                "fvg_middle_body_pts": round(f.middle_body_pts,4),
            })

    return pd.DataFrame(trades)

# =============================
# MAIN
# =============================
def main():
    warnings.filterwarnings("ignore", category=FutureWarning)
    df1s = load_db_1s_csv(CONFIG["data_path"])
    df30 = resample_to_30s(df1s)
    trades = run_backtest(df30)

    if trades.empty:
        print("No trades generated.")
        return

    def metrics(df):
        n=len(df); wins=(df["outcome"]=="TP").sum()
        wr=wins/n if n else 0.0
        return n,wr

    print("=== FVG Backtest (30s) — One entry per gap ===")
    for m in ["fvg_ifvg","fvg_bos","fvg_no_fvg"]:
        sub=trades[trades["entry_model"]==m]
        n,wr=metrics(sub)
        print(f"{m:12s} trades={n:4d}  win_rate={wr:.2%}")
    n,wr=metrics(trades)
    print(f"TOTAL         trades={n:4d}  win_rate={wr:.2%}")

    trades.to_csv(CONFIG["trades_csv"], index=False)
    print(f"\nSaved trades to: {CONFIG['trades_csv']}")

if __name__ == "__main__":
    main()