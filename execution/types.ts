export type ExecutionMode = 'TEST' | 'PAPER' | 'LIVE';
export type FuturesMarket = 'COIN_M' | 'USDT_M';
export type OrderSide = 'LONG' | 'SHORT';

export interface OrderIntent {
  symbol: string;
  side: OrderSide;
  quantity: number;
  leverage?: number;
  referencePrice?: number;
  reduceOnly?: boolean;
  clientOrderId?: string;
}

export interface Fill {
  orderId: string;
  symbol: string;
  side: OrderSide;
  quantity: number;
  price: number;
  fee: number;
  settlementAsset: string;
  timestamp: number;
  mode: ExecutionMode;
  market: FuturesMarket;
}

export interface Position {
  symbol: string;
  side: OrderSide;
  quantity: number;
  entryPrice: number;
  leverage: number;
  realizedPnl: number;
  unrealizedPnl: number;
  feePaid: number;
  settlementAsset: string;
}

export interface ExecutionSnapshot {
  mode: ExecutionMode;
  market: FuturesMarket;
  balance: number;
  positions: Position[];
  fills: Fill[];
}

export interface ExecutionAdapter {
  readonly mode: ExecutionMode;
  readonly market: FuturesMarket;
  initialize(): Promise<void>;
  place(intent: OrderIntent): Promise<Fill>;
  close(symbol: string, referencePrice?: number): Promise<Fill | null>;
  markPrice(symbol: string): Promise<number>;
  snapshot(): ExecutionSnapshot;
  terminate(): Promise<void>;
}
