import type { ExecutionAdapter, ExecutionSnapshot, Fill, FuturesMarket, OrderIntent, Position } from './types.js';

type FetchLike = typeof fetch;
interface ContractMeta { contractSize: number; settlementAsset: string; }

export class PaperExecutionAdapter implements ExecutionAdapter {
  readonly mode = 'PAPER' as const;
  readonly market: FuturesMarket;
  private balance: number;
  private sequence = 0;
  private readonly positions = new Map<string, Position>();
  private readonly fills: Fill[] = [];
  private readonly metadata = new Map<string, ContractMeta>();
  private readonly fetcher: FetchLike;
  private readonly feeRate: number;
  private readonly slippageBps: number;

  constructor(options: {
    market?: FuturesMarket;
    initialBalance?: number;
    feeRate?: number;
    slippageBps?: number;
    fetcher?: FetchLike;
  } = {}) {
    this.market = options.market ?? 'COIN_M';
    this.balance = options.initialBalance ?? 100_000;
    this.feeRate = options.feeRate ?? 0.0004;
    this.slippageBps = options.slippageBps ?? 1;
    this.fetcher = options.fetcher ?? fetch;
  }

  private baseUrl(): string {
    return this.market === 'COIN_M' ? 'https://dapi.binance.com' : 'https://fapi.binance.com';
  }

  private apiPrefix(): string {
    return this.market === 'COIN_M' ? '/dapi' : '/fapi';
  }

  async initialize(): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl()}${this.apiPrefix()}/v1/exchangeInfo`);
    if (!response.ok) throw new Error(`Paper exchangeInfo failed: HTTP ${response.status}`);
    const data = await response.json() as { symbols?: Array<Record<string, unknown>> };
    for (const symbol of data.symbols ?? []) {
      const name = String(symbol.symbol ?? '');
      if (!name) continue;
      const contractSize = Number(symbol.contractSize ?? 1);
      const settle = String(symbol.settlePlan ?? symbol.marginAsset ?? symbol.baseAsset ?? 'COIN');
      this.metadata.set(name, { contractSize: Number.isFinite(contractSize) && contractSize > 0 ? contractSize : 1, settlementAsset: settle });
    }
  }

  private meta(symbol: string): ContractMeta {
    return this.metadata.get(symbol) ?? { contractSize: 1, settlementAsset: this.market === 'COIN_M' ? 'COIN' : 'USDT' };
  }

  async markPrice(symbol: string): Promise<number> {
    const response = await this.fetcher(`${this.baseUrl()}${this.apiPrefix()}/v1/ticker/price?symbol=${encodeURIComponent(symbol)}`);
    if (!response.ok) throw new Error(`Paper ticker failed: HTTP ${response.status}`);
    const data = await response.json() as { price?: string };
    const price = Number(data.price);
    if (!Number.isFinite(price) || price <= 0) throw new Error(`Invalid paper price for ${symbol}`);
    return price;
  }

  private simulatedPrice(reference: number, side: 'LONG' | 'SHORT'): number {
    const slip = this.slippageBps / 10_000;
    return side === 'LONG' ? reference * (1 + slip) : reference * (1 - slip);
  }

  private fee(quantity: number, price: number, symbol: string): number {
    if (this.market === 'COIN_M') return (quantity * this.meta(symbol).contractSize / price) * this.feeRate;
    return quantity * price * this.feeRate;
  }

  async place(intent: OrderIntent): Promise<Fill> {
    if (!Number.isFinite(intent.quantity) || intent.quantity <= 0) throw new Error('Invalid paper quantity');
    const existing = this.positions.get(intent.symbol);
    if (existing && !intent.reduceOnly) throw new Error(`Paper position already open: ${intent.symbol}`);
    const reference = intent.referencePrice ?? await this.markPrice(intent.symbol);
    const price = this.simulatedPrice(reference, intent.side);
    const meta = this.meta(intent.symbol);
    const fee = this.fee(intent.quantity, price, intent.symbol);
    const fill: Fill = {
      orderId: `PAPER-${++this.sequence}`,
      symbol: intent.symbol,
      side: intent.side,
      quantity: intent.quantity,
      price,
      fee,
      settlementAsset: meta.settlementAsset,
      timestamp: Date.now(),
      mode: this.mode,
      market: this.market,
    };
    this.fills.push(fill);
    this.balance -= fee;

    if (!intent.reduceOnly) {
      this.positions.set(intent.symbol, {
        symbol: intent.symbol,
        side: intent.side,
        quantity: intent.quantity,
        entryPrice: price,
        leverage: intent.leverage ?? 1,
        realizedPnl: 0,
        unrealizedPnl: 0,
        feePaid: fee,
        settlementAsset: meta.settlementAsset,
      });
    }
    return fill;
  }

  async close(symbol: string, referencePrice?: number): Promise<Fill | null> {
    const position = this.positions.get(symbol);
    if (!position) return null;
    const reference = referencePrice ?? await this.markPrice(symbol);
    const exitSide = position.side === 'LONG' ? 'SHORT' : 'LONG';
    const fill = await this.place({ symbol, side: exitSide, quantity: position.quantity, referencePrice: reference, reduceOnly: true });
    const meta = this.meta(symbol);
    const pnl = this.market === 'COIN_M'
      ? position.side === 'LONG'
        ? position.quantity * meta.contractSize * (1 / position.entryPrice - 1 / fill.price)
        : position.quantity * meta.contractSize * (1 / fill.price - 1 / position.entryPrice)
      : position.side === 'LONG'
        ? position.quantity * (fill.price - position.entryPrice)
        : position.quantity * (position.entryPrice - fill.price);
    const net = pnl - fill.fee;
    this.balance += pnl;
    position.realizedPnl = net;
    position.unrealizedPnl = 0;
    position.feePaid += fill.fee;
    this.positions.delete(symbol);
    return fill;
  }

  snapshot(): ExecutionSnapshot {
    return { mode: this.mode, market: this.market, balance: this.balance, positions: [...this.positions.values()], fills: [...this.fills] };
  }

  async terminate(): Promise<void> {}
}
