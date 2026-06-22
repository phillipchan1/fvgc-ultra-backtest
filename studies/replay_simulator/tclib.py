"""Track C shared library — canonical loaders, session-table joins, ledger.

Consumes ONLY frozen artifacts:
  studies/confluence_framework/results/cache/baseline_trades_8yr.csv  (canonical 8yr)
  studies/confluence_framework/results/cache/session_quality.csv      (quality rule)
  studies/confluence_framework/results/phase1_split.json              (era boundary)
  studies/session_path_atlas/results/cache/session_table.parquet      (Track B joins)

fvgc/model.py and fvgc/engine.py are never imported or re-run (REPLAY_RULES.md §1).
Run with python3.13.
"""
from __future__ import annotations

import json
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RESULTS = HERE / "results"
TRACKA = REPO / "studies" / "confluence_framework" / "results"
SESSION_TABLE = (REPO / "studies" / "session_path_atlas" / "results" / "cache"
                 / "session_table.parquet")
LEDGER = RESULTS / "test_ledger.csv"
LEDGER_COLS = ["test_id", "phase", "hypothesis", "cohort", "n", "WR", "PF",
               "p_value", "q_value", "notes"]

_split = json.loads((TRACKA / "phase1_split.json").read_text())
OOS_BOUNDARY = pd.Timestamp(_split["split"]["oos_boundary_date"])  # 2024-02-13

BM_WINDOW = (dtime(9, 29, 30), dtime(9, 31, 0))
W1_END = dtime(9, 45)
OR5_END_SEC = 9 * 3600 + 35 * 60  # 09:35:00


class ReconciliationError(RuntimeError):
    pass


def load_quality_sessions() -> pd.DataFrame:
    q = pd.read_csv(TRACKA / "cache" / "session_quality.csv",
                    parse_dates=["session_date"])
    return q


def load_baseline() -> pd.DataFrame:
    """All baseline rows (signals), with quality/split/benchmark labels."""
    df = pd.read_csv(TRACKA / "cache" / "baseline_trades_8yr.csv",
                     parse_dates=["timestamp", "fvg_created_at", "exit_time"])
    df["session_date"] = df["timestamp"].dt.normalize()

    q = load_quality_sessions()
    ok = set(q.loc[q["pass"], "session_date"])
    df["quality_pass"] = df["session_date"].isin(ok)

    df["tradeable"] = df["outcome"].isin(["win", "loss"])
    df["win"] = (df["outcome"] == "win").astype(int)
    df["r"] = np.where(df["sl_dist"] > 0, df["pnl"] / df["sl_dist"], np.nan)
    df["split"] = np.where(df["session_date"] >= OOS_BOUNDARY, "recent", "IS")

    tod = df["fvg_created_at"].dt.time
    df["benchmark"] = ((tod >= BM_WINDOW[0]) & (tod <= BM_WINDOW[1])
                       & (df["direction"] == "short")
                       & (df["variant"] != "protected_swing")
                       & df["tradeable"] & df["quality_pass"])
    df["opening_window_signal"] = (tod >= BM_WINDOW[0]) & (tod <= BM_WINDOW[1])
    return df.sort_values("timestamp").reset_index(drop=True)


def load_session_table() -> pd.DataFrame:
    t = pd.read_parquet(SESSION_TABLE)
    t = t[["date", "w1_dir", "w1_high", "w1_low", "on_bucket",
           "or5_high", "or5_low", "or5_t_hi", "or5_t_lo"]].copy()
    t["date"] = pd.to_datetime(t["date"]).dt.normalize()
    return t.set_index("date")


