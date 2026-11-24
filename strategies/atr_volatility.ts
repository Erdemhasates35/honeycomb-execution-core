import { clamp, exponentialMovingAverage, assertPositive } from "./math.js";
import type { Candle, StrategySignal } from "./types.js";

export interface AtrVolatilityConfig {
  atrPeriod: number;
  fastEmaPeriod: number;
  slowEmaPeriod: number;
  stopAtr: number;
  targetAtr: number;
  minTrendSeparationBps: number;
  maxVolatilityBps: number;
}

export function calculateAtr(candles: Candle[], period = 14): number {
  if (!Number.isInteger(period) || period < 2 || candles.length < period+1) throw new Error("ATR requires period+1 valid candles");
  const ranges: number[] = [];
  for (let index=1;index<candles.length;index++) {
    const current=candles[index];
    const previous=candles[index-1];
    if (![current.high,current.low,current.close,previous.close].every(Number.isFinite) || current.high<current.low || current.close<=0 || previous.close<=0) throw new Error("ATR candle data is invalid");
    ranges.push(Math.max(current.high-current.low,Math.abs(current.high-previous.close),Math.abs(current.low-previous.close)));
  }
  return ranges.slice(-period).reduce((sum,value)=>sum+value,0)/period;
}

export function evaluateAtrVolatility(candles: Candle[], config: AtrVolatilityConfig): StrategySignal {
  if (![config.atrPeriod,config.fastEmaPeriod,config.slowEmaPeriod,config.stopAtr,config.targetAtr,config.minTrendSeparationBps,config.maxVolatilityBps].every(Number.isFinite) || !Number.isInteger(config.atrPeriod) || !Number.isInteger(config.fastEmaPeriod) || !Number.isInteger(config.slowEmaPeriod) || config.atrPeriod<2 || config.fastEmaPeriod<1 || config.fastEmaPeriod>=config.slowEmaPeriod || config.stopAtr<=0 || config.targetAtr<=0 || config.minTrendSeparationBps<0 || config.maxVolatilityBps<=0 || candles.length < Math.max(config.slowEmaPeriod,config.atrPeriod+1)) throw new Error("ATR strategy configuration or history is invalid");
  const closes=candles.map(candle=>candle.close);
  const close=closes[closes.length-1];
  assertPositive(close,"latestClose");
  const fast=exponentialMovingAverage(closes,config.fastEmaPeriod);
  const slow=exponentialMovingAverage(closes,config.slowEmaPeriod);
  const atr=calculateAtr(candles,config.atrPeriod);
  const volatilityBps=atr/close*10000;
  const trendSeparationBps=Math.abs(fast-slow)/close*10000;
  let side: "LONG"|"SHORT"|"FLAT"="FLAT";
  if (volatilityBps<=config.maxVolatilityBps && trendSeparationBps>=config.minTrendSeparationBps) {
    if (fast>slow && close>fast) side="LONG";
    if (fast<slow && close<fast) side="SHORT";
  }
  if (side==="FLAT") return {strategyCode:"atr_volatility",side,confidence:0,expectedEdgeBps:0,entryPrice:close,stopLossPrice:null,takeProfitPrice:null,reasonCodes:["trend_or_volatility_filter"],metadata:{atr,volatilityBps,trendSeparationBps,fastEma:fast,slowEma:slow}};
  const stopDistance=atr*config.stopAtr;
  const targetDistance=atr*config.targetAtr;
  const stopLossPrice=side==="LONG"?close-stopDistance:close+stopDistance;
  const takeProfitPrice=side==="LONG"?close+targetDistance:close-targetDistance;
  const confidence=clamp(trendSeparationBps/Math.max(config.minTrendSeparationBps*3,1),0,1);
  return {strategyCode:"atr_volatility",side,confidence,expectedEdgeBps:targetDistance/close*10000,entryPrice:close,stopLossPrice,takeProfitPrice,reasonCodes:["ema_trend_confirmed","atr_sized_protection"],metadata:{atr,volatilityBps,trendSeparationBps,fastEma:fast,slowEma:slow}};
}
