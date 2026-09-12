# -*- coding: utf-8 -*-
"""
HONEYCOMB LIVE PROTECTION BRIDGE
Preserves existing LiveKernel and redirects conditional protection
to Binance Futures Algo Order API.

No mock orders.
No simulated fills.
No retry/replay of ambiguous live orders.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from live.kernel import LiveKernel


def _venue_base(kernel: LiveKernel) -> str:
    venue = str(getattr(kernel, "venue", "usdt")).lower()

    if venue in ("coin", "coinm", "coin-m", "dapi"):
        return "https://dapi.binance.com"

    return "https://fapi.binance.com"


def _algo_endpoint(kernel: LiveKernel) -> str:
    return _venue_base(kernel) + "/fapi/v1/algoOrder" \
        if _venue_base(kernel).startswith("https://fapi") \
        else _venue_base(kernel) + "/dapi/v1/algoOrder"


def _cancel_algo_endpoint(kernel: LiveKernel) -> str:
    return _venue_base(kernel) + "/fapi/v1/algoOpenOrders" \
        if _venue_base(kernel).startswith("https://fapi") \
        else _venue_base(kernel) + "/dapi/v1/algoOpenOrders"


def _call(kernel: LiveKernel, method: str, params: dict[str, Any]):
    endpoint = _algo_endpoint(kernel)

    return kernel._http(
        method,
        endpoint,
        params,
        signed=True,
        weight=1,
    )


def _safe_client_id(prefix: str) -> str:
    return (
        prefix[:8]
        + "_"
        + str(int(time.time() * 1000))[-10:]
        + "_"
        + uuid.uuid4().hex[:8]
    )[:32]


def _bridge_place_protect(
    self: LiveKernel,
    symbol,
    side,
    qty,
    tp,
    sl,
    position_side=None,
    working_type="MARK_PRICE",
    **kwargs,
):
    symbol = str(symbol).upper()
    side = str(side).upper()

    if side == "BUY":
        exit_side = "SELL"
    else:
        exit_side = "BUY"

    ps = position_side or kwargs.get("positionSide") or "BOTH"

    results = {}

    common = {
        "symbol": symbol,
        "side": exit_side,
        "positionSide": ps,
        "workingType": working_type,
        "closePosition": "true",
        "algoType": "CONDITIONAL",
    }

    if tp is not None:
        tp_params = dict(common)
        tp_params.update({
            "type": "TAKE_PROFIT_MARKET",
            "triggerPrice": str(tp),
            "clientAlgoId": _safe_client_id("HCTP"),
        })

        try:
            results["tp"] = _call(self, "POST", tp_params)
            self.log(
                "ALGO PROTECT TP %s %s trigger=%s"
                % (symbol, exit_side, tp)
            )
        except Exception as e:
            self.log(
                "ALGO PROTECT TP FAIL %s: %s"
                % (symbol, e)
            )

    if sl is not None:
        sl_params = dict(common)
        sl_params.update({
            "type": "STOP_MARKET",
            "triggerPrice": str(sl),
            "clientAlgoId": _safe_client_id("HCSL"),
        })

        try:
            results["sl"] = _call(self, "POST", sl_params)
            self.log(
                "ALGO PROTECT SL %s %s trigger=%s"
                % (symbol, exit_side, sl)
            )
        except Exception as e:
            self.log(
                "ALGO PROTECT SL FAIL %s: %s"
                % (symbol, e)
            )

    return results


LiveKernel.place_protect = _bridge_place_protect
