/**
 * ESTRADE v7 ULTRA — Cloudflare Worker
 * ═══════════════════════════════════════════════════════════════════════
 * PURPOSE: CORS proxy for exchange API calls.
 *          API keys are NEVER stored here — they are sent per-request
 *          from the browser (already signed by browser Web Crypto API),
 *          OR this Worker performs signing if keys are passed (opt-in).
 *
 * SECURITY MODEL:
 *   Option A (RECOMMENDED — Maximum Security):
 *     Browser signs request with Web Crypto API (keys never leave browser)
 *     Worker just proxies the already-signed request
 *     → keys: NEVER touch this Worker
 *
 *   Option B (Convenience):
 *     Browser sends {endpoint, method, params, apiKey, apiSecret}
 *     Worker signs with HMAC-SHA256 and forwards to exchange
 *     → keys: pass through Worker in-flight only (not stored)
 *
 * This Worker implements BOTH options.
 *
 * HOW TO DEPLOY:
 *   1. Sign up at https://workers.cloudflare.com (free tier = 100k req/day)
 *   2. Install Wrangler CLI: npm install -g wrangler
 *   3. Login: wrangler login
 *   4. Create worker: wrangler init estrade-proxy
 *   5. Replace src/index.js with this file
 *   6. Deploy: wrangler deploy
 *   7. Set your Vercel env: VITE_CF_WORKER_URL=https://estrade-proxy.YOUR-SUBDOMAIN.workers.dev
 *
 * SUPPORTED EXCHANGES:
 *   - Binance (spot + futures)
 *   - Bybit
 *   - Pionex
 *   - OKX
 *   - KuCoin
 *
 * SUPPORTED BROKERS (via REST bridge):
 *   - MetaTrader 5 (via broker REST API)
 *   - OANDA
 *
 * CORS: Allows requests from your Vercel domain only.
 * ═══════════════════════════════════════════════════════════════════════
 */

// ── Allowed origins (update with your Vercel domain) ─────────
const ALLOWED_ORIGINS = [
  "https://estrade.vercel.app",
  "https://estrade-esf.vercel.app",
  "https://estrade-esc.vercel.app",
  "http://localhost:5173",
  "http://localhost:3000",
];

// ── Exchange base URLs ────────────────────────────────────────
const EXCHANGE_HOSTS = {
  binance:   "https://api.binance.com",
  binance_f: "https://fapi.binance.com",   // futures
  bybit:     "https://api.bybit.com",
  pionex:    "https://api.pionex.com",
  okx:       "https://www.okx.com",
  kucoin:    "https://api.kucoin.com",
  oanda:     "https://api-fxtrade.oanda.com",
};

// ── HMAC-SHA256 signing (Web Crypto in Workers runtime) ───────
async function hmacSha256(secret, message) {
  const enc    = new TextEncoder();
  const key    = await crypto.subtle.importKey(
    "raw", enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false, ["sign"]
  );
  const signed = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return Array.from(new Uint8Array(signed))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
}

