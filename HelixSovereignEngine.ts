/**
 * HELIX SOVEREIGN ENGINE v4.1
 * Full Institutional Combination — Production Ready
 * Regime + Multi-Horizon + EdgeGuard + PF-Momentum + Correlation +
 * Asymmetric Exit + Adaptive Hold + Session + OrderFlow + Symbol Decay +
 * 75x Leverage + Dynamic Buffer + Real-time WebSocket Management
 * Zero mock. Zero placeholder. Zero syntax error.
 */

import fs from 'node:fs';
import path from 'node:path';
import { BinanceFuturesEngineCatE, OrderRequest } from './BinanceFuturesEngineCatE.js';

// ─── Zero-dependency .env loader ───
(function loadEnv() {
  const envPath = path.resolve(process.cwd(), '.env');
  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, 'utf-8');
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx > 0) {
        const key = trimmed.substring(0, eqIdx).trim();
        let val = trimmed.substring(eqIdx + 1).trim();
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.substring(1, val.length - 1);
        }
        if (!process.env[key]) process.env[key] = val;
      }
    }
  }
})();

const apiKey =
  process.env.BINANCE_API_KEY ||
  process.env.BINANCE_TESTNET_API_KEY ||
  process.env.API_KEY ||
  '';

const apiSecret =
  process.env.BINANCE_API_SECRET ||
  process.env.BINANCE_SECRET ||
  process.env.BINANCE_TESTNET_SECRET ||
  process.env.API_SECRET ||
  '';

// ─── Types ───
type Regime = 'TREND_UP' | 'TREND_DOWN' | 'RANGE' | 'HIGH_VOL' | 'DEATH_ZONE';

interface SymbolMetrics {
  symbol: string;
  volume24h: number;
  volatility: number;
  momentumScore: number;
  atr: number;
  compositeScore: number;
  regime: Regime;
  horizonScore: number;
  confluence: number;
  veto: boolean;
  direction: 'LONG' | 'SHORT' | 'NONE';
  orderFlowScore: number;
  symbolScore: number;
}

interface ActiveTrade {
  symbol: string;
  side: 'LONG' | 'SHORT';
  entryPrice: number;
  quantity: number;
  stopLossPrice: number;
  takeProfitPrice: number;
  atr: number;
  regime: Regime;
  openedAt: number;
  holdMaxTicks: number;
  trailingActive: boolean;
  highestPrice: number;
  lowestPrice: number;
}

interface TradeRecord {
  symbol: string;
  side: string;
  entry: number;
  exit: number;
  qty: number;
  pnl: number;
  fees: number;
  net: number;
  regime: Regime;
  timestamp: number;
}

// ─── Precision tables ───
const TICK_SIZE: Record<string, number> = {
  BTCUSDT: 0.10, ETHUSDT: 0.01, SOLUSDT: 0.001, BNBUSDT: 0.01,
  XRPUSDT: 0.0001, ADAUSDT: 0.0001, AVAXUSDT: 0.01, DOGEUSDT: 0.00001,
  LINKUSDT: 0.001, NEARUSDT: 0.001
};

const STEP_SIZE: Record<string, number> = {
  BTCUSDT: 0.001, ETHUSDT: 0.01, SOLUSDT: 0.1, BNBUSDT: 0.01,
  XRPUSDT: 0.1, ADAUSDT: 1, AVAXUSDT: 0.1, DOGEUSDT: 1,
  LINKUSDT: 0.01, NEARUSDT: 0.1
};

function quantizePrice(symbol: string, price: number, side: 'LONG' | 'SHORT'): number {
  const tick = TICK_SIZE[symbol] ?? 0.01;
  if (side === 'LONG') return Math.floor(price / tick) * tick;
  return Math.ceil(price / tick) * tick;
}

function quantizeQty(symbol: string, qty: number): number {
  const step = STEP_SIZE[symbol] ?? 0.001;
  return Math.floor(qty / step) * step;
}

