import test from 'node:test';
import assert from 'node:assert/strict';
import { PaperExecutionAdapter } from '../execution/paper_execution_adapter.js';

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

test('PAPER COIN-M uses public metadata and inverse-settlement PnL', async () => {
  const adapter = new PaperExecutionAdapter({
    market: 'COIN_M',
    initialBalance: 100,
    feeRate: 0,
    slippageBps: 0,
    fetcher: async (url) => {
      if (url.endsWith('/exchangeInfo')) return response({ symbols: [{ symbol: 'BTCUSD_PERP', contractSize: 100, marginAsset: 'BTC' }] });
      if (url.includes('/ticker/price')) return response({ price: '100000' });
      throw new Error(`unexpected URL ${url}`);
    },
  });
  await adapter.initialize();
  await adapter.place({ symbol: 'BTCUSD_PERP', side: 'LONG', quantity: 1, referencePrice: 100000 });
  await adapter.close('BTCUSD_PERP', 110000);
  const snapshot = adapter.snapshot();
  assert.equal(snapshot.positions.length, 0);
  assert(snapshot.balance > 100);
});