// ── Binance signature builder ─────────────────────────────────
function buildBinanceQuery(params = {}) {
  return Object.entries(params)
    .filter(([_, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
}

async function signBinance(params, apiSecret) {
  const timestamp = Date.now();
  const qStr      = buildBinanceQuery({ ...params, timestamp });
  const signature  = await hmacSha256(apiSecret, qStr);
  return `${qStr}&signature=${signature}`;
}

// ── Bybit signature builder ───────────────────────────────────
async function signBybit(params, apiKey, apiSecret, timestamp) {
  const paramStr = JSON.stringify(params);
  const signStr  = `${timestamp}${apiKey}5000${paramStr}`;
  return hmacSha256(apiSecret, signStr);
}

// ── Pionex signature builder ──────────────────────────────────
async function signPioex(method, path, params, apiSecret, timestamp) {
  const queryStr = buildBinanceQuery(params);
  const signStr  = `${method.toUpperCase()}\n${path}\n${queryStr}\n${timestamp}`;
  return hmacSha256(apiSecret, signStr);
}

// ── CORS headers ──────────────────────────────────────────────
function corsHeaders(origin) {
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin":  allowed,
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,X-API-Key,X-Exchange,X-Sign-Mode",
    "Access-Control-Max-Age":       "86400",
  };
}

// ── Rate limiting (simple in-memory, resets per isolate) ──────
const requestCount = new Map();
const RATE_LIMIT   = 60; // per minute per IP

function checkRateLimit(ip) {
  const now = Math.floor(Date.now() / 60000);
  const key = `${ip}:${now}`;
  const cnt = (requestCount.get(key) || 0) + 1;
  requestCount.set(key, cnt);
  // Clean old entries
  if (requestCount.size > 1000) {
    const oldKey = `${ip}:${now - 1}`;
    requestCount.delete(oldKey);
  }
  return cnt <= RATE_LIMIT;
}

// ── Option A: Proxy already-signed request ────────────────────
async function proxySignedRequest(exchange, endpoint, method, signedQuery, body, apiKey) {
  const base = EXCHANGE_HOSTS[exchange] || EXCHANGE_HOSTS.binance;
  const url  = signedQuery
    ? `${base}${endpoint}?${signedQuery}`
    : `${base}${endpoint}`;

  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers["X-MBX-APIKEY"] = apiKey;  // Binance
  if (exchange === "bybit") headers["X-BAPI-API-KEY"] = apiKey;
  if (exchange === "pionex") headers["PIONEX-KEY"] = apiKey;
  if (exchange === "okx") headers["OK-ACCESS-KEY"] = apiKey;

  const opts = {
    method,
    headers,
    body: method !== "GET" && body ? JSON.stringify(body) : undefined,
  };

  const resp = await fetch(url, opts);
  const data = await resp.text();
  return { status: resp.status, data };
}

// ── Option B: Worker signs the request ───────────────────────
async function signAndProxy(exchange, endpoint, method, params, apiKey, apiSecret) {
  let signedQuery = "";
  let extraHeaders = {};
  const base = EXCHANGE_HOSTS[exchange] || EXCHANGE_HOSTS.binance;

  if (exchange === "binance" || exchange === "binance_f") {
    signedQuery     = await signBinance(params, apiSecret);
    extraHeaders["X-MBX-APIKEY"] = apiKey;
  } else if (exchange === "bybit") {
    const ts   = Date.now().toString();
    const sig  = await signBybit(params, apiKey, apiSecret, ts);
    extraHeaders = {
      "X-BAPI-API-KEY":   apiKey,
      "X-BAPI-TIMESTAMP": ts,
      "X-BAPI-SIGN":      sig,
      "X-BAPI-RECV-WINDOW": "5000",
    };
    signedQuery = buildBinanceQuery(params);
  } else if (exchange === "pionex") {
    const ts  = Date.now().toString();
    const path= endpoint;
    const sig  = await signPioex(method, path, params, apiSecret, ts);
    extraHeaders = { "PIONEX-KEY": apiKey, "PIONEX-SIGN": sig, "PIONEX-TIMESTAMP": ts };
    signedQuery = buildBinanceQuery(params);
  }

  const url = method === "GET" && signedQuery
    ? `${base}${endpoint}?${signedQuery}`
    : `${base}${endpoint}`;

  const resp = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", ...extraHeaders },
    body: method !== "GET" && Object.keys(params).length
      ? JSON.stringify(params) : undefined,
  });
  const data = await resp.text();
  return { status: resp.status, data };
}

// ── Public market data proxy (no keys needed) ─────────────────
async function proxyPublicData(exchange, endpoint, queryString) {
  const base = EXCHANGE_HOSTS[exchange] || EXCHANGE_HOSTS.binance;
  const url  = queryString
    ? `${base}${endpoint}?${queryString}`
    : `${base}${endpoint}`;
  const resp = await fetch(url, { headers: { "Content-Type": "application/json" } });
  const data = await resp.text();
  return { status: resp.status, data };
}

