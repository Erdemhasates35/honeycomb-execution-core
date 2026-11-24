import { assertPositive } from "./math.js";

export interface VenueQuote {
  venue: string;
  bid: number;
  ask: number;
  feeBps: number;
  slippageBps: number;
  latencyMs: number;
}

export interface CrossVenueBasisSignal {
  side: "BUY_LEFT_SELL_RIGHT" | "BUY_RIGHT_SELL_LEFT" | "FLAT";
  buyVenue: string | null;
  sellVenue: string | null;
  grossEdgeBps: number;
  netEdgeBps: number;
  reasonCode: string;
}

export function evaluateCrossVenueBasis(left:VenueQuote,right:VenueQuote,config:{minNetEdgeBps:number;latencyPenaltyBpsPerSecond:number}):CrossVenueBasisSignal{
  for(const quote of [left,right]){
    assertPositive(quote.bid,"venueBid");
    assertPositive(quote.ask,"venueAsk");
    if(quote.ask<quote.bid||quote.feeBps<0||quote.slippageBps<0||quote.latencyMs<0)throw new Error("Cross venue quote is invalid");
  }
  const buyLeftGross=(right.bid-left.ask)/((right.bid+left.ask)/2)*10000;
  const buyRightGross=(left.bid-right.ask)/((left.bid+right.ask)/2)*10000;
  if (!Number.isFinite(config.minNetEdgeBps) || config.minNetEdgeBps < 0 || !Number.isFinite(config.latencyPenaltyBpsPerSecond) || config.latencyPenaltyBpsPerSecond < 0) throw new Error("Cross venue cost policy is invalid");
  const leftLatency=left.latencyMs/1000*config.latencyPenaltyBpsPerSecond;
  const rightLatency=right.latencyMs/1000*config.latencyPenaltyBpsPerSecond;
  const buyLeftNet=buyLeftGross-left.feeBps-right.feeBps-left.slippageBps-right.slippageBps-leftLatency-rightLatency;
  const buyRightNet=buyRightGross-left.feeBps-right.feeBps-left.slippageBps-right.slippageBps-leftLatency-rightLatency;
  if(buyLeftNet>=buyRightNet&&buyLeftNet>=config.minNetEdgeBps)return{side:"BUY_LEFT_SELL_RIGHT",buyVenue:left.venue,sellVenue:right.venue,grossEdgeBps:buyLeftGross,netEdgeBps:buyLeftNet,reasonCode:"net_cross_venue_edge_positive"};
  if(buyRightNet>buyLeftNet&&buyRightNet>=config.minNetEdgeBps)return{side:"BUY_RIGHT_SELL_LEFT",buyVenue:right.venue,sellVenue:left.venue,grossEdgeBps:buyRightGross,netEdgeBps:buyRightNet,reasonCode:"net_cross_venue_edge_positive"};
  return{side:"FLAT",buyVenue:null,sellVenue:null,grossEdgeBps:Math.max(buyLeftGross,buyRightGross),netEdgeBps:Math.max(buyLeftNet,buyRightNet),reasonCode:"cross_venue_edge_below_cost_floor"};
}
