import assert from "node:assert/strict";
import test from "node:test";
import {
  evaluateBasisFundingVelocity,
  calculateAtr,
  evaluateAtrVolatility,
  buildVwapExecutionPlan,
  evaluateCorrelationRelativeValue,
  evaluateOrderBookLstm,
  calculateAvellanedaStoikovQuote,
  estimateHawkesToxicity,
  evaluateCrossVenueBasis,
  calculateFractionalKelly,
  reconcileExecutionEvents,
} from "../strategies/index.js";

test("basis funding velocity requires aligned carry and favorable acceleration",()=>{
  const input={symbol:"BTCUSDT",markPrice:101,indexPrice:100,lastFundingRate:0.001,fundingHistory:[{fundingTime:1,fundingRate:0.0005},{fundingTime:2,fundingRate:0.0007},{fundingTime:3,fundingRate:0.0009}],atr:1,estimatedRoundTripCostBps:2};
  const config={minFundingBps:5,minBasisBps:10,basisCaptureFraction:0.5,velocityLookaheadPeriods:1,minExpectedEdgeBps:5,stopAtr:1,targetAtr:2,minRewardRisk:1.5};
  const signal=evaluateBasisFundingVelocity(input,config);
  assert.equal(signal.side,"SHORT");
  assert.ok(signal.expectedEdgeBps>5);
  assert.ok(signal.stopLossPrice!>signal.entryPrice);
  assert.ok(signal.takeProfitPrice!<signal.entryPrice);
  const adverse=evaluateBasisFundingVelocity({...input,fundingHistory:[{fundingTime:1,fundingRate:0.001},{fundingTime:2,fundingRate:0.0008},{fundingTime:3,fundingRate:0.0006}]},config);
  assert.ok(adverse.expectedEdgeBps<signal.expectedEdgeBps);
});

test("ATR volatility computes true range and directional protection",()=>{
  const candles=Array.from({length:24},(_,index)=>{
    const close=100+index*0.5;
    return{openTime:index*300000,open:close-0.2,high:close+1,low:close-1,close,volume:100+index};
  });
  assert.ok(calculateAtr(candles,5)>0);
  const signal=evaluateAtrVolatility(candles,{atrPeriod:5,fastEmaPeriod:3,slowEmaPeriod:8,stopAtr:1.5,targetAtr:3,minTrendSeparationBps:1,maxVolatilityBps:500});
  assert.equal(signal.side,"LONG");
  assert.ok(signal.stopLossPrice!<signal.entryPrice);
  assert.ok(signal.takeProfitPrice!>signal.entryPrice);
});

test("VWAP plan respects participation and reconciles slice quantity",()=>{
  const trades=[{timestamp:1,price:100,quantity:4,buyerIsMaker:false},{timestamp:2,price:101,quantity:6,buyerIsMaker:true}];
  const buckets=[{startTime:1,endTime:2,volume:5},{startTime:2,endTime:3,volume:5}];
  const plan=buildVwapExecutionPlan({side:"BUY",targetQuantity:5,trades,buckets,maxParticipationRate:0.5,limitOffsetBps:1});
  assert.equal(plan.accepted,true);
  assert.ok(Math.abs(plan.slices.reduce((sum,slice)=>sum+slice.quantity,0)-5)<1e-10);
  assert.ok(plan.slices[0].limitPrice<plan.vwap);
  const rejected=buildVwapExecutionPlan({side:"BUY",targetQuantity:8,trades,buckets,maxParticipationRate:0.5,limitOffsetBps:1});
  assert.equal(rejected.accepted,false);
});

test("correlation relative value identifies a spread dislocation",()=>{
  const right=[100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115];
  const left=right.map((price,index)=>price*Math.exp(index===right.length-1?0.08:0));
  const signal=evaluateCorrelationRelativeValue({leftPrices:left,rightPrices:right,minCorrelation:0.8,entryZScore:1});
  assert.ok(signal.correlation>0.8);
  assert.equal(signal.side,"SHORT_LEFT_LONG_RIGHT");
});

