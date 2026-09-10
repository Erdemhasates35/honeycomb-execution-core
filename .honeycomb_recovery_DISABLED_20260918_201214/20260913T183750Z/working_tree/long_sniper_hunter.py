import os
import time
import hmac
import hashlib
import logging
import requests
import math
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- LOG AYARLARI ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("LONG_SNIPER")

# --- .ENV OKUYUCU ---
def load_env(filepath='.env'):
    env_vars = {}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    env_vars[key.strip()] = val.strip()
    except FileNotFoundError:
        logger.warning(".env dosyası bulunamadı, varsayılanlar kullanılıyor.")
    return env_vars

ENV = load_env()
API_KEY = ENV.get('BINANCE_TESTNET_API_KEY', '')
API_SECRET = ENV.get('BINANCE_TESTNET_SECRET', '')
BASE_URL = ENV.get('BINANCE_TESTNET_URL', 'https://testnet.binancefuture.com')

SYMBOLS = ENV.get('LIVE_SYMBOLS', 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT').split(',')
RISK_PER_TRADE = float(ENV.get('TESTNET_RISK', 0.02)) # Çift motor çalıştığı için riski biraz düşürdüm (0.05 -> 0.02)
MAX_LEVERAGE = int(ENV.get('TESTNET_LEVERAGE', 20))
TP_PCT = float(ENV.get('TESTNET_TP_M', 1.2)) / 100
SL_PCT = float(ENV.get('TESTNET_SL_P', 0.8)) / 100

# --- AĞ DİRENCİ (Timeout artırıldı) ---
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

# --- BINANCE API YÖNETİCİSİ ---
def get_signed_params(params=None):
    if params is None: params = {}
    params['timestamp'] = int(time.time() * 1000)
    query = '&'.join([f"{k}={v}" for k, v in params.items()])
    params['signature'] = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return params

def api_request(method, endpoint, params=None, signed=False):
    url = BASE_URL + endpoint
    if signed: params = get_signed_params(params or {})
    headers = {'X-MBX-APIKEY': API_KEY} if signed else {}
    try:
        # Timeout süresi ağ kopmalarına karşı 15 saniyeye çıkarıldı
        resp = session.request(method, url, headers=headers, params=params, timeout=15)
        data = resp.json()
        if resp.status_code != 200:
            logger.error(f"API Hatası: {data.get('msg', 'Bilinmeyen')}")
            return None
        return data
    except Exception as e:
        logger.error(f"Ağ Hatası: {e}")
        return None

def get_symbol_rules(symbol):
    info = api_request('GET', '/fapi/v1/exchangeInfo')
    if not info: return None, None
    for s in info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'PRICE_FILTER': tick = float(f['tickSize'])
                if f['filterType'] == 'LOT_SIZE': step = float(f['stepSize'])
            return tick, step
    return None, None

def round_tick(price, tick_size):
    precision = int(round(-math.log10(tick_size)))
    return round(math.floor(price / tick_size) * tick_size, precision)

def round_step(qty, step_size):
    precision = int(round(-math.log10(step_size)))
    return round(math.floor(qty / step_size) * step_size, precision)

# --- İNDİKATÖR MOTORU ---
def calc_ema(data, period):
    if len(data) < period: return data[-1]
    mult = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for price in data[period:]: ema = (price - ema) * mult + ema
    return ema

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(closes):
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd_line = ema12 - ema26
    macd_hist = []
    for i in range(len(closes)-9, len(closes)):
        e12 = calc_ema(closes[:i+1], 12)
        e26 = calc_ema(closes[:i+1], 26)
        macd_hist.append(e12 - e26)
    signal = sum(macd_hist) / len(macd_hist)
    return macd_line, signal, macd_line - signal

# --- LONG POTANSİYEL ANALİZİ (SHORT'UN TAM TERSİ) ---
def analyze_long_potential(symbol):
    """Bir coinin LONG (Yükseliş) potansiyelini 0-100 arasında puanlar"""
    klines = api_request('GET', '/fapi/v1/klines', {'symbol': symbol, 'interval': '15m', 'limit': 100})
    if not klines: return 0, 0
    
    closes = [float(k[4]) for k in klines]
    current_price = closes[-1]
    score = 0

    # 1. RSI (Aşırı Satım Bölgesi LONG için altın madenidir)
    rsi = calc_rsi(closes)
    if rsi < 25: score += 40
    elif rsi < 35: score += 20

    # 2. MACD (Momentum Yükselişi)
    macd, signal, hist = calc_macd(closes)
    if hist > 0 and macd > signal: score += 30

    # 3. EMA Trend (Fiyat EMA50 üstündeyse baskı yukarıdır)
    ema50 = calc_ema(closes, 50)
    if current_price > ema50: score += 20

    # 4. Bollinger Alt Bant Vuruşu (Düşüşün sonu, dönüş sinyali)
    sma20 = sum(closes[-20:]) / 20
    std20 = (sum((x - sma20) ** 2 for x in closes[-20:]) / 20) ** 0.5
    lower_band = sma20 - (2 * std20)
    if current_price <= lower_band * 1.005: score += 10

    return score, current_price

# --- ÇAKIŞMA ÖNLEYİCİ (ANTI-CLASH) ---
def get_open_short_positions():
    """Short motorunun açtığı pozisyonları çeker, aynı coine LONG açılmasını engeller."""
    positions = api_request('GET', '/fapi/v2/positionRisk', signed=True)
    if not positions: return []
    # positionAmt < 0 ise SHORT pozisyon vardır.
    return [p['symbol'] for p in positions if float(p['positionAmt']) < 0]

# --- ANA LONG AVCI MOTORU ---
def run_hunter_cycle():
    logger.info("🎯 LONG SNIPER HUNTER TARAMAYA BAŞLADI (PARALEL MOD)...")
    
    # Çakışma kontrolü: Hangi coinlerde zaten SHORT var?
    blocked_symbols = get_open_short_positions()
    if blocked_symbols:
        logger.info(f"🚫 Short motoru şu an {blocked_symbols} coinlerinde SHORT tutuyor. LONG için engellendi.")

    best_symbol = None
    best_score = 0
    best_price = 0

    # PARALEL TARAMA (Maksimum Verimlilik)
    # Ağ kopmalarında bir coin beklemesin diye 5 paralel thread açıyoruz.
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_symbol = {executor.submit(analyze_long_potential, sym.strip()): sym.strip() 
                            for sym in SYMBOLS if sym.strip() not in blocked_symbols}
        
        for future in as_completed(future_to_symbol):
            sym = future_to_symbol[future]
            try:
                score, price = future.result()
                logger.info(f" 🔍 {sym} | LONG Skoru: {score}/100 | Fiyat: {price}")
                if score > best_score and score >= 70:
                    best_score = score
                    best_symbol = sym
                    best_price = price
            except Exception as exc:
                logger.error(f" ⚠️ {sym} taranırken hata: {exc}")

    if not best_symbol:
        logger.info("⛔ Şu an için yüksek güvenilirlikte LONG fırsatı yok. Bekleniyor...")
        return

    logger.info(f"🚨 HEDEF BULUNDU: {best_symbol} | Skor: {best_score}/100 | Fiyat: {best_price}")

    # Pozisyon Boyutlandırma
    account = api_request('GET', '/fapi/v2/account', signed=True)
    if not account: return
    balance = float([a for a in account['assets'] if a['asset'] == 'USDT'][0]['walletBalance'])
    risk_amount = balance * RISK_PER_TRADE
    notional = risk_amount * MAX_LEVERAGE
    qty = notional / best_price

    tick_size, step_size = get_symbol_rules(best_symbol)
    if not tick_size: return
    qty = round_step(qty, step_size)
    if qty <= 0:
        logger.warning("Miktar çok küçük veya bakiye yetersiz.")
        return

    # LONG EMRİ (Taker'a düşmemesi için çok az üstünden LIMIT)
    limit_price = round_tick(best_price * 1.0001, tick_size) 

    params = {
        'symbol': best_symbol, 'side': 'BUY', 'type': 'LIMIT', 'timeInForce': 'GTC',
        'quantity': qty, 'price': str(limit_price)
    }
    
    logger.info(f"🚀 EMİR GÖNDERİLİYOR | LONG {qty} {best_symbol} | Fiyat: {limit_price} | Notional: {notional:.2f}$")
    order = api_request('POST', '/fapi/v1/order', params, signed=True)

    if order and order.get('status') in ['NEW', 'FILLED']:
        logger.info(f"✅ EMİR BAŞARILI | ID: {order['orderId']}")
        
        tp_price = round_tick(limit_price * (1 + TP_PCT), tick_size)
        sl_price = round_tick(limit_price * (1 - SL_PCT), tick_size)

        api_request('POST', '/fapi/v1/order', {
            'symbol': best_symbol, 'side': 'SELL', 'type': 'TAKE_PROFIT_MARKET',
            'stopPrice': str(tp_price), 'quantity': qty, 'workingType': 'MARK_PRICE', 'reduceOnly': 'true'
        }, signed=True)
        
        api_request('POST', '/fapi/v1/order', {
            'symbol': best_symbol, 'side': 'SELL', 'type': 'STOP_MARKET',
            'stopPrice': str(sl_price), 'quantity': qty, 'workingType': 'MARK_PRICE', 'reduceOnly': 'true'
        }, signed=True)
        
        logger.info(f"🛡️ TP ({tp_price}) ve SL ({sl_price}) sisteme işlendi.")
    else:
        logger.error("❌ Emir reddedildi.")

if __name__ == "__main__":
    logger.info("🌌 HONEYCOMB LONG SNIPER HUNTER ONLINE (PARALEL)")
    logger.info(f"Taranacak Coinler: {SYMBOLS}")
    while True:
        try:
            # Kendi pozisyonlarını kontrol et (Short motoru kendi işine bakar)
            positions = api_request('GET', '/fapi/v2/positionRisk', signed=True)
            open_long_pos = [p for p in positions if float(p['positionAmt']) > 0] if positions else []
            
            if not open_long_pos:
                run_hunter_cycle()
            else:
                logger.info(f"Pozisyon açık, yönetiliyor... ({len(open_long_pos)} LONG pozisyon)")
                
            time.sleep(45)
        except KeyboardInterrupt:
            logger.info("Bot durduruldu.")
            break
        except Exception as e:
            logger.error(f"Kritik Hata: {e}")
            time.sleep(10)
