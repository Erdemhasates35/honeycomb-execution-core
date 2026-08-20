#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0
if ! grep -q '^EXECUTION_MODE=live' .env 2>/dev/null; then echo 'FAIL: EXECUTION_MODE=live is required'; fail=1; fi
if grep -qiE 'testnet|paper|mock|simulation|fake|dummy|fallback.?price' internal cmd --exclude='*_test.go' 2>/dev/null; then echo 'FAIL: simulation/testnet/mock/fallback execution token detected in live path'; fail=1; fi
if ! grep -q 'newClientOrderId' internal/exchange/binance.go; then echo 'FAIL: Binance idempotency key missing'; fail=1; fi
if ! grep -q 'MAX_CAPITAL_USDT' internal/config/config.go; then echo 'FAIL: capital cap missing'; fail=1; fi
if ! grep -q 'TradeCapitalPercent' internal/order/router.go internal/config/config.go; then echo 'FAIL: 10% capital cap wiring missing'; fail=1; fi
if ! grep -q 'Mode == "live"' internal/order/router.go; then echo 'FAIL: live execution branch missing'; fail=1; fi

go test ./...
if [ "$fail" -ne 0 ]; then exit 1; fi
echo 'LIVE GATE PASS'