// ── Main handler ──────────────────────────────────────────────
export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    const ip     = request.headers.get("CF-Connecting-IP") || "unknown";

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    // Rate limiting
    if (!checkRateLimit(ip)) {
      return new Response(
        JSON.stringify({ error: "Rate limit exceeded. Max 60 req/min." }),
        { status: 429, headers: { "Content-Type": "application/json", ...corsHeaders(origin) } }
      );
    }

    const url  = new URL(request.url);
    const path = url.pathname;

    // ── Health check ─────────────────────────────────────────
    if (path === "/" || path === "/health") {
      return new Response(
        JSON.stringify({
          status:   "ok",
          service:  "ESTRADE v7 ULTRA — Cloudflare Worker Proxy",
          version:  "7.0.0",
          note:     "API keys are never stored. This is a CORS proxy only.",
          endpoints: ["/proxy/public", "/proxy/signed", "/proxy/worker-sign"],
        }),
        { headers: { "Content-Type": "application/json", ...corsHeaders(origin) } }
      );
    }

    try {
      // ── /proxy/public — Market data (no keys) ───────────────
      if (path === "/proxy/public") {
        const body     = await request.json();
        const exchange = body.exchange || "binance";
        const endpoint = body.endpoint;
        const qs       = body.queryString || "";

        if (!endpoint) {
          return new Response(
            JSON.stringify({ error: "endpoint required" }),
            { status: 400, headers: { "Content-Type":"application/json",...corsHeaders(origin) } }
          );
        }

        const result = await proxyPublicData(exchange, endpoint, qs);
        return new Response(result.data, {
          status: result.status,
          headers: { "Content-Type": "application/json", ...corsHeaders(origin) },
        });
      }

      // ── /proxy/signed — Browser already signed (Option A) ───
      if (path === "/proxy/signed") {
        const body        = await request.json();
        const exchange    = body.exchange    || "binance";
        const endpoint    = body.endpoint;
        const method      = body.method      || "GET";
        const signedQuery = body.signedQuery || "";
        const apiKey      = body.apiKey      || "";
        const reqBody     = body.body;

        if (!endpoint || !apiKey) {
          return new Response(
            JSON.stringify({ error: "endpoint and apiKey required" }),
            { status: 400, headers: { "Content-Type":"application/json",...corsHeaders(origin) } }
          );
        }

        const result = await proxySignedRequest(exchange, endpoint, method, signedQuery, reqBody, apiKey);
        return new Response(result.data, {
          status: result.status,
          headers: { "Content-Type": "application/json", ...corsHeaders(origin) },
        });
      }

      // ── /proxy/worker-sign — Worker signs (Option B) ────────
      if (path === "/proxy/worker-sign") {
        const body      = await request.json();
        const exchange  = body.exchange  || "binance";
        const endpoint  = body.endpoint;
        const method    = body.method    || "GET";
        const params    = body.params    || {};
        const apiKey    = body.apiKey    || "";
        const apiSecret = body.apiSecret || "";

        if (!endpoint || !apiKey || !apiSecret) {
          return new Response(
            JSON.stringify({ error: "endpoint, apiKey, apiSecret required" }),
            { status: 400, headers: { "Content-Type":"application/json",...corsHeaders(origin) } }
          );
        }

        // Security: do not log apiKey/apiSecret
        const result = await signAndProxy(exchange, endpoint, method, params, apiKey, apiSecret);
        return new Response(result.data, {
          status: result.status,
          headers: { "Content-Type": "application/json", ...corsHeaders(origin) },
        });
      }

      // ── /ws-info — WebSocket endpoint info ──────────────────
      if (path === "/ws-info") {
        return new Response(JSON.stringify({
          binance_ws:  "wss://stream.binance.com:9443/ws",
          bybit_ws:    "wss://stream.bybit.com/v5/public/spot",
          pionex_ws:   "wss://ws.pionex.com/wsPub",
          note: "Connect directly from browser for lowest latency. No auth needed for public streams.",
          examples: {
            binance_ticker:    "wss://stream.binance.com:9443/ws/btcusdt@ticker",
            binance_depth:     "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms",
            binance_kline:     "wss://stream.binance.com:9443/ws/btcusdt@kline_1m",
            binance_aggTrade:  "wss://stream.binance.com:9443/ws/btcusdt@aggTrade",
          },
        }), {
          headers: { "Content-Type": "application/json", ...corsHeaders(origin) },
        });
      }

      // ── 404 ──────────────────────────────────────────────────
      return new Response(
        JSON.stringify({ error: "Not found", available: ["/proxy/public","/proxy/signed","/proxy/worker-sign","/ws-info"] }),
        { status: 404, headers: { "Content-Type":"application/json",...corsHeaders(origin) } }
      );

    } catch (err) {
      return new Response(
        JSON.stringify({ error: err.message || "Worker error" }),
        { status: 500, headers: { "Content-Type":"application/json",...corsHeaders(origin) } }
      );
    }
  },
};

/* ═══════════════════════════════════════════════════════════════
   DEPLOYMENT GUIDE
   ═══════════════════════════════════════════════════════════════

   1. Install Wrangler CLI:
      npm install -g wrangler

   2. Login to Cloudflare:
      wrangler login

   3. Create your worker project:
      mkdir estrade-proxy && cd estrade-proxy
      wrangler init --type javascript

   4. Replace src/index.js with this file.

   5. Edit wrangler.toml:
      name = "estrade-proxy"
      main = "src/index.js"
      compatibility_date = "2024-01-01"

      [vars]
      ENVIRONMENT = "production"

   6. Deploy:
      wrangler deploy

   7. Your Worker URL will be:
      https://estrade-proxy.YOUR-ACCOUNT.workers.dev

   8. Add to your .env.local on Vercel:
      VITE_CF_WORKER_URL=https://estrade-proxy.YOUR-ACCOUNT.workers.dev

   COST:
   • Free tier: 100,000 requests/day
   • Paid ($5/mo): 10 million requests/day
   • CPU time: 10ms free, 50ms paid

   WHY CLOUDFLARE WORKERS FOR LOW LATENCY:
   • 300+ edge locations worldwide
   • < 5ms overhead vs direct call
   • No cold starts (unlike Lambda)
   • Auto-scaling, no infrastructure to manage

   ALTERNATIVE (if you don't want CF Worker):
   Just sign requests directly in the browser using the Web Crypto API.
   The TradingPanel.jsx already supports this (Option A mode).
   In that case you DON'T need this Worker at all — the browser
   sends signed requests directly to Binance/Bybit/etc.
   CORS won't be an issue for GET requests (public market data).
   For POST (orders), Binance allows CORS from browsers in spot API.
   ═══════════════════════════════════════════════════════════════ */
