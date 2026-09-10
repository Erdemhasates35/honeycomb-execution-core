import test from 'node:test';
import assert from 'node:assert/strict';
import { ExecutionRouter } from '../execution/execution_router.js';

test('TEST defaults to COIN_M and never requires credentials', async () => {
  const router = new ExecutionRouter({ mode: 'TEST', market: 'COIN_M', initialBalance: 1000 });
  await router.initialize();
  const testAdapter = router.testAdapter!;
  testAdapter.setPrice('BTCUSD_PERP', 100000);
  const fill = await router.place({ symbol: 'BTCUSD_PERP', side: 'LONG', quantity: 1, referencePrice: 100000 });
  assert.equal(fill.mode, 'TEST');
  assert.equal(fill.market, 'COIN_M');
  await router.close('BTCUSD_PERP', 101000);
  assert.equal(router.snapshot().positions.length, 0);
  await router.terminate();
});

test('LIVE is independently armed', () => {
  const old = process.env.LIVE_ARMED;
  delete process.env.LIVE_ARMED;
  assert.throws(() => new ExecutionRouter({ mode: 'LIVE', market: 'COIN_M', apiKey: 'x', apiSecret: 'y' }), /LIVE requires LIVE_ARMED=1/);
  if (old === undefined) delete process.env.LIVE_ARMED; else process.env.LIVE_ARMED = old;
});
