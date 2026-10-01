# Core Hardening (partial)

## Added
- core/mode_guard.py
- core/portfolio_risk.py
- core/execution_gateway.py
- tests/test_risk_and_mode.py

## Limits
- MAX_LEVERAGE <= 50 (startup fail if >50)
- LIVE_MAX_CAPITAL_PERCENT default 10
- LIVE refuses testnet URL, AUTO_PAPER, missing credentials

## Tests
11/11 unit tests PASS locally.

## Certification
LIVE CERTIFICATION = FAIL until all engines route through ExecutionGateway and CI is green.
