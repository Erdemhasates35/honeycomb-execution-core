import test from 'node:test';
import assert from 'node:assert/strict';
import { RiskEngine, parseRiskLimits } from '../execution/risk_engine.js';

const limits = {
  maxRiskPerTrade: 0.01,
  maxDailyLoss: 0.02,
  maxDrawdown: 0.1,
  maxLeverage: 3,
  maxOpenOrders: 5,
  maxPositionNotional: 5000,
  maxSlippageBps: 8,
  maxFeeBps: 8,
  maxFundingBps: 20,
  maxConcentration: 0.2,
  minRewardRisk: 2,
};

const context = {
  equity: 10000,
  peakEquity: 10500,
  availableBalance: 5000,
  dailyRealizedPnl: -20,
  openOrders: 1,
  portfolioNotional: 1000,
  estimatedSlippageBps: 2,
  estimatedFeeBps: 4,
  estimatedFundingBps: 1,
  contractMultiplier: 1,
};

test('accepts a protected order within all configured risk limits', () => {
  const engine = new RiskEngine(limits);
  const result = engine.evaluate({ symbol: 'BTCUSDT', side: 'LONG', quantity: 1, leverage: 2, stopLossPrice: 98, takeProfitPrice: 104 }, 100, context);
  assert.equal(result.decision, 'allow');
  assert.equal(result.reasonCode, 'risk_limits_passed');
  assert.equal(result.metrics.rewardRisk, 2);
});

test('rejects new exposure without protective prices', () => {
  const result = new RiskEngine(limits).evaluate({ symbol: 'BTCUSDT', side: 'LONG', quantity: 1, leverage: 2 }, 100, context);
  assert.equal(result.decision, 'deny');
  assert.equal(result.reasonCode, 'protective_prices_required');
});

test('rejects leverage and daily loss limit violations', () => {
  const engine = new RiskEngine(limits);
  const leverage = engine.evaluate({ symbol: 'BTCUSDT', side: 'LONG', quantity: 1, leverage: 5, stopLossPrice: 98, takeProfitPrice: 104 }, 100, context);
  assert.equal(leverage.reasonCode, 'max_leverage_exceeded');
  const loss = engine.evaluate({ symbol: 'BTCUSDT', side: 'LONG', quantity: 1, leverage: 2, stopLossPrice: 98, takeProfitPrice: 104 }, 100, { ...context, dailyRealizedPnl: -300 });
  assert.equal(loss.reasonCode, 'daily_loss_limit_reached');
});

test('rejects invalid reward/risk and protective direction', () => {
  const engine = new RiskEngine(limits);
  const reward = engine.evaluate({ symbol: 'BTCUSDT', side: 'LONG', quantity: 1, stopLossPrice: 99, takeProfitPrice: 101 }, 100, context);
  assert.equal(reward.reasonCode, 'minimum_reward_risk_not_met');
  const direction = engine.evaluate({ symbol: 'BTCUSDT', side: 'LONG', quantity: 1, stopLossPrice: 101, takeProfitPrice: 104 }, 100, context);
  assert.equal(direction.reasonCode, 'protective_price_direction_invalid');
});

test('validates risk profile configuration before engine construction', () => {
  assert.deepEqual(parseRiskLimits(JSON.stringify(limits)), limits);
  assert.throws(() => parseRiskLimits('{"maxLeverage":100}'), /Missing or invalid risk limit/);
});

test('rejects implicit leverage on new exposure', () => {
  const result = new RiskEngine(limits).evaluate({ symbol: 'BTCUSDT', side: 'LONG', quantity: 1, stopLossPrice: 98, takeProfitPrice: 104 }, 100, context);
  assert.equal(result.reasonCode, 'explicit_leverage_required');
});
