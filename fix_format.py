import os

dosya_yolu = "/data/data/com.termux/files/home/honeycomb-execution-core/extreme_scanner_engine.py"

with open(dosya_yolu, "r", encoding="utf-8") as f:
    icerik = f.read()

# Hatalı olan eski string formatı
eski_kod = 'format="%(asctime)s [%(levelname)s] [OMEGA:%s] %(message)s" % ACCOUNT_LABEL'

# Değişkeni doğrudan içeri alan yeni f-string formatı
yeni_kod = 'format=f"%(asctime)s [%(levelname)s] [OMEGA:{ACCOUNT_LABEL}] %(message)s"'

if eski_kod in icerik:
    yeni_icerik = icerik.replace(eski_kod, yeni_kod)
    with open(dosya_yolu, "w", encoding="utf-8") as f:
        f.write(yeni_icerik)
    print("Başarılı: Format hatası düzeltildi! Motoru yeniden başlatabilirsin.")
else:
    print("Uyarı: Hatalı satır bulunamadı. Zaten düzeltilmiş olabilir veya kodda boşluk farklılığı var.")
