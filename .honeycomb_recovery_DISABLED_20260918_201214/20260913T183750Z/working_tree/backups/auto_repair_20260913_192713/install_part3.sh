#!/data/data/com.termux/files/usr/bin/bash
# ÇOKLU HESAP KURULUMU — 5 USDT-M + 5 COIN-M, TAMAMEN İZOLE PROCESS'LER.
# install_part1.sh + install_part2.sh'dan SONRA, ana dizinde bir kez çalıştırın.
#
# MİMARİ TERCİHİ (bilerek): her hesap kendi ayrı klasöründe, kendi ayrı
# python process'inde çalışır. Tek process içinde paylaşılan durum
# YERİNE bunu seçtim çünkü: (1) zaten çalışan ve test edilmiş kodu
# tekrar riske atmadan aynen kullanır, (2) bir hesapta çıkan hata/çökme
# diğer 9 hesabı ETKİLEMEZ, (3) her hesabın DB/log/panel'i doğal olarak
# ayrı — karışma riski sıfır.
set -e

SRC_DIR="$(pwd)"
for f in live/kernel.py live/__init__.py alpha_core.py ai_parliament.py sovereign_parliament_engine.py; do
    if [ ! -f "$f" ]; then
        echo "HATA: $f bulunamadı. Önce install_part1.sh ve install_part2.sh çalıştırılmış olmalı."
        exit 1
    fi
done

mkdir -p accounts
PORT=8101
declare -a LABELS=("USDT-1" "USDT-2" "USDT-3" "USDT-4" "USDT-5" "COIN-1" "COIN-2" "COIN-3" "COIN-4" "COIN-5")
declare -a VENUES=("usdt" "usdt" "usdt" "usdt" "usdt" "coin" "coin" "coin" "coin" "coin")

for i in "${!LABELS[@]}"; do
    LABEL="${LABELS[$i]}"
    VENUE="${VENUES[$i]}"
    DIR="accounts/$LABEL"
    mkdir -p "$DIR/live"
    cp live/kernel.py live/__init__.py "$DIR/live/"
    cp alpha_core.py ai_parliament.py sovereign_parliament_engine.py "$DIR/"

    if [ ! -f "$DIR/.env" ]; then
        cat > "$DIR/.env" << ENVEOF
# ===== $LABEL ($VENUE) — GERÇEK BİLGİLERİNİZİ DOLDURUN =====
ACCOUNT_LABEL=$LABEL
VENUE=$VENUE
BINANCE_API_KEY=BURAYA_${LABEL}_API_KEY
BINANCE_API_SECRET=BURAYA_${LABEL}_API_SECRET

EXECUTION_MODE=LIVE
LIVE_ARMED=0
HONEYCOMB_BRIDGE_PORT=$PORT

LIVE_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT
MAX_POSITIONS=3
LEV_MIN=25
MAX_LEVERAGE=75
LIVE_RISK=0.05
MAX_POSITION_SIZE_USDT=200
FEE_RATE=0.0004
TECH_WEIGHT=0.45
AI_WEIGHT=0.55
MIN_FINAL_CONF=60
DEFENSE_ENABLED=1
DEFENSE_COOLDOWN_SEC=600
SCALP_MODE=0

OPENROUTER_API_KEY=
GOOGLE_API_KEY=
XAI_API_KEY=
ANTHROPIC_API_KEY=
ENVEOF
        echo "[$LABEL] .env oluşturuldu (port $PORT) — API anahtarlarını doldurmadan LIVE_ARMED=1 yapmayın."
    else
        echo "[$LABEL] .env zaten var, dokunulmadı."
    fi
    PORT=$((PORT + 1))
done

cat > accounts/start_all.sh << 'STARTEOF'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
mkdir -p logs pids
for d in USDT-1 USDT-2 USDT-3 USDT-4 USDT-5 COIN-1 COIN-2 COIN-3 COIN-4 COIN-5; do
    if [ -f "pids/$d.pid" ] && kill -0 "$(cat pids/$d.pid)" 2>/dev/null; then
        echo "[$d] zaten çalışıyor (pid $(cat pids/$d.pid))"
        continue
    fi
    (cd "$d" && nohup python3 sovereign_parliament_engine.py > "../logs/$d.log" 2>&1 & echo $! > "../pids/$d.pid")
    echo "[$d] başlatıldı (pid $(cat pids/$d.pid)) — log: accounts/logs/$d.log"
done
STARTEOF

cat > accounts/stop_all.sh << 'STOPEOF'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
for d in USDT-1 USDT-2 USDT-3 USDT-4 USDT-5 COIN-1 COIN-2 COIN-3 COIN-4 COIN-5; do
    if [ -f "pids/$d.pid" ]; then
        PID=$(cat "pids/$d.pid")
        if kill "$PID" 2>/dev/null; then
            echo "[$d] durduruldu (pid $PID)"
        fi
        rm -f "pids/$d.pid"
    fi
done
STOPEOF

cat > accounts/status_all.sh << 'STATUSEOF'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
PORT=8101
for d in USDT-1 USDT-2 USDT-3 USDT-4 USDT-5 COIN-1 COIN-2 COIN-3 COIN-4 COIN-5; do
    RUNNING="KAPALI"
    if [ -f "pids/$d.pid" ] && kill -0 "$(cat pids/$d.pid)" 2>/dev/null; then RUNNING="ÇALIŞIYOR"; fi
    echo "[$d] $RUNNING  panel: http://127.0.0.1:$PORT/"
    PORT=$((PORT + 1))
done
STATUSEOF

chmod +x accounts/start_all.sh accounts/stop_all.sh accounts/status_all.sh
echo ""
echo "TAMAM. Sıradaki adımlar:"
echo "  1) accounts/USDT-1/.env ... accounts/COIN-5/.env dosyalarına GERÇEK API anahtarlarınızı girin"
echo "  2) bash accounts/start_all.sh     (10 hesabı da başlatır, her biri kendi portunda: 8101-8110)"
echo "  3) bash accounts/status_all.sh    (hangisi çalışıyor, hangi panelde)"
echo "  4) bash accounts/stop_all.sh      (hepsini durdurur)"
echo "NOT: Her .env'de LIVE_ARMED=0 olarak geldi. Bir hesabı gerçekten canlıya almak için"
echo "     o hesabın panelinden (Kontrol Paneli) veya .env'den LIVE_ARMED=1 yapmanız gerekir —"
echo "     hiçbiri sizin onayınız olmadan gerçek emir göndermez."
