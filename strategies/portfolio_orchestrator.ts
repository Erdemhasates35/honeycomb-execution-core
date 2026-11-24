import type { KellyAllocation } from "./fractional_kelly_allocator.js";
import type { StrategySignal } from "./types.js";

export interface CostedStrategySignal {
  signal: StrategySignal;
  grossEdgeBps: number;
  estimatedRoundTripCostBps: number;
}

export interface PortfolioRiskLimits {
  equity: number;
  availableBalance: number;
  maxRiskPerTrade: number;
  maxPositionNotional: number;
  maxLeverage: number;
  maxOpenOrders: number;
  openOrders: number;
  minimumNotional: number;
  minimumNetEdgeBps: number;
  minimumConsensusRatio: number;
}

export interface PortfolioExecutionGuards {
  circuitBreakerOpen: boolean;
  toxicityPause: boolean;
  reconciliationHealthy: boolean;
  drawdownBreached: boolean;
}

export interface PortfolioCandidate {
  strategyCode: string;
  side: "LONG" | "SHORT";
  entryPrice: number;
  stopLossPrice: number;
  takeProfitPrice: number | null;
  quantity: number;
  notional: number;
  confidence: number;
  grossEdgeBps: number;
  estimatedRoundTripCostBps: number;
  netEdgeBps: number;
  supportingStrategies: string[];
}

export interface PortfolioDecision {
  approved: boolean;
  reasonCode: string;
  candidate: PortfolioCandidate | null;
  longScore: number;
  shortScore: number;
}

function finitePositive(value: number, field: string): void {
  if (!Number.isFinite(value) || value <= 0) throw new Error(field + "_must_be_positive");
}

