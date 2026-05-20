// nq-live-snapshot — Cloudflare Worker.
//
// Polls Databento every minute during pre-open + opening range, derives a
// session-window snapshot (current price, overnight H/L, OR H/L/width),
// caches in Workers KV. Exposes GET /api/live so the briefing dashboard
// can poll for live data without leaking the Databento API key into the
// browser.
//
// Designed to coexist with the morning snapshot in GitHub Pages:
//   - Pages serves briefing.json (morning baseline, ~6:10 AM PT)
//   - Worker serves /api/live (current state, refreshed every minute)
//   - Dashboard merges both client-side
//
// All times in this file are explicit about UTC vs ET. Databento ts_event
// is UTC nanoseconds since epoch (string). We convert to ET via Intl.

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const ALLOWED_ORIGINS = [
  'https://phillipchan1.github.io',
  'http://localhost:8765',
  'http://127.0.0.1:8765',
];

const SNAPSHOT_KEY = 'latest';
const KV_TTL_SECONDS = 24 * 60 * 60;  // 24h — auto-expire stale snapshots

// Databento Historical Timeseries API
const DATABENTO_HOST = 'https://hist.databento.com';
const DATASET = 'GLBX.MDP3';      // CME Globex
const SYMBOL = 'NQ.c.0';          // NQ continuous front month
const SCHEMA = 'ohlcv-1m';        // 1-minute OHLCV bars

// Databento prices for GLBX.MDP3 are fixed-point ints, base unit 1e-9.
const PRICE_SCALE = 1e9;

// Session windows in ET
const RTH_OPEN  = { h: 9,  m: 30 };
const OR_CLOSE  = { h: 10, m: 15 };

// ---------------------------------------------------------------------------
// Worker entrypoints
// ---------------------------------------------------------------------------

export default {
  // HTTP requests — the dashboard polls this.
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const cors = corsHeaders(request);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    // GET /api/live — return the cached snapshot.
    if (url.pathname === '/api/live' && request.method === 'GET') {
      const snapshot = await env.SNAPSHOT_KV.get(SNAPSHOT_KEY, 'json');
      if (!snapshot) {
        return json(
          { error: 'no snapshot yet — cron has not run successfully' },
          { status: 503, cors }
        );
      }
      return json(snapshot, { status: 200, cors });
    }

    // GET /api/refresh — manual trigger for debugging. Polls Databento now.
    if (url.pathname === '/api/refresh' && request.method === 'GET') {
      const result = await pollAndStore(env, 'manual');
      return json(result, { status: result.error ? 500 : 200, cors });
    }

    // Health.
    if (url.pathname === '/' || url.pathname === '/health') {
      return json({
        ok: true,
        ts: new Date().toISOString(),
        endpoints: ['/api/live', '/api/refresh', '/health'],
      }, { status: 200, cors });
    }

    return new Response('Not found', { status: 404, headers: cors });
  },

  // Cron — fires per `triggers.crons` in wrangler.toml.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(pollAndStore(env, event.cron));
  },
};

// ---------------------------------------------------------------------------
// Poll + store
// ---------------------------------------------------------------------------

async function pollAndStore(env, cronOrTrigger) {
  if (!env.DATABENTO_API_KEY) {
    const err = { error: 'DATABENTO_API_KEY secret not set', source: cronOrTrigger };
    console.error(err.error);
    return err;
  }

  const start = Date.now();
  try {
    const snapshot = await fetchSnapshot(env.DATABENTO_API_KEY);
    snapshot.trigger = cronOrTrigger;
    snapshot.poll_duration_ms = Date.now() - start;

    await env.SNAPSHOT_KV.put(SNAPSHOT_KEY, JSON.stringify(snapshot), {
      expirationTtl: KV_TTL_SECONDS,
    });
    console.log(
      `stored snapshot: price=${snapshot.current_price?.toFixed?.(2)} ` +
      `bars=${snapshot.bar_count} in_session=${snapshot.in_session} ` +
      `(${snapshot.poll_duration_ms}ms)`
    );
    return snapshot;
  } catch (e) {
    // Don't overwrite KV on failure — last good snapshot stays.
    console.error('pollAndStore error:', e.message);
    return { error: e.message, trigger: cronOrTrigger, failed_at_utc: new Date().toISOString() };
  }
}

// ---------------------------------------------------------------------------
// Databento client
// ---------------------------------------------------------------------------

