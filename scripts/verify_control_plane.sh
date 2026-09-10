#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

echo "=== HONEYCOMB CONTROL PLANE VERIFY ==="

python -m py_compile \
    orchestrator/control_plane.py \
    scripts/testnet_auth_probe.py

echo "PYTHON=PASS"

if command -v node >/dev/null 2>&1; then

    while IFS= read -r -d '' file; do

        node --check "$file" >/dev/null

    done < <(
        find . \
        -type f \
        \( \
        -name '*.js' \
        -o -name '*.mjs' \
        -o -name '*.cjs' \
        \) \
        -not -path './node_modules/*' \
        -not -path './.git/*' \
        -print0
    )

    echo "NODE=PASS"

fi

if [ -x "./node_modules/.bin/tsc" ]; then

    ./node_modules/.bin/tsc --noEmit

    echo "TSC=PASS"

fi

git diff --check

echo "GIT_DIFF_CHECK=PASS"

for key in \
BINANCE_TESTNET_API_KEY \
BINANCE_TESTNET_SECRET \
BINANCE_TESTNET_URL
do

    value="${!key:-}"

    if [ -n "$value" ]; then

        echo \
        "$key=SET length=${#value}"

    else

        echo "$key=NOT_SET"

    fi

done

echo \
"DASHBOARD=http://127.0.0.1:8787"