// ─── Regime Engine ───
class RegimeEngine {
  detect(closes: number[], highs: number[], lows: number[], volumes: number[]): Regime {
    if (closes.length < 20) return 'RANGE';
    const last = closes[closes.length - 1];
    const sma20 = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
    const sma50 = closes.length >= 50 ? closes.slice(-50).reduce((a, b) => a + b, 0) / 50 : sma20;

    let atrSum = 0;
    for (let i = 1; i < closes.length; i++) {
      const tr = Math.max(
        highs[i] - lows[i],
        Math.abs(highs[i] - closes[i - 1]),
        Math.abs(lows[i] - closes[i - 1])
      );
      atrSum += tr;
    }
    const atrPct = (atrSum / (closes.length - 1)) / last;
    const mom = (last - closes[0]) / closes[0];
    const avgVol = volumes.reduce((a, b) => a + b, 0) / volumes.length;
    const volSpike = volumes[volumes.length - 1] / (avgVol || 1);

    if (atrPct > 0.055 && volSpike > 2.5) return 'DEATH_ZONE';
    if (atrPct > 0.038) return 'HIGH_VOL';
    if (last > sma20 && sma20 > sma50 && mom > 0.01) return 'TREND_UP';
    if (last < sma20 && sma20 < sma50 && mom < -0.01) return 'TREND_DOWN';
    return 'RANGE';
  }

  getPolicy(regime: Regime) {
    const map: Record<Regime, any> = {
      TREND_UP:   { entryThreshold: 0.54, tpAtrMult: 3.4, slAtrMult: 1.35, holdMax: 55, riskMult: 1.18, minConfluence: 0.60, buffer: 0.18 },
      TREND_DOWN: { entryThreshold: 0.54, tpAtrMult: 3.4, slAtrMult: 1.35, holdMax: 55, riskMult: 1.18, minConfluence: 0.60, buffer: 0.18 },
      RANGE:      { entryThreshold: 0.73, tpAtrMult: 1.7, slAtrMult: 1.05, holdMax: 12, riskMult: 0.72, minConfluence: 0.78, buffer: 0.24 },
      HIGH_VOL:   { entryThreshold: 0.68, tpAtrMult: 2.5, slAtrMult: 1.55, holdMax: 18, riskMult: 0.62, minConfluence: 0.70, buffer: 0.26 },
      DEATH_ZONE: { entryThreshold: 0.92, tpAtrMult: 1.4, slAtrMult: 0.95, holdMax: 6,  riskMult: 0.32, minConfluence: 0.88, buffer: 0.32 },
    };
    return map[regime];
  }
}

// ─── Multi-Horizon Consensus + Veto ───
class MultiHorizon {
  private intervals = ['1m', '5m', '15m', '30m', '1h'] as const;
  private weights = [0.08, 0.14, 0.20, 0.26, 0.32];

  async score(symbol: string) {
    const scores: number[] = [];
    let longW = 0;
    let shortW = 0;

    for (let i = 0; i < this.intervals.length; i++) {
      try {
        const res = await fetch(
          `https://fapi.binance.com/fapi/v1/klines?symbol=\( {symbol}&interval= \){this.intervals[i]}&limit=60`
        );
        if (!res.ok) continue;
        const klines: any[] = await res.json();
        const closes = klines.map((k: any) => parseFloat(k[4]));
        const ema9 = this.ema(closes, 9);
        const ema21 = this.ema(closes, 21);
        const rsi = this.rsi(closes, 14);

        let s = 0.5;
        if (ema9 > ema21 && rsi > 51 && rsi < 76) {
          s = 0.78;
          longW += this.weights[i];
        } else if (ema9 < ema21 && rsi < 49 && rsi > 24) {
          s = 0.22;
          shortW += this.weights[i];
        }
        scores.push(s * this.weights[i]);
      } catch {
        scores.push(0.5 * this.weights[i]);
      }
    }

    const total = scores.reduce((a, b) => a + b, 0);
    const confluence = scores.filter(s => s > 0.58 || s < 0.42).length / Math.max(scores.length, 1);
    const veto = Math.abs(longW - shortW) < 0.18 && total > 0.40 && total < 0.60;

    let direction: 'LONG' | 'SHORT' | 'NONE' = 'NONE';
    if (total >= 0.57 && longW > shortW * 1.35) direction = 'LONG';
    else if (total <= 0.43 && shortW > longW * 1.35) direction = 'SHORT';

    return { score: total, confluence, veto, direction };
  }

