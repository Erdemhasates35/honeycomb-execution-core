import { mean, pearsonCorrelation, standardDeviation, assertPositive } from "./math.js";

export interface CorrelationRelativeValueSignal {
  side: "LONG_LEFT_SHORT_RIGHT" | "SHORT_LEFT_LONG_RIGHT" | "FLAT";
  correlation: number;
  hedgeRatio: number;
  spreadZScore: number;
  reasonCode: string;
}

function returns(prices:number[]):number[]{
  if(prices.length<4||prices.some(price=>!Number.isFinite(price)||price<=0))throw new Error("Relative value prices are invalid");
  return prices.slice(1).map((price,index)=>Math.log(price/prices[index]));
}

export function evaluateCorrelationRelativeValue(input:{
  leftPrices:number[];
  rightPrices:number[];
  minCorrelation:number;
  entryZScore:number;
}):CorrelationRelativeValueSignal{
  const leftReturns=returns(input.leftPrices);
  const rightReturns=returns(input.rightPrices);
  if(leftReturns.length!==rightReturns.length)throw new Error("Relative value series are misaligned");
  const correlation=pearsonCorrelation(leftReturns,rightReturns);
  if(Math.abs(correlation)<input.minCorrelation)return{side:"FLAT",correlation,hedgeRatio:0,spreadZScore:0,reasonCode:"correlation_below_threshold"};
  const rightMean=mean(rightReturns);
  const leftMean=mean(leftReturns);
  const covariance=leftReturns.reduce((sum,value,index)=>sum+(value-leftMean)*(rightReturns[index]-rightMean),0)/(rightReturns.length-1);
  const rightVariance=standardDeviation(rightReturns)**2;
  if(rightVariance<=0)throw new Error("Relative value hedge variance is zero");
  const hedgeRatio=covariance/rightVariance;
  const spread=input.leftPrices.slice(1).map((price,index)=>Math.log(price)-hedgeRatio*Math.log(input.rightPrices[index+1]));
  const spreadMean=mean(spread);
  const spreadStd=standardDeviation(spread);
  if(spreadStd<=0)return{side:"FLAT",correlation,hedgeRatio,spreadZScore:0,reasonCode:"spread_variance_is_zero"};
  const spreadZScore=(spread[spread.length-1]-spreadMean)/spreadStd;
  const side=spreadZScore>=input.entryZScore?"SHORT_LEFT_LONG_RIGHT":spreadZScore<=-input.entryZScore?"LONG_LEFT_SHORT_RIGHT":"FLAT";
  return{side,correlation,hedgeRatio,spreadZScore,reasonCode:side==="FLAT"?"spread_inside_entry_band":"correlated_spread_deviation"};
}
