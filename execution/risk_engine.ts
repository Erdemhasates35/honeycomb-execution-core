import type { OrderIntent } from "./types.js";

export interface RiskLimits {
  maxRiskPerTrade: number;
  maxDailyLoss: number;
  maxDrawdown: number;
  maxLeverage: number;
  maxOpenOrders: number;
  maxPositionNotional: number;
  maxSlippageBps: number;
  maxFeeBps: number;
  maxFundingBps: number;
  maxConcentration: number;
  minRewardRisk: number;
}

export interface RiskContext {
  equity: number;
  peakEquity: number;
  availableBalance: number;
  dailyRealizedPnl: number;
  openOrders: number;
  portfolioNotional: number;
  estimatedSlippageBps: number;
  estimatedFeeBps: number;
  estimatedFundingBps: number;
  contractMultiplier?: number;
}

export interface RiskDecision {
  decision: "allow" | "deny";
  reasonCode: string;
  metrics: Record<string, number | boolean>;
}

function finite(value: number): boolean {
  return Number.isFinite(value);
}

export function parseRiskLimits(raw: string): RiskLimits {
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { throw new Error("NEXUS_RISK_PROFILE_JSON is invalid JSON"); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("NEXUS_RISK_PROFILE_JSON must be an object");
  const value = parsed as Record<string, unknown>;
  const keys: Array<keyof RiskLimits> = [
    "maxRiskPerTrade","maxDailyLoss","maxDrawdown","maxLeverage","maxOpenOrders",
    "maxPositionNotional","maxSlippageBps","maxFeeBps","maxFundingBps",
    "maxConcentration","minRewardRisk",
  ];
  for (const key of keys) {
    if (typeof value[key] !== "number" || !Number.isFinite(value[key] as number)) throw new Error("Missing or invalid risk limit: " + key);
  }
  const limits = value as RiskLimits;
  if (limits.maxRiskPerTrade <= 0 || limits.maxRiskPerTrade > 0.05) throw new Error("maxRiskPerTrade must be in (0, 0.05]");
  if (limits.maxDailyLoss <= 0 || limits.maxDailyLoss > 0.25) throw new Error("maxDailyLoss must be in (0, 0.25]");
  if (limits.maxDrawdown <= 0 || limits.maxDrawdown > 0.5) throw new Error("maxDrawdown must be in (0, 0.5]");
  if (limits.maxLeverage < 1 || limits.maxLeverage > 20) throw new Error("maxLeverage must be in [1, 20]");
  if (!Number.isInteger(limits.maxOpenOrders) || limits.maxOpenOrders < 1 || limits.maxOpenOrders > 100) throw new Error("maxOpenOrders must be in [1, 100]");
  if (limits.maxPositionNotional <= 0 || limits.maxSlippageBps < 0 || limits.maxFeeBps < 0 || limits.maxFundingBps < 0) throw new Error("Risk costs and notional limits are invalid");
  if (limits.maxConcentration <= 0 || limits.maxConcentration > 1 || limits.minRewardRisk < 1) throw new Error("Concentration or reward/risk limits are invalid");
  return limits;
}

export class RiskEngine {
  constructor(private readonly limits: RiskLimits) {}

  evaluate(intent: OrderIntent, entryPrice: number, context: RiskContext): RiskDecision {
    const deny = (reasonCode: string, metrics: Record<string, number | boolean> = {}): RiskDecision => ({ decision: "deny", reasonCode, metrics });
    const quantity = intent.quantity;
    const leverage = intent.leverage ?? 1;
    const multiplier = context.contractMultiplier ?? 1;
    const numericValues = [quantity,entryPrice,leverage,multiplier,context.equity,context.peakEquity,context.availableBalance,context.dailyRealizedPnl,context.portfolioNotional,context.estimatedSlippageBps,context.estimatedFeeBps,context.estimatedFundingBps];
    if (numericValues.some((value) => !finite(value))) return deny("non_finite_risk_input");
    if (!intent.reduceOnly && intent.leverage === undefined) return deny("explicit_leverage_required");
    if (quantity <= 0 || entryPrice <= 0 || leverage < 1 || multiplier <= 0) return deny("invalid_order_geometry");
    if (context.equity <= 0 || context.peakEquity <= 0 || context.availableBalance < 0) return deny("invalid_account_equity");
    if (!Number.isInteger(context.openOrders) || context.openOrders < 0) return deny("invalid_open_order_count");
    if (context.estimatedSlippageBps < 0 || context.estimatedFeeBps < 0 || context.estimatedFundingBps < 0) return deny("negative_execution_cost");

    const notional = quantity * multiplier * entryPrice;
    const marginRequired = notional / leverage;
    const dailyLoss = Math.max(0, -context.dailyRealizedPnl);
    const dailyLossRatio = dailyLoss / context.equity;
    const drawdown = Math.max(0, (context.peakEquity - context.equity) / context.peakEquity);
    const concentration = notional / Math.max(context.portfolioNotional + notional, Number.EPSILON);
    const metrics: Record<string, number | boolean> = {
      notional,
      marginRequired,
      dailyLossRatio,
      drawdown,
      concentration,
      estimatedSlippageBps: context.estimatedSlippageBps,
      estimatedFeeBps: context.estimatedFeeBps,
      estimatedFundingBps: context.estimatedFundingBps,
      leverage,
    };

    if (notional > this.limits.maxPositionNotional) return deny("max_position_notional_exceeded", metrics);
    if (leverage > this.limits.maxLeverage) return deny("max_leverage_exceeded", metrics);
    if (marginRequired > context.availableBalance) return deny("insufficient_available_margin", metrics);
    if (context.openOrders >= this.limits.maxOpenOrders && !intent.reduceOnly) return deny("max_open_orders_exceeded", metrics);
    if (context.estimatedSlippageBps > this.limits.maxSlippageBps) return deny("max_slippage_exceeded", metrics);
    if (context.estimatedFeeBps > this.limits.maxFeeBps) return deny("max_fee_exceeded", metrics);
    if (context.estimatedFundingBps > this.limits.maxFundingBps) return deny("max_funding_cost_exceeded", metrics);
    if (dailyLossRatio >= this.limits.maxDailyLoss) return deny("daily_loss_limit_reached", metrics);
    if (drawdown >= this.limits.maxDrawdown) return deny("drawdown_limit_reached", metrics);
    if (concentration > this.limits.maxConcentration && !intent.reduceOnly) return deny("portfolio_concentration_exceeded", metrics);

    if (!intent.reduceOnly) {
      const stop = intent.stopLossPrice;
      const target = intent.takeProfitPrice;
      if (!finite(Number(stop)) || !finite(Number(target)) || Number(stop) <= 0 || Number(target) <= 0) return deny("protective_prices_required", metrics);
      const stopPrice = Number(stop);
      const targetPrice = Number(target);
      const stopDirectionValid = intent.side === "LONG" ? stopPrice < entryPrice && targetPrice > entryPrice : stopPrice > entryPrice && targetPrice < entryPrice;
      if (!stopDirectionValid) return deny("protective_price_direction_invalid", metrics);
      const stopDistance = Math.abs(entryPrice - stopPrice);
      const targetDistance = Math.abs(targetPrice - entryPrice);
      const riskNotional = notional * stopDistance / entryPrice;
      const rewardRisk = targetDistance / stopDistance;
      const riskFraction = riskNotional / context.equity;
      metrics.riskNotional = riskNotional;
      metrics.riskFraction = riskFraction;
      metrics.rewardRisk = rewardRisk;
      if (riskFraction > this.limits.maxRiskPerTrade) return deny("max_risk_per_trade_exceeded", metrics);
      if (rewardRisk < this.limits.minRewardRisk) return deny("minimum_reward_risk_not_met", metrics);
    }

    return { decision: "allow", reasonCode: "risk_limits_passed", metrics };
  }
}
