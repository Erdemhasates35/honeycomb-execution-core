#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
α-Agent 05 — Funding-Rate Capture Agent
Academic: Perpetual futures funding rate arbitrage literature
(BitMEX, Binance research + academic funding premium papers)
Captures positive expected funding when rate is extreme and direction aligned.
Zero extra infrastructure cost.
"""
from __future__ import annotations
import os
from typing import Dict, Any, Optional, Tuple

FUNDING_THRESHOLD = float(os.getenv("FUNDING_CAPTURE_THRESHOLD", "0.0008"))  # 0.08%
FUNDING_EXTREME = float(os.getenv("FUNDING_EXTREME", "0.0015"))             # 0.15%
MIN_HOLD_HOURS = float(os.getenv("FUNDING_MIN_HOLD_H", "4.0"))

def funding_signal(
    symbol: str,
    current_funding_rate: float,
    predicted_next_funding: float,
    side_bias: str,  # "LONG" or "SHORT" from scanner
) -> Dict[str, Any]:
    """
    Returns structured funding opportunity.
    positive funding → longs pay shorts → prefer SHORT
    negative funding → shorts pay longs → prefer LONG
    """
    rate = float(current_funding_rate)
    pred = float(predicted_next_funding)
    avg = (rate + pred) / 2.0

    preferred_side = "SHORT" if avg > 0 else "LONG"
    magnitude = abs(avg)
    extreme = magnitude >= FUNDING_EXTREME
    actionable = magnitude >= FUNDING_THRESHOLD

    aligned = (preferred_side == side_bias)

    score = 0.0
    if actionable:
        score = min(100.0, (magnitude / FUNDING_EXTREME) * 70.0)
        if extreme:
            score += 20.0
        if aligned:
            score += 10.0

    return {
        "symbol": symbol,
        "funding_rate": round(rate, 6),
        "predicted": round(pred, 6),
        "avg": round(avg, 6),
        "preferred_side": preferred_side,
        "aligned": aligned,
        "extreme": extreme,
        "actionable": actionable,
        "score": round(score, 2),
        "min_hold_hours": MIN_HOLD_HOURS,
    }

def should_capture_funding(
    funding_info: Dict[str, Any],
    scanner_side: str,
    quality: float,
) -> Tuple[bool, str]:
    """
    Final decision gate.
    Only capture when funding edge is real AND scanner agrees or extreme.
    """
    if not funding_info.get("actionable"):
        return False, "FUNDING_TOO_LOW"
    if funding_info["extreme"] and funding_info["score"] >= 80:
        return True, "EXTREME_FUNDING"
    if funding_info["aligned"] and quality >= 70 and funding_info["score"] >= 55:
        return True, "ALIGNED_FUNDING"
    return False, "NO_CAPTURE"

# Self-test
if __name__ == "__main__":
    info = funding_signal("BTCUSDT", 0.0012, 0.0011, "SHORT")
    assert info["preferred_side"] == "SHORT"
    ok, reason = should_capture_funding(info, "SHORT", 78.0)
    assert ok is True
    print("PASS", info, reason)
