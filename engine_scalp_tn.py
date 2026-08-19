#!/data/data/com.termux/files/usr/bin/python3
import os
import sys
import time
import math
import json
import hmac
import hashlib
import sqlite3
import threading
import urllib.request
import urllib.parse
from collections import deque
from flask import Flask, jsonify

app = Flask(__name__)

# Environment Configuration & Defaults
PORT = int(os.getenv("TESTNET_PORT", "8081"))
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
FALLBACK_PRICES = {"BTCUSDT": 64000.0, "ETHUSDT": 1870.0, "SOLUSDT": 76.0, "BNBUSDT": 600.0}

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "TESTNET_PAPER")  # "LIVE", "TESTNET_REST", "TESTNET_PAPER"
TESTNET_URL = os.getenv("BINANCE_TESTNET_URL", "https://testnet.binancefuture.com/fapi/v1")
LIVE_URL = os.getenv("BINANCE_LIVE_URL", "https://fapi.binance.com/fapi/v1")

BASE_URL = LIVE_URL if EXECUTION_MODE == "LIVE" else TESTNET_URL

# Mathematical Core Parameters
START_BALANCE = 10000.0
LEVERAGE = float(os.getenv("ENGINE_LEVERAGE", "50.0"))
FEE_RATE = 0.0002  # 0.02% taker fee
MAX_HOLD_TICKS = 20
INTERVAL = 5
COOLDOWN_TICKS = 2
MAX_DAILY_DRAWDOWN_PCT = 15.0