async function fetchSnapshot(apiKey) {
  // Fetch last ~6 hours of 1-min bars. Covers overnight + opening-range with
  // margin. Trimmed by Databento if outside trading hours; we adapt downstream.
  const now = new Date();
  const start = new Date(now.getTime() - 6 * 60 * 60 * 1000);

  const params = new URLSearchParams({
    dataset: DATASET,
    symbols: SYMBOL,
    schema: SCHEMA,
    stype_in: 'continuous',
    start: start.toISOString(),
    end: now.toISOString(),
    encoding: 'json',
  });

  const auth = 'Basic ' + btoa(`${apiKey}:`);  // basic auth, empty password
  const url = `${DATABENTO_HOST}/v0/timeseries.get_range?${params.toString()}`;

  const resp = await fetch(url, {
    headers: { 'Authorization': auth, 'Accept': 'application/json' },
    // Cloudflare-specific: don't cache subrequests since this fires every min.
    cf: { cacheTtl: 0, cacheEverything: false },
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Databento HTTP ${resp.status}: ${body.slice(0, 300)}`);
  }

  const text = await resp.text();
  // Response is NDJSON: one bar per line.
  const bars = text.trim().split('\n')
    .filter(line => line)
    .map(line => JSON.parse(line));

  if (bars.length === 0) {
    return {
      error: 'no bars in window',
      fetched_at_utc: now.toISOString(),
      bar_count: 0,
    };
  }

  // Sort ascending by ts_event (string -> BigInt for accurate compare).
  bars.sort((a, b) => {
    const ta = BigInt(a.ts_event);
    const tb = BigInt(b.ts_event);
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });

  return computeSnapshot(bars, now);
}

function computeSnapshot(bars, nowUTC) {
  const px = (b, field) => Number(b[field]) / PRICE_SCALE;

  const last = bars[bars.length - 1];
  const currentPrice = px(last, 'close');

  // Determine today's session windows in ET.
  const etNow = toET(nowUTC);
  const todayET = etNow.dateStr;
  const minNow = etNow.h * 60 + etNow.m;
  const minOpen = RTH_OPEN.h * 60 + RTH_OPEN.m;
  const minORClose = OR_CLOSE.h * 60 + OR_CLOSE.m;

  // Bucket each bar.
  const overnightBars = [];
  const orBars = [];
  const sessionBars = [];

  for (const b of bars) {
    const et = barET(b);
    if (et.dateStr === todayET) {
      const m = et.h * 60 + et.m;
      if (m < minOpen) {
        overnightBars.push(b);
      } else {
        sessionBars.push(b);
        if (m >= minOpen && m < minORClose) orBars.push(b);
      }
    } else {
      // Any bar earlier than today (ET) — definitely overnight from our window
      overnightBars.push(b);
    }
  }

  const snap = {
    current_price: currentPrice,
    current_ts_utc: nanosToIso(BigInt(last.ts_event)),
    fetched_at_utc: nowUTC.toISOString(),
    fetched_at_et: toET(nowUTC).iso,
    bar_count: bars.length,
    pre_open: minNow < minOpen,
    in_session: sessionBars.length > 0,
    overnight: overnightBars.length ? {
      high: Math.max(...overnightBars.map(b => px(b, 'high'))),
      low:  Math.min(...overnightBars.map(b => px(b, 'low'))),
      bar_count: overnightBars.length,
    } : null,
    opening_range: null,
  };

  if (snap.overnight) {
    snap.overnight.range = snap.overnight.high - snap.overnight.low;
  }

  if (orBars.length) {
    const high = Math.max(...orBars.map(b => px(b, 'high')));
    const low  = Math.min(...orBars.map(b => px(b, 'low')));
    snap.opening_range = {
      high,
      low,
      width: high - low,
      bar_count: orBars.length,
      minutes_elapsed: Math.min(orBars.length, 45),
      complete: minNow >= minORClose,
    };
  } else if (minNow >= minOpen) {
    // After 9:30 ET but no OR bars yet — likely the very first minute.
    snap.opening_range = {
      high: null, low: null, width: 0,
      bar_count: 0, minutes_elapsed: 0, complete: false,
    };
  }

  return snap;
}

// ---------------------------------------------------------------------------
// Time helpers
// ---------------------------------------------------------------------------

function toET(d) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).formatToParts(d);
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  const hour = parseInt(p.hour, 10) % 24;  // some locales return "24" at midnight
  return {
    dateStr: `${p.year}-${p.month}-${p.day}`,
    h: hour,
    m: parseInt(p.minute, 10),
    s: parseInt(p.second, 10),
    iso: `${p.year}-${p.month}-${p.day}T${String(hour).padStart(2,'0')}:${p.minute}:${p.second} ET`,
  };
}

function barET(b) {
  const ms = Number(BigInt(b.ts_event) / 1_000_000n);
  return toET(new Date(ms));
}

function nanosToIso(nanos) {
  const ms = Number(nanos / 1_000_000n);
  return new Date(ms).toISOString();
}

// ---------------------------------------------------------------------------
// Response helpers
// ---------------------------------------------------------------------------

function corsHeaders(request) {
  const origin = request.headers.get('Origin') || '';
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin',
  };
}

function json(body, { status = 200, cors = {} } = {}) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      ...cors,
    },
  });
}
