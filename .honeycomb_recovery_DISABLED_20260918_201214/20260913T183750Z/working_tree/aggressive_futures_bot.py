import requests
import hmac
import hashlib
import time
import json
import logging
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# --- YAPILANDIRMA (CONFIG) ---
API_KEY = 'pvyl41vtH7R8YpW1g0KnnPxDhZbEigpZFzdnwftmnC8HETkEJQtJSaNumSAIXAaI'
API_SECRET = 'ARwQgGxxVZqkUPm9vOUhf89gMUlKjzsgUirdxl0y62jSVEsUngaCZsk2Z07gnyIF'
BASE_URL = 'https://fapi.binance.com'
SYMBOL = 'BTCUSDT'
LEVERAGE = 20
# Agresif ama güvenli: Bakiyenin %2'si ile işlem aç (1000$ varsa 20$ marjin)
RISK_PER_TRADE_RATIO = 0.02 
TRAILING_STOP_ACTIVATION = 0.003  # %0.3 kârda devreye girer
TRAILING_STOP_CALLBACK = 0.001    # %0.1 geri çekilmede kapatır

# --- LOG AYARLARI ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Nexus_Aggressive_Engine")

# --- AĞ DİRENCİ (ERRNO 7 ÇÖZÜMÜ) ---
def create_robust_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504, 429],
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

http_session = create_robust_session()

# --- BİNAANCE API İMZA VE İSTEK YÖNETİCİSİ ---
def send_signed_request(method, endpoint, params=None, is_signed=True):
    if params is None:
        params = {}
    
    url = BASE_URL + endpoint
    
    if is_signed:
        params['timestamp'] = int(time.time() * 1000)
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        params['signature'] = signature
        
    headers = {'X-MBX-APIKEY': API_KEY}
    
    try:
        if method == 'GET':
            response = http_session.get(url, headers=headers, params=params, timeout=10)
        elif method == 'POST':
            response = http_session.post(url, headers=headers, params=params, timeout=10)
        elif method == 'DELETE':
            response = http_session.delete(url, headers=headers, params=params, timeout=10)
            
        data = response.json()
        if response.status_code != 200:
            logger.error(f"API Hatası: {data}")
            return None
        return data
    except requests.exceptions.RequestException as e:
        logger.warning(f"Ağ Hatası (Yeniden deneniyor...): {e}")
        time.sleep(2)
        return None

# --- BAKİYE VE POZİSYON YÖNETİMİ ---
def get_usdt_balance():
    account = send_signed_request('GET', '/fapi/v2/account')
    if not account: return 0
    for asset in account['assets']:
        if asset['asset'] == 'USDT':
            return float(asset['walletBalance'])
    return 0

def set_leverage(symbol, leverage):
    params = {'symbol': symbol, 'leverage': leverage}
    send_signed_request('POST', '/fapi/v1/leverage', params)

def get_open_positions(symbol):
    positions = send_signed_request('GET', '/fapi/v2/positionRisk', {'symbol': symbol})
    if not positions: return []
    return [p for p in positions if float(p['positionAmt']) != 0]

