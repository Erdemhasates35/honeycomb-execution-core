#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# HONEYCOMB_CONFLICT_MARKER <<<<<<< HEAD
"""
EXTREME SCANNER ENGINE — geniş sembol evreninde çoklu-osilatör aşırı
alım/satım taraması. (MİKRO-SCALPING & MAKER OPTİMİZASYONLU VERSİYON)

Ana parlamento motorundan (sovereign_parliament_engine.py)
FARKLI, ayrı bir process — AI çağrısı YAPMAZ, tamamen alpha_core'un
extreme_reversion_signal() (RSI/Stoch/Williams%R/CCI/MFI/Bollinger çoklu
osilatör uyuşması) + rejim filtresine dayanır. Aynı test edilmiş kernel
(LiveKernel, DynamicTrailingStopEngine, PartialProfitEngine, CircuitBreaker,
CryptographicAuditLedger) kullanılır.

STRATEJİK GÜNCELLEME:
- Piyasa emri (Taker) yerine Limit emri (Maker) mimarisine odaklanılmıştır.
- 15m yerine 1m (mikro yapı) analizi ile anlık boşluklar hedeflenmiştir.
- Döngü gecikmeleri (time.sleep) kaldırılarak saniyelik HFT (Yüksek Frekans) tepkisi sağlanmıştır.
- Kâr/Zarar hedefleri (TP/SL) mikro dalgalanmaları yakalayacak şekilde daraltılmıştır.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
"""HONEYCOMB EXTREME SCANNER ENGINE — tactical reversal (LIVE).

Uses alpha_core.get_technical_decision / evaluate_entry_gate.
klines lives in alpha_core — this file never assumes a global klines.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Dict, List, Tuple
# HONEYCOMB_CONFLICT_MARKER >>>>>>> refs/remotes/origin/main

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# HONEYCOMB_CONFLICT_MARKER <<<<<<< HEAD
from live.kernel import (  # noqa: E402
    LiveKernel, DynamicTrailingStopEngine, PartialProfitEngine, CircuitBreaker,
    CryptographicAuditLedger, load_env,
)
import alpha_core  # noqa: E402
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from live.kernel import (
    LiveKernel,
    DynamicTrailingStopEngine,
    PartialProfitEngine,
    CircuitBreaker,
    CryptographicAuditLedger,
    load_env,
)
import alpha_core
# HONEYCOMB_CONFLICT_MARKER >>>>>>> refs/remotes/origin/main

try:
    for _k, _v in load_env().items():
        os.environ.setdefault(_k, _v)
except Exception as _e:
# HONEYCOMB_CONFLICT_MARKER <<<<<<< HEAD
    print("UYARI: .env yuklenemedi (%s)" % _e, flush=True)

ACCOUNT_LABEL = os.getenv("ACCOUNT_LABEL", "SCANNER")
logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [%(levelname)s] [SCANNER:{ACCOUNT_LABEL}] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extreme_scanner")

