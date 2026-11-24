import test from 'node:test';
import assert from 'node:assert/strict';
import { ExecutionRouter } from '../execution/execution_router.js';

function withEnv(values: Record<string, string | undefined>, fn: () => void): void {
  const previous = new Map<string,string | undefined>();
  for (const key of Object.keys(values)) {
    previous.set(key, process.env[key]);
    if (values[key] === undefined) delete process.env[key];
    else process.env[key] = values[key]!;
  }
  try { fn(); } finally {
    for (const [key,value] of previous) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

test('defaults to paper execution', () => {
  withEnv({ EXECUTION_MODE: undefined, LIVE_ARMED: undefined, TESTNET_ARMED: undefined }, () => {
    const router = new ExecutionRouter();
    assert.equal(router.mode, 'PAPER');
  });
});

test('testnet requires explicit arming and separate testnet credentials', () => {
  withEnv({ TESTNET_ARMED: '0', BINANCE_TESTNET_API_KEY: undefined, BINANCE_TESTNET_API_SECRET: undefined }, () => {
    assert.throws(() => new ExecutionRouter({ mode: 'TESTNET' }), /TESTNET_ARMED=1/);
  });
  withEnv({ TESTNET_ARMED: '1', BINANCE_TESTNET_API_KEY: undefined, BINANCE_TESTNET_API_SECRET: undefined }, () => {
    assert.throws(() => new ExecutionRouter({ mode: 'TESTNET' }), /separate Binance testnet credentials/);
  });
});

test('live mode requires explicit arming and production credentials', () => {
  withEnv({ LIVE_ARMED: '0', BINANCE_API_KEY: undefined, BINANCE_API_SECRET: undefined, BINANCE_SECRET: undefined }, () => {
    assert.throws(() => new ExecutionRouter({ mode: 'LIVE' }), /LIVE_ARMED=1/);
  });
  withEnv({ LIVE_ARMED: '1', BINANCE_API_KEY: undefined, BINANCE_API_SECRET: undefined, BINANCE_SECRET: undefined, BINANCE_TESTNET_API_KEY: 'test-key', BINANCE_TESTNET_API_SECRET: 'test-secret' }, () => {
    assert.throws(() => new ExecutionRouter({ mode: 'LIVE' }), /production credentials/);
  });
});
