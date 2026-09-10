#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

if [ -f .env ]; then
    set -a
    . .env
    set +a
fi

[
    "${LIVE_ARMED:-0}"
    = "1"
] || {
    echo "LIVE_ARMED=1 required"
    exit 41
}

export HONEYCOMB_MODE=LIVE

bash scripts/start_control_plane.sh

LAUNCHER=""

for file in \
    run_nexus_live.sh \
    engine_live.py \
    engine_live2.py
do

    if [ -f "$file" ]; then

        LAUNCHER="$file"
        break

    fi

done

[
    -n "$LAUNCHER"
] || {
    echo "LIVE_LAUNCHER=NOT_FOUND"
    exit 42
}

echo \
"LIVE_LAUNCHER=$LAUNCHER"

case "$LAUNCHER" in

    *.py)

        nohup python \
            "$LAUNCHER" \
            >> logs/live_launcher.log 2>&1 &

        ;;

    *.sh)

        nohup bash \
            "$LAUNCHER" \
            >> logs/live_launcher.log 2>&1 &

        ;;

esac

echo $! \
    > runtime/live_launcher.pid

echo \
"DASHBOARD=http://127.0.0.1:8787"
