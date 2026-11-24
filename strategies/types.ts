export type SignalSide = "LONG" | "SHORT" | "FLAT";

export interface StrategySignal {
  strategyCode: string;
  side: SignalSide;
  confidence: number;
  expectedEdgeBps: number;
  entryPrice: number;
  stopLossPrice: number | null;
  takeProfitPrice: number | null;
  reasonCodes: string[];
  metadata: Record<string, number | string | boolean | null>;
}

export interface Candle {
  openTime: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OrderBookLevel {
  price: number;
  quantity: number;
}

export interface OrderBookSnapshot {
  observedAt: number;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
}

export interface TradePrint {
  timestamp: number;
  price: number;
  quantity: number;
  buyerIsMaker: boolean;
}
