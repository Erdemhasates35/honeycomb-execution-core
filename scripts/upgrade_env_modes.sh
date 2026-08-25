#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
[[ -f "${ENV_FILE}" ]] || { printf '%s\n' "ERROR: .env not found: ${ENV_FILE}" >&2; exit 1; }

stamp="$(date +%Y%m%d_%H%M%S)"
cp -p "${ENV_FILE}" "${ENV_FILE}.backup.${stamp}"

ensure_key() {
  local key="$1" value="$2"
  if ! grep -qE "^[[:space:]]*${key}=" "${ENV_FILE}"; then
    printf '\n%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
    printf '[ADD] %s\n' "${key}"
  else
    printf '[KEEP] %s\n' "${key}"
  fi
}

ensure_key EXECUTION_MODE TEST
ensure_key FUTURES_MARKET COIN_M
ensure_key LIVE_ARMED 0
ensure_key PAPER_INITIAL_BALANCE 100000
ensure_key PAPER_FEE_RATE 0.0004
ensure_key PAPER_SLIPPAGE_BPS 1
ensure_key TEST_INITIAL_BALANCE 100000
ensure_key TEST_DEFAULT_PRICE 1
ensure_key BINANCE_API_SECRET ""
ensure_key BINANCE_RECV_WINDOW 5000
ensure_key BINANCE_MAX_RETRIES 5
ensure_key BINANCE_COIN_WSS_URL wss://dstream.binance.com/ws
ensure_key BINANCE_TESTNET_WSS_URL wss://stream.binancefuture.com/ws
ensure_key BINANCE_COIN_TESTNET_WSS_URL wss://dstream.binancefuture.com/ws

printf '\nENV UPGRADE COMPLETE\nFILE=%s\nBACKUP=%s\nMODE=%s\nMARKET=%s\n' "${ENV_FILE}" "${ENV_FILE}.backup.${stamp}" "$(grep -E '^EXECUTION_MODE=' "${ENV_FILE}" | tail -1 | cut -d= -f2-)" "$(grep -E '^FUTURES_MARKET=' "${ENV_FILE}" | tail -1 | cut -d= -f2-)"
