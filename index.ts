import dotenv from 'dotenv';
import { BinanceFuturesEngineCatE, type FuturesMarket } from './BinanceFuturesEngineCatE.js';

dotenv.config();

async function main() {
  const apiKey = (process.env.BINANCE_API_KEY || '').trim();
  const apiSecret = (process.env.BINANCE_API_SECRET || process.env.BINANCE_SECRET || '').trim();
  const marketType = ((process.env.FUTURES_MARKET || 'USDT_M').toUpperCase() as FuturesMarket);
  if (!apiKey || !apiSecret) throw new Error('BINANCE_API_KEY and BINANCE_API_SECRET/BINANCE_SECRET are required in .env');
  if (!['COIN_M', 'USDT_M'].includes(marketType)) throw new Error(`Unsupported FUTURES_MARKET=${marketType}`);

  console.log(`[PRODUCTION]: Starting BinanceFuturesEngineCatE | market=${marketType} | mainnet`);
  console.log(`[AUTH CHECK]: API Key Length: ${apiKey.length} | API Secret Length: ${apiSecret.length}`);

  const engine = new BinanceFuturesEngineCatE({
    apiKey,
    apiSecret,
    marketType,
    recvWindow: Number(process.env.BINANCE_RECV_WINDOW || process.env.BINANCE_RECV_WINDOW_MS) || 5000,
    maxRetries: Number(process.env.BINANCE_MAX_RETRIES) || 5,
  });

  engine.on('connected', () => console.log('[STREAM]: User Data Stream connected.'));
  engine.on('orderUpdate', (order) => console.log('[EVENT]: Order Update:', order.s, 'Side:', order.S, 'PosSide:', order.ps, 'Price:', order.p, 'Qty:', order.q));
  engine.on('accountUpdate', (acc) => console.log('[EVENT]: Account State Updated. Reason:', acc.m));
  engine.on('marginCall', (mc) => console.warn('[CRITICAL]: Margin Call Triggered!', mc));
  engine.on('rateLimitExceeded', (data) => console.warn('[WARNING]: Rate limit warning emitted:', data));
  engine.on('error', (err) => console.error('[ENGINE ERROR]:', err.message));

  const shutdown = async () => {
    console.log('\n[SHUTDOWN]: Terminating Binance Futures Engine gracefully...');
    engine.terminate();
    console.log('[SHUTDOWN]: Complete.');
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  try {
    await engine.initialize();
    await engine.getAccountBalance();
    console.log('[STATUS]: Engine initialized successfully. Account balance fetched.');
    const positions = await engine.getPositionRisk();
    const activePositions = positions.filter((p) => parseFloat(p.positionAmt) !== 0);
    console.log(`[STATUS]: Active Positions Count: ${activePositions.length}`);
    activePositions.forEach((pos) => console.log(`[POSITION]: ${pos.symbol} | Side=${pos.positionSide} | Amount=${pos.positionAmt} | Entry=${pos.entryPrice} | Mark=${pos.markPrice} | PnL=${pos.unRealizedProfit}`));
  } catch (err) {
    console.error('[INITIALIZATION ERROR]:', (err as Error).message);
    await shutdown();
  }
}

main().catch((err) => { console.error('[FATAL]:', err.message); process.exit(1); });
