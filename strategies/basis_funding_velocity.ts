import { clamp, regressionSlope, assertPositive } from "./math.js";
import type { StrategySignal } from "./types.js";

export interface FundingPoint {
  fundingTime: number;
  fundingRate: number;
}

export interface BasisFundingInput {
  symbol: string;
  markPrice: number;
  indexPrice: number;
  lastFundingRate: number;
  fundingHistory: FundingPoint[];
  atr: number;
  estimatedRoundTripCostBps: number;
}

export interface BasisFundingConfig {
  minFundingBps: number;
  minBasisBps: number;
  basisCaptureFraction: number;
  velocityLookaheadPeriods: number;
  minExpectedEdgeBps: number;
  stopAtr: number;
  targetAtr: number;
  minRewardRisk: number;
}

export function evaluateBasisFundingVelocity(input: BasisFundingInput, config: BasisFundingConfig): StrategySignal {
  assertPositive(input.markPrice,"markPrice");
  assertPositive(input.indexPrice,"indexPrice");
  assertPositive(input.atr,"atr");
  if (!Number.isFinite(input.lastFundingRate) || !Number.isFinite(input.estimatedRoundTripCostBps) || input.estimatedRoundTripCostBps < 0) throw new Error("Funding input is invalid");
  if (input.fundingHistory.length < 3 || input.fundingHistory.some(point => !Number.isFinite(point.fundingRate) || !Number.isFinite(point.fundingTime))) {
    return { strategyCode:"basis_funding_velocity",side:"FLAT",confidence:0,expectedEdgeBps:0,entryPrice:input.markPrice,stopLossPrice:null,takeProfitPrice:null,reasonCodes:["insufficient_funding_history"],metadata:{symbol:input.symbol} };
  }
  if (config.basisCaptureFraction < 0 || config.basisCaptureFraction > 1 || config.velocityLookaheadPeriods < 0 || config.stopAtr <= 0 || config.targetAtr <= 0 || config.minRewardRisk <= 0) throw new Error("Basis funding strategy configuration is invalid");
  const basisBps = (input.markPrice-input.indexPrice)/input.indexPrice*10000;
  const fundingBps = input.lastFundingRate*10000;
  const fundingVelocityBps = regressionSlope(input.fundingHistory.slice(-8).map(point => point.fundingRate*10000));
  const side = fundingBps >= config.minFundingBps && basisBps >= config.minBasisBps
    ? "SHORT"
    : fundingBps <= -config.minFundingBps && basisBps <= -config.minBasisBps
      ? "LONG"
      : "FLAT";
  const favorableFundingVelocityBps = side === "SHORT" ? Math.max(0,fundingVelocityBps) : side === "LONG" ? Math.max(0,-fundingVelocityBps) : 0;
  const grossEdgeBps = Math.abs(fundingBps)+Math.abs(basisBps)*config.basisCaptureFraction+favorableFundingVelocityBps*config.velocityLookaheadPeriods;
  const expectedEdgeBps = grossEdgeBps-input.estimatedRoundTripCostBps;
  if (side === "FLAT") {
    return { strategyCode:"basis_funding_velocity",side,confidence:0,expectedEdgeBps,entryPrice:input.markPrice,stopLossPrice:null,takeProfitPrice:null,reasonCodes:["funding_basis_alignment_missing"],metadata:{symbol:input.symbol,basisBps,fundingBps,fundingVelocityBps,favorableFundingVelocityBps,grossEdgeBps,estimatedRoundTripCostBps:input.estimatedRoundTripCostBps} };
  }
  if (expectedEdgeBps < config.minExpectedEdgeBps) {
    return { strategyCode:"basis_funding_velocity",side:"FLAT",confidence:0,expectedEdgeBps,entryPrice:input.markPrice,stopLossPrice:null,takeProfitPrice:null,reasonCodes:["net_edge_below_threshold"],metadata:{symbol:input.symbol,basisBps,fundingBps,fundingVelocityBps,grossEdgeBps,estimatedRoundTripCostBps:input.estimatedRoundTripCostBps} };
  }
  const rewardRisk = config.targetAtr/config.stopAtr;
  if (rewardRisk < config.minRewardRisk) {
    return { strategyCode:"basis_funding_velocity",side:"FLAT",confidence:0,expectedEdgeBps,entryPrice:input.markPrice,stopLossPrice:null,takeProfitPrice:null,reasonCodes:["reward_risk_below_policy"],metadata:{symbol:input.symbol,rewardRisk} };
  }
  const stopDistance = input.atr*config.stopAtr;
  const targetDistance = input.atr*config.targetAtr;
  const stopLossPrice = side === "LONG" ? input.markPrice-stopDistance : input.markPrice+stopDistance;
  const takeProfitPrice = side === "LONG" ? input.markPrice+targetDistance : input.markPrice-targetDistance;
  const confidence = clamp((expectedEdgeBps-config.minExpectedEdgeBps)/Math.max(config.minExpectedEdgeBps,1),0,1);
  return {
    strategyCode:"basis_funding_velocity",
    side,
    confidence,
    expectedEdgeBps,
    entryPrice:input.markPrice,
    stopLossPrice,
    takeProfitPrice,
    reasonCodes:["funding_basis_velocity_positive","costs_subtracted","atr_protection_attached"],
    metadata:{symbol:input.symbol,basisBps,fundingBps,fundingVelocityBps,grossEdgeBps,estimatedRoundTripCostBps:input.estimatedRoundTripCostBps,rewardRisk},
  };
}