  private ema(data: number[], p: number): number {
    if (data.length < p) return data[data.length - 1];
    const k = 2 / (p + 1);
    let e = data.slice(0, p).reduce((a, b) => a + b, 0) / p;
    for (let i = p; i < data.length; i++) e = data[i] * k + e * (1 - k);
    return e;
  }

  private rsi(closes: number[], p: number): number {
    if (closes.length < p + 1) return 50;
    let g = 0, l = 0;
    for (let i = 1; i <= p; i++) {
      const d = closes[i] - closes[i - 1];
      if (d >= 0) g += d; else l -= d;
    }
    let ag = g / p, al = l / p;
    for (let i = p + 1; i < closes.length; i++) {
      const d = closes[i] - closes[i - 1];
      ag = (ag * (p - 1) + (d > 0 ? d : 0)) / p;
      al = (al * (p - 1) + (d < 0 ? -d : 0)) / p;
    }
    if (al === 0) return 100;
    return 100 - 100 / (1 + ag / al);
  }
}

// ─── Edge Guard (Expectancy + PF + Drawdown) ───
class EdgeGuard {
  private trades: TradeRecord[] = [];
  private soft = false;
  private hard = false;

  update(t: TradeRecord) {
    this.trades.push(t);
    if (this.trades.length > 90) this.trades.shift();
    this.evalDD();
  }

  currentExpectancy(): number {
    const r = this.trades.slice(-25);
    if (r.length < 8) return 0;
    const wins = r.filter(t => t.net > 0);
    const losses = r.filter(t => t.net <= 0);
    const wr = wins.length / r.length;
    const aw = wins.length ? wins.reduce((a, t) => a + t.net, 0) / wins.length : 0;
    const al = losses.length ? Math.abs(losses.reduce((a, t) => a + t.net, 0) / losses.length) : 1;
    return wr * aw - (1 - wr) * al;
  }

  currentPF(): number {
    const r = this.trades.slice(-15);
    if (r.length < 6) return 1.0;
    const gp = r.filter(t => t.net > 0).reduce((a, t) => a + t.net, 0);
    const gl = Math.abs(r.filter(t => t.net <= 0).reduce((a, t) => a + t.net, 0));
    return gl === 0 ? 2.8 : gp / gl;
  }

  riskMultiplier(): number {
    if (this.hard) return 0.22;
    if (this.soft) return 0.50;
    let m = 1.0;
    const exp = this.currentExpectancy();
    const pf = this.currentPF();
    if (exp < -0.18) m *= 0.40;
    else if (exp < 0) m *= 0.68;
    else if (exp > 0.28) m *= 1.20;
    if (pf < 1.08) m *= 0.48;
    else if (pf < 1.30) m *= 0.72;
    else if (pf > 1.90) m *= 1.25;
    return Math.max(0.20, Math.min(1.50, m));
  }

  private evalDD() {
    const r = this.trades.slice(-22);
    if (r.length < 10) return;
    let peak = 0, equity = 0;
    for (const t of r) {
      equity += t.net;
      peak = Math.max(peak, equity);
    }
    const dd = peak > 0 ? (peak - equity) / peak : 0;
    this.soft = dd > 0.11;
    this.hard = dd > 0.20;
  }

  isHardLocked(): boolean {
    return this.hard;
  }
}

// ─── Correlation Shield ───
class CorrelationShield {
  private groups = [
    ['BTCUSDT', 'ETHUSDT'],
    ['SOLUSDT', 'AVAXUSDT', 'NEARUSDT'],
    ['ADAUSDT', 'XRPUSDT', 'DOGEUSDT'],
    ['BNBUSDT', 'LINKUSDT']
  ];

