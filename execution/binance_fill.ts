import type { Fill, FuturesMarket, OrderIntent, ExecutionMode } from './types.js';

export interface BinanceOrderResult {
  orderId?: string | number;
  status?: string;
  executedQty?: string | number;
  avgPrice?: string | number;
  cumQuote?: string | number;
  updateTime?: number;
}

export interface BinanceUserTrade {
  id: number | string;
  orderId: number | string;
  price: string;
  qty: string;
  commission: string;
  commissionAsset: string;
  time: number;
  maker: boolean;
  realizedPnl?: string;
}

export interface ReconciledBinanceFill {
  fill: Fill;
  trades: BinanceUserTrade[];
}

export function normalizeBinanceOrderFill(result: BinanceOrderResult, intent: OrderIntent, market: FuturesMarket, feeRate: number, mode: ExecutionMode = 'LIVE'): Fill {
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
    feeAsset: market === 'COIN_M' ? 'COIN' : 'USDT',
    status,
    clientOrderId: intent.clientOrderId,
    settlementAsset: market === 'COIN_M' ? 'COIN' : 'USDT',
    timestamp: Number.isFinite(result.updateTime) && Number(result.updateTime) > 0 ? Number(result.updateTime) : Date.now(),
    mode,
    market
  };
}

export function reconcileBinanceUserTrades(result: BinanceOrderResult, allTrades: BinanceUserTrade[], intent: OrderIntent, market: FuturesMarket, mode: ExecutionMode): ReconciledBinanceFill {
  const orderId = result.orderId === undefined || result.orderId === null ? '' : String(result.orderId);
  const status = String(result.status ?? '').toUpperCase();
  const executedQty = Number(result.executedQty);
  if (!orderId) throw new Error('Binance order response is missing orderId');
  if (status !== 'FILLED' && status !== 'CANCELED') throw new Error(`Binance order did not reach a terminal state: ${status || 'UNKNOWN'}`);
  if (!Number.isFinite(executedQty) || executedQty <= 0) throw new Error('Binance order has no exchange-confirmed executed quantity');
  const trades = allTrades.filter((trade) => String(trade.orderId) === orderId);
  if (trades.length === 0) throw new Error('Binance userTrades returned no records for the order');
  const quantity = trades.reduce((sum, trade) => sum + Number(trade.qty), 0);
  const notional = trades.reduce((sum, trade) => sum + Number(trade.qty) * Number(trade.price), 0);
  const commissions = trades.map((trade) => Number(trade.commission));
  const assets = [...new Set(trades.map((trade) => trade.commissionAsset))];
  if (Math.abs(quantity - executedQty) > Math.max(1e-10, executedQty * 1e-8)) throw new Error('Binance userTrades quantity does not match order executedQty');
  if (assets.length !== 1 || !assets[0]) throw new Error('Binance userTrades commission assets are inconsistent');
  if (commissions.some((value) => !Number.isFinite(value) || value < 0)) throw new Error('Binance userTrades contains an invalid commission');
  const price = notional / quantity;
  const fee = commissions.reduce((sum, value) => sum + value, 0);
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(fee)) throw new Error('Binance userTrades contains invalid fill economics');
  const fill: Fill = {
    orderId,
    symbol: intent.symbol,
    side: intent.side,
    quantity,
    price,
    fee,
    feeEstimated: false,
    feeAsset: assets[0],
    status: status === 'FILLED' ? 'FILLED' : 'PARTIALLY_FILLED',
    clientOrderId: intent.clientOrderId,
    settlementAsset: market === 'COIN_M' ? 'COIN' : 'USDT',
    timestamp: Math.max(...trades.map((trade) => trade.time)),
    mode,
    market,
  };
  return { fill, trades };
}
