#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""
HELIX SOVEREIGN PRO v3.1 — PRODUCTION LIVE ONLY
- Emirler: live.kernel.LiveKernel (HMAC, time-sync, -1022 retry)
- AI: OpenRouter ücretsiz modeller — 2 finansal + 2 üretken ajan
- Panel: Flask web (log / PnL / pozisyon / ajan oyları)
- Mod: CANLI. Paper/mock/simülasyon yok.
"""
from __future__ import annotations

import json
import os

# α-SELF-EVOLVE: Her karar sonrası öğrenme kaydı (Türkçe log)
def log_and_learn(symbol, side, score, conf, result, reason=""):
    import sqlite3, time, json
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{ts}] {symbol} {side} skor={score:.1f} conf={conf} → {result} | {reason}"
    print(f"[ÖĞRENME] {msg}")
    try:
        conn = sqlite3.connect("brain.db")
        conn.execute("""CREATE TABLE IF NOT EXISTS evolve_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, side TEXT, score REAL, conf REAL,
            result TEXT, reason TEXT
        )""")
        conn.execute("INSERT INTO evolve_log (ts,symbol,side,score,conf,result,reason) VALUES (?,?,?,?,?,?,?)",
                     (ts, symbol, side, score, conf, result, reason))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ÖĞRENME-HATA] {e}")

import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request

# ── path: live kernel ─────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from live.kernel import LiveKernel, ema, rsi, atr  # noqa: E402

# ── env ───────────────────────────────────────────────────────────────────────
def _load_env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().split("#")[0].strip()
    for k, v in os.environ.items():
        env.setdefault(k, v)
    return env


ENV = _load_env()

API_KEY = (ENV.get("BINANCE_API_KEY") or "").strip()
API_SEC = (
    ENV.get("BINANCE_SECRET_KEY")
    or ENV.get("BINANCE_SECRET")
    or ENV.get("BINANCE_API_SECRET")
    or ""
).strip()
OPENROUTER_KEY = (ENV.get("OPENROUTER_API_KEY") or ENV.get("OPENROUTER_KEY") or "").strip()

PORT = int(ENV.get("SOVEREIGN_PORT") or ENV.get("LIVE_PORT") or "34299")
SYMBOLS = [
    s.strip().upper()
    for s in (ENV.get("LIVE_SYMBOLS") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT").split(",")
    if s.strip()
]
MAX_POS = int(ENV.get("MAX_POSITIONS") or "3")
RISK_PCT = float(ENV.get("LIVE_RISK") or ENV.get("RISK_PCT") or "0.10")
LEV_MIN = int(float(ENV.get("LEV_MIN") or "10"))
LEV_MAX = int(float(ENV.get("MAX_LEVERAGE") or "25"))
TP_PCT = float(ENV.get("TP_PCT") or "1.8")
SL_PCT = float(ENV.get("SL_PCT") or "0.9")
MAX_NOTIONAL = float(ENV.get("MAX_POSITION_SIZE_USDT") or "200")
SCAN_SEC = int(ENV.get("SCAN_INTERVAL_SEC") or "45")
MIN_SCORE = float(ENV.get("MIN_SCORE") or "55")
AI_MIN_CONF = int(ENV.get("AI_CONFIDENCE_THRESHOLD") or "60")
FEE_RATE = float(ENV.get("FEE_RATE") or "0.0004")

# OpenRouter — ücretsiz / deneme odaklı modeller (güncel nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free tier)
# 2 finansal + 2 üretken
AGENTS = [
    {
        "id": "fin_alpha",
        "role": "financial",
        "model": ENV.get("OR_MODEL_FIN1") or "meta-llama/nvidia/nemotron-3.5-lightning:nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free",
        "task": "momentum_risk",
    },
    {
        "id": "fin_beta",
        "role": "financial",
        "model": ENV.get("OR_MODEL_FIN2") or "google/nvidia/nemotron-3.5-lightning:nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free",
        "task": "mean_reversion_structure",
    },
    {
        "id": "gen_coord",
        "role": "generative",
        "model": ENV.get("OR_MODEL_GEN1") or "mistralai/nvidia/nemotron-3.5-lightning:nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free",
        "task": "coordination_narrative",
    },
    {
        "id": "gen_risk",
        "role": "generative",
        "model": ENV.get("OR_MODEL_GEN2") or "huggingfaceh4/nvidia/nemotron-3.5-lightning:nvidia/nemotron-3.5-lightning:inclusionai/ling-3.0-flash-fin:minimax/minimax-m3:meta-llama/llama-3.3-70b-instruct:qwen/qwen3-coder:free",
        "task": "risk_story_and_veto",
    },
]

if not API_KEY or not API_SEC:
    print("=" * 60)
    print("SOVEREIGN PRO v3.1 BASLATILAMADI")
    print("Neden: BINANCE_API_KEY / BINANCE_SECRET_KEY eksik")
    print("Cozum: .env dosyani kontrol et (LIVE mainnet keys)")
    print("=" * 60)
    sys.exit(1)

# ── state ─────────────────────────────────────────────────────────────────────
lock = threading.RLock()
logs: Deque[str] = deque(maxlen=400)
journal: Deque[Dict[str, Any]] = deque(maxlen=100)
agent_votes: Deque[Dict[str, Any]] = deque(maxlen=80)
positions: Dict[str, Dict[str, Any]] = {}
engine_running = False
last_scan: Dict[str, Any] = {}
stats = {
    "opens": 0,
    "closes": 0,
    "wins": 0,
    "losses": 0,
    "gross_pnl": 0.0,
    "total_fees": 0.0,
    "net_pnl": 0.0,
}


def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S") + " [SOVEREIGN-V3] " + str(msg)
    with lock:
        logs.appendleft(line)
    print(line, flush=True)


kernel = LiveKernel(
    venue="usdt",
    api_key=API_KEY,
    api_secret=API_SEC,
    env=ENV,
    log_fn=lambda m: log("[K] " + str(m)),
)


# ── OpenRouter parliament ─────────────────────────────────────────────────────
def openrouter_chat(model: str, prompt: str, timeout: int = 25) -> Optional[str]:
    if not OPENROUTER_KEY:
        return None
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 180,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + OPENROUTER_KEY,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Erdemhasates35/honeycomb-execution-core",
            "X-Title": "HelixSovereignPro",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        log("OpenRouter %s hata: %s" % (model.split("/")[-1], e))
        return None


def parse_agent_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    s, e = text.find("{"), text.rfind("}") + 1
    if s < 0 or e <= s:
        return {}
    try:
        return json.loads(text[s:e])
    except Exception:
        return {}


def parliament_vote(symbol: str, tech: Dict[str, Any]) -> Tuple[Optional[str], float, List[Dict]]:
    """4 ajan oylaması. Dönüş: side, conf, votes."""
    summary = (
        "symbol=%s price=%.6f rsi=%.1f ema_trend=%s atr_pct=%.4f score=%.1f"
        % (
            symbol,
            tech.get("price", 0),
            tech.get("rsi", 50),
            tech.get("trend", "?"),
            tech.get("atr_pct", 0),
            tech.get("score", 0),
        )
    )
    votes: List[Dict[str, Any]] = []
    if not OPENROUTER_KEY:
        # OpenRouter yoksa teknik skor tek başına
        side = tech.get("side")
        conf = float(tech.get("score") or 0)
        return side, conf, votes

    for ag in AGENTS:
        if ag["role"] == "financial":
            prompt = (
                "You are a crypto futures trading analyst. Data: %s. "
                "Reply ONLY JSON: {\"side\":\"LONG\"|\"SHORT\"|\"FLAT\",\"confidence\":0-100,\"reason\":\"brief\"}"
                % summary
            )
        else:
            prompt = (
                "You coordinate aggressive profit logic and risk narrative. Data: %s. "
                "Reply ONLY JSON: {\"side\":\"LONG\"|\"SHORT\"|\"FLAT\",\"confidence\":0-100,\"reason\":\"brief\",\"veto\":true|false}"
                % summary
            )
        raw = openrouter_chat(ag["model"], prompt)
        parsed = parse_agent_json(raw or "")
        side = str(parsed.get("side", "FLAT")).upper()
        if side not in ("LONG", "SHORT", "FLAT"):
            side = "FLAT"
        conf = float(parsed.get("confidence") or 0)
        veto = bool(parsed.get("veto", False))
        v = {
            "id": ag["id"],
            "role": ag["role"],
            "model": ag["model"],
            "side": side,
            "confidence": conf,
            "veto": veto,
            "reason": str(parsed.get("reason", ""))[:120],
            "ts": int(time.time()),
            "symbol": symbol,
        }
        votes.append(v)
        with lock:
            agent_votes.appendleft(v)
        log(
            "AGENT %s [%s] %s conf=%.0f veto=%s | %s"
            % (ag["id"], ag["role"], side, conf, veto, v["reason"][:60])
        )

    if any(v.get("veto") for v in votes if v["role"] == "generative"):
        log("PARLIAMENT VETO — giriş yok %s" % symbol)
        return None, 0.0, votes

    long_w = sum(v["confidence"] for v in votes if v["side"] == "LONG")
    short_w = sum(v["confidence"] for v in votes if v["side"] == "SHORT")
    total = long_w + short_w
    if total < 1:
        return tech.get("side"), float(tech.get("score") or 0), votes
    if long_w >= short_w and long_w / total * 100 >= AI_MIN_CONF:
        return "LONG", long_w / total * 100, votes
    if short_w > long_w and short_w / total * 100 >= AI_MIN_CONF:
        return "SHORT", short_w / total * 100, votes
    return None, max(long_w, short_w) / total * 100, votes


# ── teknik skor ───────────────────────────────────────────────────────────────
def tech_score(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        closes, vols = kernel.klines(symbol, "5m", 80)
        if len(closes) < 40:
            return None
        e9 = ema(closes, 9)
        e21 = ema(closes, 21)
        r = rsi(closes, 14) or 50.0
        a = atr(closes, 14) or 0.0
        price = closes[-1]
        atr_pct = (a / price * 100) if price else 0
        mom = (closes[-1] - closes[-12]) / closes[-12] * 100 if closes[-12] else 0
        score = 50.0
        trend = "FLAT"
        if e9 and e21:
            if e9 > e21:
                score += 12
                trend = "UP"
            else:
                score -= 12
                trend = "DOWN"
        if 40 <= r <= 60:
            score += 6
        elif r > 72:
            score -= 10
        elif r < 28:
            score += 10
        if mom > 0.4:
            score += 8
        elif mom < -0.4:
            score -= 8
        if atr_pct < 0.05:
            score *= 0.7
        side = None
        if score >= MIN_SCORE and trend == "UP":
            side = "LONG"
        elif score <= (100 - MIN_SCORE) and trend == "DOWN":
            side = "SHORT"
        elif score >= MIN_SCORE + 8:
            side = "LONG"
        elif score <= 100 - (MIN_SCORE + 8):
            side = "SHORT"
        return {
            "symbol": symbol,
            "price": price,
            "rsi": r,
            "trend": trend,
            "atr_pct": atr_pct,
            "mom": mom,
            "score": score,
            "side": side,
        }
    except Exception as e:
        log("tech %s: %s" % (symbol, e))
        return None


def dynamic_lev(score: float) -> int:
    # agresif ama tavanlı
    t = min(1.0, max(0.0, (score - 50) / 40))
    return int(LEV_MIN + t * (LEV_MAX - LEV_MIN))


# ── execution ─────────────────────────────────────────────────────────────────
def try_open(symbol: str, side: str, score: float, conf: float) -> None:
    with lock:
        if len(positions) >= MAX_POS:
            log("MAX POS %d — skip %s" % (MAX_POS, symbol))
            return
        if symbol in positions:
            return
    lev = dynamic_lev(score)
    try:
        bal = kernel.balance_usdt()
        log(
            "ENTER TRY | %s %s score=%.1f conf=%.0f lev=%dx bal=%.4f risk=%.0f%%"
            % (side, symbol, score, conf, lev, bal, RISK_PCT * 100)
        )
        if bal <= 0:
            log_and_learn(symbol, side, score, conf, "FAIL", "exception")
            print("[GİRİŞ BAŞARISIZ]")
            log_and_learn(symbol, side, score, conf, "FAIL", "exception")
            print("[GİRİŞ BAŞARISIZ]")
            print("[GİRİŞ BAŞARISIZ]")  # ENTER FAIL %s: futures wallet bakiye 0 — USDT futures'a aktar" % symbol)
            print(f"[HATA DETAY] {type(e).__name__}: {e}")
            log_and_learn(symbol, side, score, conf, "FAIL", str(e)[:200], engine="helix")
            return
        res = kernel.open_market(
            symbol,
            side,
            RISK_PCT,
            lev,
            TP_PCT,
            SL_PCT,
            max_notional=MAX_NOTIONAL,
        )
        entry = float(res["entry"])
        qty = float(res["qty"])
        notional = entry * qty
        open_fee = float(res.get("commission") or notional * FEE_RATE)
        with lock:
            positions[symbol] = {
                "symbol": symbol,
                "side": side,
                "entry": entry,
                "qty": qty,
                "tp": res["tp"],
                "sl": res["sl"],
                "lev": lev,
                "oid": res.get("oid"),
                "open_fee": open_fee,
                "notional": notional,
                "score": score,
                "conf": conf,
                "ts": time.time(),
                "pos_side": res.get("pos_side"),
            }
            stats["opens"] += 1
            stats["total_fees"] += open_fee
        log(
            "ENTER OK | %s %s entry=%.6f qty=%s notional=%.4f open_fee=%.6f oid=%s slip=%.1fbps"
            % (
                side,
                symbol,
                entry,
                qty,
                notional,
                open_fee,
                res.get("oid"),
                res.get("slip_bps", 0),
            )
        )
    except Exception as e:
            log_and_learn(symbol, side, score, conf, "FAIL", "exception")
            print("[GİRİŞ BAŞARISIZ]")
            log_and_learn(symbol, side, score, conf, "FAIL", "exception")
            print("[GİRİŞ BAŞARISIZ]")
            print("[GİRİŞ BAŞARISIZ]")  # ENTER FAIL %s: %s" % (symbol, e))
            print(f"[HATA DETAY] {type(e).__name__}: {e}")
            log_and_learn(symbol, side, score, conf, "FAIL", str(e)[:200], engine="helix")


def manage_positions() -> None:
    with lock:
        items = list(positions.items())
    for symbol, pos in items:
        try:
            mark = kernel.mark(symbol)
            if mark <= 0:
                continue
            side = pos["side"]
            entry = pos["entry"]
            qty = pos["qty"]
            if side == "LONG":
                u_pnl = (mark - entry) * qty
                hit_tp = mark >= pos["tp"]
                hit_sl = mark <= pos["sl"]
            else:
                u_pnl = (entry - mark) * qty
                hit_tp = mark <= pos["tp"]
                hit_sl = mark >= pos["sl"]
            log(
                "HOLD %s %s mark=%.6f uPnL=%.6f tp=%.6f sl=%.6f"
                % (side, symbol, mark, u_pnl, pos["tp"], pos["sl"])
            )
            # exchange-side protect var; ekstra local close sadece gerekirse
            if hit_tp or hit_sl:
                reason = "TP" if hit_tp else "SL"
                fill = kernel.close_market(symbol, side, qty, pos.get("pos_side"))
                exit_px = float(fill.get("avg") or mark)
                close_fee = float(fill.get("commission") or exit_px * qty * FEE_RATE)
                if side == "LONG":
                    raw = (exit_px - entry) * qty
                else:
                    raw = (entry - exit_px) * qty
                net = raw - close_fee
                with lock:
                    stats["closes"] += 1
                    stats["gross_pnl"] += raw
                    stats["total_fees"] += close_fee
                    stats["net_pnl"] += net
                    if net > 0:
                        stats["wins"] += 1
                    else:
                        stats["losses"] += 1
                    journal.appendleft(
                        {
                            "symbol": symbol,
                            "side": side,
                            "entry": entry,
                            "exit": exit_px,
                            "qty": qty,
                            "raw": round(raw, 6),
                            "open_fee": round(pos["open_fee"], 6),
                            "close_fee": round(close_fee, 6),
                            "fees": round(pos["open_fee"] + close_fee, 6),
                            "net": round(net, 6),
                            "reason": reason,
                            "ts": int(time.time()),
                        }
                    )
                    positions.pop(symbol, None)
                log(
                    "CLOSE %s %s %s exit=%.6f raw=%.6f fees=%.6f NET=%.6f"
                    % (side, symbol, reason, exit_px, raw, pos["open_fee"] + close_fee, net)
                )
        except Exception as e:
            log("manage %s: %s" % (symbol, e))


def scan_cycle() -> None:
    ranked: List[Dict[str, Any]] = []
    log("Scanning %d symbols (LIVE)..." % len(SYMBOLS))
    for sym in SYMBOLS:
        t = tech_score(sym)
        if not t:
            continue
        log("SCORED %s: side=%s score=%.1f trend=%s rsi=%.1f" % (sym, t.get("side"), t["score"], t["trend"], t["rsi"]))
        ranked.append(t)
    ranked.sort(key=lambda x: abs(x["score"] - 50), reverse=True)
    top = ranked[:5]
    with lock:
        last_scan["top"] = top
        last_scan["ts"] = time.time()
    if top:
        log(
            "TOP: "
            + " | ".join(
                "%s(%.0f/%s)" % (x["symbol"], x["score"], x.get("side") or "-") for x in top
            )
        )
    for t in top:
        if not t.get("side"):
            continue
        with lock:
            if t["symbol"] in positions or len(positions) >= MAX_POS:
                continue
        side, conf, votes = parliament_vote(t["symbol"], t)
        if not side:
            log("NO CONSENSUS %s conf=%.0f" % (t["symbol"], conf))
            continue
        # teknik ile parlemento aynı yönde olsun
        if t.get("side") and t["side"] != side and conf < 75:
            log("CONFLICT tech=%s ai=%s — skip %s" % (t["side"], side, t["symbol"]))
            continue
        try_open(t["symbol"], side, t["score"], conf)


def engine_loop() -> None:
    global engine_running
    log("=== SOVEREIGN PRO v3.1 LIVE STARTED ===")
    log(
        "Market: USDT_M | Capital risk=%.0f%% | MaxPos=%d | Lev=%d-%d | TP=%.2f%% SL=%.2f%%"
        % (RISK_PCT * 100, MAX_POS, LEV_MIN, LEV_MAX, TP_PCT, SL_PCT)
    )
    try:
        bal = kernel.balance_usdt()
        log("API OK. Balance: %s" % bal)
        if bal <= 0:
            log("WARNING: Futures wallet 0 — emir açılamaz ta ki bakiye yüklensin")
        kernel.load_exchange_info(SYMBOLS)
    except Exception as e:
        log("BOOT WARN: %s" % e)
    while engine_running:
        try:
            manage_positions()
            with lock:
                nopen = len(positions)
            if nopen < MAX_POS:
                scan_cycle()
            time.sleep(SCAN_SEC)
        except Exception as e:
            log("LOOP ERR: %s" % e)
            time.sleep(10)
    log("ENGINE STOPPED")


# ── Flask panel ───────────────────────────────────────────────────────────────
app = Flask(__name__)

DASH = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Helix Sovereign Pro LIVE</title>
<style>
:root{--bg:#0b0f14;--p:#121821;--g:#b8ff3c;--r:#ff5c5c;--t:#e8eef5;--d:#8b98a8}
body{margin:0;background:var(--bg);color:var(--t);font-family:ui-monospace,Menlo,monospace;padding:14px}
h1{color:var(--g);font-size:18px;margin:0 0 6px}.sub{color:var(--d);font-size:12px;margin-bottom:12px}
.panel{background:var(--p);border:1px solid #243040;border-radius:10px;padding:12px;margin-bottom:12px}
.stat{display:inline-block;margin:6px 14px 6px 0}.stat .l{font-size:10px;color:var(--d)}.stat .v{font-size:18px;color:var(--g);font-weight:700}
button{background:var(--g);color:#0b0f14;border:0;padding:8px 12px;border-radius:6px;font-weight:700;cursor:pointer;margin:3px;font-size:12px}
button.stop{background:var(--r);color:#fff}.log{background:#000;height:280px;overflow:auto;font-size:11px;padding:8px;border-radius:8px;line-height:1.45}
.pos{border-left:3px solid var(--g);padding:6px;margin:4px 0;background:#0d1218;font-size:12px}
.pos.s{border-left-color:var(--r)}.agent{font-size:11px;padding:4px 0;border-bottom:1px solid #1c2733}
</style></head><body>
<h1>HELIX SOVEREIGN PRO v3.1 — LIVE</h1>
<div class="sub">LiveKernel emir · OpenRouter parlemento · detaylı PnL — simülasyon yok</div>
<div class="panel">
<div class="stat"><div class="l">BAKIYE</div><div class="v" id="bal">--</div></div>
<div class="stat"><div class="l">AÇIK</div><div class="v" id="open">--</div></div>
<div class="stat"><div class="l">NET PnL</div><div class="v" id="net">--</div></div>
<div class="stat"><div class="l">FEES</div><div class="v" id="fees">--</div></div>
<div class="stat"><div class="l">W/L</div><div class="v" id="wl">--</div></div>
<div class="stat"><div class="l">MOTOR</div><div class="v" id="run">--</div></div>
</div>
<div class="panel">
<button onclick="api('/api/resume')">▶ RESUME</button>
<button class="stop" onclick="api('/api/pause')">■ PAUSE</button>
<button onclick="api('/api/scan')">↻ SCAN</button>
<button onclick="load()">YENİLE</button>
</div>
<div class="panel"><b>Pozisyonlar</b><div id="pos"></div></div>
<div class="panel"><b>Parlamento / Ajanlar</b><div id="agents"></div></div>
<div class="panel"><b>Journal</b><div id="jn"></div></div>
<div class="panel"><b>Log</b><div class="log" id="log"></div></div>
<script>
async function api(p){const r=await fetch(p,{method:'POST'});const d=await r.json();alert(d.msg||JSON.stringify(d));load()}
async function load(){
 const r=await fetch('/api/status');const d=await r.json();
 document.getElementById('bal').innerText=(d.balance||0).toFixed(4)+' $';
 document.getElementById('open').innerText=d.open;
 document.getElementById('net').innerText=(d.net_pnl>=0?'+':'')+d.net_pnl.toFixed(4);
 document.getElementById('fees').innerText=d.total_fees.toFixed(4);
 document.getElementById('wl').innerText=d.wins+'/'+d.losses;
 document.getElementById('run').innerText=d.running?'LIVE':'PAUSE';
 document.getElementById('pos').innerHTML=(d.positions||[]).map(p=>`<div class="pos ${p.side==='SHORT'?'s':''}"><b>${p.side}</b> ${p.symbol} entry=${p.entry} qty=${p.qty} lev=${p.lev}x fee=${p.open_fee}</div>`).join('')||'<i>yok</i>';
 document.getElementById('agents').innerHTML=(d.agents||[]).slice(0,12).map(a=>`<div class="agent">${a.id} [${a.role}] ${a.side} conf=${a.confidence} ${a.reason||''}</div>`).join('')||'<i>oy yok</i>';
 document.getElementById('jn').innerHTML=(d.journal||[]).slice(0,10).map(j=>`<div class="agent">${j.side} ${j.symbol} ${j.reason} net=${j.net} fees=${j.fees}</div>`).join('')||'<i>—</i>';
 document.getElementById('log').innerHTML=(d.logs||[]).map(l=>`<div>${l}</div>`).join('');
}
load();setInterval(load,3000);
</script></body></html>"""


