import test from 'node:test';
import assert from 'node:assert/strict';
import { NexusTelemetryClient, NexusTelemetryError } from '../execution/nexus_telemetry_client.js';

test('requires HTTPS endpoint and token', () => {
  assert.throws(() => new NexusTelemetryClient({ endpoint: 'http://localhost', token: 'token' }), /HTTPS/);
  assert.throws(() => new NexusTelemetryClient({ endpoint: 'https://example.test', token: '' }), /missing or invalid/);
});

test('posts authenticated allowlisted telemetry and returns the database identifier', async () => {
  let captured: RequestInit | undefined;
  const client = new NexusTelemetryClient({
    endpoint: 'https://edge.example.test/functions/v1/nexus-telemetry-ingest/',
    token: 'test-token',
    fetcher: async (_input, init) => {
      captured = init;
      return new Response(JSON.stringify({ ok: true, id: 'intent-123', kind: 'order_intent' }), { status: 201 });
    },
  });
  const result = await client.createOrderIntent({
    strategyCode: 'basis_funding_velocity',
    accountId: '123e4567-e89b-42d3-a456-426614174000',
    instrumentId: '123e4567-e89b-42d3-a456-426614174001',
    clientOrderId: 'client-1',
    idempotencyKey: 'idem-1',
    side: 'buy',
    quantity: '0.001',
    requestedMode: 'testnet',
  });
  assert.equal(result.id, 'intent-123');
  assert.equal(result.kind, 'order_intent');
  assert.equal((captured?.headers as Record<string,string>).authorization, 'Bearer test-token');
  const body = JSON.parse(String(captured?.body));
  assert.equal(body.kind, 'order_intent');
  assert.equal(body.record.quantity, '0.001');
  assert.equal(body.record.requested_mode, 'testnet');
});

test('rejects a response that does not acknowledge a persisted record', async () => {
  const client = new NexusTelemetryClient({
    endpoint: 'https://edge.example.test/functions/v1/nexus-telemetry-ingest',
    token: 'test-token',
    fetcher: async () => new Response(JSON.stringify({ ok: false, error: 'unauthorized' }), { status: 401 }),
  });
  await assert.rejects(client.record('heartbeat', { agent_code: 'scout', worker_id: 'worker-a', status: 'healthy' }), (error: unknown) => error instanceof NexusTelemetryError && error.status === 401);
});

test('registers venue accounts as disabled metadata, never armed', async () => {
  let payload: any;
  const client = new NexusTelemetryClient({
    endpoint: 'https://edge.example.test/functions/v1/nexus-telemetry-ingest',
    token: 'test-token',
    fetcher: async (_input, init) => {
      payload = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({ ok: true, id: 'account-1' }), { status: 201 });
    },
  });
  await client.registerVenueAccount({ venue: 'binance', accountLabel: 'testnet-primary', environment: 'testnet' });
  assert.equal(payload.record.environment, 'testnet');
  assert.equal('status' in payload.record, false);
});

test('loads versioned execution configuration from the guarded Supabase endpoint', async () => {
  let captured: RequestInit | undefined;
  const config = {
    mode: 'testnet',
    riskProfile: {
      profileCode: 'canary_testnet_v1',
      enabled: true,
      maxRiskPerTrade: 0.001,
      maxDailyLoss: 0.01,
      maxDrawdown: 0.05,
      maxLeverage: 2,
      maxOpenOrders: 2,
      maxPositionNotional: 100,
      maxSlippageBps: 5,
      maxFeeBps: 10,
      maxFundingBps: 15,
      maxConcentration: 0.1,
      minRewardRisk: 1.5,
      config: {},
    },
    strategy: {
      strategyCode: 'basis_funding_velocity',
      enabled: true,
      supportedModes: ['testnet'],
      config: {},
      version: {
        id: 'version-1',
        version: '1.0.0',
        sourceCommitSha: 'a'.repeat(40),
        configSha256: 'b'.repeat(64),
        validationStatus: 'validated',
        parameterSchema: {},
        parameters: {},
      },
    },
    activeGuardPolicy: null,
    circuitBreakers: [],
  };
  const client = new NexusTelemetryClient({
    endpoint: 'https://edge.example.test/functions/v1/nexus-telemetry-ingest',
    token: 'test-token',
    fetcher: async (_input, init) => {
      captured = init;
      return new Response(JSON.stringify({ ok: true, kind: 'execution_config', data: config }), { status: 200 });
    },
  });
  const result = await client.getExecutionConfig({
    riskProfileCode: 'canary_testnet_v1',
    strategyCode: 'basis_funding_velocity',
    mode: 'testnet',
    accountId: '123e4567-e89b-42d3-a456-426614174000',
    instrumentId: '123e4567-e89b-42d3-a456-426614174001',
    symbol: 'BTCUSDT',
  });
  assert.equal(result.riskProfile.profileCode, 'canary_testnet_v1');
  assert.equal(result.strategy.version.validationStatus, 'validated');
  assert.equal((captured?.headers as Record<string,string>).authorization, 'Bearer test-token');
  assert.equal((captured?.headers as Record<string,string>)['cache-control'], 'no-store');
  const body = JSON.parse(String(captured?.body));
  assert.equal(body.kind, 'execution_config');
  assert.equal(body.record.risk_profile_code, 'canary_testnet_v1');
  assert.equal(body.record.strategy_code, 'basis_funding_velocity');
  assert.equal(body.record.mode, 'testnet');
  assert.equal(body.record.account_id, '123e4567-e89b-42d3-a456-426614174000');
  assert.equal(body.record.instrument_id, '123e4567-e89b-42d3-a456-426614174001');
  assert.equal(body.record.symbol, 'BTCUSDT');
});
