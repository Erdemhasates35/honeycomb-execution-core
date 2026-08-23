#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail(){ echo "LIVE PREFLIGHT FAIL: $*" >&2; exit 1; }
pass(){ echo "LIVE PREFLIGHT OK: $*"; }

[ -f .env ] || fail ".env missing"
set -a
. ./.env
set +a

[[ "${EXECUTION_MODE:-}" == "live" ]] || fail "EXECUTION_MODE must be live"
[[ "${LIVE_ARMED:-0}" == "1" ]] || fail "LIVE_ARMED=1 required"
[[ "${BINANCE_BASE_URL:-}" == "https://fapi.binance.com" ]] || fail "BINANCE_BASE_URL must be production USD-M endpoint"
[[ -n "${BINANCE_API_KEY:-}" && -n "${BINANCE_SECRET:-}" ]] || fail "production Binance credentials not set"

python - <<'PY'
import os
from decimal import Decimal

def d(k, default=None):
    v=os.getenv(k, default)
    return Decimal(v) if v is not None else None

maker=d('MAKER_FEE_BPS'); taker=d('TAKER_FEE_BPS')
if maker is None or taker is None or maker < 0 or taker < 0 or maker > 100 or taker > 100:
    raise SystemExit('invalid MAKER_FEE_BPS/TAKER_FEE_BPS')
if os.getenv('FEE_RATE'):
    legacy=d('FEE_RATE')
    if legacy >= 1:
        raise SystemExit('ambiguous legacy FEE_RATE >= 1')
risk=d('RISK_PER_TRADE_PCT','0.75')
daily=d('MAX_DAILY_LOSS_PCT','3.0')
lev=d('MAX_LEVERAGE','20')
if risk > Decimal('0.75'):
    raise SystemExit('RISK_PER_TRADE_PCT exceeds live canary ceiling 0.75')
if daily > Decimal('3.0'):
    raise SystemExit('MAX_DAILY_LOSS_PCT exceeds live canary ceiling 3.0')
if lev > Decimal('20'):
    raise SystemExit('MAX_LEVERAGE exceeds live canary ceiling 20x')
print('economics: maker_bps=',maker,'taker_bps=',taker,'risk_pct=',risk,'daily_loss_pct=',daily,'max_leverage=',lev)
PY

python -m py_compile execution_economics.py config.py engine.py engine_alpha.py engine_alpha2.py engine_live.py engine_live2.py engine_scalp_tn.py engine_testnet.py nexus_testnet_bridge.py orchestrator/control_plane.py orchestrator/quality_gate.py scripts/audit_execution_economics.py scripts/returns_projection.py
python -m pytest -q tests/test_execution_economics.py tests/test_quality_gate.py

echo "LIVE PREFLIGHT PASS: code/config gate passed. This script intentionally does not submit an order."
