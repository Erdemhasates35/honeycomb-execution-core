import { BinanceFuturesEngineCatE } from '../BinanceFuturesEngineCatE.js';
import { PaperExecutionAdapter } from './paper_execution_adapter.js';
import { TestExecutionAdapter } from './test_execution_adapter.js';
import type { ExecutionAdapter, ExecutionMode, ExecutionSnapshot, FuturesMarket, Fill, OrderIntent } from './types.js';

class LiveExecutionAdapter implements ExecutionAdapter {
  readonly mode = 'LIVE' as const;
  readonly market: FuturesMarket;
  private readonly engine: BinanceFuturesEngineCatE;
  private readonly fills: Fill[] = [];
  constructor(options: { apiKey: string; apiSecret: string; market: FuturesMarket; testnet?: boolean }) {
    this.market = options.market;
    this.engine = new BinanceFuturesEngineCatE({ apiKey: options.apiKey, apiSecret: options.apiSecret, testnet: options.testnet ?? false, marketType: options.market });
  }
  async initialize(): Promise<void> { await this.engine.initialize(); }
  async markPrice(symbol: string): Promise<number> {
    const prefix = this.market === 'COIN_M' ? 'dapi' : 'fapi';
    const base = this.market === 'COIN_M' ? 'https://dapi.binance.com' : 'https://fapi.binance.com';
    const response = await fetch(`${base}/${prefix}/v1/ticker/price?symbol=${encodeURIComponent(symbol)}`);
    if (!response.ok) throw new Error(`LIVE ticker failed: HTTP ${response.status}`);
    const data = await response.json() as { price?: string };
    const price = Number(data.price);
    if (!Number.isFinite(price) || price <= 0) throw new Error(`Invalid LIVE price for ${symbol}`);
    return price;
  }
  async place(intent: OrderIntent): Promise<Fill> {
    const result = await this.engine.executeOrder({ symbol: intent.symbol, side: intent.side === 'LONG' ? 'BUY' : 'SELL', type: 'MARKET', quantity: intent.quantity, reduceOnly: intent.reduceOnly });
    const payload = result as { avgPrice?: string; price?: string; orderId?: string | number };
    const price = Number(payload?.avgPrice ?? payload?.price ?? intent.referencePrice ?? await this.markPrice(intent.symbol));
    const fill: Fill = { orderId: String(payload?.orderId ?? `LIVE-${Date.now()}`), symbol: intent.symbol, side: intent.side, quantity: intent.quantity, price, fee: 0, settlementAsset: this.market === 'COIN_M' ? 'COIN' : 'USDT', timestamp: Date.now(), mode: this.mode, market: this.market };
    this.fills.push(fill);
    return fill;
  }
  async close(symbol: string, referencePrice?: number): Promise<Fill | null> {
    const positions = await this.engine.getPositionRisk(symbol);
    const active = positions.find((p) => Number(p.positionAmt) !== 0);
    if (!active) return null;
    return this.place({ symbol, side: Number(active.positionAmt) > 0 ? 'SHORT' : 'LONG', quantity: Math.abs(Number(active.positionAmt)), referencePrice, reduceOnly: true });
  }
  snapshot(): ExecutionSnapshot { return { mode: this.mode, market: this.market, balance: 0, positions: [], fills: [...this.fills] }; }
  async terminate(): Promise<void> { this.engine.terminate(); }
}

export interface RouterConfig { mode?: ExecutionMode; market?: FuturesMarket; initialBalance?: number; apiKey?: string; apiSecret?: string; testnet?: boolean; paperFeeRate?: number; paperSlippageBps?: number; }

export class ExecutionRouter implements ExecutionAdapter {
  readonly mode: ExecutionMode;
  readonly market: FuturesMarket;
  private readonly adapter: ExecutionAdapter;
  constructor(config: RouterConfig = {}) {
    this.mode = (config.mode ?? process.env.EXECUTION_MODE ?? 'PAPER').toUpperCase() as ExecutionMode;
    this.market = (config.market ?? process.env.FUTURES_MARKET ?? 'COIN_M').toUpperCase() as FuturesMarket;
    if (!['TEST', 'PAPER', 'LIVE'].includes(this.mode)) throw new Error(`Unsupported EXECUTION_MODE=${this.mode}`);
    if (!['COIN_M', 'USDT_M'].includes(this.market)) throw new Error(`Unsupported FUTURES_MARKET=${this.market}`);
    if (this.mode === 'TEST') this.adapter = new TestExecutionAdapter({ market: this.market, initialBalance: config.initialBalance });
    else if (this.mode === 'PAPER') this.adapter = new PaperExecutionAdapter({ market: this.market, initialBalance: config.initialBalance, feeRate: config.paperFeeRate, slippageBps: config.paperSlippageBps });
    else {
      if (process.env.LIVE_ARMED !== '1') throw new Error('LIVE requires LIVE_ARMED=1');
      const apiKey = config.apiKey ?? process.env.BINANCE_API_KEY ?? '';
      const apiSecret = config.apiSecret ?? process.env.BINANCE_API_SECRET ?? process.env.BINANCE_SECRET ?? '';
      if (!apiKey || !apiSecret) throw new Error('LIVE requires Binance credentials from environment');
      this.adapter = new LiveExecutionAdapter({ apiKey, apiSecret, market: this.market, testnet: config.testnet });
    }
  }
  initialize(): Promise<void> { return this.adapter.initialize(); }
  place(intent: OrderIntent): Promise<Fill> { return this.adapter.place(intent); }
  close(symbol: string, referencePrice?: number): Promise<Fill | null> { return this.adapter.close(symbol, referencePrice); }
  markPrice(symbol: string): Promise<number> { return this.adapter.markPrice(symbol); }
  snapshot(): ExecutionSnapshot { return this.adapter.snapshot(); }
  terminate(): Promise<void> { return this.adapter.terminate(); }
  get testAdapter(): TestExecutionAdapter | undefined { return this.adapter instanceof TestExecutionAdapter ? this.adapter : undefined; }
}
