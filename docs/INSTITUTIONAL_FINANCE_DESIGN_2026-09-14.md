# Honeycomb Institutional Finance Design — 2026-09-14

## Objective
Unify the existing Honeycomb/Quantum Nexus signal, AI-agent, risk, execution, protection and accounting layers around a signed expected-value objective that maximizes net realized return subject to hard exchange, margin, liquidity, drawdown and execution constraints.

## Three-stage architecture

### Stage 1 — Financial mathematics and accounting
1. Signed directional expected move; never use `abs(expected_move)` for a directional decision.
2. Net edge in basis points: expected move minus round-trip commission, spread, slippage, market impact, adverse selection and funding actually crossed during the holding horizon.
3. Funding is settlement-aware: zero cost before the next settlement; count only settlements crossed by expected holding time; negative signed transfer is a credit.
4. Margin budget is distinct from stop-risk. Default margin budget is 5% of available equity; leverage only transforms margin into notional and never increases the equity budget.
5. PnL is recorded in quote currency and as percentage of posted margin. Also record fee, funding, gross/net PnL, MAE, MFE, holding time and implementation shortfall.
6. Dynamic TP/SL/trailing surfaces use ATR, confidence and regime rather than fixed universal percentages.

### Stage 2 — Signal/AI/execution integration
All existing engines keep their public names/interfaces. Their decisions are normalized into a common contract:
`symbol, side, confidence, regime, expected_move_bps, spread_bps, funding_bps, risk_fraction, leverage, tp_pct, sl_pct, source, rationale`.

AI/agent authority is advisory rather than an unconditional order authority. The financial gate remains deterministic and can veto any signal that fails net edge, data quality, exchange limits, portfolio exposure or drawdown constraints.

Execution selection compares maker expected value with taker immediacy. Maker fill probability and adverse selection are explicit; a maker order that does not fill is not counted as a phantom trade.

### Stage 3 — Live reconciliation, observability and verification
1. Reconcile exchange positions/orders at startup and after reconnects.
2. Never infer fills from order submission; fill ledger requires exchange status/fill quantities.
3. Protection is confirmed separately from entry.
4. Restart-safe local state is reconciled with Binance before a new entry.
5. Portfolio metrics are computed from actual fills: net PnL %, profit factor, expectancy, drawdown %, MAE/MFE, fees %, funding and implementation shortfall.
6. `LIVE_ARMED=1` remains a hard gate. No component bypasses the gate.
7. Static checks: merge-marker scan, syntax/type checks, ATR compatibility, missing-value guards, no-secret audit, diff whitespace checks.

## Quantitative objective

`maximize E[NetPnL] - lambda_cost*ExecutionCost - lambda_dd*Drawdown - lambda_tail*TailRisk - lambda_is*ImplementationShortfall`

with hard constraints for:
- exchange leverage and symbol filters;
- 5% default margin budget;
- maximum notional and portfolio concentration;
- minimum positive net edge;
- stale/invalid market data;
- circuit breaker and loss cooldown;
- live execution gate.

## Required indicators and features

Existing indicators remain available and are treated as evidence rather than isolated authorities: EMA(9/21/55), ATR(14), ADX(14), RSI, Bollinger, momentum/returns, volume ratio, MTF agreement, spread and order-book/microstructure features where available.

Each engine must avoid duplicate weighting of correlated indicators. Confidence is a calibrated probability/score input, not a profit guarantee. The central economic gate decides whether an otherwise strong signal has enough expected value after costs.

## AI/agent hierarchy

1. Market-data validity and exchange state.
2. Deterministic risk and financial gate.
3. Quantitative signal consensus.
4. AI/Parliament synthesis for contextual evidence.
5. Execution optimizer.
6. Live kernel.
7. Protection and post-trade accounting.

AI may raise or lower confidence and explain regime/context, but cannot authorize an order that fails the deterministic gate.

## Evidence standard

Every optimization is evaluated by out-of-sample net expectancy, profit factor, net PnL, drawdown, MAE/MFE, fees, funding and implementation shortfall. Win rate alone is insufficient. Academic execution improvements are treated as hypotheses to validate on Honeycomb's own fills, not as guaranteed performance increases.

## Non-destructive policy

No existing production file, database, audit log, environment secret, engine or integration is deleted. Changes are additive or targeted compatibility fixes. Backups remain preserved. New central modules provide compatibility interfaces rather than replacing existing engine names.
