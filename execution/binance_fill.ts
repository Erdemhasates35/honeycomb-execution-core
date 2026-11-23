import type { Fill, FuturesMarket, OrderIntent } from './types.js';

export interface BinanceOrderResult {
  orderId?: string | number;
  status?: string;
  executedQty?: string | number;
  avgPrice?: string | number;
  cumQuote?: string | number;
  updateTime?: number;
}

export function normalizeBinanceOrderFill(result: BinanceOrderResult, intent: OrderIntent, market: FuturesMarket, feeRate: number): Fill {
  const executedQty = Number(result.executedQty);
  const averagePrice = Number(result.avgPrice);
  const cumulativeQuote = Number(result.cumQuote);
  const price = Number.isFinite(averagePrice) && averagePrice > 0
    ? averagePrice
    : Number.isFinite(cumulativeQuote) && cumulativeQuote > 0 && executedQty > 0
      ? cumulativeQuote / executedQty
      : NaN;
  const requestedQty = intent.quantity;
  const orderId = result.orderId === undefined || result.orderId === null ? '' : String(result.orderId);
  const status = result.status;
  if (!orderId) throw new Error('Binance order response is missing orderId');
  if (status !== 'FILLED' && status !== 'PARTIALLY_FILLED') throw new Error(`Binance order is not executed: status=${String(status)}`);
  if (!Number.isFinite(executedQty) || executedQty <= 0 || executedQty > requestedQty) throw new Error('Binance returned an invalid executedQty');
  if (status === 'FILLED' && Math.abs(executedQty - requestedQty) > Math.max(1e-10, requestedQty * 1e-8)) throw new Error('Binance FILLED quantity does not match requested quantity');
  if (status === 'PARTIALLY_FILLED' && executedQty >= requestedQty) throw new Error('Binance PARTIALLY_FILLED status conflicts with executedQty');
  if (!Number.isFinite(price) || price <= 0) throw new Error('Binance order response has no confirmed average fill price');
  if (!Number.isFinite(feeRate) || feeRate < 0) throw new Error('FEE_RATE must be a finite non-negative number');
  const fee = market === 'COIN_M' ? executedQty * feeRate / price : executedQty * price * feeRate;
  return {
    orderId,
    symbol: intent.symbol,
    side: intent.side,
    quantity: executedQty,
    price,
    fee,
    feeEstimated: true,
    status,
    settlementAsset: market === 'COIN_M' ? 'COIN' : 'USDT',
    timestamp: Number.isFinite(result.updateTime) && Number(result.updateTime) > 0 ? Number(result.updateTime) : Date.now(),
    mode: 'LIVE',
    market
  };
}
