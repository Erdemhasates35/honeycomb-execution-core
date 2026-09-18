#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""HONEYCOMB PROTECTION BRIDGE — exchange-state protection reconciler."""
from __future__ import annotations
from typing import Any, Dict, Optional
from live.kernel import LiveKernel

class ProtectionBridge:
    def __init__(self, kernel: LiveKernel, log_fn=None):
        self.kernel = kernel
        self.log = log_fn or (lambda m: None)

    def protect(self, symbol: str, side: str, entry: float, tp: float, sl: float,
                position_side: Optional[str] = None) -> Dict[str, Any]:
        result = self.kernel.place_protect(symbol, side, entry, tp, sl, position_side)
        self.log("PROTECTED %s %s tp=%s sl=%s" % (symbol, side, result["tp"], result["sl"]))
        return result

    def reconcile_position(self, symbol: str, tp: float, sl: float,
                           position_side: Optional[str] = None) -> Dict[str, Any]:
        rows = self.kernel.position_rows(symbol)
        active = [p for p in rows if abs(float(p.get("positionAmt") or 0)) > 0]
        if not active:
            return {"symbol": symbol, "active": False, "action": "none"}
        p = active[0]
        amt = float(p.get("positionAmt") or 0)
        side = "LONG" if amt > 0 else "SHORT"
        entry = float(p.get("entryPrice") or 0)
        if entry <= 0:
            raise RuntimeError("invalid exchange entry price for " + symbol)
        ps = position_side if position_side in ("LONG", "SHORT") else (side if self.kernel.hedge_mode else None)
        self.kernel.cancel_all(symbol)
        result = self.protect(symbol, side, entry, tp, sl, ps)
        return {"symbol": symbol, "active": True, "side": side, "entry": entry, **result}

    def emergency_flatten(self, symbol: str, side: str, qty: float,
                          position_side: Optional[str] = None) -> Dict[str, Any]:
        self.kernel.cancel_all(symbol)
        fill = self.kernel.close_market(symbol, side, qty, position_side)
        if fill.get("avg") is None or fill.get("commission") is None:
            raise RuntimeError("flatten fill not reconciled")
        return fill
