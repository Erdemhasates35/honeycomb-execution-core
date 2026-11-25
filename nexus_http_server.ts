import fs from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { timingSafeEqual, randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { ExecutionRouter } from "./execution/execution_router.js";
import type { ExecutionMode, OrderIntent } from "./execution/types.js";

const MAX_BODY_BYTES = 16 * 1024;
const MAX_LOG_ENTRIES = 200;
const SYMBOL_PATTERN = /^[A-Z0-9_]{2,32}$/;
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9._:-]{8,128}$/;
const CLIENT_ORDER_ID_PATTERN = /^[A-Za-z0-9_-]{1,36}$/;

type JsonRecord = Record<string, unknown>;

interface CloseIntent {
  symbol: string;
  referencePrice?: number;
  guardApprovalDigest?: string;
  idempotencyKey: string;
}

class ApiError extends Error {
  constructor(readonly statusCode: number, readonly code: string) {
    super(code);
  }
}

function asRecord(value: unknown): JsonRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError(400, "json_object_required");
  }
  return value as JsonRecord;
}

function optionalPositiveNumber(value: unknown, field: string): number | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new ApiError(400, `invalid_${field}`);
  }
  return value;
}

function optionalString(value: unknown, field: string, maxLength: number): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  if (typeof value !== "string" || value.length > maxLength) {
    throw new ApiError(400, `invalid_${field}`);
  }
  return value;
}

function requiredIdempotencyKey(value: unknown): string {
  if (typeof value !== "string" || !IDEMPOTENCY_PATTERN.test(value)) {
    throw new ApiError(400, "valid_idempotency_key_required");
  }
  return value;
}

function validateKnownFields(value: JsonRecord, allowed: readonly string[]): void {
  const allow = new Set(allowed);
  const unexpected = Object.keys(value).find((key) => !allow.has(key));
  if (unexpected) throw new ApiError(400, `unexpected_field_${unexpected}`);
}

export function assertProductionExecutionMode(mode: string): asserts mode is "TESTNET" | "LIVE" {
  const normalized = mode.toUpperCase();
  if (normalized !== "TESTNET" && normalized !== "LIVE") {
    throw new Error("Execution HTTP API requires EXECUTION_MODE=TESTNET or LIVE; TEST and PAPER are disabled");
  }
}

export function validateControlApiToken(token: string): void {
  if (Buffer.byteLength(token.trim(), "utf8") < 32) {
    throw new Error("CONTROL_API_TOKEN must contain at least 32 non-whitespace bytes");
  }
}

export function parseOpenIntent(value: unknown, mode: ExecutionMode): OrderIntent {
  const body = asRecord(value);
  validateKnownFields(body, [
    "symbol", "side", "quantity", "size", "leverage", "referencePrice", "positionSide",
    "clientOrderId", "idempotencyKey", "stopLossPrice", "takeProfitPrice", "guardApprovalDigest",
  ]);

  const symbol = typeof body.symbol === "string" ? body.symbol.trim().toUpperCase() : "";
  if (!SYMBOL_PATTERN.test(symbol)) throw new ApiError(400, "invalid_symbol");

  const side = typeof body.side === "string" ? body.side.trim().toUpperCase() : "";
  if (side !== "LONG" && side !== "SHORT") throw new ApiError(400, "side_must_be_LONG_or_SHORT");

  const quantityValue = body.quantity ?? body.size;
  if (typeof quantityValue !== "number" || !Number.isFinite(quantityValue) || quantityValue <= 0) {
    throw new ApiError(400, "positive_quantity_required");
  }

  const idempotencyKey = requiredIdempotencyKey(body.idempotencyKey);
  const guardApprovalDigest = optionalString(body.guardApprovalDigest, "guard_approval_digest", 512);
  if (mode === "LIVE" && !guardApprovalDigest) throw new ApiError(400, "live_guard_approval_digest_required");

  const leverage = optionalPositiveNumber(body.leverage, "leverage") ?? 1;
  if (leverage < 1 || leverage > 125) throw new ApiError(400, "leverage_out_of_range");

  const positionSideRaw = optionalString(body.positionSide, "position_side", 5);
  const positionSide = positionSideRaw?.toUpperCase() as "LONG" | "SHORT" | undefined;
  if (positionSide !== undefined && positionSide !== "LONG" && positionSide !== "SHORT") {
    throw new ApiError(400, "invalid_position_side");
  }

  const clientOrderId = optionalString(body.clientOrderId, "client_order_id", 36);
  if (clientOrderId !== undefined && !CLIENT_ORDER_ID_PATTERN.test(clientOrderId)) {
    throw new ApiError(400, "invalid_client_order_id");
  }

  const referencePrice = optionalPositiveNumber(body.referencePrice, "reference_price");
  const stopLossPrice = optionalPositiveNumber(body.stopLossPrice, "stop_loss_price");
  const takeProfitPrice = optionalPositiveNumber(body.takeProfitPrice, "take_profit_price");

  return {
    symbol,
    side,
    quantity: quantityValue,
    idempotencyKey,
    ...(leverage === undefined ? {} : { leverage }),
    ...(referencePrice === undefined ? {} : { referencePrice }),
    ...(positionSide === undefined ? {} : { positionSide }),
    ...(clientOrderId === undefined ? {} : { clientOrderId }),
    ...(stopLossPrice === undefined ? {} : { stopLossPrice }),
    ...(takeProfitPrice === undefined ? {} : { takeProfitPrice }),
    ...(guardApprovalDigest === undefined ? {} : { guardApprovalDigest }),
  };
}