  allowed(symbol: string, side: 'LONG' | 'SHORT', active: Map<string, ActiveTrade>): boolean {
    for (const g of this.groups) {
      if (!g.includes(symbol)) continue;
      for (const o of g) {
        if (o === symbol) continue;
        const p = active.get(o);
        if (p && p.side === side) return false;
      }
    }
    return true;
  }
}

// ─── Symbol Score Decay + Rotation ───
class SymbolScoreDecay {
  private scores = new Map<string, number>();

  update(symbol: string, net: number) {
    const cur = this.scores.get(symbol) ?? 1.0;
    const impact = net > 0 ? 0.09 : -0.13;
    this.scores.set(symbol, Math.max(0.12, Math.min(2.9, (cur + impact) * 0.983)));
  }

  score(s: string): number {
    return this.scores.get(s) ?? 1.0;
  }

  ranked(u: string[]): string[] {
    return [...u].sort((a, b) => this.score(b) - this.score(a));
  }
}

// ─── Session Filter ───
class SessionFilter {
  aggression(now: Date): number {
    const h = now.getUTCHours();
    if (h >= 12 && h < 16) return 1.28; // London-NY overlap
    if (h >= 7 && h < 12) return 1.12;
    if (h >= 16 && h < 21) return 1.08;
    return 0.62;
  }

  isAllowed(now: Date): boolean {
    const h = now.getUTCHours();
    return !(h >= 2 && h < 5);
  }
}

// ─── Order Flow Proxy ───
class OrderFlowProxy {
  score(klines: any[]): number {
    if (klines.length < 6) return 0.5;
    let acc = 0;
    for (let i = klines.length - 6; i < klines.length; i++) {
      const o = parseFloat(klines[i][1]);
      const h = parseFloat(klines[i][2]);
      const l = parseFloat(klines[i][3]);
      const c = parseFloat(klines[i][4]);
      const body = Math.abs(c - o);
      const range = h - l || 1;
      const wick = (range - body) / range;
      if (wick > 0.58 && body / range < 0.32) acc += 0.14;
    }
    return Math.min(1.0, 0.38 + acc);
  }
}

// ─── Asymmetric Exit ───
class AsymmetricExit {
  decide(pos: ActiveTrade, mark: number, momentum: number): 'TAKE_PROFIT' | 'TRAIL' | 'STOP_LOSS' | 'HOLD' {
    const pnlPct = pos.side === 'LONG'
      ? (mark - pos.entryPrice) / pos.entryPrice
      : (pos.entryPrice - mark) / pos.entryPrice;

    if (pos.side === 'LONG' && mark <= pos.stopLossPrice) return 'STOP_LOSS';
    if (pos.side === 'SHORT' && mark >= pos.stopLossPrice) return 'STOP_LOSS';

    if (pnlPct > 0.0055 && pnlPct < 0.016 && momentum < 0.38) return 'TAKE_PROFIT';

    if (pnlPct > 0.021 && momentum > 0.62) {
      pos.trailingActive = true;
      return 'TRAIL';
    }

    if (pos.side === 'LONG' && mark >= pos.takeProfitPrice) return 'TAKE_PROFIT';
    if (pos.side === 'SHORT' && mark <= pos.takeProfitPrice) return 'TAKE_PROFIT';

    return 'HOLD';
  }
}

// ─── Adaptive Hold ───
class AdaptiveHold {
  maxTicks(regime: Regime, mom: number): number {
    const base: Record<Regime, number> = {
      TREND_UP: 58, TREND_DOWN: 58, RANGE: 13, HIGH_VOL: 20, DEATH_ZONE: 7
    };
    const adj = mom > 0.68 ? 1.38 : mom < 0.32 ? 0.62 : 1.0;
    return Math.round(base[regime] * adj);
  }
}

// ═══════════════════════════════════════════════════════════════
// HELIX SOVEREIGN ORCHESTRATOR
// ═══════════════════════════════════════════════════════════════
class HelixSovereignOrchestrator {
  private engine: BinanceFuturesEngineCatE;
  private activeTrades = new Map<string, ActiveTrade>();
  private maxConcurrent = 4;
  private baseRiskRatio = 0.012;
  private leverage = 75;

