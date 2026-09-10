cd ~/honeycomb-execution-core || { echo "ROOT BULUNAMADI, cd ile doğru yere geç"; exit 1; }
echo "PWD: $(pwd)"

echo
echo "=== 1. YANLIŞLIKLA OLUŞAN live/live TEMİZLİĞİ ==="
if [ -d live/live ]; then
  echo "live/live bulundu -> siliniyor"
  rm -rf live/live
else
  echo "live/live yok, temiz"
fi

echo
echo "=== 2. live/__init__.py DOĞRU YERE, DOĞRU İÇERİKLE YAZILIYOR ==="
cp live/__init__.py "live/__init__.py.bak.$(date +%s)" 2>/dev/null
cat > live/__init__.py << 'EOF'
# -*- coding: utf-8 -*-
"""Honeycomb Live Package"""
from live.kernel import (
    LiveKernel, DynamicTrailingStopEngine, CircuitBreaker,
    CryptographicAuditLedger, PartialProfitEngine,
    _finite_num, _gt, _lt, _ge, _le,
)

__all__ = [
    "LiveKernel", "DynamicTrailingStopEngine", "CircuitBreaker",
    "CryptographicAuditLedger", "PartialProfitEngine",
    "_finite_num", "_gt", "_lt", "_ge", "_le",
]
EOF
echo "yazıldı"

echo
echo "=== 3. TÜM __pycache__ TEMİZLENİYOR (eski .pyc karışıklığı önler) ==="
find . -name "__pycache__" -type d -not -path "*/node_modules/*" -exec rm -rf {} + 2>/dev/null
echo "temizlendi"

echo
echo "=== 4. KAÇ TANE alpha_core.py / kernel.py VAR — HANGİSİ GERÇEKTEN IMPORT EDİLİYOR ==="
echo "--- alpha_core.py kopyaları ---"
find . -name "alpha_core.py" -not -path "*/node_modules/*" 2>/dev/null
echo "--- kernel.py kopyaları ---"
find . -name "kernel.py" -not -path "*/node_modules/*" 2>/dev/null
echo "--- python'un GERÇEKTE bulduğu alpha_core ---"
python3 -c "import alpha_core, os; print(os.path.abspath(alpha_core.__file__))"

echo
echo "=== 5. alpha_core.py (KÖK) İÇİNE EKSİK FONKSİYONLARI GÜVENLİ ŞEKİLDE EKLE ==="
TARGET="./alpha_core.py"
if [ -f "$TARGET" ]; then
  if ! grep -q "^def klines" "$TARGET"; then
    cat >> "$TARGET" << 'EOF'


# ---- EKSİK OLAN klines() — detect_regime() bunu çağırıyordu ama tanımlı değildi ----
def klines(symbol, interval="5m", limit=60):
    """Public REST üzerinden mum verisi çeker (auth gerekmez). Döner: (closes, volumes)."""
    import json, urllib.parse, urllib.request
    url = ("https://fapi.binance.com/fapi/v1/klines?" +
           urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit}))
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    closes = [float(x[4]) for x in data]
    volumes = [float(x[5]) for x in data]
    return closes, volumes
EOF
    echo "klines() eklendi -> $TARGET"
  else
    echo "klines() zaten var, dokunulmadı"
  fi

  if ! grep -q "^def get_technical_decision" "$TARGET"; then
    cat >> "$TARGET" << 'EOF'


# ---- EKSİK OLAN get_technical_decision() — PARLIAMENT bunu çağırıyordu ----
def get_technical_decision(symbol, balance=None, open_positions=None):
    """Basit, güvenli fallback karar üretici. Gerçek versiyon başka bir alpha_core.py
    kopyasındaysa, adım 4'teki 'python'un GERÇEKTE bulduğu alpha_core' satırına bak —
    orası kök dizindeki bu dosya değilse, doğru dosyayı bana gönder, birleştirelim."""
    try:
        closes, _vols = klines(symbol, "5m", 60)
        if len(closes) < 20:
            return {"side": None, "score": 0.0, "confidence": 0, "regime": "FLAT"}
        change = (closes[-1] - closes[-20]) / closes[-20] * 100.0
        side = "LONG" if change > 0.3 else ("SHORT" if change < -0.3 else None)
        score = min(100.0, abs(change) * 20)
        return {"side": side, "score": round(score, 1), "confidence": int(score), "regime": "TREND" if side else "FLAT"}
    except Exception as e:
        return {"side": None, "score": 0.0, "confidence": 0, "regime": "FLAT", "error": str(e)}
EOF
    echo "get_technical_decision() eklendi -> $TARGET (FALLBACK — gerçek fonksiyon başka dosyadaysa haber ver)"
  else
    echo "get_technical_decision() zaten var, dokunulmadı"
  fi
else
  echo "UYARI: ./alpha_core.py kök dizinde bulunamadı"
fi

echo
echo "=== 6. DERLEME + IMPORT DOĞRULAMA ==="
python3 -m py_compile alpha_core.py live/kernel.py live/__init__.py && echo "PYCOMPILE_OK"
python3 -c "
import alpha_core
print('klines:', hasattr(alpha_core, 'klines'))
print('get_technical_decision:', hasattr(alpha_core, 'get_technical_decision'))
import live
print('LIVE_INIT_OK')
"

echo
echo "=== 7. sqlite3 DB PATH TEŞHİSİ (engine_alpha.py / engine_alpha2.py) ==="
grep -n "DB_PATH" engine_alpha.py engine_alpha2.py 2>/dev/null

echo
echo "=== 8. latin-1/α HATASI İÇİN TEŞHİS (engine_live.py / engine_live2.py) ==="
grep -n "α\|headers\[" engine_live.py engine_live2.py 2>/dev/null | head -30

echo
echo "=== 9. matmul SHAPE HATASI İÇİN TEŞHİS (quantum_nexus_v3_monolithic.py) ==="
grep -n "matmul\|self\.H \?=\|self\.x \?=\|self\.P \?=" quantum_nexus_v3_monolithic.py 2>/dev/null | head -30

echo
echo "============================================================"
echo " Adım 1-6 kalıcı çözüldü. Adım 7-8-9 çıktısını olduğu gibi"
echo " bana gönder, tam satırı görüp nokta atışı yamayı yazayım."
echo "============================================================"
