#!/usr/bin/env bash
# Gated real Binance USD-M launcher for the Alpha2 engine.
# It does not start unless live_preflight passes.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

bash scripts/live_preflight.sh

set -a
. ./.env
set +a

# Translate the portfolio risk budget into Alpha2's legacy LIVE_RISK semantics.
# Alpha2 interprets LIVE_RISK as a fraction of equity allocated to margin,
# while the canonical model defines RISK_PER_TRADE_PCT as loss-at-stop budget.
python - <<'PY' > runtime/live_economics.env
import os
from decimal import Decimal as D
risk = D(os.getenv('RISK_PER_TRADE_PCT','0.75'))
sl = D(os.getenv('SL_P_BASE', os.getenv('SL_P','0.80')))
taker = D(os.getenv('TAKER_FEE_BPS','5'))
slippage = D(os.getenv('SLIPPAGE_BPS','1'))
spread = D(os.getenv('SPREAD_BPS','0.5'))
funding = D(os.getenv('FUNDING_BUFFER_BPS','1'))
buffer = D(os.getenv('ADVERSE_BUFFER_PCT','0.10'))
lev = D(os.getenv('MAX_LEVERAGE','20'))
# Legacy engine charges one FEE on open and one on close. Fold half of the
# non-fee execution buffer into each side so the legacy accounting remains conservative.
per_side_bps = taker + (slippage + spread + funding) / D('2')
fee_rate = per_side_bps / D('10000')
effective = sl + (D('2') * per_side_bps / D('100')) + buffer
margin_fraction = (risk / effective) / lev
print(f'LIVE_RISK={margin_fraction:.10f}')
print(f'FEE_RATE={fee_rate:.10f}')
print(f'TAKER_FEE_BPS={taker}')
print(f'MAKER_FEE_BPS={os.getenv("MAKER_FEE_BPS","2")}')
print(f'MAX_LEVERAGE={lev}')
print(f'MAX_POSITION_SIZE_USDT={os.getenv("MAX_POSITION_SIZE_USDT","20")}')
PY

set -a
. ./runtime/live_economics.env
set +a

export EXECUTION_MODE=live
export HONEYCOMB_MODE=LIVE
export LIVE_ARMED=1
export LIVE_CONFIRM=true
export BINANCE_BASE_URL=https://fapi.binance.com
export BINANCE_FUTURES_URL=https://fapi.binance.com
export MAX_LEVERAGE="${MAX_LEVERAGE:-20}"
export MAX_POSITION_SIZE_USDT="${MAX_POSITION_SIZE_USDT:-20}"

printf 'LIVE ALPHA2 READY | risk-margin=%s | fee/side=%s | leverage=%sx | max-notional=%s\n' "$LIVE_RISK" "$FEE_RATE" "$MAX_LEVERAGE" "$MAX_POSITION_SIZE_USDT"
exec python engine_alpha2.py
