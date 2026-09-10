import ccxt
import os

# API Anahtarlarınızı buraya ekleyin veya Termux ortam değişkenlerinden (export) çekin
API_KEY = os.getenv('BINANCE_API_KEY', 'API_ANAHTARINIZI_YAZIN')
SECRET_KEY = os.getenv('BINANCE_SECRET_KEY', 'GIZLI_ANAHTARINIZI_YAZIN')

exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'} # Vadeli işlemler (Futures) için zorunlu
})

print("[!] Honeycomb Acil Durum Protokolü Başlatıldı...\n")

try:
    # Güncel cüzdan bakiyesini çek
    balance = exchange.fetch_balance()
    usdt_balance = balance['total'].get('USDT', 0)
    print(f"[+] Kalan Toplam USDT Bakiyesi: {usdt_balance}\n")

    print("[!] Risk Altındaki Pozisyonlar Kontrol Ediliyor...")
    positions = balance['info']['positions']
    
    # Miktarı 0'dan farklı olan aktif pozisyonları filtrele
    active_positions = [p for p in positions if float(p['positionAmt']) != 0]

    if active_positions:
        for pos in active_positions:
            symbol = pos['symbol']
            amt = pos['positionAmt']
            pnl = pos['unrealizedProfit']
            print(f" -> Sembol: {symbol} | Miktar: {amt} | Zarar/Kar (PNL): {pnl}")
            
            # Kalan pozisyonların sembolündeki bekleyen (limit/stop) emirleri anında iptal et
            try:
                exchange.cancel_all_orders(symbol)
                print(f"    [+] {symbol} için bekleyen tüm riskli emirler iptal edildi.")
            except Exception as e:
                pass
    else:
        print("[+] Açık pozisyon bulunmuyor. Sistem likide olmuş veya temizlenmiş.")

except Exception as e:
    print(f"[-] Kritik Hata (API/Bağlantı): {e}")
