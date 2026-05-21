# Slim Python base — only ~50MB; pandas/numpy add ~70MB but we're still
# comfortably under Fly.io's 256MB free VM memory budget.
#
# Build context (set in fly.toml [build]) is the REPO ROOT so COPY can
# reach both flyio/* and the sibling fvgc/ package. Paths below are
# relative to that root.
FROM python:3.11-slim

# Avoid .pyc files + stdout buffering inside containers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first so Docker layer cache stays warm across app code edits.
COPY flyio/requirements.txt .
RUN pip install -r requirements.txt

# Application code.
COPY flyio/app.py .

# FVGC engine — imported by app.py to detect FVG signals on the live
# 1s stream (aggregated to 30s). Importing the canonical engine instead
# of re-implementing it ensures the dashboard's "missed signal" view
# matches the backtest behavior bit-for-bit.
COPY fvgc/ ./fvgc/

# Morning briefing pipeline — moved from GH Actions to Fly.io for
# reliable scheduling. The script + its non-CSV dependencies total
# ~2MB; we copy only the paths morning_briefing.py actually reads
# (NOT the huge nq_1m_csv / liquidity_levels.csv from briefing_config —
# those are config-declared but unreferenced).
COPY tools/                                              ./tools/
COPY playbook/                                           ./playbook/
COPY analysis/results/combo_top_results.txt              ./analysis/results/
COPY studies/factor_importance/results/factor_importance_report.txt \
                                                         ./studies/factor_importance/results/
COPY studies/or_width_predictor/results/features.csv     ./studies/or_width_predictor/results/
COPY studies/or_width_predictor/results/model_cold_start.json \
                                                         ./studies/or_width_predictor/results/
COPY studies/or_width_predictor/results/walkforward_performance.csv \
                                                         ./studies/or_width_predictor/results/
COPY studies/multi_cell_confluence/results/              ./studies/multi_cell_confluence/results/
COPY data/raw/market_high_volume_events_2020_2025.csv    ./data/raw/
COPY data/trading_days/trading_days.csv                  ./data/trading_days/

# Fly's default internal port is 8080 — keep that convention.
EXPOSE 8080

# Single worker is right: we have a long-running background thread (the
# Databento Live client) holding shared state. Multiple workers would each
# open their own subscription, wasting Databento bandwidth + diverging state.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
