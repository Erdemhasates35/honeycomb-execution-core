#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
α-Agent 02 — Correlation-Kill Engine
Academic: Portfolio concentration & correlation risk (Markowitz + risk-parity)
Hard blocks same-direction clusters and high-beta pairs.
"""
from __future__ import annotations
import os
from typing import List, Tuple, Set, Dict, Any

CORR_GROUPS: List[Set[str]] = [
    {"BTCUSDT", "ETHUSDT"},
    {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"},
    {"SOLUSDT", "AVAXUSDT", "NEARUSDT", "SUIUSDT"},
    {"DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "WIFUSDT"},
    {"XRPUSDT", "ADAUSDT", "DOTUSDT", "LINKUSDT"},
    {"ARBUSDT", "OPUSDT", "MATICUSDT"},
]
MAX_SAME_SIDE = int(os.getenv("CORR_MAX_SAME_SIDE", "4"))
MAX_TOTAL_POSITIONS = int(os.getenv("CORR_MAX_TOTAL", "7"))
MAX_GROUP_EXPOSURE = int(os.getenv("CORR_MAX_GROUP", "2"))

def correlation_blocked(symbol: str, side: str,
                        open_positions: List[Tuple[str, str]]) -> Tuple[bool, str]:
    if len(open_positions) >= MAX_TOTAL_POSITIONS:
        return True, f"MAX_TOTAL_{MAX_TOTAL_POSITIONS}"
    same_side = sum(1 for _, s in open_positions if s == side)
    if same_side >= MAX_SAME_SIDE:
        return True, f"MAX_SAME_SIDE_{MAX_SAME_SIDE}"
    for group in CORR_GROUPS:
        if symbol not in group:
            continue
        group_count = sum(1 for s, _ in open_positions if s in group)
        if group_count >= MAX_GROUP_EXPOSURE:
            return True, f"GROUP_EXPOSURE_{group_count}"
    if any(s == symbol and sd != side for s, sd in open_positions):
        return True, "ALREADY_OPEN_OPPOSITE"
    return False, "OK"

def portfolio_heat(open_positions: List[Tuple[str, str]]) -> Dict[str, Any]:
    long_n = sum(1 for _, s in open_positions if s == "LONG")
    short_n = sum(1 for _, s in open_positions if s == "SHORT")
    groups_hit = sum(1 for g in CORR_GROUPS if any(s in g for s, _ in open_positions))
    return {"total": len(open_positions), "long": long_n, "short": short_n,
            "groups_hit": groups_hit, "heat": round(len(open_positions) / MAX_TOTAL_POSITIONS, 3)}

if __name__ == "__main__":
    pos = [("BTCUSDT", "LONG"), ("ETHUSDT", "LONG")]
    blocked, reason = correlation_blocked("BNBUSDT", "LONG", pos)
    assert blocked is True
    print("PASS", reason, portfolio_heat(pos))
