#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
α-Agent 07 — Multi-Venue Micro-Arb Agent
Academic: Cross-exchange microstructure arbitrage (latency + fee aware)
Detects small price dislocations between Binance / Bitget (or other venues)
that survive after fees + slippage.
Pure production signal generator — execution left to existing engine.
"""
from __future__ import annotations
import os
from typing import Dict, Any, Optional, Tuple, List

MIN_ARB_BPS = float(os.getenv("MICRO_ARB_MIN_BPS", "4.5"))   # after fees
FEE_BPS_ROUNDTRIP = float(os.getenv("MICRO_ARB_FEE_BPS", "8.0"))  # both sides
MAX_SIZE_USDT = float(os.getenv("MICRO_ARB_MAX_USDT", "180.0"))

def micro_arb_opportunity(
    symbol: str,
    venue_a_bid: float,
    venue_a_ask: float,
    venue_b_bid: float,
    venue_b_ask: float,
    venue_a_name: str = "BINANCE",
    venue_b_name: str = "BITGET",
) -> Optional[Dict[str, Any]]:
    """
    Detects two classic micro-arb legs:
    1. Buy A / Sell B  if B_bid - A_ask > fees
    2. Buy B / Sell A  if A_bid - B_ask > fees
    Returns None if no edge after costs.
    """
    if min(venue_a_bid, venue_a_ask, venue_b_bid, venue_b_ask) <= 0:
        return None

    # Leg 1: buy on A, sell on B
    edge1 = (venue_b_bid - venue_a_ask) / venue_a_ask * 10000.0  # bps
    net1 = edge1 - FEE_BPS_ROUNDTRIP

    # Leg 2: buy on B, sell on A
    edge2 = (venue_a_bid - venue_b_ask) / venue_b_ask * 10000.0
    net2 = edge2 - FEE_BPS_ROUNDTRIP

    best_net = max(net1, net2)
    if best_net < MIN_ARB_BPS:
        return None

    if net1 >= net2:
        direction = "BUY_A_SELL_B"
        buy_venue, sell_venue = venue_a_name, venue_b_name
        buy_px, sell_px = venue_a_ask, venue_b_bid
        raw_edge = edge1
    else:
        direction = "BUY_B_SELL_A"
        buy_venue, sell_venue = venue_b_name, venue_a_name
        buy_px, sell_px = venue_b_ask, venue_a_bid
        raw_edge = edge2

    return {
        "symbol": symbol,
        "direction": direction,
        "buy_venue": buy_venue,
        "sell_venue": sell_venue,
        "buy_px": round(buy_px, 6),
        "sell_px": round(sell_px, 6),
        "raw_edge_bps": round(raw_edge, 3),
        "net_edge_bps": round(best_net, 3),
        "max_size_usdt": MAX_SIZE_USDT,
        "score": round(min(100.0, best_net * 8.0), 2),
    }

def execute_micro_arb_signal(opp: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts opportunity into a normalized signal the existing engine can consume.
    Does NOT place orders — only produces the signal object.
    """
    return {
        "type": "MICRO_ARB",
        "symbol": opp["symbol"],
        "side": "LONG" if "BUY_A" in opp["direction"] or "BUY_B" in opp["direction"] else "SHORT",
        "urgency": "HIGH",
        "size_usdt": opp["max_size_usdt"],
        "edge_bps": opp["net_edge_bps"],
        "meta": opp,
    }

# Self-test
if __name__ == "__main__":
    opp = micro_arb_opportunity(
        "BTCUSDT",
        venue_a_bid=67400.0, venue_a_ask=67405.0,
        venue_b_bid=67455.0, venue_b_ask=67460.0,
    )
    assert opp is not None
    assert opp["net_edge_bps"] > 0
    sig = execute_micro_arb_signal(opp)
    print("PASS", opp["net_edge_bps"], sig["type"])
