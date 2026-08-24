import os
import time
import hmac
import hashlib
import logging
import requests
import math
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# --- LOG AYARLARI ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("SHORT_HUNTER")

# --- SAF PYTHON .ENV OKUYUCU (dotenv gerektirmez) ---
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
RISK_PER_TRADE = float(ENV.get('TESTNET_RISK', 0.05))
MAX_LEVERAGE = int(ENV.get('TESTNET_LEVERAGE', 20))
TP_PCT = float(ENV.get('TESTNET_TP_M', 1.2)) / 100
SL_PCT = float(ENV.get('TESTNET_SL_P', 0.8)) / 100

# --- AĞ DİRENCİ ---
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

# --- BINANCE API MATEMATİK & İSTEK YÖNETİCİSİ ---
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
        resp = session.request(method, url, headers=headers, params=params, timeout=10)
        data = resp.json()
        if resp.status_code != 200:
            logger.error(f"API Hatası: {data.get('msg', 'Bilinmeyen')}")
            return None
        return data
    except Exception as e:
        logger.error(f"Ağ Hatası: {e}")
        return None

def get_symbol_rules(symbol):
    """Binance'in tickSize ve stepSize kurallarını dinamik çeker (Price not increased hatasını çözer)"""
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
    """Fiyatı Binance'in kabul ettiği ondalık basamağa yuvarlar"""
    precision = int(round(-math.log10(tick_size)))
    return round(math.floor(price / tick_size) * tick_size, precision)

def round_step(qty, step_size):
    """Miktarı Binance'in kabul ettiği ondalık basamağa yuvarlar"""
    precision = int(round(-math.log10(step_size)))
    return round(math.floor(qty / step_size) * step_size, precision)

# --- SAF PYTHON İNDİKATÖR MOTORU ---
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
    # Basitleştirilmiş sinyal (son 9 mumun MACD ortalaması)
    macd_hist = []
    for i in range(len(closes)-9, len(closes)):
        e12 = calc_ema(closes[:i+1], 12)
        e26 = calc_ema(closes[:i+1], 26)
        macd_hist.append(e12 - e26)
    signal = sum(macd_hist) / len(macd_hist)
    return macd_line, signal, macd_line - signal

def analyze_short_potential(symbol):
    """Bir coinin SHORT (Düşüş) potansiyelini 0-100 arasında puanlar"""
    klines = api_request('GET', '/fapi/v1/klines', {'symbol': symbol, 'interval': '15m', 'limit': 100})
    if not klines: return 0, 0
    
    closes = [float(k[4]) for k in klines]
    current_price = closes[-1]
    score = 0
    
    # 1. RSI (Aşırı Alım Bölgesi SHORT için altın madenidir)
    rsi = calc_rsi(closes)
    if rsi > 75: score += 40
    elif rsi > 65: score += 20
    
    # 2. MACD (Momentum Düşüşü)
    macd, signal, hist = calc_macd(closes)
    if hist < 0 and macd < signal: score += 30
    
    # 3. EMA Trend (Fiyat EMA50 altındaysa baskı var)
    ema50 = calc_ema(closes, 50)
    if current_price < ema50: score += 20
    
    # 4. Bollinger Üst Bant Vuruşu
    sma20 = sum(closes[-20:]) / 20
    std20 = (sum((x - sma20) ** 2 for x in closes[-20:]) / 20) ** 0.5
    upper_band = sma20 + (2 * std20)
    if current_price >= upper_band * 0.995: score += 10
    
    return score, current_price

# --- ANA AVCI MOTORU ---
def run_hunter_cycle():
    logger.info("🎯 AGRESİF SHORT AVCI MOTORU TARAMAYA BAŞLADI...")
    best_symbol = None
    best_score = 0
    best_price = 0
    
    # Tüm coinleri tara, en yüksek SHORT potansiyelli olanı bul
    for sym in SYMBOLS:
        sym = sym.strip()
        score, price = analyze_short_potential(sym)
        logger.info(f" 🔍 {sym} | SHORT Skoru: {score}/100 | Fiyat: {price}")
        if score > best_score and score >= 70:  # Minimum 70 puan gerekli
            best_score = score
            best_symbol = sym
            best_price = price
            
    if not best_symbol:
        logger.info("⛔ Şu an için yüksek güvenilirlikte SHORT fırsatı yok. Bekleniyor...")
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

    # Fiyatı_tick_size'a göre yuvarla (Price not increased hatasını %100 çözer)
    limit_price = round_tick(best_price * 0.9999, tick_size) # Çok az altından LIMIT atarak Taker'a düşme
    
    # SHORT EMRİ GÖNDER
    params = {
        'symbol': best_symbol,
        'side': 'SELL',
        'type': 'LIMIT',
        'timeInForce': 'GTC',
        'quantity': qty,
        'price': str(limit_price)
    }
    
    logger.info(f"🚀 EMİR GÖNDERİLİYOR | SHORT {qty} {best_symbol} | Fiyat: {limit_price} | Notional: {notional:.2f}$")
    order = api_request('POST', '/fapi/v1/order', params, signed=True)
    
    if order and order.get('status') in ['NEW', 'FILLED']:
        logger.info(f"✅ EMİR BAŞARILI | ID: {order['orderId']}")
        # TP ve SL Ayarla
        tp_price = round_tick(limit_price * (1 - TP_PCT), tick_size)
        sl_price = round_tick(limit_price * (1 + SL_PCT), tick_size)
        
        api_request('POST', '/fapi/v1/order', {
            'symbol': best_symbol, 'side': 'BUY', 'type': 'TAKE_PROFIT_MARKET',
            'stopPrice': str(tp_price), 'quantity': qty, 'workingType': 'MARK_PRICE', 'reduceOnly': 'true'
        }, signed=True)
        
        api_request('POST', '/fapi/v1/order', {
            'symbol': best_symbol, 'side': 'BUY', 'type': 'STOP_MARKET',
            'stopPrice': str(sl_price), 'quantity': qty, 'workingType': 'MARK_PRICE', 'reduceOnly': 'true'
        }, signed=True)
        logger.info(f"🛡️ TP ({tp_price}) ve SL ({sl_price}) sisteme işlendi.")
    else:
        logger.error("❌ Emir reddedildi.")

if __name__ == "__main__":
    logger.info("🌌 HONEYCOMB AGRESİF SHORT HUNTER ONLINE")
    logger.info(f"Taranacak Coinler: {SYMBOLS}")
    while True:
        try:
            positions = api_request('GET', '/fapi/v2/positionRisk', signed=True)
            open_pos = [p for p in positions if float(p['positionAmt']) != 0] if positions else []
            if not open_pos:
                run_hunter_cycle()
            else:
                logger.info(f"Pozisyon açık, yönetiliyor... ({len(open_pos)} pozisyon)")
            time.sleep(45) # 45 saniyelik tarama döngüsü
        except KeyboardInterrupt:
            logger.info("Bot durduruldu.")
            break
        except Exception as e:
            logger.error(f"Kritik Hata: {e}")
            time.sleep(10)