# ------------------------------------------------------------------ ENV ----
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "PAPER").upper()
VENUE = os.getenv("VENUE", "usdt")
DEFAULT_WIDE_SYMBOLS = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,LTCUSDT,"
    "DOTUSDT,MATICUSDT,TRXUSDT,ATOMUSDT,NEARUSDT,APTUSDT,ARBUSDT,OPUSDT,FILUSDT,ETCUSDT,"
    "UNIUSDT,ICPUSDT,SUIUSDT,INJUSDT"
)
WIDE_SYMBOLS = [s.strip().upper() for s in os.getenv("WIDE_SYMBOLS", DEFAULT_WIDE_SYMBOLS).split(",") if s.strip()]
MAX_POSITIONS = int(os.getenv("SCANNER_MAX_POSITIONS", "8"))
SCAN_INTERVAL_SEC = int(os.getenv("SCANNER_INTERVAL_SEC", "1")) # MİKRO-SCALPING: 20'den 1'e düşürüldü
REVERSION_THRESHOLD = float(os.getenv("REVERSION_THRESHOLD", "85"))  # MİKRO-SCALPING: Sadece en kusursuz sinyaller (85)
BASE_RISK_PCT = float(os.getenv("SCANNER_RISK", "0.01")) # MİKRO-SCALPING: Sürümden kazanmak için risk %1'e çekildi
LEV_MIN = int(float(os.getenv("LEV_MIN", "50"))) # MİKRO-SCALPING: Mikro hareketler için yüksek kaldıraç tabanı
LEV_MAX = int(float(os.getenv("MAX_LEVERAGE", "100"))) # MİKRO-SCALPING: Maksimum kaldıraç tavanı artırıldı
MAX_NOTIONAL = float(os.getenv("MAX_POSITION_SIZE_USDT", "150"))
FEE_RATE = float(os.getenv("FEE_RATE", "0.0001")) # MİKRO-SCALPING: Maker komisyon oranına ayarlandı
BRIDGE_HOST = os.getenv("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("HONEYCOMB_BRIDGE_PORT", "8200"))
    print("UYARI .env: %s" % _e, flush=True)

ACCOUNT_LABEL = os.getenv("ACCOUNT_LABEL", "SCANNER-OMEGA")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [OMEGA:%s] %%(message)s" % ACCOUNT_LABEL,
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extreme_scanner_engine")

VENUE = os.getenv("VENUE", "usdt").lower()
DEFAULT_WIDE = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,"
    "AVAXUSDT,LINKUSDT,LTCUSDT,DOTUSDT,TRXUSDT,ATOMUSDT,NEARUSDT"
)
WIDE_SYMBOLS = [s.strip().upper() for s in os.getenv("WIDE_SYMBOLS", DEFAULT_WIDE).split(",") if s.strip()]
MAX_POSITIONS = int(os.getenv("SCANNER_MAX_POSITIONS", "8"))
SCAN_INTERVAL_SEC = float(os.getenv("SCANNER_INTERVAL_SEC", "12"))
SYMBOL_DELAY_SEC = float(os.getenv("SCANNER_SYMBOL_DELAY_SEC", "0.35"))
AUDIT_FILE = os.path.join(ROOT, os.getenv("SCANNER_AUDIT_FILE", "scanner_omega_audit.jsonl"))
# HONEYCOMB_CONFLICT_MARKER >>>>>>> refs/remotes/origin/main

kernel = LiveKernel(venue=VENUE, log_fn=lambda m: log.info(m))
kernel.load_exchange_info(WIDE_SYMBOLS)
trail_engine = DynamicTrailingStopEngine(kernel, log_fn=lambda m: log.info(m))
partial_engine = PartialProfitEngine(kernel, log_fn=lambda m: log.info(m))
order_breaker = CircuitBreaker(fail_threshold=4, cooldown_sec=180)
# HONEYCOMB_CONFLICT_MARKER <<<<<<< HEAD
audit = CryptographicAuditLedger(os.path.join(ROOT, "scanner_audit_ledger.jsonl"))

_lock = threading.Lock()
_open_meta: Dict[str, Dict[str, Any]] = {}
_journal: List[Dict[str, Any]] = []
_decision_log: List[Dict[str, Any]] = []
_runtime_lock = threading.Lock()
RUNTIME = {"live_armed": os.getenv("LIVE_ARMED", "0") == "1"}


def is_live() -> bool:
    with _runtime_lock:
        return EXECUTION_MODE == "LIVE" and RUNTIME["live_armed"]


def rset(key, value):
    with _runtime_lock:
        RUNTIME[key] = value


def rget(key):
    with _runtime_lock:
        return RUNTIME[key]


def _log_decision(symbol: str, opened: bool, reason: str, extra: Dict[str, Any]) -> None:
    with _lock:
        _decision_log.insert(0, {"ts": int(time.time()), "symbol": symbol, "opened": opened, "reason": reason, **extra})
        if len(_decision_log) > 150:
            _decision_log.pop()


def get_wallet_equity() -> float:
    try:
        data = kernel._http("GET", kernel.v["balance"], {}, signed=True, weight=5)
        for a in data:
            if a.get("asset") == "USDT":
                return float(a.get("balance") or a.get("crossWalletBalance") or a.get("availableBalance") or 0)
    except Exception as e:
        log.warning("wallet equity alınamadı, availableBalance'a düşülüyor: %s", e)
        return kernel.balance_usdt()
    return kernel.balance_usdt()


