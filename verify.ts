import { BinanceFuturesEngine } from './BinanceFuturesEngineCatE.js';
import type { OrderRequest } from './execution/types.js';

// Existing verification/runtime surface is preserved; only the response typing is hardened.

async function runVerification() {
  console.log('[VERIFY]: BinanceFuturesEngineCatE Başlatılıyor...');
  const engine = new BinanceFuturesEngine();
  const symbols = ['BTCUSDT'];
  for (const symbol of symbols) {
    try {
      const positions = await engine.getPositionRisk(symbol);
      const markPrice = parseFloat(positions[0]?.markPrice || '0');
      if (markPrice <= 0) continue;
      const metric = { atr: markPrice * 0.01 };
      const riskAmountUSD = 10;
      const stopDistance = Math.max(metric.atr * 1.5, markPrice * 0.015);
      const stopLossPrice = markPrice - stopDistance;
      const takeProfitPrice = markPrice + (stopDistance * 3);
      const quantity = (riskAmountUSD / stopDistance).toFixed(3);
      console.log(`[EXECUTION]: Pozisyon Açılıyor -> ${symbol} | Miktar: ${quantity} | Fiyat: $${markPrice}`);
      const order: OrderRequest = { symbol, side: 'BUY', type: 'MARKET', quantity };
      try {
        const raw = await engine.executeOrder(order);
        const res = raw as Partial<{ orderId: string }>;
        console.log(`[EXECUTION SUCCESS]: ${symbol} İletildi | OrderId: ${res.orderId || 'OK'}`);
        void stopLossPrice;
        void takeProfitPrice;
      } catch (err) {
        console.error(`[EXECUTION ERROR]: ${symbol} Hatası:`, (err as Error).message);
      }
    } catch (err) {
      console.error(`[VERIFY ERROR]: ${symbol} Hatası:`, (err as Error).message);
    }
  }
}

runVerification().catch((err) => {
  console.error('[VERIFY FATAL]:', err);
  process.exitCode = 1;
});
