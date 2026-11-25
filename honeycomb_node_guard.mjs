// Honeycomb additive Node runtime guard. It does not replace any engine or order API.
// It shares .honeycomb_runtime/binance_guard.json with the Python guard.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));

function loadEnvFile() {
  const envPath = path.join(ROOT, '.env');
  try {
    for (const raw of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const [key, ...rest] = line.split('=');
      if (key && process.env[key] === undefined) {
        process.env[key] = rest.join('=').trim().replace(/^['"]|['"]$/g, '');
      }
    }
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
}
loadEnvFile();

const RUNTIME = path.join(ROOT, '.honeycomb_runtime');
const STATE = path.join(RUNTIME, 'binance_guard.json');
// This exact lock path and O_EXCL protocol are shared with honeycomb_execution_guard.py.
const LOCK = path.join(RUNTIME, 'binance_guard.lock');
const LOCK_STALE_MS = 60_000;
fs.mkdirSync(RUNTIME, { recursive: true });

function positiveLimit(name, fallback) {
  const raw = process.env[name];
  const value = raw === undefined || raw.trim() === '' ? fallback : Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} must be a finite positive number`);
  }
  return value;
}
const SAFE_WEIGHT = positiveLimit('BINANCE_SAFE_WEIGHT_PER_MIN', 900);
const SAFE_ORDERS = positiveLimit('BINANCE_SAFE_ORDERS_PER_10S', 60);
const HOSTS = new Set(['fapi.binance.com','dapi.binance.com','testnet.binancefuture.com','demo-fapi.binance.com']);

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}
function withLock(fn) {
  for (;;) {
    let fd;
    try {
      fd = fs.openSync(LOCK, 'wx', 0o600);
      fs.writeFileSync(fd, `${process.pid} ${Date.now()}\n`);
    } catch (error) {
      if (fd !== undefined) {
        const own = fs.fstatSync(fd);
        fs.closeSync(fd);
        try {
          const current = fs.statSync(LOCK);
          if (current.dev === own.dev && current.ino === own.ino) fs.unlinkSync(LOCK);
        } catch {}
      }
      if (error?.code !== 'EEXIST') throw error;
      try {
        const previous = fs.statSync(LOCK);
        if (Date.now() - previous.mtimeMs > LOCK_STALE_MS) {
          const current = fs.statSync(LOCK);
          if (current.dev === previous.dev && current.ino === previous.ino) {
            fs.unlinkSync(LOCK);
            continue;
          }
        }
      } catch (statError) {
        if (statError?.code === 'ENOENT') continue;
        throw statError;
      }
      sleep(25);
      continue;
    }

    try {
      return fn();
    } finally {
      try {
        const own = fs.fstatSync(fd);
        const current = fs.statSync(LOCK);
        if (current.dev === own.dev && current.ino === own.ino) fs.unlinkSync(LOCK);
      } catch {}
      fs.closeSync(fd);
    }
  }
}
function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch { return {}; }
}
function saveState(s) {
  const tmp = `${STATE}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(s), { mode: 0o600 });
  fs.renameSync(tmp, STATE);
}
function weight(url) {
  const u = new URL(url); const p = u.pathname; const limit = Number(u.searchParams.get('limit') || 500);
  if (p.endsWith('/klines')) return limit < 100 ? 1 : limit < 500 ? 2 : limit <= 1000 ? 5 : 10;
  if (p.endsWith('/exchangeInfo')) return 1;
  if (p.endsWith('/ticker/bookTicker')) return u.searchParams.has('symbol') ? 2 : 5;
  if (p.endsWith('/ticker/price') || p.endsWith('/premiumIndex') || p.endsWith('/time')) return 1;
  if (p.endsWith('/balance') || p.endsWith('/account') || p.endsWith('/positionRisk')) return 5;
  if (p.endsWith('/userTrades')) return 5;
  return 1;
}
function isOrder(url) {
  const p = new URL(url).pathname;
  return p.endsWith('/order') || p.endsWith('/allOpenOrders') || p.endsWith('/leverage') || p.endsWith('/marginType');
}
function acquire(w, order) {
  for (;;) {
    const now = Date.now() / 1000;
    const wait = withLock(() => {
      const s = loadState();
      const ban = Number(s.ban_until || 0);
      if (ban > now) throw new Error(`BINANCE_GUARD_BAN ${(ban-now).toFixed(1)}s remaining`);
      let ws = Number(s.weight_window_start || now), used = Number(s.weight_used || 0);
      if (now-ws >= 60) { ws=now; used=0; }
      let os = Number(s.order_window_start || now), orders = Number(s.orders_used || 0);
      if (now-os >= 10) { os=now; orders=0; }
      const ww = used+w > SAFE_WEIGHT ? Math.max(0,60-(now-ws)) : 0;
      const wo = order && orders+1 > SAFE_ORDERS ? Math.max(0,10-(now-os)) : 0;
      const delay = Math.max(ww,wo);
      if (delay > 0) return delay;
      s.weight_window_start=ws; s.weight_used=used+w; s.order_window_start=os; s.orders_used=orders+(order?1:0); s.last_node_acquire=now; saveState(s); return 0;
    });
    if (!wait) return;
    sleep(Math.max(25, Math.ceil(wait*1000)));
  }
}
function recordRateError(status, body, headers) {
  const now = Date.now()/1000;
  const retry = Number(headers?.get?.('Retry-After') || 0);
  const m = String(body || '').match(/banned\s+until\s+(\d{10,16})/i);
  const parsed = m ? Number(m[1]) / (Number(m[1]) > 1e10 ? 1000 : 1) : 0;
  const until = status === 418 || String(body).includes('-1003') ? (parsed || now + Math.max(retry,60)) : now + Math.max(retry,2);
  withLock(() => { const s=loadState(); s.ban_until=Math.max(Number(s.ban_until||0),until); s.last_rate_error={status,until,ts:now}; saveState(s); });
}

const originalFetch = globalThis.fetch;
globalThis.fetch = async function honeycombGuardedFetch(input, init = {}) {
  const url = typeof input === 'string' ? input : input?.url;
  if (!url) return originalFetch(input, init);
  let u; try { u = new URL(url); } catch { return originalFetch(input, init); }
  if (!HOSTS.has(u.hostname)) return originalFetch(input, init);
  const method = String(init.method || input?.method || 'GET').toUpperCase();
  acquire(weight(url), isOrder(url));
  try {
    const res = await originalFetch(input, init);
    if (res.status === 418 || res.status === 429) {
      let body = ''; try { body = await res.clone().text(); } catch {}
      recordRateError(res.status, body, res.headers);
    }
    return res;
  } catch (e) {
    if (String(e?.message || '').includes('BINANCE_GUARD_BAN')) throw e;
    throw e;
  }
};

export const HONEYCOMB_NODE_GUARD = true;