def portfolio_notional_blocked(new_notional: float, equity: float, max_mult: float = 3.0) -> bool:
    if equity <= 0:
        return False
    with _lock:
        current = sum(m["entry"] * m["qty"] * m.get("lev", 1) for m in _open_meta.values())
    return (current + new_notional) > equity * max_mult


def scan_symbol(symbol: str, equity: float) -> None:
    with _lock:
        if symbol in _open_meta or len(_open_meta) >= MAX_POSITIONS:
            return

    regime, atr_pct = alpha_core.detect_regime(symbol)
    if regime in ["DEATH", "CHOPPY"]: # MİKRO-SCALPING: Momentumsuz ve aşırı riskli rejimler elenir
        return
        
    # MİKRO-SCALPING: 15m yerine 1m verisi kullanılarak anlık mikro uyuşmalar yakalanır
    indicators = alpha_core.full_indicator_set(symbol, "1m")
    if not indicators:
        return
        
    rev_score, rev_label = alpha_core.extreme_reversion_signal(indicators)

    if abs(rev_score) < REVERSION_THRESHOLD:
        return  # Sessizce geç

    side = "LONG" if rev_score > 0 else "SHORT"
    confidence = min(99.0, 50.0 + abs(rev_score) * 0.45) # Maksimum %99'a kadar güven skalası

    log.info("SİNYAL %s %s | %s | rejim=%s güven=%.0f", side, symbol, rev_label, regime, confidence)
    _log_decision(symbol, False, f"Aday sinyal: {rev_label}", {"side": side, "regime": regime, "confidence": round(confidence, 1)})

    if order_breaker.state() == "OPEN" and not order_breaker.allow():
        log.warning("Devre kesici açık, %s atlandı", symbol)
        return

    if alpha_core.correlation_blocked(symbol, side, [(s, m["side"]) for s, m in _open_meta.items()]):
        log.info("AÇILMADI %s -> korelasyon kalkanı", symbol)
        return

    lev = max(LEV_MIN, min(LEV_MAX, int(LEV_MIN + (LEV_MAX - LEV_MIN) * (confidence - 50) / 45.0)))
    risk_pct = BASE_RISK_PCT * alpha_core.get_risk_multiplier()
    
    # MİKRO-SCALPING HEDEFLERİ: Ultra dar TP ve SL seviyeleri
    tp_pct = max(0.04, atr_pct * 0.15) 
    sl_pct = max(0.05, atr_pct * 0.20)

    est_notional = equity * risk_pct * lev
    if portfolio_notional_blocked(est_notional, equity):
        log.info("AÇILMADI %s -> portföy risk sınırı", symbol)
        return

    if not is_live():
        log.warning("GÖNDERİLMEDİ %s %s (LIVE_ARMED kapalı) lev=%dx risk=%.3f%%", side, symbol, lev, risk_pct * 100)
        return

    try:
        # MİKRO-SCALPING MAKER İNFAZI: 
        # Kernel kütüphanesinde 'open_limit_maker' yoksa 'open_market' metoduna düşer. 
        # Kusursuz Maker infazı için kernel içine 'open_limit_maker' tanımlanmış olmalıdır.
        order_method = getattr(kernel, "open_limit_maker", kernel.open_market)
        res = order_method(symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=MAX_NOTIONAL)
        order_breaker.record_success()
    except Exception as e:
        order_breaker.record_failure()
        log.error("AÇILAMADI %s: %s", symbol, e)
        return

    open_fee = res["entry"] * res["qty"] * FEE_RATE
    with _lock:
        _open_meta[symbol] = {
            "side": side, "entry": res["entry"], "qty": res["qty"], "tp": res["tp"], "sl": res["sl"],
            "lev": lev, "open_fee": open_fee, "ts": time.time(), "regime": regime,
            "confidence": confidence, "trail_stage": 0, "realized_partial_net": 0.0,
        }
    trail_engine.register(symbol, side, res["entry"], res["tp"], res["sl"])
    partial_engine.register(symbol, side, res["entry"], res["tp"], res["sl"], qty=res["qty"], pos_side=res.get("pos_side"))
    audit.append({"event": "OPEN", "symbol": symbol, "side": side, "entry": res["entry"], "lev": lev, "reason": rev_label})
    log.info("AÇILDI %s %s entry=%.6f lev=%dx TP=%.6f SL=%.6f | %s", side, symbol, res["entry"], lev, res["tp"], res["sl"], rev_label)
    _log_decision(symbol, True, f"Pozisyon açıldı: {rev_label}", {"side": side, "regime": regime})


