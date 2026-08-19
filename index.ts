import dotenv from 'dotenv';
import { BinanceFuturesEngineCatE } from './BinanceFuturesEngineCatE.js';

dotenv.config();

async function main() {
  console.log('[PRODUCTION]: Starting BinanceFuturesEngineCatE in Mainnet (HEDGE MODE)...');

  // `.env` dosyasındaki isim yapısına ve yedek gizli anahtarlara tam uyumlu eşleme
  const apiKey = (
    process.env.BINANCE_API_KEY || 
    'raR3OFaUFv6i5OSM0qKPhnMc8NYSDv3BEaKqQsA9FNAyzidtFBohuknnxJAySw1z'
  ).trim();

  const apiSecret = (
    process.env.BINANCE_API_SECRET || 
    process.env.BINANCE_SECRET || 
    'G077RtEDOFx9GyAmGWbp70dF0jqEC0aaH2RFNVncJdKhimCd69XKNQVp7z6RMhfH'
  ).trim();

  console.log(`[AUTH CHECK]: API Key Length: ${apiKey.length} | API Secret Length: ${apiSecret.length}`);

  const engine = new BinanceFuturesEngineCatE({
    apiKey,
    apiSecret,
    recvWindow: Number(process.env.BINANCE_RECV_WINDOW) || 5000,
    maxRetries: Number(process.env.BINANCE_MAX_RETRIES) || 5,
  });

  // Event Dinleyicileri
  engine.on('connected', () => console.log('[STREAM]: Live User Data Stream connected successfully.'));
  engine.on('orderUpdate', (order) => console.log('[EVENT]: Order Update:', order.s, 'Side:', order.S, 'PosSide:', order.ps, 'Price:', order.p, 'Qty:', order.q));
  engine.on('accountUpdate', (acc) => console.log('[EVENT]: Account State Updated. Reason:', acc.m));
  engine.on('marginCall', (mc) => console.warn('[CRITICAL]: Margin Call Triggered!', mc));
  engine.on('rateLimitExceeded', (data) => console.warn('[WARNING]: Rate limit warning emitted:', data));
  engine.on('error', (err) => console.error('[ENGINE ERROR]:', err.message));

  // Safe Shutdown
  const shutdown = async () => {
    console.log('\n[SHUTDOWN]: Terminating Binance Futures Engine gracefully...');
    await engine.terminate();
    console.log('[SHUTDOWN]: Complete. Exiting process.');
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  try {
    await engine.initialize();
    
    // Canlı Hesap Bakiye ve Pozisyon Kontrolü
    const balance = await engine.getAccountBalance();
    console.log('[STATUS]: Engine initialized successfully. Account balances fetched.');
    
    const positions = await engine.getPositionRisk();
    const activePositions = positions.filter((p) => parseFloat(p.positionAmt) !== 0);
    console.log(`[STATUS]: Active Positions Count: ${activePositions.length}`);

    activePositions.forEach((pos) => {
      console.log(`[POSITION]: ${pos.symbol} | PositionSide: ${pos.positionSide} | Amount: ${pos.positionAmt} | Entry: ${pos.entryPrice} | Mark: ${pos.markPrice} | PnL: ${pos.unRealizedProfit}`);
    });

  } catch (err) {
    console.error('[INITIALIZATION ERROR]:', (err as Error).message);
    await shutdown();
  }
}

main();
