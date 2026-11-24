export interface HawkesEvent {
  timestamp: number;
  side: "BUY" | "SELL";
}

export interface HawkesToxicity {
  buyIntensity: number;
  sellIntensity: number;
  toxicity: number;
  dominantSide: "BUY" | "SELL" | "BALANCED";
  pauseMarketMaking: boolean;
}

export function estimateHawkesToxicity(events:HawkesEvent[],input:{now:number;baselineIntensity:number;excitation:number;decayPerSecond:number;toxicityThreshold:number}):HawkesToxicity{
  if(!Number.isFinite(input.now)||input.baselineIntensity<=0||input.excitation<0||input.decayPerSecond<=0||input.toxicityThreshold<0||input.toxicityThreshold>1)throw new Error("Hawkes model parameters are invalid");
  let buy=input.baselineIntensity;
  let sell=input.baselineIntensity;
  for(const event of events){
    if(!Number.isFinite(event.timestamp)||event.timestamp>input.now)throw new Error("Hawkes event time is invalid");
    const ageSeconds=(input.now-event.timestamp)/1000;
    const excitation=input.excitation*Math.exp(-input.decayPerSecond*ageSeconds);
    if(event.side==="BUY")buy+=excitation;else sell+=excitation;
  }
  const total=buy+sell;
  const toxicity=Math.abs(buy-sell)/total;
  const dominantSide=buy>sell?"BUY":sell>buy?"SELL":"BALANCED";
  return{buyIntensity:buy,sellIntensity:sell,toxicity,dominantSide,pauseMarketMaking:toxicity>=input.toxicityThreshold};
}