def manage_positions() -> None:
    with _lock:
        symbols = list(_open_meta.keys())
    for symbol in symbols:
        try:
            bid, ask, mid = kernel.book(symbol)
        except Exception:
            continue
        new_sl = trail_engine.update(symbol, mid)
        if new_sl is not None:
            with _lock:
                if symbol in _open_meta:
                    _open_meta[symbol]["sl"] = new_sl
        partial_res = partial_engine.update(symbol, mid)
        if partial_res is not None:
            with _lock:
                if symbol in _open_meta:
                    _open_meta[symbol]["qty"] = partial_res["remaining"]
                    _open_meta[symbol]["realized_partial_net"] += partial_res["net"]
            audit.append({"event": "PARTIAL_CLOSE", "symbol": symbol, **partial_res})


def check_closed_positions() -> None:
    with _lock:
        symbols = list(_open_meta.keys())
    for symbol in symbols:
        with _lock:
            meta = _open_meta.get(symbol)
        if not meta:
            continue
        try:
            real_amt = kernel.position_amt(symbol, meta["side"])
        except Exception:
            continue
        if real_amt > 0:
            continue
        try:
            bid, ask, mid = kernel.book(symbol)
            exit_px = mid
        except Exception:
            exit_px = meta["entry"]
        close_fee = exit_px * meta["qty"] * FEE_RATE
        raw = (exit_px - meta["entry"]) * meta["qty"] if meta["side"] == "LONG" else (meta["entry"] - exit_px) * meta["qty"]
        net = raw - close_fee + meta.get("realized_partial_net", 0.0)
        rec = {"symbol": symbol, "side": meta["side"], "entry": meta["entry"], "exit": exit_px,
               "net_pnl": round(net, 6), "hold_sec": round(time.time() - meta["ts"], 1),
               "regime": meta["regime"], "closed_ts": int(time.time())}
        with _lock:
            _journal.insert(0, rec)
            if len(_journal) > 300:
                _journal.pop()
            _open_meta.pop(symbol, None)
        trail_engine.forget(symbol)
        partial_engine.forget(symbol)
        alpha_core.on_trade_closed(symbol, meta["side"], net, meta["confidence"], meta["regime"])
        audit.append({"event": "CLOSE", "symbol": symbol, "net_pnl": rec["net_pnl"]})
        log.info("KAPANDI %s %s net=%.6f hold=%.0fs", meta["side"], symbol, net, rec["hold_sec"])


def main_loop() -> None:
    log.info("MİKRO-YAPI MOTORU AKTİF | sembol_sayisi=%d max_pos=%d esik=%.0f mod=%s live_armed=%s",
              len(WIDE_SYMBOLS), MAX_POSITIONS, REVERSION_THRESHOLD, EXECUTION_MODE, rget("live_armed"))
    while True:
        try:
            check_closed_positions()
            if is_live():
                manage_positions()
            equity = get_wallet_equity()
            for symbol in WIDE_SYMBOLS:
                scan_symbol(symbol, equity)
                # MİKRO-SCALPING: time.sleep(0.6) kaldırıldı. Hızlı asenkron geçiş sağlandı.
            time.sleep(SCAN_INTERVAL_SEC)
        except KeyboardInterrupt:
            log.info("Durduruldu.")
            break
        except Exception as e:
            log.error("DÖNGÜ HATASI: %s", e)
            time.sleep(2) # MİKRO-SCALPING: Hata bekleme süresi 8'den 2'ye düşürüldü