test("LSTM inference uses explicit validated weights and rejects malformed matrices",()=>{
  const weights={inputSize:4,hiddenSize:1,weights:Array.from({length:4},()=>Array(5).fill(0)),biases:[10,0,1,10],projection:[10],projectionBias:0};
  const snapshots=Array.from({length:4},(_,index)=>({timestamp:index+1,midPrice:100,bidDepth:120+index,askDepth:80,spreadBps:2,microprice:100.01,tradeImbalance:0.2}));
  const signal=evaluateOrderBookLstm({symbol:"BTCUSDT",snapshots,weights,modelId:"model-1",modelVersion:"1.0.0",markPrice:100,atr:1,probabilityThreshold:0.7,stopAtr:1,targetAtr:2,edgeBpsPerProbabilityPoint:100});
  assert.equal(signal.side,"LONG");
  assert.ok(signal.confidence>0.9);
  assert.throws(()=>evaluateOrderBookLstm({symbol:"BTCUSDT",snapshots,weights:{...weights,weights:[[1]]},modelId:"model-1",modelVersion:"1.0.0",markPrice:100,atr:1,probabilityThreshold:0.7,stopAtr:1,targetAtr:2,edgeBpsPerProbabilityPoint:100}),/dimensions/);
});

test("Avellaneda-Stoikov quotes remain ordered around inventory-adjusted reservation",()=>{
  const quote=calculateAvellanedaStoikovQuote({midPrice:100,volatility:0.02,inventory:5,riskAversion:0.1,liquidityParameter:1,horizon:1,tickSize:0.01});
  assert.ok(quote.bidPrice<quote.askPrice);
  assert.ok(quote.reservationPrice<100);
});

test("Hawkes toxicity gate pauses quoting under one-sided event intensity",()=>{
  const result=estimateHawkesToxicity([{timestamp:9900,side:"BUY"},{timestamp:9950,side:"BUY"},{timestamp:9990,side:"BUY"}],{now:10000,baselineIntensity:0.1,excitation:2,decayPerSecond:1,toxicityThreshold:0.4});
  assert.equal(result.dominantSide,"BUY");
  assert.equal(result.pauseMarketMaking,true);
});

test("cross-venue basis subtracts fees, slippage and latency before signaling",()=>{
  const left={venue:"binance",bid:100,ask:100.1,feeBps:1,slippageBps:1,latencyMs:10};
  const right={venue:"bitget",bid:101,ask:101.1,feeBps:1,slippageBps:1,latencyMs:20};
  const signal=evaluateCrossVenueBasis(left,right,{minNetEdgeBps:10,latencyPenaltyBpsPerSecond:0.1});
  assert.equal(signal.side,"BUY_LEFT_SELL_RIGHT");
  assert.ok(signal.netEdgeBps>10);
});

test("fractional Kelly allocation contracts under drawdown",()=>{
  const returns=[0.01,-0.005,0.02,0.015,-0.01,0.012,-0.004];
  const normal=calculateFractionalKelly(returns,{fraction:0.25,maxFraction:0.2,currentDrawdown:0.01,maxDrawdown:0.1,minimumSampleSize:5});
  const stressed=calculateFractionalKelly(returns,{fraction:0.25,maxFraction:0.2,currentDrawdown:0.08,maxDrawdown:0.1,minimumSampleSize:5});
  assert.ok(normal.allocatedFraction>stressed.allocatedFraction);
  assert.ok(stressed.allocatedFraction>=0);
});

test("event reconciliation compares unique exchange trades to cumulative quantity",()=>{
  const result=reconcileExecutionEvents({exchangeExecutedQuantity:3,trades:[{quantity:1,price:100,fee:0.04,realizedPnl:0,tradeId:"1"},{quantity:2,price:101,fee:0.08,realizedPnl:1,tradeId:"2"}],knownTradeIds:["1"],tolerance:1e-9});
  assert.equal(result.reconciled,true);
  assert.equal(result.executedQuantity,3);
  assert.equal(result.averagePrice,100.66666666666667);
  assert.deepEqual(result.missingTradeIds,["2"]);
});
