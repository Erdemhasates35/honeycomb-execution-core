import test from "node:test";
import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import { ExecutionRouter } from "../execution/execution_router.js";
import {
  assertProductionExecutionMode,
  createExecutionHttpHandler,
  parseCloseIntent,
  parseOpenIntent,
  validateControlApiToken,
} from "../nexus_http_server.js";

const TOKEN = "honeycomb-test-control-token-0123456789abcdef";

async function withServer(
  handler: ReturnType<typeof createExecutionHttpHandler>,
  action: (baseUrl: string) => Promise<void>,
): Promise<void> {
  const server: Server = createServer(handler);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });

  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Test HTTP server did not bind to a TCP port");
  try {
    await action(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => error ? reject(error) : resolve());
    });
  }
}

test("production HTTP API rejects TEST and PAPER execution modes", () => {
  assert.throws(() => assertProductionExecutionMode("TEST"), /TEST and PAPER are disabled/);
  assert.throws(() => assertProductionExecutionMode("PAPER"), /TEST and PAPER are disabled/);
  assert.doesNotThrow(() => assertProductionExecutionMode("TESTNET"));
  assert.doesNotThrow(() => assertProductionExecutionMode("LIVE"));
});

test("control API token must be at least 32 bytes", () => {
  assert.throws(() => validateControlApiToken("short"), /at least 32 bytes/);
  assert.doesNotThrow(() => validateControlApiToken(TOKEN));
});

test("entry parser requires an idempotency key and a signed approval in LIVE mode", () => {
  assert.throws(
    () => parseOpenIntent({ symbol: "BTCUSDT", side: "LONG", quantity: 0.001 }, "TESTNET"),
    /valid_idempotency_key_required/,
  );
  assert.throws(
    () => parseOpenIntent({ symbol: "BTCUSDT", side: "LONG", quantity: 0.001, idempotencyKey: "order-key-123" }, "LIVE"),
    /live_guard_approval_digest_required/,
  );
});

test("entry parser normalizes the request and accepts the documented size alias", () => {
  const intent = parseOpenIntent({
    symbol: "btcusdt",
    side: "long",
    size: 0.001,
    leverage: 2,
    idempotencyKey: "client-order-key-123",
    guardApprovalDigest: "signed-testnet-approval",
  }, "TESTNET");

  assert.equal(intent.symbol, "BTCUSDT");
  assert.equal(intent.side, "LONG");
  assert.equal(intent.quantity, 0.001);
  assert.equal(intent.leverage, 2);
  assert.equal(intent.idempotencyKey, "client-order-key-123");
});

test("entry parser does not let clients override server-owned strategy or risk profiles", () => {
  assert.throws(
    () => parseOpenIntent({
      symbol: "BTCUSDT", side: "LONG", quantity: 0.001,
      idempotencyKey: "client-order-key-123", strategyCode: "unapproved_strategy",
    }, "TESTNET"),
    /unexpected_field_strategyCode/,
  );
});

test("close parser requires idempotency and a LIVE Guard approval digest", () => {
  assert.throws(
    () => parseCloseIntent({ symbol: "BTCUSDT", idempotencyKey: "close-order-key-123" }, "LIVE"),
    /live_guard_approval_digest_required/,
  );
  const intent = parseCloseIntent({
    symbol: "btcusdt",
    referencePrice: 100000,
    idempotencyKey: "close-order-key-123",
    guardApprovalDigest: "signed-close-approval",
  }, "LIVE");
  assert.equal(intent.symbol, "BTCUSDT");
  assert.equal(intent.idempotencyKey, "close-order-key-123");
});

test("health endpoint is public and does not expose account balances", async () => {
  const router = new ExecutionRouter({ mode: "TEST", market: "USDT_M" });
  const handler = createExecutionHttpHandler(router, TOKEN);
  await withServer(handler, async (baseUrl) => {
    const response = await fetch(`${baseUrl}/health`);
    const payload = await response.json() as Record<string, unknown>;
    assert.equal(response.status, 200);
    assert.equal(payload.status, "ok");
    assert.equal(payload.mode, "TEST");
    assert.equal("balance" in payload, false);
  });
});

test("private routes reject missing and incorrect Bearer tokens", async () => {
  const router = new ExecutionRouter({ mode: "TEST", market: "USDT_M" });
  const handler = createExecutionHttpHandler(router, TOKEN);
  await withServer(handler, async (baseUrl) => {
    const missing = await fetch(`${baseUrl}/logs`);
    assert.equal(missing.status, 401);

    const incorrect = await fetch(`${baseUrl}/logs`, {
      headers: { authorization: "Bearer wrong-token" },
    });
    assert.equal(incorrect.status, 401);

    const authorized = await fetch(`${baseUrl}/logs`, {
      headers: { authorization: `Bearer ${TOKEN}` },
    });
    assert.equal(authorized.status, 200);
    assert.deepEqual(await authorized.json(), []);
  });
});

test("HTTP API rejects oversized order bodies before reaching the execution router", async () => {
  const router = new ExecutionRouter({ mode: "TEST", market: "USDT_M" });
  const handler = createExecutionHttpHandler(router, TOKEN);
  await withServer(handler, async (baseUrl) => {
    const response = await fetch(`${baseUrl}/order/open`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${TOKEN}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ padding: "x".repeat(17 * 1024) }),
    });
    const payload = await response.json() as Record<string, unknown>;
    assert.equal(response.status, 413);
    assert.equal(payload.error, "request_body_too_large");
  });
});

test("HTTP API returns 405 for a known route with the wrong method", async () => {
  const router = new ExecutionRouter({ mode: "TEST", market: "USDT_M" });
  const handler = createExecutionHttpHandler(router, TOKEN);
  await withServer(handler, async (baseUrl) => {
    const response = await fetch(`${baseUrl}/order/open`, {
      headers: { authorization: `Bearer ${TOKEN}` },
    });
    assert.equal(response.status, 405);
  });
});