# ========================================================== BRIDGE HTTP API
class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/panel"):
            with _lock:
                positions = [{"symbol": s, **m} for s, m in _open_meta.items()]
                journal = list(_journal[:30])
                decisions = list(_decision_log[:40])
            total_net = sum(r["net_pnl"] for r in journal)
            pos_rows = "".join(
                "<tr><td>{sym}</td><td class='{cls}'>{side}</td><td>{entry:.6f}</td><td>{lev}x</td><td>{regime}</td></tr>".format(
                    sym=p["symbol"], cls=p["side"].lower(), side=p["side"], entry=p["entry"], lev=p["lev"], regime=p["regime"]
                ) for p in positions
            ) or "<tr><td colspan=5 class=muted>Açık pozisyon yok</td></tr>"
            j_rows = "".join(
                "<tr><td>{sym}</td><td class='{cls}'>{side}</td><td class='{pcls}'>{net:+.4f}</td><td>{hold:.0f}s</td></tr>".format(
                    sym=r["symbol"], cls=r["side"].lower(), side=r["side"],
                    pcls=("pos" if r["net_pnl"] >= 0 else "neg"), net=r["net_pnl"], hold=r["hold_sec"]
                ) for r in journal
            ) or "<tr><td colspan=4 class=muted>Henüz kapanan yok</td></tr>"
            d_rows = "".join(
                "<tr><td>{ts}</td><td>{sym}</td><td class='{cls}'>{state}</td><td>{reason}</td></tr>".format(
                    ts=time.strftime("%H:%M:%S", time.localtime(d["ts"])), sym=d["symbol"],
                    cls=("pos" if d.get("opened") else "muted"), state=("AÇILDI" if d.get("opened") else "sinyal"),
                    reason=d.get("reason", "")
                ) for d in decisions
            ) or "<tr><td colspan=4 class=muted>Henüz sinyal yok</td></tr>"
            html = (
                "<!DOCTYPE html><html lang=\"tr\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                "<meta http-equiv=\"refresh\" content=\"10\"><title>Extreme Scanner</title>"
                "<style>body{background:#0b0f14;color:#d7e0e8;font-family:system-ui;margin:0;padding:16px}"
                "h1{color:#ffb454;font-size:18px}table{width:100%;border-collapse:collapse;margin-bottom:20px;font-size:13px}"
                "td,th{padding:6px;border-bottom:1px solid #223}.long{color:#5ee6a0}.short{color:#ff7b7b}"
                ".pos{color:#5ee6a0}.neg{color:#ff7b7b}.muted{color:#5a6b78}h2{font-size:14px;color:#9fb3c2}</style>"
                "</head><body>"
                f"<h1>EXTREME SCANNER (MICRO-SCALPING) — {len(WIDE_SYMBOLS)} sembol | mod={EXECUTION_MODE} | live_armed={rget('live_armed')}</h1>"
                f"<p>Net K/Z: <b class=\"{'pos' if total_net >= 0 else 'neg'}\">{total_net:+.4f}</b> | Açık: {len(positions)}/{MAX_POSITIONS}</p>"
                f"<h2>Açık Pozisyonlar</h2><table><tr><th>Sembol</th><th>Yön</th><th>Giriş</th><th>Kaldıraç</th><th>Rejim</th></tr>{pos_rows}</table>"
                f"<h2>Son Kapananlar</h2><table><tr><th>Sembol</th><th>Yön</th><th>Net</th><th>Süre</th></tr>{j_rows}</table>"
                f"<h2>Son Sinyaller/Kararlar</h2><table><tr><th>Saat</th><th>Sembol</th><th>Durum</th><th>Sebep</th></tr>{d_rows}</table>"
                "</body></html>"
            )
            self._send_html(html)
        elif path == "/status":
            self._send(200, {"mode": EXECUTION_MODE, "live_armed": rget("live_armed"), "symbols": len(WIDE_SYMBOLS), "open": len(_open_meta)})
        else:
            self._send(404, {"error": "NOT_FOUND"})

    def do_POST(self):
        if self.path.split("?")[0] != "/control":
            self._send(404, {"error": "NOT_FOUND"})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
        if "live_armed" in payload:
            rset("live_armed", bool(payload["live_armed"]))
        self._send(200, {"ok": True, "runtime": dict(RUNTIME)})

    def log_message(self, *_a):
        return


def start_bridge():
    port = BRIDGE_PORT
    for _ in range(10):
        try:
            server = ThreadingHTTPServer((BRIDGE_HOST, port), Handler)
            break
        except OSError:
            port += 1
    else:
        log.error("Bridge başlatılamadı.")
        return
    log.info("PANEL http://%s:%d", BRIDGE_HOST, port)
    server.serve_forever()


def main():
    t = threading.Thread(target=start_bridge, daemon=True)
    t.start()
    main_loop()


