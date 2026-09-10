import test from 'node:test';
import assert from 'node:assert/strict';
import { BinanceFuturesEngineCatE } from '../BinanceFuturesEngineCatE.js';

test('Binance adapter defaults to legacy USDT-M compatibility', () => {
  const engine = new BinanceFuturesEngineCatE({ apiKey: 'x', apiSecret: 'y' });
  assert.equal(engine.marketType, 'USDT_M');
  engine.terminate();
});

test('Binance adapter accepts COIN-M without changing the public API', () => {
  const engine = new BinanceFuturesEngineCatE({ apiKey: 'x', apiSecret: 'y', marketType: 'COIN_M' });
  assert.equal(engine.marketType, 'COIN_M');
  engine.terminate();
});
