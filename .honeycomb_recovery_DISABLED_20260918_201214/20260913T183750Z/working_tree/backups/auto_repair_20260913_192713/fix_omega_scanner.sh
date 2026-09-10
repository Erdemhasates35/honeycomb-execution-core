#!/bin/bash

echo "[*] 1. Aşama: Zaman Senkronizasyonu (Time Sync Fail Çözümü)"
# NTP paketini kur ve zamanı senkronize et
pkg update -y && pkg install ntp -y
ntpd -q -p pool.ntp.org

echo "[*] 2. Aşama: API Uç Noktası Ağ Testi"
# Bağlantı kısıtlamalarını kontrol et
curl -I -s --connect-timeout 5 https://api.binance.com/api/v3/time || echo "[!] Ana API engelli, Python scripti alternatifleri deneyecek."

echo "[*] 3. Aşama: Python WAF ve Timeout Yaması Oluşturuluyor..."
# Orijinal extreme_scanner_omega.py dosyana entegre etmen gereken yapı:
cat << 'PYEOF' > omega_api_patch.py
import time
import urllib.request
import urllib.error
import json

def safe_api_request():
    # Sadece api.binance.com değil, banlanmayan yedek endpointler
    endpoints = [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com"
    ]
    
    # Borsa WAF (Cloudflare/AWS) engellerini aşmak için zorunlu Header
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }

    for base_url in endpoints:
        try:
            # Senkronize edilmiş güncel zaman damgası
            timestamp = int(time.time() * 1000)
            url = f"{base_url}/api/v3/time" 
            
            # NOT: Bakiye (equity) sorgularında params içine mutlaka 'recvWindow=10000' eklemelisin.
            
            req = urllib.request.Request(url, headers=headers)
            print(f"[*] Deneniyor: {base_url} ...")
            
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                server_time = data['serverTime']
                diff = server_time - timestamp
                
                print(f"[+] Bağlantı Başarılı! Sunucu-Cihaz zaman farkı: {diff} ms")
                if abs(diff) > 1000:
                    print("[!] UYARI: Zaman farkı hala 1000ms'den büyük. İşletim sistemi saatini kontrol et.")
                return True
                
        except urllib.error.URLError as e:
            print(f"[-] Bağlantı Koptu ({base_url}): {e.reason}")
        except Exception as e:
            print(f"[-] Hata: {str(e)}")
            
    print("[!] Tüm uç noktalar reddedildi. IP ban yemiş olabilirsin, modemi yeniden başlat veya VPN kapat.")
    return False

if __name__ == "__main__":
    safe_api_request()
PYEOF

echo "[*] İşlem tamamlandı. Test betiği çalıştırılıyor..."
python omega_api_patch.py
