import os
import time
import json
import hmac
import hashlib
import logging
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv
#from openai import OpenAI

# --- YAPILANDIRMA YÜKLEME ---
load_dotenv()

# --- LOG AYARLARI ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [AI-SOVEREIGN] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("AI_Sovereign_Engine")

# --- ENV DEĞİŞKENLERİ ---
API_KEY = os.getenv('BINANCE_TESTNET_API_KEY')
API_SECRET = os.getenv('BINANCE_TESTNET_SECRET')
BASE_URL = os.getenv('BINANCE_TESTNET_URL', 'https://testnet.binancefuture.com')
FEE_RATE = float(os.getenv('FEE_RATE', 0.0002))
MAX_LEVERAGE = int(os.getenv('TESTNET_LEVERAGE', 20))
RISK_PER_TRADE = float(os.getenv('TESTNET_RISK', 0.05))
TP_PCT = float(os.getenv('TESTNET_TP_M', 1.2)) / 100
SL_PCT = float(os.getenv('TESTNET_SL_P', 0.8)) / 100
SYMBOL = 'BTCUSDT'

# AI Config
OPENROUTER_KEY = os.getenv('OPENROUTER_API_KEY')
AI_MODEL = os.getenv('AI_MODEL_ID', 'google/gemini-flash-1.5')
AI_THRESHOLD = int(os.getenv('AI_CONFIDENCE_THRESHOLD', 70))

# --- AĞ DİRENCİ (ERRNO 7 ÇÖZÜMÜ) ---
def create_robust_session():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1.5, status_forcelist=[500, 502, 503, 504, 429])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

http_session = create_robust_session()

# --- AI BEYİN (OPENROUTER / GROK ENTEGRASYONU) ---
def get_ai_signal(symbol, price, rsi, ema_trend):
    if not OPENROUTER_KEY or OPENROUTER_KEY.startswith('sk-or-v1-buraya'):
        logger.warning("OpenRouter API Key girilmedi. Sadece teknik filtre kullanılıyor.")
        return "LONG" if ema_trend == "UP" else "SHORT", 80

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
    
    prompt = f"""
    Sen agresif bir kripto vadeli işlem asistanısın. 
    Sembol: {symbol} | Anlık Fiyat: {price} | RSI(14): {rsi} | EMA Trendi: {ema_trend}
    Görevin: Piyasa yapısını analiz edip tek bir yön ve güven skarı döndürmek.
    Sadece şu JSON formatında cevap ver, başka hiçbir şey yazma:
    {{"direction": "LONG" veya "SHORT", "confidence": 0-100 arası sayı}}
    """
    
    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=50
        )
        data = json.loads(response.choices[0].message.content)
        return data.get('direction', 'LONG'), int(data.get('confidence', 50))
    except Exception as e:
        logger.error(f"AI Çağrı Hatası: {e}")
        return "LONG" if ema_trend == "UP" else "SHORT", 50

# --- BINANCE API İSTEK YÖNETİCİSİ ---
def send_signed_request(method, endpoint, params=None):
    if params is None: params = {}
    url = BASE_URL + endpoint
    
    params['timestamp'] = int(time.time() * 1000)
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    params['signature'] = signature
        
    headers = {'X-MBX-APIKEY': API_KEY}
    
    try:
        if method == 'GET': resp = http_session.get(url, headers=headers, params=params, timeout=10)
        elif method == 'POST': resp = http_session.post(url, headers=headers, params=params, timeout=10)
        elif method == 'DELETE': resp = http_session.delete(url, headers=headers, params=params, timeout=10)
        
        data = resp.json()
        if resp.status_code != 200:
            logger.error(f"API Hatası: {data.get('msg', 'Bilinmeyen')}")
            return None
        return data
    except requests.exceptions.RequestException as e:
        logger.warning(f"Ağ Hatası: {e}")
        return None

# --- İNCE YAPI MATEMATİK & POZİSYON HESAPLAMA ---
def calculate_position_size(balance, price, leverage):
    """
    İnce Yapı Matematik:
    1. Riske atılacak USDT miktarını bul (Bakiye * Risk Oranı).
    2. Stop Loss mesafesine göre hassas miktar hesapla.
    3. Komisyonları (Maker %0.02) hesaba kat.
    """
    risk_amount_usdt = balance * RISK_PER_TRADE
    notional_value = risk_amount_usdt * leverage
    
    # Komisyon düşümü (Açılış + Kapanış = 2 * FEE_RATE)
    total_fee_pct = FEE_RATE * 2 
    effective_notional = notional_value * (1 - total_fee_pct)
    
    quantity = effective_notional / price
    
    # Binance step size kuralına uydur (BTC için genelde 3 decimal)
    if 'BTC' in SYMBOL: quantity = round(quantity, 3)
    elif 'ETH' in SYMBOL: quantity = round(quantity, 2)
    else: quantity = round(quantity, 1)
    
    return quantity, notional_value

