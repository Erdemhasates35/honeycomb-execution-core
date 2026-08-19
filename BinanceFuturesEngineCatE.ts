import crypto from 'node:crypto';
import EventEmitter from 'node:events';
import WebSocket from 'ws';

export interface BinanceFuturesConfig {
  apiKey: string;
  apiSecret: string;
  testnet?: boolean;
  recvWindow?: number;
  maxRetries?: number;
}

export interface OrderRequest {
  symbol: string;
  side: 'BUY' | 'SELL';
  type: 'LIMIT' | 'MARKET' | 'STOP' | 'TAKE_PROFIT' | 'TRAILING_STOP_MARKET';
  quantity: string | number;
  price?: string | number;
  stopPrice?: string | number;
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

export class BinanceFuturesEngineCatE extends EventEmitter {
  private readonly apiKey: string;
  private readonly apiSecret: string;
  private readonly baseUrl: string;
  private readonly wsUrl: string;
  private readonly recvWindow: number;
  private readonly maxRetries: number;
  
  private timeOffset: number = 0;
  private listenKey: string | null = null;
  private userWs: WebSocket | null = null;
  private keepAliveInterval: NodeJS.Timeout | null = null;
  private syncTimeInterval: NodeJS.Timeout | null = null;
  
  private reconnectAttempts: number = 0;
  private isTerminated: boolean = false;
  private isConnecting: boolean = false;

  constructor(config: BinanceFuturesConfig) {
    super();
    if (!config.apiKey || !config.apiSecret) {
      throw new Error('Cat E Validation Error: API key and Secret are required.');
    }
    this.apiKey = config.apiKey;
    this.apiSecret = config.apiSecret;
    this.baseUrl = config.testnet
      ? 'https://testnet.binancefuture.com'
      : 'https://fapi.binance.com';
    this.wsUrl = config.testnet
      ? 'wss://stream.binancefuture.com/ws'
      : 'wss://fstream.binance.com/ws';
    this.recvWindow = config.recvWindow || 5000;
    this.maxRetries = config.maxRetries || 5;
  }

  public async initialize(): Promise<void> {
    this.isTerminated = false;
    await this.syncServerTime();
    
    // Periyodik saat senkronizasyonu (Her 1 saatte bir t_offset güncellemesi)
    this.syncTimeInterval = setInterval(() => {
      this.syncServerTime().catch((err) => this.emit('error', err));
    }, 3600000);

    await this.startUserDataStream();
  }

