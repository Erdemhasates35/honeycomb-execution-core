import fs from 'node:fs';
import path from 'node:path';
import { ExecutionRouter } from './execution/execution_router.js';

function loadEnv(): void {
  const envPath = path.resolve(process.cwd(), '.env');
  if (!fs.existsSync(envPath)) return;
  for (const raw of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const [key, ...rest] = line.split('=');
    if (key && process.env[key] === undefined) process.env[key] = rest.join('=').trim().replace(/^['"]|['"]$/g, '');
  }
}

async function main(): Promise<void> {
  loadEnv();
  const router = new ExecutionRouter({
    mode: process.env.EXECUTION_MODE as any,
    market: process.env.FUTURES_MARKET as any,
    initialBalance: Number(process.env.PAPER_INITIAL_BALANCE || process.env.TEST_INITIAL_BALANCE || 100000),
    paperFeeRate: Number(process.env.PAPER_FEE_RATE || 0.0004),
    paperSlippageBps: Number(process.env.PAPER_SLIPPAGE_BPS || 1),
  });

  await router.initialize();
  const snapshot = router.snapshot();
  console.log(JSON.stringify({
    ok: true,
    engine: 'NEXUS_HONEYCOMB_EXECUTION_ROUTER_V10',
    mode: router.mode,
    market: router.market,
    balance: snapshot.balance,
    positions: snapshot.positions.length,
    fills: snapshot.fills.length,
    live_armed: process.env.LIVE_ARMED === '1',
  }, null, 2));

  const shutdown = async () => { await router.terminate(); process.exit(0); };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}

main().catch((error) => { console.error('[NEXUS EXECUTION FATAL]', error); process.exit(1); });
