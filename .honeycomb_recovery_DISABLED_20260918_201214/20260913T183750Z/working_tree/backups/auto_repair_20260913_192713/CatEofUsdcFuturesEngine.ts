import { EventEmitter } from 'events';
import * as crypto from 'crypto';

// --- SABİTLER VE ALPHA HASSASİYET PARAMETRELERİ ---
const FINE_STRUCTURE_ALPHA = 0.00729735256;
const MAX_LEVERAGE = 75;
const MAX_MARGIN_PER_TRADE_PCT = 0.20; // İşlem başına max %20 marjin
const TOTAL_CAPITAL_UTILIZATION_PCT = 1.00; // Maksimum sermaye kullanımı
const TECHNICAL_INDICATOR_COUNT = 15;

export interface MarketMetrics {
  symbol: string;
  price: number;
  bid: number;
  ask: number;
  volume24h: number;
  ema9: number;
  ema21: number;
  ema50: number;
  ema200: number;
  vwap: number;
  rsi14: number;
  macdHist: number;
  bbUpper: number;
  bbLower: number;
  atr14: number;
  supertrendSignal: 'BUY' | 'SELL';
  obir: number; // Orderbook Imbalance Ratio (-1.0 to 1.0)
  vfi: number; // Volume Force Index
  stochRsiK: number;
  keltnerUpper: number;
  obvDelta: number;
  pivotSupport: number;
  pivotResistance: number;
}

export interface PositionState {
  symbol: string;
  side: 'LONG' | 'SHORT' | 'NONE';
  entryPrice: number;
  size: number;
  marginUsed: number;
  leverage: number;
  unrealizedPnL: number;
  unrealizedPnLPct: number;
  entryTimestamp: number;
}

export class CatEofUsdcFuturesEngine extends EventEmitter {
  private apiSecret: string;
  private apiKey: string;
  private isLiveMode: boolean = true;
  private currentPosition: PositionState;
  private accountBalanceUSDC: number = 0;

  constructor(apiKey: string, apiSecret: string) {
    super();
    this.apiKey = apiKey;
    this.apiSecret = apiSecret;
    this.currentPosition = {
      symbol: 'SOLUSDC',
      side: 'NONE',
      entryPrice: 0,
      size: 0,
      marginUsed: 0,
      leverage: MAX_LEVERAGE,
      unrealizedPnL: 0,
      unrealizedPnLPct: 0,
      entryTimestamp: 0
    };
  }

  /**
   * 15 İndikatörlü Konsensüs Sinyal Motoru
   * -1.0 (Güçlü SHORT) ile +1.0 (Güçlü LONG) arasında skor üretir.
   */
  public calculateSignalConsensus(m: MarketMetrics): number {
    let score = 0;

    // 1-4: EMA Hizalama Mantığı
    if (m.price > m.ema9 && m.ema9 > m.ema21) score += 0.10;
    if (m.ema21 > m.ema50 && m.ema50 > m.ema200) score += 0.10;
    if (m.price < m.ema9 && m.ema9 < m.ema21) score -= 0.10;
    if (m.ema21 < m.ema50 && m.ema50 < m.ema200) score -= 0.10;

    // 5: VWAP Desteği
    if (m.price > m.vwap) score += 0.08; else score -= 0.08;

    // 6: RSI Diverjans ve Seviye Kontrolü
    if (m.rsi14 > 50 && m.rsi14 < 70) score += 0.07;
    else if (m.rsi14 < 50 && m.rsi14 > 30) score -= 0.07;

    // 7: MACD Histogram İvmesi
    if (m.macdHist > 0) score += 0.08; else score -= 0.08;

    // 8: Bollinger Bant Konumu
    if (m.price > m.bbUpper) score += 0.05; // Trend kırılımı
    if (m.price < m.bbLower) score -= 0.05;

    // 9: ATR Volatilite Kanalı Sıkışması
    const bbWidth = (m.bbUpper - m.bbLower) / m.price;
    if (bbWidth > m.atr14 / m.price) score *= 1.05; // Volatilite artışı çarpanı

    // 10: Supertrend Trend Sinyali
    if (m.supertrendSignal === 'BUY') score += 0.12; else score -= 0.12;

    // 11: Derinlik Dengesizliği (Orderbook Imbalance - OBIR)
    score += m.obir * 0.15;

    // 12: Volume Force Index (VFI)
    if (m.vfi > 0) score += 0.05; else score -= 0.05;

    // 13: Stochastic RSI K/D Kesişimi
    if (m.stochRsiK > 80) score -= 0.04;
    else if (m.stochRsiK < 20) score += 0.04;

    // 14: Keltner Kanalları Kırılımı
    if (m.price > m.keltnerUpper) score += 0.05;

    // 15: OBV Delta Yönü
    if (m.obvDelta > 0) score += 0.06; else score -= 0.06;

    // Alpha Hassasiyet Sönümlemesi Entegrasyonu
    return Math.max(-1.0, Math.min(1.0, score * (1 + FINE_STRUCTURE_ALPHA)));
  }