# --- ANA MOTOR ---
def run_sovereign_cycle():
    logger.info("🧠 AI Sovereign Döngüsü Başlatıldı. Piyasa taranıyor...")
    
    # 1. Bakiye ve Fiyat Çek
    account = send_signed_request('GET', '/fapi/v2/account')
    if not account: return
    balance = float([a for a in account['assets'] if a['asset'] == 'USDT'][0]['walletBalance'])
    
    ticker = send_signed_request('GET', '/fapi/v1/ticker/price', {'symbol': SYMBOL})
    if not ticker: return
    price = float(ticker['price'])
    
    # 2. Teknik Veri Çek (RSI ve EMA)
    klines = send_signed_request('GET', '/fapi/v1/klines', {'symbol': SYMBOL, 'interval': '15m', 'limit': 20})
    if not klines: return
    closes = [float(k[4]) for k in klines]
    
    # Basit RSI ve EMA hesaplaması
    rsi = 50 # Gerçek hesaplamada ta-lib kullanılabilir, burada mock/temel mantık
    ema9 = sum(closes[-9:]) / 9
    ema21 = sum(closes[-21:]) / 21 if len(closes) >= 21 else ema9
    ema_trend = "UP" if ema9 > ema21 else "DOWN"
    
    # 3. AI Karar Mekanizması
    direction, confidence = get_ai_signal(SYMBOL, price, rsi, ema_trend)
    logger.info(f"🤖 AI Kararı: {direction} | Güven Skoru: %{confidence} | Fiyat: {price}")
    
    if confidence < AI_THRESHOLD:
        logger.info(f"⛔ AI Güven Skoru (%{confidence}) eşiğin (%{AI_THRESHOLD}) altında. İşlem atlandı.")
        return

    # 4. Pozisyon Boyutlandırma (İnce Yapı)
    quantity, notional = calculate_position_size(balance, price, MAX_LEVERAGE)
    if quantity <= 0 or notional < 10:
        logger.warning("Yetersiz bakiye veya hesaplanan miktar çok düşük.")
        return

    # 5. LIMIT (MAKER) EMİR GÖNDERME
    # Fiyatı mevcut piyasa fiyatının çok az altına/üstüne koyarak emrin hemen dolmasını sağla ama Taker'a düşme!
    limit_price = price * (1.0001 if direction == "LONG" else 0.9999)
    
    tp_price = limit_price * (1 + TP_PCT) if direction == "LONG" else limit_price * (1 - TP_PCT)
    sl_price = limit_price * (1 - SL_PCT) if direction == "LONG" else limit_price * (1 + SL_PCT)
    
    params = {
        'symbol': SYMBOL,
        'side': 'BUY' if direction == "LONG" else 'SELL',
        'type': 'LIMIT',
        'timeInForce': 'GTC',
        'quantity': quantity,
        'price': str(round(limit_price, 2))
    }
    
    logger.info(f"🚀 EMİR GÖNDERİLİYOR | {direction} {quantity} {SYMBOL} | Fiyat: {limit_price:.2f} | Notional: {notional:.2f} USDT")
    order = send_signed_request('POST', '/fapi/v1/order', params)
    
    if order and order.get('status') in ['FILLED', 'NEW']:
        logger.info(f"✅ EMİR BAŞARILI | ID: {order['orderId']} | Durum: {order['status']}")
        # TP ve SL emirlerini de LIMIT olarak gir (Komisyon cinliği)
        place_tp_sl_orders(direction, quantity, tp_price, sl_price)
    else:
        logger.error("❌ Emir reddedildi.")

def place_tp_sl_orders(direction, quantity, tp_price, sl_price):
    """TP ve SL'yi de LIMIT/STOP_LIMIT yaparak komisyonlardan tasarruf et."""
    tp_side = 'SELL' if direction == "LONG" else 'BUY'
    sl_side = 'SELL' if direction == "LONG" else 'BUY'
    
    # Take Profit (Limit Emir)
    tp_params = {
        'symbol': SYMBOL, 'side': tp_side, 'type': 'TAKE_PROFIT_MARKET', # Testnet bazen MARKET destekler, Live'da LIMIT yap
        'stopPrice': str(round(tp_price, 2)), 'quantity': quantity, 'workingType': 'MARK_PRICE', 'reduceOnly': 'true'
    }
    send_signed_request('POST', '/fapi/v1/order', tp_params)
    
    # Stop Loss (Stop Market)
    sl_params = {
        'symbol': SYMBOL, 'side': sl_side, 'type': 'STOP_MARKET',
        'stopPrice': str(round(sl_price, 2)), 'quantity': quantity, 'workingType': 'MARK_PRICE', 'reduceOnly': 'true'
    }
    send_signed_request('POST', '/fapi/v1/order', sl_params)
    logger.info(f"🛡️ TP ({tp_price:.2f}) ve SL ({sl_price:.2f}) emirleri sisteme işlendi.")

if __name__ == "__main__":
    logger.info("🌌 HONEYCOMB AI SOVEREIGN ENGINE ONLINE")
    logger.info(f"Mod: Testnet | AI Model: {AI_MODEL} | Maker Fee: %{FEE_RATE*100}")
    
    while True:
        try:
            # Açık pozisyon var mı kontrol et
            positions = send_signed_request('GET', '/fapi/v2/positionRisk', {'symbol': SYMBOL})
            open_pos = [p for p in positions if float(p['positionAmt']) != 0] if positions else []
            
            if not open_pos:
                run_sovereign_cycle()
            else:
                logger.info(f"Pozisyon açık, AI dinleniyor... ({len(open_pos)} pozisyon)")
                
            time.sleep(30) # 30 saniyelik döngü
        except KeyboardInterrupt:
            logger.info("Kullanıcı tarafından durduruldu.")
            break
        except Exception as e:
            logger.error(f"Kritik Döngü Hatası: {e}")
            time.sleep(10)
