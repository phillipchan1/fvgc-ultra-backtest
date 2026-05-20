# Slim Python base — only ~50MB, runs comfortably in Fly.io's 256MB free VM.
FROM python:3.11-slim

# Avoid .pyc files + stdout buffering inside containers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first so Docker layer cache stays warm across app code edits.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .

# Fly's default internal port is 8080 — keep that convention.
EXPOSE 8080

# Single worker is right: we have a long-running background thread (the
# Databento Live client) holding shared state. Multiple workers would each
# open their own subscription, wasting Databento bandwidth + diverging state.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