  /**
   * Erken Flip Düzeltme ve Direnç/Destek Bazlı Pozisyon Yönetimi
   */
  public processTick(m: MarketMetrics, balance: number): void {
    this.accountBalanceUSDC = balance;
    const signal = this.calculateSignalConsensus(m);

    // Mevcut pozisyon PnL Güncellemesi
    if (this.currentPosition.side !== 'NONE') {
      const priceDiff = m.price - this.currentPosition.entryPrice;
      const direction = this.currentPosition.side === 'LONG' ? 1 : -1;
      
      this.currentPosition.unrealizedPnL = priceDiff * this.currentPosition.size * direction;
      this.currentPosition.unrealizedPnLPct = (this.currentPosition.unrealizedPnL / this.currentPosition.marginUsed) * 100;

      // MİKRO-PULLBACK KORUMA LOGIC:
      // Yanlış zararına kapatmayı önle! Sadece PnL eksiye düştü diye KAPATMA.
      // Kapatma kararı ancak Yapısal Destek/Direnç Kırılırsa VEYA Konsensüs tam tersi yönde > 0.65 olursa verilir.
      const isLongInvalidated = this.currentPosition.side === 'LONG' && (m.price < m.pivotSupport || signal < -0.65);
      const isShortInvalidated = this.currentPosition.side === 'SHORT' && (m.price > m.pivotResistance || signal > 0.65);

      if (isLongInvalidated || isShortInvalidated) {
        this.executeLimitClose(m, 'STRUCTURAL_INVALIDATION');
        return;
      }

      // Kâr Realizasyon Mantığı (%20 - %150 PnL Aralığında Büyüyen İzleyen Stop)
      if (this.currentPosition.unrealizedPnLPct >= 20.0) {
        if (this.currentPosition.side === 'LONG' && m.price < m.ema9) {
          this.executeLimitClose(m, 'TAKE_PROFIT_TRAILING_EMA9');
          return;
        }
        if (this.currentPosition.side === 'SHORT' && m.price > m.ema9) {
          this.executeLimitClose(m, 'TAKE_PROFIT_TRAILING_EMA9');
          return;
        }
      }
    }

    // Yeni Pozisyon Açma Mantığı (Eğer Pozisyon Yoksa)
    if (this.currentPosition.side === 'NONE') {
      const maxMarginForThisTrade = this.accountBalanceUSDC * MAX_MARGIN_PER_TRADE_PCT;
      const notionalSize = (maxMarginForThisTrade * MAX_LEVERAGE) / m.price;

      if (signal > 0.55) {
        this.executeLimitOrder('LONG', m.bid, notionalSize, maxMarginForThisTrade);
      } else if (signal < -0.55) {
        this.executeLimitOrder('SHORT', m.ask, notionalSize, maxMarginForThisTrade);
      }
    }
  }

  private executeLimitOrder(side: 'LONG' | 'SHORT', price: number, size: number, margin: number): void {
    // Canlı Mod için Post-Only Limit Order Algoritması (Sıfır Taker Komisyonu Hedefi)
    const orderPayload = {
      symbol: 'SOLUSDC',
      side: side === 'LONG' ? 'BUY' : 'SELL',
      type: 'LIMIT',
      timeInForce: 'GTX', // Post-Only: Taker ücreti ödemeyi engeller
      quantity: size.toFixed(3),
      price: price.toFixed(4),
      leverage: MAX_LEVERAGE,
      timestamp: Date.now()
    };

    // Atomik Pozisyon Güncellemesi
    this.currentPosition = {
      symbol: 'SOLUSDC',
      side: side,
      entryPrice: price,
      size: size,
      marginUsed: margin,
      leverage: MAX_LEVERAGE,
      unrealizedPnL: 0,
      unrealizedPnLPct: 0,
      entryTimestamp: Date.now()
    };

    this.emit('ORDER_EXECUTED', { mode: 'LIVE_USDC_75X', payload: orderPayload });
  }

  private executeLimitClose(m: MarketMetrics, reason: string): void {
    const closeSide = this.currentPosition.side === 'LONG' ? 'SELL' : 'BUY';
    const closePrice = closeSide === 'SELL' ? m.ask : m.bid;

    const closePayload = {
      symbol: this.currentPosition.symbol,
      side: closeSide,
      type: 'LIMIT',
      timeInForce: 'IOC', // Immediate or Cancel limit execution
      quantity: this.currentPosition.size.toFixed(3),
      price: closePrice.toFixed(4),
      reason: reason,
      realizedPnL: this.currentPosition.unrealizedPnL
    };

    this.currentPosition = {
      symbol: 'SOLUSDC',
      side: 'NONE',
      entryPrice: 0,
      size: 0,
      marginUsed: 0,
      leverage: MAX_LEVERAGE,
      unrealizedPnL: 0,
      unrealizedPnLPct: 0,
      entryTimestamp: 0
    };

    this.emit('POSITION_CLOSED', { mode: 'LIVE_USDC_75X', payload: closePayload });
  }
}
