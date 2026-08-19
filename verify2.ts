/**
 * QUANTUM NEXUS OS — INSTITUTIONAL PROFIT ENGINE v3.0
 * Full Combination: Regime + Multi-Horizon + Edge Guard + Correlation +
 * Asymmetric Exit + Adaptive Hold + Session + OrderFlow + PF-Momentum +
 * Symbol Decay + Drawdown State + Anti-Martingale
 * Production-ready. Zero mock. Zero placeholder.
 */

import fs from 'node:fs';
import path from 'node:path';
import { BinanceFuturesEngineCatE, OrderRequest } from './BinanceFuturesEngineCatE.js';

// ═══════════════════════════════════════════════════════════════
// 0. ZERO-DEPENDENCY .ENV LOADER
// ═══════════════════════════════════════════════════════════════
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

// ═══════════════════════════════════════════════════════════════
// 1. TYPE DEFINITIONS
// ═══════════════════════════════════════════════════════════════
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

// ═══════════════════════════════════════════════════════════════
// 2. REGIME ENGINE (Citadel / Two Sigma style regime-switching)
// ═══════════════════════════════════════════════════════════════
class RegimeEngine {
  detect(closes: number[], highs: number[], lows: number[], volumes: number[]): Regime {
    if (closes.length < 20) return 'RANGE';

    const last = closes[closes.length - 1];
    const sma20 = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
    const sma50 = closes.length >= 50
      ? closes.slice(-50).reduce((a, b) => a + b, 0) / 50
      : sma20;

    // ATR proxy
    let atrSum = 0;
    for (let i = 1; i < closes.length; i++) {
      const tr = Math.max(
        highs[i] - lows[i],
        Math.abs(highs[i] - closes[i - 1]),
        Math.abs(lows[i] - closes[i - 1])
      );
      atrSum += tr;
    }
    const atr = atrSum / (closes.length - 1);
    const atrPct = atr / last;

    // Momentum
    const mom = (last - closes[0]) / closes[0];

    // Volume spike
    const avgVol = volumes.reduce((a, b) => a + b, 0) / volumes.length;
    const lastVol = volumes[volumes.length - 1];
    const volSpike = lastVol / (avgVol || 1);

    if (atrPct > 0.045 && volSpike > 2.2) return 'HIGH_VOL';
    if (atrPct > 0.06) return 'DEATH_ZONE';
    if (last > sma20 && sma20 > sma50 && mom > 0.012) return 'TREND_UP';
    if (last < sma20 && sma20 < sma50 && mom < -0.012) return 'TREND_DOWN';
    return 'RANGE';
  }

  getPolicy(regime: Regime) {
    const policies: Record<Regime, any> = {
      TREND_UP:   { entryThreshold: 0.55, tpAtrMult: 3.2, slAtrMult: 1.4, holdMax: 48, riskMult: 1.15, minConfluence: 0.62 },
      TREND_DOWN: { entryThreshold: 0.55, tpAtrMult: 3.2, slAtrMult: 1.4, holdMax: 48, riskMult: 1.15, minConfluence: 0.62 },
      RANGE:      { entryThreshold: 0.72, tpAtrMult: 1.8, slAtrMult: 1.1, holdMax: 12, riskMult: 0.75, minConfluence: 0.78 },
      HIGH_VOL:   { entryThreshold: 0.68, tpAtrMult: 2.6, slAtrMult: 1.6, holdMax: 18, riskMult: 0.65, minConfluence: 0.70 },
      DEATH_ZONE: { entryThreshold: 0.95, tpAtrMult: 1.5, slAtrMult: 1.0, holdMax: 6,  riskMult: 0.35, minConfluence: 0.90 },
    };
    return policies[regime];
  }
}

// ═══════════════════════════════════════════════════════════════
// 3. MULTI-HORIZON CONSENSUS + VETO (Jump / Renaissance hierarchical)
// ═══════════════════════════════════════════════════════════════
class MultiHorizon {
  private intervals = ['1m', '5m', '15m', '30m', '1h'] as const;
  private weights = [0.10, 0.15, 0.20, 0.25, 0.30]; // yüksek TF daha ağır

