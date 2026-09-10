#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

mkdir -p runtime logs

if [
    -f runtime/control_plane.pid
] && kill -0 "$(
    cat runtime/control_plane.pid
)" 2>/dev/null; then

    echo "CONTROL_PLANE=ALREADY_RUNNING"

else

    nohup python \
        orchestrator/control_plane.py \
        >> logs/control_plane.log 2>&1 &

    echo $! \
        > runtime/control_plane.pid

    sleep 1

fi

echo \
"LOCAL_URL=http://127.0.0.1:8787"

if command -v termux-open-url >/dev/null 2>&1; then
    termux-open-url \
        "http://127.0.0.1:8787" || true
fi
