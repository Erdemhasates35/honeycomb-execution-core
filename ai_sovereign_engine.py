#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI SOVEREIGN ENGINE — production HMAC + detaylı kar/zarar/masraf logları
Testnet veya Live (ENV ile). İmza -1022 düzeltildi.
"""
import os
import time
import json
import hmac
import hashlib
import logging
import urllib.parse
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [AI-SOVEREIGN] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AI_Sovereign_Engine")

# --- ENV (çoklu alias) ---
USE_TESTNET = os.getenv("USE_TESTNET", os.getenv("HONEYCOMB_MODE", "TESTNET")).upper() in (
    "TRUE", "1", "TESTNET", "YES"
)
API_KEY = (
    os.getenv("BINANCE_TESTNET_API_KEY" if USE_TESTNET else "BINANCE_API_KEY")
    or os.getenv("BINANCE_API_KEY")
    or ""
).strip()
API_SECRET = (
    os.getenv("BINANCE_TESTNET_SECRET" if USE_TESTNET else "BINANCE_SECRET_KEY")
    or os.getenv("BINANCE_SECRET_KEY")
    or os.getenv("BINANCE_SECRET")
    or os.getenv("BINANCE_API_SECRET")
    or ""
).strip()
BASE_URL = (
    os.getenv("BINANCE_TESTNET_URL", "https://testnet.binancefuture.com")
    if USE_TESTNET
    else os.getenv("BINANCE_BASE_URL", os.getenv("BINANCE_FUTURES_URL", "https://fapi.binance.com"))
).rstrip("/")

FEE_RATE = float(os.getenv("FEE_RATE", "0.0004"))  # taker ~0.04%
MAX_LEVERAGE = int(float(os.getenv("TESTNET_LEVERAGE", os.getenv("MAX_LEVERAGE", "20"))))
RISK_PER_TRADE = float(os.getenv("TESTNET_RISK", os.getenv("LIVE_RISK", "0.05")))
TP_PCT = float(os.getenv("TESTNET_TP_M", "1.2")) / 100.0
SL_PCT = float(os.getenv("TESTNET_SL_P", "0.8")) / 100.0
SYMBOL = os.getenv("SOVEREIGN_SYMBOL", "BTCUSDT")
RECV_WINDOW = int(os.getenv("RECV_WINDOW", os.getenv("BINANCE_RECV_WINDOW_MS", "10000")))
CYCLE_SEC = int(os.getenv("SOVEREIGN_CYCLE_SEC", "30"))

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL_ID", "google/gemini-flash-1.5")
AI_THRESHOLD = int(os.getenv("AI_CONFIDENCE_THRESHOLD", "70"))

_time_offset = 0
_journal: List[Dict[str, Any]] = []
_open_meta: Dict[str, Any] = {}


def sync_time() -> None:
    global _time_offset
    try:
        data = _http("GET", "/fapi/v1/time", {}, signed=False)
        server = int(data["serverTime"])
        _time_offset = server - int(time.time() * 1000)
        logger.info("TIME SYNC offset=%d ms | base=%s", _time_offset, BASE_URL)
    except Exception as e:
        logger.warning("TIME SYNC FAIL: %s", e)
        _time_offset = 0


def _sign(params: Dict[str, Any]) -> str:
    clean = {k: str(v) for k, v in params.items() if v is not None}
    qs = urllib.parse.urlencode(clean, doseq=True)
    sig = hmac.new(API_SECRET.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    return qs + "&signature=" + sig


def _http(
    method: str,
    endpoint: str,
    params: Optional[Dict] = None,
    signed: bool = True,
    retries: int = 3,
) -> Any:
    params = dict(params or {})
    last_err = None
    for attempt in range(retries):
        try:
            if signed:
                if not API_KEY or not API_SECRET:
                    raise RuntimeError("API_KEY / API_SECRET eksik")
                params["timestamp"] = int(time.time() * 1000) + _time_offset
                params["recvWindow"] = RECV_WINDOW
                body = _sign(params)
            else:
                body = urllib.parse.urlencode({k: str(v) for k, v in params.items()}, doseq=True)

            url = BASE_URL + endpoint
            data = None
            headers = {
                "X-MBX-APIKEY": API_KEY,
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "AI-SOVEREIGN/1.1",
            }
            if method.upper() == "GET":
                if body:
                    url = url + "?" + body
            else:
                data = body.encode("utf-8") if body else None

            req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode() if e.fp else str(e)
            try:
                err = json.loads(raw)
            except Exception:
                err = {"code": e.code, "msg": raw}
            code = err.get("code")
            if code in (-1021, -1022):
                logger.warning("SIG/TIME retry %d: %s", attempt + 1, err)
                sync_time()
                last_err = RuntimeError("sig/time: %s" % err)
                time.sleep(0.2 * (attempt + 1))
                continue
            if code == -2015:
                raise RuntimeError("API key invalid / IP restricted (-2015)")
            raise RuntimeError("HTTP %s: %s" % (e.code, err))
        except Exception as e:
            last_err = e
            time.sleep(0.3 * (attempt + 1))
    raise RuntimeError("request failed: %s" % last_err)


def get_ai_signal(symbol: str, price: float, rsi: float, ema_trend: str):
    if not OPENROUTER_KEY or OPENROUTER_KEY.startswith("sk-or-v1-buraya"):
        logger.warning("OpenRouter yok — teknik filtre: %s", ema_trend)
        return ("LONG" if ema_trend == "UP" else "SHORT"), 80
    try:
        from openai import OpenAI

        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
        prompt = (
            f"Sen agresif bir kripto vadeli asistanısın. Sembol:{symbol} Fiyat:{price} "
            f"RSI:{rsi} EMA:{ema_trend}. Sadece JSON: "
            '{"direction":"LONG|SHORT","confidence":0-100}'
        )
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=50,
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("direction", "LONG"), int(data.get("confidence", 50))
    except Exception as e:
        logger.error("AI Çağrı Hatası: %s", e)
        return ("LONG" if ema_trend == "UP" else "SHORT"), 50


def calculate_position_size(balance: float, price: float, leverage: int):
    risk_usdt = balance * RISK_PER_TRADE
    notional = risk_usdt * leverage
    total_fee_pct = FEE_RATE * 2
    effective = notional * (1 - total_fee_pct)
    qty = effective / price if price > 0 else 0
    if "BTC" in SYMBOL:
        qty = round(qty, 3)
    elif "ETH" in SYMBOL:
        qty = round(qty, 2)
    else:
        qty = round(qty, 1)
    est_open_fee = notional * FEE_RATE
    est_close_fee = notional * FEE_RATE
    logger.info(
        "SIZING | bal=%.4f risk=%.2f%% lev=%dx | notional=%.4f qty=%s | "
        "est_open_fee=%.6f est_close_fee=%.6f est_total_fee=%.6f",
        balance,
        RISK_PER_TRADE * 100,
        leverage,
        notional,
        qty,
        est_open_fee,
        est_close_fee,
        est_open_fee + est_close_fee,
    )
    return qty, notional


def place_tp_sl(direction: str, quantity: float, tp_price: float, sl_price: float):
    tp_side = "SELL" if direction == "LONG" else "BUY"
    sl_side = "SELL" if direction == "LONG" else "BUY"
    try:
        _http(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": SYMBOL,
                "side": tp_side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": str(round(tp_price, 2)),
                "quantity": quantity,
                "workingType": "MARK_PRICE",
                "reduceOnly": "true",
            },
        )
        _http(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": SYMBOL,
                "side": sl_side,
                "type": "STOP_MARKET",
                "stopPrice": str(round(sl_price, 2)),
                "quantity": quantity,
                "workingType": "MARK_PRICE",
                "reduceOnly": "true",
            },
        )
        logger.info("PROTECT | TP=%.4f SL=%.4f qty=%s", tp_price, sl_price, quantity)
    except Exception as e:
        logger.error("PROTECT FAIL: %s", e)


def log_fill_economics(side: str, entry: float, qty: float, notional: float, order_id: Any):
    open_fee = notional * FEE_RATE
    logger.info(
        "FILL OPEN | side=%s entry=%.6f qty=%s notional=%.4f open_fee≈%.6f orderId=%s",
        side,
        entry,
        qty,
        notional,
        open_fee,
        order_id,
    )
    _open_meta[SYMBOL] = {
        "side": side,
        "entry": entry,
        "qty": qty,
        "notional": notional,
        "open_fee": open_fee,
        "ts": time.time(),
        "order_id": order_id,
    }


def log_close_economics(exit_px: float, reason: str):
    meta = _open_meta.get(SYMBOL)
    if not meta:
        return
    entry = meta["entry"]
    qty = meta["qty"]
    side = meta["side"]
    open_fee = meta["open_fee"]
    close_notional = exit_px * qty
    close_fee = close_notional * FEE_RATE
    if side == "LONG":
        raw = (exit_px - entry) * qty
        move_pct = (exit_px - entry) / entry * 100 if entry else 0
    else:
        raw = (entry - exit_px) * qty
        move_pct = (entry - exit_px) / entry * 100 if entry else 0
    total_fees = open_fee + close_fee
    net = raw - close_fee  # open fee already paid at open
    hold_sec = time.time() - meta["ts"]
    rec = {
        "symbol": SYMBOL,
        "side": side,
        "entry": entry,
        "exit": exit_px,
        "qty": qty,
        "raw_pnl": round(raw, 6),
        "open_fee": round(open_fee, 6),
        "close_fee": round(close_fee, 6),
        "total_fees": round(total_fees, 6),
        "net_pnl": round(net, 6),
        "move_pct": round(move_pct, 4),
        "reason": reason,
        "hold_sec": round(hold_sec, 1),
    }
    _journal.insert(0, rec)
    if len(_journal) > 100:
        _journal.pop()
    logger.info(
        "FILL CLOSE | %s %s reason=%s | entry=%.6f exit=%.6f move=%.3f%% | "
        "raw=%.6f fees=%.6f (open=%.6f+close=%.6f) NET=%.6f | hold=%.0fs",
        side,
        SYMBOL,
        reason,
        entry,
        exit_px,
        move_pct,
        raw,
        total_fees,
        open_fee,
        close_fee,
        net,
        hold_sec,
    )
    _open_meta.pop(SYMBOL, None)


def run_sovereign_cycle():
    logger.info("CYCLE | tarama başlıyor symbol=%s", SYMBOL)
    account = _http("GET", "/fapi/v2/account", {})
    assets = account.get("assets") or []
    usdt = next((a for a in assets if a.get("asset") == "USDT"), None)
    balance = float(usdt.get("availableBalance") or usdt.get("walletBalance") or 0) if usdt else 0.0
    logger.info("BALANCE | available=%.6f USDT | mode=%s", balance, "TESTNET" if USE_TESTNET else "LIVE")

    ticker = _http("GET", "/fapi/v1/ticker/price", {"symbol": SYMBOL}, signed=False)
    price = float(ticker["price"])

    klines = _http(
        "GET",
        "/fapi/v1/klines",
        {"symbol": SYMBOL, "interval": "15m", "limit": 30},
        signed=False,
    )
    closes = [float(k[4]) for k in klines]
    ema9 = sum(closes[-9:]) / 9 if len(closes) >= 9 else closes[-1]
    ema21 = sum(closes[-21:]) / 21 if len(closes) >= 21 else ema9
    ema_trend = "UP" if ema9 > ema21 else "DOWN"
    # basit RSI
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-14:] if d > 0]
    losses = [-d for d in deltas[-14:] if d < 0]
    ag = sum(gains) / 14 if gains else 0
    al = sum(losses) / 14 if losses else 1e-9
    rsi = 100 - (100 / (1 + ag / al))

    direction, confidence = get_ai_signal(SYMBOL, price, rsi, ema_trend)
    logger.info(
        "SIGNAL | %s conf=%d | price=%.4f RSI=%.1f EMA=%s",
        direction,
        confidence,
        price,
        rsi,
        ema_trend,
    )
    if confidence < AI_THRESHOLD:
        logger.info("SKIP | conf %d < threshold %d", confidence, AI_THRESHOLD)
        return

    qty, notional = calculate_position_size(balance, price, MAX_LEVERAGE)
    if qty <= 0 or notional < 5:
        logger.warning("SKIP | qty/notional yetersiz qty=%s notional=%.4f", qty, notional)
        return

    try:
        _http("POST", "/fapi/v1/leverage", {"symbol": SYMBOL, "leverage": int(MAX_LEVERAGE)})
        logger.info("LEVERAGE OK | %s %dx", SYMBOL, MAX_LEVERAGE)
    except Exception as e:
        logger.error("LEVERAGE FAIL: %s", e)
        return

    limit_price = price * (1.0001 if direction == "LONG" else 0.9999)
    tp_price = limit_price * (1 + TP_PCT) if direction == "LONG" else limit_price * (1 - TP_PCT)
    sl_price = limit_price * (1 - SL_PCT) if direction == "LONG" else limit_price * (1 + SL_PCT)

    side = "BUY" if direction == "LONG" else "SELL"
    params = {
        "symbol": SYMBOL,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": qty,
        "price": str(round(limit_price, 2)),
    }
    logger.info(
        "ORDER SEND | %s %s qty=%s limit=%.4f notional≈%.4f TP=%.4f SL=%.4f",
        direction,
        SYMBOL,
        qty,
        limit_price,
        notional,
        tp_price,
        sl_price,
    )
    order = _http("POST", "/fapi/v1/order", params)
    status = order.get("status")
    oid = order.get("orderId")
    avg = float(order.get("avgPrice") or 0) or limit_price
    if status in ("FILLED", "NEW", "PARTIALLY_FILLED"):
        logger.info("ORDER ACK | id=%s status=%s avg=%.6f", oid, status, avg)
        log_fill_economics(direction, avg, qty, notional, oid)
        place_tp_sl(direction, qty, tp_price, sl_price)
    else:
        logger.error("ORDER REJECT | %s", order)


def main():
    if not API_KEY or not API_SECRET:
        logger.error("KRITIK: API key/secret yok. .env kontrol et.")
        return
    sync_time()
    logger.info(
        "ONLINE | mode=%s base=%s symbol=%s lev=%dx fee=%.4f%% cycle=%ds",
        "TESTNET" if USE_TESTNET else "LIVE",
        BASE_URL,
        SYMBOL,
        MAX_LEVERAGE,
        FEE_RATE * 100,
        CYCLE_SEC,
    )
    while True:
        try:
            positions = _http("GET", "/fapi/v2/positionRisk", {"symbol": SYMBOL})
            open_pos = [p for p in positions if float(p.get("positionAmt") or 0) != 0] if positions else []
            if not open_pos:
                if SYMBOL in _open_meta:
                    # borsa tarafı kapandı, meta temizle
                    try:
                        ticker = _http("GET", "/fapi/v1/ticker/price", {"symbol": SYMBOL}, signed=False)
                        log_close_economics(float(ticker["price"]), "FLAT")
                    except Exception:
                        _open_meta.pop(SYMBOL, None)
                run_sovereign_cycle()
            else:
                p = open_pos[0]
                amt = float(p.get("positionAmt") or 0)
                entry = float(p.get("entryPrice") or 0)
                upnl = float(p.get("unRealizedProfit") or 0)
                mark = float(p.get("markPrice") or 0)
                logger.info(
                    "HOLD | amt=%s entry=%.6f mark=%.6f uPnL=%.6f",
                    amt,
                    entry,
                    mark,
                    upnl,
                )
            time.sleep(CYCLE_SEC)
        except KeyboardInterrupt:
            logger.info("Durduruldu.")
            break
        except Exception as e:
            logger.error("LOOP ERR: %s", e)
            time.sleep(10)


if __name__ == "__main__":
    main()
