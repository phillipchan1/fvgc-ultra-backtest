#!/usr/bin/env bash
#
# Regenerate the full FVGC data + baseline pipeline from raw 1s NQ + VIXY.
#
# Prereqs (must exist on disk):
#   data/raw/glbx-mdp3-*.ohlcv-1s.csv         (NQ.FUT 1s history from Databento)
#   data/raw/xnas-itch-*.ohlcv-1h.csv         (VIXY 1h history from Databento)
#   data/raw/market_high_volume_events_*.csv  (red folder events)
#
# Pipeline steps (each fail-fast):
#   1. Consolidate 1s -> 7 timeframes (15s/30s/1m/2m/3m/5m/15m) as parquet+csv
#   2. Validate new 1m vs prior raw 1m (sanity check; warns on regression)
#   3. Build trading_days.csv (~2,158 days w/ 63 columns)
#   4. Build liquidity_levels.csv (sessions + HTF FVGs across 15m/1H/4H/Daily)
#   5. Build daily_volume_profile.csv (POC/VAH/VAL per RTH day)
#   6. Run baselines (30s canonical + 1m/2m/3m) — emits trades.csv + fvgs.csv
#
# Runtime on M-series Mac:
#   step 1: ~3 min   (polars streaming over ~11GB CSV)
#   step 2: ~30 sec
#   step 3: ~2 min
#   step 4-5: ~3 min combined
#   step 6: baselines run in parallel — 1m/2m/3m finish in ~2h, 30s in ~8h
#           (30s alone is the long tail; the rest are quick)
#
# Usage:
#   bash tools/regenerate_all.sh                # full pipeline
#   bash tools/regenerate_all.sh --skip-30s     # skip the 8h 30s baseline
#   bash tools/regenerate_all.sh --data-only    # skip baselines entirely
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_30S=0
DATA_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --skip-30s)  SKIP_30S=1 ;;
    --data-only) DATA_ONLY=1 ;;
    -h|--help)
      sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "unknown arg: $arg"; exit 2 ;;
  esac
done

mkdir -p logs
LOG="logs/regenerate_$(date +%Y%m%d_%H%M%S).log"
echo "Logging to $LOG"

step() {
  local label="$1"; shift
  local t0
  t0=$(date +%s)
  echo
  echo "=========================================================="
  echo "==  [$(date +%H:%M:%S)] $label"
  echo "=========================================================="
  "$@" 2>&1 | tee -a "$LOG"
  local rc=${PIPESTATUS[0]}
  local dt=$(( $(date +%s) - t0 ))
  if [[ $rc -ne 0 ]]; then
    echo "FAIL: $label (rc=$rc, ${dt}s)" | tee -a "$LOG"
    exit $rc
  fi
  echo "OK:   $label (${dt}s)" | tee -a "$LOG"
}

# Sanity: prereqs present?
if ! ls data/raw/glbx-mdp3-*.ohlcv-1s.csv >/dev/null 2>&1; then
  echo "ERROR: no data/raw/glbx-mdp3-*.ohlcv-1s.csv found. Need NQ 1s history from Databento."
  exit 1
fi
if ! ls data/raw/xnas-itch-*.ohlcv-1h.csv >/dev/null 2>&1; then
  echo "ERROR: no data/raw/xnas-itch-*.ohlcv-1h.csv found. Need VIXY 1h history from Databento."
  exit 1
fi

# --- DATA LAYER -------------------------------------------------------------
step "1/6  Consolidate 1s -> all timeframes"                  python3 tools/consolidate_data.py
step "2/6  Validate consolidation vs prior 1m baseline"        python3 tools/validate_consolidation.py
step "3/6  Build trading_days.csv"                             python3 data/trading_days/build_trading_days.py
step "4/6  Build liquidity_levels.csv (sessions + HTF FVGs)"   python3 data/levels/build_liquidity_levels.py
step "5/6  Build daily_volume_profile.csv"                     python3 data/levels/build_volume_profile.py

if [[ $DATA_ONLY -eq 1 ]]; then
  echo
  echo "==  --data-only: skipping baselines."
  exit 0
fi

# --- BASELINES --------------------------------------------------------------
# 1m / 2m / 3m run in parallel (independent, CPU-bound).
echo
echo "=========================================================="
echo "==  [$(date +%H:%M:%S)] 6/6  Running baselines (1m, 2m, 3m in parallel)"
echo "=========================================================="

python3 -u studies/baseline_1m/run.py > logs/baseline_1m.log 2>&1 &
P1=$!
python3 -u studies/baseline_2m/run.py > logs/baseline_2m.log 2>&1 &
P2=$!
python3 -u studies/baseline_3m/run.py > logs/baseline_3m.log 2>&1 &
P3=$!
echo "  spawned 1m=$P1 2m=$P2 3m=$P3"

# Wait, propagate failures
fail=0
for pid_label in "$P1 1m" "$P2 2m" "$P3 3m"; do
  set -- $pid_label
  if wait "$1"; then
    echo "  OK  baseline_$2  (PID $1)"
  else
    echo "  FAIL baseline_$2 (PID $1)"
    fail=1
  fi
done
[[ $fail -eq 1 ]] && exit 1

if [[ $SKIP_30S -eq 1 ]]; then
  echo
  echo "==  --skip-30s: skipping canonical 30s baseline."
  echo "    (Run separately with: python3 studies/baseline/run.py)"
  exit 0
fi

# 30s canonical — runs SOLO because it dominates wall time (~5-8h).
# If you don't want to wait, re-run with --skip-30s.
step "6/6b Run canonical 30s baseline (~5-8h)"  python3 -u studies/baseline/run.py

echo
echo "=========================================================="
echo "==  DONE.  Full pipeline complete."
echo "=========================================================="
