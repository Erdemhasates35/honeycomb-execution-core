#!/data/data/com.termux/files/usr/bin/bash
# Canonical Honeycomb TESTNET runtime entrypoint.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"
exec bash runtime/start_testnet.sh
