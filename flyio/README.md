# `nq-live-snapshot` — Fly.io live data service

Persistent Python process holding a Databento Live connection for NQ
futures 1-min bars. Exposes `GET /api/live` returning a session-window
snapshot fresh to within ~1-2 seconds. The dashboard polls this URL
during the trading day in place of the slower Cloudflare Worker.

## Why this exists

Databento's Live API is a streaming protocol over TLS — bars arrive as
they're published (sub-second lag). Cloudflare Workers can't hold
persistent connections (invocation-based, max 30s per run), so we run
the streaming consumer on a small always-on Fly.io VM. Free tier
covers it.

## Architecture

```
Databento Live  (TLS stream)
       │
       ▼
 Fly.io VM (shared-cpu-1x, 256MB, always-on)
   ├── threading.Thread: holds Live connection, ingests bars
   ├── In-memory ring buffer: last 24h of 1-min bars
   ├── On every bar: recompute snapshot (overnight, OR, current price)
   └── FastAPI: GET /api/live  →  JSON snapshot
       │
       ▼
 Dashboard (GitHub Pages, polls every ~10s)
```

Single VM, single process, single worker, single Live subscription.
Multi-instance would cause duplicate Databento subs and diverging state —
we explicitly stay single-instance via `min_machines_running = 1` +
`auto_stop_machines = "off"`.

## One-time setup

You'll need:
- A Fly.io account (free, no card required at this tier)
- Your Databento API key (the same one used by the Cloudflare Worker)

```bash
# 1. Install flyctl
brew install flyctl   # or: curl -L https://fly.io/install.sh | sh

# 2. Sign up / log in
fly auth signup       # or: fly auth login

# 3. Launch the app (only the first time)
cd flyio
fly launch --copy-config --no-deploy
# When prompted:
#   - "Choose an app name" → either accept nq-live-snapshot or pick your own
#   - "Choose a region" → iad (US East), or whichever is closest
#   - "Would you like to set up a Postgresql database?" → No
#   - "Would you like to set up an Upstash Redis database?" → No
#   - "Would you like to deploy now?" → No  (we set secrets first)

# 4. Set the Databento secret
fly secrets set DATABENTO_API_KEY="db-xxxxxxxxxxxxxxxxxxxxxxxxxx"

# 5. Deploy
fly deploy

# 6. Verify
fly status                              # machine running?
fly logs                                # see the live thread connect
curl https://<your-app>.fly.dev/health  # connected: true, bar_count > 0
curl https://<your-app>.fly.dev/api/live | jq
```

## Endpoints

| Path | Purpose |
|---|---|
| `GET /` | Service identity |
| `GET /health` | Connection status, bar count, uptime, last error |
| `GET /api/live` | Latest session snapshot (the dashboard polls this) |

## Snapshot shape (`/api/live`)

```json
{
  "current_price": 21487.25,
  "current_ts_utc": "2026-05-20T14:31:00.000Z",
  "current_ts_et": "2026-05-20T10:31:00-04:00",
  "fetched_at_utc": "2026-05-20T14:31:02.183Z",
  "fetched_at_et": "2026-05-20T10:31:02-04:00",
  "lag_seconds": 2,
  "bar_count": 1380,
  "pre_open": false,
  "in_session": true,
  "source": "databento-live",
  "overnight": {
    "high": 21520.00,
    "low":  21435.50,
    "range": 84.50,
    "bar_count": 1020
  },
  "opening_range": {
    "high": 21505.25,
    "low":  21478.00,
    "width": 27.25,
    "bar_count": 1,
    "minutes_elapsed": 1,
    "complete": false
  }
}
```

Compare to the Cloudflare Worker's snapshot — same shape, same fields,
just `lag_seconds` ~2 instead of ~900. The dashboard can swap data
sources without any client code changes.

## Local development

```bash
cd flyio
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Put your key in a local env var (don't commit it)
export DATABENTO_API_KEY="db-xxxx..."

uvicorn app:app --reload --host 0.0.0.0 --port 8080

# In another shell:
curl http://localhost:8080/health
curl http://localhost:8080/api/live | jq
```

## Cost

- Fly.io free tier: 3× shared-cpu-1x VMs, 256MB each, always-on. We use 1. **$0/month.**
- Outbound bandwidth: ~100MB/day from polling + Databento stream. Well inside free tier.
- Databento Live: already covered by your Standard plan ($179/mo). One subscription.

## Failure modes

- **Connection drops** → live thread reconnects with exponential backoff (1s → 2s → 4s → ... → 60s cap). Snapshot stays at last-known-good during disconnect; `lag_seconds` grows accordingly.
- **Fly machine restart** → snapshot empty until backfill completes (~10s of Historical fetch on startup), then resumes streaming.
- **Databento outage** → service returns last snapshot with growing `lag_seconds`; dashboard's "live" indicator should flip stale based on `lag_seconds` threshold.

## Logs

```bash
fly logs            # live tail
fly logs -i 5m      # last 5 minutes
```

Look for lines like:
```
INFO nq-live: Live subscription active — listening for bars
INFO nq-live: Historical backfill: ingested 1380 bars
```