export function parseCloseIntent(value: unknown, mode: ExecutionMode): CloseIntent {
  const body = asRecord(value);
  validateKnownFields(body, ["symbol", "referencePrice", "guardApprovalDigest", "idempotencyKey"]);

  const symbol = typeof body.symbol === "string" ? body.symbol.trim().toUpperCase() : "";
  if (!SYMBOL_PATTERN.test(symbol)) throw new ApiError(400, "invalid_symbol");

  const idempotencyKey = requiredIdempotencyKey(body.idempotencyKey);
  const guardApprovalDigest = optionalString(body.guardApprovalDigest, "guard_approval_digest", 512);
  if (mode === "LIVE" && !guardApprovalDigest) throw new ApiError(400, "live_guard_approval_digest_required");

  const referencePrice = optionalPositiveNumber(body.referencePrice, "reference_price");
  return {
    symbol,
    idempotencyKey,
    ...(referencePrice === undefined ? {} : { referencePrice }),
    ...(guardApprovalDigest === undefined ? {} : { guardApprovalDigest }),
  };
}

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const contentType = request.headers["content-type"]?.split(";")[0].trim().toLowerCase();
  if (contentType !== "application/json") throw new ApiError(415, "application_json_required");

  const chunks: Buffer[] = [];
  let totalBytes = 0;

  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    totalBytes += buffer.length;
    if (totalBytes > MAX_BODY_BYTES) throw new ApiError(413, "request_body_too_large");
    chunks.push(buffer);
  }

  if (totalBytes === 0) throw new ApiError(400, "json_body_required");
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
  } catch {
    throw new ApiError(400, "invalid_json");
  }
}

function sendJson(response: ServerResponse, statusCode: number, requestId: string, payload: unknown): void {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "x-request-id": requestId,
    "content-length": Buffer.byteLength(body),
  });
  response.end(body);
}