@app.route("/")
def index():
    return DASH


@app.route("/api/status")
def api_status():
    try:
        bal = kernel.balance_usdt()
    except Exception:
        bal = 0.0
    with lock:
        return jsonify(
            {
                "balance": bal,
                "open": len(positions),
                "positions": list(positions.values()),
                "journal": list(journal)[:20],
                "logs": list(logs)[:80],
                "agents": list(agent_votes)[:20],
                "running": engine_running,
                "net_pnl": round(stats["net_pnl"], 6),
                "total_fees": round(stats["total_fees"], 6),
                "wins": stats["wins"],
                "losses": stats["losses"],
                "opens": stats["opens"],
                "mode": "LIVE",
                "or_key": bool(OPENROUTER_KEY),
            }
        )


@app.route("/api/logs")
def api_logs():
    with lock:
        return jsonify(list(logs)[:100])


@app.route("/api/resume", methods=["POST", "GET"])
def api_resume():
    global engine_running
    if not engine_running:
        engine_running = True
        threading.Thread(target=engine_loop, daemon=True).start()
        log("ENGINE RESUMED via API")
        return jsonify({"ok": 1, "msg": "LIVE motor başlatıldı"})
    return jsonify({"ok": 1, "msg": "zaten çalışıyor"})


@app.route("/api/pause", methods=["POST", "GET"])
def api_pause():
    global engine_running
    engine_running = False
    log("ENGINE PAUSED via API")
    return jsonify({"ok": 1, "msg": "motor durdu (pozisyonlar borsada kalır)"})


@app.route("/api/scan", methods=["POST", "GET"])
def api_scan():
    threading.Thread(target=scan_cycle, daemon=True).start()
    return jsonify({"ok": 1, "msg": "scan tetiklendi"})


def main() -> None:
    global engine_running
    log("Validating API connection...")
    try:
        bal = kernel.balance_usdt()
        log("API OK. Balance: %s" % bal)
        if bal <= 0:
            log("WARNING: Balance is 0. Futures wallet may be empty.")
    except Exception as e:
        log("API VALIDATE FAIL: %s" % e)
        print("SOVEREIGN PRO v3.1 BASLATILAMADI — API/imza hatası: %s" % e)
        sys.exit(1)

    engine_running = True
    threading.Thread(target=engine_loop, daemon=True).start()

    url = "http://127.0.0.1:%d/" % PORT
    log("=== SOVEREIGN PRO v3.1 STARTED ===")
    log("Market: USDT_M | Base: https://fapi.binance.com | LIVE")
    log("WEB PANEL: %s" % url)
    log("OpenRouter agents: %s" % ("ON" if OPENROUTER_KEY else "OFF (tech only)"))
    print("\n>>> Tarayicide ac: %s\n" % url, flush=True)

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
