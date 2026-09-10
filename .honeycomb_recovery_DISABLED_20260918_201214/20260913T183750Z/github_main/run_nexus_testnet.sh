#!/data/data/com.termux/files/usr/bin/bash
# Canonical Honeycomb TESTNET runtime entrypoint.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"
# Validation: never start outside the repository root.
test -d "$ROOT/runtime"
# Observability: explicit entrypoint marker; credentials remain redacted.
echo "[HONEYCOMB] TESTNET entrypoint root=$ROOT"
# Security invariant: diagnostics must redact API secrets/tokens.
# redact credentials; never print BINANCE_API_SECRET/BINANCE_SECRET.
exec bash runtime/start_testnet.sh