# Database Initialization with WAL Mode
DB_PATH = os.path.expanduser("~/honeycomb-execution-core/journal.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS journal (
            id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            reason TEXT,
            entry_price REAL,
            exit_price REAL,
            move_pct REAL,
            total_fees REAL,
            raw_pnl REAL,
            net_pnl REAL,
            margin_pnl_pct REAL,
            balance REAL,
            drawdown_pct REAL,
            timestamp REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Thread-Safe Memory Lock & O(1) Deque State Initialization
state_lock = threading.RLock()
last_known_prices = dict(FALLBACK_PRICES)
price_history = {sym: deque(maxlen=30) for sym in SYMBOLS}

balance = START_BALANCE
peak_balance = START_BALANCE
positions = {}
memory_journal = deque(maxlen=100)
engine_logs = deque(maxlen=300)
latency_samples = deque(maxlen=50)

execution_metrics = {
    "total_ticks": 0,
    "last_tick_time": time.time(),
    "circuit_breaker_active": False
}

def emit_log(msg):
    timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_line = f"{timestamp_str} [NEXUS-CORE] {msg}"
    with state_lock:
        engine_logs.appendleft(formatted_line)
    print(formatted_line, flush=True)

def generate_signature(query_string):
    return hmac.new(API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def execute_signed_request(method, endpoint, params=None):
    if not params:
        params = {}
    params['timestamp'] = int(time.time() * 1000)
    query_string = urllib.parse.urlencode(params)
    signature = generate_signature(query_string)
    full_url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    
    headers = {
        "X-MBX-APIKEY": API_KEY,
        "User-Agent": "NexusSovereignEngine/13.0"
    }
    req = urllib.request.Request(full_url, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read().decode('utf-8'))

def fetch_market_price(symbol):
    start_time = time.time()
    try:
        url = f"{BASE_URL}/ticker/price?symbol={symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "NexusEngine/13.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            px = float(data["price"])
            latency = (time.time() - start_time) * 1000.0
            with state_lock:
                last_known_prices[symbol] = px
                latency_samples.append(latency)
            return px, "LIVE_REST", latency
    except Exception as err:
        with state_lock:
            fallback_px = last_known_prices.get(symbol, FALLBACK_PRICES[symbol])
        return fallback_px, f"FALLBACK_ERR({type(err).__name__})", 0.0

def compute_indicators(symbol):
    with state_lock:
        prices = list(price_history[symbol])
    if len(prices) < 10:
        base_px = prices[-1] if prices else FALLBACK_PRICES[symbol]
        return {"signal": "NEUTRAL", "atr": base_px * 0.002, "ema_fast": base_px, "ema_slow": base_px}
    
    def calc_ema(data, period):
        k = 2.0 / (period + 1.0)
        ema = data[0]
        for val in data[1:]:
            ema = (val * k) + (ema * (1.0 - k))
        return ema

    ema_fast = calc_ema(prices[-5:], 3)
    ema_slow = calc_ema(prices[-10:], 8)
    
    diffs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    atr = sum(diffs[-5:]) / 5.0 if diffs else (prices[-1] * 0.002)
    
    signal = "NEUTRAL"
    if ema_fast > ema_slow * 1.0002:
        signal = "LONG"
    elif ema_fast < ema_slow * 0.9998:
        signal = "SHORT"
        
    return {"signal": signal, "atr": atr, "ema_fast": ema_fast, "ema_slow": ema_slow}

def calculate_kelly_position_size(win_rate=0.55, win_loss_ratio=1.5):
    q = 1.0 - win_rate
    f_star = (win_rate * win_loss_ratio - q) / win_loss_ratio
    fractional_kelly = max(0.02, min(f_star * 0.25, 0.15))
    return fractional_kelly

def check_circuit_breaker():
    global balance, peak_balance
    with state_lock:
        if peak_balance <= 0:
            return False
        current_dd = ((peak_balance - balance) / peak_balance) * 100.0
        if current_dd >= MAX_DAILY_DRAWDOWN_PCT:
            execution_metrics["circuit_breaker_active"] = True
            emit_log(f"CRITICAL CIRCUIT BREAKER ACTIVATED: Max Drawdown Exceeded [{current_dd:.2f}% >= {MAX_DAILY_DRAWDOWN_PCT}%]. Halting Execution.")
            return True
        return False

def open_execution_position(symbol, side, current_price, source_info):
    global balance
    if check_circuit_breaker():
        return
        
    with state_lock:
        active_positions = [p for p in positions.values() if p.get("status") == "OPEN"]
        if len(active_positions) >= 2:
            return
            
        risk_fraction = calculate_kelly_position_size()
        allocated_margin = balance * risk_fraction
        if allocated_margin < 5.0:
            emit_log("EXECUTION SKIPPED: Insufficient Margin Balance.")
            return

        indicators = compute_indicators(symbol)
        atr = indicators["atr"]
        
        sl_distance = max(current_price * 0.008, atr * 2.0)
        tp_distance = sl_distance * 1.8
        
        notional = allocated_margin * LEVERAGE
        quantity = notional / current_price
        entry_fee = notional * FEE_RATE
        balance -= entry_fee
        
        if side == "LONG":
            tp_price = current_price + tp_distance
            sl_price = current_price - sl_distance
        else:
            tp_price = current_price - tp_distance
            sl_price = current_price + sl_distance
            
        position_id = f"POS_{int(time.time() * 1000)}"
        position_record = {
            "id": position_id,
            "symbol": symbol,
            "side": side,
            "status": "OPEN",
            "entry": current_price,
            "high_watermark": current_price,
            "qty": quantity,
            "margin": allocated_margin,
            "notional": notional,
            "tp": tp_price,
            "sl": sl_price,
            "open_fee": entry_fee,
            "ticks": 0,
            "source": source_info
        }
        positions[position_id] = position_record
        
        emit_log(
            f"OPENED {side} on {symbol} @ {current_price:.4f} ({source_info}) | "
            f"Margin: ${allocated_margin:.2f} | Notional: ${notional:.2f} | Leverage: {LEVERAGE:.0f}x | "
            f"TP: {tp_price:.4f} | SL: {sl_price:.4f} | Fee: ${entry_fee:.4f}"
        )

def close_execution_position(pos, exit_price, reason_code, source_info):
    global balance, peak_balance
    exit_notional = pos["qty"] * exit_price
    close_fee = exit_notional * FEE_RATE
    
    if pos["side"] == "LONG":
        raw_pnl = (exit_price - pos["entry"]) * pos["qty"]
        price_move_pct = ((exit_price - pos["entry"]) / pos["entry"]) * 100.0
    else:
        raw_pnl = (pos["entry"] - exit_price) * pos["qty"]
        price_move_pct = ((pos["entry"] - exit_price) / pos["entry"]) * 100.0
        
    total_fees = pos["open_fee"] + close_fee
    net_pnl = raw_pnl - close_fee
    
    with state_lock:
        balance += pos["margin"] + net_pnl
        peak_balance = max(peak_balance, balance)
        current_dd = ((peak_balance - balance) / peak_balance) * 100.0 if peak_balance > 0 else 0.0
        margin_pnl_pct = (net_pnl / pos["margin"]) * 100.0 if pos["margin"] > 0 else 0.0
        
        pos["status"] = "CLOSED"
        
        trade_journal_entry = {
            "id": pos["id"],
            "symbol": pos["symbol"],
            "side": pos["side"],
            "reason": reason_code,
            "entry_price": round(pos["entry"], 4),
            "exit_price": round(exit_price, 4),
            "move_pct": round(price_move_pct, 4),
            "total_fees": round(total_fees, 4),
            "raw_pnl": round(raw_pnl, 4),
            "net_pnl": round(net_pnl, 4),
            "margin_pnl_pct": round(margin_pnl_pct, 2),
            "balance": round(balance, 2),
            "drawdown_pct": round(current_dd, 2),
            "timestamp": time.time()
        }
        
        memory_journal.appendleft(trade_journal_entry)
            
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10.0)
            c = conn.cursor()
            c.execute('''
                INSERT INTO journal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_journal_entry["id"], trade_journal_entry["symbol"], trade_journal_entry["side"],
                trade_journal_entry["reason"], trade_journal_entry["entry_price"], trade_journal_entry["exit_price"],
                trade_journal_entry["move_pct"], trade_journal_entry["total_fees"], trade_journal_entry["raw_pnl"],
                trade_journal_entry["net_pnl"], trade_journal_entry["margin_pnl_pct"], trade_journal_entry["balance"],
                trade_journal_entry["drawdown_pct"], trade_journal_entry["timestamp"]
            ))
            conn.commit()
            conn.close()
        except Exception as db_err:
            emit_log(f"DATABASE WRITE ERROR: {db_err}")

        emit_log(
            f"CLOSED {pos['side']} on {pos['symbol']} VIA {reason_code} @ {exit_price:.4f} ({source_info}) | "
            f"Move: {price_move_pct:+.3f}% | Fees: ${total_fees:.4f} | NET PnL: ${net_pnl:+.4f} ({margin_pnl_pct:+.1f}%) | "
            f"Balance: ${balance:.2f} | Drawdown: {current_dd:.2f}%"
        )

def evaluate_position_exit(pos, current_price):
    if pos["side"] == "LONG":
        if current_price > pos["high_watermark"]:
            pos["high_watermark"] = current_price
            new_sl = current_price * 0.994
            if new_sl > pos["sl"]:
                pos["sl"] = new_sl
        
        if current_price >= pos["tp"]:
            return "TAKE_PROFIT"
        if current_price <= pos["sl"]:
            return "STOP_LOSS"
    else:
        if current_price < pos["high_watermark"]:
            pos["high_watermark"] = current_price
            new_sl = current_price * 1.006
            if new_sl < pos["sl"]:
                pos["sl"] = new_sl
                
        if current_price <= pos["tp"]:
            return "TAKE_PROFIT"
        if current_price >= pos["sl"]:
            return "STOP_LOSS"
            
    return None

def execution_loop():
    emit_log(f"INITIALIZING EXECUTION CORE ENGINE | Mode: {EXECUTION_MODE} | Balance: ${balance:.2f} | Leverage: {LEVERAGE}x")
    tick_counter = 0
    cooldown = 0
    
    while True:
        try:
            with state_lock:
                execution_metrics["total_ticks"] = tick_counter
                execution_metrics["last_tick_time"] = time.time()
            
            target_symbol = SYMBOLS[tick_counter % len(SYMBOLS)]
            current_price, price_source, fetch_lat = fetch_market_price(target_symbol)
            
            with state_lock:
                price_history[target_symbol].append(current_price)

            with state_lock:
                open_positions = [p for p in positions.values() if p.get("status") == "OPEN"]
                
            if open_positions:
                for active_pos in open_positions:
                    active_pos["ticks"] += 1
                    px, src, _ = fetch_market_price(active_pos["symbol"])
                    exit_reason = evaluate_position_exit(active_pos, px)
                    
                    if exit_reason:
                        close_execution_position(active_pos, px, exit_reason, src)
                        cooldown = COOLDOWN_TICKS
                    elif active_pos["ticks"] >= MAX_HOLD_TICKS:
                        close_execution_position(active_pos, px, "MAX_TIME_EXPIRATION", src)
                        cooldown = COOLDOWN_TICKS
                    else:
                        emit_log(
                            f"HOLDING {active_pos['side']} {active_pos['symbol']} | Ticks: {active_pos['ticks']}/{MAX_HOLD_TICKS} | "
                            f"Price: {px:.4f} | Entry: {active_pos['entry']:.4f} | HWM: {active_pos['high_watermark']:.4f}"
                        )
            else:
                if cooldown > 0:
                    cooldown -= 1
                    emit_log(f"COOLDOWN ACTIVE: {cooldown} ticks remaining.")
                else:
                    indicator_data = compute_indicators(target_symbol)
                    sig = indicator_data["signal"]
                    if sig in ["LONG", "SHORT"]:
                        open_execution_position(target_symbol, sig, current_price, price_source)

            tick_counter += 1
        except Exception as main_err:
            emit_log(f"EXECUTION UNHANDLED EXCEPTION [{type(main_err).__name__}]: {main_err}")
            
        time.sleep(INTERVAL)

# Telemetry Microservices API Router
@app.route("/health", methods=["GET"])
def http_health():
    with state_lock:
        age = time.time() - execution_metrics["last_tick_time"]
        is_healthy = age < (INTERVAL * 3) and not execution_metrics["circuit_breaker_active"]
    return jsonify({
        "status": "HEALTHY" if is_healthy else "DEGRADED",
        "ticks": execution_metrics["total_ticks"],
        "age_seconds": round(age, 2),
        "circuit_breaker": execution_metrics["circuit_breaker_active"],
        "engine": "Nexus-Execution-Core-v13.0"
    }), 200 if is_healthy else 500

@app.route("/status", methods=["GET"])
def http_status():
    with state_lock:
        open_count = sum(1 for p in positions.values() if p.get("status") == "OPEN")
        avg_lat = sum(latency_samples) / len(latency_samples) if latency_samples else 0.0
        return jsonify({
            "balance": round(balance, 2),
            "peak_balance": round(peak_balance, 2),
            "open_positions": open_count,
            "leverage": LEVERAGE,
            "total_trades": len(memory_journal),
            "mode": EXECUTION_MODE,
            "avg_latency_ms": round(avg_lat, 2)
        })

@app.route("/journal", methods=["GET"])
def http_journal():
    with state_lock:
        return jsonify(list(memory_journal))

@app.route("/logs", methods=["GET"])
def http_logs():
    with state_lock:
        return jsonify(list(engine_logs))

@app.route("/metrics", methods=["GET"])
def http_metrics():
    with state_lock:
        wins = [t for t in memory_journal if t.get("net_pnl", 0) > 0]
        losses = [t for t in memory_journal if t.get("net_pnl", 0) <= 0]
        total_net_pnl = sum(t.get("net_pnl", 0) for t in memory_journal)
        total_fees = sum(t.get("total_fees", 0) for t in memory_journal)
        win_rate = (len(wins) / len(memory_journal) * 100.0) if memory_journal else 0.0
        
        return jsonify({
            "metrics": {
                "current_balance": round(balance, 2),
                "total_net_pnl": round(total_net_pnl, 4),
                "total_fees_paid": round(total_fees, 4),
                "total_trades": len(memory_journal),
                "win_count": len(wins),
                "loss_count": len(losses),
                "win_rate_pct": round(win_rate, 2),
                "max_drawdown_pct": round(((peak_balance - balance) / peak_balance * 100.0) if peak_balance > 0 else 0.0, 2)
            }
        })

if __name__ == "__main__":
    daemon_thread = threading.Thread(target=execution_loop, daemon=True)
    daemon_thread.start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)