function isAuthorized(request: IncomingMessage, token: string): boolean {
  const header = request.headers.authorization;
  if (typeof header !== "string" || !header.startsWith("Bearer ")) return false;
  const supplied = Buffer.from(header.slice(7), "utf8");
  const expected = Buffer.from(token, "utf8");
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

function addLog(logs: string[], message: string): void {
  logs.push(`${new Date().toISOString()} ${message}`);
  if (logs.length > MAX_LOG_ENTRIES) logs.splice(0, logs.length - MAX_LOG_ENTRIES);
}

export function createExecutionHttpHandler(
  router: ExecutionRouter,
  token: string,
  logs: string[] = [],
): (request: IncomingMessage, response: ServerResponse) => void {
  validateControlApiToken(token);

  return (request, response) => {
    const requestId = randomUUID();
    void (async () => {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      const method = request.method ?? "GET";

      if (method === "GET" && url.pathname === "/health") {
        sendJson(response, 200, requestId, {
          status: "ok",
          service: "honeycomb-execution-core",
          mode: router.mode,
          market: router.market,
        });
        return;
      }

      if (!isAuthorized(request, token)) {
        sendJson(response, 401, requestId, { success: false, error: "unauthorized", requestId });
        return;
      }

      if (method === "GET" && url.pathname === "/status") {
        const snapshot = router.snapshot();
        sendJson(response, 200, requestId, {
          mode: snapshot.mode,
          market: snapshot.market,
          balance: snapshot.balance,
          positions: snapshot.positions.length,
          fills: snapshot.fills.length,
        });
        return;
      }

      if (method === "GET" && url.pathname === "/positions") {
        sendJson(response, 200, requestId, router.snapshot().positions);
        return;
      }

      if (method === "GET" && url.pathname === "/logs") {
        sendJson(response, 200, requestId, [...logs].reverse());
        return;
      }

      if (method === "GET" && url.pathname === "/mark-price") {
        const symbol = (url.searchParams.get("symbol") ?? "").trim().toUpperCase();
        if (!SYMBOL_PATTERN.test(symbol)) throw new ApiError(400, "invalid_symbol");
        const price = await router.markPrice(symbol);
        sendJson(response, 200, requestId, { symbol, price });
        return;
      }

      if (method === "POST" && url.pathname === "/order/open") {
        const intent = parseOpenIntent(await readJsonBody(request), router.mode);
        const fill = await router.place(intent);
        addLog(logs, `request=${requestId} order=open symbol=${intent.symbol} result=confirmed orderId=${fill.orderId}`);
        sendJson(response, 201, requestId, { success: true, fill });
        return;
      }

      if (method === "POST" && url.pathname === "/order/close") {
        const intent = parseCloseIntent(await readJsonBody(request), router.mode);
        const fill = await router.close(intent.symbol, intent.referencePrice, intent.guardApprovalDigest, intent.idempotencyKey);
        if (!fill) throw new ApiError(409, "position_not_found_or_already_closed");
        addLog(logs, `request=${requestId} order=close symbol=${intent.symbol} result=confirmed orderId=${fill.orderId}`);
        sendJson(response, 200, requestId, { success: true, fill });
        return;
      }

      const knownPath = ["/status", "/positions", "/logs", "/mark-price", "/order/open", "/order/close"].includes(url.pathname);
      throw new ApiError(knownPath ? 405 : 404, knownPath ? "method_not_allowed" : "not_found");
    })().catch((error: unknown) => {
      const statusCode = error instanceof ApiError ? error.statusCode : 502;
      const code = error instanceof ApiError ? error.code : "execution_failed";
      addLog(logs, `request=${requestId} result=error code=${code}`);
      if (!response.headersSent) sendJson(response, statusCode, requestId, { success: false, error: code, requestId });
      else response.destroy();
    });
  };
}

function listen(server: ReturnType<typeof createServer>, host: string, port: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const onError = (error: Error): void => reject(error);
    server.once("error", onError);
    server.listen(port, host, () => {
      server.off("error", onError);
      resolve();
    });
  });
}

function loadEnv(): void {
  const envPath = path.resolve(process.cwd(), ".env");
  if (!fs.existsSync(envPath)) return;
  for (const raw of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    if (key && process.env[key] === undefined) {
      process.env[key] = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
    }
  }
}

export async function startExecutionApi(): Promise<void> {
  loadEnv();
  const mode = (process.env.EXECUTION_MODE ?? "").trim().toUpperCase();
  assertProductionExecutionMode(mode);

  const token = process.env.CONTROL_API_TOKEN?.trim() ?? "";
  validateControlApiToken(token);

  const port = Number(process.env.HTTP_PORT ?? "8080");
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("HTTP_PORT must be an integer from 1 to 65535");
  const host = process.env.HTTP_HOST?.trim() || "127.0.0.1";

  const router = new ExecutionRouter({ mode: mode as ExecutionMode });
  try {
    await router.initialize();
  } catch (error) {
    try { await router.terminate(); } catch { /* preserve the initialization failure */ }
    throw error;
  }

  const logs: string[] = [];
  const server = createServer(createExecutionHttpHandler(router, token, logs));
  server.requestTimeout = 15_000;
  server.headersTimeout = 10_000;
  server.keepAliveTimeout = 5_000;
  server.maxHeadersCount = 50;

  try {
    await listen(server, host, port);
  } catch (error) {
    try { await router.terminate(); } catch { /* preserve the bind failure */ }
    throw error;
  }
  process.stdout.write(JSON.stringify({
    status: "ready",
    service: "honeycomb-execution-core",
    mode: router.mode,
    market: router.market,
    host,
    port,
  }) + "\n");

  let stopping = false;
  const shutdown = async (): Promise<void> => {
    if (stopping) return;
    stopping = true;
    try {
      await new Promise<void>((resolve, reject) => {
        server.close((error) => error ? reject(error) : resolve());
      });
    } finally {
      await router.terminate();
    }
  };
  const handleSignal = (): void => {
    void shutdown().then(() => {
      process.stdout.write("Honeycomb execution API stopped\n");
    }).catch((error: unknown) => {
      process.stderr.write(`Honeycomb execution API shutdown failed: ${error instanceof Error ? error.message : "unknown error"}\n`);
      process.exitCode = 1;
    });
  };
  process.once("SIGINT", handleSignal);
  process.once("SIGTERM", handleSignal);
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  void startExecutionApi().catch((error: unknown) => {
    const message = error instanceof Error ? error.message : "Execution API startup failed";
    process.stderr.write(JSON.stringify({ status: "failed", error: message }) + "\n");
    process.exitCode = 1;
  });
}
