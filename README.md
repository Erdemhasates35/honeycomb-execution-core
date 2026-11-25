# α-HONEYCOMB EXECUTION CORE

Binance Futures execution engine with a guarded Node.js HTTP control API. The repository also contains a Go fail-closed router; that Go router is **not** the production exchange adapter.

## Runtime contract

- The production HTTP service accepts only \`EXECUTION_MODE=TESTNET\` or \`EXECUTION_MODE=LIVE\`. It refuses \`TEST\` and \`PAPER\` modes.
- Testnet requires \`TESTNET_ARMED=1\` and separate Binance testnet credentials.
- Live requires \`LIVE_ARMED=1\`, production trading credentials, an enabled Supabase risk profile, strategy configuration, executor identity, an armed venue account, an active guard policy, and a signed per-intent Guard approval digest.
- \`CONTROL_API_TOKEN\` is mandatory and must be at least 32 bytes. Every route except \`GET /health\` requires \`Authorization: Bearer <token>\`.
- Every open/close request requires a caller-supplied idempotency key. Duplicate submissions are rejected by the telemetry idempotency contract.
- The service binds to \`127.0.0.1:8080\` by default. Expose it only through a TLS reverse proxy and firewall policy; do not publish plain HTTP directly.
- The live adapter in this repository is Binance Futures. Bitget execution is not connected and must not be advertised as active.
- No API key, token, private key, or account secret belongs in Git.

## Ubuntu VPS setup

Use Node.js 24 and npm. The execution host must be a Linux x64 VPS; Termux/Android is not a supported production host.

\`\`\`bash
git clone https://github.com/Erdemhasates35/honeycomb-execution-core.git
cd honeycomb-execution-core
npm ci
cp .env.example .env
\`\`\`

Set the real environment values in \`.env\` or the service secret manager. Generate the control-plane token locally:

\`\`\`bash
openssl rand -hex 32
\`\`\`

Set \`CONTROL_API_TOKEN\` to the generated value. Do not commit \`.env\`.

For a testnet deployment, set \`EXECUTION_MODE=TESTNET\`, \`TESTNET_ARMED=1\`, and the separate \`BINANCE_TESTNET_API_KEY\` / \`BINANCE_TESTNET_API_SECRET\` values. Configure the Supabase telemetry URL/token, account label, strategy code, risk profile code, settlement asset, and testnet account state before startup.

For live deployment, use \`EXECUTION_MODE=LIVE\`, \`LIVE_ARMED=1\`, production trading credentials, \`NEXUS_EXECUTOR_ID\`, and a fully provisioned, enabled production risk/strategy/guard configuration. A read-only exchange key is insufficient for order submission.

Start the authenticated execution API:

\`\`\`bash
npm run start:api
\`\`\`

The process fails during startup if mode, credentials, account configuration, telemetry, or exchange initialization is incomplete. It does not silently fall back to paper or test execution.

## HTTP API

All private routes require the Bearer token. JSON request bodies are limited to 16 KiB.

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| GET | \`/health\` | Public | Process health and mode |
| GET | \`/status\` | Required | Account balance and execution counts |
| GET | \`/positions\` | Required | Reconciled open positions |
| GET | \`/logs\` | Required | Recent API execution events |
| GET | \`/mark-price?symbol=BTCUSDT\` | Required | Exchange mark price |
| POST | \`/order/open\` | Required | Submit a guarded entry order |
| POST | \`/order/close\` | Required | Close an existing position |

Example entry request:

\`\`\`json
{
  "symbol": "BTCUSDT",
  "side": "LONG",
  "quantity": 0.001,
  "leverage": 1,
  "idempotencyKey": "unique-client-generated-key",
  "guardApprovalDigest": "signed-guard-digest"
}
\`\`\`

The live adapter independently verifies risk limits and the signed Guard approval against Supabase before it submits an exchange order. A successful HTTP response is returned only after the adapter has a venue acknowledgement and reconciled fill evidence.

## Legacy Go router

\`go run ./cmd/engine\` remains a fail-closed diagnostic service. It has no connected live exchange adapter and must not be used as the production order API. It rejects open/close requests rather than fabricating fills or local positions.

## Verification boundary

CI unit tests and static checks do not prove a real exchange order. Production certification requires a successful Binance testnet startup, signed Guard approval, actual exchange order acknowledgement, trade-ledger reconciliation, protective-order confirmation, and clean post-trade position reconciliation.