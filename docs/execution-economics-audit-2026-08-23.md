# Honeycomb Execution Economics Audit — 2026-08-23

## Executive result

The observed testnet losses are dominated by an execution-cost unit defect. The runtime treated `FEE_RATE=0.04` as a decimal rate, producing a 4% commission per side instead of the intended 0.04% / 4 bps class of fee. A 200 USDT notional therefore showed about 8 USDT opening fee and about 8 USDT closing fee.

The correction is to make all fee inputs explicit in basis points and derive the legacy decimal only at the compatibility boundary.

## Current engine inventory

The repository currently contains multiple execution cores, including:

- `engine.py`
- `engine_alpha.py`
- `engine_alpha2.py`
- `engine_live.py`
- `engine_live2.py`
- `engine_scalp_tn.py`
- `engine_testnet.py`
- `BinanceFuturesEngineCatE.ts`
- `CatEofUsdcFuturesEngine.ts`
- `HelixSovereignEngine.ts`
- `nexus_futures_engine.ts`
- Go order/risk/edge components under `internal/`
- orchestrator, brain, verify and control-plane components

The control plane dynamically inventories source files, so the list must be treated as a runtime inventory rather than a hand-maintained static registry.

## Production blockers found

1. Ambiguous fee units (`FEE_RATE`).
2. Hardcoded or inconsistent leverage defaults across engines.
3. Fixed notional assumptions instead of risk-based sizing in some engines.
4. TP/SL formulas that embed fee assumptions instead of consuming a common cost model.
5. Runtime timestamp synchronization still needs to be proven end-to-end on the exact process being launched.
6. TypeScript full-project compilation has previously hit the Node heap limit.
7. The Go `internal/order.Router` previously accepted LIVE mode while only logging a local stub; it is now explicitly blocked until a real exchange adapter is wired.
8. Any mock/simulated execution path must be excluded from LIVE routing.

## Canonical economics contract

- `MAKER_FEE_BPS`
- `TAKER_FEE_BPS`
- `SLIPPAGE_BPS`
- `SPREAD_BPS`
- `FUNDING_BUFFER_BPS`
- `OTHER_COST_BPS`
- `RISK_PER_TRADE_PCT`
- `MAX_DAILY_LOSS_PCT`
- `ADVERSE_BUFFER_PCT`

All strategy decisions should consume expected net edge after these costs.

## Recommended live-canary envelope for 1000 TL

Using 48.04 TL/USDT only as a scenario conversion:

- capital ≈ 20.816 USDT
- risk/trade = 0.75%
- TP = 0.80%
- SL = 0.80%
- estimated mixed maker/taker cost = 0.095%
- adverse buffer = 0.10%
- risk-based notional ≈ 15.69 USDT
- 20x margin ≈ 0.785 USDT

This is a scenario model, not a performance guarantee.

## Break-even mathematics

For TP=0.50%, SL=0.90% and 0.095% round-trip cost:

`p_break_even = (SL + cost) / ((TP - cost) + (SL + cost)) ≈ 71.07%`

For TP=0.80%, SL=0.80% and the same cost:

`p_break_even ≈ 55.94%`

Therefore the existing 0.50/0.90 timeout configuration is economically demanding unless its signal quality is extremely high. The new strategy layer should select TP/SL from volatility/regime while enforcing positive expected net edge.

## Validation policy

No LIVE order is considered production-ready until:

1. all fee units are canonical;
2. actual account commission is reconciled against fills;
3. expected net edge is positive after cost buffers;
4. exchange time offset is within the configured tolerance;
5. quantity/price/notional filters come from live `exchangeInfo`;
6. order ACK, fill, position state and journal reconcile;
7. kill switch/circuit breaker tests pass;
8. no mock/simulated execution path is reachable from LIVE;
9. the live preflight passes;
10. a canary order is deliberately small and independently reconciled.