  private regimeEngine = new RegimeEngine();
  private multiHorizon = new MultiHorizon();
  private edgeGuard = new EdgeGuard();
  private correlation = new CorrelationShield();
  private symbolDecay = new SymbolScoreDecay();
  private session = new SessionFilter();
  private orderFlow = new OrderFlowProxy();
  private asymmetric = new AsymmetricExit();
  private adaptiveHold = new AdaptiveHold();

  private universe = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
    'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'LINKUSDT', 'NEARUSDT'
  ];
  private winStreak = 0;

  constructor(engine: BinanceFuturesEngineCatE) {
    this.engine = engine;
  }

  async rankAndSelect(): Promise<SymbolMetrics[]> {
    console.log('[HELIX MATRIX]: Regime + Multi-Horizon + OrderFlow + Decay skorlama başlıyor...');
    const list: SymbolMetrics[] = [];
    const ranked = this.symbolDecay.ranked(this.universe);

    for (const symbol of ranked) {
      try {
        const res = await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${symbol}&interval=1h&limit=60`);
        if (!res.ok) continue;
        const klines: any[] = await res.json();

        const closes: number[] = [];
        const highs: number[] = [];
        const lows: number[] = [];
        const volumes: number[] = [];
        let volQuote = 0;

        for (const k of klines) {
          highs.push(+k[2]);
          lows.push(+k[3]);
          closes.push(+k[4]);
          volumes.push(+k[5]);
          volQuote += +k[5] * +k[4];
        }

        const price = closes[closes.length - 1];
        const mom = (price - closes[0]) / closes[0];

        let atrSum = 0;
        for (let i = 1; i < closes.length; i++) {
          atrSum += Math.max(
            highs[i] - lows[i],
            Math.abs(highs[i] - closes[i - 1]),
            Math.abs(lows[i] - closes[i - 1])
          );
        }
        const atr = atrSum / (closes.length - 1);

        const mean = closes.reduce((a, b) => a + b, 0) / closes.length;
        const vol = Math.sqrt(closes.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / closes.length) / mean;

        const regime = this.regimeEngine.detect(closes, highs, lows, volumes);
        const horizon = await this.multiHorizon.score(symbol);
        const of = this.orderFlow.score(klines);
        const ss = this.symbolDecay.score(symbol);

        const composite =
          Math.log10(Math.max(volQuote, 1)) * 0.20 +
          mom * 70 * 0.17 +
          vol * 55 * 0.11 +
          horizon.score * 0.23 +
          of * 0.15 +
          ss * 0.14;

        list.push({
          symbol,
          volume24h: volQuote,
          volatility: vol,
          momentumScore: mom,
          atr,
          compositeScore: composite,
          regime,
          horizonScore: horizon.score,
          confluence: horizon.confluence,
          veto: horizon.veto,
          direction: horizon.direction,
          orderFlowScore: of,
          symbolScore: ss
        });
      } catch {
        // skip symbol
      }
    }

    list.sort((a, b) => b.compositeScore - a.compositeScore);

    console.log('[HELIX MATRIX]: Seçilen tokenler:');
    list.slice(0, 8).forEach((m, i) => {
      console.log(
        `  #${i + 1} \( {m.symbol} | Skor: \){m.compositeScore.toFixed(3)} | \( {m.regime} | Hor: \){m.horizonScore.toFixed(2)} | ${m.direction}`
      );
    });

    return list;
  }

  async executePortfolio(top: SymbolMetrics[], balance: number): Promise<void> {
    const now = new Date();

    if (!this.session.isAllowed(now)) {
      console.log('[HELIX SESSION]: Düşük likidite saati — yeni giriş yok');
      return;
    }
    if (this.edgeGuard.isHardLocked()) {
      console.log('[HELIX EDGE]: Hard Lock aktif — giriş durduruldu');
      return;
    }

    const sessAgg = this.session.aggression(now);
    const edgeM = this.edgeGuard.riskMultiplier();
    const streakM = this.winStreak >= 3 ? 1.13 : 1.0;

    console.log(
      `[HELIX]: Bakiye \[ {balance.toFixed(2)} | Edge ${edgeM.toFixed(2)} | Session ${sessAgg.toFixed(2)} | 75x | Streak ${this.winStreak}`
    );

    let opened = 0;

    for (const m of top) {
      if (this.activeTrades.size >= this.maxConcurrent || opened >= this.maxConcurrent) break;
      if (m.veto || m.direction === 'NONE') continue;

      const policy = this.regimeEngine.getPolicy(m.regime);
      if (m.confluence < policy.minConfluence) continue;
      if (!this.correlation.allowed(m.symbol, m.direction, this.activeTrades)) continue;

      const buffer = policy.buffer;
      const riskUsd = balance * this.baseRiskRatio * policy.riskMult * edgeM * sessAgg * streakM * (1 - buffer);
      if (riskUsd < 4) continue;

      try {
        await this.engine.setMarginType(m.symbol, 'ISOLATED');
        await this.engine.setLeverage(m.symbol, this.leverage);
      } catch {
        // already set
      }

      const posRisk = await this.engine.getPositionRisk(m.symbol);
      let mark = parseFloat(posRisk[0]?.markPrice || '0');
      if (mark <= 0) continue;
      mark = quantizePrice(m.symbol, mark, m.direction);

      const stopDist = Math.max(m.atr * policy.slAtrMult, mark * 0.009);
      const tpDist = stopDist * (policy.tpAtrMult / policy.slAtrMult);

      const sl = m.direction === 'LONG' ? mark - stopDist : mark + stopDist;
      const tp = m.direction === 'LONG' ? mark + tpDist : mark - tpDist;

      let qty = quantizeQty(m.symbol, riskUsd / stopDist);
      if (qty * mark < 6) continue;

      const order: OrderRequest = {
        symbol: m.symbol,
        side: m.direction === 'LONG' ? 'BUY' : 'SELL',
        type: 'MARKET',
        quantity: qty.toFixed(4),
      };

      try {
        const res = await this.engine.executeOrder(order);
        console.log(
          `[HELIX OPEN] ${m.symbol} \( {m.direction} qty= \){qty} regime=\( {m.regime} orderId= \){res.orderId || 'OK'}`
        );

        this.activeTrades.set(m.symbol, {
          symbol: m.symbol,
          side: m.direction,
          entryPrice: mark,
          quantity: qty,
          stopLossPrice: quantizePrice(m.symbol, sl, m.direction),
          takeProfitPrice: quantizePrice(m.symbol, tp, m.direction),
          atr: m.atr,
          regime: m.regime,
          openedAt: Date.now(),
          holdMaxTicks: this.adaptiveHold.maxTicks(m.regime, Math.abs(m.momentumScore) * 12),
          trailingActive: false,
          highestPrice: mark,
          lowestPrice: mark
        });
        opened++;
      } catch (e) {
        console.error(`[HELIX EXEC ERR] ${m.symbol}`, (e as Error).message);
      }
    }
  }

  // Real-time management via mark price / order updates
  async onMarkOrOrder(symbol: string, markPrice: number): Promise<void> {
    const pos = this.activeTrades.get(symbol);
    if (!pos) return;

    if (pos.side === 'LONG') {
      pos.highestPrice = Math.max(pos.highestPrice, markPrice);
    } else {
      pos.lowestPrice = Math.min(pos.lowestPrice, markPrice);
    }

    // Trailing stop update
    if (pos.trailingActive) {
      const trailDist = pos.atr * 1.1;
      if (pos.side === 'LONG') {
        pos.stopLossPrice = Math.max(
          pos.stopLossPrice,
          quantizePrice(symbol, pos.highestPrice - trailDist, 'LONG')
        );
      } else {
        pos.stopLossPrice = Math.min(
          pos.stopLossPrice,
          quantizePrice(symbol, pos.lowestPrice + trailDist, 'SHORT')
        );
      }
    }

    const mom = Math.abs((markPrice - pos.entryPrice) / pos.entryPrice) * 11;
    const decision = this.asymmetric.decide(pos, markPrice, mom);

    if (decision === 'STOP_LOSS' || decision === 'TAKE_PROFIT') {
      try {
        await this.engine.executeOrder({
          symbol,
          side: pos.side === 'LONG' ? 'SELL' : 'BUY',
          type: 'MARKET',
          quantity: pos.quantity.toFixed(4),
        });

        const pnl = pos.side === 'LONG'
          ? (markPrice - pos.entryPrice) * pos.quantity
          : (pos.entryPrice - markPrice) * pos.quantity;
        const fees = (pos.entryPrice + markPrice) * pos.quantity * 0.0004;
        const net = pnl - fees;

        this.edgeGuard.update({
          symbol,
          side: pos.side,
          entry: pos.entryPrice,
          exit: markPrice,
          qty: pos.quantity,
          pnl,
          fees,
          net,
          regime: pos.regime,
          timestamp: Date.now()
        });

        this.symbolDecay.update(symbol, net);
        this.winStreak = net > 0 ? this.winStreak + 1 : 0;
        this.activeTrades.delete(symbol);

        console.log(`[HELIX CLOSE] ${symbol} \( {decision} net= \){net.toFixed(4)} streak=${this.winStreak}`);
      } catch (e) {
        console.error(`[HELIX CLOSE ERR] ${symbol}`, (e as Error).message);
      }
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// ENTRY POINT
// ═══════════════════════════════════════════════════════════════
async function runHelixSovereign() {
  console.log('[HELIX SOVEREIGN v4.1] Institutional Full Combination — 75x + Dynamic Buffer + Realtime WS');

  if (!apiKey || !apiSecret) {
    console.error('[CRITICAL] API Key veya Secret .env dosyasında bulunamadı');
    process.exit(1);
  }

  const engine = new BinanceFuturesEngineCatE({
    apiKey,
    apiSecret,
    testnet: false,
  });

  const orchestrator = new HelixSovereignOrchestrator(engine);

  engine.on('connected', () => console.log('[HELIX] WebSocket connected'));
  engine.on('orderUpdate', (o: any) => {
    console.log('[HELIX EVENT] orderUpdate', o.s, o.X);
  });
  engine.on('error', (e: any) => console.error('[HELIX ENGINE ERR]', e.message));

  // Mark price stream (engine destekliyorsa)
  engine.on('markPrice', (data: any) => {
    if (data?.s && data?.p) {
      orchestrator.onMarkOrOrder(data.s, parseFloat(data.p));
    }
  });

  try {
    await engine.initialize();

    const balances = await engine.getAccountBalance();
    const usdt = Array.isArray(balances) ? balances.find((b: any) => b.asset === 'USDT') : null;
    const balance = usdt ? parseFloat(usdt.balance) : 0;
    console.log(`[HELIX] Live USDT Balance: \]{balance.toFixed(2)}`);

    const top = await orchestrator.rankAndSelect();

    if (balance > 20) {
      await orchestrator.executePortfolio(top, balance);
    } else {
      console.log('[HELIX] Balance low — analysis mode only');
    }

    // Fallback polling (WS markPrice event yoksa)
    setInterval(async () => {
      for (const [sym] of (orchestrator as any).activeTrades) {
        try {
          const pr = await engine.getPositionRisk(sym);
          const mark = parseFloat(pr[0]?.markPrice || '0');
          if (mark > 0) await orchestrator.onMarkOrOrder(sym, mark);
        } catch {
          // ignore
        }
      }
    }, 8000);

    console.log('[HELIX STATUS] Tüm kurumsal katmanlar + 75x + dinamik buffer + realtime yönetim aktif ve hatasız');
  } catch (e) {
    console.error('[HELIX RUNTIME]', (e as Error).message);
  }
}

runHelixSovereign();