  public async syncServerTime(): Promise<void> {
    const start = Date.now();
    try {
      const response = await fetch(`${this.baseUrl}/fapi/v1/time`);
      if (!response.ok) {
        throw new Error(`HTTP Error ${response.status}: ${response.statusText}`);
      }
      const data = (await response.json()) as { serverTime: number };
      const end = Date.now();
      const latency = Math.floor((end - start) / 2);
      this.timeOffset = data.serverTime - (start + latency);
    } catch (error) {
      this.emit('error', new Error(`Time Sync Failure: ${(error as Error).message}`));
      throw error;
    }
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
    isSigned: boolean = false,
    retryCount: number = 0
  ): Promise<T> {
    try {
      const mergedParams: Record<string, any> = { ...params };

      if (isSigned) {
        mergedParams.timestamp = this.getTimestamp();
        mergedParams.recvWindow = this.recvWindow;
      }

      const keys = Object.keys(mergedParams).sort();
      const queryParts: string[] = [];
      
      for (const key of keys) {
        if (mergedParams[key] !== undefined && mergedParams[key] !== null) {
          queryParts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(mergedParams[key]))}`);
        }
      }

      let queryString = queryParts.join('&');

      if (isSigned) {
        const signature = this.generateSignature(queryString);
        queryString += `&signature=${signature}`;
      }

      const url =
        method === 'GET' || method === 'DELETE'
          ? `${this.baseUrl}${endpoint}${queryString ? `?${queryString}` : ''}`
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
        // HTTP 429 Rate Limit veya 418 IP Ban Tespiti
        if (res.status === 429 || res.status === 418) {
          this.emit('rateLimitExceeded', { status: res.status, body });
        }
        throw new Error(`Binance API [${res.status}]: ${JSON.stringify(body)}`);
      }

      return body as T;
    } catch (error) {
      if (retryCount < this.maxRetries) {
        const backoffDelay = Math.pow(2, retryCount) * 200 + Math.floor(Math.random() * 100);
        await new Promise((resolve) => setTimeout(resolve, backoffDelay));
        return this.request<T>(method, endpoint, params, isSigned, retryCount + 1);
      }
      throw error;
    }
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
    if (this.isTerminated || this.isConnecting) return;
    this.isConnecting = true;

    try {
      const res = await this.request<{ listenKey: string }>('POST', '/fapi/v1/listenKey', {}, false);
      this.listenKey = res.listenKey;
      
      this.cleanUpWebSocket();

      this.userWs = new WebSocket(`${this.wsUrl}/${this.listenKey}`);

      this.userWs.on('open', () => {
        this.isConnecting = false;
        this.reconnectAttempts = 0;
        this.emit('connected');

        if (this.keepAliveInterval) clearInterval(this.keepAliveInterval);
        this.keepAliveInterval = setInterval(() => {
          this.keepAliveUserDataStream().catch((err) => this.emit('error', err));
        }, 25 * 60 * 1000); // 25 dakikada bir güvenli tazeleme
      });

      this.userWs.on('message', (data: WebSocket.RawData) => {
        try {
          const parsed = JSON.parse(data.toString());
          const eventType = parsed.e;

          if (eventType === 'ORDER_TRADE_UPDATE') {
            this.emit('orderUpdate', parsed.o);
          } else if (eventType === 'ACCOUNT_UPDATE') {
            this.emit('accountUpdate', parsed.a);
          } else if (eventType === 'MARGIN_CALL') {
            this.emit('marginCall', parsed);
          } else {
            this.emit('rawEvent', parsed);
          }
        } catch (err) {
          this.emit('error', new Error(`WebSocket Message Parse Error: ${(err as Error).message}`));
        }
      });

      this.userWs.on('close', (code: number, reason: Buffer) => {
        this.isConnecting = false;
        this.emit('disconnected', { code, reason: reason.toString() });
        this.cleanUpKeepAlive();

        if (!this.isTerminated) {
          this.scheduleReconnect();
        }
      });

      this.userWs.on('error', (err) => {
        this.emit('error', err);
      });
    } catch (error) {
      this.isConnecting = false;
      this.emit('error', new Error(`DataStream Start Failed: ${(error as Error).message}`));
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.isTerminated) return;
    this.reconnectAttempts++;
    
    // Exponential Backoff + Full Jitter
    const baseDelay = 1000;
    const maxDelay = 30000;
    const delay = Math.min(maxDelay, baseDelay * Math.pow(2, this.reconnectAttempts)) + Math.floor(Math.random() * 1000);

    setTimeout(() => {
      this.startUserDataStream().catch((err) => this.emit('error', err));
    }, delay);
  }

  private async keepAliveUserDataStream(): Promise<void> {
    if (!this.listenKey || this.isTerminated) return;
    await this.request('PUT', '/fapi/v1/listenKey', {}, false);
  }

  private cleanUpWebSocket(): void {
    if (this.userWs) {
      this.userWs.removeAllListeners();
      if (this.userWs.readyState === WebSocket.OPEN || this.userWs.readyState === WebSocket.CONNECTING) {
        this.userWs.terminate();
      }
      this.userWs = null;
    }
  }

  private cleanUpKeepAlive(): void {
    if (this.keepAliveInterval) {
      clearInterval(this.keepAliveInterval);
      this.keepAliveInterval = null;
    }
  }

  public terminate(): void {
    this.isTerminated = true;
    this.cleanUpKeepAlive();
    if (this.syncTimeInterval) {
      clearInterval(this.syncTimeInterval);
      this.syncTimeInterval = null;
    }
    this.cleanUpWebSocket();
    this.removeAllListeners();
  }
}
