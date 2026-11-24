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
