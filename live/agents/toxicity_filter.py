#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
α-Agent 06 — Order-Flow Toxicity Filter
Academic: VPIN / Order Flow Toxicity (Easley, López de Prado, O’Hara 2012)
+ modern microstructure toxicity proxies.
Rejects entries when flow is toxic (informed flow against us).
"""
from __future__ import annotations
import os
from typing import Dict, Any, List, Tuple

TOXICITY_HARD = float(os.getenv("TOXICITY_HARD", "0.72"))
TOXICITY_SOFT = float(os.getenv("TOXICITY_SOFT", "0.55"))

def toxicity_score(
    buy_volume: float,
    sell_volume: float,
    trade_count: int,
    spread_bps: float,
    atr_pct: float,
    imbalance_1m: float = 0.0,
) -> Dict[str, float]:
    """
    Simple but robust toxicity proxy.
    High absolute imbalance + wide spread + high ATR → toxic.
    """
    total = buy_volume + sell_volume + 1e-9
    imbalance = abs(buy_volume - sell_volume) / total
    # normalize components 0-1
    imb_s = min(1.0, imbalance * 1.8)
    spread_s = min(1.0, spread_bps / 25.0)
    atr_s = min(1.0, atr_pct / 0.35)
    count_s = min(1.0, trade_count / 120.0)

    # VPIN-style weight
    score = (imb_s * 0.45 + spread_s * 0.25 + atr_s * 0.20 + (1.0 - count_s) * 0.10)
    score = max(0.0, min(1.0, score + abs(imbalance_1m) * 0.15))

    return {
        "toxicity": round(score, 4),
        "imbalance": round(imbalance, 4),
        "spread_s": round(spread_s, 4),
        "atr_s": round(atr_s, 4),
    }

def toxicity_blocked(
    buy_volume: float,
    sell_volume: float,
    trade_count: int,
    spread_bps: float,
    atr_pct: float,
    side: str,
    imbalance_1m: float = 0.0,
) -> Tuple[bool, str, Dict[str, float]]:
    """
    Returns (blocked, reason, metrics)
    blocked=True → REJECT.
    Also detects adverse selection direction.
    """
    m = toxicity_score(buy_volume, sell_volume, trade_count, spread_bps, atr_pct, imbalance_1m)
    tox = m["toxicity"]

    if tox >= TOXICITY_HARD:
        return True, f"TOXIC_HARD_{tox:.3f}", m

    # adverse direction check
    if side == "LONG" and buy_volume < sell_volume * 0.65 and tox >= TOXICITY_SOFT:
        return True, f"ADVERSE_SELL_FLOW_{tox:.3f}", m
    if side == "SHORT" and sell_volume < buy_volume * 0.65 and tox >= TOXICITY_SOFT:
        return True, f"ADVERSE_BUY_FLOW_{tox:.3f}", m

    if tox >= TOXICITY_SOFT:
        return False, f"SOFT_TOXIC_{tox:.3f}", m  # allow but reduce size upstream

    return False, "OK", m

# Self-test
if __name__ == "__main__":
    blocked, reason, m = toxicity_blocked(1200, 3800, 45, 18.0, 0.22, "LONG")
    assert blocked is True
    print("PASS", reason, m)
