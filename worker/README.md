# `nq-live-snapshot` — live data middleware

Cloudflare Worker that polls Databento every minute during the trading day
and caches an NQ session snapshot in Workers KV. The briefing dashboard at
[github.io/fvgc-ultra-backtest](https://phillipchan1.github.io/fvgc-ultra-backtest/)
polls this Worker's `/api/live` endpoint for the live overlay on top of the
morning baseline.

## What it does

```
Cloudflare cron (1-min, weekdays 10–15 UTC)
       │
       ▼
  Worker polls Databento Historical Timeseries API
       │   GET /v0/timeseries.get_range  (last 6h of 1-min OHLCV)
       │   Auth: HTTP Basic, DATABENTO_API_KEY as username
       ▼
  Computes session snapshot:
       │   • current_price + timestamp
       │   • overnight H/L/range (bars before 9:30 ET today)
       │   • opening_range H/L/width + minutes_elapsed (9:30–10:15 ET)
       │   • pre_open / in_session flags
       ▼
  Workers KV ← latest snapshot (TTL 24h)
       │
       ▼
  GET /api/live  →  Dashboard polls this every ~10s
```

The Worker is **stateless** — Cloudflare invokes it from any edge POP, it reads
KV and returns. Cron triggers run on Cloudflare's infrastructure with no
dedicated server. The Databento API key is stored as a Worker secret and never
reaches the browser.

## Endpoints

| Path | Method | Purpose |
|---|---|---|
| `/api/live` | GET | Return the cached snapshot (JSON). `503` if cron hasn't run yet. |
| `/api/refresh` | GET | Force a Databento poll right now. Useful for debugging. |
| `/health` | GET | Heartbeat. |

CORS allowed origins are hardcoded in `src/index.js` — currently:
- `https://phillipchan1.github.io`
- `http://localhost:8765` (local dashboard via `python -m http.server`)

## One-time setup

You'll need a (free) Cloudflare account and a Databento API key.

```bash
# 1. Install wrangler locally
cd worker
npm install

# 2. Authenticate (opens browser)
npx wrangler login

# 3. Create the KV namespace
npx wrangler kv namespace create SNAPSHOT_KV
# Copy the returned `id = "..."` value and paste it into wrangler.toml,
# replacing REPLACE_WITH_KV_NAMESPACE_ID

# 4. Store the Databento API key as a Worker secret
npx wrangler secret put DATABENTO_API_KEY
# (paste your key when prompted, then Enter)

# 5. Deploy
npx wrangler deploy
```

The deploy command prints the Worker URL (something like
`https://nq-live-snapshot.<your-cf-subdomain>.workers.dev`). That URL is what
the dashboard fetches from.

## Smoke-test after deploy

```bash
# Force a poll and inspect the snapshot
curl -s https://nq-live-snapshot.<your-cf-subdomain>.workers.dev/api/refresh | jq

# After the first cron has fired:
curl -s https://nq-live-snapshot.<your-cf-subdomain>.workers.dev/api/live | jq
```

Expected snapshot shape:

```json
{
  "current_price": 21487.25,
  "current_ts_utc": "2026-05-19T14:31:00.000Z",
  "fetched_at_utc": "2026-05-19T14:31:42.123Z",
  "fetched_at_et": "2026-05-19T10:31:42 ET",
  "bar_count": 240,
  "pre_open": false,
  "in_session": true,
  "overnight": {
    "high": 21520.00,
    "low":  21435.50,
    "range": 84.50,
    "bar_count": 195
  },
  "opening_range": {
    "high": 21505.25,
    "low":  21478.00,
    "width": 27.25,
    "bar_count": 1,
    "minutes_elapsed": 1,
    "complete": false
  },
  "trigger": "* 10-15 * * 1-5",
  "poll_duration_ms": 380
}
```

## Local development

```bash
# Run the Worker on localhost:8787
npx wrangler dev

# In another shell:
curl http://localhost:8787/api/refresh | jq    # forces a live Databento poll
curl http://localhost:8787/api/live | jq
```

You'll need to put your Databento key in `worker/.dev.vars` for local dev:
```
DATABENTO_API_KEY=db-xxxxxxxxxxxxxxxxxxxxxx
```
(That file is in `.gitignore` — never committed.)

## Tail logs

```bash
npx wrangler tail
```
Shows live `console.log` output from cron + HTTP invocations.

## Costs

| Resource | Free tier | This Worker uses |
|---|---|---|
| Worker requests | 100k/day | ~5k/day (cron + dashboard polling) |
| KV reads | 100k/day | ~2k/day |
| KV writes | 1k/day | ~360/day (1/min during the 6h cron window) |
| Workers KV storage | 1 GB | ~1 KB |
| Databento Historical | per your subscription | ~360 requests/day, each ~6h of 1-min bars |

Stays comfortably inside Cloudflare's free tier. The only real cost is Databento.
