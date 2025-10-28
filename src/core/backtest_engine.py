# backtest_engine.py
# ---------------------------------------------------------------------------
# Main backtest engine for FVG strategies
# ---------------------------------------------------------------------------

import pandas as pd
from typing import List, Dict, Set
from .config import CONFIG
from .data_loader import in_session
from .fvg_detection import (
    detect_fvgs, update_fvg_validity, prune_active_fvgs, 
    create_fvg_from_row, FVG
)
from ..models.models import EVAL_MAP


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
            if not f.valid:
                continue

            # Evaluate all models; optionally allow multiple per gap
            passed_any = False
            for model in CONFIG["models_to_eval"]:
                res = EVAL_MAP[model](f, active, row, i, df)
                if res:
                    key = (model, local_date)
                    if model_count.get(key, 0) >= CONFIG["max_trades_per_session_per_model"]:
                        continue
                    chosen.append(res)
                    model_count[key] = model_count.get(key, 0) + 1
                    passed_any = True
                    if not CONFIG.get("allow_multiple_models_per_gap", False):
                        break
            if passed_any and not CONFIG.get("allow_multiple_models_per_gap", False):
                # If only one allowed per gap, mark consumed
                consumed.add(f.fvg_id)

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
        # scenario annotations if present on signal
        "entry_touch_type": sig.get("entry_touch_type"),
        "gap_taps_before_entry": sig.get("gap_taps_before_entry"),
        "penetrated_midline": sig.get("penetrated_midline"),
        "time_bucket": sig.get("time_bucket"),
        "first_five": sig.get("first_five"),
        "bars_to_prev_break": sig.get("bars_to_prev_break"),
    }


def calculate_metrics(trades_df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Calculate backtest metrics including P/L and profit factor.

    P/L is computed from entry/exit prices, adjusted for side, multiplied by
    point value and contracts. Commissions are applied per round turn.
    """
    pv = float(CONFIG.get("point_value", 1.0))
    contracts = int(CONFIG.get("contracts_per_trade", 1))
    commission_rtt = float(CONFIG.get("commission_roundturn_per_contract", 0.0))
    start_balance = float(CONFIG.get("starting_balance", 0.0))

    def enrich(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.assign(
                pnl_points=0.0,
                gross_dollars=0.0,
                commission=0.0,
                net_dollars=0.0,
            )
        move = df["exit_price"] - df["entry_price"]
        points = move.where(df["side"] == "long", -move)
        gross = points * pv * contracts
        comm = commission_rtt * contracts
        return df.assign(
            pnl_points=points,
            gross_dollars=gross,
            commission=comm,
            net_dollars=gross - comm,
        )

    def summarize(df: pd.DataFrame) -> Dict[str, float]:
        n = int(len(df))
        wins = int((df["outcome"] == "TP").sum()) if n else 0
        wr = (wins / n) if n else 0.0
        df2 = enrich(df)
        gross_profit = float(df2["gross_dollars"].clip(lower=0).sum())
        gross_loss = float((-df2["gross_dollars"].clip(upper=0)).sum())
        commissions = float(df2["commission"].sum())
        net = float(df2["net_dollars"].sum())
        pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
        avg_trade = float(net / n) if n else 0.0
        end_balance = start_balance + net if start_balance else None
        return {
            "trades": n,
            "win_rate": wr,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "commissions": commissions,
            "net": net,
            "profit_factor": pf,
            "avg_trade": avg_trade,
            "ending_balance": end_balance if end_balance is not None else 0.0,
        }

    results: Dict[str, Dict[str, float]] = {}

    # Overall metrics
    results["TOTAL"] = summarize(trades_df)

    # Per-model metrics (robust to empty/missing columns)
    for model in ["fvg_ifvg", "fvg_bos", "fvg_no_fvg"]:
        if not trades_df.empty and "entry_model" in trades_df.columns:
            sub = trades_df[trades_df["entry_model"] == model]
        else:
            sub = trades_df.iloc[0:0]
        results[model] = summarize(sub)

    return results
