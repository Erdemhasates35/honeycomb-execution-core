import { assertPositive } from "./math.js";
import type { TradePrint } from "./types.js";

export interface VolumeBucket {
  startTime: number;
  endTime: number;
  volume: number;
}

export interface VwapExecutionPlan {
  accepted: boolean;
  vwap: number;
  participationRate: number;
  slices: Array<{ startTime: number; endTime: number; quantity: number; limitPrice: number }>;
  reasonCode: string;
}

export function buildVwapExecutionPlan(input: {
  side: "BUY" | "SELL";
  targetQuantity: number;
  trades: TradePrint[];
  buckets: VolumeBucket[];
  maxParticipationRate: number;
  limitOffsetBps: number;
}): VwapExecutionPlan {
  assertPositive(input.targetQuantity,"targetQuantity");
  if (input.trades.length===0 || input.buckets.length===0 || input.maxParticipationRate<=0 || input.maxParticipationRate>1 || input.limitOffsetBps<0) throw new Error("VWAP execution inputs are invalid");
  const totalQuantity=input.trades.reduce((sum,trade)=>sum+trade.quantity,0);
  const totalNotional=input.trades.reduce((sum,trade)=>sum+trade.price*trade.quantity,0);
  if (!Number.isFinite(totalQuantity)||totalQuantity<=0||!Number.isFinite(totalNotional)||totalNotional<=0) throw new Error("VWAP trade history is invalid");
  const vwap=totalNotional/totalQuantity;
  const participationRate=input.targetQuantity/totalQuantity;
  const limitPrice=vwap*(input.side==="BUY"?1-input.limitOffsetBps/10000:1+input.limitOffsetBps/10000);
  const ordered=[...input.buckets].sort((a,b)=>a.startTime-b.startTime);
  if (ordered.some(bucket=>!Number.isFinite(bucket.volume)||bucket.volume<0||bucket.endTime<=bucket.startTime)) throw new Error("VWAP volume buckets are invalid");
  const slices:Array<{startTime:number;endTime:number;quantity:number;limitPrice:number}>=[];
  let remaining=input.targetQuantity;
  for(const bucket of ordered){
    const capacity=bucket.volume*input.maxParticipationRate;
    const quantity=Math.min(remaining,capacity);
    if(quantity>0){
      slices.push({startTime:bucket.startTime,endTime:bucket.endTime,quantity,limitPrice});
      remaining-=quantity;
    }
    if(remaining<=Math.max(1e-12,input.targetQuantity*1e-10)) break;
  }
  if(remaining>Math.max(1e-12,input.targetQuantity*1e-10)) return {accepted:false,vwap,participationRate,slices:[],reasonCode:"insufficient_participation_capacity"};
  const allocated=slices.reduce((sum,slice)=>sum+slice.quantity,0);
  if(Math.abs(allocated-input.targetQuantity)>Math.max(1e-10,input.targetQuantity*1e-8)) return {accepted:false,vwap,participationRate,slices:[],reasonCode:"slice_quantity_reconciliation_failed"};
  return {accepted:true,vwap,participationRate,slices,reasonCode:"vwap_plan_with_participation_cap"};
}