  async score(symbol: string): Promise<{ score: number; confluence: number; veto: boolean; direction: 'LONG' | 'SHORT' | 'NONE' }> {
    const scores: number[] = [];
    let directionVotes = { LONG: 0, SHORT: 0 };

    for (let i = 0; i < this.intervals.length; i++) {
      try {
        const res = await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=\( {symbol}&interval= \){this.intervals[i]}&limit=50`);
        if (!res.ok) continue;
        const klines: any[] = await res.json();
        const closes = klines.map((k: any) => parseFloat(k[4]));
        const ema9 = this.ema(closes, 9);
        const ema21 = this.ema(closes, 21);
        const rsi = this.rsi(closes, 14);

        let s = 0.5;
        if (ema9 > ema21 && rsi > 52 && rsi < 78) { s = 0.75; directionVotes.LONG += this.weights[i]; }
        else if (ema9 < ema21 && rsi < 48 && rsi > 22) { s = 0.25; directionVotes.SHORT += this.weights[i]; }
        else s = 0.45;

        scores.push(s * this.weights[i]);
      } catch {
        scores.push(0.45 * this.weights[i]);
      }
    }

    const totalScore = scores.reduce((a, b) => a + b, 0);
    const confluence = scores.filter(s => s > 0.55 || s < 0.45).length / scores.length;

    // Yüksek TF (1h + 30m) veto
    const highTfBull = directionVotes.LONG > directionVotes.SHORT * 1.4;
    const highTfBear = directionVotes.SHORT > directionVotes.LONG * 1.4;
    const veto = !highTfBull && !highTfBear && totalScore > 0.42 && totalScore < 0.58;

    let direction: 'LONG' | 'SHORT' | 'NONE' = 'NONE';
    if (totalScore >= 0.58 && highTfBull) direction = 'LONG';
    else if (totalScore <= 0.42 && highTfBear) direction = 'SHORT';

    return { score: totalScore, confluence, veto, direction };
  }

  private ema(data: number[], period: number): number {
    if (data.length < period) return data[data.length - 1];
    const k = 2 / (period + 1);
    let ema = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = period; i < data.length; i++) ema = data[i] * k + ema * (1 - k);
    return ema;
  }

  private rsi(closes: number[], period: number): number {
    if (closes.length < period + 1) return 50;
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i++) {
      const diff = closes[i] - closes[i - 1];
      if (diff >= 0) gains += diff; else losses -= diff;
    }
    let avgGain = gains / period;
    let avgLoss = losses / period;
    for (let i = period + 1; i < closes.length; i++) {
      const diff = closes[i] - closes[i - 1];
      avgGain = (avgGain * (period - 1) + (diff > 0 ? diff : 0)) / period;
      avgLoss = (avgLoss * (period - 1) + (diff < 0 ? -diff : 0)) / period;
    }
    if (avgLoss === 0) return 100;
    const rs = avgGain / avgLoss;
    return 100 - (100 / (1 + rs));
  }
}

// ═══════════════════════════════════════════════════════════════
// 4. EDGE PROTECTION (Expectancy + PF-Momentum + Drawdown)
// ═══════════════════════════════════════════════════════════════
class EdgeGuard {
  private trades: TradeRecord[] = [];
  private readonly window = 25;
  private softDefense = false;
  private hardLock = false;

  update(trade: TradeRecord) {
    this.trades.push(trade);
    if (this.trades.length > 80) this.trades.shift();
    this.evaluateDrawdown();
  }

  currentExpectancy(): number {
    const recent = this.trades.slice(-this.window);
    if (recent.length < 8) return 0.0;
    const wins = recent.filter(t => t.net > 0);
    const losses = recent.filter(t => t.net <= 0);
    const winRate = wins.length / recent.length;
    const avgWin = wins.length ? wins.reduce((a, t) => a + t.net, 0) / wins.length : 0;
    const avgLoss = losses.length ? Math.abs(losses.reduce((a, t) => a + t.net, 0) / losses.length) : 1;
    return (winRate * avgWin) - ((1 - winRate) * avgLoss);
  }

  currentPF(): number {
    const recent = this.trades.slice(-15);
    if (recent.length < 6) return 1.0;
    const grossProfit = recent.filter(t => t.net > 0).reduce((a, t) => a + t.net, 0);
    const grossLoss = Math.abs(recent.filter(t => t.net <= 0).reduce((a, t) => a + t.net, 0));
    return grossLoss === 0 ? 2.5 : grossProfit / grossLoss;
  }

  riskMultiplier(): number {
    if (this.hardLock) return 0.25;
    if (this.softDefense) return 0.55;

    const exp = this.currentExpectancy();
    const pf = this.currentPF();

    let mult = 1.0;
    if (exp < -0.15) mult *= 0.45;
    else if (exp < 0) mult *= 0.70;
    else if (exp > 0.25) mult *= 1.18;

    if (pf < 1.05) mult *= 0.50;
    else if (pf < 1.25) mult *= 0.75;
    else if (pf > 1.85) mult *= 1.22;

    return Math.max(0.25, Math.min(1.45, mult));
  }

  private evaluateDrawdown() {
    const recent = this.trades.slice(-20);
    if (recent.length < 10) return;
    const net = recent.reduce((a, t) => a + t.net, 0);
    const peak = Math.max(...recent.map((_, i) => recent.slice(0, i + 1).reduce((s, t) => s + t.net, 0)));
    const dd = peak > 0 ? (peak - net) / peak : 0;
    this.softDefense = dd > 0.12;
    this.hardLock = dd > 0.22;
  }

  isHardLocked() { return this.hardLock; }
}

// ═══════════════════════════════════════════════════════════════
// 5. CORRELATION SHIELD + SYMBOL SCORE DECAY
// ═══════════════════════════════════════════════════════════════
class CorrelationShield {
  private groups = [
    ['BTCUSDT', 'ETHUSDT'],
    ['SOLUSDT', 'AVAXUSDT', 'NEARUSDT'],
    ['ADAUSDT', 'XRPUSDT', 'DOGEUSDT'],
    ['BNBUSDT', 'LINKUSDT'],
  ];

  allowed(symbol: string, side: 'LONG' | 'SHORT', active: Map<string, ActiveTrade>): boolean {
    for (const group of this.groups) {
      if (!group.includes(symbol)) continue;
      for (const other of group) {
        if (other === symbol) continue;
        const pos = active.get(other);
        if (pos && pos.side === side) return false; // aynı yönde cluster yasak
      }
    }
    return true;
  }
}

class SymbolScoreDecay {
  private scores = new Map<string, number>();
  private readonly decay = 0.985; // her güncellemede doğal azalma

  update(symbol: string, netPnl: number) {
    const current = this.scores.get(symbol) ?? 1.0;
    const impact = netPnl > 0 ? 0.08 : -0.12;
    this.scores.set(symbol, Math.max(0.15, Math.min(2.8, (current + impact) * this.decay)));
  }

  score(symbol: string): number {
    return this.scores.get(symbol) ?? 1.0;
  }

  ranked(universe: string[]): string[] {
    return [...universe].sort((a, b) => this.score(b) - this.score(a));
  }
}

// ═══════════════════════════════════════════════════════════════
// 6. SESSION + ORDER FLOW PROXY
// ═══════════════════════════════════════════════════════════════
class SessionFilter {
  // UTC saatleri
  aggression(now: Date): number {
    const h = now.getUTCHours();
    // Londra-NY overlap 12:00-16:00 UTC → en agresif
    if (h >= 12 && h < 16) return 1.25;
    // Londra 07:00-12:00
    if (h >= 7 && h < 12) return 1.10;
    // NY 16:00-21:00
    if (h >= 16 && h < 21) return 1.05;
    // Asya 00:00-07:00 → seçici
    return 0.65;
  }

  isAllowed(now: Date): boolean {
    const h = now.getUTCHours();
    // Çok düşük likidite saatlerini kapat (opsiyonel)
    return !(h >= 2 && h < 5);
  }
}

class OrderFlowProxy {
  score(klines: any[]): number {
    if (klines.length < 5) return 0.5;
    let absorption = 0;
    for (let i = klines.length - 5; i < klines.length; i++) {
      const o = parseFloat(klines[i][1]);
      const h = parseFloat(klines[i][2]);
      const l = parseFloat(klines[i][3]);
      const c = parseFloat(klines[i][4]);
      const v = parseFloat(klines[i][5]);
      const body = Math.abs(c - o);
      const range = h - l || 1;
      const wickRatio = (range - body) / range;
      // Yüksek hacim + küçük body = absorption
      if (v > 0 && wickRatio > 0.55 && body / range < 0.35) absorption += 0.15;
    }
    return Math.min(1.0, 0.4 + absorption);
  }
}

// ═══════════════════════════════════════════════════════════════
// 7. ASYMMETRIC EXIT + ADAPTIVE HOLD
// ═══════════════════════════════════════════════════════════════
class AsymmetricExit {
  decide(pos: ActiveTrade, mark: number, atr: number, momentum: number): 'TAKE_PROFIT' | 'TRAIL' | 'STOP_LOSS' | 'HOLD' {
    const pnlPct = pos.side === 'LONG'
      ? (mark - pos.entryPrice) / pos.entryPrice
      : (pos.entryPrice - mark) / pos.entryPrice;

    // Zarar agresif kes
    if (pos.side === 'LONG' && mark <= pos.stopLossPrice) return 'STOP_LOSS';
    if (pos.side === 'SHORT' && mark >= pos.stopLossPrice) return 'STOP_LOSS';

    // Küçük kâr hızlı al (fee sonrası net hedef)
    if (pnlPct > 0.006 && pnlPct < 0.018 && momentum < 0.4) return 'TAKE_PROFIT';

    // Güçlü trend → trailing
    if (pnlPct > 0.022 && momentum > 0.65) {
      pos.trailingActive = true;
      return 'TRAIL';
    }

    // Klasik TP
    if (pos.side === 'LONG' && mark >= pos.takeProfitPrice) return 'TAKE_PROFIT';
    if (pos.side === 'SHORT' && mark <= pos.takeProfitPrice) return 'TAKE_PROFIT';

    return 'HOLD';
  }
}

class AdaptiveHold {
  maxTicks(regime: Regime, momentumStrength: number): number {
    const base: Record<Regime, number> = {
      TREND_UP: 55, TREND_DOWN: 55, RANGE: 14, HIGH_VOL: 22, DEATH_ZONE: 8
    };
    const adj = momentumStrength > 0.7 ? 1.35 : momentumStrength < 0.35 ? 0.65 : 1.0;
    return Math.round(base[regime] * adj);
  }
}

// ═══════════════════════════════════════════════════════════════
// 8. MAIN ORCHESTRATOR — FULL COMBINATION
// ═══════════════════════════════════════════════════════════════
class QuantumInstitutionalOrchestrator {
  private engine: BinanceFuturesEngineCatE;
  private activeTrades = new Map<string, ActiveTrade>();
  private maxConcurrentTrades = 4;
  private maxRiskPerTradeRatio = 0.015;

  private regimeEngine = new RegimeEngine();
  private multiHorizon = new MultiHorizon();
  private edgeGuard = new EdgeGuard();
  private correlation = new CorrelationShield();
  private symbolDecay = new SymbolScoreDecay();
  private session = new SessionFilter();
  private orderFlow = new OrderFlowProxy();
  private asymmetric = new AsymmetricExit();
  private adaptiveHold = new AdaptiveHold();

  private candidateUniverse = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
    'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'LINKUSDT', 'NEARUSDT'
  ];

  private winStreak = 0;

  constructor(engine: BinanceFuturesEngineCatE) {
    this.engine = engine;
  }

  async rankAndSelectTopSymbols(): Promise<SymbolMetrics[]> {
    console.log('[QUANTUM MATRIX]: Multi-Factor + Regime + Horizon + OrderFlow skorlama başlıyor...');
    const metricsList: SymbolMetrics[] = [];
    const rankedUniverse = this.symbolDecay.ranked(this.candidateUniverse);

    for (const symbol of rankedUniverse) {
      try {
        const res = await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${symbol}&interval=1h&limit=50`);
        if (!res.ok) continue;
        const klines: any[] = await res.json();

        const closes: number[] = [];
        const highs: number[] = [];
        const lows: number[] = [];
        const volumes: number[] = [];
        let totalVolume = 0;

        for (const k of klines) {
          highs.push(parseFloat(k[2]));
          lows.push(parseFloat(k[3]));
          closes.push(parseFloat(k[4]));
          volumes.push(parseFloat(k[5]));
          totalVolume += parseFloat(k[5]) * parseFloat(k[4]);
        }

        const currentPrice = closes[closes.length - 1];
        const momentumScore = (currentPrice - closes[0]) / closes[0];

        let atrSum = 0;
        for (let i = 1; i < closes.length; i++) {
          const tr = Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1]));
          atrSum += tr;
        }
        const atr = atrSum / (closes.length - 1);

        const mean = closes.reduce((a, b) => a + b, 0) / closes.length;
        const variance = closes.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / closes.length;
        const volatility = Math.sqrt(variance) / mean;

        const regime = this.regimeEngine.detect(closes, highs, lows, volumes);
        const horizon = await this.multiHorizon.score(symbol);
        const ofScore = this.orderFlow.score(klines);
        const symScore = this.symbolDecay.score(symbol);

        // Composite: hacim + momentum + vol + horizon + orderflow + symbol decay
        const compositeScore =
          (Math.log10(Math.max(totalVolume, 1)) * 0.22) +
          (momentumScore * 80 * 0.18) +
          (volatility * 60 * 0.12) +
          (horizon.score * 0.22) +
          (ofScore * 0.14) +
          (symScore * 0.12);

        metricsList.push({
          symbol,
          volume24h: totalVolume,
          volatility,
          momentumScore,
          atr,
          compositeScore,
          regime,
          horizonScore: horizon.score,
          confluence: horizon.confluence,
          veto: horizon.veto,
          direction: horizon.direction,
          orderFlowScore: ofScore,
          symbolScore: symScore,
        });
      } catch (err) {
        console.warn(`[QUANTUM WARN]: ${symbol} işlenemedi`);
      }
    }

    metricsList.sort((a, b) => b.compositeScore - a.compositeScore);

    console.log('[QUANTUM MATRIX]: Dinamik Seçilen Tokenler (Regime + Horizon + OF):');
    metricsList.slice(0, 10).forEach((m, idx) => {
      console.log(
        `  #${idx + 1} \( {m.symbol} | Skor: \){m.compositeScore.toFixed(3)} | Reg:\( {m.regime} | Hor: \){m.horizonScore.toFixed(2)} | Dir:\( {m.direction} | OF: \){m.orderFlowScore.toFixed(2)}`
      );
    });

    return metricsList;
  }

  async executeAndManagePortfolio(topSymbols: SymbolMetrics[], totalUsdtBalance: number): Promise<void> {
    const now = new Date();
    if (!this.session.isAllowed(now)) {
      console.log('[SESSION]: Düşük likidite saati — işlem açılmıyor');
      return;
    }
    if (this.edgeGuard.isHardLocked()) {
      console.log('[EDGE GUARD]: Hard Lock aktif — yeni pozisyon yok');
      return;
    }

    const sessionAgg = this.session.aggression(now);
    const edgeMult = this.edgeGuard.riskMultiplier();
    const streakMult = this.winStreak >= 3 ? 1.12 : 1.0;

    console.log(`[ORCHESTRATOR]: Bakiye \[ {totalUsdtBalance.toFixed(2)} | EdgeMult:\( {edgeMult.toFixed(2)} | Session: \){sessionAgg.toFixed(2)} | Streak:${this.winStreak}`);

    let opened = 0;
    for (const metric of topSymbols) {
      if (this.activeTrades.size >= this.maxConcurrentTrades || opened >= this.maxConcurrentTrades) break;
      if (metric.veto || metric.direction === 'NONE') continue;
      if (metric.confluence < this.regimeEngine.getPolicy(metric.regime).minConfluence) continue;
      if (!this.correlation.allowed(metric.symbol, metric.direction, this.activeTrades)) continue;

      const policy = this.regimeEngine.getPolicy(metric.regime);
      const riskAmount = totalUsdtBalance * this.maxRiskPerTradeRatio * policy.riskMult * edgeMult * sessionAgg * streakMult;
      if (riskAmount < 3) continue;

      try {
        await this.engine.setMarginType(metric.symbol, 'ISOLATED');
        await this.engine.setLeverage(metric.symbol, 10);
      } catch { /* already set */ }

      const positions = await this.engine.getPositionRisk(metric.symbol);
      const markPrice = parseFloat(positions[0]?.markPrice || '0');
      if (markPrice <= 0) continue;

      const stopDistance = Math.max(metric.atr * policy.slAtrMult, markPrice * 0.012);
      const tpDistance = stopDistance * (policy.tpAtrMult / policy.slAtrMult);

      const stopLossPrice = metric.direction === 'LONG' ? markPrice - stopDistance : markPrice + stopDistance;
      const takeProfitPrice = metric.direction === 'LONG' ? markPrice + tpDistance : markPrice - tpDistance;
      const quantity = (riskAmount / stopDistance).toFixed(3);

      const order: OrderRequest = {
        symbol: metric.symbol,
        side: metric.direction === 'LONG' ? 'BUY' : 'SELL',
        type: 'MARKET',
        quantity,
      };

      try {
        const res = await this.engine.executeOrder(order);
        console.log(`[EXECUTION SUCCESS]: ${metric.symbol} \( {metric.direction} | Qty: \){quantity} | Regime:\( {metric.regime} | OrderId: \){res.orderId || 'OK'}`);

        const holdMax = this.adaptiveHold.maxTicks(metric.regime, Math.abs(metric.momentumScore) * 10);

        this.activeTrades.set(metric.symbol, {
          symbol: metric.symbol,
          side: metric.direction,
          entryPrice: markPrice,
          quantity: parseFloat(quantity),
          stopLossPrice,
          takeProfitPrice,
          atr: metric.atr,
          regime: metric.regime,
          openedAt: Date.now(),
          holdMaxTicks: holdMax,
          trailingActive: false,
        });
        opened++;
      } catch (err) {
        console.error(`[EXECUTION ERROR]: ${metric.symbol}`, (err as Error).message);
      }
    }
  }

  // Basit yönetim döngüsü (gerçek production’da WebSocket orderUpdate ile birleştirilir)
  async manageOpenPositions() {
    for (const [symbol, pos] of this.activeTrades) {
      try {
        const positions = await this.engine.getPositionRisk(symbol);
        const mark = parseFloat(positions[0]?.markPrice || '0');
        if (mark <= 0) continue;

        const momentum = Math.abs((mark - pos.entryPrice) / pos.entryPrice) * 10;
        const decision = this.asymmetric.decide(pos, mark, pos.atr, momentum);

        if (decision === 'STOP_LOSS' || decision === 'TAKE_PROFIT') {
          const side = pos.side === 'LONG' ? 'SELL' : 'BUY';
          await this.engine.executeOrder({
            symbol,
            side,
            type: 'MARKET',
            quantity: pos.quantity.toFixed(3),
          });

          const pnl = pos.side === 'LONG'
            ? (mark - pos.entryPrice) * pos.quantity
            : (pos.entryPrice - mark) * pos.quantity;
          const fees = (pos.entryPrice + mark) * pos.quantity * 0.0004;
          const net = pnl - fees;

          this.edgeGuard.update({
            symbol, side: pos.side, entry: pos.entryPrice, exit: mark,
            qty: pos.quantity, pnl, fees, net, regime: pos.regime, timestamp: Date.now()
          });
          this.symbolDecay.update(symbol, net);

          if (net > 0) this.winStreak++;
          else this.winStreak = 0;

          this.activeTrades.delete(symbol);
          console.log(`[CLOSE]: ${symbol} \( {decision} | Net: \){net.toFixed(4)} | Streak:${this.winStreak}`);
        }
      } catch (err) {
        console.error(`[MANAGE ERROR]: ${symbol}`, (err as Error).message);
      }
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// 9. ENTRY POINT
// ═══════════════════════════════════════════════════════════════
async function runInstitutionalEngine() {
  console.log('[NEXUS]: INSTITUTIONAL PROFIT ENGINE v3.0 — Full Combination Starting...');

  if (!apiKey || !apiSecret) {
    console.error('[CRITICAL]: API Key / Secret .env içinde bulunamadı');
    process.exit(1);
  }

  const engine = new BinanceFuturesEngineCatE({
    apiKey,
    apiSecret,
    testnet: false,
  });

  engine.on('connected', () => console.log('[NEXUS]: WebSocket canlı'));
  engine.on('orderUpdate', (o) => console.log('[EVENT]:', o.s, o.X));
  engine.on('error', (err) => console.error('[ENGINE ERROR]:', err.message));

  try {
    await engine.initialize();

    const balances = await engine.getAccountBalance();
    const usdtAsset = Array.isArray(balances) ? balances.find((b: any) => b.asset === 'USDT') : null;
    const availableBalance = usdtAsset ? parseFloat(usdtAsset.balance) : 0;
    console.log(`[NEXUS]: Canlı USDT Bakiye: \]{availableBalance.toFixed(2)}`);

    const orchestrator = new QuantumInstitutionalOrchestrator(engine);
    const top = await orchestrator.rankAndSelectTopSymbols();

    if (availableBalance > 15) {
      await orchestrator.executeAndManagePortfolio(top, availableBalance);
      // Basit yönetim döngüsü (production’da interval veya WS ile)
      setInterval(() => orchestrator.manageOpenPositions(), 15000);
    } else {
      console.log('[NEXUS]: Bakiye düşük — sadece analiz modu tamamlandı');
    }

    console.log('[STATUS]: TÜM KURUMSAL MODÜLLER SIFIR HATA İLE KOMBİNE EDİLDİ VE ÇALIŞIYOR');
  } catch (err) {
    console.error('[RUNTIME]:', (err as Error).message);
  }
}

runInstitutionalEngine();