export function coordinateStrategyPortfolio(input: {
  candidates: CostedStrategySignal[];
  activeStrategyCodes: string[];
  risk: PortfolioRiskLimits;
  guards: PortfolioExecutionGuards;
  kelly: KellyAllocation;
}): PortfolioDecision {
  const { risk, guards, kelly } = input;
  for (const [field, value] of Object.entries({
    equity: risk.equity,
    availableBalance: risk.availableBalance,
    maxPositionNotional: risk.maxPositionNotional,
    maxLeverage: risk.maxLeverage,
    minimumNotional: risk.minimumNotional,
  })) finitePositive(value, field);
  if (!Number.isFinite(risk.maxRiskPerTrade) || risk.maxRiskPerTrade <= 0 || risk.maxRiskPerTrade > 1) throw new Error("maxRiskPerTrade_is_invalid");
  if (!Number.isInteger(risk.maxOpenOrders) || risk.maxOpenOrders < 0 || !Number.isInteger(risk.openOrders) || risk.openOrders < 0) throw new Error("openOrderLimits_are_invalid");
  if (!Number.isFinite(risk.minimumNetEdgeBps) || risk.minimumNetEdgeBps < 0) throw new Error("minimumNetEdgeBps_is_invalid");
  if (!Number.isFinite(risk.minimumConsensusRatio) || risk.minimumConsensusRatio < 1) throw new Error("minimumConsensusRatio_is_invalid");
  if (!Number.isFinite(kelly.allocatedFraction) || kelly.allocatedFraction < 0 || kelly.allocatedFraction > 1) throw new Error("kellyAllocation_is_invalid");

  const blocked = (reasonCode: string, longScore = 0, shortScore = 0): PortfolioDecision => ({
    approved: false,
    reasonCode,
    candidate: null,
    longScore,
    shortScore,
  });

  if (guards.circuitBreakerOpen) return blocked("circuit_breaker_open");
  if (guards.toxicityPause) return blocked("toxic_order_flow_pause");
  if (!guards.reconciliationHealthy) return blocked("execution_reconciliation_unhealthy");
  if (guards.drawdownBreached) return blocked("portfolio_drawdown_limit_reached");
  if (risk.openOrders >= risk.maxOpenOrders) return blocked("open_order_limit_reached");
  if (kelly.allocatedFraction <= 0) return blocked("kelly_allocator_zero_risk");

  const active = new Set(input.activeStrategyCodes);
  const eligible = input.candidates.filter(({ signal }) => active.has(signal.strategyCode) && signal.side !== "FLAT");
  const priced = eligible.map((candidate) => {
    const { signal, grossEdgeBps, estimatedRoundTripCostBps } = candidate;
    if (!Number.isFinite(signal.confidence) || signal.confidence < 0 || signal.confidence > 1) throw new Error("strategy_confidence_is_invalid");
    if (!Number.isFinite(grossEdgeBps) || !Number.isFinite(estimatedRoundTripCostBps) || estimatedRoundTripCostBps < 0) throw new Error("strategy_cost_or_edge_is_invalid");
    finitePositive(signal.entryPrice, "strategy_entry_price");
    if (signal.stopLossPrice === null) throw new Error("strategy_stop_loss_required");
    finitePositive(signal.stopLossPrice, "strategy_stop_loss");
    if (signal.side === "LONG" && signal.stopLossPrice >= signal.entryPrice) throw new Error("long_stop_loss_must_be_below_entry");
    if (signal.side === "SHORT" && signal.stopLossPrice <= signal.entryPrice) throw new Error("short_stop_loss_must_be_above_entry");
    if (signal.takeProfitPrice !== null) finitePositive(signal.takeProfitPrice, "strategy_take_profit");
    const netEdgeBps = grossEdgeBps - estimatedRoundTripCostBps;
    return { ...candidate, netEdgeBps, score: Math.max(0, netEdgeBps) * signal.confidence };
  }).filter((candidate) => candidate.netEdgeBps >= risk.minimumNetEdgeBps && candidate.score > 0);

  if (priced.length === 0) return blocked("no_cost_adjusted_strategy_edge");
  const longScore = priced.filter((candidate) => candidate.signal.side === "LONG").reduce((sum, candidate) => sum + candidate.score, 0);
  const shortScore = priced.filter((candidate) => candidate.signal.side === "SHORT").reduce((sum, candidate) => sum + candidate.score, 0);
  if (longScore > 0 && shortScore > 0) {
    const ratio = Math.max(longScore, shortScore) / Math.min(longScore, shortScore);
    if (ratio < risk.minimumConsensusRatio) return blocked("strategy_direction_conflict", longScore, shortScore);
  }

  const side = longScore >= shortScore ? "LONG" : "SHORT";
  const sideCandidates = priced.filter((candidate) => candidate.signal.side === side).sort((a, b) => b.score - a.score);
  const selected = sideCandidates[0];
  if (!selected) return blocked("no_consensus_candidate", longScore, shortScore);

  const stopDistanceFraction = Math.abs(selected.signal.entryPrice - selected.signal.stopLossPrice!) / selected.signal.entryPrice;
  if (!Number.isFinite(stopDistanceFraction) || stopDistanceFraction <= 0 || stopDistanceFraction >= 1) return blocked("invalid_stop_distance", longScore, shortScore);
  const riskBudget = risk.equity * risk.maxRiskPerTrade * kelly.allocatedFraction;
  const notionalByRisk = riskBudget / stopDistanceFraction;
  const notional = Math.min(risk.maxPositionNotional, risk.availableBalance * risk.maxLeverage, notionalByRisk);
  if (!Number.isFinite(notional) || notional < risk.minimumNotional) return blocked("risk_budget_below_minimum_notional", longScore, shortScore);

  const supportingStrategies = sideCandidates.filter((candidate) => candidate.score > 0).map((candidate) => candidate.signal.strategyCode);
  return {
    approved: true,
    reasonCode: "cost_adjusted_consensus_approved",
    longScore,
    shortScore,
    candidate: {
      strategyCode: selected.signal.strategyCode,
      side,
      entryPrice: selected.signal.entryPrice,
      stopLossPrice: selected.signal.stopLossPrice!,
      takeProfitPrice: selected.signal.takeProfitPrice,
      quantity: notional / selected.signal.entryPrice,
      notional,
      confidence: selected.signal.confidence,
      grossEdgeBps: selected.grossEdgeBps,
      estimatedRoundTripCostBps: selected.estimatedRoundTripCostBps,
      netEdgeBps: selected.netEdgeBps,
      supportingStrategies,
    },
  };
}
