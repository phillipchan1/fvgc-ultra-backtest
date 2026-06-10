"""Phase 1 — harness sanity check: reproduce the benchmark exactly.

Target (Phase 0 re-derivation, full 8yr, no quality filter):
  opening-window short no-PS: n=83, WR 69.9%, PF 2.85
Then report the same cohort on the program basis (quality filter applied),
its IS portion, and per-fold stability.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import load_program_trades, benchmark_mask, evaluate, CACHE  # noqa: E402

import pandas as pd  # noqa: E402

df = load_program_trades()

# 1) exact reproduction vs Phase 0 (full sample; quality filter may remove trades —
#    check raw first by rebuilding without the filter)
raw = pd.read_csv(CACHE / "baseline_trades_8yr.csv",
                  parse_dates=["timestamp", "fvg_created_at"])
raw = raw[raw["outcome"].isin(["win", "loss"])].copy()
raw["win"] = (raw["outcome"] == "win").astype(int)
from datetime import time as dtime  # noqa: E402
tod = raw["fvg_created_at"].dt.time
m_raw = ((tod >= dtime(9, 29, 30)) & (tod <= dtime(9, 31, 0))
         & (raw["direction"] == "short") & (raw["variant"] != "protected_swing"))
bm_raw = raw[m_raw]
gp = bm_raw.loc[bm_raw.pnl > 0, "pnl"].sum()
gl = -bm_raw.loc[bm_raw.pnl < 0, "pnl"].sum()
print(f"RAW reproduction:    n={len(bm_raw)}  WR={100*bm_raw['win'].mean():.1f}%  "
      f"PF={gp/gl:.2f}   (target n=83, 69.9%, 2.85)")
assert len(bm_raw) == 83 and abs(100 * bm_raw["win"].mean() - 69.9) < 0.1, \
    "Benchmark reproduction FAILED"

# 2) program basis (quality-filtered), full sample — pre-registered benchmark stat
r_all = evaluate(df, benchmark_mask(df), test_id="p1_benchmark_all", phase=1,
                 hypothesis="benchmark reproduction on program basis",
                 cohort="ow_short_noPS", split="ALL",
                 notes="sanity: quality-filtered full sample")
print(f"Program basis (ALL): n={r_all['n']}  WR={r_all['WR']}%  PF={r_all['PF']}  "
      f"avg_r={r_all['avg_r']}  maxLL={r_all['max_consec_losses']}")

# 3) IS-only benchmark + fold stability (this is the Phase 3 comparison cohort)
r_is = evaluate(df, benchmark_mask(df), test_id="p1_benchmark_is", phase=1,
                hypothesis="benchmark on IS only", cohort="ow_short_noPS",
                split="IS", notes="sanity: IS portion of benchmark")
print(f"IS only:             n={r_is['n']}  WR={r_is['WR']}%  PF={r_is['PF']}  "
      f"p={r_is['p_value']:.4f} vs IS base {r_is['base_wr']}%")
print(f"folds: {r_is['folds']}  same_sign={r_is['folds_same_sign']}/4")

# 4) split sizes
print("\nsplit sizes:", df.groupby("split").size().to_dict())
print("IS folds:", df[df.split == 'IS'].groupby("fold").size().to_dict())
print("OOS trades are LOCKED until Phase 5.")
