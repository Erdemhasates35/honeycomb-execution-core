import assert from "node:assert/strict";
import test from "node:test";
import { coordinateStrategyPortfolio } from "../strategies/index.js";
import type { KellyAllocation } from "../strategies/fractional_kelly_allocator.js";
import type { StrategySignal } from "../strategies/types.js";

const kelly: KellyAllocation = {
  rawKellyFraction: 0.1,
  allocatedFraction: 0.05,
  expectedReturn: 0.01,
  variance: 0.1,
  drawdownScale: 1,
};

const risk = {
  equity: 10_000,
  availableBalance: 10_000,
  maxRiskPerTrade: 0.01,
  maxPositionNotional: 5_000,
  maxLeverage: 2,
  maxOpenOrders: 3,
  openOrders: 0,
  minimumNotional: 10,
  minimumNetEdgeBps: 3,
  minimumConsensusRatio: 1.2,
};

const guards = {
  circuitBreakerOpen: false,
  toxicityPause: false,
  reconciliationHealthy: true,
  drawdownBreached: false,
};

function signal(strategyCode: string, side: "LONG" | "SHORT" | "FLAT", confidence = 0.8): StrategySignal {
  return {
    strategyCode,
    side,
    confidence,
    expectedEdgeBps: 15,
    entryPrice: 100,
    stopLossPrice: side === "SHORT" ? 102 : 98,
    takeProfitPrice: side === "SHORT" ? 96 : 104,
    reasonCodes: [],
    metadata: {},
  };
}

test("portfolio coordinator selects cost-adjusted consensus and sizes within stop risk", () => {
  const result = coordinateStrategyPortfolio({
    candidates: [
      { signal: signal("basis_funding_velocity", "LONG", 0.8), grossEdgeBps: 15, estimatedRoundTripCostBps: 5 },
      { signal: signal("atr_volatility", "LONG", 0.7), grossEdgeBps: 12, estimatedRoundTripCostBps: 4 },
      { signal: signal("hawkes_toxic_flow", "SHORT", 0.9), grossEdgeBps: 7, estimatedRoundTripCostBps: 6 },
    ],
    activeStrategyCodes: ["basis_funding_velocity", "atr_volatility", "hawkes_toxic_flow"],
    risk,
    guards,
    kelly,
  });
  assert.equal(result.approved, true);
  assert.equal(result.reasonCode, "cost_adjusted_consensus_approved");
  assert.equal(result.candidate?.side, "LONG");
  assert.deepEqual(result.candidate?.supportingStrategies, ["basis_funding_velocity", "atr_volatility"]);
  assert.ok((result.candidate?.notional ?? Infinity) <= 250);
  assert.ok((result.candidate?.quantity ?? Infinity) <= 2.5);
});

test("portfolio coordinator ignores strategies not enabled in the catalog", () => {
  const result = coordinateStrategyPortfolio({
    candidates: [{ signal: signal("basis_funding_velocity", "LONG"), grossEdgeBps: 50, estimatedRoundTripCostBps: 1 }],
    activeStrategyCodes: [],
    risk,
    guards,
    kelly,
  });
  assert.equal(result.approved, false);
  assert.equal(result.reasonCode, "no_cost_adjusted_strategy_edge");
});

test("portfolio coordinator blocks conflicting directions without consensus", () => {
  const result = coordinateStrategyPortfolio({
    candidates: [
      { signal: signal("basis_funding_velocity", "LONG"), grossEdgeBps: 20, estimatedRoundTripCostBps: 2 },
      { signal: signal("atr_volatility", "SHORT"), grossEdgeBps: 18, estimatedRoundTripCostBps: 2 },
    ],
    activeStrategyCodes: ["basis_funding_velocity", "atr_volatility"],
    risk,
    guards,
    kelly,
  });
  assert.equal(result.approved, false);
  assert.equal(result.reasonCode, "strategy_direction_conflict");
});

test("portfolio coordinator fails closed on toxicity and reconciliation faults", () => {
  const candidates = [{ signal: signal("basis_funding_velocity", "LONG"), grossEdgeBps: 20, estimatedRoundTripCostBps: 2 }];
  const toxic = coordinateStrategyPortfolio({
    candidates,
    activeStrategyCodes: ["basis_funding_velocity"],
    risk,
    guards: { ...guards, toxicityPause: true },
    kelly,
  });
  const unreconciled = coordinateStrategyPortfolio({
    candidates,
    activeStrategyCodes: ["basis_funding_velocity"],
    risk,
    guards: { ...guards, reconciliationHealthy: false },
    kelly,
  });
  assert.equal(toxic.reasonCode, "toxic_order_flow_pause");
  assert.equal(unreconciled.reasonCode, "execution_reconciliation_unhealthy");
});

test("portfolio coordinator caps open orders and drawdown before candidate creation", () => {
  const candidates = [{ signal: signal("basis_funding_velocity", "LONG"), grossEdgeBps: 20, estimatedRoundTripCostBps: 2 }];
  const openLimit = coordinateStrategyPortfolio({
    candidates,
    activeStrategyCodes: ["basis_funding_velocity"],
    risk: { ...risk, openOrders: 3 },
    guards,
    kelly,
  });
  const drawdown = coordinateStrategyPortfolio({
    candidates,
    activeStrategyCodes: ["basis_funding_velocity"],
    risk,
    guards: { ...guards, drawdownBreached: true },
    kelly,
  });
  assert.equal(openLimit.reasonCode, "open_order_limit_reached");
  assert.equal(drawdown.reasonCode, "portfolio_drawdown_limit_reached");
});
