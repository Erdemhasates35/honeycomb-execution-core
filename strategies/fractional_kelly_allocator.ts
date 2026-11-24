import { mean, variance, clamp } from "./math.js";

export interface KellyAllocation {
  rawKellyFraction: number;
  allocatedFraction: number;
  expectedReturn: number;
  variance: number;
  drawdownScale: number;
}

export function calculateFractionalKelly(returns:number[],input:{fraction:number;maxFraction:number;currentDrawdown:number;maxDrawdown:number;minimumSampleSize:number}):KellyAllocation{
  if(returns.length<input.minimumSampleSize||returns.some(value=>!Number.isFinite(value)))throw new Error("Kelly allocator requires a sufficient finite return sample");
  if(input.fraction<=0||input.fraction>1||input.maxFraction<=0||input.maxFraction>1||input.maxDrawdown<=0||input.currentDrawdown<0||input.minimumSampleSize<2)throw new Error("Kelly allocation policy is invalid");
  const expectedReturn=mean(returns);
  const returnVariance=variance(returns);
  if(returnVariance<=0)throw new Error("Kelly return variance must be positive");
  const rawKellyFraction=expectedReturn/returnVariance;
  const drawdownScale=clamp(1-input.currentDrawdown/input.maxDrawdown,0,1);
  const allocatedFraction=clamp(rawKellyFraction*input.fraction*drawdownScale,0,input.maxFraction);
  return{rawKellyFraction,allocatedFraction,expectedReturn,variance:returnVariance,drawdownScale};
}
