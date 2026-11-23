import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeBinanceOrderFill } from '../execution/binance_fill.js';

const intent = { symbol: 'BTCUSDT', side: 'LONG' as const, quantity: 0.01 };

test('accepts a fully executed exchange fill using exchange-confirmed values', () => {
  const fill = normalizeBinanceOrderFill({ orderId: 123, status: 'FILLED', executedQty: '0.01', avgPrice: '65000', updateTime: 1000 }, intent, 'USDT_M', 0.0004);
  assert.equal(fill.orderId, '123');
  assert.equal(fill.quantity, 0.01);
  assert.equal(fill.price, 65000);
  assert.equal(fill.feeEstimated, true);
});

test('accepts an actual partial fill without inflating its quantity', () => {
  const fill = normalizeBinanceOrderFill({ orderId: 124, status: 'PARTIALLY_FILLED', executedQty: '0.004', cumQuote: '260', updateTime: 1000 }, intent, 'USDT_M', 0.0004);
  assert.equal(fill.quantity, 0.004);
  assert.equal(fill.price, 65000);
  assert.equal(fill.status, 'PARTIALLY_FILLED');
});

test('rejects an unexecuted order', () => {
  assert.throws(() => normalizeBinanceOrderFill({ orderId: 125, status: 'NEW', executedQty: '0', avgPrice: '0' }, intent, 'USDT_M', 0.0004));
});

test('rejects a missing exchange order id', () => {
  assert.throws(() => normalizeBinanceOrderFill({ status: 'FILLED', executedQty: '0.01', avgPrice: '65000' }, intent, 'USDT_M', 0.0004));
});

test('rejects a filled status with an incomplete quantity', () => {
  assert.throws(() => normalizeBinanceOrderFill({ orderId: 126, status: 'FILLED', executedQty: '0.004', avgPrice: '65000' }, intent, 'USDT_M', 0.0004));
});

test('rejects a missing confirmed fill price', () => {
  assert.throws(() => normalizeBinanceOrderFill({ orderId: 127, status: 'FILLED', executedQty: '0.01', avgPrice: '0', cumQuote: '0' }, intent, 'USDT_M', 0.0004));
});
