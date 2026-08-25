import type { ExecutionAdapter, ExecutionSnapshot, Fill, FuturesMarket, OrderIntent, Position } from './types.js';

export class TestExecutionAdapter implements ExecutionAdapter {
  readonly mode = 'TEST' as const;
  readonly market: FuturesMarket;
  private balance: number;
  private sequence = 0;
  private readonly positions = new Map<string, Position>();
  private readonly fills: Fill[] = [];
  private readonly prices = new Map<string, number>();

  constructor(options: { market?: FuturesMarket; initialBalance?: number; settlementAsset?: string } = {}) {
    this.market = options.market ?? 'COIN_M';
    this.balance = options.initialBalance ?? 100_000;
    this.settlementAsset = options.settlementAsset ?? (this.market === 'COIN_M' ? 'COIN' : 'USDT');
  }

  private readonly settlementAsset: string;

  async initialize(): Promise<void> {}

  setPrice(symbol: string, price: number): void {
    if (!Number.isFinite(price) || price <= 0) throw new Error('Invalid deterministic test price');
    this.prices.set(symbol, price);
  }

  async markPrice(symbol: string): Promise<number> {
    const price = this.prices.get(symbol);
    if (!price) throw new Error(`No deterministic price configured for ${symbol}`);
    return price;
  }

  async place(intent: OrderIntent): Promise<Fill> {
    const price = intent.referencePrice ?? await this.markPrice(intent.symbol);
    const existing = this.positions.get(intent.symbol);
    if (existing && !intent.reduceOnly) throw new Error(`Position already open for ${intent.symbol}`);

    const fill: Fill = {
      orderId: `TEST-${++this.sequence}`,
      symbol: intent.symbol,
      side: intent.side,
      quantity: intent.quantity,
      price,
      fee: 0,
      settlementAsset: this.settlementAsset,
      timestamp: Date.now(),
      mode: this.mode,
      market: this.market,
    };
    this.fills.push(fill);

    if (!intent.reduceOnly) {
      this.positions.set(intent.symbol, {
        symbol: intent.symbol,
        side: intent.side,
        quantity: intent.quantity,
        entryPrice: price,
        leverage: intent.leverage ?? 1,
        realizedPnl: 0,
        unrealizedPnl: 0,
        feePaid: 0,
        settlementAsset: this.settlementAsset,
      });
    }
    return fill;
  }

  async close(symbol: string, referencePrice?: number): Promise<Fill | null> {
    const position = this.positions.get(symbol);
    if (!position) return null;
    const price = referencePrice ?? await this.markPrice(symbol);
    const side = position.side === 'LONG' ? 'SHORT' : 'LONG';
    const fill = await this.place({ symbol, side, quantity: position.quantity, referencePrice: price, reduceOnly: true });
    const pnl = this.market === 'COIN_M'
      ? position.side === 'LONG' ? position.quantity * (1 / position.entryPrice - 1 / price) : position.quantity * (1 / price - 1 / position.entryPrice)
      : position.side === 'LONG' ? position.quantity * (price - position.entryPrice) : position.quantity * (position.entryPrice - price);
    this.balance += pnl;
    this.positions.delete(symbol);
    return fill;
  }

  snapshot(): ExecutionSnapshot {
    return { mode: this.mode, market: this.market, balance: this.balance, positions: [...this.positions.values()], fills: [...this.fills] };
  }

  async terminate(): Promise<void> {}
}
