import { clamp, assertPositive } from "./math.js";
import type { StrategySignal } from "./types.js";

export interface LstmWeights {
  inputSize: number;
  hiddenSize: number;
  weights: number[][];
  biases: number[];
  projection: number[];
  projectionBias: number;
}

export interface OrderBookSequenceSnapshot {
  timestamp: number;
  midPrice: number;
  bidDepth: number;
  askDepth: number;
  spreadBps: number;
  microprice: number;
  tradeImbalance: number;
}

function sigmoid(value:number):number{
  return 1/(1+Math.exp(-Math.max(-40,Math.min(40,value))));
}

function validateWeights(weights:LstmWeights):void{
  const rows=weights.hiddenSize*4;
  if(!Number.isInteger(weights.inputSize)||weights.inputSize<1||!Number.isInteger(weights.hiddenSize)||weights.hiddenSize<1)throw new Error("LSTM dimensions are invalid");
  if(weights.weights.length!==rows||weights.biases.length!==rows||weights.projection.length!==weights.hiddenSize)throw new Error("LSTM parameter dimensions are invalid");
  if(weights.weights.some(row=>row.length!==weights.inputSize+weights.hiddenSize||row.some(value=>!Number.isFinite(value)))||weights.biases.some(value=>!Number.isFinite(value))||weights.projection.some(value=>!Number.isFinite(value))||!Number.isFinite(weights.projectionBias))throw new Error("LSTM parameters contain invalid values");
}

export function runLstmSequence(sequence:number[][],weights:LstmWeights):number{
  validateWeights(weights);
  if(sequence.length===0||sequence.some(row=>row.length!==weights.inputSize||row.some(value=>!Number.isFinite(value))))throw new Error("LSTM sequence is invalid");
  let hidden=Array(weights.hiddenSize).fill(0) as number[];
  let cell=Array(weights.hiddenSize).fill(0) as number[];
  for(const input of sequence){
    const joined=[...input,...hidden];
    const gates=weights.weights.map((row,index)=>row.reduce((sum,value,column)=>sum+value*joined[column],weights.biases[index]));
    const nextCell=Array(weights.hiddenSize).fill(0) as number[];
    const nextHidden=Array(weights.hiddenSize).fill(0) as number[];
    for(let index=0;index<weights.hiddenSize;index++){
      const inputGate=sigmoid(gates[index]);
      const forgetGate=sigmoid(gates[weights.hiddenSize+index]);
      const candidate=Math.tanh(gates[weights.hiddenSize*2+index]);
      const outputGate=sigmoid(gates[weights.hiddenSize*3+index]);
      nextCell[index]=forgetGate*cell[index]+inputGate*candidate;
      nextHidden[index]=outputGate*Math.tanh(nextCell[index]);
    }
    cell=nextCell;
    hidden=nextHidden;
  }
  const logit=hidden.reduce((sum,value,index)=>sum+value*weights.projection[index],weights.projectionBias);
  return sigmoid(logit);
}

export function evaluateOrderBookLstm(input:{
  symbol:string;
  snapshots:OrderBookSequenceSnapshot[];
  weights:LstmWeights;
  modelId:string;
  modelVersion:string;
  markPrice:number;
  atr:number;
  probabilityThreshold:number;
  stopAtr:number;
  targetAtr:number;
  edgeBpsPerProbabilityPoint:number;
}):StrategySignal{
  assertPositive(input.markPrice,"markPrice");
  assertPositive(input.atr,"atr");
  if(!input.modelId||!input.modelVersion||input.snapshots.length<2||input.probabilityThreshold<=0.5||input.probabilityThreshold>=1||input.stopAtr<=0||input.targetAtr<=0)throw new Error("Order-book LSTM inference configuration is invalid");
  const sequence=input.snapshots.map(snapshot=>{
    if(![snapshot.timestamp,snapshot.midPrice,snapshot.bidDepth,snapshot.askDepth,snapshot.spreadBps,snapshot.microprice,snapshot.tradeImbalance].every(Number.isFinite)||snapshot.midPrice<=0||snapshot.bidDepth<0||snapshot.askDepth<0||snapshot.bidDepth+snapshot.askDepth<=0)throw new Error("Order-book sequence contains invalid market data");
    return [
      (snapshot.bidDepth-snapshot.askDepth)/(snapshot.bidDepth+snapshot.askDepth),
      snapshot.spreadBps/100,
      (snapshot.microprice-snapshot.midPrice)/snapshot.midPrice*10000,
      snapshot.tradeImbalance,
    ];
  });
  if(input.weights.inputSize!==4)throw new Error("Order-book LSTM artifact input size must be four");
  const probability=runLstmSequence(sequence,input.weights);
  const side=probability>=input.probabilityThreshold?"LONG":probability<=1-input.probabilityThreshold?"SHORT":"FLAT";
  const expectedEdgeBps=(probability-0.5)*input.edgeBpsPerProbabilityPoint;
  if(side==="FLAT")return{strategyCode:"orderbook_lstm",side,confidence:Math.abs(probability-0.5)*2,expectedEdgeBps,entryPrice:input.markPrice,stopLossPrice:null,takeProfitPrice:null,reasonCodes:["model_probability_inside_neutral_band"],metadata:{symbol:input.symbol,modelId:input.modelId,modelVersion:input.modelVersion,probability}};
  const stopDistance=input.atr*input.stopAtr;
  const targetDistance=input.atr*input.targetAtr;
  const stopLossPrice=side==="LONG"?input.markPrice-stopDistance:input.markPrice+stopDistance;
  const takeProfitPrice=side==="LONG"?input.markPrice+targetDistance:input.markPrice-targetDistance;
  return{strategyCode:"orderbook_lstm",side,confidence:clamp(Math.abs(probability-0.5)*2,0,1),expectedEdgeBps:Math.abs(expectedEdgeBps),entryPrice:input.markPrice,stopLossPrice,takeProfitPrice,reasonCodes:["validated_lstm_inference","atr_protection_attached"],metadata:{symbol:input.symbol,modelId:input.modelId,modelVersion:input.modelVersion,probability}};
}