def join_session_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Per-trade Track B joins per REPLAY_RULES.md tiebreaks T-4/T-5/T-6."""
    st = load_session_table()
    out = df.join(st, on="session_date")
    out["w1_dir"] = out["w1_dir"].fillna("unknown")
    out["on_bucket"] = out["on_bucket"].fillna("unknown")

    entry_sec = (out["timestamp"].dt.hour * 3600 + out["timestamp"].dt.minute * 60
                 + out["timestamp"].dt.second)
    out["entry_sec"] = entry_sec
    out["w1_formed"] = out["timestamp"].dt.time >= W1_END

    broke_hi = out["or5_t_hi"].notna() & (out["or5_t_hi"] < entry_sec)
    broke_lo = out["or5_t_lo"].notna() & (out["or5_t_lo"] < entry_sec)
    state = np.select(
        [out["or5_high"].isna(),
         broke_hi & broke_lo,
         broke_hi, broke_lo,
         entry_sec < OR5_END_SEC],
        ["unknown", "broke_both", "broke_high", "broke_low", "forming"],
        default="inside")
    out["or5_state_at_entry"] = state

    # Stop position vs W1 extreme (strict; tiebreak T-5: usable as entry-time
    # information only when w1_formed).
    sb = np.select(
        [out["w1_high"].isna() | out["sl"].isna(),
         (out["direction"] == "short") & (out["sl"] > out["w1_high"]),
         (out["direction"] == "long") & (out["sl"] < out["w1_low"])],
        ["unknown", "beyond", "beyond"], default="inside")
    out["stop_vs_w1"] = sb

    # OR5-contradiction state (descriptive only; meaningful for entries >= 9:45)
    contra = np.select(
        [(out["w1_dir"] == "up") & broke_lo,
         (out["w1_dir"] == "down") & broke_hi],
        ["w1up_or5low_broken", "w1down_or5high_broken"], default="consistent")
    out["or5_contradiction"] = np.where(out["w1_dir"].isin(["up", "down"]),
                                        contra, "unknown")
    return out


def reconcile_or_die(df: pd.DataFrame) -> dict:
    """REPLAY_RULES.md §4 — must match Track A exactly or nothing is produced."""
    bm = df[df["benchmark"]]
    full = dict(n=len(bm), wins=int(bm["win"].sum()))
    is_ = bm[bm["split"] == "IS"]
    rc = bm[bm["split"] == "recent"]
    gp = bm.loc[bm["pnl"] > 0, "pnl"].sum()
    gl = -bm.loc[bm["pnl"] < 0, "pnl"].sum()
    pf = gp / gl
    checks = {
        "full n=83": full["n"] == 83,
        "full wins=58": full["wins"] == 58,
        "PF 2.85": abs(pf - 2.846) < 0.005,
        "avg R +0.398": abs(bm["r"].mean() - 0.398) < 0.002,
        "IS n=41": len(is_) == 41,
        "IS wins=23": int(is_["win"].sum()) == 23,
        "recent n=42": len(rc) == 42,
        "recent wins=35": int(rc["win"].sum()) == 35,
    }
    failed = [k for k, v in checks.items() if not v]
    if failed:
        raise ReconciliationError(
            f"Replay does NOT reconcile with Track A benchmark: failed {failed}; "
            f"got full n={full['n']} wins={full['wins']} PF={pf:.3f} "
            f"IS n={len(is_)}/{int(is_['win'].sum())} "
            f"recent n={len(rc)}/{int(rc['win'].sum())}")
    return dict(n=full["n"], wins=full["wins"], pf=round(float(pf), 3),
                avg_r=round(float(bm["r"].mean()), 4),
                is_n=len(is_), is_wins=int(is_["win"].sum()),
                recent_n=len(rc), recent_wins=int(rc["win"].sum()))


def ledger_append(row: dict) -> None:
    out = {c: row.get(c, "") for c in LEDGER_COLS}
    pd.DataFrame([out]).to_csv(LEDGER, mode="a", header=not LEDGER.exists(),
                               index=False)


def bh_qvalues(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)
    q = np.empty(m)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, p[i] * m / (rank + 1))
        q[i] = prev
    return q.tolist()
