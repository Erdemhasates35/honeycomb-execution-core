import crypto from 'node:crypto';
import EventEmitter from 'node:events';
import WebSocket from 'ws';

export interface BinanceFuturesConfig {
  apiKey: string;
  apiSecret: string;
  testnet?: boolean;
  recvWindow?: number;
}

export interface OrderRequest {
  symbol: string;
  side: 'BUY' | 'SELL';
  type: 'LIMIT' | 'MARKET' | 'STOP' | 'TAKE_PROFIT' | 'TRAILING_STOP_MARKET';
  quantity: number;
  price?: number;
  stopPrice?: number;
  timeInForce?: 'GTC' | 'IOC' | 'FOK' | 'GTX';
  reduceOnly?: boolean;
  closePosition?: boolean;
  workingType?: 'MARK_PRICE' | 'CONTRACT_PRICE';
}

export interface PositionRisk {
  symbol: string;
  positionAmt: string;
  entryPrice: string;
  markPrice: string;
  unRealizedProfit: string;
  liquidationPrice: string;
  leverage: string;
  marginType: string;
  isolatedMargin: string;
  positionSide: string;
}

export class BinanceFuturesEngine extends EventEmitter {
  private readonly apiKey: string;
  private readonly apiSecret: string;
  private readonly baseUrl: string;
  private readonly wsUrl: string;
  private readonly recvWindow: number;
  private timeOffset: number = 0;
  private listenKey: string | null = null;
  private userWs: WebSocket | null = null;
  private keepAliveInterval: NodeJS.Timeout | null = null;

  constructor(config: BinanceFuturesConfig) {
    super();
    this.apiKey = config.apiKey;
    this.apiSecret = config.apiSecret;
    this.baseUrl = config.testnet
      ? 'https://testnet.binancefuture.com'
      : 'https://fapi.binance.com';
    this.wsUrl = config.testnet
      ? 'wss://stream.binancefuture.com/ws'
      : 'wss://fstream.binance.com/ws';
    this.recvWindow = config.recvWindow || 5000;
  }

  public async initialize(): Promise<void> {
    await this.syncServerTime();
    await this.startUserDataStream();
  }

  private async syncServerTime(): Promise<void> {
    const start = Date.now();
    const response = await fetch(`${this.baseUrl}/fapi/v1/time`);
    if (!response.ok) {
      throw new Error(`Time sync failed: ${response.statusText}`);
    }
    const data = (await response.json()) as { serverTime: number };
    const end = Date.now();
    const latency = Math.floor((end - start) / 2);
    this.timeOffset = data.serverTime - (start + latency);
  }

  private getTimestamp(): number {
    return Date.now() + this.timeOffset;
  }

  private generateSignature(queryString: string): string {
    return crypto
      .createHmac('sha256', this.apiSecret)
      .update(queryString)
      .digest('hex');
  }

  private async request<T>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE',
    endpoint: string,
    params: Record<string, any> = {},
    isSigned: boolean = false
  ): Promise<T> {
    let queryString = '';
    const mergedParams = { ...params };

    if (isSigned) {
      mergedParams.timestamp = this.getTimestamp();
      mergedParams.recvWindow = this.recvWindow;
    }

    const keys = Object.keys(mergedParams).sort();
    const encodedParams = keys
      .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(mergedParams[k])}`)
      .join('&');

    queryString = encodedParams;

    if (isSigned) {
      const signature = this.generateSignature(queryString);
      queryString += `&signature=${signature}`;
    }

    const url =
      method === 'GET' || method === 'DELETE'
        ? `${this.baseUrl}${endpoint}?${queryString}`
        : `${this.baseUrl}${endpoint}`;

    const headers: Record<string, string> = {
      'X-MBX-APIKEY': this.apiKey,
      'Content-Type': 'application/x-www-form-urlencoded',
    };

    const options: RequestInit = { method, headers };

    if (method === 'POST' || method === 'PUT') {
      options.body = queryString;
    }

    const res = await fetch(url, options);
    const body = await res.json();

    if (!res.ok) {
      throw new Error(`Binance API Error [${res.status}]: ${JSON.stringify(body)}`);
    }

    return body as T;
  }

  public async setLeverage(symbol: string, leverage: number): Promise<{ symbol: string; leverage: number; maxNotionalValue: string }> {
    return this.request('POST', '/fapi/v1/leverage', { symbol, leverage }, true);
  }

  public async setMarginType(symbol: string, marginType: 'ISOLATED' | 'CROSSED'): Promise<{ code: number; msg: string }> {
    return this.request('POST', '/fapi/v1/marginType', { symbol, marginType }, true);
  }

  public async executeOrder(order: OrderRequest): Promise<any> {
    const params: Record<string, any> = {
      symbol: order.symbol,
      side: order.side,
      type: order.type,
      quantity: order.quantity,
    };

    if (order.price !== undefined) params.price = order.price;
    if (order.stopPrice !== undefined) params.stopPrice = order.stopPrice;
    if (order.timeInForce !== undefined) params.timeInForce = order.timeInForce;
    if (order.reduceOnly !== undefined) params.reduceOnly = order.reduceOnly;
    if (order.closePosition !== undefined) params.closePosition = order.closePosition;
    if (order.workingType !== undefined) params.workingType = order.workingType;

    return this.request('POST', '/fapi/v1/order', params, true);
  }

  public async cancelOrder(symbol: string, orderId: number): Promise<any> {
    return this.request('DELETE', '/fapi/v1/order', { symbol, orderId }, true);
  }

  public async getPositionRisk(symbol?: string): Promise<PositionRisk[]> {
    const params: Record<string, any> = {};
    if (symbol) params.symbol = symbol;
    return this.request('GET', '/fapi/v2/positionRisk', params, true);
  }

  public async getAccountBalance(): Promise<any> {
    return this.request('GET', '/fapi/v2/balance', {}, true);
  }

  private async startUserDataStream(): Promise<void> {
    const res = await this.request<{ listenKey: string }>('POST', '/fapi/v1/listenKey', {}, false);
    this.listenKey = res.listenKey;

    this.userWs = new WebSocket(`${this.wsUrl}/${this.listenKey}`);

    this.userWs.on('open', () => {
      this.emit('connected');
      this.keepAliveInterval = setInterval(() => {
        this.keepAliveUserDataStream().catch((err) => this.emit('error', err));
      }, 30 * 60 * 1000);
    });

    this.userWs.on('message', (data: WebSocket.RawData) => {
      try {
        const parsed = JSON.parse(data.toString());
        if (parsed.e === 'ORDER_TRADE_UPDATE') {
          this.emit('orderUpdate', parsed.o);
        } else if (parsed.e === 'ACCOUNT_UPDATE') {
          this.emit('accountUpdate', parsed.a);
        } else if (parsed.e === 'MARGIN_CALL') {
          this.emit('marginCall', parsed);
        }
      } catch (err) {
        this.emit('error', err);
      }
    });

    this.userWs.on('close', () => {
      this.emit('disconnected');
      if (this.keepAliveInterval) clearInterval(this.keepAliveInterval);
      setTimeout(() => this.startUserDataStream(), 5000);
    });

    this.userWs.on('error', (err) => {
      this.emit('error', err);
    });
  }

  private async keepAliveUserDataStream(): Promise<void> {
    if (!this.listenKey) return;
    await this.request('PUT', '/fapi/v1/listenKey', {}, false);
  }

  public terminate(): void {
    if (this.keepAliveInterval) clearInterval(this.keepAliveInterval);
    if (this.userWs) this.userWs.close();
  }
}
