import { assertPositive } from "./math.js";

export interface AvellanedaStoikovQuote {
  reservationPrice: number;
  bidPrice: number;
  askPrice: number;
  optimalSpread: number;
}

export function calculateAvellanedaStoikovQuote(input:{
  midPrice:number;
  volatility:number;
  inventory:number;
  riskAversion:number;
  liquidityParameter:number;
  horizon:number;
  tickSize:number;
}):AvellanedaStoikovQuote{
  assertPositive(input.midPrice,"midPrice");
  assertPositive(input.volatility,"volatility");
  assertPositive(input.riskAversion,"riskAversion");
  assertPositive(input.liquidityParameter,"liquidityParameter");
  assertPositive(input.horizon,"horizon");
  assertPositive(input.tickSize,"tickSize");
  const variance=input.volatility**2;
  const reservationPrice=input.midPrice-input.inventory*input.riskAversion*variance*input.horizon;
  const optimalSpread=input.riskAversion*variance*input.horizon+(2/input.riskAversion)*Math.log(1+input.riskAversion/input.liquidityParameter);
  const bidPrice=Math.floor((reservationPrice-optimalSpread/2)/input.tickSize)*input.tickSize;
  const askPrice=Math.ceil((reservationPrice+optimalSpread/2)/input.tickSize)*input.tickSize;
  if(!(bidPrice>0&&askPrice>bidPrice))throw new Error("Avellaneda-Stoikov quote is invalid");
  return{reservationPrice,bidPrice,askPrice,optimalSpread};
}
