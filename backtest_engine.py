# backtest_engine.py
# ---------------------------------------------------------------------------
# Main backtest engine for FVG strategies
# ---------------------------------------------------------------------------

import pandas as pd
from typing import List, Dict, Set
from config import CONFIG
from data_loader import in_session
from fvg_detection import (
    detect_fvgs, update_fvg_validity, prune_active_fvgs, 
    create_fvg_from_row, FVG
)
from models import EVAL_MAP


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    """Run the main backtest loop."""
    trades = []
    active = []
    model_count = {}
    consumed = set()

    # Detect FVGs in the dataframe
    df = detect_fvgs(df)

    for i, row in df.iterrows():
        ts = row["timestamp"]
        local_date = ts.tz_convert(CONFIG["session_tz"]).date()

        # Create new FVGs at this bar
        if bool(row.get("bull_fvg", False)):
            active.append(create_fvg_from_row(row, i, "bullish"))
        if bool(row.get("bear_fvg", False)):
            active.append(create_fvg_from_row(row, i, "bearish"))

        # Update active FVGs
        active = prune_active_fvgs(active)
        update_fvg_validity(active, row, i)

        # Skip if not in trading session
        if not in_session(ts, CONFIG["session_tz"], CONFIG["session_start"], CONFIG["session_end"]):
            continue

        # Evaluate each active FVG for entry signals
        chosen = []
        for f in active:
            if not f.valid or f.fvg_id in consumed:
                continue
                
            # Try each model in priority order
            for model in CONFIG["models_to_eval"]:
                res = EVAL_MAP[model](f, active, row, i, df)
                if res:
                    key = (model, local_date)
                    if model_count.get(key, 0) >= CONFIG["max_trades_per_session_per_model"]:
                        continue
                    chosen.append(res)
                    consumed.add(f.fvg_id)  # One entry per gap
                    model_count[key] = model_count.get(key, 0) + 1
                    break

        # Resolve each chosen trade
        for sig in chosen:
            trade = resolve_trade(sig, df, i)
            if trade:
                trades.append(trade)

    return pd.DataFrame(trades)


def resolve_trade(sig: Dict, df: pd.DataFrame, entry_idx: int) -> Dict:
    """Resolve a trade from entry to exit."""
    side = sig["side"]
    entry = float(sig["entry_price"])
    f = sig["fvg"]
    
    # Calculate TP and SL
    tp = entry + CONFIG["points_tp"] if side == "long" else entry - CONFIG["points_tp"]
    sl = entry - CONFIG["points_sl"] if side == "long" else entry + CONFIG["points_sl"]

    # Find exit
    outcome = None
    exit_px = None
    exit_ts = None
    
    for j in range(entry_idx + 1, len(df)):
        r = df.iloc[j]
        ts2 = r["timestamp"]
        h, l, c = float(r["high"]), float(r["low"]), float(r["close"])
        
        # Check for TP/SL hits
        hit_tp = (h >= tp) if side == "long" else (l <= tp)
        hit_sl = (l <= sl) if side == "long" else (h >= sl)
        
        # Handle simultaneous TP/SL
        if hit_tp and hit_sl:
            if CONFIG["assume_tp_first"]:
                hit_sl = False
            else:
                hit_tp = False
        
        if hit_tp or hit_sl:
            outcome = "TP" if hit_tp else "SL"
            exit_px = tp if hit_tp else sl
            exit_ts = ts2
            break
            
        # Check if session ended
        if not in_session(ts2, CONFIG["session_tz"], CONFIG["session_start"], CONFIG["session_end"]):
            outcome = "Flat"
            exit_px = c
            exit_ts = ts2
            break
    
    # Handle case where no exit was found
    if outcome is None:
        r = df.iloc[-1]
        outcome = "Flat"
        exit_px = float(r["close"])
        exit_ts = r["timestamp"]

    # Create trade record
    entry_ts = df.iloc[entry_idx]["timestamp"]
    return {
        "entry_model": sig["entry_model"],
        "entry_time_utc": entry_ts.isoformat(),
        "entry_time_et": entry_ts.tz_convert(CONFIG["session_tz"]).isoformat(),
        "exit_time_utc": pd.Timestamp(exit_ts).isoformat(),
        "exit_time_et": pd.Timestamp(exit_ts).tz_convert(CONFIG["session_tz"]).isoformat(),
        "side": side,
        "entry_price": round(entry, 4),
        "tp_price": round(tp, 4),
        "sl_price": round(sl, 4),
        "exit_price": round(float(exit_px), 4),
        "outcome": outcome,
        "fvg_id": f.fvg_id,
        "fvg_dir": f.direction,
        "fvg_created_at_utc": f.created_at.isoformat(),
        "fvg_lower": round(f.lower, 4),
        "fvg_upper": round(f.upper, 4),
        "fvg_size_pts": round(f.size_pts, 4),
        "fvg_middle_body_pts": round(f.middle_body_pts, 4),
    }


def calculate_metrics(trades_df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Calculate backtest metrics."""
    def metrics(df):
        n = len(df)
        wins = (df["outcome"] == "TP").sum()
        wr = wins / n if n else 0.0
        return n, wr

    results = {}
    
    # Overall metrics
    n, wr = metrics(trades_df)
    results["TOTAL"] = {"trades": n, "win_rate": wr}
    
    # Per-model metrics
    for model in ["fvg_ifvg", "fvg_bos", "fvg_no_fvg"]:
        sub = trades_df[trades_df["entry_model"] == model]
        n, wr = metrics(sub)
        results[model] = {"trades": n, "win_rate": wr}
    
    return results
