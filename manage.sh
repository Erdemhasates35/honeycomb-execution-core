#!/data/data/com.termux/files/usr/bin/bash
# ANA DİZİNDEN TEK KOMUTLA 10 HESABI YÖNET.
# Kullanım:
#   bash manage.sh start          -> 10 hesabı da başlatır
#   bash manage.sh stop           -> 10 hesabı da durdurur
#   bash manage.sh restart        -> durdur + başlat
#   bash manage.sh status         -> hangisi çalışıyor, hangi portta
#   bash manage.sh logs USDT-1    -> o hesabın canlı logunu izler (Ctrl+C ile çık)
#   bash manage.sh check          -> her hesabın OPENROUTER_API_KEY dolu mu, tek tek gösterir
set -e
cd "$(dirname "$0")"

if [ ! -d "accounts" ]; then
    echo "HATA: accounts/ klasörü yok. Önce setup_multi_account.sh çalıştırılmış olmalı."
    exit 1
fi

CMD="${1:-}"

case "$CMD" in
    start)
        bash accounts/start_all.sh
        ;;
    stop)
        bash accounts/stop_all.sh
        ;;
    restart)
        bash accounts/stop_all.sh
        sleep 2
        bash accounts/start_all.sh
        ;;
    status)
        bash accounts/status_all.sh
        ;;
    logs)
        ACC="${2:-}"
        if [ -z "$ACC" ]; then
            echo "Kullanım: bash manage.sh logs USDT-1   (veya COIN-3 gibi)"
            exit 1
        fi
        tail -f "accounts/logs/$ACC.log"
        ;;
    check)
        echo "=== OPENROUTER_API_KEY / BINANCE_API_KEY kontrolü (her hesap) ==="
        for d in accounts/USDT-1 accounts/USDT-2 accounts/USDT-3 accounts/USDT-4 accounts/USDT-5 \
                 accounts/COIN-1 accounts/COIN-2 accounts/COIN-3 accounts/COIN-4 accounts/COIN-5; do
            NAME=$(basename "$d")
            KEY=$(grep "^OPENROUTER_API_KEY=" "$d/.env" 2>/dev/null | cut -d= -f2)
            BINKEY=$(grep "^BINANCE_API_KEY=" "$d/.env" 2>/dev/null | cut -d= -f2)
            ARMED=$(grep "^LIVE_ARMED=" "$d/.env" 2>/dev/null | cut -d= -f2)
            if [ -z "$KEY" ] || [[ "$KEY" == BURAYA_* ]]; then
                AI_STATUS="BOŞ (AI hiç oy veremez!)"
            else
                AI_STATUS="dolu"
            fi
            if [ -z "$BINKEY" ] || [[ "$BINKEY" == BURAYA_* ]]; then
                BIN_STATUS="BOŞ"
            else
                BIN_STATUS="dolu"
            fi
            echo "[$NAME] OPENROUTER=$AI_STATUS | BINANCE=$BIN_STATUS | LIVE_ARMED=$ARMED"
        done
        ;;
    *)
        echo "Kullanım: bash manage.sh {start|stop|restart|status|logs <HESAP>|check}"
        echo ""
        echo "Örnek: bash manage.sh check       -> hangi hesapta API anahtarı eksik, hemen görürsün"
        echo "Örnek: bash manage.sh start       -> 10 hesabı da başlatır"
        echo "Örnek: bash manage.sh logs USDT-1 -> o hesabı canlı izle"
        exit 1
        ;;
esac
