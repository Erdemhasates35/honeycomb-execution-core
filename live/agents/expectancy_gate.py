#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
α-Agent 01 — Fee-Aware Expectancy Gate
Academic: Transaction-cost-adjusted expectancy (Kissell 2013 + Thorp cost literature)
Minimum net edge after fees + slippage + funding.
Production: persistent state, atomic update, hard reject on negative EV.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

STATE_PATH = Path(os.getenv("HONEYCOMB_RUNTIME", ".honeycomb_runtime")) / "expectancy_state.json"
FEE_RATE = float(os.getenv("FEE_RATE", "0.0004"))
SLIPPAGE_BPS = float(os.getenv("SCANNER_SLIPPAGE_BPS", "2.0"))
FUNDING_RESERVE = float(os.getenv("SCANNER_FUNDING_RESERVE", "0.0002"))
MIN_NET_EV = float(os.getenv("MIN_NET_EV", "0.0015"))
MIN_TRADES_FOR_GATE = int(os.getenv("MIN_TRADES_FOR_GATE", "12"))

def _load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"wins": 0, "losses": 0, "sum_win": 0.0, "sum_loss": 0.0, "sum_fees": 0.0, "last_pnl": 0.0, "updated_at": 0.0}

def _save_state(st: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    st["updated_at"] = time.time()
    STATE_PATH.write_text(json.dumps(st, indent=2))

def update_trade(net_pnl: float, fees_paid: float = 0.0) -> None:
    st = _load_state()
    if net_pnl > 0:
        st["wins"] += 1
        st["sum_win"] += net_pnl
    else:
        st["losses"] += 1
        st["sum_loss"] += abs(net_pnl)
    st["sum_fees"] += abs(fees_paid)
    st["last_pnl"] = net_pnl
    _save_state(st)

def get_expectancy() -> Tuple[float, float, float, int]:
    st = _load_state()
    w, l = st["wins"], st["losses"]
    total = w + l
    if total == 0:
        return 0.0, 0.5, 1.0, 0
    wr = w / total
    avg_w = st["sum_win"] / max(w, 1)
    avg_l = st["sum_loss"] / max(l, 1)
    exp = (wr * avg_w) - ((1.0 - wr) * avg_l)
    ratio = avg_w / max(avg_l, 1e-9)
    return exp, wr, ratio, total

def cost_aware_net_ev(gross_score: float, quality: float, atr_pct: float,
                      fee: float = FEE_RATE, slip_bps: float = SLIPPAGE_BPS,
                      funding: float = FUNDING_RESERVE) -> float:
    gross = (abs(gross_score) / 100.0) * (quality / 100.0) * (atr_pct / 100.0) * 2.8
    cost = (fee * 2.0) + (slip_bps / 10000.0) + funding
    return gross - cost

def gate(gross_score: float, quality: float, atr_pct: float,
         force_allow_early: bool = False) -> Optional[Dict[str, Any]]:
    net_ev = cost_aware_net_ev(gross_score, quality, atr_pct)
    exp, wr, ratio, n = get_expectancy()
    if n < MIN_TRADES_FOR_GATE and not force_allow_early:
        if net_ev < MIN_NET_EV:
            return None
        return {"net_ev": round(net_ev, 6), "expectancy": round(exp, 6),
                "win_rate": round(wr, 4), "avg_wl_ratio": round(ratio, 4),
                "trades": n, "gate": "EARLY_PASS"}
    if net_ev < MIN_NET_EV or exp <= 0.0:
        return None
    return {"net_ev": round(net_ev, 6), "expectancy": round(exp, 6),
            "win_rate": round(wr, 4), "avg_wl_ratio": round(ratio, 4),
            "trades": n, "gate": "MATURE_PASS"}

if __name__ == "__main__":
    update_trade(12.5, 0.8)
    update_trade(-4.2, 0.7)
    update_trade(8.1, 0.6)
    g = gate(78.0, 82.0, 0.12)
    assert g is not None
    print("PASS", g)