# --- AGRESİF MOTOR (MAKER EMİR + TRAILING STOP) ---
def execute_aggressive_trade():
    balance = get_usdt_balance()
    if balance <= 0:
        logger.error("Bakiye 0 veya API hatası. Bekleniyor...")
        return

    margin = balance * RISK_PER_TRADE_RATIO
    if margin < 10:
        logger.warning(f"Yetersiz Marjin: {margin:.2f} USDT. Minimum 10 USDT gerekli.")
        return

    set_leverage(SYMBOL, LEVERAGE)
    
    # Anlık fiyatı al
    ticker = send_signed_request('GET', '/fapi/v1/ticker/price', {'symbol': SYMBOL}, is_signed=False)
    if not ticker: return
    current_price = float(ticker['price'])
    
    # Yön belirleme (Basit Momentum: Son 5 mumun yönü)
    klines = send_signed_request('GET', '/fapi/v1/klines', {'symbol': SYMBOL, 'interval': '5m', 'limit': 5}, is_signed=False)
    if not klines: return
    
    close_prices = [float(k[4]) for k in klines]
    is_bullish = close_prices[-1] > close_prices[0]
    
    side = 'BUY' if is_bullish else 'SELL'
    
    # KOMİSYON İÇİN LIMIT (MAKER) EMİR KULLAN
    # Fiyatı mevcut fiyatın %0.01 altından/üstünden vererek emrin hemen dolmasını sağla ama Maker sayılsın
    limit_price = current_price * (0.9999 if side == 'BUY' else 1.0001)
    quantity = round((margin * LEVERAGE) / limit_price, 3)
    
    params = {
        'symbol': SYMBOL,
        'side': side,
        'type': 'LIMIT',
        'timeInForce': 'GTC',
        'quantity': quantity,
        'price': str(limit_price)
    }
    
    logger.info(f"[SİNYAL] {side} {SYMBOL} | Fiyat: {limit_price:.2f} | Miktar: {quantity} | Marjin: {margin:.2f}")
    order = send_signed_request('POST', '/fapi/v1/order', params)
    
    if order and order.get('status') in ['FILLED', 'NEW']:
        logger.info(f"[EMİR AÇILDI] ID: {order['orderId']} | Durum: {order['status']}")
        monitor_trailing_stop(order['orderId'], side, limit_price, quantity)
    else:
        logger.error("Emir reddedildi veya beklemeye alındı.")

def monitor_trailing_stop(order_id, side, entry_price, quantity):
    logger.info("[İZ SÜREN STOP] Aktif. Pozisyon izleniyor...")
    highest_pnl_price = entry_price
    lowest_pnl_price = entry_price
    
    while True:
        time.sleep(2)
        ticker = send_signed_request('GET', '/fapi/v1/ticker/price', {'symbol': SYMBOL}, is_signed=False)
        if not ticker: continue
        current_price = float(ticker['price'])
        
        if side == 'BUY':
            pnl_pct = (current_price - entry_price) / entry_price
            if current_price > highest_pnl_price:
                highest_pnl_price = current_price
                
            # Aktivasyon ve Geri Çekilme
            activation_reached = (highest_pnl_price - entry_price) / entry_price >= TRAILING_STOP_ACTIVATION
            callback_triggered = (highest_pnl_price - current_price) / highest_pnl_price >= TRAILING_STOP_CALLBACK
            
            if activation_reached and callback_triggered:
                close_position(side, quantity)
                break
        else: # SELL
            pnl_pct = (entry_price - current_price) / entry_price
            if current_price < lowest_pnl_price:
                lowest_pnl_price = current_price
                
            activation_reached = (entry_price - lowest_pnl_price) / entry_price >= TRAILING_STOP_ACTIVATION
            callback_triggered = (current_price - lowest_pnl_price) / lowest_pnl_price >= TRAILING_STOP_CALLBACK
            
            if activation_reached and callback_triggered:
                close_position(side, quantity)
                break

def close_position(side, quantity):
    close_side = 'SELL' if side == 'BUY' else 'BUY'
    # Pozisyonu kapatmak için piyasa emri (Taker) kullanıyoruz çünkü çıkışta hız önemlidir.
    params = {
        'symbol': SYMBOL,
        'side': close_side,
        'type': 'MARKET',
        'quantity': quantity,
        'reduceOnly': 'true'
    }
    logger.info(f"[KAPANIŞ] Pozisyon kapatılıyor. Yön: {close_side}")
    send_signed_request('POST', '/fapi/v1/order', params)

# --- ANA DÖNGÜ ---
if __name__ == "__main__":
    logger.info("🚀 NEXUS AGRESİF MOTOR BAŞLATILDI")
    logger.info("Ağ direnci aktif, komisyon optimizasyonu (Maker) yüklendi.")
    
    while True:
        try:
            open_pos = get_open_positions(SYMBOL)
            if not open_pos:
                execute_aggressive_trade()
            else:
                logger.info(f"Açık pozisyon var, izleniyor... ({len(open_pos)} adet)")
            
            time.sleep(15) # 15 saniyede bir döngü
        except KeyboardInterrupt:
            logger.info("Bot kullanıcı tarafından durduruldu.")
            break
        except Exception as e:
            logger.error(f"Beklenmeyen Hata: {e}")
            time.sleep(5)