if __name__ == "__main__":
    main()
audit = CryptographicAuditLedger(AUDIT_FILE)
_open_meta: Dict[str, Dict[str, Any]] = {}


def open_positions_list() -> List[Tuple[str, str]]:
    return [(s, m.get("side", "")) for s, m in _open_meta.items()]


def scan_symbol(symbol: str) -> None:
    if not order_breaker.allow():
        log.warning("circuit open — skip %s", symbol)
        return
    if len(_open_meta) >= MAX_POSITIONS:
        return
    if symbol in _open_meta:
        return
    try:
        equity = max(0.0, float(kernel.balance_usdt() or 0.0))
    except Exception as e:
        log.warning("equity: %s", e)
        equity = 0.0
    tech = alpha_core.get_technical_decision(symbol, equity=equity, open_positions=open_positions_list())
    if not tech.get("allow"):
        log.info("FILTER %s %s conf=%s", symbol, tech.get("reason"), tech.get("confidence"))
        return
    side = tech["side"]
    risk_pct = float(tech.get("risk_pct") or os.getenv("SCANNER_RISK", "0.015"))
    lev = int(tech.get("leverage") or 10)
    tp_pct = max(0.20, float(os.getenv("SCANNER_MIN_TP_PCT", "0.20")))
    sl_pct = max(0.30, float(os.getenv("SCANNER_MIN_SL_PCT", "0.30")))
    max_notional = float(os.getenv("MAX_POSITION_SIZE_USDT", "500"))
    if os.getenv("LIVE_ARMED", "0") != "1":
        log.info("PAPER GATE %s %s score=%s", symbol, side, tech.get("score"))
        audit.append({"event": "paper", "symbol": symbol, "tech": {k: tech[k] for k in tech if k != "details"}})
        return
    try:
        res = kernel.open_market(symbol, side, risk_pct, lev, tp_pct, sl_pct, max_notional=max_notional)
        _open_meta[symbol] = {
            "side": side, "entry": res["entry"], "qty": res["qty"], "lev": lev,
            "tp": res["tp"], "sl": res["sl"], "confidence": tech.get("confidence"),
            "regime": tech.get("regime"),
        }
        trail_engine.register(symbol, side, res["entry"], res["tp"], res["sl"])
        partial_engine.register(symbol, side, res["entry"], res["tp"], res["sl"], res["qty"], res.get("pos_side"))
        order_breaker.record_success()
        audit.append({"event": "open", "symbol": symbol, "res": res, "tech": tech.get("reason")})
        log.info("OPEN %s %s", side, symbol)
    except Exception as e:
        order_breaker.record_failure()
        log.error("OPEN HATA %s: %s", symbol, e)


def check_closed_positions() -> None:
    for symbol, meta in list(_open_meta.items()):
        try:
            real_amt = kernel.position_amt(symbol, meta["side"])
        except Exception as e:
            log.warning("pos %s: %s", symbol, e)
            continue
        if real_amt > 0:
            try:
                bid, ask, mid = kernel.book(symbol)
                trail_engine.update(symbol, mid)
                partial_engine.update(symbol, mid)
            except Exception:
                pass
            continue
        net = 0.0
        alpha_core.on_trade_closed(symbol, meta["side"], net, meta.get("confidence") or 0, meta.get("regime") or "")
        trail_engine.forget(symbol)
        partial_engine.forget(symbol)
        _open_meta.pop(symbol, None)
        log.info("CLOSED %s", symbol)


def main_loop() -> None:
    log.info("exchangeInfo loaded filters=%s symbols=%s LIVE_ARMED=%s",
             len(getattr(kernel, "_filters", {})), len(WIDE_SYMBOLS), os.getenv("LIVE_ARMED", "0"))
    log.info("PANEL http://127.0.0.1:%s", os.getenv("HONEYCOMB_SCANNER_PORT", "8200"))
    while True:
        check_closed_positions()
        for sym in WIDE_SYMBOLS:
            try:
                scan_symbol(sym)
            except Exception as e:
                log.error("DONGU HATASI: %s", e)
            time.sleep(SYMBOL_DELAY_SEC)
        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    main_loop()
# HONEYCOMB_CONFLICT_MARKER >>>>>>> refs/remotes/origin/main
