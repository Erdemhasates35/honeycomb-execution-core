#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

if [ -f .env ]; then
    set -a
    . .env
    set +a
fi

export HONEYCOMB_MODE=TESTNET

bash scripts/start_control_plane.sh

LAUNCHER=""

for file in \
    run_nexus_testnet.sh \
    run_testnet.sh \
    fix_testnet_stack.sh
do

    if [
        -x "$file"
    ] || [
        -f "$file"
    ]; then

        LAUNCHER="$file"
        break

    fi

done

if [ -n "$LAUNCHER" ]; then

    echo \
    "TESTNET_LAUNCHER=$LAUNCHER"

    nohup bash \
        "$LAUNCHER" \
        >> logs/testnet_launcher.log 2>&1 &

    echo $! \
        > runtime/testnet_launcher.pid

else

    echo \
    "TESTNET_LAUNCHER=NOT_FOUND"

fi

echo \
"DASHBOARD=http://127.0.0.1:8787"
