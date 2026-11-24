export interface ReconciliationTrade {
  quantity: number;
  price: number;
  fee: number;
  realizedPnl: number;
  tradeId: string;
}

export interface ReconciliationResult {
  reconciled: boolean;
  executedQuantity: number;
  averagePrice: number | null;
  totalFees: number;
  realizedPnl: number;
  discrepancyQuantity: number;
  missingTradeIds: string[];
}

export function reconcileExecutionEvents(input:{exchangeExecutedQuantity:number;trades:ReconciliationTrade[];knownTradeIds?:string[];tolerance:number}):ReconciliationResult{
  if(!Number.isFinite(input.exchangeExecutedQuantity)||input.exchangeExecutedQuantity<0||!Number.isFinite(input.tolerance)||input.tolerance<0)throw new Error("Execution reconciliation input is invalid");
  if(input.trades.some(trade=>!Number.isFinite(trade.quantity)||trade.quantity<=0||!Number.isFinite(trade.price)||trade.price<=0||!Number.isFinite(trade.fee)||!Number.isFinite(trade.realizedPnl)||!trade.tradeId))throw new Error("Execution trade event is invalid");
  const tradeIds=input.trades.map(trade=>trade.tradeId);
  if(new Set(tradeIds).size!==tradeIds.length)throw new Error("Execution reconciliation contains duplicate trade IDs");
  const executedQuantity=input.trades.reduce((sum,trade)=>sum+trade.quantity,0);
  const totalNotional=input.trades.reduce((sum,trade)=>sum+trade.quantity*trade.price,0);
  const totalFees=input.trades.reduce((sum,trade)=>sum+trade.fee,0);
  const realizedPnl=input.trades.reduce((sum,trade)=>sum+trade.realizedPnl,0);
  const discrepancyQuantity=Math.abs(input.exchangeExecutedQuantity-executedQuantity);
  const known=new Set(input.knownTradeIds??[]);
  const missingTradeIds=input.trades.map(trade=>trade.tradeId).filter(id=>!known.has(id));
  return{reconciled:discrepancyQuantity<=input.tolerance,executedQuantity,averagePrice:executedQuantity>0?totalNotional/executedQuantity:null,totalFees,realizedPnl,discrepancyQuantity,missingTradeIds};
}
