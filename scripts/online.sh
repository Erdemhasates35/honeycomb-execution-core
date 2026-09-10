#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

bash scripts/start_control_plane.sh

if command -v cloudflared >/dev/null 2>&1; then

    echo "PUBLIC_TUNNEL=STARTING"

    nohup cloudflared \
        tunnel \
        --url http://127.0.0.1:8787 \
        --no-autoupdate \
        > runtime/cloudflared.log 2>&1 &

    echo $! \
        > runtime/cloudflared.pid

    sleep 3

    grep -Eo \
        'https://[-a-zA-Z0-9]+\.trycloudflare\.com' \
        runtime/cloudflared.log \
        | tail -1 || true

else

    echo "CLOUDFLARED=NOT_INSTALLED"

fi

if command -v npx >/dev/null 2>&1; then

    echo \
    "VERCEL_PROJECT_DIR=$ROOT/dashboard"

    echo \
    "VERCEL_DEPLOY=npx vercel --prod"

fi
